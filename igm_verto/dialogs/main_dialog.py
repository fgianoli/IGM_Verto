# -*- coding: utf-8 -*-
"""Dialog principale: conversione manuale, da CSV e di layer vettoriali."""

import csv
import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QTabWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QPushButton, QPlainTextEdit, QLineEdit, QCheckBox, QComboBox, QSpinBox,
    QFileDialog, QMessageBox, QApplication, QProgressDialog, QWidget, QGroupBox,
    QListWidget, QListWidgetItem
)

from qgis.core import (
    QgsProject, QgsMapLayerProxyModel, QgsApplication, QgsVectorLayer
)
from qgis.gui import QgsMapLayerComboBox

from .. import settings
from .. import verto_api
from .. import converter
from .srs_combo import SrsComboBox
from .. import tasks


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


_SAME_DATUM_MSG = (
    "Origine e destinazione appartengono allo stesso datum ({}).\n\n"
    "Il servizio IGM converte solo tra datum diversi (es. Monte Mario "
    "<-> RDN2008). Per cambiare solo proiezione o fuso nello stesso datum usa "
    "la riproiezione standard di QGIS: clic destro sul layer > Esporta > "
    "Salva oggetti come... scegliendo il CRS di destinazione (oppure "
    "Processing > Riproietta vettore). E' una trasformazione esatta e non "
    "richiede i grigliati."
)


