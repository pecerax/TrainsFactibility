"""Mosaicos raster de Chile para el mapa web: relieve (desde teselas Terrarium de AWS) y geología (Macrostrat).

Se descargan teselas web Mercator a un zoom fijo, se unen en una sola imagen y se
guardan junto con sus límites geográficos, para usarlas como L.imageOverlay en Leaflet.
"""
import io
import math
import time

import numpy as np
import requests
from PIL import Image

from .config import CACHE

URL_TERRARIUM = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
URL_GEOLOGIA = "https://tiles.macrostrat.org/carto/{z}/{x}/{y}.png"


def _xy(lon, lat, z):
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def _lonlat(x, y, z):
    n = 2 ** z
    lon = x / n * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lon, lat


def _tesela(url, z, x, y):
    destino = CACHE / "teselas" / url.split("//")[1].split("/")[0] / f"{z}_{x}_{y}.png"
    if destino.exists():
        return Image.open(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    for intento in range(3):
        try:
            r = requests.get(url.format(z=z, x=x, y=y), timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            destino.write_bytes(r.content)
            return Image.open(io.BytesIO(r.content))
        except requests.RequestException:
            time.sleep(2 * (intento + 1))
    return None


def mosaico(url, bbox, z):
    """Devuelve (imagen RGBA, bounds [[lat_s, lon_o], [lat_n, lon_e]])."""
    lon0, lat0, lon1, lat1 = bbox
    x0, y0 = (int(v) for v in _xy(lon0, lat1, z))
    x1, y1 = (int(v) for v in _xy(lon1, lat0, z))
    teselas = {(x, y): _tesela(url, z, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}
    lado = 256
    for t in teselas.values():
        if t is not None:  # Macrostrat entrega teselas de 512 px; Terrarium de 256
            lado = t.size[0]
            break
    img = Image.new("RGBA", ((x1 - x0 + 1) * lado, (y1 - y0 + 1) * lado))
    for (x, y), t in teselas.items():
        if t is not None:
            t = t.convert("RGBA")
            if t.size[0] != lado:
                t = t.resize((lado, lado))
            img.paste(t, ((x - x0) * lado, (y - y0) * lado))
    lon_o, lat_n = _lonlat(x0, y0, z)
    lon_e, lat_s = _lonlat(x1 + 1, y1 + 1, z)
    return img, [[lat_s, lon_o], [lat_n, lon_e]]


def relieve(bbox, z=7):
    """Relieve sombreado con tinte hipsométrico. Devuelve (Image RGB, bounds)."""
    img, bounds = mosaico(URL_TERRARIUM, bbox, z)
    a = np.asarray(img).astype(float)
    elev = a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768
    # tamaño de pixel aprox. en metros a la latitud media
    lat_m = (bounds[0][0] + bounds[1][0]) / 2
    px = 40_075_016 * math.cos(math.radians(lat_m)) / (256 * 2 ** z)
    gy, gx = np.gradient(elev, px)
    pend = np.arctan(np.hypot(gx, gy) * 2.0)  # exageración vertical x2
    asp = np.arctan2(-gx, gy)
    az, alt = math.radians(315), math.radians(45)
    hs = np.sin(alt) * np.cos(pend) + np.cos(alt) * np.sin(pend) * np.cos(az - asp)
    hs = np.clip(hs, 0, 1)
    # Paleta hipsométrica sobria (m s.n.m.)
    paradas = [(0, (196, 210, 170)), (500, (214, 214, 168)), (1500, (200, 180, 140)),
               (3000, (170, 140, 115)), (4500, (150, 135, 130)), (6000, (245, 245, 245))]
    e = np.clip(elev, 0, 6000)
    col = np.zeros(elev.shape + (3,))
    xs = [p[0] for p in paradas]
    for c in range(3):
        col[..., c] = np.interp(e, xs, [p[1][c] for p in paradas])
    rgb = col * (0.45 + 0.65 * hs[..., None])
    mar = elev <= 0
    rgb[mar] = (178, 203, 222)
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB"), bounds


def geologia(bbox, z=7):
    img, bounds = mosaico(URL_GEOLOGIA, bbox, z)
    img = img.resize((img.width // 2, img.height // 2), Image.LANCZOS) if img.width > 2000 else img
    return img.convert("RGB"), bounds
