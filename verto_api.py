# -*- coding: utf-8 -*-
"""
Client per l'API IGM "VERTO on line".

Endpoint POST JSON: https://igmi.esercito.difesa.it/porta-magna/wps/volapi

Richiesta "info":      {"richiesta": "info"}
Richiesta "conversione":
    {"richiesta": "conversione", "utente": "...", "chiave": "...",
     "inEpsg": 4265, "outEpsg": 6706,
     "coordinate": [{"e": 7.0, "n": 37.0}, ...]}
Risposta OK:  {"stato": "successo", "coordinate": [{"e": ..., "n": ...}, ...]}
Errore:       {"stato": "errore", "dove": "...", "messaggio": "..."}

Le coordinate geografiche sono SEMPRE in gradi sessadecimali.
Le conversioni tra lo stesso datum non sono supportate.

Le richieste di rete usano esclusivamente QgsBlockingNetworkRequest, che
rispetta le impostazioni di proxy/SSL di QGIS. Le coordinate sono inviate in
blocchi di al piu' CHUNK_SIZE punti; un errore di rete transitorio viene
ritentato (RETRY_DELAYS) prima di interrompere la conversione.
"""

import json
import time

ENDPOINT = "https://igmi.esercito.difesa.it/porta-magna/wps/volapi"
DEFAULT_MAX_COORD = 32000
# Blocchi piu' piccoli del massimo ammesso dal servizio: avanzamento piu' fine,
# annullamento piu' rapido e, in caso di errore, si ritenta solo un blocco.
CHUNK_SIZE = 5000
# Attese (secondi) prima dei nuovi tentativi dopo un errore di rete.
RETRY_DELAYS = (2, 5)
# Timeout della richiesta "info" (elenco SRS), fatta dal thread principale.
INFO_TIMEOUT_MS = 15000
# Timeout del client di ripiego per il certificato scaduto (vedi _pinned_post).
PINNED_TIMEOUT_MS = 120000

try:
    from qgis.core import QgsBlockingNetworkRequest
    from qgis.PyQt.QtCore import (
        QUrl, QByteArray, QEventLoop, QTimer, QCryptographicHash)
    from qgis.PyQt.QtNetwork import (
        QNetworkRequest, QNetworkAccessManager, QNetworkReply, QSslError)
    _HAS_QGIS = True
except Exception:  # pragma: no cover - fuori da QGIS
    _HAS_QGIS = False


DEFAULT_USER = "qgis"
DEFAULT_KEY = "qgis"
CREDENTIALS_URL = "https://igmi.esercito.difesa.it/servizi/verto-online/"

# Istruzioni mostrate nelle Impostazioni e nella guida (HTML).
CREDENTIALS_HELP_HTML = (
    "Dal <b>1&deg; novembre 2026</b> il servizio IGM Verto online richiede "
    "un account (nome utente e password/chiave). L'accesso resta "
    "<b>gratuito</b> e le credenziali <b>scadono ogni 3 mesi</b>.<br>"
    "<b>Come ottenerle:</b>"
    "<ol style=\"margin-top:2px;margin-bottom:2px\">"
    "<li>apri la <a href=\"{url}\">pagina IGM di Verto online</a> ed "
    "effettua il <b>login</b> (registrati se non hai un account);</li>"
    "<li>entra nell'<b>Area Riservata</b> e scegli <b>Abbonamenti ai "
    "servizi</b> (ultimo tasto a sinistra nella pagina utente);</li>"
    "<li>copia nome utente e chiave/password e inseriscili qui sotto;</li>"
    "<li>ogni 3 mesi ripeti la consultazione per rinnovarle.</li></ol>"
    "Finch&eacute; il controllo non &egrave; attivo puoi lasciare i valori "
    "predefiniti."
).format(url=CREDENTIALS_URL)

