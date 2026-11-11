"""Descarga y recorta a Chile las capas base: ríos, cuencas y fallas activas.

Uso:  python scripts/preparar_capas.py
Deja en data/procesado/ archivos GeoJSON livianos para el mapa y la evaluación.
"""
import sys
import zipfile
from pathlib import Path

import geopandas as gpd
import requests
from shapely.geometry import box

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from trenes.config import BBOX_CHILE, CACHE, FUENTES, PROCESADO  # noqa: E402


def descargar(url: str, destino: Path) -> Path:
    if destino.exists() and destino.stat().st_size > 0:
        return destino
    print(f"Descargando {url}")
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(destino, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    return destino


def leer_zip(zip_path: Path) -> gpd.GeoDataFrame:
    """Extrae el shapefile y lo lee recortado a Chile.

    Se descartan los índices espaciales .sbn/.sbx de ESRI, que GDAL no siempre lee.
    """
    destino = zip_path.with_suffix("")
    if not destino.exists():
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(destino)
    for idx in list(destino.rglob("*.sbn")) + list(destino.rglob("*.sbx")):
        idx.unlink()
    shp = next(destino.rglob("*.shp"))
    return gpd.read_file(shp, bbox=BBOX_CHILE)


def main() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    PROCESADO.mkdir(parents=True, exist_ok=True)
    marco = box(*BBOX_CHILE)

    # Ríos (HydroRIVERS). Se guardan dos versiones:
    #  - data/cache/rios_chile.gpkg: completo, para detectar cruces en la evaluación
    #  - rios_mapa.geojson: solo cauces con cuenca aportante > 500 km2, para el mapa web
    rios = leer_zip(descargar(FUENTES["rios"], CACHE / "HydroRIVERS_v10_sa_shp.zip"))
    rios = rios[rios.intersects(marco)]
    cols = ["HYRIV_ID", "ORD_STRA", "ORD_CLAS", "UPLAND_SKM", "DIS_AV_CMS", "LENGTH_KM", "geometry"]
    rios = rios[cols]
    rios.to_file(CACHE / "rios_chile.gpkg", driver="GPKG")  # completo, pesado: no se versiona
    mapa = rios[rios.UPLAND_SKM > 500].copy()
    mapa["geometry"] = mapa.simplify(0.003)
    mapa[["ORD_STRA", "UPLAND_SKM", "DIS_AV_CMS", "geometry"]].to_file(
        PROCESADO / "rios_mapa.geojson", driver="GeoJSON", COORDINATE_PRECISION=4)
    print(f"Ríos: {len(rios)} tramos ({len(mapa)} en el mapa)")

    # Cuencas nivel 6 (HydroBASINS)
    cuencas = leer_zip(descargar(FUENTES["cuencas"], CACHE / "hybas_sa_lev06.zip"))
    cuencas = cuencas[cuencas.intersects(marco)][["HYBAS_ID", "SUB_AREA", "UP_AREA", "geometry"]]
    cuencas["geometry"] = cuencas.simplify(0.005)
    cuencas.to_file(PROCESADO / "cuencas_chile.geojson", driver="GeoJSON", COORDINATE_PRECISION=4)
    print(f"Cuencas: {len(cuencas)}")

    # Fallas activas (GEM Global Active Faults)
    fallas = gpd.read_file(descargar(FUENTES["fallas"], CACHE / "gem_faults.geojson"))
    fallas = fallas[fallas.intersects(marco)]
    keep = [c for c in ["catalog_name", "name", "slip_type", "net_slip_rate", "geometry"] if c in fallas.columns]
    fallas[keep].to_file(PROCESADO / "fallas_chile.geojson", driver="GeoJSON", COORDINATE_PRECISION=5)
    print(f"Fallas: {len(fallas)}")


if __name__ == "__main__":
    main()
