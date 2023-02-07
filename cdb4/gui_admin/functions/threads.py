"""This module contains operations that relate to time consuming
processes like installation or mainly refresh views.

The purpose of this module is to hint the user that a heavy process is
running in the background, so that they don't think that the plugin crashed,
or froze.

The plugin runs on single thread, meaning that in such processes the plugin
'freezes' until completion. But without warning or visual cue the user could
think that it broke.

To avoid this module provides two visuals cues.
1. Progress bar.
2. Disabling the entire plugin (gray-out to ignore signals from panic clicking)

This is done by assigning a working thread for the
heavy process. In the main thread the progress bar is assigned to
update following the heavy process taking place in the worker thread.
"""
import os

from qgis.PyQt.QtCore import QObject, QThread, pyqtSignal
from qgis.core import Qgis, QgsMessageLog
import psycopg2, psycopg2.sql as pysql

from ....cdb_tools_main import CDBToolsMain # Used only to add the type of the function parameters

from ...gui_db_connector.functions import conn_functions as conn_f
from ...shared.functions import sql as sh_sql, general_functions as gen_f

from ..other_classes import FeatureType
from .. import admin_constants as c

from . import sql
from . import tab_install_widget_functions as ti_wf

FILE_LOCATION = gen_f.get_file_relative_path(file=__file__)

#####################################################################################
##### QGIS PACKAGE INSTALL ##########################################################
#####################################################################################

def run_install_qgis_pkg_thread(cdbMain: CDBToolsMain, sql_scripts_path: str, qgis_pkg_schema: str) -> None:
    """Function that installs the plugin package (qgis_pkg) in the database
    by branching a new Worker thread to execute the operation on.

    *   :param path: The relative path to the directory storing the
            SQL installation scripts (e.g. ./cdb_loader/cdb4/ddl_scripts/postgresql)
        :type path: str
    
    *   :param pkg: The package (schema) name that's installed
        :type pkg: str
    """
    dlg = cdbMain.admin_dlg

    if qgis_pkg_schema == cdbMain.QGIS_PKG_SCHEMA:
        # Add a new progress bar to follow the installation procedure.
        cdbMain.create_progress_bar(dialog=dlg, layout=dlg.vLayoutMainInst, position=-1)

    # Create new thread object.
    cdbMain.thread = QThread()
    # Instantiate worker object for the operation.
    cdbMain.worker = QgisPackageInstallWorker(cdbMain, sql_scripts_path)
    # Move worker object to be executed on the new thread.
    cdbMain.worker.moveToThread(cdbMain.thread)

    #-SIGNALS--(start)--################################################################
    # Anti-panic clicking: Disable widgets to avoid queuing signals.
    # ...

    # Execute worker's 'run' method.
    cdbMain.thread.started.connect(cdbMain.worker.install_thread)

    # Capture progress to show in bar.
    cdbMain.worker.sig_progress.connect(cdbMain.evt_update_bar)

    # Get rid of worker and thread objects.
    cdbMain.worker.sig_finished.connect(cdbMain.thread.quit)
    cdbMain.worker.sig_finished.connect(cdbMain.worker.deleteLater)
    cdbMain.thread.finished.connect(cdbMain.thread.deleteLater)

    # Reenable the GUI
    cdbMain.thread.finished.connect(dlg.msg_bar.clearWidgets)

    # On installation status
    cdbMain.worker.sig_success.connect(lambda: ev_qgis_pkg_install_success(cdbMain, qgis_pkg_schema))
    cdbMain.worker.sig_fail.connect(lambda: ev_qgis_pkg_install_fail(cdbMain, qgis_pkg_schema))
    #-SIGNALS--(end)---################################################################

    # Initiate worker thread
    cdbMain.thread.start()


