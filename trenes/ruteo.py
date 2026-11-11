"""Corredor de menor costo sobre el DEM entre puntos de paso.

El costo de cada celda crece con la pendiente del terreno: una vía férrea tolera
pendientes de 1,5-2,5 %, así que el algoritmo prefiere valles, terrazas y cuestas suaves.
Es una herramienta de exploración de corredores, no un diseño geométrico.
"""
import numpy as np
from pyproj import Geod
from skimage.graph import MCP_Geometric

from . import dem

GEOD = Geod(ellps="WGS84")


def costo_por_pendiente(z: np.ndarray, paso_m: float, pendiente_ref: float = 0.025) -> np.ndarray:
    gy, gx = np.gradient(np.nan_to_num(z, nan=0.0), paso_m)
    pend = np.hypot(gx, gy)
    # 1 en terreno plano; ~5 a 2x la pendiente de referencia; crece rápido en laderas
    c = 1.0 + (pend / pendiente_ref) ** 2
    c[np.isnan(z)] = 1e4  # mar
    return c


def corredor(puntos: list[tuple[float, float]], margen: float = 0.3, factor: int = 2) -> list[tuple[float, float]]:
    """Une los puntos (lon, lat) en orden con el camino de menor costo. Devuelve coordenadas."""
    salida = []
    for (lo1, la1), (lo2, la2) in zip(puntos[:-1], puntos[1:]):
        caja = (min(lo1, lo2) - margen, min(la1, la2) - margen, max(lo1, lo2) + margen, max(la1, la2) + margen)
        z, tr = dem.mosaico(*caja, factor=factor)
        lat_c = (la1 + la2) / 2
        paso_m = abs(tr.a) * 111_320 * np.cos(np.radians(lat_c))  # aprox. (celdas casi cuadradas en m)
        costo = costo_por_pendiente(z, paso_m)
        inv = ~tr
        def celda(lo, la):
            c, f = inv * (lo, la)
            return int(min(max(f, 0), z.shape[0] - 1)), int(min(max(c, 0), z.shape[1] - 1))
        ini, fin = celda(lo1, la1), celda(lo2, la2)
        costo[ini] = costo[fin] = 1.0  # extremos en la costa pueden caer en "mar"
        mcp = MCP_Geometric(costo, fully_connected=True)
        mcp.find_costs([ini], [fin])
        camino = mcp.traceback(fin)
        coords = [tr * (c + 0.5, f + 0.5) for f, c in camino]
        coords[0], coords[-1] = (lo1, la1), (lo2, la2)
        salida += coords if not salida else coords[1:]
    return suavizar(salida)


def suavizar(coords, ventana: int = 9):
    """Promedio móvil para quitar el zigzag de la grilla (mantiene los extremos)."""
    a = np.array(coords)
    if len(a) <= ventana:
        return [tuple(p) for p in a]
    k = np.ones(ventana) / ventana
    lon = np.convolve(np.pad(a[:, 0], ventana // 2, mode="edge"), k, mode="valid")
    lat = np.convolve(np.pad(a[:, 1], ventana // 2, mode="edge"), k, mode="valid")
    lon[0], lat[0], lon[-1], lat[-1] = a[0, 0], a[0, 1], a[-1, 0], a[-1, 1]
    return list(zip(lon.round(5), lat.round(5)))
