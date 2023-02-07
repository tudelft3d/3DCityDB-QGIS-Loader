import os.path
from . import loader_constants as c

class LoaderDialogChecks:
    def __init__(self):
        self.is_conn_successful: bool = False
        self.is_postgis_installed: bool = False
        self.is_3dcitydb_installed: bool = False
        self.is_qgis_pkg_installed: bool = False
        self.is_usr_pkg_installed: bool = False
        self.layers_exist: bool = False
        self.layers_refreshed: bool = False

    def __str__(self):
        return_str: str = \
            f"Is the connection to the database established? {self.is_conn_successful}\n" + \
            f"Is PostGIS installed? {self.is_postgis_installed}\n" + \
            f"Is the 3DCityDB installed? {self.is_3dcitydb_installed}\n" + \
            f"Is the QGIS Package installed? {self.is_qgis_pkg_installed}\n" + \
            f"Is the user schema installed? {self.is_usr_pkg_installed}\n" + \
            f"Have layers been created? {self.layers_exist}\n" + \
            f"Have layers been refreshed? {self.layers_refreshed}\n"
        return return_str


    def are_requirements_fulfilled(self) -> bool:
        """Method that is used to check whether layers can be loaded in the ""Layers' tab"

        *   :returns: The plugin's readiness to finally load layers.
            :rtype: bool
        """
        if all((self.is_conn_successful,
                self.is_postgis_installed,
                self.is_3dcitydb_installed,
                self.is_qgis_pkg_installed,
                self.is_usr_pkg_installed,
                self.layers_exist,
                self.layers_refreshed)):
            return True
        return False

    
class LoaderDefaultSettings:
    """ Contains all DEFAULT settings of the CDB4-Loader dialog, and their explanation.
    """
    def __init__(self):
        self.simp_geom_enabled_default: int = False
        self.simp_geom_enabled_label: str = "Toggles on or off the geometry simplification settings"

        self.simp_geom_dec_prec_default: int = 3
        self.simp_geom_dec_prec_label: str = "Number of decimal positions after the comma to round coordinates"

        self.simp_geom_min_area_default: float = 0.0001
        self.simp_geom_min_area_label: str = "Minimum area threshold to keep a simplified polygon, in [m2]"

        self.max_features_to_import_default: int = 50000
        self.max_features_to_import_label: str = "Maximum (cumulative) number of features to import into QGIS at a time"

        self.force_all_layers_creation_default: bool = False
        self.force_all_layers_creation_label: str = "Forces QGIS Package to generate all layers, even if empty"
        
        self.enable_3d_renderer_default: bool = False
        self.enable_3d_renderer_label: str = "Toggles on or off the 3D rendered and the assignment of the 3D styles to the layers"

    def __str__(self):
        return_str: str = \
            f"simp_geom_enabled (DEFAULT): {self.simp_geom_enabled_default}\n" + \
            f"simp_geom_dec_prec (DEFAULT): {self.simp_geom_dec_prec_default}\n" + \
            f"simp_geom_min_area (DEFAULT): {self.simp_geom_min_area_default}\n" + \
            f"max_features_to_import (DEFAULT): {self.max_features_to_import_default}\n" + \
            f"force_all_layers_creation (DEFAULT): {self.force_all_layers_creation_default}\n" + \
            f"enable_3d_renderer (DEFAULT): {self.enable_3d_renderer_default}\n"
        return return_str


class CDBLayer():
    """This class is used to convert each row of the 'layer_metadata' table into object
    instances. Its purpose is to facilitate access to attributes.
    """
    def __init__(self,
            l_id: int,
            cdb_schema: str,
            layer_type: str,
            feature_type: str,
            root_class: str,
            curr_class: str,
            lod: str,
            layer_name: str,
            av_name: str,
            gv_name: str,
            n_features: int,
            creation_date: str,
            refresh_date: str,
            qml_form: str,
            qml_symb: str,
            qml_3d: str
            ):

        self.l_id = l_id
        self.cdb_schema = cdb_schema
        self.layer_type = layer_type
        self.feature_type = feature_type
        self.root_class = root_class
        self.curr_class = curr_class
        self.lod = lod
        self.root_class_name = root_class
        self.curr_class_name = curr_class
        self.layer_name = layer_name
        self.gv_name = gv_name
        self.av_name = av_name
        self.n_features = n_features
        self.creation_date = creation_date
        self.refresh_date = refresh_date
        self.qml_form = qml_form
        self.qml_symb = qml_symb
        self.qml_3d = qml_3d

        if qml_form:
            self.qml_form_with_path: str = os.path.join(c.QML_PATH, c.QML_FORM_DIR, qml_form)
        else:
            self.qml_form_with_path = None

        if qml_symb:
            self.qml_symb_with_path: str = os.path.join(c.QML_PATH, c.QML_SYMB_DIR, qml_symb)
        else:
            self.qml_symb_with_path = None

        if qml_3d:
            self.qml_3d_with_path: str = os.path.join(c.QML_PATH, c.QML_3D_DIR, qml_3d)
        else:
            self.qml_3d_with_path = None
        
        self.n_selected: int = 0


class FeatureType():
    def __init__(self,
                name: str, 
                alias: str,
                layers_create_function: str = None,
                layers_refresh_function: str = None,
                layers_drop_function: str = None,
                exists: bool = None,                   # i.e. exists in the selected cdb_schema?
                is_ade: bool = False,
                is_selected: bool = True,
                n_features: int = 0
                ):
        self.name = name
        self.alias = alias

        if layers_create_function:
            self.layers_create_function = layers_create_function
        else:
            self.layers_create_function = "_".join(["create_layers", alias])

        if layers_refresh_function:
            self.layers_refresh_function = layers_drop_function
        else:
            self.layers_refresh_function = "_".join(["refresh_layers", alias])

        if layers_drop_function:
            self.layers_drop_function = layers_drop_function
        else:
            self.layers_drop_function = "_".join(["drop_layers", alias])

        self.exists = exists 
        self.is_ade = is_ade
        self.is_selected = is_selected
        self.n_features = n_features
        self.layers = [] # Will contain the CDBLayer objects to be loaded
    
    def __str__(self):
        return_str: str = \
            f"alias: {self.alias}\n" + \
            f"layers_create_function: {self.layers_create_function}\n" + \
            f"layers_refresh_function: {self.layers_refresh_function}\n" + \
            f"layers_drop_function: {self.layers_drop_function}\n" + \
            f"exists? {self.exists}\n" + \
            f"is_ade? {self.is_ade}\n" + \
            f"is selected? {self.is_selected}\n" \
            f"layers number: {len(self.layers)}\n"
        return return_str





