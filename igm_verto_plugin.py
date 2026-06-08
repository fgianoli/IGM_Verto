# -*- coding: utf-8 -*-
"""Classe principale del plugin IGM Verto Coordinate Converter."""

import os

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMenu, QToolButton

from qgis.core import QgsApplication

PLUGIN_DIR = os.path.dirname(__file__)


class IgmVertoPlugin(object):
    """Plugin QGIS 3/4 per la conversione coordinate via API IGM Verto."""

    def __init__(self, iface):
        self.iface = iface
        self.actions = []
        self.menu_name = "IGM Verto"
        self.toolbar = None
        self.menu = None
        self.provider = None
        self.map_tool = None
        self.map_tool_action = None
        self.tool_button = None
        self._dialog = None

    # ------------------------------------------------------------------ utils
    @staticmethod
    def tr(message):
        return QCoreApplication.translate("IgmVerto", message)

    def _icon(self, name="icon.svg"):
        path = os.path.join(PLUGIN_DIR, name)
        if not os.path.exists(path):
            path = os.path.join(PLUGIN_DIR, "icon.svg")
        return QIcon(path)

    def _make_action(self, text, callback, icon="icon.svg",
                     checkable=False, tooltip=None):
        action = QAction(self._icon(icon), text, self.iface.mainWindow())
        action.triggered.connect(callback)
        action.setCheckable(checkable)
        if tooltip:
            action.setToolTip(tooltip)
            action.setStatusTip(tooltip)
        self.actions.append(action)
        return action

    # --------------------------------------------------------------- GUI init
    def initGui(self):  # noqa: N802
        self.toolbar = self.iface.addToolBar(self.menu_name)
        self.toolbar.setObjectName("IgmVertoToolbar")

        # Azioni (condivise tra menu a tendina e barra dei menu principale)
        act_convert = self._make_action(
            self.tr("Conversione coordinate..."), self.open_dialog,
            icon=os.path.join("icons", "convert.svg"),
            tooltip=self.tr("Converti coordinate manuali, CSV o layer con i "
                            "grigliati IGM"))
        self.map_tool_action = self._make_action(
            self.tr("Click sulla mappa"), self.toggle_map_tool,
            icon=os.path.join("icons", "map.svg"), checkable=True,
            tooltip=self.tr("Clicca un punto sulla mappa e leggi le coordinate "
                            "convertite"))
        act_settings = self._make_action(
            self.tr("Impostazioni..."), self.open_settings,
            icon=os.path.join("icons", "settings.svg"),
            tooltip=self.tr("Credenziali, endpoint e aggiornamento elenco SRS"))
        act_help = self._make_action(
            self.tr("Guida..."), self.open_help,
            icon=os.path.join("icons", "help.svg"),
            tooltip=self.tr("Come funziona il plugin"))

        # Menu a tendina con un'unica icona nella toolbar
        self.tool_button = QToolButton(self.toolbar)
        self.tool_button.setIcon(self._icon())
        self.tool_button.setText(self.menu_name)
        self.tool_button.setToolTip(self.tr("IGM Verto - conversione coordinate"))
        self.tool_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup)

        self.menu = QMenu(self.menu_name, self.tool_button)
        self.menu.setIcon(self._icon())
        self.menu.addAction(act_convert)
        self.menu.addAction(self.map_tool_action)
        self.menu.addSeparator()
        self.menu.addAction(act_settings)
        self.menu.addAction(act_help)

        self.tool_button.setMenu(self.menu)
        self.toolbar.addWidget(self.tool_button)

        # Stesse voci nella barra dei menu principale (Plugin -> IGM Verto)
        self.iface.addPluginToMenu(self.menu_name, act_convert)
        self.iface.addPluginToMenu(self.menu_name, self.map_tool_action)
        self.iface.addPluginToMenu(self.menu_name, act_settings)
        self.iface.addPluginToMenu(self.menu_name, act_help)

        # Registra il provider Processing
        self._init_processing()

    def _init_processing(self):
        try:
            from .processing.provider import VertoProcessingProvider
            self.provider = VertoProcessingProvider()
            QgsApplication.processingRegistry().addProvider(self.provider)
        except Exception as exc:  # pragma: no cover
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(
                "Impossibile registrare il provider Processing: {}".format(exc),
                "IGM Verto", Qgis.MessageLevel.Warning,
            )

    def unload(self):
        for action in self.actions:
            try:
                self.iface.removePluginMenu(self.menu_name, action)
            except Exception:
                pass
        if self.map_tool is not None:
            try:
                self.iface.mapCanvas().unsetMapTool(self.map_tool)
            except Exception:
                pass
            self.map_tool = None
        if self.menu is not None:
            self.menu.deleteLater()
            self.menu = None
        if self.tool_button is not None:
            self.tool_button.deleteLater()
            self.tool_button = None
        if self.toolbar is not None:
            self.toolbar.deleteLater()
            self.toolbar = None
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
        self.actions = []

    # ------------------------------------------------------------- callbacks
    def open_dialog(self):
        from .dialogs.main_dialog import MainDialog
        if self._dialog is None:
            self._dialog = MainDialog(self.iface, self.iface.mainWindow())
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()

    def open_settings(self):
        from .dialogs.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self.iface.mainWindow())
        dlg.exec()

    def open_help(self):
        from .dialogs.help_dialog import HelpDialog
        dlg = HelpDialog(self.iface.mainWindow())
        dlg.exec()

    def toggle_map_tool(self, checked):
        from .map_tool import VertoMapTool
        canvas = self.iface.mapCanvas()
        if checked:
            if self.map_tool is None:
                self.map_tool = VertoMapTool(self.iface)
                self.map_tool.setAction(self.map_tool_action)
            canvas.setMapTool(self.map_tool)
        else:
            if self.map_tool is not None:
                canvas.unsetMapTool(self.map_tool)
