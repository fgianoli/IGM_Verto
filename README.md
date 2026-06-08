# IGM Verto Coordinate Converter

Plugin per **QGIS 3 e QGIS 4** che converte coordinate usando i **grigliati ufficiali IGM**
tramite l'API REST *"Verto on line"* dell'Istituto Geografico Militare. È più preciso delle
trasformazioni PROJ standard tra i datum italiani (Monte Mario/Roma40, ED50, IGM95,
ETRS89/RDN2008) perché usa i grigliati nazionali.

Servizio IGM: https://igmi.esercito.difesa.it/servizi/verto-online/
Richiede connessione internet.

## Funzionalità

- **Conversione coordinate manuali** — incolla coppie E/N e ottieni il risultato (con copia/incolla).
- **Conversione da file CSV** — conversione batch con scelta di separatore, colonne, intestazione;
  output CSV e caricamento opzionale come layer di punti.
- **Riproiezione di layer vettoriali** — crea un nuovo layer in memoria convertendo tutti i
  vertici (punti, linee, poligoni, multi-geometrie); supporta "solo elementi selezionati".
- **Strumento click sulla mappa** — clicca un punto e leggi le coordinate convertite nella barra messaggi.
- **Algoritmo Processing** — *IGM Verto ▸ Riproietta con grigliati IGM (Verto)*, utilizzabile in
  toolbox, batch e modelli grafici.
- **Impostazioni** — credenziali utente/chiave (oggi ignorate ma obbligatorie nella richiesta),
  endpoint configurabile e aggiornamento dell'elenco dei sistemi di riferimento.

## Sistemi di riferimento supportati

L'elenco viene letto dal server (richiesta `info`) e include, tra gli altri:
Monte Mario (EPSG:4265, 3003, 3004, 4806), ED50 (4230, 23032/33/34),
IGM95 (4670, 3064, 3065, 9716), ETRS89-LAEA/LCC (3035, 3034),
RDN2008 (6706, 6707, 6708, 6709, 7794, 6876).

> Nota: le conversioni nello **stesso datum** non sono supportate dal servizio
> (es. da "RDN2008 2D geo" a "RDN2008 / TM32").

## Installazione

1. In QGIS: *Plugin ▸ Gestisci e installa plugin ▸ Installa da ZIP* e seleziona
   `igm_verto.zip`.
2. Oppure copia la cartella `igm_verto/` nella cartella dei plugin QGIS:
   - Windows: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`
   - Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
   - macOS: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`
3. Attiva il plugin dall'elenco. Comparirà il menu/toolbar **IGM Verto**.

## Note tecniche

- Le richieste di rete usano `QgsBlockingNetworkRequest` (rispetta proxy/SSL di QGIS).
- Le coordinate vengono inviate in batch rispettando il limite del servizio
  (`maxCoord`, attualmente 32000 per richiesta).
- Convenzione: `e` = est/longitudine (X), `n` = nord/latitudine (Y); le coordinate
  geografiche sono in **gradi sessadecimali**.
- Compatibilità Qt5 (QGIS 3) e Qt6 (QGIS 4) tramite `qgis.PyQt` ed enum con scope.

## Verifica

L'esempio del manuale (EPSG:4265 → 6706) è stato verificato sul servizio live:

| Input (E, N)   | Output (E, N)                  |
|----------------|--------------------------------|
| 7.0, 37.0      | 6.9996175526, 37.0006110152    |
| 12.0, 42.0     | 11.9997804498, 42.0006477023   |
| 16.0, 45.0     | 15.9999259776, 45.0006501430   |

## Condizioni d'uso e licenza

Il servizio di conversione è fornito dall'**Istituto Geografico Militare (IGM)** —
*Verto Online*. Secondo le [Condizioni di Uso ufficiali](https://igmi.esercito.difesa.it/servizi/verto-online/):

- l'utilizzo delle API è **libero, anche per finalità commerciali**, purché non si
  comprometta/sovraccarichi il servizio, non si tentino accessi non autorizzati e si
  rispettino le normative (l'IGM può applicare limiti/quote o sospendere il servizio);
- il software e l'infrastruttura **restano di proprietà esclusiva dell'IGM**;
  l'accesso alle API non trasferisce diritti sul software;
- **licenza dei risultati**: salvo diversa indicazione, i risultati mantengono la
  stessa licenza dei dati in ingresso;
- servizio fornito **"as is", senza garanzie** e con esclusione di responsabilità.

> Nota: Verto Online **non** è rilasciato sotto CC BY 4.0 (licenza usata invece per
> altri servizi IGM, es. WFS). Citare comunque la fonte quando si pubblicano dati
> convertiti: «Conversioni effettuate con il servizio Verto Online dell'IGM».

Il codice di questo plugin è cosa distinta dal servizio e può avere una propria
licenza (molti plugin QGIS usano la GPL).
