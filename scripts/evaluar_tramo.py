"""Evalúa un trazado (GeoJSON de LineStrings, una por subtramo) contra las capas base.

Uso:
    python scripts/evaluar_tramo.py tramos/santiago-antofagasta.geojson [--paso 200] [--res 90]

Para cada subtramo calcula:
  - longitud, perfil de terreno (Copernicus DEM) y pendientes del terreno
  - rasante con pendiente máxima de 1,5 % (carga) y 2,5 % (mixto/pasajeros):
    largo en túnel, viaducto y movimiento de tierras
  - cruces de cauces (HydroRIVERS) con su cuenca aportante y caudal medio
  - unidades geológicas atravesadas (Macrostrat) y largo sobre suelos blandos / volcánicos
  - cruces y cercanía a fallas activas (GEM)
Escribe en reportes/<nombre>/: un perfil PNG por subtramo, resumen.md, resumen.json
y trazado_evaluado.geojson (para el mapa).
"""
import argparse
import json
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from shapely.geometry import LineString, mapping  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from trenes import dem, geologia, rasante  # noqa: E402
from trenes.config import CACHE, CRS_METRICO, PROCESADO, REPORTES  # noqa: E402

PENDIENTES = {"carga_1.5": 0.015, "mixto_2.5": 0.025}
PASO_GEOLOGIA_M = 5000
UPLAND_MIN_KM2 = 10  # cauces menores se ignoran


def densificar(linea_m: LineString, paso: float) -> np.ndarray:
    dists = np.r_[np.arange(0, linea_m.length, paso), linea_m.length]
    return dists


def tramos_continuos(s, mascara):
    """Lista de (inicio_m, fin_m) donde mascara es True."""
    out, ini = [], None
    for i, m in enumerate(mascara):
        if m and ini is None:
            ini = s[i]
        if not m and ini is not None:
            out.append((ini, s[i]))
            ini = None
    if ini is not None:
        out.append((ini, s[-1]))
    return out


