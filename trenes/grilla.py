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
