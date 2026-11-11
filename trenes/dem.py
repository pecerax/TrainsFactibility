"""Elevación desde Copernicus DEM (GLO-90 por defecto, GLO-30 opcional)."""
import math
from pathlib import Path

import numpy as np
import rasterio
import requests

from .config import CACHE

URLS = {
    90: ("https://copernicus-dem-90m.s3.amazonaws.com", "Copernicus_DSM_COG_30_{lat}_00_{lon}_00_DEM"),
    30: ("https://copernicus-dem-30m.s3.amazonaws.com", "Copernicus_DSM_COG_10_{lat}_00_{lon}_00_DEM"),
}


def _nombre_tile(lat: float, lon: float, res: int) -> str:
    la, lo = math.floor(lat), math.floor(lon)
    lat_s = f"{'N' if la >= 0 else 'S'}{abs(la):02d}"
    lon_s = f"{'E' if lo >= 0 else 'W'}{abs(lo):03d}"
    return URLS[res][1].format(lat=lat_s, lon=lon_s)


def _tile(nombre: str, res: int) -> Path | None:
    destino = CACHE / "dem" / f"{nombre}.tif"
    if destino.exists():
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    url = f"{URLS[res][0]}/{nombre}/{nombre}.tif"
    r = requests.get(url, timeout=300)
    if r.status_code == 404:  # tile de océano: no existe
        return None
    r.raise_for_status()
    destino.write_bytes(r.content)
    return destino


def elevaciones(lons: np.ndarray, lats: np.ndarray, res: int = 90) -> np.ndarray:
    """Elevación (m s.n.m.) en cada punto. NaN donde no hay tile (mar)."""
    z = np.full(len(lons), np.nan)
    nombres = np.array([_nombre_tile(la, lo, res) for lo, la in zip(lons, lats)])
    for nombre in np.unique(nombres):
        idx = np.where(nombres == nombre)[0]
        ruta = _tile(nombre, res)
        if ruta is None:
            continue
        with rasterio.open(ruta) as src:
            vals = np.array([v[0] for v in src.sample(zip(lons[idx], lats[idx]))], dtype=float)
            if src.nodata is not None:
                vals[vals == src.nodata] = np.nan
        z[idx] = vals
    # Copernicus usa 0 exacto en mar y en algunos bordes de tile: se trata como sin dato
    z[z == 0] = np.nan
    return z


def mosaico(lon_min: float, lat_min: float, lon_max: float, lat_max: float, res: int = 90,
            factor: int = 2):
    """Mosaico del DEM en la caja pedida, submuestreado por `factor`.

    Devuelve (z, transform) con z en metros (NaN en mar) y la transformación afín de rasterio.
    """
    from rasterio.merge import merge
    from rasterio.enums import Resampling

    rutas = []
    for la in range(math.floor(lat_min), math.floor(lat_max) + 1):
        for lo in range(math.floor(lon_min), math.floor(lon_max) + 1):
            r = _tile(_nombre_tile(la + 0.5, lo + 0.5, res), res)
            if r is not None:
                rutas.append(r)
    srcs = [rasterio.open(r) for r in rutas]
    paso = srcs[0].res[0] * factor
    z, tr = merge(srcs, bounds=(lon_min, lat_min, lon_max, lat_max), res=paso,
                  resampling=Resampling.average, nodata=-9999)
    for s_ in srcs:
        s_.close()
    z = z[0].astype(float)
    z[(z == -9999) | (z == 0)] = np.nan
    return z, tr
