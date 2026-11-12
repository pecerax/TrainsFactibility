"""Grilla de elevación regular (lat/lon) de Chile para el trazado interactivo en el navegador.

Se arma desde teselas Terrarium (zoom 8, ~500 m) y se remuestrea a una grilla de paso fijo.
Se codifica en un PNG: elevación + 1000 m en 16 bits (canal R = byte alto, G = byte bajo);
0 = mar o sin dato. El PNG comprime bien y el navegador lo decodifica con un canvas.
"""
import base64
import io
import math

import numpy as np
from PIL import Image

from . import teselas


def grilla(bbox, paso=0.0125, z=8):
    img, b = teselas.mosaico(teselas.URL_TERRARIUM, bbox, z)
    a = np.asarray(img).astype(float)
    elev = a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768
    (lat_s, lon_o), (lat_n, lon_e) = b
    n = 2 ** z
    alto, ancho = elev.shape
    lon0, lat0, lon1, lat1 = bbox
    lons = np.arange(lon0, lon1, paso) + paso / 2
    lats = np.arange(lat1, lat0, -paso) - paso / 2  # de norte a sur
    # posición de cada lon/lat en pixeles del mosaico Mercator
    x0 = (lon_o + 180) / 360 * n * 256
    y0 = (1 - math.asinh(math.tan(math.radians(lat_n))) / math.pi) / 2 * n * 256
    px = (lons + 180) / 360 * n * 256 - x0
    py = (1 - np.arcsinh(np.tan(np.radians(lats))) / np.pi) / 2 * n * 256 - y0
    xi = np.clip(px.astype(int), 0, ancho - 1)
    yi = np.clip(py.astype(int), 0, alto - 1)
    g = elev[np.ix_(yi, xi)]
    return g, (lon0, lat1, paso)


def a_png_uri(g):
    v = np.where(g > 0, np.clip(np.round(g) + 1000, 1, 65535), 0).astype(np.uint16)
    rgb = np.zeros(v.shape + (3,), np.uint8)
    rgb[..., 0] = v >> 8
    rgb[..., 1] = v & 255
    buf = io.BytesIO()
    Image.fromarray(rgb, "RGB").save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(), len(buf.getvalue())


# ---------------- restricciones territoriales en la grilla ----------------
# Banderas por celda (canal azul del PNG):
BANDERAS = {"estricta": 1, "sensible": 2, "indigena": 4, "urbano": 8, "ffcc": 16}
# Áreas protegidas donde una obra nueva es muy difícil de aprobar (SEIA, Ley 21.600)
TIPOS_ESTRICTOS = {"PN", "MN", "RN", "SN", "RAMSAR"}
# Áreas que suben el costo o el riesgo de tramitación, sin bloquear
TIPOS_SENSIBLES = {"APC", "APE", "APPP", "IFDC", "SPB", "RBIO"}


def banderas(bbox, paso, forma):
    """Rasteriza las capas territoriales sobre la grilla (mismo origen y paso que `grilla`)."""
    import geopandas as gpd
    from rasterio.features import rasterize
    from rasterio.transform import from_origin

    from .config import PROCESADO

    lon0, _, _, lat1 = bbox
    tr = from_origin(lon0, lat1, paso, paso)
    b = np.zeros(forma, np.uint8)

    def quemar(geoms, valor, todas=False):
        geoms = [g for g in geoms if g is not None and not g.is_empty]
        if geoms:
            m = rasterize(((g, 1) for g in geoms), out_shape=forma, transform=tr, all_touched=todas, dtype=np.uint8)
            b[m == 1] |= valor

    ap = gpd.read_file(PROCESADO / "areas_protegidas.geojson")
    quemar(ap[ap.TIPO.isin(TIPOS_ESTRICTOS)].geometry, BANDERAS["estricta"])
    quemar(ap[ap.TIPO.isin(TIPOS_SENSIBLES)].geometry, BANDERAS["sensible"])
    quemar(gpd.read_file(PROCESADO / "areas_desarrollo_indigena.geojson").geometry, BANDERAS["indigena"])
    quemar(gpd.read_file(PROCESADO / "areas_urbanas.geojson").geometry, BANDERAS["urbano"], todas=True)
    ff = gpd.read_file(PROCESADO / "red_ferroviaria.geojson")
    quemar(ff[ff.operativa].geometry, BANDERAS["ffcc"], todas=True)
    return b


def a_png_uri_con_banderas(g, b):
    v = np.where(g > 0, np.clip(np.round(g) + 1000, 1, 65535), 0).astype(np.uint16)
    rgb = np.zeros(v.shape + (3,), np.uint8)
    rgb[..., 0] = v >> 8
    rgb[..., 1] = v & 255
    rgb[..., 2] = b
    buf = io.BytesIO()
    Image.fromarray(rgb, "RGB").save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(), len(buf.getvalue())


def ciudades():
    """Áreas urbanas con su población 2025 (GHSL) y centroide: candidatas a estación."""
    import geopandas as gpd
    import rasterio
    from rasterio.mask import mask

    from .config import CACHE, PROCESADO

    u = gpd.read_file(PROCESADO / "areas_urbanas.geojson")
    # Se agrupan polígonos del mismo nombre (una ciudad puede venir en varias piezas)
    u = u.dissolve(by="NOMBRE", as_index=False)
    out = []
    with rasterio.open(CACHE / "poblacion_2025_1km.tif") as src:
        for _, f in u.iterrows():
            try:
                arr, _ = mask(src, [f.geometry.buffer(0.01)], crop=True, all_touched=True)
                pob = float(arr[arr > 0].sum())
            except ValueError:
                pob = 0.0
            c = f.geometry.representative_point()
            out.append({"nombre": f.NOMBRE.title(), "lon": round(c.x, 4), "lat": round(c.y, 4), "pob": round(pob)})
    return sorted(out, key=lambda d: -d["pob"])