class QgisPackageInstallWorker(QObject):
    """Class to assign Worker that executes the 'installation scripts'
    to install the QGIS Package (qgis_pkg) into the database.
    """
    # Create custom signals.
    sig_finished = pyqtSignal()
    sig_progress = pyqtSignal(str, int, str)
    sig_success = pyqtSignal()
    sig_fail = pyqtSignal()

    def __init__(self, cdbMain: CDBToolsMain, sql_scripts_path):
        super().__init__()
        self.plugin = cdbMain
        self.sql_scripts_path = sql_scripts_path

    def install_thread(self) -> None:
        """Execution method that installs the qgis_pkg. SQL scripts are run
        directly using the execution method. No psql app needed.
        """
        # Procedure overview:
        # 1) Install the ddl scripts in numbered order (from 010 onwards)
        # 2) Check the Settings (Default Users). If enabled, follow the choices set there
            # - Install the selected default user(s) (qgis_user_ro, qgis_user_rw)
            # - create their user_schemas
        # 3) If required, grant them (default) privileges: ro or rw on all existing cdb_schemas

        dlg = self.plugin.admin_dlg

        # Flag to help us break from a failing installation.
        fail_flag: bool = False

        # Get an alphabetical ordered list of the script names. Important: Keep the order with number prefixes.
        install_scripts: list = sorted(os.listdir(self.sql_scripts_path))

        # Check that we read some files!
        if not install_scripts:
            fail_flag = True
            self.sig_fail.emit()
            self.sig_finished.emit()
            return None
        else:
            install_scripts_num = len(install_scripts)

        # Check the Settings (Default Users)
        install_users_num = 0
        set_privileges_num = 0
        def_usr_name_suffixes = []
        def_usr_access_suffixes = []

        if dlg.gbxDefaultUsers.isEnabled():
            if dlg.ckbUserRO.isChecked():
                def_usr_name_suffixes.append('ro')
                install_users_num += 1
                if dlg.ckbUserROAccess.isChecked():
                    def_usr_access_suffixes.append('ro')
                    set_privileges_num += 1
            if dlg.ckbUserRW.isChecked():
                def_usr_name_suffixes.append('rw')
                install_users_num += 1
                if dlg.ckbUserRWAccess.isChecked():
                    def_usr_access_suffixes.append('rw')
                    set_privileges_num += 1

        # Set progress bar goal
        steps_tot = install_scripts_num + install_users_num + set_privileges_num
        self.plugin.admin_dlg.bar.setMaximum(steps_tot)

        curr_step: int = 0

        try:
            # Open new temp session, reserved for installation.
            temp_conn = conn_f.create_db_connection(db_connection=self.plugin.DB, app_name=" ".join([self.plugin.PLUGIN_NAME_ADMIN, "(QGIS Package Installation)"]))
            with temp_conn:

                # 1) Install the DDL scripts
                for script in install_scripts:

                    # Update progress bar
                    msg = f"Installing: '{script}'"
                    curr_step += 1
                    self.sig_progress.emit(self.plugin.DLG_NAME_ADMIN, curr_step, msg)

                    try:
                        with temp_conn.cursor() as cur:
                            with open(os.path.join(self.sql_scripts_path, script), "r") as sql_script:
                                cur.execute(sql_script.read())
                        temp_conn.commit() # Actually no need of it, automatically committed in the with

                    except (Exception, psycopg2.Error) as error:
                        temp_conn.rollback()
                        fail_flag = True
                        gen_f.critical_log(
                            func=self.install_thread,
                            location=FILE_LOCATION,
                            header="Installing QGIS Package ddl scripts",
                            error=error)
                        self.sig_fail.emit()
                        break # Exit from the loop

                # 2) Install the DEFAULT users and create their usr_schemas
                if install_users_num == 0:
                    pass
                else:
                    for suf in def_usr_name_suffixes:
                        # Prepare the name of the user
                        usr_name = "_".join(["qgis_user", suf])

                        query = pysql.SQL("""
                            SELECT {_qgis_pkg_schema}.create_default_qgis_pkg_user({_priv_type});
                        """).format(
                            _qgis_pkg_schema = pysql.Identifier(self.plugin.QGIS_PKG_SCHEMA),
                            _priv_type = pysql.Literal(suf)
                        )                    

                        query2 = pysql.SQL("""
                            SELECT {_qgis_pkg_schema}.create_qgis_usr_schema({_usr_name});
                        """).format(
                            _qgis_pkg_schema = pysql.Identifier(self.plugin.QGIS_PKG_SCHEMA),
                            _usr_name = pysql.Literal(usr_name)
                        ) 

                        # Update progress bar
                        msg = f"Creating user: '{usr_name}'"
                        curr_step += 1
                        self.sig_progress.emit(self.plugin.DLG_NAME_ADMIN, curr_step, msg)

                        try:
                            with temp_conn.cursor() as cur:
                                cur.execute(query)
                                cur.execute(query2)
                            temp_conn.commit()

                        except (Exception, psycopg2.Error) as error:
                            temp_conn.rollback()
                            fail_flag = True
                            gen_f.critical_log(
                                func=self.install_thread,
                                location=FILE_LOCATION,
                                header=f"Creating QGIS Package default user '{usr_name}'",
                                error=error)
                            self.sig_fail.emit()
                            break # Exit from the loop

                # 3) If required, grant them (default) privileges: ro or rw on all existing cdb_schemas
                if set_privileges_num == 0:
                    pass
                else:
                    for suf in def_usr_access_suffixes:
                        # Prepare the nale of the user
                        usr_name = "_".join(["qgis_user", suf])

                        query = pysql.SQL("""
                            SELECT {_qgis_pkg_schema}.grant_qgis_usr_privileges(usr_name := {_usr_name}, priv_type := {_priv_type}, cdb_schema := NULL);
                        """).format(
                            _qgis_pkg_schema = pysql.Identifier(self.plugin.QGIS_PKG_SCHEMA),
                            _usr_name = pysql.Literal(usr_name),
                            _priv_type = pysql.Literal(suf)
                        )                    

                        # Update progress bar with current step and script.
                        msg = f"Setting privileges for user: '{usr_name}'"
                        curr_step += 1
                        self.sig_progress.emit(self.plugin.DLG_NAME_ADMIN, curr_step, msg)

                        try:
                            with temp_conn.cursor() as cur:
                                cur.execute(query)
                            temp_conn.commit()

                        except (Exception, psycopg2.Error) as error:
                            temp_conn.rollback()
                            fail_flag = True
                            gen_f.critical_log(
                                func=self.install_thread,
                                location=FILE_LOCATION,
                                header=f"Granting {suf} privileges to user {usr_name}",
                                error=error)
                            self.sig_fail.emit()
                            break # Exit from the loop

        except (Exception, psycopg2.Error) as error:
            temp_conn.rollback()
            fail_flag = True
            gen_f.critical_log(
                func=self.install_thread,
                location=FILE_LOCATION,
                header=f"Establishing temporary connection",
                error=error)
            self.sig_fail.emit()

        # No FAIL = SUCCESS
        if not fail_flag:
            self.sig_success.emit()

        self.sig_finished.emit()
        # Close connection
        temp_conn.close()
        return None

#--EVENTS  (start)  ##############################################################

def ev_qgis_pkg_install_success(cdbMain: CDBToolsMain, pkg: str) -> None:
    """Event that is called when the thread executing the installation finishes successfully.

    Shows success message at cdbMain.usr_dlg.msg_bar: QgsMessageBar
    Shows success message in Connection Status groupbox
    Shows success message in QgsMessageLog
    """
    dlg = cdbMain.admin_dlg

    if sh_sql.is_qgis_pkg_installed(cdbMain):
        # Replace with Success msg.
        msg = dlg.msg_bar.createMessage(c.INST_SUCC_MSG.format(pkg=pkg))
        dlg.msg_bar.pushWidget(msg, Qgis.Success, 5)

        # Show database name
        dlg.lblConnToDb_out.setText(c.success_html.format(text=cdbMain.DB.database_name))
        # Update the label regarding the QGIS Package Installation
        dlg.lblMainInst_out.setText(c.success_html.format(text=c.INST_SUCC_MSG + " (v. " + c.QGIS_PKG_MIN_VERSION_TXT + ")").format(pkg=cdbMain.QGIS_PKG_SCHEMA))

        # Inform user
        QgsMessageLog.logMessage(
                message=c.INST_SUCC_MSG.format(pkg=pkg),
                tag=cdbMain.PLUGIN_NAME,
                level=Qgis.Success,
                notifyUser=True)

        # Finish (re)setting up the GUI
        ti_wf.setup_post_qgis_pkg_installation(cdbMain)

    else:
        ev_qgis_pkg_install_fail(cdbMain, pkg)


