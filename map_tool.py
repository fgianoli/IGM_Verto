# -*- coding: utf-8 -*-
"""Strumento di click sulla mappa: legge un punto e ne mostra la conversione IGM."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QApplication
from qgis.gui import QgsMapToolEmitPoint
from qgis.core import Qgis

from . import settings
from . import converter
from . import verto_api
from .dialogs.srs_combo import pick_target_srs


class VertoMapTool(QgsMapToolEmitPoint):
    """Clicca un punto: converte dalla CRS del progetto a un SRS scelto."""

    def __init__(self, iface):
        self.iface = iface
        self.canvas = iface.mapCanvas()
        super().__init__(self.canvas)
        self.target_epsg = None

    def canvasReleaseEvent(self, event):
        point = self.toMapCoordinates(event.pos())
        project_crs = self.canvas.mapSettings().destinationCrs()
        in_epsg = converter.crs_to_epsg(project_crs)
        if in_epsg is None:
            self.iface.messageBar().pushMessage(
                "IGM Verto",
                "CRS del progetto non in formato EPSG: impossibile convertire.",
                level=Qgis.MessageLevel.Warning,
            )
            return

        # Sceglie l'SRS di destinazione al primo click (o se non impostato)
        if self.target_epsg is None:
            epsg = pick_target_srs(self.canvas, exclude_epsg=in_epsg)
            if epsg is None:
                return
            if converter.same_datum(in_epsg, epsg):
                self.iface.messageBar().pushMessage(
                    "IGM Verto",
                    "Origine e destinazione hanno lo stesso datum: "
                    "conversione non supportata dal servizio IGM.",
                    level=Qgis.MessageLevel.Warning)
                return
            self.target_epsg = epsg

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = verto_api.convert(
                in_epsg, self.target_epsg, [(point.x(), point.y())],
                utente=settings.get_utente(), chiave=settings.get_chiave(),
                endpoint=settings.get_endpoint(),
                max_coord=settings.get_max_coord(),
            )
        except verto_api.VertoError as exc:
            QApplication.restoreOverrideCursor()
            self.iface.messageBar().pushMessage(
                "IGM Verto", "Errore: {}".format(exc),
                level=Qgis.MessageLevel.Critical,
            )
            return
        finally:
            QApplication.restoreOverrideCursor()

        e, n = result[0]
        msg = ("EPSG:{} → EPSG:{}  |  origine: E={:.6f} N={:.6f}  →  "
               "E={:.6f}  N={:.6f}").format(
            in_epsg, self.target_epsg, point.x(), point.y(), e, n)
        self.iface.messageBar().pushMessage(
            "IGM Verto", msg, level=Qgis.MessageLevel.Info, duration=15)

    def deactivate(self):
        self.target_epsg = None
        super().deactivate()
