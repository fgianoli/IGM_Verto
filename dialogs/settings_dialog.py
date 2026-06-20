# -*- coding: utf-8 -*-
"""Dialog impostazioni: credenziali, endpoint, aggiornamento elenco SRS."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QFormLayout, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QLabel, QMessageBox, QApplication, QDialogButtonBox
)

from .. import settings
from .. import verto_api


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("IGM Verto - Impostazioni")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Le credenziali utente/chiave sono attualmente ignorate dal "
            "servizio IGM ma obbligatorie nella richiesta. Puoi lasciarle "
            "ai valori predefiniti."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self.utente_edit = QLineEdit(settings.get_utente())
        self.chiave_edit = QLineEdit(settings.get_chiave())
        self.endpoint_edit = QLineEdit(settings.get_endpoint())
        form.addRow("Utente:", self.utente_edit)
        form.addRow("Chiave:", self.chiave_edit)
        form.addRow("Endpoint API:", self.endpoint_edit)
        layout.addLayout(form)

        refresh_row = QHBoxLayout()
        self.refresh_btn = QPushButton("Aggiorna elenco SRS dal server")
        self.status_lbl = QLabel("")
        refresh_row.addWidget(self.refresh_btn)
        refresh_row.addWidget(self.status_lbl, 1)
        layout.addLayout(refresh_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(buttons)

        self.refresh_btn.clicked.connect(self.refresh_srs)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)

        cached = settings.get_cached_srs()
        if cached:
            self.status_lbl.setText("{} SRS in cache.".format(len(cached)))

    def refresh_srs(self):
        # Salva prima l'endpoint corrente per usarlo nella richiesta
        settings.set_endpoint(self.endpoint_edit.text().strip())
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            max_coord, srs = settings.load_srs(force_refresh=True)
        except verto_api.VertoError as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "IGM Verto", "Errore: {}".format(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.status_lbl.setText(
            "{} SRS aggiornati (max {} coord/richiesta).".format(
                len(srs), max_coord)
        )

    def save(self):
        settings.set_utente(self.utente_edit.text().strip() or "qgis")
        settings.set_chiave(self.chiave_edit.text().strip() or "qgis")
        settings.set_endpoint(self.endpoint_edit.text().strip())
        self.accept()