def ev_qgis_pkg_install_fail(cdbMain: CDBToolsMain, pkg: str) -> None:
    """Event that is called when the thread executing the installation
    emits a fail signal meaning that something went wrong with installation.

    It prompt the user to clear the installation before trying again.
    .. Not sure if this is necessary as in every installation the package
    .. is dropped to replace it with a new one.

    Shows fail message at cdbMain.admin_dlg.msg_bar: QgsMessageBar
    Shows fail message in Connection Status groupbox
    Shows fail message in QgsMessageLog
    """
    dlg = cdbMain.admin_dlg

    # Replace with Failure msg.
    msg = dlg.msg_bar.createMessage(c.INST_FAIL_MSG.format(pkg=pkg))
    dlg.msg_bar.pushWidget(msg, Qgis.Critical, 5)

    # Inform user
    dlg.lblMainInst_out.setText(c.failure_html.format(text=c.INST_FAIL_MSG.format(pkg=pkg)))
    QgsMessageLog.logMessage(
            message=c.INST_FAIL_MSG.format(pkg=pkg),
            tag=cdbMain.PLUGIN_NAME,
            level=Qgis.Critical,
            notifyUser=True)

    # Drop corrupted installation.
    sql.exec_drop_db_schema(cdbMain, schema=cdbMain.QGIS_PKG_SCHEMA, close_connection=False)

    # Fisish (re)setting up the GUI
    ti_wf.setup_post_qgis_pkg_uninstallation(cdbMain)

#--EVENTS  (end) ################################################################

#####################################################################################
##### QGIS PACKAGE UNINSTALL ########################################################
#####################################################################################

def run_uninstall_qgis_pkg_thread(cdbMain: CDBToolsMain) -> None:
    """Function that uninstalls the qgis_pkg schema from the database
    by branching a new Worker thread to execute the operation on.
    """
    dlg = cdbMain.admin_dlg

    # Add a new progress bar to follow the installation procedure.
    cdbMain.create_progress_bar(dialog=dlg, layout=dlg.vLayoutMainInst, position=-1)

    # Create new thread object.
    cdbMain.thread = QThread()
    # Instantiate worker object for the operation.
    cdbMain.worker = QgisPackageUninstallWorker(cdbMain)
    # Move worker object to the be executed on the new thread.
    cdbMain.worker.moveToThread(cdbMain.thread)

    #-SIGNALS--(start)--################################################################
    # Anti-panic clicking: Disable widgets to avoid queuing signals.
    # ...

    # Execute worker's 'run' method.
    cdbMain.thread.started.connect(cdbMain.worker.uninstall_thread)

    # Capture progress to show in bar.
    cdbMain.worker.sig_progress.connect(cdbMain.evt_update_bar)

    # Get rid of worker and thread objects.
    cdbMain.worker.sig_finished.connect(cdbMain.thread.quit)
    cdbMain.worker.sig_finished.connect(cdbMain.worker.deleteLater)
    cdbMain.thread.finished.connect(cdbMain.thread.deleteLater)

    # Reenable the GUI
    cdbMain.thread.finished.connect(dlg.msg_bar.clearWidgets)

    # On installation status
    cdbMain.worker.sig_success.connect(lambda: evt_qgis_pkg_uninstall_success(cdbMain))
    cdbMain.worker.sig_fail.connect(lambda: evt_qgis_pkg_uninstall_fail(cdbMain))
    #-SIGNALS--(end)---################################################################

    # Initiate worker thread
    cdbMain.thread.start()


