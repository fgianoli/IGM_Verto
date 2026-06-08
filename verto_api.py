# -*- coding: utf-8 -*-
"""
Client per l'API IGM "VERTO on line".

Documentazione (manuale-verto-online):
    Endpoint POST JSON: https://igmi.esercito.difesa.it/porta-magna/wps/volapi

    Richiesta "info":
        {"richiesta": "info"}
    Risposta:
        {"maxCoord": 32000, "srsSupportati": [{"epsg": 4265, "descrizione": "..."}, ...]}

    Richiesta "conversione":
        {
          "richiesta": "conversione",
          "utente": "...", "chiave": "...",
          "inEpsg": 4265, "outEpsg": 6706,
          "coordinate": [{"e": 7.0, "n": 37.0}, ...]
        }
    Risposta:
        {"stato": "successo", "coordinate": [{"e": ..., "n": ...}, ...]}
    Errore:
        {"stato": "errore", "dove": "...", "messaggio": "..."}

Le coordinate geografiche sono SEMPRE in gradi sessadecimali.
Le conversioni tra lo stesso datum non sono supportate.

Questo modulo e' indipendente dalla GUI e funziona sia dentro QGIS
(usando QgsBlockingNetworkRequest, che rispetta proxy e impostazioni di rete)
sia fuori (fallback urllib), per facilitare i test.
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


def _http_post_json(url, payload, timeout_ms=TIMEOUT_MS):
    """Esegue una POST JSON e restituisce il dizionario di risposta."""
    body = json.dumps(payload).encode("utf-8")

    if _HAS_QGIS:
        request = QNetworkRequest(QUrl(url))
        request.setHeader(
            QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json"
        )
        blocking = QgsBlockingNetworkRequest()
        err = blocking.post(request, QByteArray(body), True)
        if err != QgsBlockingNetworkRequest.ErrorCode.NoError:
            raise VertoError(
                "Errore di rete: {}".format(blocking.errorMessage() or err)
            )
        reply = blocking.reply()
        raw = bytes(reply.content())
        if not raw:
            raise VertoError("Risposta vuota dal server IGM.")
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            raise VertoError(
                "Risposta non valida dal server IGM: {}".format(raw[:200])
            )

    # Fallback urllib (test / uso standalone)
    import urllib.request
    import urllib.error

    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_ms / 1000.0) as resp:
            raw = resp.read()
    except urllib.error.URLError as exc:
        raise VertoError("Errore di rete: {}".format(exc))
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        raise VertoError("Risposta non valida dal server IGM.")


def get_info(endpoint=ENDPOINT):
    """Restituisce (max_coord, [{'epsg': int, 'descrizione': str}, ...])."""
    data = _http_post_json(endpoint, {"richiesta": "info"})
    if data.get("stato") == "errore":
        raise VertoError(data.get("messaggio", "Errore"), data.get("dove"))
    max_coord = int(data.get("maxCoord", DEFAULT_MAX_COORD))
    srs = data.get("srsSupportati", [])
    return max_coord, srs


def _convert_chunk(in_epsg, out_epsg, coords, utente, chiave, endpoint):
    payload = {
        "richiesta": "conversione",
        "utente": utente,
        "chiave": chiave,
        "inEpsg": int(in_epsg),
        "outEpsg": int(out_epsg),
        "coordinate": [{"e": float(e), "n": float(n)} for (e, n) in coords],
    }
    data = _http_post_json(endpoint, payload)
    if data.get("stato") != "successo":
        raise VertoError(
            data.get("messaggio", "Errore di conversione"), data.get("dove")
        )
    out = []
    for item in data.get("coordinate", []):
        out.append((item.get("e"), item.get("n")))
    if len(out) != len(coords):
        raise VertoError(
            "Numero di coordinate restituite ({}) diverso da quelle inviate "
            "({}).".format(len(out), len(coords))
        )
    return out


def convert(
    in_epsg,
    out_epsg,
    coords,
    utente="qgis",
    chiave="qgis",
    endpoint=ENDPOINT,
    max_coord=DEFAULT_MAX_COORD,
    progress_cb=None,
):
    """
    Converte una lista di coordinate.

    coords: lista di tuple (e, n) -> (est/longitudine, nord/latitudine)
            Per le coordinate geografiche usare gradi sessadecimali.
    Ritorna: lista di tuple (e, n) convertite, nello stesso ordine.

    progress_cb(done, total): callback opzionale per la barra di avanzamento.
    """
    if int(in_epsg) == int(out_epsg):
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
