"""Genera un trazado de menor costo a partir de un archivo de paradas.

Uso:  python scripts/trazar_corredor.py tramos/santiago-antofagasta_paradas.json
Escribe tramos/<name>.geojson, listo para scripts/evaluar_tramo.py.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from trenes import ruteo  # noqa: E402

ruta = Path(sys.argv[1])
datos = json.loads(ruta.read_text(encoding="utf-8"))
feats = []
for st in datos["subtramos"]:
    print(f"Trazando {st['nombre']} ...", flush=True)
    coords = ruteo.corredor([(p[1], p[2]) for p in st["puntos"]])
    feats.append({"type": "Feature",
                  "properties": {"id": st["id"], "nombre": st["nombre"],
                                 "paradas": [p[0] for p in st["puntos"]]},
                  "geometry": {"type": "LineString", "coordinates": [list(c) for c in coords]}})
salida = ruta.parent / f"{datos['name']}.geojson"
salida.write_text(json.dumps({"type": "FeatureCollection", "name": datos["name"],
                              "description": datos["description"], "features": feats},
                             ensure_ascii=False), encoding="utf-8")
print(f"Listo: {salida}")