class QgisPackageUninstallWorker(QObject):
    """Class to assign Worker that executes the 'uninstallation scripts'
    to uninstall the plugin package (qgis_pkg) from the database.
    """
    # Create custom signals.
    sig_finished = pyqtSignal()
    sig_progress = pyqtSignal(str, int, str)
    sig_success = pyqtSignal()
    sig_fail = pyqtSignal()

    def __init__(self, cdbMain: CDBToolsMain):
        super().__init__()
        self.plugin = cdbMain

    def uninstall_thread(self):

        # Named tuple: version, full_version, major_version, minor_version, minor_revision, code_name, release_date
        qgis_pkg_curr_version = sh_sql.exec_qgis_pkg_version(self.plugin)

        # print(qgis_pkg_curr_version)
        qgis_pkg_curr_version_major    : int = qgis_pkg_curr_version.major_version   # e.g. 0
        qgis_pkg_curr_version_minor    : int = qgis_pkg_curr_version.minor_version   # e.g. 8

        if all((qgis_pkg_curr_version_major <= c.QGIS_PKG_MIN_VERSION_MAJOR,
                qgis_pkg_curr_version_minor < c.QGIS_PKG_MIN_VERSION_MINOR)):
            self.uninstall_thread_qgis_pkg_till_08()
        else:
            self.uninstall_thread_qgis_pkg_current()

        return None


    def uninstall_thread_qgis_pkg_till_08(self):
        """Execution method that uninstalls the QGIS Package (older version, till 0.8.x).
        """
        # Flag to help us break from a failing installation.
        fail_flag: bool = False
        qgis_pkg_schema: str = self.plugin.QGIS_PKG_SCHEMA

        # Get users
        usr_names_all: tuple = sql.exec_list_qgis_pkg_usrgroup_members(cdbMain=self.plugin)
        usr_names = []
        if usr_names_all:
            usr_names = [elem for elem in usr_names_all if elem != 'postgres']
        else:
            usr_names = usr_names_all

        # Get usr_schemas
        usr_schemas = sql.exec_list_usr_schemas(cdbMain=self.plugin)

        # Get cdb_schemas
        cdb_schemas, dummy = sh_sql.exec_list_cdb_schemas_all(cdbMain=self.plugin)
        dummy = None # discard byproduct

        drop_layers_funcs: list = [
            "drop_layers_bridge",
            "drop_layers_building",
            "drop_layers_cityfurniture",
            "drop_layers_generics",
            "drop_layers_landuse",
            "drop_layers_relief",
            "drop_layers_transportation",
            "drop_layers_tunnel",
            "drop_layers_vegetation",
            "drop_layers_waterbody",
            ]

        if not usr_names:
            usr_names_num = 0
        else:
            usr_names_num = len(usr_names)

        if not usr_schemas:
            usr_schemas_num = 0
        else:
            usr_schemas_num = len(usr_schemas)

        if not cdb_schemas:
            cdb_schemas_num = 0
        else:
            cdb_schemas_num = len(cdb_schemas)

        # Set progress bar goal (number of actions):
        # 1) revoke privileges: usr_names_num (all but postgres)
        # 2) drop layers: usr_names_num x cdb_schemas_num x drop_functions_num #IDEALLY: usr_schemas_num x cdb_schemas_num x drop_functions_num
        # 3) drop usr schemas: usr_schemas_num 
        # 4) drop 'qgis_pkg': 1
        # TOTAL = usr_names_num + usr_schemas_num x (cdb_schemas_num x drop_functions_num + 1) + 1

        steps_tot = usr_names_num + usr_names_num * cdb_schemas_num * len(drop_layers_funcs) + usr_schemas_num + 1
        self.plugin.admin_dlg.bar.setMaximum(steps_tot)

        curr_step: int = 0

        try:
            temp_conn = conn_f.create_db_connection(db_connection=self.plugin.DB, app_name=" ".join([self.plugin.PLUGIN_NAME_ADMIN, "(QGIS Package Uninstallation)"]))
            with temp_conn:

                # 1) revoke privileges: for all users
                if usr_names_num == 0:
                    pass # nothing to do 
                else:
                    for usr_name in usr_names:

                        query = pysql.SQL("""
                            SELECT {_qgis_pkg_schema}.revoke_qgis_usr_privileges(usr_name := {_usr_name}, cdb_schema := NULL);
                            """).format(
                            _qgis_pkg_schema = pysql.Identifier(self.plugin.QGIS_PKG_SCHEMA),
                            _usr_name = pysql.Literal(usr_name)
                            )

                        # Update progress bar
                        msg = f"Revoking privileges from user: {usr_name}"
                        curr_step += 1
                        self.sig_progress.emit(self.plugin.DLG_NAME_ADMIN, curr_step, msg)

                        try:
                            with temp_conn.cursor() as cur:
                                cur.execute(query)
                            temp_conn.commit()

                        except (Exception, psycopg2.Error) as error:
                            temp_conn.rollback()
                            fail_flag = True
                            gen_f.critical_log(
                                func=self.uninstall_thread,
                                location=FILE_LOCATION,
                                header=f"Revoking privileges from users",
                                error=error)
                            self.sig_fail.emit()

                # 2) drop layers:  usr_names_num x cdb_schemas_num x drop_functions_num
                if usr_names_num == 0 or cdb_schemas_num == 0:
                    pass # nothing to do 
                else:
                    for usr_name in usr_names:
                        # Get current user's schema
                        usr_schema: str = sh_sql.exec_create_qgis_usr_schema_name(self.plugin, usr_name)
                        for cdb_schema in cdb_schemas:
                            for drop_layers_func in drop_layers_funcs:

                                query = pysql.SQL("""
                                    SELECT {_qgis_pkg_schema}.{_drop_layers_func}({_usr_name},{_cdb_schema});
                                    """).format(
                                    _qgis_pkg_schema = pysql.Identifier(qgis_pkg_schema),
                                    _drop_layers_func = pysql.Identifier(drop_layers_func),
                                    _usr_name = pysql.Literal(usr_name),
                                    _cdb_schema = pysql.Literal(cdb_schema)
                                    )

                                # Update progress bar
                                msg = f"In {usr_schema}: dropping layers for {cdb_schema}"
                                curr_step += 1
                                self.sig_progress.emit(self.plugin.DLG_NAME_ADMIN, curr_step, msg)

                                try:
                                    with temp_conn.cursor() as cur:
                                        cur.execute(query)
                                    temp_conn.commit()

                                except (Exception, psycopg2.Error) as error:
                                    fail_flag = True
                                    gen_f.critical_log(
                                        func=self.uninstall_thread,
                                        location=FILE_LOCATION,
                                        header="Dropping layers",
                                        error=error)
                                    temp_conn.rollback()
                                    self.sig_fail.emit()

                # 3) drop usr_schemas
                if usr_schemas_num == 0:
                    pass # nothing to do 
                else:
                    for usr_schema in usr_schemas:
                        query = pysql.SQL("""
                        DROP SCHEMA IF EXISTS {_usr_schema} CASCADE;
                        """).format(
                        _usr_schema = pysql.Identifier(usr_schema)
                        )

                        # Update progress bar
                        msg = " ".join(["Dropping user schema:", usr_schema])
                        curr_step += 1
                        self.sig_progress.emit(self.plugin.DLG_NAME_ADMIN, curr_step, msg)

                        try:
                            with temp_conn.cursor() as cur:
                                cur.execute(query)
                            temp_conn.commit()

                        except (Exception, psycopg2.Error) as error:
                            fail_flag = True
                            gen_f.critical_log(
                                func=self.uninstall_thread,
                                location=FILE_LOCATION,
                                header=f"Dropping user schema {usr_schema}",
                                error=error)
                            temp_conn.rollback()
                            self.sig_fail.emit()

                # 4) Drop "qgis_pkg" schema
                query = pysql.SQL("""
                    DROP SCHEMA IF EXISTS {_qgis_pkg_schema} CASCADE;
                    """).format(
                    _qgis_pkg_schema = pysql.Identifier(qgis_pkg_schema)
                    )

                # Update progress bar
                msg = " ".join(["Dropping schema:", qgis_pkg_schema])
                curr_step += 1
                self.sig_progress.emit(self.plugin.DLG_NAME_ADMIN, curr_step, msg)

                try:
                    with temp_conn.cursor() as cur:
                        cur.execute(query)
                    temp_conn.commit()

                except (Exception, psycopg2.Error) as error:
                    temp_conn.rollback()
                    fail_flag = True
                    gen_f.critical_log(
                        func=self.uninstall_thread,
                        location=FILE_LOCATION,
                        header=f"Dropping QGIS Package schema '{qgis_pkg_schema}'",
                        error=error)
                    self.sig_fail.emit()

        except (Exception, psycopg2.Error) as error:
            temp_conn.rollback()
            fail_flag = True
            gen_f.critical_log(
                func=self.uninstall_thread_qgis_pkg_till_08,
                location=FILE_LOCATION,
                header=f"Establishing temporary connection",
                error=error)
            self.sig_fail.emit()

        # No FAIL = SUCCESS
        if not fail_flag:
            self.sig_success.emit()

        self.sig_finished.emit()
        # Close temp connection
        temp_conn.close()
        return None


    def uninstall_thread_qgis_pkg_current(self):
        """Execution method that uninstalls the QGIS Package (current version).
        """
        # Flag to help us break from a failing installation.
        fail_flag: bool = False
        qgis_pkg_schema: str = self.plugin.QGIS_PKG_SCHEMA

        # Overview of the procedure:
        # 1) revoke privileges: for all users (except postgres or superusers)
        # 2) drop feature types (layers)
        # 3) drop usr_schemas
        # 4) drop qgis_pkg schema

        # Get required information
        
        # usr_names = sql.exec_list_qgis_pkg_usrgroup_members(cdbMain=self.plugin)
        # print("uninstall usr_names:", usr_names)

        # Get users
        usr_names_all = sql.exec_list_qgis_pkg_usrgroup_members(cdbMain=self.plugin)
        # print("uninstall usr_names:", usr_names_all)
        usr_names = []
        if usr_names_all:
            usr_names = [elem for elem in usr_names_all if elem != 'postgres']
        else:
            usr_names = usr_names_all
        # print("uninstall usr_names:", usr_names)

        drop_tuples = sql.exec_list_feature_types(self.plugin, usr_schema=None) # get 'em all!!
        # print("uninstall drop_tuples:", drop_tuples)

        # Get usr_schemas
        usr_schemas = sql.exec_list_usr_schemas(cdbMain=self.plugin)
        # print("uninstall usr_schemas:", usr_schemas)

        # Set progress bar goal:
        # revoke privileges: 1 x len(usr_names) actions
        # drop feature types (layers): len(drop_tuples)
        # drop usr_schemas: 1 x len(usr_schemas)
        # drop the qgis_pkg_usrgroup_*: +1
        # drop 'qgis_pkg': +1

        if not usr_names:
            usr_names_num = 0
        else:
            usr_names_num = len(usr_names)

        if not drop_tuples:
            drop_tuples_num = 0
        else:
            drop_tuples_num = len(drop_tuples)

        if not usr_schemas:
            usr_schemas_num = 0
        else:
            usr_schemas_num = len(usr_schemas)

        steps_tot = usr_names_num + drop_tuples_num + usr_schemas_num + 2
        self.plugin.admin_dlg.bar.setMaximum(steps_tot)

        curr_step: int = 0

        try:
            # Open new temp session, reserved for installation.
            temp_conn = conn_f.create_db_connection(db_connection=self.plugin.DB, app_name=" ".join([self.plugin.PLUGIN_NAME_ADMIN, "(QGIS Package Uninstallation)"]))
            with temp_conn:

                # 1) revoke privileges: for all users
                if usr_names_num == 0:
                    pass # nothing to do 
                else:
                    for usr_name in usr_names:

                        query = pysql.SQL("""
                            SELECT {_qgis_pkg_schema}.revoke_qgis_usr_privileges(usr_name := {_usr_name}, cdb_schemas := NULL);
                            """).format(
                            _qgis_pkg_schema = pysql.Identifier(self.plugin.QGIS_PKG_SCHEMA),
                            _usr_name = pysql.Literal(usr_name)
                            )

                        # Update progress bar
                        msg = f"Revoking privileges from user: {usr_name}"
                        curr_step += 1
                        self.sig_progress.emit(self.plugin.DLG_NAME_ADMIN, curr_step, msg)

                        try:
                            with temp_conn.cursor() as cur:
                                cur.execute(query)
                            temp_conn.commit()               

                        except (Exception, psycopg2.Error) as error:
                            temp_conn.rollback()
                            fail_flag = True
                            gen_f.critical_log(
                                func=self.uninstall_thread,
                                location=FILE_LOCATION,
                                header=f"Revoking privileges from users",
                                error=error)
                            self.sig_fail.emit()

                # 2) drop feature types (layers)
                if drop_tuples_num == 0:
                    pass # nothing to do 
                else:
                    ft: FeatureType
                    for usr_schema, cdb_schema, feat_type in drop_tuples:
                        ft = self.plugin.admin_dlg.FeatureTypesRegistry[feat_type]
                        module_drop_func = ft.layers_drop_function

                        # Prepare the query for the drop_layer_{*} function
                        # E.g. qgis_pkg.drop_layers_building(usr_name, cdb_schema)
                        query = pysql.SQL("""
                            SELECT {_qgis_pkg_schema}.{_module_drop_func}({_usr_name},{_cdb_schema});
                            """).format(
                            _qgis_pkg_schema = pysql.Identifier(qgis_pkg_schema),
                            _module_drop_func = pysql.Identifier(module_drop_func),
                            _usr_name = pysql.Literal(usr_name),
                            _cdb_schema = pysql.Literal(cdb_schema)
                            )

                        # Update progress bar
                        msg = f"In {usr_schema}: dropping {feat_type} layers for {cdb_schema}"
                        curr_step += 1
                        self.sig_progress.emit(self.plugin.DLG_NAME_ADMIN, curr_step, msg)

                        try:
                            with temp_conn.cursor() as cur:
                                cur.execute(query)
                            temp_conn.commit()

                        except (Exception, psycopg2.Error) as error:
                            fail_flag = True
                            gen_f.critical_log(
                                func=self.uninstall_thread,
                                location=FILE_LOCATION,
                                header="Dropping layers",
                                error=error)
                            temp_conn.rollback()
                            self.sig_fail.emit()

                # 3) drop usr_schemas
                if usr_schemas_num == 0:
                    pass # nothing to do 
                else:
                    for usr_schema in usr_schemas:

                        query = pysql.SQL("""
                            DROP SCHEMA IF EXISTS {_usr_schema} CASCADE;
                            """).format(
                            _usr_schema = pysql.Identifier(usr_schema)
                            )

                        # Update progress bar
                        msg = f"Dropped user schema: {usr_schema}"
                        curr_step += 1
                        self.sig_progress.emit(self.plugin.DLG_NAME_ADMIN, curr_step, msg)

                        try:
                            with temp_conn.cursor() as cur:
                                cur.execute(query)
                            temp_conn.commit()

                        except (Exception, psycopg2.Error) as error:
                            temp_conn.rollback()
                            fail_flag = True
                            gen_f.critical_log(
                                func=self.uninstall_thread,
                                location=FILE_LOCATION,
                                header="Dropping user schemas",
                                error=error)
                            self.sig_fail.emit()

                # 4) Drop database group
                if not self.plugin.GROUP_NAME:
                    self.plugin.GROUP_NAME = sql.exec_create_qgis_pkg_usrgroup_name(self.plugin)

                query = pysql.SQL("""
                    DROP ROLE IF EXISTS {_qgis_pkg_usrgroup};
                    """).format(
                    _qgis_pkg_usrgroup = pysql.Identifier(self.plugin.GROUP_NAME)
                    )

                # Update progress bar
                msg = f"Dropping group {self.plugin.GROUP_NAME}"
                curr_step += 1
                self.sig_progress.emit(self.plugin.DLG_NAME_ADMIN, curr_step, msg)

                try:
                    with temp_conn.cursor() as cur:
                        cur.execute(query)
                    temp_conn.commit()

                except (Exception, psycopg2.Error) as error:
                    temp_conn.rollback()
                    fail_flag = True
                    gen_f.critical_log(
                        func=self.uninstall_thread,
                        location=FILE_LOCATION,
                        header=f"Dropping group '{self.plugin.GROUP_NAME}'",
                        error=error)
                    self.sig_fail.emit()

                # 5) drop qgis_pkg schema
                query = pysql.SQL("""
                    DROP SCHEMA IF EXISTS {_qgis_pkg_schema} CASCADE;
                    """).format(
                    _qgis_pkg_schema = pysql.Identifier(qgis_pkg_schema)
                    )

                # Update progress bar with current step and script.
                msg = f"Dropping QGIS Package schema"
                curr_step += 1            
                self.sig_progress.emit(self.plugin.DLG_NAME_ADMIN, curr_step, msg)

                try:
                    with temp_conn.cursor() as cur:
                        cur.execute(query)
                    temp_conn.commit()

                except (Exception, psycopg2.Error) as error:
                    temp_conn.rollback()
                    fail_flag = True
                    gen_f.critical_log(
                        func=self.uninstall_thread,
                        location=FILE_LOCATION,
                        header=f"Dropping QGIS Package schema '{qgis_pkg_schema}'",
                        error=error)
                    self.sig_fail.emit()

        except (Exception, psycopg2.Error) as error:
            temp_conn.rollback()
            fail_flag = True
            gen_f.critical_log(
                func=self.uninstall_thread_qgis_pkg_current,
                location=FILE_LOCATION,
                header=f"Establishing temporary connection",
                error=error)

        # No FAIL = SUCCESS
        if not fail_flag:
            self.sig_success.emit()

        self.sig_finished.emit()
        # Close temp connection
        temp_conn.close()
        return None


