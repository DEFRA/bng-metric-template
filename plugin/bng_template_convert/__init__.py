"""BNG Template Convert — move habitat mapping between the two BNG QGIS templates."""


def classFactory(iface):
    from .plugin import BngTemplateConvertPlugin

    return BngTemplateConvertPlugin(iface)
