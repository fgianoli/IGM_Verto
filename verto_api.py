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
rispetta le impostazioni di proxy/SSL di QGIS.
"""

import json

ENDPOINT = "https://igmi.esercito.difesa.it/porta-magna/wps/volapi"
DEFAULT_MAX_COORD = 32000
TIMEOUT_MS = 60000

try:
    from qgis.core import QgsBlockingNetworkRequest
    from qgis.PyQt.QtCore import QUrl, QByteArray
    from qgis.PyQt.QtNetwork import QNetworkRequest
    _HAS_QGIS = True
except Exception:  # pragma: no cover - fuori da QGIS
    _HAS_QGIS = False


DEFAULT_USER = "qgis"
DEFAULT_KEY = "qgis"
CREDENTIALS_URL = "https://igmi.esercito.difesa.it/servizi/verto-online/"

# SRS non elencati dal servizio IGM ma ottenibili tramite un equivalente
# supportato: EPSG:7795 (RDN2008 / Zone 12, E-N) ha gli stessi parametri di
# EPSG:6876 (N-E) e differisce solo per l'ordine degli assi; il servizio
# restituisce comunque sempre (est, nord). Il plugin lo inoltra come 6876.
SERVER_ALIAS = {7795: 6876}
EXTRA_SRS = [{"epsg": 7795, "descrizione": "RDN2008 / Zone 12 (E-N)"}]


def to_server_epsg(epsg):
    """Codice EPSG da inviare al servizio (risolve gli alias)."""
    return SERVER_ALIAS.get(int(epsg), int(epsg))


ALIAS_NOTE = (
    "EPSG:{alias} non e' supportato direttamente dal servizio IGM Verto. "
    "Il plugin esegue la conversione verso/da EPSG:{real}, che ha gli stessi "
    "parametri di proiezione (RDN2008 / Zone 12, meridiano centrale 12\u00b0E, "
    "falso est 3.000.000 m) e differisce solo per l'ordine degli assi "
    "(N-E invece di E-N). Le coordinate sono restituite sempre come "
    "(Est, Nord), cioe' nell'ordine E-N proprio dell'EPSG:{alias}. "
    "Il risultato e' quindi quello del grigliato IGM per l'EPSG:{real}."
)


def alias_notice(*epsgs):
    """Testo dell'avviso se tra gli EPSG c'e' un alias, altrimenti None."""
    notes = []
    for e in epsgs:
        try:
            e = int(e)
        except (TypeError, ValueError):
            continue
        if e in SERVER_ALIAS:
            notes.append(ALIAS_NOTE.format(alias=e, real=SERVER_ALIAS[e]))
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


def _http_post_json(url, payload, timeout_ms=TIMEOUT_MS):
    """Esegue una POST JSON verso il servizio IGM e restituisce il dizionario."""
    if not _HAS_QGIS:
        raise VertoError(
            "Ambiente QGIS non disponibile: impossibile contattare il "
            "servizio IGM."
        )
    body = json.dumps(payload).encode("utf-8")
    request = QNetworkRequest(QUrl(url))
    request.setHeader(
        QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json"
    )
    blocking = QgsBlockingNetworkRequest()
    err = blocking.post(request, QByteArray(body), True)
    if err != QgsBlockingNetworkRequest.ErrorCode.NoError:
        status = blocking.reply().attribute(
            QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if status in (401, 403):
            raise _auth_error("HTTP {}".format(status))
        raise VertoError(
            "Errore di rete: {}".format(blocking.errorMessage() or err)
        )
    reply = blocking.reply()
    raw = bytes(reply.content())
    if not raw:
        raise VertoError("Risposta vuota dal server IGM.")
    return _parse_json(raw.decode("utf-8", "replace"))


def get_info(endpoint=ENDPOINT):
    """Restituisce (max_coord, [{'epsg': int, 'descrizione': str}, ...])."""
    data = _http_post_json(endpoint, {"richiesta": "info"})
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
        out.append((item.get("e"), item.get("n")))
    if len(out) != len(coords):
        raise VertoError(
            "Numero di coordinate restituite ({}) diverso da quelle inviate "
            "({}).".format(len(out), len(coords))
        )
    return out


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

    result = []
    for start in range(0, total, max_coord):
        chunk = coords[start:start + max_coord]
        result.extend(
            _convert_chunk(in_epsg, out_epsg, chunk, utente, chiave, endpoint)
        )
        if progress_cb:
            progress_cb(min(start + max_coord, total), total)
    return result