#--EVENTS  (start)  ##############################################################

def evt_qgis_pkg_uninstall_success(cdbMain: CDBToolsMain) -> None:
    """Event that is called when the thread executing the uninstallation finishes successfully.

    Shows success message at cdbMain.admin_dlg.msg_bar: QgsMessageBar
    Shows success message in Connection Status groupbox
    Shows success message in QgsMessageLog
    """
    dlg = cdbMain.admin_dlg
    qgis_pkg_schema = cdbMain.QGIS_PKG_SCHEMA

    is_qgis_pkg_installed: bool = sh_sql.is_qgis_pkg_installed(cdbMain) # Will always be true or false

    ######### FOR DEBUGGING PURPOSES ONLY ##########
    # is_qgis_pkg_installed = False
    ################################################

    if is_qgis_pkg_installed:
        # QGIS Package was NOT successfully removed
        evt_qgis_pkg_uninstall_fail(cdbMain, qgis_pkg_schema)
    else:
        # QGIS Package was successfully removed
        # Replace with Success msg.
        msg = dlg.msg_bar.createMessage(c.UNINST_SUCC_MSG.format(pkg=qgis_pkg_schema))
        dlg.msg_bar.pushWidget(msg, Qgis.Success, 5)

        # Inform user
        dlg.lblMainInst_out.setText(c.crit_warning_html.format(text=c.INST_FAIL_MSG.format(pkg=qgis_pkg_schema)))
        QgsMessageLog.logMessage(
                message=c.UNINST_SUCC_MSG.format(pkg=qgis_pkg_schema),
                tag=cdbMain.PLUGIN_NAME,
                level=Qgis.Success,
                notifyUser=True)

        # Clear the label in the connection status groupbox
        dlg.lblUserInst_out.clear()

        # Finish (re)setting up the GUI
        ti_wf.setup_post_qgis_pkg_uninstallation(cdbMain)

    return None