# Dal 2026-10 l'IGM ha sostituito i vecchi EPSG RDN2008 proiettati con assi
# N-E (6875, 6876, 6707, 6708, 6709) con gli equivalenti E-N (7794, 7795,
# 7791, 7792, 7793): stessi parametri di proiezione, cambia solo l'ordine degli assi.
# I file scaricati da geoportali (es. Regione Veneto) portano ancora i vecchi
# codici: il plugin li accetta e li inoltra al servizio con il codice nuovo.
SERVER_ALIAS = {6875: 7794, 6876: 7795, 6707: 7791, 6708: 7792, 6709: 7793}
EXTRA_SRS = [
    {"epsg": 6875, "descrizione": "RDN2008 / Italy zone (N-E)"},
    {"epsg": 6876, "descrizione": "RDN2008 / Zone 12 (N-E)"},
    {"epsg": 6707, "descrizione": "RDN2008 / UTM zone 32N (N-E)"},
    {"epsg": 6708, "descrizione": "RDN2008 / UTM zone 33N (N-E)"},
    {"epsg": 6709, "descrizione": "RDN2008 / UTM zone 34N (N-E)"},
]


def to_server_epsg(epsg):
    """Codice EPSG da inviare al servizio (risolve gli alias)."""
    return SERVER_ALIAS.get(int(epsg), int(epsg))


ALIAS_NOTE = (
    "EPSG:{alias} (assi N-E) non e' piu' elencato dal servizio IGM Verto, "
    "che offre l'equivalente EPSG:{real} (assi E-N). Il plugin esegue la "
    "conversione con EPSG:{real}: i parametri di proiezione sono gli stessi "
    "e cambia solo l'ordine degli assi. Le coordinate sono usate e restituite "
    "come (Est, Nord), come in QGIS. Il risultato e' quello del grigliato IGM "
    "ufficiale."
)


def _as_int(value):
    """int(value) oppure None se non convertibile."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def alias_notice(*epsgs):
    """Testo dell'avviso se tra gli EPSG c'e' un alias, altrimenti None."""
    notes = []
    for e in epsgs:
        code = _as_int(e)
        if code in SERVER_ALIAS:
            notes.append(ALIAS_NOTE.format(alias=code, real=SERVER_ALIAS[code]))
    return "\n\n".join(dict.fromkeys(notes)) or None


def with_extra_srs(srs_list):
    """Aggiunge all'elenco del servizio gli SRS gestiti via alias."""
    known = {int(x["epsg"]) for x in srs_list}
    return list(srs_list) + [x for x in EXTRA_SRS if x["epsg"] not in known]


# Parole chiave che indicano un rifiuto per credenziali (il formato esatto
# dell'errore di autenticazione IGM non e' ancora documentato).
_AUTH_HINTS = ("utente", "chiave", "credenzial", "autentic", "autoriz",
               "scadut", "scadenz", "abbonament", "unauthorized",
               "forbidden", "key", "expired")


class VertoError(Exception):
    """Errore restituito dall'API o errore di rete."""

    def __init__(self, message, dove=None):
        super().__init__(message)
        self.message = message
        self.dove = dove

    def __str__(self):
        if self.dove:
            return "{} ({})".format(self.message, self.dove)
        return self.message


class VertoAuthError(VertoError):
    """Credenziali (utente/chiave) mancanti, non valide o scadute."""


class VertoNetworkError(VertoError):
    """Errore di rete (potenzialmente transitorio: si puo' ritentare)."""


def _auth_error(message, dove=None):
    return VertoAuthError(
        "Credenziali IGM non accettate: {}. Le chiavi hanno validita' "
        "trimestrale: accedi al sito IGM, apri 'Abbonamenti ai servizi' e "
        "aggiorna utente/chiave in Impostazioni del plugin.".format(message),
        dove,
    )


def _looks_like_auth_error(message):
    low = (message or "").lower()
    return any(h in low for h in _AUTH_HINTS)


def _parse_json(text):
    """Interpreta la risposta JSON tollerando righe di log non-JSON.

    Il server IGM puo' anteporre alla risposta una riga di log
    (es. "QUERY: INSERT INTO vol.log ..."); in tal caso si estrae
    l'oggetto JSON dal primo '{' all'ultimo '}'.
    """
    try:
        return json.loads(text)
    except ValueError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except ValueError:
                pass
        raise VertoError(
            "Risposta non valida dal server IGM: {}".format(text[:200])
        )


