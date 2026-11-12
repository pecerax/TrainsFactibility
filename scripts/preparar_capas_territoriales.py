"""Descarga capas territoriales: áreas protegidas, red ferroviaria, áreas urbanas y población.

Uso:  python scripts/preparar_capas_territoriales.py

Fuentes:
  - SNASPE y otras áreas protegidas: servidor SIT del MOP (MAPA_BASE/SNASPE).
  - Red ferroviaria: IGM 1:50.000 vía SIT MOP (MAPA_BASE/IGM50, capa Viario, tipos ferrocarril).
  - Cascos urbanos: SIT MOP (MAPA_BASE/ASENTAMIENTOS, capa de mayor detalle).
  - Población 2025: GHSL GHS-POP R2023A, 30 arcsec (~1 km), Comisión Europea (JRC).
  - Áreas de Desarrollo Indígena: vienen en la misma capa del SNASPE del MOP (tipo ADI).
"""
import sys
import zipfile
from pathlib import Path

import numpy as np
import rasterio
import requests
from rasterio.merge import merge

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from trenes import arcgis  # noqa: E402
from trenes.config import BBOX_CHILE, CACHE, PROCESADO  # noqa: E402

MOP = "https://rest-sit.mop.gob.cl/arcgis/rest/services/MAPA_BASE"
GHSL = ("https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/"
        "GHS_POP_E2025_GLOBE_R2023A_4326_30ss/V1-0/tiles/")

TIPOS_FFCC = {"6": "Desmantelado, trocha angosta", "7": "Operativo, trocha angosta, 1 vía",
              "17": "Operativo, trocha angosta, 2 vías", "8": "Operativo, trocha ancha, 1 vía",
              "18": "Operativo, trocha ancha, 2 vías", "13": "Puente ferroviario", "16": "Túnel ferroviario"}
NOMBRE_SNASPE = {"PN": "Parque Nacional", "RN": "Reserva Nacional", "MN": "Monumento Natural",
                 "SN": "Santuario de la Naturaleza", "BNP": "Bien Nacional Protegido",
                 "ACU": "Acuífero protegido", "RM": "Reserva Marina", "AMCP-MU": "Área Marina Costera Protegida",
                 "PM": "Parque Marino", "HUM": "Humedal urbano", "RAMSAR": "Sitio Ramsar"}


def guardar(gdf, nombre, precision=4):
    ruta = PROCESADO / f"{nombre}.geojson"
    gdf.to_file(ruta, driver="GeoJSON", COORDINATE_PRECISION=precision)
    print(f"{nombre}: {len(gdf)} elementos, {ruta.stat().st_size / 1e6:.1f} MB")


def areas_protegidas():
    g = arcgis.descargar(f"{MOP}/SNASPE/MapServer/0", campos="TIPO,NOMBRE,CAT_IUCN,SUP_HA,MARINO",
                         simplificar_grados=0.003)
    g = g[g.geometry.notna() & ~g.geometry.is_empty]
    g = g[g.MARINO.fillna("No").str.lower().ne("si") & g.MARINO.fillna("No").str.lower().ne("sí")]
    g["tipo_nombre"] = g.TIPO.map(NOMBRE_SNASPE).fillna(g.TIPO)
    g["geometry"] = g.geometry.buffer(0)
    g = g[["TIPO", "tipo_nombre", "NOMBRE", "CAT_IUCN", "SUP_HA", "geometry"]]
    # Las Áreas de Desarrollo Indígena vienen en la misma capa: se separan
    guardar(g[g.TIPO == "ADI"], "areas_desarrollo_indigena")
    guardar(g[g.TIPO != "ADI"], "areas_protegidas")


def red_ferroviaria():
    where = "TIPO IN (" + ",".join(f"'{t}'" for t in TIPOS_FFCC) + ")"
    g = arcgis.descargar(f"{MOP}/IGM50/MapServer/17", where=where, campos="TIPO", simplificar_grados=0.0005)
    g["tipo_nombre"] = g.TIPO.map(TIPOS_FFCC)
    g["operativa"] = ~g.TIPO.isin(["6"])
    guardar(g[["TIPO", "tipo_nombre", "operativa", "geometry"]], "red_ferroviaria", 5)


def areas_urbanas():
    g = arcgis.descargar(f"{MOP}/ASENTAMIENTOS/MapServer/21", campos="NOMBRE,NOM_REG", simplificar_grados=0.0008)
    g["geometry"] = g.geometry.buffer(0)
    guardar(g[["NOMBRE", "NOM_REG", "geometry"]], "areas_urbanas", 5)


def poblacion():
    carpeta = CACHE / "ghsl"
    carpeta.mkdir(parents=True, exist_ok=True)
    tifs = []
    for r in range(11, 16):          # filas de 10° entre 10°S y 60°S
        for c in (11, 12):           # columnas 80°O-70°O y 70°O-60°O
            nombre = f"GHS_POP_E2025_GLOBE_R2023A_4326_30ss_V1_0_R{r}_C{c}"
            z = carpeta / f"{nombre}.zip"
            if not z.exists():
                resp = requests.get(GHSL + z.name, timeout=600)
                if resp.status_code == 404:
                    continue
                resp.raise_for_status()
                z.write_bytes(resp.content)
            with zipfile.ZipFile(z) as zf:
                tif = [n for n in zf.namelist() if n.endswith(".tif")][0]
                zf.extract(tif, carpeta)
                tifs.append(carpeta / tif)
    srcs = [rasterio.open(t) for t in tifs]
    arr, tr = merge(srcs, bounds=BBOX_CHILE)
    perfil = srcs[0].profile | {"height": arr.shape[1], "width": arr.shape[2], "transform": tr,
                                "compress": "deflate", "dtype": "float32"}
    for s in srcs:
        s.close()
    a = arr[0].astype("float32")
    a[a < 0] = 0
    with rasterio.open(CACHE / "poblacion_2025_1km.tif", "w", **perfil) as dst:
        dst.write(a, 1)
    print(f"poblacion: grilla {a.shape}, total en la caja {a.sum() / 1e6:.1f} millones")


if __name__ == "__main__":
    PROCESADO.mkdir(parents=True, exist_ok=True)
    pasos = sys.argv[1:] or ["areas_protegidas", "red_ferroviaria", "areas_urbanas", "poblacion"]
    for p in pasos:
        globals()[p]()