def evt_qgis_pkg_uninstall_fail(cdbMain: CDBToolsMain, error: str = 'Uninstallation error') -> None:
    """Event that is called when the thread executing the uninstallation
    emits a fail signal meaning that something went wrong with uninstallation.

    Shows fail message at cdbMain.admin_dlg.msg_bar: QgsMessageBar
    Shows fail message in Connection Status groupbox
    Shows fail message in QgsMessageLog
    """
    dlg = cdbMain.admin_dlg

    # Replace with Failure msg.
    msg = dlg.msg_bar.createMessage(error)
    dlg.msg_bar.pushWidget(msg, Qgis.Critical, 5)

    # Inform user
    dlg.lblMainInst_out.setText(error)
    QgsMessageLog.logMessage(
            message=error,
            tag=cdbMain.PLUGIN_NAME,
            level=Qgis.Critical,
            notifyUser=True)
    
    return None

#--EVENTS  (end) ################################################################


#####################################################################################
##### USR SCHEMA DROP ###############################################################
#####################################################################################

def run_drop_usr_schema_thread(cdbMain: CDBToolsMain) -> None:
    """Function that uninstalls the {usr_schema} from the database
    by branching a new Worker thread to execute the operation on.
    """
    dlg = cdbMain.admin_dlg

    # Add a new progress bar to follow the installation procedure.
    cdbMain.create_progress_bar(dialog=dlg, layout=dlg.vLayoutUserInstGroup, position=2)

    # Create new thread object.
    cdbMain.thread = QThread()
    # Instantiate worker object for the operation.
    cdbMain.worker = DropUsrSchemaWorker(cdbMain)
    # Move worker object to the be executed on the new thread.
    cdbMain.worker.moveToThread(cdbMain.thread)

    #-SIGNALS--(start)#########################################################
    # Anti-panic clicking: Disable widgets to avoid queuing signals.
    # ...

    # Execute worker's 'run' method.
    cdbMain.thread.started.connect(cdbMain.worker.drop_usr_schema_thread)

    # Capture progress to show in bar.
    cdbMain.worker.sig_progress.connect(cdbMain.evt_update_bar)

    # Get rid of worker and thread objects.
    cdbMain.worker.sig_finished.connect(cdbMain.thread.quit)
    cdbMain.worker.sig_finished.connect(cdbMain.worker.deleteLater)
    cdbMain.thread.finished.connect(cdbMain.thread.deleteLater)

    # Reenable the GUI
    cdbMain.thread.finished.connect(dlg.msg_bar.clearWidgets)

    # On installation status
    cdbMain.worker.sig_success.connect(lambda: evt_usr_schema_drop_success(cdbMain))
    cdbMain.worker.sig_fail.connect(lambda: evt_usr_schema_drop_fail(cdbMain))
    #-SIGNALS--(end)############################################################

    # Initiate worker thread
    cdbMain.thread.start()