def _is_ssl_message(text):
    low = (text or "").lower()
    return "ssl" in low or "certific" in low


SSL_HELP = (
    "Il certificato SSL del server IGM non e' valido e non e' quello, "
    "scaduto a novembre 2026, che il plugin accetta in via eccezionale. "
    "Il problema e' lato IGM: la connessione e' stata rifiutata per "
    "sicurezza. Attendi che l'IGM sistemi il certificato o controlla se "
    "esiste una versione aggiornata del plugin."
)

# Il certificato *.esercito.difesa.it del server IGM e' scaduto a inizio
# novembre 2026 e QGIS rifiuta la connessione. Finche' l'IGM non lo rinnova,
# il plugin ripiega su un client Qt diretto che ignora SOLO l'errore
# "certificato scaduto" e SOLO per questo esatto certificato (impronta SHA-1):
# l'identita' del server resta verificata (catena, nome host, impronta).
# Qualsiasi altro errore o certificato viene rifiutato. Con il certificato
# rinnovato la richiesta normale torna a funzionare e questo codice non serve.
# (e' l'impronta pubblica di un certificato, non un segreto)
PINNED_EXPIRED_SHA1 = "a7c18ba99fc1f7afe3be20bcccab0e699fdfea7b"  # pragma: allowlist secret
# True dopo il primo ripiego riuscito: nella sessione si usa subito il client
# diretto, evitando a ogni richiesta l'avviso "Certificato scaduto" di QGIS.
_use_pinned = False


def _only_pinned_expired(errors):
    """True se gli errori SSL sono solo 'scaduto' sul certificato atteso."""
    if not errors:
        return False
    for err in errors:
        digest = err.certificate().digest(QCryptographicHash.Algorithm.Sha1)
        fingerprint = bytes(digest.toHex()).decode("ascii").lower()
        if (err.error() != QSslError.SslError.CertificateExpired
                or fingerprint != PINNED_EXPIRED_SHA1):
            return False
    return True


