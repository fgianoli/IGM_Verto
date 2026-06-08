# -*- coding: utf-8 -*-
"""Dialog principale: conversione manuale, da CSV e di layer vettoriali."""

import csv
import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QTabWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QPushButton, QPlainTextEdit, QLineEdit, QCheckBox, QComboBox, QSpinBox,
    QFileDialog, QMessageBox, QApplication, QProgressDialog, QWidget, QGroupBox
)

from qgis.core import QgsProject, QgsMapLayerProxyModel
from qgis.gui import QgsMapLayerComboBox

from .. import settings
from .. import verto_api
from .. import converter
from .srs_combo import SrsComboBox


def _vector_filter():
    try:
        return QgsMapLayerProxyModel.Filter.VectorLayer
    except AttributeError:  # QGIS 3 / PyQt5
        return QgsMapLayerProxyModel.VectorLayer


def _api_kwargs():
    return dict(
        utente=settings.get_utente(),
        chiave=settings.get_chiave(),
        endpoint=settings.get_endpoint(),
        max_coord=settings.get_max_coord(),
    )


class MainDialog(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("IGM Verto - Conversione coordinate")
        self.setMinimumSize(640, 520)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.tabs.addTab(self._build_manual_tab(), "Coordinate manuali")
        self.tabs.addTab(self._build_csv_tab(), "File CSV")
        self.tabs.addTab(self._build_layer_tab(), "Layer vettoriale")

        credit = QLabel(
            'Conversioni: <a href="https://igmi.esercito.difesa.it/servizi/'
            'verto-online/">IGM &ndash; Verto Online</a> &middot; uso libero '
            '(anche commerciale) secondo le Condizioni d\'uso IGM.')
        credit.setOpenExternalLinks(True)
        credit.setWordWrap(True)
        layout.addWidget(credit)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("Chiudi")
        close_btn.clicked.connect(self.close)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

    # ------------------------------------------------------ widget condivisi
    def _srs_row(self, default_in=None, default_out=None):
        in_combo = SrsComboBox()
        out_combo = SrsComboBox()
        if default_in:
            in_combo.set_current_epsg(default_in)
        if default_out:
            out_combo.set_current_epsg(default_out)
        return in_combo, out_combo

    # -------------------------------------------------------- TAB: manuale
    def _build_manual_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        form = QFormLayout()
        self.m_in, self.m_out = self._srs_row(4265, 6706)
        form.addRow("Sistema di origine:", self.m_in)
        form.addRow("Sistema di destinazione:", self.m_out)
        v.addLayout(form)

        v.addWidget(QLabel(
            "Inserisci una coordinata per riga, formato: E[,; spazio o tab]N\n"
            "E = est/longitudine, N = nord/latitudine. "
            "Coordinate geografiche in gradi sessadecimali."))

        io = QHBoxLayout()
        in_box = QVBoxLayout()
        in_box.addWidget(QLabel("Input:"))
        self.m_input = QPlainTextEdit()
        self.m_input.setPlaceholderText("7.0, 37.0\n12.0, 42.0")
        in_box.addWidget(self.m_input)
        out_box = QVBoxLayout()
        out_box.addWidget(QLabel("Risultato:"))
        self.m_output = QPlainTextEdit()
        self.m_output.setReadOnly(True)
        out_box.addWidget(self.m_output)
        io.addLayout(in_box)
        io.addLayout(out_box)
        v.addLayout(io)

        btns = QHBoxLayout()
        swap = QPushButton("Scambia origine/destinazione")
        swap.clicked.connect(self._manual_swap)
        conv = QPushButton("Converti")
        conv.clicked.connect(self._manual_convert)
        copy = QPushButton("Copia risultato")
        copy.clicked.connect(
            lambda: QApplication.clipboard().setText(self.m_output.toPlainText()))
        btns.addWidget(swap)
        btns.addStretch(1)
        btns.addWidget(copy)
        btns.addWidget(conv)
        v.addLayout(btns)
        return w

    def _manual_swap(self):
        a, b = self.m_in.current_epsg(), self.m_out.current_epsg()
        if a:
            self.m_out.set_current_epsg(a)
        if b:
            self.m_in.set_current_epsg(b)

    @staticmethod
    def _parse_line(line):
        for sep in (",", ";", "\t"):
            line = line.replace(sep, " ")
        parts = [p for p in line.split() if p]
        if len(parts) < 2:
            raise ValueError("servono due valori (E e N)")
        return float(parts[0]), float(parts[1])

    def _manual_convert(self):
        in_epsg = self.m_in.current_epsg()
        out_epsg = self.m_out.current_epsg()
        if not in_epsg or not out_epsg:
            QMessageBox.warning(self, "IGM Verto", "Seleziona i sistemi EPSG.")
            return
        coords = []
        for i, line in enumerate(self.m_input.toPlainText().splitlines(), 1):
            if not line.strip():
                continue
            try:
                coords.append(self._parse_line(line))
            except ValueError as exc:
                QMessageBox.warning(
                    self, "IGM Verto", "Riga {}: {}".format(i, exc))
                return
        if not coords:
            QMessageBox.information(self, "IGM Verto", "Nessuna coordinata.")
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = verto_api.convert(in_epsg, out_epsg, coords, **_api_kwargs())
        except verto_api.VertoError as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "IGM Verto", "Errore: {}".format(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.m_output.setPlainText(
            "\n".join("{:.8f}, {:.8f}".format(e, n) for e, n in result))

    # ------------------------------------------------------------ TAB: CSV
    def _build_csv_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        in_grp = QGroupBox("File di input")
        ig = QFormLayout(in_grp)
        self.c_in_path = QLineEdit()
        in_browse = QPushButton("Sfoglia...")
        in_browse.clicked.connect(self._csv_browse_in)
        row = QHBoxLayout()
        row.addWidget(self.c_in_path)
        row.addWidget(in_browse)
        ig.addRow("CSV input:", self._wrap(row))

        self.c_delim = QComboBox()
        self.c_delim.addItems([", (virgola)", "; (punto e virgola)", "tab", "spazio"])
        ig.addRow("Separatore:", self.c_delim)
        self.c_header = QCheckBox("La prima riga e' un'intestazione")
        self.c_header.setChecked(True)
        ig.addRow("", self.c_header)
        self.c_col_e = QSpinBox(); self.c_col_e.setMinimum(1); self.c_col_e.setValue(1)
        self.c_col_n = QSpinBox(); self.c_col_n.setMinimum(1); self.c_col_n.setValue(2)
        ig.addRow("Colonna E (est/lon), n.:", self.c_col_e)
        ig.addRow("Colonna N (nord/lat), n.:", self.c_col_n)
        v.addWidget(in_grp)

        form = QFormLayout()
        self.c_in, self.c_out = self._srs_row(4265, 6706)
        form.addRow("Sistema di origine:", self.c_in)
        form.addRow("Sistema di destinazione:", self.c_out)
        v.addLayout(form)

        out_grp = QGroupBox("Output")
        og = QFormLayout(out_grp)
        self.c_out_path = QLineEdit()
        out_browse = QPushButton("Sfoglia...")
        out_browse.clicked.connect(self._csv_browse_out)
        orow = QHBoxLayout()
        orow.addWidget(self.c_out_path)
        orow.addWidget(out_browse)
        og.addRow("CSV output:", self._wrap(orow))
        self.c_load = QCheckBox("Carica il risultato come layer di punti")
        self.c_load.setChecked(True)
        og.addRow("", self.c_load)
        v.addWidget(out_grp)

        v.addStretch(1)
        conv = QPushButton("Converti CSV")
        conv.clicked.connect(self._csv_convert)
        v.addWidget(conv)
        return w

    @staticmethod
    def _wrap(layout):
        c = QWidget()
        c.setLayout(layout)
        return c

    def _csv_browse_in(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Seleziona CSV", "", "CSV (*.csv *.txt);;Tutti i file (*)")
        if path:
            self.c_in_path.setText(path)
            if not self.c_out_path.text():
                base, ext = os.path.splitext(path)
                self.c_out_path.setText(base + "_convertito.csv")

    def _csv_browse_out(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Salva CSV", "", "CSV (*.csv)")
        if path:
            self.c_out_path.setText(path)

    def _csv_delimiter(self):
        return {0: ",", 1: ";", 2: "\t", 3: " "}[self.c_delim.currentIndex()]

    def _csv_convert(self):
        in_path = self.c_in_path.text().strip()
        out_path = self.c_out_path.text().strip()
        if not in_path or not os.path.exists(in_path):
            QMessageBox.warning(self, "IGM Verto", "File di input non valido.")
            return
        if not out_path:
            QMessageBox.warning(self, "IGM Verto", "Specifica il file di output.")
            return
        in_epsg = self.c_in.current_epsg()
        out_epsg = self.c_out.current_epsg()
        if not in_epsg or not out_epsg:
            QMessageBox.warning(self, "IGM Verto", "Seleziona i sistemi EPSG.")
            return

        delim = self._csv_delimiter()
        ci = self.c_col_e.value() - 1
        cn = self.c_col_n.value() - 1
        try:
            with open(in_path, "r", newline="", encoding="utf-8-sig") as f:
                rows = list(csv.reader(f, delimiter=delim))
        except Exception as exc:
            QMessageBox.critical(self, "IGM Verto",
                                 "Lettura CSV fallita: {}".format(exc))
            return
        if not rows:
            QMessageBox.information(self, "IGM Verto", "CSV vuoto.")
            return

        header = None
        data_rows = rows
        if self.c_header.isChecked():
            header = rows[0]
            data_rows = rows[1:]

        coords = []
        valid_idx = []
        for idx, r in enumerate(data_rows):
            try:
                e = float(r[ci])
                n = float(r[cn])
            except (ValueError, IndexError):
                continue
            coords.append((e, n))
            valid_idx.append(idx)
        if not coords:
            QMessageBox.warning(
                self, "IGM Verto",
                "Nessuna coordinata valida nelle colonne indicate.")
            return

        progress = QProgressDialog("Conversione in corso...", "Annulla",
                                   0, len(coords), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)

        def cb(done, total):
            progress.setValue(done)
            QApplication.processEvents()

        try:
            result = verto_api.convert(in_epsg, out_epsg, coords,
                                       progress_cb=cb, **_api_kwargs())
        except verto_api.VertoError as exc:
            progress.close()
            QMessageBox.critical(self, "IGM Verto", "Errore: {}".format(exc))
            return
        progress.setValue(len(coords))

        conv_map = dict(zip(valid_idx, result))
        try:
            with open(out_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f, delimiter=delim)
                if header is not None:
                    writer.writerow(list(header) + ["E_out", "N_out"])
                for idx, r in enumerate(data_rows):
                    if idx in conv_map:
                        e, n = conv_map[idx]
                        writer.writerow(list(r) + ["{:.8f}".format(e),
                                                   "{:.8f}".format(n)])
                    else:
                        writer.writerow(list(r) + ["", ""])
        except Exception as exc:
            QMessageBox.critical(self, "IGM Verto",
                                 "Scrittura CSV fallita: {}".format(exc))
            return

        if self.c_load.isChecked():
            self._load_csv_as_points(out_path, out_epsg, delim)
        QMessageBox.information(
            self, "IGM Verto",
            "Conversione completata: {} coordinate.\nSalvato in:\n{}".format(
                len(coords), out_path))

    def _load_csv_as_points(self, path, epsg, delim=","):
        from qgis.PyQt.QtCore import QUrl
        from qgis.core import QgsVectorLayer
        crs = converter.epsg_to_crs(epsg)
        delim_enc = QUrl.toPercentEncoding(delim).data().decode("ascii")
        uri = ("file:///{}?delimiter={}&xField=E_out&yField=N_out&crs={}"
               ).format(path.lstrip("/"), delim_enc,
                        crs.authid() or ("EPSG:%d" % epsg))
        layer = QgsVectorLayer(uri, os.path.basename(path), "delimitedtext")
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)

    # ---------------------------------------------------------- TAB: layer
    def _build_layer_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        form = QFormLayout()
        self.l_combo = QgsMapLayerComboBox()
        self.l_combo.setFilters(_vector_filter())
        self.l_combo.layerChanged.connect(self._layer_changed)
        form.addRow("Layer:", self.l_combo)

        self.l_selected = QCheckBox("Solo elementi selezionati")
        form.addRow("", self.l_selected)

        self.l_in, self.l_out = self._srs_row(None, 6706)
        form.addRow("Sistema di origine:", self.l_in)
        form.addRow("Sistema di destinazione:", self.l_out)
        v.addLayout(form)

        v.addWidget(QLabel(
            "Crea un nuovo layer in memoria con le geometrie convertite "
            "tramite i grigliati IGM. L'EPSG di origine e' precompilato dal "
            "CRS del layer ma puo' essere modificato."))
        v.addStretch(1)
        conv = QPushButton("Riproietta layer")
        conv.clicked.connect(self._layer_convert)
        v.addWidget(conv)
        self._layer_changed(self.l_combo.currentLayer())
        return w

    def _layer_changed(self, layer):
        if layer is not None:
            epsg = converter.crs_to_epsg(layer.crs())
            if epsg:
                self.l_in.set_current_epsg(epsg)

    def _layer_convert(self):
        layer = self.l_combo.currentLayer()
        if layer is None:
            QMessageBox.warning(self, "IGM Verto", "Seleziona un layer.")
            return
        in_epsg = self.l_in.current_epsg()
        out_epsg = self.l_out.current_epsg()
        if not in_epsg or not out_epsg:
            QMessageBox.warning(self, "IGM Verto", "Seleziona i sistemi EPSG.")
            return
        sel = self.l_selected.isChecked()
        n_feat = layer.selectedFeatureCount() if sel else layer.featureCount()
        if sel and n_feat == 0:
            QMessageBox.warning(self, "IGM Verto", "Nessun elemento selezionato.")
            return

        progress = QProgressDialog("Riproiezione in corso...", "Annulla",
                                   0, 0, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.show()
        QApplication.processEvents()

        def cb(done, total):
            progress.setMaximum(total)
            progress.setValue(done)
            QApplication.processEvents()

        try:
            mem, n = converter.reproject_layer_to_memory(
                layer, out_epsg, selected_only=sel, in_epsg=in_epsg,
                progress_cb=cb, **_api_kwargs())
        except verto_api.VertoError as exc:
            progress.close()
            QMessageBox.critical(self, "IGM Verto", "Errore: {}".format(exc))
            return
        progress.close()
        QgsProject.instance().addMapLayer(mem)
        QMessageBox.information(
            self, "IGM Verto",
            "Creato layer '{}' con {} elementi.".format(mem.name(), n))
