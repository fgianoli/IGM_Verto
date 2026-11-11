# -*- coding: utf-8 -*-
"""Gestione delle impostazioni del plugin (credenziali, endpoint, cache SRS)."""

import json
import time

from qgis.PyQt.QtCore import QSettings

from . import verto_api

_PREFIX = "igm_verto/"


def _s():
    return QSettings()


def get_utente():
    return _s().value(_PREFIX + "utente", verto_api.DEFAULT_USER, type=str)


def set_utente(value):
    _s().setValue(_PREFIX + "utente", value)


# La chiave personale e' salvata cifrata nel gestore di autenticazione di
# QGIS; se non e' disponibile si ripiega sulle impostazioni in chiaro.
# NB: chiamare get_chiave/set_chiave solo dal thread principale (il gestore
# puo' chiedere la password principale).
_AUTH_KEY = "igm_verto_chiave"


def _auth():
    """Gestore di autenticazione di QGIS, o None se non utilizzabile."""
    from qgis.core import QgsApplication
    am = QgsApplication.authManager()
    if am is None or not hasattr(am, "storeAuthSetting"):
        return None
    if am.isDisabled():
        return None
    return am


def get_chiave():
    am = _auth()
    if am is not None and am.existsAuthSetting(_AUTH_KEY):
        value = am.authSetting(_AUTH_KEY, "", True)
        if value:
            return str(value)
    return _s().value(_PREFIX + "chiave", verto_api.DEFAULT_KEY, type=str)


def set_chiave(value):
    """Salva la chiave. Ritorna True se e' stata salvata cifrata."""
    am = _auth()
    if value and value != verto_api.DEFAULT_KEY and am is not None:
        if am.storeAuthSetting(_AUTH_KEY, value, True):
            _s().remove(_PREFIX + "chiave")
            return True
    if am is not None and am.existsAuthSetting(_AUTH_KEY):
        am.removeAuthSetting(_AUTH_KEY)
    _s().setValue(_PREFIX + "chiave", value)
    return False


def has_personal_credentials():
    """True se l'utente ha impostato credenziali diverse dai segnaposto."""
    return (get_utente() != verto_api.DEFAULT_USER
            and get_chiave() != verto_api.DEFAULT_KEY)


def get_endpoint():
    return _s().value(_PREFIX + "endpoint", verto_api.ENDPOINT, type=str)


def set_endpoint(value):
    _s().setValue(_PREFIX + "endpoint", value or verto_api.ENDPOINT)


def get_cached_srs():
    """Restituisce la lista SRS in cache, o None se assente."""
    raw = _s().value(_PREFIX + "srs_cache", "", type=str)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def set_cached_srs(srs_list):
    _s().setValue(_PREFIX + "srs_cache", json.dumps(srs_list))
    _s().setValue(_PREFIX + "srs_cache_time", float(time.time()))


def cache_is_fresh():
    """True se l'elenco SRS in cache ha meno di CACHE_TTL_S secondi."""
    saved = _s().value(_PREFIX + "srs_cache_time", 0.0, type=float)
    return 0 <= time.time() - saved < CACHE_TTL_S


def supported_epsg():
    """Insieme dei codici EPSG accettati dal plugin (alias compresi)."""
    _max, srs = load_srs()
    return {int(x["epsg"]) for x in srs}


def get_max_coord():
    return _s().value(_PREFIX + "max_coord", verto_api.DEFAULT_MAX_COORD, type=int)


def set_max_coord(value):
    _s().setValue(_PREFIX + "max_coord", int(value))


# Elenco di fallback dei sistemi supportati (richiesta "info" del servizio IGM),
# usato se la chiamata "info" non e' ancora stata eseguita o manca la rete.
FALLBACK_SRS = [
    {"epsg": 4265, "descrizione": "Monte Mario"},
    {"epsg": 3003, "descrizione": "Monte Mario / Italy zone 1"},
    {"epsg": 3004, "descrizione": "Monte Mario / Italy zone 2"},
    {"epsg": 4806, "descrizione": "Monte Mario (Rome)"},
    {"epsg": 4230, "descrizione": "ED50"},
    {"epsg": 23032, "descrizione": "ED50 / UTM zone 32N"},
    {"epsg": 23033, "descrizione": "ED50 / UTM zone 33N"},
    {"epsg": 23034, "descrizione": "ED50 / UTM zone 34N"},
    {"epsg": 4670, "descrizione": "IGM95"},
    {"epsg": 3064, "descrizione": "IGM95 / UTM zone 32N"},
    {"epsg": 3065, "descrizione": "IGM95 / UTM zone 33N"},
    {"epsg": 9716, "descrizione": "IGM95 / UTM zone 34N"},
    {"epsg": 3035, "descrizione": "ETRS89 / ETRS-LAEA"},
    {"epsg": 3034, "descrizione": "ETRS89 / ETRS-LCC"},
    {"epsg": 6706, "descrizione": "RDN2008 2D (geo)"},
    {"epsg": 7791, "descrizione": "RDN2008 / UTM zone 32N (E-N)"},
    {"epsg": 7792, "descrizione": "RDN2008 / UTM zone 33N (E-N)"},
    {"epsg": 7793, "descrizione": "RDN2008 / UTM zone 34N (E-N)"},
    {"epsg": 7794, "descrizione": "RDN2008 / Italy Zone (E-N)"},
    {"epsg": 7795, "descrizione": "RDN2008 / Zone 12 (E-N)"},
]


# L'elenco in cache viene rinnovato dal servizio dopo una settimana.
CACHE_TTL_S = 7 * 24 * 3600
# True dopo una richiesta "info" fallita: nella stessa sessione di QGIS non si
# riprova in automatico (evita blocchi e avvisi ripetuti a server irraggiungibile).
_info_failed = False


def _offline_srs():
    cached = get_cached_srs()
    if cached:
        return get_max_coord(), verto_api.with_extra_srs(cached)
    return verto_api.DEFAULT_MAX_COORD, verto_api.with_extra_srs(FALLBACK_SRS)


def load_srs(force_refresh=False):
    """
    Restituisce (max_coord, srs_list).
    Usa la cache se recente; altrimenti (o con force_refresh) interroga l'API,
    al piu' una volta per sessione in caso di errore; se la rete non risponde
    usa la cache o l'elenco statico.
    """
    global _info_failed
    if not force_refresh:
        if _info_failed or (get_cached_srs() and cache_is_fresh()):
            return _offline_srs()
    try:
        return refresh_srs()
    except verto_api.VertoError:
        _info_failed = True
        return _offline_srs()


def refresh_srs():
    """Interroga il servizio e aggiorna la cache. Solleva VertoError."""
    global _info_failed
    max_coord, srs = verto_api.get_info(get_endpoint())
    if not srs:
        raise verto_api.VertoError("Il servizio IGM non ha restituito sistemi.")
    _info_failed = False
    set_cached_srs(srs)
    set_max_coord(max_coord)
    return max_coord, srs