def _pinned_post(url, body, timeout_ms=None):
    """POST con client Qt diretto; ritorna i byte della risposta o None."""
    nam = QNetworkAccessManager()
    request = QNetworkRequest(QUrl(url))
    request.setHeader(
        QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
    reply = nam.post(request, QByteArray(body))

    def on_ssl_errors(errors):
        if _only_pinned_expired(errors):
            reply.ignoreSslErrors(errors)

    reply.sslErrors.connect(on_ssl_errors)
    loop = QEventLoop()
    reply.finished.connect(loop.quit)
    QTimer.singleShot(int(timeout_ms or PINNED_TIMEOUT_MS), loop.quit)
    loop.exec()
    raw = None
    if not reply.isFinished():
        reply.abort()
    elif reply.error() == QNetworkReply.NetworkError.NoError:
        raw = bytes(reply.readAll()) or None
    reply.deleteLater()
    return raw


def _http_post_json(url, payload, timeout_ms=None):
    """Esegue una POST JSON verso il servizio IGM e restituisce il dizionario.

    timeout_ms: se indicato, limite di tempo della richiesta (oltre al
    timeout di rete impostato in QGIS, che vale comunque).
    """
    if not _HAS_QGIS:
        raise VertoError(
            "Ambiente QGIS non disponibile: impossibile contattare il "
            "servizio IGM."
        )
    global _use_pinned
    body = json.dumps(payload).encode("utf-8")
    if _use_pinned:
        raw = _pinned_post(url, body, timeout_ms)
        if raw:
            return _parse_json(raw.decode("utf-8", "replace"))
    request = QNetworkRequest(QUrl(url))
    request.setHeader(
        QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json"
    )
    if timeout_ms and hasattr(request, "setTransferTimeout"):
        request.setTransferTimeout(int(timeout_ms))
    blocking = QgsBlockingNetworkRequest()
    err = blocking.post(request, QByteArray(body), True)
    if err != QgsBlockingNetworkRequest.ErrorCode.NoError:
        status = blocking.reply().attribute(
            QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if status in (401, 403):
            raise _auth_error("HTTP {}".format(status))
        msg = blocking.errorMessage() or str(err)
        if _is_ssl_message(msg):
            raw = _pinned_post(url, body, timeout_ms)
            if raw:
                _use_pinned = True
                return _parse_json(raw.decode("utf-8", "replace"))
            raise VertoError("{} ({})".format(SSL_HELP, msg))
        raise VertoNetworkError("Errore di rete: {}".format(msg))
    reply = blocking.reply()
    raw = bytes(reply.content())
    if not raw:
        raise VertoError("Risposta vuota dal server IGM.")
    return _parse_json(raw.decode("utf-8", "replace"))


def get_info(endpoint=ENDPOINT):
    """Restituisce (max_coord, [{'epsg': int, 'descrizione': str}, ...])."""
    data = _http_post_json(endpoint, {"richiesta": "info"},
                           timeout_ms=INFO_TIMEOUT_MS)
    if data.get("stato") == "errore":
        raise VertoError(data.get("messaggio", "Errore"), data.get("dove"))
    max_coord = int(data.get("maxCoord", DEFAULT_MAX_COORD))
    srs = with_extra_srs(data.get("srsSupportati", []))
    return max_coord, srs


def _convert_chunk(in_epsg, out_epsg, coords, utente, chiave, endpoint):
    payload = {
        "richiesta": "conversione",
        "utente": utente,
        "chiave": chiave,
        "inEpsg": to_server_epsg(in_epsg),
        "outEpsg": to_server_epsg(out_epsg),
        "coordinate": [{"e": float(e), "n": float(n)} for (e, n) in coords],
    }
    data = _http_post_json(endpoint, payload)
    if data.get("stato") != "successo":
        msg = data.get("messaggio", "Errore di conversione")
        if _looks_like_auth_error(msg):
            raise _auth_error(msg, data.get("dove"))
        raise VertoError(msg, data.get("dove"))
    out = []
    for item in data.get("coordinate", []):
        e, n = item.get("e"), item.get("n")
        if e is None or n is None:
            raise VertoError(
                "Il servizio IGM non ha restituito un risultato per una o "
                "piu' coordinate (controlla che i punti siano in Italia e "
                "nel sistema di origine indicato).")
        out.append((float(e), float(n)))
    if len(out) != len(coords):
        raise VertoError(
            "Numero di coordinate restituite ({}) diverso da quelle inviate "
            "({}).".format(len(out), len(coords))
        )
    return out


def _convert_chunk_retry(in_epsg, out_epsg, coords, utente, chiave, endpoint):
    """_convert_chunk con nuovi tentativi sugli errori di rete."""
    last = None
    for delay in (0,) + tuple(RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            return _convert_chunk(
                in_epsg, out_epsg, coords, utente, chiave, endpoint)
        except VertoNetworkError as exc:
            last = exc
    raise last


def convert(in_epsg, out_epsg, coords, utente=DEFAULT_USER, chiave=DEFAULT_KEY,
            endpoint=ENDPOINT, max_coord=DEFAULT_MAX_COORD, progress_cb=None):
    """
    Converte una lista di coordinate.

    coords: lista di tuple (e, n) -> (est/longitudine, nord/latitudine).
            Per le coordinate geografiche usare gradi sessadecimali.
    Ritorna: lista di tuple (e, n) convertite, nello stesso ordine.
    progress_cb(done, total): callback opzionale di avanzamento.
    """
    if to_server_epsg(in_epsg) == to_server_epsg(out_epsg):
        raise VertoError(
            "Sistema di origine e destinazione coincidono (EPSG:{}). "
            "Le conversioni nello stesso datum non sono supportate.".format(in_epsg)
        )
    coords = list(coords)
    total = len(coords)
    if total == 0:
        return []
    if max_coord <= 0:
        max_coord = DEFAULT_MAX_COORD

    step = min(int(max_coord), CHUNK_SIZE)
    result = []
    for start in range(0, total, step):
        chunk = coords[start:start + step]
        result.extend(_convert_chunk_retry(
            in_epsg, out_epsg, chunk, utente, chiave, endpoint))
        if progress_cb:
            progress_cb(min(start + step, total), total)
    return result
