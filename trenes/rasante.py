"""Rasante (perfil longitudinal de diseño) con pendiente máxima.

Se busca la rasante g(s) más cercana al terreno z(s) (mínimos cuadrados) sujeta a
|dg/ds| <= pendiente máxima. Es un problema cuadrático disperso que resuelve OSQP.

Luego se clasifica cada punto según la diferencia terreno - rasante:
  > UMBRAL_TUNEL m      -> túnel
  < -UMBRAL_VIADUCTO m  -> viaducto
  resto                 -> movimiento de tierras (corte o terraplén)
Es una aproximación de nivel perfil: no considera curvas horizontales ni geometría vertical fina.
"""
import numpy as np
import osqp
import scipy.sparse as sp

UMBRAL_TUNEL = 30.0
UMBRAL_VIADUCTO = 20.0


def rasante(s: np.ndarray, z: np.ndarray, pendiente_max: float) -> np.ndarray:
    """s: distancia acumulada (m); z: terreno (m); pendiente_max: p.ej. 0.025 para 2,5 %.

    min 1/2 ||g - z||^2  s.a.  |g[i+1] - g[i]| <= pendiente_max * ds[i]
    """
    n = len(s)
    ds = np.diff(s)
    D = sp.diags([-np.ones(n - 1), np.ones(n - 1)], [0, 1], shape=(n - 1, n), format="csc")
    lim = pendiente_max * ds
    m = osqp.OSQP()
    m.setup(P=sp.identity(n, format="csc"), q=-z, A=D, l=-lim, u=lim,
            verbose=False, eps_abs=1e-4, eps_rel=1e-6, max_iter=200000, polish=True)
    g = m.solve().x
    # Pequeña corrección por tolerancia numérica: recorta pendientes excedidas
    for i in range(n - 1):
        g[i + 1] = np.clip(g[i + 1], g[i] - lim[i], g[i] + lim[i])
    return g


def clasificar(z: np.ndarray, g: np.ndarray) -> np.ndarray:
    dif = z - g
    clase = np.full(len(z), "tierra", dtype=object)
    clase[dif > UMBRAL_TUNEL] = "tunel"
    clase[dif < -UMBRAL_VIADUCTO] = "viaducto"
    return clase


def longitudes_por_clase(s: np.ndarray, clase: np.ndarray) -> dict:
    ds = np.r_[np.diff(s), 0.0]
    return {c: float(ds[clase == c].sum()) for c in ("tierra", "tunel", "viaducto")}
