# -*- coding: utf-8 -*-
"""Gestione delle impostazioni del plugin (credenziali, endpoint, cache SRS).

Nel file di configurazione di QGIS (QGIS3.ini / QGIS4.ini) finiscono solo i
valori che l'utente ha cambiato rispetto ai predefiniti. L'elenco dei sistemi
in cache sta in un file nella cartella del plugin, che QGIS elimina con la
disinstallazione. QGIS non avvisa i plugin quando vengono disinstallati: per
rimuovere anche le impostazioni personali c'e' clear_all() (pulsante in
Impostazioni).
"""

import json
import os
import time

from qgis.PyQt.QtCore import QSettings

from . import verto_api

_PREFIX = "igm_verto/"


def _s():
    return QSettings()


def get_utente():
    return _s().value(_PREFIX + "utente", verto_api.DEFAULT_USER, type=str)


def _set_or_remove(name, value, default):
    """Salva il valore solo se diverso dal predefinito, altrimenti lo toglie."""
    if value and value != default:
        _s().setValue(_PREFIX + name, value)
    else:
        _s().remove(_PREFIX + name)


def set_utente(value):
    _set_or_remove("utente", value, verto_api.DEFAULT_USER)


# La chiave personale e' salvata cifrata nel gestore di autenticazione di
# QGIS; se non e' disponibile si ripiega sulle impostazioni in chiaro.
# NB: chiamare get_chiave/set_chiave solo dal thread principale (il gestore
# puo' chiedere la password principale).
_AUTH_SETTING = "igm_verto_chiave"


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
    if am is not None and am.existsAuthSetting(_AUTH_SETTING):
        value = am.authSetting(_AUTH_SETTING, "", True)
        if value:
            return str(value)
    return _s().value(_PREFIX + "chiave", verto_api.DEFAULT_KEY, type=str)


def set_chiave(value):
    """Salva la chiave. Ritorna True se e' stata salvata cifrata."""
    am = _auth()
    if value and value != verto_api.DEFAULT_KEY and am is not None:
        if am.storeAuthSetting(_AUTH_SETTING, value, True):
            _s().remove(_PREFIX + "chiave")
            return True
    if am is not None and am.existsAuthSetting(_AUTH_SETTING):
        am.removeAuthSetting(_AUTH_SETTING)
    _set_or_remove("chiave", value, verto_api.DEFAULT_KEY)
    return False


def has_personal_credentials():
    """True se l'utente ha impostato credenziali diverse dai segnaposto."""
    return (get_utente() != verto_api.DEFAULT_USER
            and get_chiave() != verto_api.DEFAULT_KEY)


def get_endpoint():
    return _s().value(_PREFIX + "endpoint", verto_api.ENDPOINT, type=str)


def set_endpoint(value):
    _set_or_remove("endpoint", value, verto_api.ENDPOINT)


# Cache dell'elenco SRS: file nella cartella del plugin (non nel file ini).
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "srs_cache.json")


def _read_cache():
    """Contenuto della cache: {"time", "max_coord", "srs"} oppure {}."""
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def get_cached_srs():
    """Restituisce la lista SRS in cache, o None se assente."""
    return _read_cache().get("srs") or None


def set_cached_srs(srs_list, max_coord=verto_api.DEFAULT_MAX_COORD):
    """Scrive la cache; ritorna False se la cartella non e' scrivibile."""
    data = {"time": time.time(), "max_coord": int(max_coord), "srs": srs_list}
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        return False
    return True


def cache_is_fresh():
    """True se l'elenco SRS in cache ha meno di CACHE_TTL_S secondi."""
    saved = float(_read_cache().get("time", 0) or 0)
    return 0 <= time.time() - saved < CACHE_TTL_S


# Chiavi scritte nel file ini dalle versioni precedenti e non piu' usate.
_LEGACY_KEYS = ("srs_cache", "srs_cache_time", "max_coord", "ignore_ssl_errors")


def cleanup_legacy():
    """Toglie dal file ini le chiavi obsolete e i valori uguali ai predefiniti."""
    s = _s()
    for name in _LEGACY_KEYS:
        s.remove(_PREFIX + name)
    for name, default in (("utente", verto_api.DEFAULT_USER),
                          ("chiave", verto_api.DEFAULT_KEY),
                          ("endpoint", verto_api.ENDPOINT)):
        if s.value(_PREFIX + name, default, type=str) == default:
            s.remove(_PREFIX + name)


def clear_all():
    """Elimina tutto cio' che il plugin ha salvato: impostazioni nel file ini,
    chiave nel gestore di autenticazione e cache dell'elenco SRS."""
    global _info_failed
    cleanup_legacy()
    for name in ("utente", "chiave", "endpoint"):
        _s().remove(_PREFIX + name)
    am = _auth()
    if am is not None and am.existsAuthSetting(_AUTH_SETTING):
        am.removeAuthSetting(_AUTH_SETTING)
    if os.path.exists(CACHE_FILE):
        os.remove(CACHE_FILE)
    _info_failed = False


def supported_epsg():
    """Insieme dei codici EPSG accettati dal plugin (alias compresi)."""
    _max, srs = load_srs()
    return {int(x["epsg"]) for x in srs}


def get_max_coord():
    value = _read_cache().get("max_coord")
    return int(value) if value else verto_api.DEFAULT_MAX_COORD


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
    set_cached_srs(srs, max_coord)
    return max_coord, srs