class DropUsrSchemaWorker(QObject):
    """Class to assign Worker that drops a user schema from the database and all associated activities.
    """
    # Create custom signals.
    sig_finished = pyqtSignal()
    sig_progress = pyqtSignal(str, int, str)
    sig_success = pyqtSignal()
    sig_fail = pyqtSignal()

    def __init__(self, cdbMain: CDBToolsMain):
        super().__init__()
        self.plugin = cdbMain


    def drop_usr_schema_thread(self):
        """Execution method that uninstalls the {usr_schema} from the current database
        """
         # Flag to help us break from a failing installation.
        fail_flag: bool = False
        qgis_pkg_schema: str = self.plugin.QGIS_PKG_SCHEMA
        
        usr_name: str = self.plugin.admin_dlg.cbxUser.currentText()

        usr_schema = self.plugin.USR_SCHEMA

        # Overview of the procedure:
        # 1) revoke privileges for selected user
        # 2) drop feature types (layers)
        # 3) drop usr_schema of the selected user

        drop_tuples = sql.exec_list_feature_types(self.plugin, self.plugin.USR_SCHEMA)

        # Set progress bar goal:
        # revoke privileges: 1 action (not needed with postgres)
        # drop feature types (layers): len(drop_tuples)
        # drop usr schema: 1

        usr_names_num = 1

        if not drop_tuples:
            drop_tuples_num = 0
        else:
            drop_tuples_num = len(drop_tuples)

        steps_tot = usr_names_num + drop_tuples_num + 1
        self.plugin.admin_dlg.bar.setMaximum(steps_tot)

        curr_step: int = 0

        try:
            # Open new temp session, reserved for usr_schema installation.
            temp_conn = conn_f.create_db_connection(db_connection=self.plugin.DB, app_name=" ".join([self.plugin.PLUGIN_NAME_ADMIN, "(User schema Uninstallation)"]))
            with temp_conn:

                # 1) revoke privileges for selected user
                query = pysql.SQL("""
                    SELECT {_qgis_pkg_schema}.revoke_qgis_usr_privileges(usr_name := {_usr_name}, cdb_schema := NULL);
                    """).format(
                    _qgis_pkg_schema = pysql.Identifier(self.plugin.QGIS_PKG_SCHEMA),
                    _usr_name = pysql.Literal(usr_name)
                    )

                # Update progress bar
                msg = f"Revoking privileges from user: {usr_name}"
                curr_step += 1
                self.sig_progress.emit(self.plugin.DLG_NAME_ADMIN, curr_step, msg)

                try:
                    with temp_conn.cursor() as cur:
                        cur.execute(query)
                    temp_conn.commit()

                except (Exception, psycopg2.Error) as error:
                    temp_conn.rollback()
                    fail_flag = True
                    gen_f.critical_log(
                        func=self.drop_usr_schema_thread,
                        location=FILE_LOCATION,
                        header=f"Revoking privileges from user '{usr_name}",
                        error=error)
                    self.sig_fail.emit()

                # 2) drop feature types (layers)
                if drop_tuples_num == 0:
                    pass
                else:
                    for usr_schema, cdb_schema, feat_type in drop_tuples:

                        ft: FeatureType
                        ft = self.plugin.admin_dlg.FeatureTypesRegistry[feat_type]
                        module_drop_func = ft.layers_drop_function

                        query = pysql.SQL("""
                            SELECT {_qgis_pkg_schema}.{_module_drop_func}({_usr_name},{_cdb_schema});
                            """).format(
                            _qgis_pkg_schema = pysql.Identifier(qgis_pkg_schema),
                            _module_drop_func = pysql.Identifier(module_drop_func),
                            _usr_name = pysql.Literal(usr_name),
                            _cdb_schema = pysql.Literal(cdb_schema)
                            )

                        # Update progress bar
                        msg = f"In {usr_schema}: dropping {feat_type} layers for {cdb_schema}"
                        curr_step += 1
                        self.sig_progress.emit(self.plugin.DLG_NAME_ADMIN, curr_step, msg)

                        try:
                            with temp_conn.cursor() as cur:
                                cur.execute(query)
                            temp_conn.commit()

                        except (Exception, psycopg2.Error) as error:
                            temp_conn.rollback()
                            fail_flag = True
                            gen_f.critical_log(
                                func=self.drop_usr_schema_thread,
                                location=FILE_LOCATION,
                                header="Dropping layers",
                                error=error)
                            self.sig_fail.emit()

                # 3) drop usr_schema
                query = pysql.SQL("""
                    DROP SCHEMA IF EXISTS {_usr_schema} CASCADE;
                    """).format(
                    _usr_schema = pysql.Identifier(usr_schema)
                    )

                # Update progress bar with current step and script.
                msg = f"Dropping user schema: {usr_schema}"
                curr_step += 1
                self.sig_progress.emit(self.plugin.DLG_NAME_ADMIN, curr_step, msg)

                try:
                    with temp_conn.cursor() as cur:
                        cur.execute(query)
                    temp_conn.commit()

                except (Exception, psycopg2.Error) as error:
                    temp_conn.rollback()
                    fail_flag = True
                    gen_f.critical_log(
                        func=self.drop_usr_schema_thread,
                        location=FILE_LOCATION,
                        header="Dropping user schema '{usr_schema}'",
                        error=error)
                    self.sig_fail.emit()

        except (Exception, psycopg2.Error) as error:
            temp_conn.rollback()
            fail_flag = True
            gen_f.critical_log(
                func=self.drop_usr_schema_thread,
                location=FILE_LOCATION,
                header=f"Establishing temporary connection",
                error=error)
            self.sig_fail.emit()

        # No FAIL = SUCCESS
        if not fail_flag:
            self.sig_success.emit()

        self.sig_finished.emit()
        # Close temp connection
        temp_conn.close()
        return None