def evaluar_subtramo(feat, rios, fallas, paso, res, carpeta):
    props = feat["properties"]
    nombre = props.get("nombre", props.get("id"))
    geo = gpd.GeoSeries([LineString(feat["geometry"]["coordinates"])], crs="EPSG:4326")
    linea_m = geo.to_crs(CRS_METRICO).iloc[0]
    s = densificar(linea_m, paso)
    pts_m = gpd.GeoSeries([linea_m.interpolate(d) for d in s], crs=CRS_METRICO)
    pts = pts_m.to_crs("EPSG:4326")
    lons, lats = pts.x.values, pts.y.values
    z = dem.elevaciones(lons, lats, res)
    if np.isnan(z).any():  # puntos sobre el mar o sin dato: interpolar
        ok = ~np.isnan(z)
        z = np.interp(s, s[ok], z[ok])

    pend_terreno = np.abs(np.gradient(z, s))
    r = {"id": props.get("id"), "nombre": nombre, "largo_km": linea_m.length / 1000,
         "cota_min": float(z.min()), "cota_max": float(z.max()),
         "subida_acum_m": float(np.clip(np.diff(z), 0, None).sum()),
         "bajada_acum_m": float(-np.clip(np.diff(z), None, 0).sum()),
         "terreno_pct_sobre_2_5": float((pend_terreno > 0.025).mean() * 100)}

    rasantes, clases = {}, {}
    for clave, pmax in PENDIENTES.items():
        g = rasante.rasante(s, z, pmax)
        c = rasante.clasificar(z, g)
        lon = rasante.longitudes_por_clase(s, c)
        rasantes[clave], clases[clave] = g, c
        r[clave] = {"tunel_km": lon["tunel"] / 1000, "viaducto_km": lon["viaducto"] / 1000,
                    "tierra_km": lon["tierra"] / 1000,
                    "corte_terraplen_medio_m": float(np.abs(z - g)[c == "tierra"].mean()),
                    "tuneles": [(a / 1000, b / 1000) for a, b in tramos_continuos(s, c == "tunel")],
                    "viaductos": [(a / 1000, b / 1000) for a, b in tramos_continuos(s, c == "viaducto")]}

    # Cruces de cauces
    cruces = []
    rios_cerca = rios[rios.intersects(linea_m.buffer(100))]
    for _, rio in rios_cerca.iterrows():
        inter = linea_m.intersection(rio.geometry)
        if inter.is_empty:
            continue
        geoms = getattr(inter, "geoms", [inter])
        for gpt in geoms:
            km = linea_m.project(gpt.centroid) / 1000
            cruces.append({"km": round(km, 1), "cuenca_km2": float(rio.UPLAND_SKM),
                           "caudal_medio_m3s": float(rio.DIS_AV_CMS), "orden": int(rio.ORD_STRA)})
    # Un mismo cauce cortado varias veces en pocos km (meandros, eje paralelo al río) cuenta una vez
    cruces.sort(key=lambda c: c["km"])
    unicos = []
    for c in cruces:
        if unicos and c["km"] - unicos[-1]["km"] < 3 and \
                abs(c["cuenca_km2"] - unicos[-1]["cuenca_km2"]) <= 0.2 * unicos[-1]["cuenca_km2"]:
            continue
        unicos.append(c)
    cruces = unicos
    r["cruces_cauces"] = cruces
    r["n_cruces_mayores"] = sum(c["cuenca_km2"] >= 1000 for c in cruces)

    # Geología
    s_geo = np.r_[np.arange(0, linea_m.length, PASO_GEOLOGIA_M), linea_m.length]
    pts_geo = gpd.GeoSeries([linea_m.interpolate(d) for d in s_geo], crs=CRS_METRICO).to_crs("EPSG:4326")
    unidades = geologia.unidades(list(zip(pts_geo.x, pts_geo.y)))
    segmentos_geo, actual = [], None
    for d, u in zip(s_geo, unidades):
        clave_u = (u["nombre"], u["edad"])
        if actual is None or actual["clave"] != clave_u:
            actual = {"clave": clave_u, "desde_km": d / 1000, "hasta_km": d / 1000, **u}
            segmentos_geo.append(actual)
        actual["hasta_km"] = d / 1000
    for i in range(len(segmentos_geo) - 1):
        segmentos_geo[i]["hasta_km"] = segmentos_geo[i + 1]["desde_km"]
    segmentos_geo[-1]["hasta_km"] = linea_m.length / 1000
    paso_geo_km = PASO_GEOLOGIA_M / 1000
    r["suelo_blando_km"] = sum(geologia.es_suelo_blando(u) for u in unidades) * paso_geo_km
    r["volcanico_km"] = sum(geologia.es_volcanica(u) for u in unidades) * paso_geo_km
    r["geologia"] = [{k: v for k, v in sg.items() if k != "clave"} for sg in segmentos_geo]

    # Fallas activas
    fallas_m = fallas
    cruces_f, cercanas = [], []
    for _, f in fallas_m.iterrows():
        dist = linea_m.distance(f.geometry)
        if dist < 10000:
            info = {"nombre": f.get("name") or "sin nombre", "tipo": f.get("slip_type") or "",
                    "dist_km": round(dist / 1000, 1),
                    "km": round(linea_m.project(f.geometry.centroid) / 1000, 1)}
            (cruces_f if linea_m.intersects(f.geometry) else cercanas).append(info)
    r["fallas_cruzadas"] = cruces_f
    r["fallas_a_menos_de_10km"] = cercanas

    graficar(s, z, rasantes, clases, cruces, segmentos_geo, cruces_f, nombre, carpeta / f"perfil_{props.get('id')}.png")

    # Geometría clasificada para el mapa (con la rasante de 2,5 %)
    feats = []
    c25 = clases["mixto_2.5"]
    cambios = [0] + [i for i in range(1, len(c25)) if c25[i] != c25[i - 1]] + [len(c25) - 1]
    for a, b in zip(cambios[:-1], cambios[1:]):
        if b <= a:
            continue
        coords = list(zip(lons[a:b + 1], lats[a:b + 1]))
        feats.append({"type": "Feature", "geometry": mapping(LineString(coords)),
                      "properties": {"subtramo": nombre, "clase": c25[a],
                                     "desde_km": round(s[a] / 1000, 1), "hasta_km": round(s[b] / 1000, 1)}})
    return r, feats


COLORES = {"tunel": "#c0392b", "viaducto": "#8e44ad", "tierra": "#2c3e50"}


