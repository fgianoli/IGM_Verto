# -*- coding: utf-8 -*-
"""
Logica di conversione geometrie/layer condivisa tra dialog e Processing.

Convenzione API IGM: "e" (est) = X (longitudine/easting), "n" (nord) = Y
(latitudine/northing). QGIS usa la stessa convenzione X=est, Y=nord, quindi
(e, n) == (x, y).
"""

from qgis.core import (
    QgsGeometry,
    QgsCoordinateReferenceSystem,
    QgsVectorLayer,
    QgsFeature,
    QgsFields,
    QgsWkbTypes,
)

from . import verto_api


def crs_to_epsg(crs):
    """Restituisce il codice EPSG (int) di un QgsCoordinateReferenceSystem, o None."""
    if crs is None or not crs.isValid():
        return None
    auth = crs.authid()  # es. "EPSG:3003"
    if auth and auth.upper().startswith("EPSG:"):
        try:
            return int(auth.split(":")[1])
        except (ValueError, IndexError):
            return None
    pg = crs.postgisSrid()
    return int(pg) if pg else None


def epsg_to_crs(epsg):
    return QgsCoordinateReferenceSystem.fromEpsgId(int(epsg))


def convert_geometries(geometries, in_epsg, out_epsg, utente="qgis",
                       chiave="qgis", endpoint=verto_api.ENDPOINT,
                       max_coord=verto_api.DEFAULT_MAX_COORD, progress_cb=None):
    """
    Converte una lista di QgsGeometry. Tutti i vertici di tutte le geometrie
    vengono raccolti e inviati in batch (rispettando max_coord), poi riscritti.
    Restituisce una nuova lista di QgsGeometry (le originali non sono modificate).
    """
    all_points = []
    spans = []          # (start, count) per geometria
    out_geoms = []
    for geom in geometries:
        if geom is None or geom.isEmpty() or geom.isNull():
            spans.append((len(all_points), 0))
            out_geoms.append(QgsGeometry(geom) if geom is not None else QgsGeometry())
            continue
        g = QgsGeometry(geom)  # copia
        pts = [(v.x(), v.y()) for v in g.vertices()]
        spans.append((len(all_points), len(pts)))
        all_points.extend(pts)
        out_geoms.append(g)

    if all_points:
        converted = verto_api.convert(
            in_epsg, out_epsg, all_points,
            utente=utente, chiave=chiave, endpoint=endpoint,
            max_coord=max_coord, progress_cb=progress_cb,
        )
    else:
        converted = []

    for g, (start, count) in zip(out_geoms, spans):
        for k in range(count):
            x, y = converted[start + k]
            g.moveVertex(float(x), float(y), k)
    return out_geoms


def reproject_layer_to_memory(source_layer, out_epsg, selected_only=False,
                              utente="qgis", chiave="qgis",
                              endpoint=verto_api.ENDPOINT,
                              max_coord=verto_api.DEFAULT_MAX_COORD,
                              progress_cb=None, in_epsg=None):
    """
    Riproietta un QgsVectorLayer creando un layer in memoria con CRS out_epsg.
    Restituisce (memory_layer, n_features).
    """
    if in_epsg is None:
        in_epsg = crs_to_epsg(source_layer.crs())
    if in_epsg is None:
        raise verto_api.VertoError(
            "Impossibile determinare il codice EPSG del layer di origine."
        )

    if selected_only:
        features = list(source_layer.selectedFeatures())
    else:
        features = list(source_layer.getFeatures())

    geoms = [f.geometry() for f in features]
    new_geoms = convert_geometries(
        geoms, in_epsg, out_epsg, utente=utente, chiave=chiave,
        endpoint=endpoint, max_coord=max_coord, progress_cb=progress_cb,
    )

    geom_type = QgsWkbTypes.displayString(source_layer.wkbType())
    out_crs = epsg_to_crs(out_epsg)
    uri = "{}?crs={}".format(geom_type, out_crs.authid() or ("EPSG:%d" % out_epsg))
    mem = QgsVectorLayer(
        uri, "{}_EPSG{}".format(source_layer.name(), out_epsg), "memory"
    )
    dp = mem.dataProvider()
    dp.addAttributes(source_layer.fields().toList())
    mem.updateFields()

    out_feats = []
    for f, g in zip(features, new_geoms):
        nf = QgsFeature(mem.fields())
        nf.setAttributes(f.attributes())
        nf.setGeometry(g)
        out_feats.append(nf)
    dp.addFeatures(out_feats)
    mem.updateExtents()
    return mem, len(out_feats)
