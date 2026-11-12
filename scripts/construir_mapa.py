"""Construye mapa/index.html: mapa interactivo (Leaflet) con capas base y trazados evaluados.

Uso:  python scripts/construir_mapa.py
Lee data/procesado/*.geojson, reportes/*/trazado_evaluado.geojson y web/ (plantilla y motor de
trazado) y los incrusta en un único
HTML que se abre directamente en el navegador (no necesita servidor).
"""
import base64
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from trenes import grilla, teselas  # noqa: E402
from trenes.config import BBOX_CHILE, MAPA, PROCESADO, RAIZ, REPORTES  # noqa: E402


def a_data_uri(img, calidad=78):
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=calidad, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def cargar(ruta: Path):
    return json.loads(ruta.read_text(encoding="utf-8"))


def main():
    capas = {
        "rios": cargar(PROCESADO / "rios_mapa.geojson"),
        "cuencas": cargar(PROCESADO / "cuencas_chile.geojson"),
        "fallas": cargar(PROCESADO / "fallas_chile.geojson"),
    }
    trazados = {}
    for carpeta in sorted(REPORTES.iterdir()):
        f = carpeta / "trazado_evaluado.geojson"
        if f.exists():
            resumen = cargar(carpeta / "resumen.json")
            trazados[carpeta.name] = {"geo": cargar(f), "resumen": [
                {"nombre": r["nombre"], "largo_km": round(r["largo_km"]),
                 "tunel_km": round(r["mixto_2.5"]["tunel_km"], 1),
                 "viaducto_km": round(r["mixto_2.5"]["viaducto_km"], 1),
                 "cruces": r["n_cruces_mayores"]} for r in resumen]}
    paradas = []
    for f in (RAIZ / "tramos").glob("*_paradas.json"):
        for st in cargar(f)["subtramos"]:
            for nombre, lon, lat in st["puntos"]:
                paradas.append({"nombre": nombre, "lon": lon, "lat": lat})
    paradas = list({p["nombre"]: p for p in paradas}.values())

    print("Generando relieve y geología ...", flush=True)
    rel, b_rel = teselas.relieve(BBOX_CHILE)
    geo, b_geo = teselas.geologia(BBOX_CHILE)
    rasters = {"relieve": {"src": a_data_uri(rel), "bounds": b_rel},
               "geologia": {"src": a_data_uri(geo, 70), "bounds": b_geo}}

    print("Generando grilla de elevación para el trazado interactivo ...", flush=True)
    bbox_dem = (-75.8, -56.0, -66.4, -17.4)
    g, (lon0, lat0, paso) = grilla.grilla(bbox_dem)
    dem_uri, _ = grilla.a_png_uri(g)
    dem = {"src": dem_uri, "meta": {"lon0": lon0, "lat0": lat0, "paso": paso}}

    datos = json.dumps({"dem": dem, "rasters": rasters, "capas": capas, "trazados": trazados, "paradas": paradas}, ensure_ascii=False,
                       separators=(",", ":"))
    plantilla = (WEB / "plantilla.html").read_text(encoding="utf-8")
    css = (WEB / "leaflet-1.9.4.css").read_text(encoding="utf-8")
    cuerpo = (plantilla.replace("__LEAFLET_CSS__", "<style>\n" + css + "\n</style>")
              .replace("__MOTOR__", (WEB / "motor.js").read_text(encoding="utf-8"))
              .replace("__DATOS__", datos))
    html = ('<!doctype html>\n<html lang="es">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            + cuerpo + "\n</html>\n")
    MAPA.mkdir(exist_ok=True)
    (MAPA / "index.html").write_text(html, encoding="utf-8")
    print(f"Listo: {MAPA / 'index.html'} ({len(html) / 1e6:.1f} MB)")


WEB = RAIZ / "web"


if __name__ == "__main__":
    main()