def graficar(s, z, rasantes, clases, cruces, geo, fallas, nombre, ruta):
    km = s / 1000
    fig, (ax, axg) = plt.subplots(2, 1, figsize=(13, 5.6), sharex=True,
                                  gridspec_kw={"height_ratios": [6, 0.6], "hspace": 0.05})
    ax.fill_between(km, z, z.min() - 50, color="#d9cbb3", lw=0)
    ax.plot(km, z, color="#7a6a4f", lw=0.8, label="Terreno (Copernicus DEM)")
    ax.plot(km, rasantes["carga_1.5"], color="#2980b9", lw=1.2, ls="--", label="Rasante 1,5 % (carga)")
    g = rasantes["mixto_2.5"]
    c = clases["mixto_2.5"]
    for clase, col in COLORES.items():
        gg = np.where(c == clase, g, np.nan)
        ax.plot(km, gg, color=col, lw=2.0,
                label={"tierra": "Rasante 2,5 %: corte/terraplén", "tunel": "Rasante 2,5 %: túnel",
                       "viaducto": "Rasante 2,5 %: viaducto"}[clase])
    for cr in cruces:
        if cr["cuenca_km2"] >= 1000:
            ax.axvline(cr["km"], color="#3498db", lw=0.8, alpha=0.6)
    for f in fallas:
        ax.axvline(f["km"], color="#e67e22", lw=1.2, ls=":")
    ax.set_ylabel("Cota (m s.n.m.)")
    ax.set_title(f"{nombre}: perfil longitudinal", loc="left", fontsize=12, fontweight="bold")
    ax.legend(loc="upper left", fontsize=8, ncol=2, frameon=False)
    ax.grid(alpha=0.25)
    ax.text(0.995, 0.02, "Líneas azules: ríos con cuenca > 1.000 km²   Punteado naranjo: falla activa",
            transform=ax.transAxes, ha="right", fontsize=7.5, color="#555")
    for sg in geo:
        axg.axvspan(sg["desde_km"], sg["hasta_km"], color=sg["color"], lw=0)
    axg.set_yticks([])
    axg.set_ylabel("Geol.", rotation=0, ha="right", va="center", fontsize=8)
    axg.set_xlabel("Distancia (km)")
    axg.set_xlim(km[0], km[-1])
    fig.savefig(ruta, dpi=130, bbox_inches="tight")
    plt.close(fig)


