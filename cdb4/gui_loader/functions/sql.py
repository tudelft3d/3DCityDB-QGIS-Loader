"""This module contains functions that relate to the server side operations.

These functions are responsible to communicate and fetch data from
the database with sql queries or sql function calls.
"""
from __future__ import annotations
from typing import TYPE_CHECKING, cast, Iterable, Optional, Literal, Union
if TYPE_CHECKING:       
    from ...gui_loader.loader_dialog import CDB4LoaderDialog
    from ...shared.dataTypes import CDBSchemaPrivs, DetailViewMetadata, LookupTableConfig
    from ..other_classes import CDBLayer

import psycopg2, psycopg2.sql as pysql
from psycopg2.extras import NamedTupleCursor

from ...shared.dataTypes import BBoxType
from ...shared.functions import general_functions as gen_f

FILE_LOCATION = gen_f.get_file_relative_path(file=__file__)

def list_cdb_schemas_privs(dlg: CDB4LoaderDialog) -> list[CDBSchemaPrivs]:
    """SQL function that retrieves the database cdb_schemas for the current database, 
    included the privileges status for the selected usr_name

    *   :returns: A list of named tuples with all usr_schemas, the number of available cityobecjts, 
         and the user's privileges for each cdb_schema in the current database
        :rtype: list[NamedTuple(cdb_schema, is_empty, priv_type)]
    """
    query = pysql.SQL("""
        SELECT cdb_schema, is_empty, priv_type FROM {_qgis_pkg_schema}.list_cdb_schemas_privs({_usr_name});
        """).format(
        _qgis_pkg_schema = pysql.Identifier(dlg.QGIS_PKG_SCHEMA),
        _usr_name = pysql.Literal(dlg.DB.username)
        )

    try:
        with dlg.conn.cursor(cursor_factory=NamedTupleCursor) as cur:
            cur.execute(query)
            res = cur.fetchall()
        dlg.conn.commit()

        if not res:
            res = []

        return res
    
    except (Exception, psycopg2.Error) as error:
        gen_f.critical_log(
            func=list_cdb_schemas_privs,
            location=FILE_LOCATION,
            header="Retrieving list of cdb_schemas with their privileges",
            error=error)
        dlg.conn.rollback()


def get_precomputed_extents(dlg: CDB4LoaderDialog, 
                            bbox_type: Literal[BBoxType.CDB_SCHEMA, BBoxType.MAT_VIEW, BBoxType.QGIS]
                            ) -> Optional[str]:
    """SQL query that reads and retrieves extents stored in {usr_schema}.extents

    *   :param bbox_type: BBoxType(enum), one of ["db_schema", "m_view", "qgis"]
        :type bbox_type: str

    *   :returns: Extents as WKT or None if the entry is empty.
        :rtype: str
    """

    # Get the value associated to the enumeration member
    bbox_type_value = bbox_type.value

    # Get cdb_schema extents from server as WKT rectangular polygon _withouth_ srid.
    query = pysql.SQL("""
        SELECT ST_AsText(envelope) FROM {_usr_schema}.extents 
        WHERE cdb_schema = {_cdb_schema} AND bbox_type = {_ext_type};
        """).format(
        _usr_schema = pysql.Identifier(dlg.USR_SCHEMA),
        _cdb_schema = pysql.Literal(dlg.CDB_SCHEMA),
        _ext_type = pysql.Literal(bbox_type_value)
        )

    try:
        with dlg.conn.cursor() as cur:
            cur.execute(query)
            extents = cur.fetchone()
            # extents = (None,) when the envelope is Null,
            # BUT extents = None when the query returns NO results.
            if type(extents) == tuple:
                extents = extents[0] # Get the value without trailing comma.

        dlg.conn.commit()
        return extents

    except (Exception, psycopg2.Error) as error:
        gen_f.critical_log(
            func=get_precomputed_extents,
            location=FILE_LOCATION,
            header=f"Retrieving extents of schema {dlg.CDB_SCHEMA}",
            error=error)
        dlg.conn.rollback()