class MainDialog(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._tasks = []
        self.setWindowTitle("IGM Verto - Conversione coordinate")
        self.setMinimumSize(640, 520)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.tabs.addTab(self._build_layer_tab(), "Layer vettoriale")
        self.tabs.addTab(self._build_manual_tab(), "Coordinate manuali")
        self.tabs.addTab(self._build_csv_tab(), "File CSV")

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

    def _alias_notice(self, *epsgs):
        """Mostra (una volta per apertura della finestra) come viene gestito
        un EPSG non supportato direttamente dal servizio."""
        note = verto_api.alias_notice(*epsgs)
        if note and not getattr(self, "_alias_shown", False):
            self._alias_shown = True
            QMessageBox.information(self, "IGM Verto - Nota sul sistema scelto", note)

    def _manual_convert(self):
        in_epsg = self.m_in.current_epsg()
        out_epsg = self.m_out.current_epsg()
        if not in_epsg or not out_epsg:
            QMessageBox.warning(self, "IGM Verto", "Seleziona i sistemi EPSG.")
            return
        if converter.same_datum(in_epsg, out_epsg):
            QMessageBox.information(
                self, "IGM Verto",
                _SAME_DATUM_MSG.format(converter.datum_of(in_epsg)))
            return
        self._alias_notice(in_epsg, out_epsg)
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
            QApplication.setOverrideCursor(Qt.CursorShape.ArrowCursor)
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
        self.c_col_e = QSpinBox()
        self.c_col_e.setMinimum(1)
        self.c_col_e.setValue(1)
        self.c_col_n = QSpinBox()
        self.c_col_n.setMinimum(1)
        self.c_col_n.setValue(2)
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

    @staticmethod
    def _csv_number(text, decimal_comma):
        """float da una cella CSV; con decimal_comma accetta '12,5'."""
        text = text.strip().replace(" ", "")
        if decimal_comma and "," in text and "." not in text:
            text = text.replace(",", ".")
        return float(text)

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
        if converter.same_datum(in_epsg, out_epsg):
            QMessageBox.information(
                self, "IGM Verto",
                _SAME_DATUM_MSG.format(converter.datum_of(in_epsg)))
            return
        self._alias_notice(in_epsg, out_epsg)

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

        # La virgola decimale e' accettata se non e' anche il separatore
        dec_comma = delim != ","
        coords = []
        valid_idx = []
        for idx, r in enumerate(data_rows):
            pair = self._csv_pair(r, ci, cn, dec_comma)
            if pair is not None:
                coords.append(pair)
                valid_idx.append(idx)
        n_skipped = sum(1 for r in data_rows if r) - len(coords)
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
            if progress.wasCanceled():
                raise verto_api.VertoError("Operazione annullata.")

        try:
            result = verto_api.convert(in_epsg, out_epsg, coords,
                                       progress_cb=cb, **_api_kwargs())
        except verto_api.VertoError as exc:
            progress.close()
            QMessageBox.critical(self, "IGM Verto", "Errore: {}".format(exc))
            return
        progress.setValue(len(coords))

        conv_map = dict(zip(valid_idx, result))
        # Tutte le righe alla stessa larghezza: E_out/N_out restano incolonnati
        width = max(len(r) for r in rows)

        def padded(r):
            return list(r) + [""] * (width - len(r))
        try:
            with open(out_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f, delimiter=delim)
                if header is not None:
                    writer.writerow(padded(header) + ["E_out", "N_out"])
                for idx, r in enumerate(data_rows):
                    if idx in conv_map:
                        e, n = conv_map[idx]
                        writer.writerow(padded(r) + ["{:.8f}".format(e),
                                                     "{:.8f}".format(n)])
                    else:
                        writer.writerow(padded(r) + ["", ""])
        except Exception as exc:
            QMessageBox.critical(self, "IGM Verto",
                                 "Scrittura CSV fallita: {}".format(exc))
            return

        loaded = True
        if self.c_load.isChecked():
            # Senza intestazione i campi si chiamano field_1, field_2, ...
            fields = (("E_out", "N_out") if header is not None else
                      ("field_{}".format(width + 1), "field_{}".format(width + 2)))
            loaded = self._load_csv_as_points(
                out_path, out_epsg, delim, fields, header is not None)
        msg = "Conversione completata: {} coordinate.\nSalvato in:\n{}".format(
            len(coords), out_path)
        if n_skipped:
            msg += ("\n\nRighe saltate perche' prive di coordinate numeriche "
                    "nelle colonne indicate: {}.".format(n_skipped))
        if not loaded:
            msg += ("\n\nNon e' stato possibile caricare il risultato come "
                    "layer di punti: aggiungilo dal menu Layer > Aggiungi "
                    "layer testo delimitato.")
        QMessageBox.information(self, "IGM Verto", msg)

    def _csv_pair(self, row, ci, cn, dec_comma):
        """(e, n) della riga, oppure None se le celle non sono numeriche."""
        try:
            return (self._csv_number(row[ci], dec_comma),
                    self._csv_number(row[cn], dec_comma))
        except (ValueError, IndexError):
            return None

    def _load_csv_as_points(self, path, epsg, delim=",",
                            fields=("E_out", "N_out"), has_header=True):
        from qgis.PyQt.QtCore import QUrl
        from qgis.core import QgsVectorLayer
        crs = converter.epsg_to_crs(epsg)
        # Il separatore va scritto come lo vuole il provider "delimitedtext":
        # virgola e punto e virgola letterali (codificati non funzionano)
        delim_uri = {"\t": "\\t", " ": "%20"}.get(delim, delim)
        base = bytes(QUrl.fromLocalFile(path).toEncoded()).decode("ascii")
        uri = ("{}?type=csv&delimiter={}&useHeader={}&xField={}&yField={}"
               "&crs={}").format(
                   base, delim_uri, "Yes" if has_header else "No",
                   fields[0], fields[1], crs.authid() or ("EPSG:%d" % epsg))
        layer = QgsVectorLayer(uri, os.path.basename(path), "delimitedtext")
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)
            return True
        return False

    # ---------------------------------------------------------- TAB: layer
    def _labeled(self, text, *widgets):
        c = QWidget()
        h = QHBoxLayout(c)
        h.setContentsMargins(0, 0, 0, 0)
        lab = QLabel(text)
        lab.setMinimumWidth(130)
        h.addWidget(lab)
        for wdg in widgets:
            h.addWidget(wdg)
        return c

    def _build_layer_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        mform = QFormLayout()
        self.l_mode = QComboBox()
        self.l_mode.addItems(
            ["Layer del progetto", "Più layer del progetto", "Cartella (batch)"])
        self.l_mode.currentIndexChanged.connect(self._layer_mode_changed)
        mform.addRow("Modalità:", self.l_mode)
        v.addLayout(mform)

        # Modalità: layer del progetto
        self.l_single_grp = QGroupBox("Layer del progetto")
        sg = QFormLayout(self.l_single_grp)
        self.l_combo = QgsMapLayerComboBox()
        self.l_combo.setFilters(_vector_filter())
        self.l_combo.layerChanged.connect(self._layer_changed)
        sg.addRow("Layer:", self.l_combo)
        self.l_selected = QCheckBox("Solo elementi selezionati")
        sg.addRow("", self.l_selected)
        v.addWidget(self.l_single_grp)

        # Modalità: più layer del progetto
        self.l_multi_grp = QGroupBox("Più layer del progetto")
        mg = QVBoxLayout(self.l_multi_grp)
        mg.addWidget(QLabel("Spunta i layer vettoriali da riproiettare:"))
        self.l_multi_list = QListWidget()
        self.l_multi_list.setMinimumHeight(140)
        mg.addWidget(self.l_multi_list)
        mrow = QHBoxLayout()
        b_all = QPushButton("Seleziona tutti")
        b_none = QPushButton("Deseleziona tutti")
        b_ref = QPushButton("Aggiorna elenco")
        b_all.clicked.connect(lambda: self._multi_set_all(True))
        b_none.clicked.connect(lambda: self._multi_set_all(False))
        b_ref.clicked.connect(self._multi_refresh)
        for b in (b_all, b_none, b_ref):
            mrow.addWidget(b)
        mg.addLayout(mrow)
        self.l_multi_selected = QCheckBox("Solo elementi selezionati")
        mg.addWidget(self.l_multi_selected)
        v.addWidget(self.l_multi_grp)

        # Modalità: cartella (batch)
        self.l_batch_grp = QGroupBox("Cartella (batch)")
        bg = QFormLayout(self.l_batch_grp)
        self.l_in_dir = QLineEdit()
        bin_btn = QPushButton("Sfoglia...")
        bin_btn.clicked.connect(self._layer_browse_indir)
        rin = QHBoxLayout()
        rin.addWidget(self.l_in_dir)
        rin.addWidget(bin_btn)
        bg.addRow("Cartella input:", self._wrap(rin))
        self.l_recursive = QCheckBox("Includi sottocartelle")
        bg.addRow("", self.l_recursive)
        v.addWidget(self.l_batch_grp)

        # Sistemi di riferimento
        sform = QFormLayout()
        self.l_in, self.l_out = self._srs_row(None, 6706)
        sform.addRow("Sistema di origine:", self.l_in)
        sform.addRow("Sistema di destinazione:", self.l_out)
        v.addLayout(sform)
        self.l_note = QLabel("")
        self.l_note.setWordWrap(True)
        v.addWidget(self.l_note)

        # Output
        out_grp = QGroupBox("Output")
        ov = QVBoxLayout(out_grp)
        self.l_out_mode = QComboBox()
        self.l_out_mode.addItems(["In memoria (solo progetto)", "Salva su file"])
        self.l_out_mode.currentIndexChanged.connect(self._layer_outmode_changed)
        self.row_dest = self._labeled("Destinazione:", self.l_out_mode)
        ov.addWidget(self.row_dest)

        self.l_out_path = QLineEdit()
        of_btn = QPushButton("Sfoglia...")
        of_btn.clicked.connect(self._layer_browse_outfile)
        self.row_outfile = self._labeled("File output:", self.l_out_path, of_btn)
        ov.addWidget(self.row_outfile)

        self.l_out_dir = QLineEdit()
        od_btn = QPushButton("Sfoglia...")
        od_btn.clicked.connect(self._layer_browse_outdir)
        self.row_outdir = self._labeled("Cartella output:", self.l_out_dir, od_btn)
        ov.addWidget(self.row_outdir)

        self.l_out_fmt = QComboBox()
        self.l_out_fmt.addItems(
            ["GeoPackage (.gpkg)", "Shapefile (.shp)", "GeoJSON (.geojson)"])
        self.row_fmt = self._labeled("Formato:", self.l_out_fmt)
        ov.addWidget(self.row_fmt)

        self.l_load = QCheckBox("Aggiungi i risultati al progetto")
        self.l_load.setChecked(True)
        ov.addWidget(self.l_load)
        v.addWidget(out_grp)

        v.addStretch(1)
        self.l_btn = QPushButton("Riproietta layer")
        self.l_btn.clicked.connect(self._layer_run)
        v.addWidget(self.l_btn)

        self._layer_changed(self.l_combo.currentLayer())
        self._layer_mode_changed()
        return w

    def _out_ext(self):
        return {0: ".gpkg", 1: ".shp", 2: ".geojson"}[self.l_out_fmt.currentIndex()]

    def _mode(self):
        return ("single", "multi", "batch")[self.l_mode.currentIndex()]

    def _layer_mode_changed(self, *args):
        mode = self._mode()
        self.l_single_grp.setVisible(mode == "single")
        self.l_multi_grp.setVisible(mode == "multi")
        self.l_batch_grp.setVisible(mode == "batch")
        self.l_note.setVisible(mode != "single")
        if mode == "multi":
            self.l_note.setText(
                "L'EPSG di origine viene letto dal CRS di ciascun layer; "
                "l'origine qui sopra è usata solo come ripiego per i layer il "
                "cui CRS non è riconosciuto.")
            self._multi_refresh()
        elif mode == "batch":
            self.l_note.setText(
                "In modalità cartella l'EPSG di origine viene letto dal CRS di "
                "ciascun file; l'origine qui sopra è usata solo come ripiego "
                "per i file privi di CRS.")
        self.l_btn.setText({
            "single": "Riproietta layer",
            "multi": "Riproietta i layer selezionati",
            "batch": "Riproietta cartella"}[mode])
        self._layer_outmode_changed()

    def _layer_outmode_changed(self, *args):
        mode = self._mode()
        to_file = self.l_out_mode.currentIndex() == 1
        if mode == "batch":
            self.row_dest.setVisible(False)
            self.row_outfile.setVisible(False)
            self.row_outdir.setVisible(True)
            self.row_fmt.setVisible(True)
        elif mode == "multi":
            self.row_dest.setVisible(True)
            self.row_outfile.setVisible(False)
            self.row_outdir.setVisible(to_file)
            self.row_fmt.setVisible(to_file)
        else:
            self.row_dest.setVisible(True)
            self.row_outdir.setVisible(False)
            self.row_fmt.setVisible(False)
            self.row_outfile.setVisible(to_file)

    # -- selezione di più layer del progetto ------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, "l_multi_list") and self._mode() == "multi":
            self._multi_refresh()

    def _multi_refresh(self):
        """Ricarica l'elenco dei layer vettoriali del progetto, mantenendo
        le spunte già fatte."""
        checked = set()
        for i in range(self.l_multi_list.count()):
            it = self.l_multi_list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                checked.add(it.data(Qt.ItemDataRole.UserRole))
        self.l_multi_list.clear()
        layers = [lyr for lyr in QgsProject.instance().mapLayers().values()
                  if isinstance(lyr, QgsVectorLayer)]
        for lyr in sorted(layers, key=lambda x: x.name().lower()):
            epsg = converter.crs_to_epsg(lyr.crs())
            label = "{}  [{}]".format(
                lyr.name(), "EPSG:{}".format(epsg) if epsg else "CRS non riconosciuto")
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, lyr.id())
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if lyr.id() in checked
                             else Qt.CheckState.Unchecked)
            self.l_multi_list.addItem(it)

    def _multi_set_all(self, on):
        state = Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
        for i in range(self.l_multi_list.count()):
            self.l_multi_list.item(i).setCheckState(state)

    def _multi_checked_layers(self):
        out = []
        for i in range(self.l_multi_list.count()):
            it = self.l_multi_list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                lyr = QgsProject.instance().mapLayer(
                    it.data(Qt.ItemDataRole.UserRole))
                if lyr is not None:
                    out.append(lyr)
        return out

    def _layer_browse_indir(self):
        d = QFileDialog.getExistingDirectory(
            self, "Cartella con i file da convertire")
        if d:
            self.l_in_dir.setText(d)
            if not self.l_out_dir.text():
                self.l_out_dir.setText(os.path.join(d, "convertiti"))

    def _layer_browse_outdir(self):
        d = QFileDialog.getExistingDirectory(self, "Cartella di output")
        if d:
            self.l_out_dir.setText(d)

    def _layer_browse_outfile(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Salva layer convertito", "",
            "GeoPackage (*.gpkg);;Shapefile (*.shp);;GeoJSON (*.geojson)")
        if path:
            self.l_out_path.setText(path)

    def _layer_changed(self, layer):
        if layer is not None:
            epsg = converter.crs_to_epsg(layer.crs())
            if epsg:
                self.l_in.set_current_epsg(epsg)

    def _layer_run(self):
        mode = self._mode()
        if mode == "batch":
            self._run_batch()
        elif mode == "multi":
            self._run_multi()
        else:
            self._run_single()

    def _start_task(self, task, info):
        """Avvia il task in background con una piccola finestra di progresso.

        La finestra non e' modale: QGIS resta utilizzabile. Il pulsante
        Annulla richiede l'interruzione del task.
        """
        dlg = QProgressDialog(info, "Annulla", 0, 100, self)
        dlg.setWindowTitle("IGM Verto")
        dlg.setWindowModality(Qt.WindowModality.NonModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setValue(0)
        task.progressChanged.connect(lambda p: dlg.setValue(int(p)))
        dlg.canceled.connect(task.cancel)
        task.taskCompleted.connect(dlg.close)
        task.taskTerminated.connect(dlg.close)
        if not hasattr(self, "_dialogs"):
            self._dialogs = []
        self._dialogs.append(dlg)
        self._tasks.append(task)
        QgsApplication.taskManager().addTask(task)
        dlg.show()

    def _run_single(self):
        layer = self.l_combo.currentLayer()
        if layer is None:
            QMessageBox.warning(self, "IGM Verto", "Seleziona un layer.")
            return
        in_epsg = self.l_in.current_epsg()
        out_epsg = self.l_out.current_epsg()
        if not in_epsg or not out_epsg:
            QMessageBox.warning(self, "IGM Verto", "Seleziona i sistemi EPSG.")
            return
        if in_epsg == out_epsg:
            QMessageBox.warning(self, "IGM Verto",
                                "Origine e destinazione coincidono.")
            return
        if converter.same_datum(in_epsg, out_epsg):
            QMessageBox.information(
                self, "IGM Verto",
                _SAME_DATUM_MSG.format(converter.datum_of(in_epsg)))
            return
        self._alias_notice(in_epsg, out_epsg)
        sel = self.l_selected.isChecked()
        if sel and layer.selectedFeatureCount() == 0:
            QMessageBox.warning(self, "IGM Verto", "Nessun elemento selezionato.")
            return
        to_file = self.l_out_mode.currentIndex() == 1
        out_path = self.l_out_path.text().strip()
        if to_file and not out_path:
            QMessageBox.warning(self, "IGM Verto", "Specifica il file di output.")
            return

        # Lettura dati nel thread principale
        feats = list(layer.selectedFeatures() if sel else layer.getFeatures())
        geoms = [f.geometry() for f in feats]
        attrs = [f.attributes() for f in feats]
        fields = layer.fields()
        wkb = layer.wkbType()
        name = "{}_EPSG{}".format(layer.name(), out_epsg)
        api = _api_kwargs()
        load = self.l_load.isChecked()

        def work(task):
            def pcb(done, total):
                if task.isCanceled():
                    raise verto_api.VertoError("Operazione annullata.")
                task.setProgress(done * 100.0 / total if total else 0)
            return converter.convert_geometries(
                geoms, in_epsg, out_epsg, progress_cb=pcb, **api)

        def on_done():
            try:
                mem, n = converter.geoms_to_memory_layer(
                    name, fields, wkb, out_epsg, attrs, task.result)
                if to_file:
                    converter.write_vector(mem, out_path)
            except Exception as exc:
                self.iface.messageBar().pushCritical(
                    "IGM Verto", "Errore: {}".format(exc))
                return
            if to_file:
                if load:
                    self._add_file_to_project(out_path)
                self.iface.messageBar().pushSuccess(
                    "IGM Verto",
                    "Convertiti {} elementi -> {}".format(n, out_path))
            else:
                QgsProject.instance().addMapLayer(mem)
                self.iface.messageBar().pushSuccess(
                    "IGM Verto",
                    "Creato layer '{}' ({} elementi)".format(mem.name(), n))

        def on_failed():
            msg = str(task.error) if task.error else "operazione annullata"
            self.iface.messageBar().pushWarning(
                "IGM Verto", "Conversione non completata: {}".format(msg))

        task = tasks.FunctionTask(
            "IGM Verto: riproiezione {}".format(layer.name()), work)
        task.taskCompleted.connect(on_done)
        task.taskTerminated.connect(on_failed)
        self._start_task(task, "Conversione avviata in background...")

    def _run_multi(self):
        layers = self._multi_checked_layers()
        if not layers:
            QMessageBox.warning(
                self, "IGM Verto", "Spunta almeno un layer da riproiettare.")
            return
        out_epsg = self.l_out.current_epsg()
        if not out_epsg:
            QMessageBox.warning(self, "IGM Verto",
                                "Seleziona il sistema di destinazione.")
            return
        fallback_in = self.l_in.current_epsg()
        sel = self.l_multi_selected.isChecked()
        to_file = self.l_out_mode.currentIndex() == 1
        out_dir = self.l_out_dir.text().strip()
        ext = self._out_ext()
        if to_file:
            if not out_dir:
                QMessageBox.warning(self, "IGM Verto",
                                    "Specifica la cartella di output.")
                return
            try:
                os.makedirs(out_dir, exist_ok=True)
            except OSError as exc:
                QMessageBox.critical(
                    self, "IGM Verto",
                    "Impossibile creare la cartella di output: {}".format(exc))
                return

        # Controlli per ciascun layer; quelli non convertibili sono saltati
        jobs = []
        skipped = []
        for lyr in layers:
            in_epsg = converter.crs_to_epsg(lyr.crs()) or fallback_in
            if not in_epsg:
                skipped.append("{}: CRS di origine sconosciuto".format(lyr.name()))
            elif in_epsg == out_epsg:
                skipped.append("{}: già in EPSG:{}".format(lyr.name(), out_epsg))
            elif converter.same_datum(in_epsg, out_epsg):
                skipped.append("{}: stesso datum ({}), usa la riproiezione "
                               "standard di QGIS".format(
                                   lyr.name(), converter.datum_of(in_epsg)))
            elif sel and lyr.selectedFeatureCount() == 0:
                skipped.append("{}: nessun elemento selezionato".format(lyr.name()))
            else:
                jobs.append((lyr, in_epsg))
        if not jobs:
            QMessageBox.warning(
                self, "IGM Verto",
                "Nessun layer convertibile:\n- " + "\n- ".join(skipped))
            return
        self._alias_notice(out_epsg, *[e for _l, e in jobs])

        # Lettura dei dati nel thread principale
        data = []
        for lyr, in_epsg in jobs:
            feats = list(lyr.selectedFeatures() if sel else lyr.getFeatures())
            data.append({
                "name": lyr.name(),
                "in_epsg": in_epsg,
                "geoms": [f.geometry() for f in feats],
                "attrs": [f.attributes() for f in feats],
                "fields": lyr.fields(),
                "wkb": lyr.wkbType(),
            })
        load = self.l_load.isChecked()
        api = _api_kwargs()
        total_jobs = len(data)

        def work(task):
            results = []
            for i, d in enumerate(data):
                if task.isCanceled():
                    break

                def pcb(done, total, i=i):
                    if task.isCanceled():
                        raise verto_api.VertoError("Operazione annullata.")
                    frac = (done / total) if total else 1.0
                    task.setProgress((i + frac) * 100.0 / total_jobs)
                try:
                    res = converter.convert_geometries(
                        d["geoms"], d["in_epsg"], out_epsg,
                        progress_cb=pcb, **api)
                    results.append((d, res, None))
                except Exception as exc:
                    results.append((d, None, str(exc)))
            return results

        def on_done():
            made = 0
            errors = list(skipped)
            used_names = set()
            for d, geoms, err in task.result:
                if err:
                    errors.append("{}: {}".format(d["name"], err))
                    continue
                name = "{}_EPSG{}".format(d["name"], out_epsg)
                try:
                    mem, n = converter.geoms_to_memory_layer(
                        name, d["fields"], d["wkb"], out_epsg, d["attrs"], geoms)
                    if to_file:
                        safe = "".join(
                            c if (c.isalnum() or c in "-_ .") else "_"
                            for c in name).strip() or "layer"
                        path = os.path.join(out_dir, safe + ext)
                        k = 2
                        while path.lower() in used_names or os.path.exists(path):
                            path = os.path.join(
                                out_dir, "{}_{}{}".format(safe, k, ext))
                            k += 1
                        used_names.add(path.lower())
                        converter.write_vector(mem, path)
                        if load:
                            self._add_file_to_project(path)
                    else:
                        QgsProject.instance().addMapLayer(mem)
                    made += 1
                except Exception as exc:
                    errors.append("{}: {}".format(d["name"], exc))
            self.iface.messageBar().pushSuccess(
                "IGM Verto",
                "Layer convertiti: {}/{}".format(made, len(layers)))
            if errors:
                QMessageBox.warning(
                    self, "IGM Verto",
                    "Layer non convertiti ({}):\n- {}".format(
                        len(errors), "\n- ".join(errors[:15])))
            self._multi_refresh()

        def on_failed():
            msg = str(task.error) if task.error else "annullato"
            self.iface.messageBar().pushWarning(
                "IGM Verto", "Conversione non completata: {}".format(msg))

        task = tasks.FunctionTask(
            "IGM Verto: riproiezione di {} layer".format(total_jobs), work)
        task.taskCompleted.connect(on_done)
        task.taskTerminated.connect(on_failed)
        self._start_task(task, "Conversione di {} layer avviata in "
                               "background...".format(total_jobs))

    def _run_batch(self):
        in_dir = self.l_in_dir.text().strip()
        out_dir = self.l_out_dir.text().strip()
        if not in_dir or not os.path.isdir(in_dir):
            QMessageBox.warning(self, "IGM Verto", "Cartella di input non valida.")
            return
        if not out_dir:
            QMessageBox.warning(self, "IGM Verto",
                                "Specifica la cartella di output.")
            return
        out_epsg = self.l_out.current_epsg()
        if not out_epsg:
            QMessageBox.warning(self, "IGM Verto",
                                "Seleziona il sistema di destinazione.")
            return
        self._alias_notice(out_epsg)
        fallback_in = self.l_in.current_epsg()
        ext = self._out_ext()
        files = converter.list_vector_files(in_dir, self.l_recursive.isChecked())
        if not files:
            QMessageBox.information(
                self, "IGM Verto",
                "Nessun file vettoriale trovato nella cartella.")
            return
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(
                self, "IGM Verto",
                "Impossibile creare la cartella di output: {}".format(exc))
            return
        load = self.l_load.isChecked()
        api = _api_kwargs()

        def work(task):
            ok = 0
            errors = []
            outs = []
            # Un file puo' contenere piu' layer (es. GeoPackage): una voce
            # per ciascun layer di ciascun file
            jobs = converter.plan_batch(
                [(f, converter.list_sublayers(f)) for f in files],
                out_dir, out_epsg, ext)
            total = len(jobs)
            written = set()
            for i, job in enumerate(jobs):
                if task.isCanceled():
                    break
                task.setProgress(i * 100.0 / total if total else 0)
                out_path = job["out_path"]
                try:
                    converter.reproject_path_to_file(
                        job["in_path"], out_path, out_epsg,
                        fallback_in_epsg=fallback_in,
                        layer_uri=job["layer_uri"], out_layer=job["out_layer"],
                        append=out_path in written, **api)
                    ok += 1
                    written.add(out_path)
                    outs.append((out_path, job["out_layer"]))
                except Exception as exc:
                    errors.append("{}: {}".format(job["label"], exc))
            return {"ok": ok, "errors": errors, "outs": outs, "total": total,
                    "files": len(files)}

        def on_done():
            r = task.result
            if load:
                for path, lname in r["outs"]:
                    self._add_file_to_project(path, lname)
            self.iface.messageBar().pushSuccess(
                "IGM Verto",
                "Layer convertiti: {}/{} (file letti: {})".format(
                    r["ok"], r["total"], r["files"]))
            if r["errors"]:
                QMessageBox.warning(
                    self, "IGM Verto",
                    "Errori ({}):\n- {}".format(
                        len(r["errors"]), "\n- ".join(r["errors"][:15])))

        def on_failed():
            msg = str(task.error) if task.error else "annullato"
            self.iface.messageBar().pushWarning(
                "IGM Verto", "Batch non completato: {}".format(msg))

        task = tasks.FunctionTask("IGM Verto: batch cartella", work)
        task.taskCompleted.connect(on_done)
        task.taskTerminated.connect(on_failed)
        self._start_task(task, "Conversione batch avviata in background...")

    def _add_file_to_project(self, path, layer_name=None):
        from qgis.core import QgsVectorLayer
        name = layer_name or os.path.splitext(os.path.basename(path))[0]
        uri = path
        if layer_name and path.lower().endswith(".gpkg"):
            uri = "{}|layername={}".format(path, layer_name)
        layer = QgsVectorLayer(uri, name, "ogr")
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)
