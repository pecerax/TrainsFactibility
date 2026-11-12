"""Descarga de capas desde servicios ArcGIS REST (MapServer/FeatureServer) como GeoDataFrame."""
import json
import time

import geopandas as gpd
import requests
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon


def descargar(url_capa: str, where: str = "1=1", campos: str = "*", simplificar_grados: float | None = None,
              bbox=None, lote: int | None = None) -> gpd.GeoDataFrame:
    """Pagina la consulta por OBJECTID para no depender de resultOffset (no todos los servidores lo aceptan)."""
    info = requests.get(url_capa, params={"f": "json"}, timeout=120).json()
    lote = lote or min(info.get("maxRecordCount") or 1000, 1000)
    base = {"where": where, "f": "json", "returnIdsOnly": "true"}
    if bbox:
        base.update({"geometry": ",".join(map(str, bbox)), "geometryType": "esriGeometryEnvelope",
                     "inSR": 4326, "spatialRel": "esriSpatialRelIntersects"})
    ids = sorted(_get(url_capa + "/query", base).get("objectIds") or [])
    feats = []
    for i in range(0, len(ids), lote):
        p = {"objectIds": ",".join(map(str, ids[i:i + lote])), "outFields": campos, "outSR": 4326,
             "returnGeometry": "true", "f": "json"}
        if simplificar_grados:
            p["maxAllowableOffset"] = simplificar_grados
        feats += _get(url_capa + "/query", p, metodo="post").get("features", [])
    if not feats:
        return gpd.GeoDataFrame(geometry=[], crs=4326)
    filas = [f.get("attributes", {}) for f in feats]
    geoms = [_geom(f.get("geometry")) for f in feats]
    return gpd.GeoDataFrame(filas, geometry=geoms, crs=4326)


def _area(r):
    return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(r, r[1:] + r[:1])) / 2


def _geom(g):
    """Geometría Esri JSON -> shapely (anillos horarios = exteriores, antihorarios = huecos)."""
    if not g:
        return None
    if "x" in g:
        return Point(g["x"], g["y"])
    if "paths" in g:
        ps = [LineString(p) for p in g["paths"] if len(p) >= 2]
        return ps[0] if len(ps) == 1 else MultiLineString(ps)
    if "rings" in g:
        ext, huecos = [], []
        for r in g["rings"]:
            if len(r) < 4:
                continue
            (ext if _area([tuple(c[:2]) for c in r]) < 0 else huecos).append(r)
        polys = []
        for e in ext:
            pe = Polygon(e)
            hs = [h for h in huecos if pe.contains(Point(h[0][:2]))]
            polys.append(Polygon(e, hs).buffer(0))
        if not polys and huecos:  # anillos con orientación invertida
            polys = [Polygon(h).buffer(0) for h in huecos]
        return polys[0] if len(polys) == 1 else MultiPolygon([q for p in polys for q in getattr(p, "geoms", [p])])
    return None


def _get(url, params, metodo="get"):
    for intento in range(4):
        try:
            r = (requests.post(url, data=params, timeout=300) if metodo == "post"
                 else requests.get(url, params=params, timeout=300))
            r.raise_for_status()
            d = r.json()
            if "error" in d:
                raise RuntimeError(json.dumps(d["error"])[:300])
            return d
        except Exception:
            if intento == 3:
                raise
            time.sleep(3 * (intento + 1))