def escribir_md(nombre_trazado, descripcion, resultados, carpeta):
    L = [f"# Evaluación preliminar: {nombre_trazado}", "", descripcion, "",
         "Resultados de nivel perfil (idea). Rasante calculada sobre el eje propuesto sin optimizar el trazado en planta; "
         "las longitudes de túnel y viaducto indican dónde el eje actual choca con el relieve, no un diseño.", "",
         "## Resumen por subtramo", "",
         "| Subtramo | Largo (km) | Cota mín–máx (m) | Subida acum. (m) | Túnel 2,5 % (km) | Viaducto 2,5 % (km) | Túnel 1,5 % (km) | Cruces cuenca >1.000 km² | Suelo blando (km) | Fallas cruzadas |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    tot = {"largo": 0, "t25": 0, "v25": 0, "t15": 0}
    for r in resultados:
        L.append(f"| {r['nombre']} | {r['largo_km']:.0f} | {r['cota_min']:.0f}–{r['cota_max']:.0f} | {r['subida_acum_m']:.0f} | "
                 f"{r['mixto_2.5']['tunel_km']:.1f} | {r['mixto_2.5']['viaducto_km']:.1f} | {r['carga_1.5']['tunel_km']:.1f} | "
                 f"{r['n_cruces_mayores']} | {r['suelo_blando_km']:.0f} | {len(r['fallas_cruzadas'])} |")
        tot["largo"] += r["largo_km"]
        tot["t25"] += r["mixto_2.5"]["tunel_km"]
        tot["v25"] += r["mixto_2.5"]["viaducto_km"]
        tot["t15"] += r["carga_1.5"]["tunel_km"]
    L.append(f"| **Total** | **{tot['largo']:.0f}** | | | **{tot['t25']:.1f}** | **{tot['v25']:.1f}** | **{tot['t15']:.1f}** | | | |")
    L.append("")
    for r in resultados:
        L += [f"## {r['nombre']}", "", f"![perfil](perfil_{r['id']}.png)", ""]
        L.append(f"- Largo {r['largo_km']:.0f} km; cota entre {r['cota_min']:.0f} y {r['cota_max']:.0f} m; "
                 f"{r['terreno_pct_sobre_2_5']:.0f} % del eje sobre terreno con pendiente > 2,5 %.")
        for clave, txt in (("mixto_2.5", "Rasante 2,5 %"), ("carga_1.5", "Rasante 1,5 %")):
            d = r[clave]
            tun = ", ".join(f"km {a:.0f}–{b:.0f}" for a, b in d["tuneles"] if b - a >= 0.4) or "ninguno"
            via = ", ".join(f"km {a:.0f}–{b:.0f}" for a, b in d["viaductos"] if b - a >= 0.4) or "ninguno"
            L.append(f"- {txt}: túnel {d['tunel_km']:.1f} km ({tun}); viaducto {d['viaducto_km']:.1f} km ({via}); "
                     f"corte/terraplén medio {d['corte_terraplen_medio_m']:.1f} m.")
        mayores = [c for c in r["cruces_cauces"] if c["cuenca_km2"] >= 1000]
        if mayores:
            L.append("- Cruces de ríos mayores: " + "; ".join(
                f"km {c['km']:.0f} (cuenca {c['cuenca_km2']:,.0f} km², caudal medio {c['caudal_medio_m3s']:.1f} m³/s)".replace(",", ".")
                for c in mayores) + ".")
        n_menores = len(r["cruces_cauces"]) - len(mayores)
        L.append(f"- Otros {n_menores} cruces de quebradas o esteros con cuenca entre {UPLAND_MIN_KM2} y 1.000 km² "
                 "(alcantarillas o puentes menores; en el norte, riesgo de aluvión).")
        L.append(f"- Geología: {r['suelo_blando_km']:.0f} km sobre depósitos cuaternarios no consolidados y "
                 f"{r['volcanico_km']:.0f} km sobre rocas volcánicas. Unidades atravesadas:")
        for g in r["geologia"]:
            L.append(f"    - km {g['desde_km']:.0f}–{g['hasta_km']:.0f}: {g['nombre']} ({g['edad']}; {g['litologia']})")
        if r["fallas_cruzadas"]:
            L.append("- Fallas activas cruzadas: " + "; ".join(
                f"{f['nombre']} ({f['tipo']}) cerca del km {f['km']:.0f}" for f in r["fallas_cruzadas"]) + ".")
        if r["fallas_a_menos_de_10km"]:
            L.append("- Fallas activas a menos de 10 km: " + "; ".join(
                f"{f['nombre']} a {f['dist_km']} km" for f in r["fallas_a_menos_de_10km"]) + ".")
        L.append("")
    L += ["## Fuentes", "",
          "- Elevación: Copernicus DEM GLO-90 (ESA), vía AWS Open Data.",
          "- Cauces: HydroRIVERS v1.0 (WWF/HydroSHEDS). Cuencas: HydroBASINS nivel 6.",
          "- Geología: Macrostrat (API v2), que compila mapas regionales incluido el Mapa Geológico de Chile 1:1.000.000 (Sernageomin).",
          "- Fallas activas: GEM Global Active Faults Database.", ""]
    (carpeta / "resumen.md").write_text("\n".join(L), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trazado")
    ap.add_argument("--paso", type=float, default=200, help="separación de puntos del perfil (m)")
    ap.add_argument("--res", type=int, default=90, choices=[30, 90], help="resolución del DEM (m)")
    a = ap.parse_args()

    ruta = Path(a.trazado)
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    carpeta = REPORTES / ruta.stem
    carpeta.mkdir(parents=True, exist_ok=True)

    rios = gpd.read_file(CACHE / "rios_chile.gpkg")
    rios = rios[rios.UPLAND_SKM >= UPLAND_MIN_KM2].to_crs(CRS_METRICO)
    fallas = gpd.read_file(PROCESADO / "fallas_chile.geojson").to_crs(CRS_METRICO)

    resultados, feats = [], []
    for feat in datos["features"]:
        print(f"Evaluando {feat['properties'].get('nombre')} ...", flush=True)
        r, f = evaluar_subtramo(feat, rios, fallas, a.paso, a.res, carpeta)
        resultados.append(r)
        feats += f

    (carpeta / "resumen.json").write_text(json.dumps(resultados, ensure_ascii=False, indent=1), encoding="utf-8")
    (carpeta / "trazado_evaluado.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": feats}), encoding="utf-8")
    escribir_md(datos.get("name", ruta.stem), datos.get("description", ""), resultados, carpeta)
    print(f"Listo: {carpeta}")


if __name__ == "__main__":
    main()
