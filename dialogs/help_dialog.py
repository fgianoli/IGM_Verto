# -*- coding: utf-8 -*-
"""Finestra di Guida con la documentazione (in italiano) del plugin."""

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextBrowser, QPushButton
)

HELP_HTML = """
<html><body style="font-family:Sans-Serif; font-size:10pt; line-height:1.4;">
<h2 style="color:#0b6e4f;">IGM Verto &ndash; Convertitore di coordinate</h2>
<p>Questo plugin converte coordinate usando i <b>grigliati ufficiali IGM</b>
tramite l'API REST <i>&laquo;Verto on line&raquo;</i> dell'Istituto Geografico
Militare. &Egrave; pi&ugrave; preciso delle trasformazioni PROJ standard tra i
datum italiani (Monte Mario/Roma40, ED50, IGM95, ETRS89/RDN2008) perch&eacute;
usa i grigliati nazionali.</p>
<p><b>Richiede una connessione internet.</b> Il servizio &egrave; fornito da IGM:
<a href="https://igmi.esercito.difesa.it/servizi/verto-online/">verto-online</a>.</p>

<h3 style="color:#0b6e4f;">Come si usa</h3>
<p>Tutti gli strumenti si aprono dall'unica icona <b>IGM Verto</b> nella barra
degli strumenti (menu a tendina) oppure dal menu <i>Plugin &rsaquo; IGM
Verto</i>.</p>

<h4>1. Conversione coordinate (finestra con tre schede)</h4>
<ul>
<li><b>Coordinate manuali</b> &ndash; scegli il sistema di origine e di
destinazione, incolla una coordinata per riga nel formato
<code>E[,; spazio o tab]N</code>, premi <b>Converti</b> e copia il risultato.
Il pulsante <b>Scambia</b> inverte origine/destinazione.</li>
<li><b>File CSV</b> &ndash; seleziona il CSV di input, indica separatore, se
c'&egrave; un'intestazione e i numeri delle colonne E ed N. Scegli i sistemi e
il file di output: viene creato un nuovo CSV con due colonne aggiuntive
(<code>E_out</code>, <code>N_out</code>); opzionalmente il risultato viene
caricato come layer di punti.</li>
<li><b>Layer vettoriale</b> &ndash; scegli un layer (punti, linee o poligoni),
eventualmente solo gli elementi selezionati, e i sistemi di origine
(precompilato dal CRS del layer) e destinazione. Viene creato un nuovo layer in
memoria con tutte le geometrie convertite vertice per vertice.</li>
</ul>

<h4>2. Click sulla mappa</h4>
<p>Attiva lo strumento e clicca un punto sulla mappa: al primo click scegli il
sistema di destinazione, poi le coordinate convertite (dal CRS del progetto)
compaiono nella barra dei messaggi di QGIS.</p>

<h4>3. Algoritmo Processing</h4>
<p>In <i>Processing &rsaquo; Cassetta degli strumenti &rsaquo; IGM Verto</i>
trovi <b>Riproietta con grigliati IGM (Verto)</b>, utilizzabile anche in
modalit&agrave; batch e nei modelli grafici.</p>

<h4>4. Impostazioni</h4>
<p>Imposta <b>Utente</b> e <b>Chiave</b> (oggi <i>ignorati</i> dal servizio ma
obbligatori nella richiesta: puoi lasciare i valori predefiniti),
l'<b>endpoint</b> dell'API e aggiorna l'elenco dei sistemi di riferimento
direttamente dal server.</p>

<h3 style="color:#0b6e4f;">Note importanti</h3>
<ul>
<li>Le coordinate <b>geografiche</b> sono sempre in <b>gradi sessadecimali</b>
(es. 12.4823), non in gradi/primi/secondi.</li>
<li>Convenzione: <b>E</b> = est/longitudine (X), <b>N</b> = nord/latitudine (Y).</li>
<li>Le conversioni <b>nello stesso datum</b> non sono supportate dal servizio
(es. da &laquo;RDN2008 2D geo&raquo; a &laquo;RDN2008 / TM32&raquo;).</li>
<li>Limite del servizio: <b>32000 coordinate per richiesta</b>; il plugin
suddivide automaticamente i lotti pi&ugrave; grandi.</li>
</ul>

<h3 style="color:#0b6e4f;">Condizioni d'uso e licenza (IGM)</h3>
<p>Il servizio di conversione &egrave; fornito dall'<b>Istituto Geografico
Militare (IGM)</b> &ndash; <i>Verto Online</i>. Secondo le
<a href="https://igmi.esercito.difesa.it/servizi/verto-online/">Condizioni di
Uso</a> ufficiali:</p>
<ul>
<li>l'utilizzo delle API &egrave; <b>libero, anche per finalit&agrave;
commerciali</b>, purch&eacute; non si comprometta o sovraccarichi il servizio,
non si tentino accessi non autorizzati e si rispettino le normative; l'IGM
pu&ograve; introdurre limiti/quote o sospendere il servizio in qualsiasi
momento;</li>
<li>il software e l'infrastruttura del servizio <b>restano di propriet&agrave;
esclusiva dell'IGM</b>; l'accesso alle API non trasferisce diritti sul
software;</li>
<li><b>licenza dei risultati</b>: salvo diversa indicazione, i risultati
mantengono la stessa licenza dei dati in ingresso;</li>
<li>il servizio &egrave; fornito <b>&laquo;as is&raquo;, senza garanzie</b> e
con esclusione di responsabilit&agrave; da parte dell'IGM.</li>
</ul>
<p>Quando pubblichi o condividi dati ottenuti con questo plugin, <b>cita la
fonte</b>: &laquo;Conversioni effettuate con il servizio Verto Online
dell'Istituto Geografico Militare&raquo;. Il codice del plugin &egrave; cosa
distinta e pu&ograve; avere una propria licenza (es. GPL, come molti plugin
QGIS).</p>

<h3 style="color:#0b6e4f;">Sistemi di riferimento supportati</h3>
<p>L'elenco viene letto dal server e comprende, tra gli altri: Monte Mario
(EPSG:4265, 3003, 3004, 4806), ED50 (4230, 23032/33/34), IGM95 (4670, 3064,
3065, 9716), ETRS89-LAEA/LCC (3035, 3034) e RDN2008 (6706, 6707, 6708, 6709,
7794, 6876).</p>
</body></html>
"""


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("IGM Verto - Guida")
        self.setMinimumSize(660, 580)
        layout = QVBoxLayout(self)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(HELP_HTML)
        layout.addWidget(browser)
        row = QHBoxLayout()
        row.addStretch(1)
        btn = QPushButton("Chiudi")
        btn.clicked.connect(self.close)
        row.addWidget(btn)
        layout.addLayout(row)
