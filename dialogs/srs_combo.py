# -*- coding: utf-8 -*-
"""ComboBox per la scelta dei sistemi di riferimento supportati da IGM Verto."""

from qgis.PyQt.QtWidgets import (
    QComboBox, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
)

from qgis.PyQt.QtCore import Qt

from .. import settings
from .. import verto_api


class SrsComboBox(QComboBox):
    """Combo dei SRS supportati; il dato utente di ogni voce e' il codice EPSG."""

    def __init__(self, parent=None, exclude_epsg=None):
        super().__init__(parent)
        self.setEditable(True)
        self.populate(exclude_epsg=exclude_epsg)

    def populate(self, force_refresh=False, exclude_epsg=None):
        current = self.current_epsg()
        self.clear()
        _, srs_list = settings.load_srs(force_refresh=force_refresh)
        for srs in srs_list:
            epsg = srs.get("epsg")
            if exclude_epsg is not None and epsg == exclude_epsg:
                continue
            label = "EPSG:{} - {}".format(epsg, srs.get("descrizione", ""))
            self.addItem(label, epsg)
            note = verto_api.alias_notice(epsg)
            if note:
                idx = self.count() - 1
                self.setItemText(idx, label + " [via EPSG:{}]".format(
                    verto_api.SERVER_ALIAS[int(epsg)]))
                self.setItemData(idx, note, Qt.ItemDataRole.ToolTipRole)
        if current is not None:
            self.set_current_epsg(current)

    def current_epsg(self):
        data = self.currentData()
        if data is not None:
            return int(data)
        # tentativo di parse dal testo "EPSG:1234 - ..."
        text = self.currentText().strip()
        if text.upper().startswith("EPSG:"):
            try:
                return int(text.split(":")[1].split("-")[0].strip())
            except (ValueError, IndexError):
                return None
        if text.isdigit():
            return int(text)
        return None

    def set_current_epsg(self, epsg):
        for i in range(self.count()):
            if self.itemData(i) == epsg:
                self.setCurrentIndex(i)
                return True
        return False


def pick_target_srs(parent=None, exclude_epsg=None):
    """Mini-dialog per scegliere l'SRS di destinazione. Ritorna EPSG o None."""
    dlg = QDialog(parent)
    dlg.setWindowTitle("Sistema di destinazione")
    layout = QVBoxLayout(dlg)
    layout.addWidget(QLabel("Converti le coordinate verso:"))
    combo = SrsComboBox(dlg, exclude_epsg=exclude_epsg)
    layout.addWidget(combo)
    btns = QHBoxLayout()
    ok = QPushButton("OK")
    cancel = QPushButton("Annulla")
    btns.addStretch(1)
    btns.addWidget(ok)
    btns.addWidget(cancel)
    layout.addLayout(btns)
    ok.clicked.connect(dlg.accept)
    cancel.clicked.connect(dlg.reject)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        return combo.current_epsg()
    return None