def get_cdb_schema_srid(dlg: CDB4LoaderDialog) -> int:
    """SQL query that reads and retrieves the current schema's srid from {cdb_schema}.database_srs

    *   :returns: srid number
        :rtype: int
    """
    # Get database srid
    query = pysql.SQL("""
        SELECT srid FROM {_cdb_schema}.database_srs LIMIT 1;
        """).format(
        _cdb_schema = pysql.Identifier(dlg.CDB_SCHEMA)
        )
   
    try:
        with dlg.conn.cursor() as cur:

            cur.execute(query)
            srid = cur.fetchone()[0] # Tuple has trailing comma.
        dlg.conn.commit()
        return srid

    except (Exception, psycopg2.Error) as error:
        gen_f.critical_log(
            func=get_cdb_schema_srid,
            location=FILE_LOCATION,
            header="Retrieving srid",
            error=error)
        dlg.conn.rollback()


def get_layer_metadata(dlg: CDB4LoaderDialog, cols_list: list[str] = ["*"]) -> tuple[list[str], list[tuple]]:
    """SQL query that retrieves the current schema's layer metadata from {usr_schema}.layer_metadata table. 
    By default it retrieves all columns.

    *   :param cols: The columns to retrieve from the table.
            Note: to fetch multiple columns use: ",".join([col1,col2,col3])
        :type cols: str

    *   :returns: metadata of the layers combined with a collection of
        the attributes names
        :rtype: tuple(attribute_names, metadata)
    """
    if cols_list == ["*"]:    
        query = pysql.SQL("""
                    SELECT * FROM {_usr_schema}.layer_metadata
                    WHERE cdb_schema = {_cdb_schema} AND ade_prefix IS NOT DISTINCT FROM {_ade_prefix} AND layer_type IN ('VectorLayer', 'VectorLayerNoGeom')
                    ORDER BY feature_type, lod, root_class, layer_name;
                    """).format(
                    _usr_schema = pysql.Identifier(dlg.USR_SCHEMA),
                    _cdb_schema = pysql.Literal(dlg.CDB_SCHEMA),
                    _ade_prefix = pysql.Literal(dlg.ADE_PREFIX)
                    )
    else:
        query = pysql.SQL("""
                    SELECT {_cols} FROM {_usr_schema}.layer_metadata
                    WHERE cdb_schema = {_cdb_schema} AND ade_prefix IS NOT DISTINCT FROM {_ade_prefix} AND layer_type IN ('VectorLayer', 'VectorLayerNoGeom')
                    ORDER BY feature_type, lod, root_class, layer_name;
                    """).format(
                    _cols = pysql.SQL(', ').join(pysql.Identifier(col) for col in cols_list),
                    _usr_schema = pysql.Identifier(dlg.USR_SCHEMA),
                    _cdb_schema = pysql.Literal(dlg.CDB_SCHEMA),
                    _ade_prefix = pysql.Literal(dlg.ADE_PREFIX)
                    )

    try:
        with dlg.conn.cursor() as cur:
            cur.execute(query)
            res = cur.fetchall()
            # Attribute names
            col_names = [desc[0] for desc in cast(Iterable[tuple[str, ...]], cur.description)]
        dlg.conn.commit()

        if not res:
            metadata = []
        else:
            metadata = res
        return col_names, metadata

    except (Exception, psycopg2.Error) as error:
        gen_f.critical_log(
            func=get_layer_metadata,
            location=FILE_LOCATION,
            header="Retrieving layers metadata",
            error=error)
        dlg.conn.rollback()


def get_detail_view_metadata(dlg: CDB4LoaderDialog) -> list[DetailViewMetadata]:
    """SQL query that retrieves the current schema's layer metadata from {usr_schema}.layer_metadata table. 
    By default it retrieves all columns.
    
    keys: id, cdb_schema, layer_type, class, layer_name, av_name, qml_form, qml_symb, qml_3d 
    
    *   :param dlg: The dialog we are working with
        :type dlg: CDB4LoaderDialog

    *   :returns: metadata of the layers combined with a collection of
        the attributes names
        :rtype: list(named tuples)
    """
    query = pysql.SQL("""
                    SELECT id, cdb_schema, layer_type, class AS curr_class, layer_name, av_name AS gen_name, qml_form, qml_symb, qml_3d
                    FROM {_usr_schema}.layer_metadata
                    WHERE cdb_schema = {_cdb_schema} AND ade_prefix IS NOT DISTINCT FROM {_ade_prefix} AND layer_type IN ('DetailView', 'DetailViewNoGeom')
                    ORDER BY av_name;
                    """).format(
                    _usr_schema = pysql.Identifier(dlg.USR_SCHEMA),
                    _cdb_schema = pysql.Literal(dlg.CDB_SCHEMA),
                    _ade_prefix = pysql.Literal(dlg.ADE_PREFIX)
                    )

    try:
        with dlg.conn.cursor(cursor_factory=NamedTupleCursor) as cur:
            cur.execute(query)
            res = cur.fetchall()
        dlg.conn.commit()

        if not res:
            res = []

        return res

    except (Exception, psycopg2.Error) as error:
        gen_f.critical_log(
            func=get_detail_view_metadata,
            location=FILE_LOCATION,
            header="Retrieving detail views metadata",
            error=error)
        dlg.conn.rollback()