#--EVENTS  (start)  ##############################################################

def evt_usr_schema_drop_success(cdbMain: CDBToolsMain) -> None:
    """Event that is called when the thread executing the uninstallation
    finishes successfully.

    Shows success message at cdbMain.admin_dlg.msg_bar: QgsMessageBar
    Shows success message in Connection Status groupbox
    Shows success message in QgsMessageLog
    """
    dlg = cdbMain.admin_dlg
    usr_schema = cdbMain.USR_SCHEMA

    if not sh_sql.is_usr_schema_installed(cdbMain):
        # Replace with Success msg.
        msg = dlg.msg_bar.createMessage(c.UNINST_SUCC_MSG.format(pkg=usr_schema))
        dlg.msg_bar.pushWidget(msg, Qgis.Success, 5)

        # Inform user
        dlg.lblUserInst_out.setText(c.crit_warning_html.format(text=c.INST_FAIL_MSG.format(pkg=usr_schema)))
        QgsMessageLog.logMessage(
                message=c.UNINST_SUCC_MSG.format(pkg=usr_schema),
                tag=cdbMain.PLUGIN_NAME,
                level=Qgis.Success,
                notifyUser=True)

        # Enable the remove from group button
        dlg.btnRemoveUserFromGrp.setDisabled(False)
        # Enable the user Installation button
        dlg.btnUsrInst.setDisabled(False)
        # Disable the the user Uninstallation button
        dlg.btnUsrUninst.setDisabled(True)
        
        # Reset and disable the user privileges groupbox
        ti_wf.gbxPriv_reset(cdbMain) # this also disables it.

    else:
        evt_usr_schema_drop_fail(cdbMain, usr_schema)


def evt_usr_schema_drop_fail(cdbMain: CDBToolsMain, error: str ='error') -> None:
    """Event that is called when the thread executing the uninstallation
    emits a fail signal meaning that something went wrong with uninstallation.

    Shows fail message at cdbMain.admin_dlg.msg_bar: QgsMessageBar
    Shows fail message in Connection Status groupbox
    Shows fail message in QgsMessageLog
    """
    dlg = cdbMain.admin_dlg

    # Replace with Failure msg.
    msg = dlg.msg_bar.createMessage(error)
    dlg.msg_bar.pushWidget(msg, Qgis.Critical, 5)

    # Inform user
    dlg.lblUserInst_out.setText(error)
    QgsMessageLog.logMessage(
            message=error,
            tag=cdbMain.PLUGIN_NAME,
            level=Qgis.Critical,
            notifyUser=True)

    # Disable the remove from group button
    dlg.btnRemoveUserFromGrp.setDisabled(True)
    # Disable the user Installation button
    dlg.btnUsrInst.setDisabled(True)
    # Enable the the user Uninstallation button
    dlg.btnUsrUninst.setDisabled(False)

#--EVENTS  (end) ################################################################

