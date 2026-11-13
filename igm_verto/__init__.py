# -*- coding: utf-8 -*-
"""IGM Verto Coordinate Converter - plugin QGIS 3/4."""


def classFactory(iface):  # noqa: N802 (nome richiesto da QGIS)
    from .igm_verto_plugin import IgmVertoPlugin
    return IgmVertoPlugin(iface)
