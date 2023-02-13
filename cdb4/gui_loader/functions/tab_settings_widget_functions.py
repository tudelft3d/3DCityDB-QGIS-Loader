"""This module contains reset functions for each QT widgets.

The logic behind all of the functions is to reset widgets as individual
objects or as block of objects, depending on the needs.

The reset functions consist of clearing text or changed text to original state,
clearing widget items or selections and deactivating widgets.
"""
from ....cdb_tools_main import CDBToolsMain # Used only to add the type of the function parameters

from ...shared.functions import general_functions as gen_f

FILE_LOCATION = gen_f.get_file_relative_path(file=__file__)

####################################################
## Reset widget functions for 'Settings' tab
####################################################

def tabSettings_reset(cdbMain: CDBToolsMain) -> None:
    """Function to reset the 'Settings' tab
    """
    dlg = cdbMain.loader_dlg
    dlg.tabSettings.setDisabled(True)
    gbxGeomSimp_reset(cdbMain)
    gbxLayerOptions_reset(cdbMain)
    gbxMisc_reset(cdbMain)

    return None

def gbxGeomSimp_reset(cdbMain: CDBToolsMain) -> None:
    """Function to reset the 'Geometry simplification' groupbox to the DEFAULT values
    """
    dlg = cdbMain.loader_dlg

    dlg.gbxGeomSimp.setChecked(False)
    dlg.qspbDecimalPrec.setValue(dlg.settings.simp_geom_dec_prec_default)
    dlg.qspbMinArea.setValue(dlg.settings.simp_geom_min_area_default)

    return None

def gbxLayerOptions_reset(cdbMain: CDBToolsMain) -> None:
    """Function to reset the 'Layer Options' groupbox to the DEFAULT values
    """
    dlg = cdbMain.loader_dlg

    dlg.gbxGeomSimp.setChecked(False)
    dlg.qspbMaxFeatImport.setValue(dlg.settings.max_features_to_import_default)
    dlg.cbxForceLayerGen.setChecked(dlg.settings.force_all_layers_creation_default)

    return None

def gbxMisc_reset(cdbMain: CDBToolsMain) -> None:
    """Function to reset the 'Miscellaneous option' groupbox to the DEFAULT values
    """
    dlg = cdbMain.loader_dlg

    dlg.cbxEnable3D.setChecked(dlg.settings.enable_3d_renderer_default)

    return None

