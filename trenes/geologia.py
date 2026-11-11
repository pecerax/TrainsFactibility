"""Unidades geológicas desde la API de Macrostrat (incluye el mapa 1:1M de Sernageomin)."""
import json
import time

import requests

from .config import CACHE, FUENTES

_CACHE = CACHE / "macrostrat.json"


def _cargar() -> dict:
    return json.loads(_CACHE.read_text()) if _CACHE.exists() else {}


def unidades(puntos: list[tuple[float, float]]) -> list[dict]:
    """Para cada (lon, lat) devuelve la unidad de mayor detalle disponible."""
    cache = _cargar()
    salida = []
    for lon, lat in puntos:
        clave = f"{lon:.4f},{lat:.4f}"
        if clave not in cache:
            for intento in range(3):
                try:
                    r = requests.get(FUENTES["geologia_api"], params={"lat": lat, "lng": lon}, timeout=60)
                    r.raise_for_status()
                    cache[clave] = r.json()["success"]["data"]
                    break
                except Exception:
                    time.sleep(2 * (intento + 1))
            else:
                cache[clave] = []
            time.sleep(0.15)
        datos = cache[clave]
        # Preferir escala más detallada: large > medium > small > tiny
        orden = {"large": 0, "medium": 1, "small": 2, "tiny": 3}
        datos = sorted(datos, key=lambda d: orden.get(d.get("scale"), 9))
        if datos:
            d = datos[0]
            salida.append({
                "nombre": d.get("name") or "",
                "litologia": d.get("lith") or "",
                "edad": d.get("best_int_name") or "",
                "edad_ma": d.get("b_age"),
                "color": d.get("color") or "#cccccc",
                "escala": d.get("scale"),
                "fuente_id": d.get("source_id"),
            })
        else:
            salida.append({"nombre": "Sin dato", "litologia": "", "edad": "", "edad_ma": None,
                           "color": "#cccccc", "escala": None, "fuente_id": None})
    _CACHE.write_text(json.dumps(cache))
    return salida


def es_suelo_blando(u: dict) -> bool:
    """Depósitos cuaternarios no consolidados: riesgo de licuefacción, asentamientos y aluviones."""
    texto = f"{u['nombre']} {u['litologia']}".lower()
    cuaternario = (u.get("edad_ma") or 99) <= 2.6 or "quaternary" in texto or "cuaternario" in texto
    sedimento = any(p in texto for p in ["unconsolidated", "alluv", "sand", "gravel", "siliciclastic",
                                          "sediment", "aluvi", "fluvial", "eolian", "colluv"])
    return cuaternario and sedimento


def es_volcanica(u: dict) -> bool:
    texto = f"{u['nombre']} {u['litologia']}".lower()
    return any(p in texto for p in ["volcan", "andesit", "basalt", "ignimbr", "pyroclast", "tuff", "lava"])
