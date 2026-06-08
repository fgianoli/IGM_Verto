# -*- coding: utf-8 -*-
"""Gestione delle impostazioni del plugin (credenziali, endpoint, cache SRS)."""

import json

from qgis.PyQt.QtCore import QSettings

from . import verto_api

_PREFIX = "igm_verto/"


def _s():
    return QSettings()


def get_utente():
    return _s().value(_PREFIX + "utente", "qgis", type=str)


def set_utente(value):
    _s().setValue(_PREFIX + "utente", value)


def get_chiave():
    return _s().value(_PREFIX + "chiave", "qgis", type=str)


def set_chiave(value):
    _s().setValue(_PREFIX + "chiave", value)


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
    {"epsg": 6706, "descrizione": "RDN2008 2D geo"},
    {"epsg": 6707, "descrizione": "RDN2008 / TM32"},
    {"epsg": 6708, "descrizione": "RDN2008 / TM33"},
    {"epsg": 6709, "descrizione": "RDN2008 / TM34"},
    {"epsg": 7794, "descrizione": "RDN2008 / Italy Zone EN"},
    {"epsg": 6876, "descrizione": "RDN2008 / Zone 12"},
]


def load_srs(force_refresh=False):
    """
    Restituisce (max_coord, srs_list).
    Prova la cache; se assente o force_refresh interroga l'API; in caso di
    errore di rete usa la cache o il fallback statico.
    """
    if not force_refresh:
        cached = get_cached_srs()
        if cached:
            return get_max_coord(), cached
    try:
        max_coord, srs = verto_api.get_info(get_endpoint())
        if srs:
            set_cached_srs(srs)
            set_max_coord(max_coord)
            return max_coord, srs
    except verto_api.VertoError:
        pass
    cached = get_cached_srs()
    if cached:
        return get_max_coord(), cached
    return verto_api.DEFAULT_MAX_COORD, list(FALLBACK_SRS)
