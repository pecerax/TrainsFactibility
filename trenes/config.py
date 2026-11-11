"""Rutas y parámetros comunes."""
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "data" / "cache"
PROCESADO = RAIZ / "data" / "procesado"
REPORTES = RAIZ / "reportes"
MAPA = RAIZ / "mapa"

# Chile continental (lon_min, lat_min, lon_max, lat_max), con margen
BBOX_CHILE = (-76.0, -56.5, -66.0, -17.3)

# CRS métrico para Chile continental (UTM 19S cubre la mayor parte del país)
CRS_METRICO = "EPSG:32719"

FUENTES = {
    "rios": "https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_sa_shp.zip",
    "cuencas": "https://data.hydrosheds.org/file/HydroBASINS/standard/hybas_sa_lev06_v1c.zip",
    "fallas": "https://raw.githubusercontent.com/GEMScienceTools/gem-global-active-faults/master/geojson/gem_active_faults_harmonized.geojson",
    "dem30": "https://copernicus-dem-30m.s3.amazonaws.com/{n}/{n}.tif",
    "geologia_api": "https://macrostrat.org/api/v2/geologic_units/map",
}
