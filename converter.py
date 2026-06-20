# -*- coding: utf-8 -*-
"""
Logica di conversione geometrie/layer condivisa tra dialog e Processing.

Convenzione API IGM: "e" (est) = X (longitudine/easting), "n" (nord) = Y
(latitudine/northing). QGIS usa la stessa convenzione X=est, Y=nord, quindi
(e, n) == (x, y).
"""

from qgis.core import (
    QgsGeometry,
    QgsPoint,
    QgsCoordinateReferenceSystem,
    QgsVectorLayer,
    QgsFeature,
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


# Famiglie di datum tra i sistemi supportati da IGM. Il servizio non converte
# tra sistemi dello stesso datum (cambio di sola proiezione/fuso): in quel caso
# va usata la riproiezione standard di QGIS, esatta e senza grigliati.
DATUM_FAMILIES = {
    "Monte Mario / Roma40": {4265, 3003, 3004, 4806},
    "ED50": {4230, 23032, 23033, 23034},
    "IGM95": {4670, 3064, 3065, 9716},
    "RDN2008 / ETRS89": {6706, 6707, 6708, 6709, 7794, 6876, 3035, 3034},
}


def datum_of(epsg):
    """Restituisce il nome della famiglia di datum dell'EPSG, o None."""
    try:
        code = int(epsg)
    except (TypeError, ValueError):
        return None
    for name, codes in DATUM_FAMILIES.items():
        if code in codes:
            return name
    return None


def same_datum(in_epsg, out_epsg):
    """True se i due EPSG appartengono allo stesso datum (conversione non
    ammessa dal servizio IGM)."""
    da = datum_of(in_epsg)
    db = datum_of(out_epsg)
    return da is not None and da == db


def convert_geometries(geometries, in_epsg, out_epsg, utente="qgis",
                       chiave="qgis", endpoint=verto_api.ENDPOINT,
                       max_coord=verto_api.DEFAULT_MAX_COORD, progress_cb=None):
    """
    Converte una lista di QgsGeometry. Tutti i vertici di tutte le geometrie
    vengono raccolti e inviati in batch (rispettando max_coord), poi riscritti.
    La quota Z e l'eventuale valore M dei vertici vengono preservati (il
    servizio IGM converte solo la planimetria).
    Restituisce una nuova lista di QgsGeometry (le originali non sono modificate).
    """
    all_points = []
    orig_meta = []      # (z, m) per vertice, per conservare quota/misura
    spans = []          # (start, count) per geometria
    out_geoms = []
    for geom in geometries:
        if geom is None or geom.isEmpty() or geom.isNull():
            spans.append((len(all_points), 0))
            out_geoms.append(QgsGeometry(geom) if geom is not None else QgsGeometry())
            continue
        g = QgsGeometry(geom)  # copia
        start = len(all_points)
        count = 0
        for v in g.vertices():
            all_points.append((v.x(), v.y()))
            z = v.z() if v.is3D() else None
            m = v.m() if v.isMeasure() else None
            orig_meta.append((z, m))
            count += 1
        spans.append((start, count))
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
            z, m = orig_meta[start + k]
            new_pt = QgsPoint(float(x), float(y))
            if z is not None:
                new_pt.addZValue(z)
            if m is not None:
                new_pt.addMValue(m)
            g.moveVertex(new_pt, k)
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


def geoms_to_memory_layer(name, fields, wkb_type, out_epsg, attributes, geoms):
    """Costruisce un layer in memoria da geometrie gia' convertite.

    Pensata per essere chiamata nel thread principale (es. al termine di un
    QgsTask), separando la parte di rete da quella di costruzione del layer.
    """
    geom_type = QgsWkbTypes.displayString(wkb_type)
    out_crs = epsg_to_crs(out_epsg)
    uri = "{}?crs={}".format(geom_type, out_crs.authid() or ("EPSG:%d" % out_epsg))
    mem = QgsVectorLayer(uri, name, "memory")
    dp = mem.dataProvider()
    dp.addAttributes(fields.toList())
    mem.updateFields()
    feats = []
    for attrs, g in zip(attributes, geoms):
        nf = QgsFeature(mem.fields())
        nf.setAttributes(attrs)
        nf.setGeometry(g)
        feats.append(nf)
    dp.addFeatures(feats)
    mem.updateExtents()
    return mem, len(feats)


# --------------------------------------------------------------------------
# Salvataggio su file e conversione batch di una cartella
# --------------------------------------------------------------------------
import os  # noqa: E402

VECTOR_EXTS = {".shp", ".gpkg", ".geojson", ".json", ".kml", ".gml",
               ".tab", ".csv"}

_DRIVER_BY_EXT = {
    ".gpkg": "GPKG", ".shp": "ESRI Shapefile", ".geojson": "GeoJSON",
    ".json": "GeoJSON", ".kml": "KML", ".gml": "GML", ".csv": "CSV",
}


def list_vector_files(folder, recursive=False):
    """Elenco di file vettoriali in una cartella (ordinato)."""
    out = []
    if recursive:
        for dp, _dn, fn in os.walk(folder):
            for f in fn:
                if os.path.splitext(f)[1].lower() in VECTOR_EXTS:
                    out.append(os.path.join(dp, f))
    else:
        for f in os.listdir(folder):
            p = os.path.join(folder, f)
            if os.path.isfile(p) and os.path.splitext(f)[1].lower() in VECTOR_EXTS:
                out.append(p)
    return sorted(out)


def write_vector(layer, out_path):
    """Scrive un QgsVectorLayer su file scegliendo il driver dall'estensione."""
    from qgis.core import QgsVectorFileWriter, QgsProject
    ext = os.path.splitext(out_path)[1].lower()
    driver = _DRIVER_BY_EXT.get(ext, "GPKG")
    ctx = QgsProject.instance().transformContext()
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = driver
    if ext == ".gpkg":
        opts.layerName = os.path.splitext(os.path.basename(out_path))[0]
    try:
        res = QgsVectorFileWriter.writeAsVectorFormatV3(layer, out_path, ctx, opts)
    except AttributeError:  # QGIS < 3.20
        res = QgsVectorFileWriter.writeAsVectorFormatV2(layer, out_path, ctx, opts)
    code = res[0] if isinstance(res, (tuple, list)) else res
    if code != QgsVectorFileWriter.NoError:
        detail = res[1] if isinstance(res, (tuple, list)) and len(res) > 1 else code
        raise verto_api.VertoError("Scrittura su file fallita: {}".format(detail))
    return out_path


def reproject_path_to_file(in_path, out_path, out_epsg, fallback_in_epsg=None,
                           **kwargs):
    """Apre un file vettoriale, lo riproietta via IGM e lo salva su out_path."""
    from qgis.core import QgsVectorLayer
    layer = QgsVectorLayer(in_path, os.path.basename(in_path), "ogr")
    if not layer.isValid():
        raise verto_api.VertoError("Layer non valido: {}".format(in_path))
    in_epsg = crs_to_epsg(layer.crs()) or fallback_in_epsg
    if in_epsg is None:
        raise verto_api.VertoError(
            "CRS non determinabile per {}".format(os.path.basename(in_path)))
    mem, n = reproject_layer_to_memory(layer, out_epsg, in_epsg=in_epsg, **kwargs)
    write_vector(mem, out_path)
    return n