def list_lookup_tables(dlg: CDB4LoaderDialog) -> Union[tuple[str, ...], tuple[()]]:
    """SQL query that retrieves look-up tables from {usr_schema}.

    *   :returns: Look-up tables names
        :rtype: tuple[str, ...]
    """
    # Prepare query to get all existing look-up tables from the database
    query = pysql.SQL("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = {_usr_schema}
        AND table_type = 'VIEW' AND (table_name LIKE '%codelist%' OR table_name LIKE '%enumeration%');
        """).format(
        _usr_schema = pysql.Literal(dlg.USR_SCHEMA)
        )

    try:
        with dlg.conn.cursor() as cur:
            cur.execute(query)
            res=cur.fetchall()
        dlg.conn.commit()

        if not res:
            lookups = ()
        else:
            lookups: tuple[str, ...]
            lookups = tuple(zip(*res))[0]
            # lookups = tuple(elem[0] for elem in cast(Iterable[tuple[str]],res))

        return lookups

    except (Exception, psycopg2.Error) as error:
        # Send error to QGIS Message Log panel.
        gen_f.critical_log(
            func=list_lookup_tables,
            location=FILE_LOCATION,
            header="Retrieving look-up tables with enumerations and codelists",
            error=error)
        dlg.conn.rollback()


def compute_cdb_schema_extents(dlg: CDB4LoaderDialog) -> tuple[bool, float, float, float, float, int]:
    """Calls the qgis_pkg function that computes the cdb_schema extents.

    *   :returns: is_geom_null, x_min, y_min, x_max, y_max, srid
        :rtype: tuple[bool, float, float, float, float, int]
    """
    # Prepar query to execute server function to compute the schema's extents
    query = pysql.SQL("""
        SELECT * FROM {_qgis_pkg_schema}.compute_cdb_schema_extents({_cdb_schema},{_is_geographic});
        """).format(
        _qgis_pkg_schema = pysql.Identifier(dlg.QGIS_PKG_SCHEMA),
        _cdb_schema = pysql.Literal(dlg.CDB_SCHEMA),
        _is_geographic = pysql.Literal(dlg.CRS_is_geographic)
        )

    try:
        with dlg.conn.cursor() as cur:
            cur.execute(query)
            values = cur.fetchone()
            dlg.conn.commit()
            if values:
                is_geom_null, x_min, y_min, x_max, y_max, srid = values
                return is_geom_null, x_min, y_min, x_max, y_max, srid
            else:
                return None

    except (Exception, psycopg2.Error) as error:
        gen_f.critical_log(
            func=compute_cdb_schema_extents,
            location=FILE_LOCATION,
            header=f"Computing extents of the schema '{dlg.CDB_SCHEMA}'",
            error=error)
        dlg.conn.rollback()


def exec_gview_counter(dlg: CDB4LoaderDialog, layer: CDBLayer) -> int:
    """Calls the qgis_pkg function that counts the number of geometry objects found within the selected extents.

    *   :returns: Number of objects.
        :rtype: int
    """
    # Convert QgsRectanlce into WKT polygon format
    extents = dlg.CURRENT_EXTENTS.asWktPolygon()
    
    # Prepare query to execute server function to get the number of objects in extents.
    query = pysql.SQL("""
        SELECT {_qgis_pkg_schema}.gview_counter({_usr_schema},{_cdb_schema},{_gv_name},{_extents});
        """).format(
        _qgis_pkg_schema = pysql.Identifier(dlg.QGIS_PKG_SCHEMA),
        _usr_schema = pysql.Literal(dlg.USR_SCHEMA),
        _cdb_schema = pysql.Literal(dlg.CDB_SCHEMA),
        _gv_name = pysql.Literal(layer.gv_name),  
        _extents = pysql.Literal(extents)
        )

    try:
        with dlg.conn.cursor() as cur:
            cur.execute(query)
            count = cur.fetchone()[0] # Tuple has trailing comma.
        dlg.conn.commit()

        # Assign the result to the view object.
        layer.n_selected = count
        return count

    except (Exception, psycopg2.Error) as error:
        gen_f.critical_log(
            func=exec_gview_counter,
            location=FILE_LOCATION,
            header=f"Counting number of geometries objects in layer {layer.layer_name} (via gview {layer.gv_name})",
            error=error)
        dlg.conn.rollback()


def has_layers_for_cdb_schema(dlg: CDB4LoaderDialog) -> bool:
    """Calls the qgis_pkg function that determines whether the {usr_schema} has layers
    regarding the current {cdb_schema}.

    *   :returns: status
        :rtype: bool
    """
    # Prepare query to check if there are already layers for the current cdb_schema and ADE (if not null)
    query = pysql.SQL("""
        SELECT {_qgis_pkg_schema}.has_layers_for_cdb_schema({_usr_schema},{_cdb_schema},{_ade_prefix});
        """).format(
        _qgis_pkg_schema = pysql.Identifier(dlg.QGIS_PKG_SCHEMA),
        _usr_schema = pysql.Literal(dlg.USR_SCHEMA),
        _cdb_schema = pysql.Literal(dlg.CDB_SCHEMA),
        _ade_prefix = pysql.Literal(dlg.ADE_PREFIX)
        )

    try:
        with dlg.conn.cursor() as cur:
            cur.execute(query)
            result_bool = cur.fetchone()[0] # Tuple has trailing comma.
        dlg.conn.commit()
        return result_bool

    except (Exception, psycopg2.Error) as error:
        gen_f.critical_log(
            func=has_layers_for_cdb_schema,
            location=FILE_LOCATION,
            header=f"Checking whether layers already exist for schema {dlg.CDB_SCHEMA}",
            error=error)
        dlg.conn.rollback()


def upsert_extents(dlg: CDB4LoaderDialog, 
                   bbox_type: Literal[BBoxType.CDB_SCHEMA, BBoxType.MAT_VIEW, BBoxType.QGIS],
                   extents_wkt_2d_poly: Optional[str]
                   ) -> Optional[int]:
    """Calls a QGIS Package function to insert (or update) the extents geometry in table qgis_{usr}.extents.

    *   :param bbox_type: BBoxType(enum), one of ["db_schema", "m_view", "qgis"]
        :type bbox_type: str

    *   :param extents_wkt_2d_poly: wkt of a polygon, 2D and _withouth_ SRID
        :type extents_wkt_2d_poly: str

    *   :returns: upserted_id
        :rtype: int
    """

    # Get the value associated to the enumeration member
    bbox_type_value = bbox_type.value

    # Prepare query to upsert the extents of the current cdb_schema
    query = pysql.SQL("""
        SELECT {_qgis_pkg_schema}.upsert_extents({_usr_schema},{_cdb_schema},{_bbox_type},{_extents},{_is_geographic});
        """).format(
        _qgis_pkg_schema = pysql.Identifier(dlg.QGIS_PKG_SCHEMA),
        _usr_schema = pysql.Literal(dlg.USR_SCHEMA),
        _cdb_schema = pysql.Literal(dlg.CDB_SCHEMA),
        _bbox_type = pysql.Literal(bbox_type_value),
        _extents = pysql.Literal(extents_wkt_2d_poly),
        _is_geographic = pysql.Literal(dlg.CRS_is_geographic)
        )

    try:
        with dlg.conn.cursor() as cur:
            cur.execute(query)
            upserted_id = cur.fetchone()[0] # Tuple has trailing comma.
        dlg.conn.commit()
        if upserted_id:
            return upserted_id
        else:
            return None

    except (Exception, psycopg2.Error) as error:
        gen_f.critical_log(
            func=upsert_extents,
            location=FILE_LOCATION,
            header=f"Upserting '{bbox_type}' extents",
            error=error)
        dlg.conn.rollback()


def list_unique_feature_types(dlg: CDB4LoaderDialog) -> Union[tuple[str, ...], tuple[()]]:
    """SQL query that retrieves the unique available feature types (CityGML modules)
    in the current cdb_schema and within the selection bounding box.

    *   :returns: unique feature types (e.g. ("Building", "Vegetation", "Transportation"))
        :rtype: tuple[str, ...]
    """
    extents_wkt: Optional[str]

    if dlg.CDB_SCHEMA_EXTENTS == dlg.LAYER_EXTENTS:
        extents_wkt = None
    else:
        # Convert QgsRectangle into WKT polygon format
        extents_wkt = dlg.CURRENT_EXTENTS.asWktPolygon()  

    query = pysql.SQL("""
        SELECT feature_type 
        FROM qgis_pkg.feature_type_checker({_cdb_schema},{_ade_prefix},{_extents}) 
        WHERE exists_in_db IS TRUE 
        ORDER BY feature_type;
        """).format(
        _cdb_schema = pysql.Literal(dlg.CDB_SCHEMA),
        _ade_prefix = pysql.Literal(dlg.ADE_PREFIX),
        _extents = pysql.Literal(extents_wkt)
        )

    try:
        with dlg.conn.cursor() as cur:
            cur.execute(query)
            res = cur.fetchall()
        dlg.conn.commit()
        #feat_types = tuple(elem[0] for elem in cast(Iterable[tuple[str, ...]], res))
        if res:
            feat_types: tuple[str, ...]
            feat_types = tuple(zip(*res))[0]
        else:
            feat_types = ()
        return feat_types

    except (Exception, psycopg2.Error) as error:
        dlg.conn.rollback()
        gen_f.critical_log(
            func=list_unique_feature_types,
            location=FILE_LOCATION,
            header="Retrieving list of available feature types in selected area",
            error=error)


def list_unique_feature_types_in_layer_metadata(dlg: CDB4LoaderDialog) -> Union[tuple[str, ...], tuple[()]]:
    """SQL query that retrieves the list of unique feature types (CityGML modules) in
    table layer_metadata 

    *   :returns: Tuple of unique feature types
        :rtype: tuple[str, ...]
    """

    query = pysql.SQL("""
        SELECT DISTINCT feature_type 
        FROM {_usr_schema}.layer_metadata
        WHERE cdb_schema = {_cdb_schema} AND ade_prefix IS NOT DISTINCT FROM {_ade_prefix} AND feature_type IS NOT NULL
        ORDER BY feature_type ASC;
        """).format(
        _usr_schema = pysql.Identifier(dlg.USR_SCHEMA),
        _cdb_schema = pysql.Literal(dlg.CDB_SCHEMA),
        _ade_prefix = pysql.Literal(dlg.ADE_PREFIX)
        )

    try:
        with dlg.conn.cursor() as cur:
            cur.execute(query)
            res = cur.fetchall()
        dlg.conn.commit()

        if not res:
            feat_types = ()
        else:
            #feat_types = tuple(elem[0] for elem in cast(Iterable[tuple[str]], res))
            feat_types: tuple[str, ...]
            feat_types = tuple(zip(*res))[0]
            # print(feat_types)
        
        return feat_types

    except (Exception, psycopg2.Error) as error:
        gen_f.critical_log(
            func=list_unique_feature_types_in_layer_metadata,
            location=FILE_LOCATION,
            header=f"Retrieving unique Feature Types in {dlg.USR_SCHEMA}.layer_metadata for cdb_schema {dlg.CDB_SCHEMA}",
            error=error)
        dlg.conn.rollback()


def get_enum_lookup_config(dlg: CDB4LoaderDialog) -> list[LookupTableConfig]:
    """SQL query that retrieves the configuration values to set up
    the look-up tables containing enumerations via combo boxes
    in the attribute forms
    
    *   :returns: the contents of table enum_lookup_config as NamedTuples
        :rtype: list[LookupTableConfig] 
    """
    if not dlg.ADE_PREFIX:
        query = pysql.SQL("""
            SELECT * FROM {_qgis_pkg_schema}.enum_lookup_config
            WHERE ade_prefix IS NULL
            ORDER BY id;
            """).format(
            _qgis_pkg_schema = pysql.Identifier(dlg.QGIS_PKG_SCHEMA)
            )
    else: 
        query = pysql.SQL("""
            SELECT * FROM {_qgis_pkg_schema}.enum_lookup_config
            WHERE ade_prefix IS NULL OR ade_prefix = {_ade_prefix}
            ORDER BY id;
            """).format(
            _qgis_pkg_schema = pysql.Identifier(dlg.QGIS_PKG_SCHEMA),
            _ade_prefix = pysql.Literal(dlg.ADE_PREFIX)
            )

    try:
        with dlg.conn.cursor(cursor_factory=NamedTupleCursor) as cur:
            cur.execute(query)
            res = cur.fetchall()
        dlg.conn.commit()

        if not res:
            res = []
        return res

    except (Exception, psycopg2.Error) as error:
        gen_f.critical_log(
            func=get_enum_lookup_config,
            location=FILE_LOCATION,
            header=f"Retrieving data from table '{dlg.QGIS_PKG_SCHEMA}.enum_lookup_config'",
            error=error)
        dlg.conn.rollback()


def get_codelist_lookup_config(dlg: CDB4LoaderDialog, codelist_set_name: str) -> list[LookupTableConfig]:
    """SQL query that retrieves the configuration values to set up
    the look-up tables containing codelists via combo boxes
    in the attribute forms

    *   :returns: the contents of table codelist_lookup_config as NamedTuples
        :rtype: list[LookupTableConfig]     
    """

    query = pysql.SQL("""
        SELECT * FROM {_usr_schema}.codelist_lookup_config
        WHERE name = {_codelist_set_name}
        ORDER BY id;
        """).format(
        _usr_schema = pysql.Identifier(dlg.USR_SCHEMA),
        _codelist_set_name = pysql.Literal(codelist_set_name)
        )

    try:
        with dlg.conn.cursor(cursor_factory=NamedTupleCursor) as cur:
            cur.execute(query)
            res = cur.fetchall()
        dlg.conn.commit()

        if not res:
            res = []

        return res

    except (Exception, psycopg2.Error) as error:
        gen_f.critical_log(
            func=get_codelist_lookup_config,
            location=FILE_LOCATION,
            header=f"Retrieving data from table '{dlg.USR_SCHEMA}.codelist_lookup_config'",
            error=error)
        dlg.conn.rollback()


def list_CityGML_codelist_set_names(dlg: CDB4LoaderDialog) -> Union[tuple[str, ...], tuple[()]]:
    """SQL query that retrieves the codelist set names to fill the codelist selection box 
    
    *   :returns: the unique names in table codelist_lookup_config
        :rtype: Union[tuple[str, ...], tuple[()]]
    """
    query = pysql.SQL("""
        SELECT DISTINCT name FROM {_usr_schema}.codelist_lookup_config
        WHERE ade_prefix IS NULL
        ORDER BY name;
        """).format(
        _usr_schema = pysql.Identifier(dlg.USR_SCHEMA)
        )

    try:
        with dlg.conn.cursor() as cur:
            cur.execute(query)
            res = cur.fetchall()
        dlg.conn.commit()

        if not res:
            codelist_set_names = ()
        else:
            # codelist_set_names = tuple(elem[0] for elem in cast(Iterable[tuple[str, ...]], res))
            codelist_set_names: tuple[str, ...]
            codelist_set_names = tuple(zip(*res))[0]
     
        return codelist_set_names

    except (Exception, psycopg2.Error) as error:
        gen_f.critical_log(
            func=list_CityGML_codelist_set_names,
            location=FILE_LOCATION,
            header=f"Retrieving CityGML codelist set from table '{dlg.USR_SCHEMA}.codelist_lookup_config'",
            error=error)
        dlg.conn.rollback()


# def fetch_ADE_codelist_set_names(dlg: CDB4LoaderDialog) -> list:
#     """SQL query that retrieves the codelist set names to fill the codelist selection box 
    
#     *   :returns: the unique names in table codelist_lookup_config
#         :rtype: list of tuples
#     """
#     query = pysql.SQL("""
#         SELECT DISTINCT name FROM {_usr_schema}.codelist_lookup_config
#         WHERE ade_prefix = {_ade_prefix}
#         ORDER BY name;
#         """).format(
#         _usr_schema = pysql.Identifier(dlg.USR_SCHEMA),
#         _ade_prefix = pysql.Identifier(dlg.ADE_PREFIX)
#         )

#     try:
#         # with dlg.conn.cursor(cursor_factory=NamedTupleCursor) as cur:
#         with dlg.conn.cursor() as cur:
#             cur.execute(query)
#             res = cur.fetchall()
#         dlg.conn.commit()

#         codelist_set_names = [elem[0] for elem in res]

#         if not codelist_set_names:
#             codelist_set_names = []
     
#         return codelist_set_names

#     except (Exception, psycopg2.Error) as error:
#         gen_f.critical_log(
#             func=fetch_ADE_codelist_set_names,
#             location=FILE_LOCATION,
#             header=f"Retrieving ADE codelist set from table '{dlg.USR_SCHEMA}.codelist_lookup_config'",
#             error=error)
#         dlg.conn.rollback()