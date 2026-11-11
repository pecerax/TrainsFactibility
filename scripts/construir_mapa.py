"""Construye mapa/index.html: mapa interactivo (Leaflet) con capas base y trazados evaluados.

Uso:  python scripts/construir_mapa.py
Lee data/procesado/*.geojson y reportes/*/trazado_evaluado.geojson y los incrusta en un único
HTML que se abre directamente en el navegador (no necesita servidor).
"""
import base64
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from trenes import teselas  # noqa: E402
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

    datos = json.dumps({"rasters": rasters, "capas": capas, "trazados": trazados, "paradas": paradas}, ensure_ascii=False,
                       separators=(",", ":"))
    cuerpo = PLANTILLA.replace("__DATOS__", datos)
    html = ('<!doctype html>\n<html lang="es">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            + cuerpo + "\n</html>\n")
    MAPA.mkdir(exist_ok=True)
    (MAPA / "index.html").write_text(html, encoding="utf-8")
    print(f"Listo: {MAPA / 'index.html'} ({len(html) / 1e6:.1f} MB)")


PLANTILLA = r"""<title>Atlas del Longitudinal</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<style>
  /* Layout: mapa a pantalla completa; ficha técnica flotante abajo a la izquierda, como el rótulo de un plano */
  :root {
    --bg: #eef0ec; --panel: #fbfcfa; --ink: #1f2a26; --muted: #5d6b65; --rule: #d5dcd7;
    --accent: #1d6f5f; --tunel: #b8402f; --viaducto: #7a4fa0; --tierra: #1f2a26;
    --rio: #2b77b0; --falla: #d9822b;
    --sans: "IBM Plex Sans", system-ui, sans-serif; --mono: "IBM Plex Mono", ui-monospace, monospace;
  }
  @media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
    --bg: #141a18; --panel: #1c2421; --ink: #e5ece8; --muted: #9aa8a2; --rule: #2e3a36;
    --accent: #5fbfa8; --tunel: #e2735f; --viaducto: #b48ad8; --tierra: #e5ece8; color-scheme: dark } }
  :root[data-theme="dark"] {
    --bg: #141a18; --panel: #1c2421; --ink: #e5ece8; --muted: #9aa8a2; --rule: #2e3a36;
    --accent: #5fbfa8; --tunel: #e2735f; --viaducto: #b48ad8; --tierra: #e5ece8; color-scheme: dark }
  html, body { height: 100%; }
  body { margin: 0; background: var(--bg); color: var(--ink); font: 14px/1.45 var(--sans); }
  #mapa { position: fixed; inset: 0; background: var(--bg); }
  .ficha { position: fixed; z-index: 1000;
    left: max(12px, env(safe-area-inset-left, 0px)); bottom: calc(12px + env(safe-area-inset-bottom, 0px));
    width: min(440px, calc(100% - 24px - env(safe-area-inset-left, 0px) - env(safe-area-inset-right, 0px)));
    max-height: 48vh; overflow: auto; background: var(--panel); border: 1px solid var(--rule); border-radius: 6px;
    padding: 12px 14px; box-shadow: 0 2px 10px rgba(0,0,0,.18); display: grid; gap: 8px; }
  .ficha h1 { margin: 0; font-size: 16px; font-weight: 600; text-wrap: balance; }
  .ficha .sub { margin: 0; color: var(--muted); font-size: 12px; }
  .fila { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  label { font-size: 12px; color: var(--muted); letter-spacing: .04em; text-transform: uppercase; }
  select { font: inherit; color: var(--ink); background: var(--bg); border: 1px solid var(--rule); border-radius: 4px; padding: 3px 6px; }
  select:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
  .tabla { overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; font: 12px/1.35 var(--mono); font-variant-numeric: tabular-nums; }
  th, td { padding: 3px 5px; text-align: right; border-bottom: 1px solid var(--rule); white-space: nowrap; }
  th { font-family: var(--sans); font-weight: 600; color: var(--muted); }
  th:first-child, td:first-child { text-align: left; font-family: var(--sans); white-space: normal; }
  tr.total td { font-weight: 500; border-bottom: 0; }
  .leyenda { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 12px; color: var(--muted); }
  .leyenda i { display: inline-block; width: 16px; height: 4px; border-radius: 2px; vertical-align: middle; margin-right: 5px; }
  .nota { font-size: 11px; color: var(--muted); margin: 0; }
  .leaflet-container { font: 13px/1.4 var(--sans); }
  .leaflet-control-layers, .leaflet-bar a, .leaflet-popup-content-wrapper, .leaflet-popup-tip { background: var(--panel); color: var(--ink); }
  .leaflet-control-layers { border: 1px solid var(--rule) !important; }
  .leaflet-control-attribution { background: color-mix(in srgb, var(--panel) 80%, transparent) !important; color: var(--muted); }
  .leaflet-control-attribution a { color: var(--accent); }
  .leaflet-top { top: env(safe-area-inset-top, 0px); }
  .leaflet-right { right: env(safe-area-inset-right, 0px); }
</style>
<div id="mapa" role="application" aria-label="Mapa de Chile con relieve, geología, ríos, fallas y trazados"></div>
<section class="ficha" aria-label="Trazados evaluados">
  <div>
    <h1>Trazados evaluados</h1>
    <p class="sub">Rasante con pendiente máxima 2,5 %. Largos en km.</p>
  </div>
  <div class="fila"><label for="sel">Trazado</label><select id="sel"></select></div>
  <div class="tabla" id="tabla"></div>
  <div class="leyenda">
    <span><i style="background:var(--tierra)"></i>corte/terraplén</span>
    <span><i style="background:var(--tunel)"></i>túnel</span>
    <span><i style="background:var(--viaducto)"></i>viaducto</span>
    <span><i style="background:var(--rio)"></i>ríos</span>
    <span><i style="background:var(--falla)"></i>fallas activas</span>
  </div>
  <p class="nota">Nivel idea: túnel y viaducto marcan dónde el eje choca con el relieve, no un diseño. Capas en el botón de arriba a la derecha.</p>
</section>
<script>
const D = __DATOS__;
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const mapa = L.map('mapa', { preferCanvas: true, zoomSnap: 0.5 }).setView([-28.6, -70.4], 6);
const relieve = L.imageOverlay(D.rasters.relieve.src, D.rasters.relieve.bounds, { attribution: 'Relieve: Mapzen Terrain Tiles (SRTM y otros)' }).addTo(mapa);
const geologia = L.imageOverlay(D.rasters.geologia.src, D.rasters.geologia.bounds, { opacity: 0.6, attribution: 'Geología: Macrostrat (incl. Sernageomin 1:1M)' });

const rios = L.geoJSON(D.capas.rios, {
  style: f => ({ color: css('--rio'), weight: Math.min(4, 0.5 + Math.log10(f.properties.UPLAND_SKM) / 1.6), opacity: 0.9 }),
  onEachFeature: (f, l) => l.bindPopup(`<b>Cauce</b><br>Cuenca aportante: ${Math.round(f.properties.UPLAND_SKM).toLocaleString('es-CL')} km²<br>Caudal medio: ${f.properties.DIS_AV_CMS.toFixed(1).replace('.', ',')} m³/s`)
});
const cuencas = L.geoJSON(D.capas.cuencas, { style: { color: css('--accent'), weight: 0.8, fill: false, opacity: 0.8 } });
const fallas = L.geoJSON(D.capas.fallas, {
  style: { color: css('--falla'), weight: 2.4 },
  onEachFeature: (f, l) => l.bindPopup(`<b>Falla activa</b><br>${f.properties.name || 'sin nombre'}<br>${f.properties.slip_type || ''}`)
});
const paradas = L.layerGroup(D.paradas.map(p => L.circleMarker([p.lat, p.lon], { radius: 5, color: css('--ink'), fillColor: css('--panel'), fillOpacity: 1, weight: 2 }).bindTooltip(p.nombre)));

const COL = { tierra: css('--tierra'), tunel: css('--tunel'), viaducto: css('--viaducto') };
const NOM = { tierra: 'corte/terraplén', tunel: 'túnel', viaducto: 'viaducto' };
const trazados = {};
for (const [k, t] of Object.entries(D.trazados)) {
  trazados[k] = L.geoJSON(t.geo, {
    style: f => ({ color: COL[f.properties.clase], weight: f.properties.clase === 'tierra' ? 3 : 5, opacity: 1 }),
    onEachFeature: (f, l) => l.bindPopup(`<b>${f.properties.subtramo}</b><br>${NOM[f.properties.clase]}: km ${f.properties.desde_km}–${f.properties.hasta_km}`)
  });
}
rios.addTo(mapa); fallas.addTo(mapa); paradas.addTo(mapa);
L.control.layers(null, { 'Relieve': relieve, 'Geología': geologia, 'Ríos (HydroRIVERS)': rios, 'Cuencas nivel 6': cuencas, 'Fallas activas (GEM)': fallas, 'Paradas': paradas }, { collapsed: true }).addTo(mapa);
L.control.scale({ imperial: false }).addTo(mapa);

const fmt = v => v.toLocaleString('es-CL', { maximumFractionDigits: 1 });
const sel = document.getElementById('sel');
const claves = Object.keys(D.trazados);
for (const k of claves) sel.add(new Option(k, k));
function mostrar(k) {
  for (const c of Object.values(trazados)) mapa.removeLayer(c);
  trazados[k].addTo(mapa);
  const R = D.trazados[k].resumen;
  const filas = R.map(r => `<tr><td>${r.nombre}</td><td>${fmt(r.largo_km)}</td><td>${fmt(r.tunel_km)}</td><td>${fmt(r.viaducto_km)}</td><td>${r.cruces}</td></tr>`).join('');
  const t = R.reduce((a, r) => [a[0] + r.largo_km, a[1] + r.tunel_km, a[2] + r.viaducto_km, a[3] + r.cruces], [0, 0, 0, 0]);
  document.getElementById('tabla').innerHTML = `<table><thead><tr><th>Subtramo</th><th>Largo</th><th>Túnel</th><th>Viaducto</th><th>Ríos &gt;1.000 km²</th></tr></thead><tbody>${filas}<tr class="total"><td>Total</td><td>${fmt(t[0])}</td><td>${fmt(t[1])}</td><td>${fmt(t[2])}</td><td>${t[3]}</td></tr></tbody></table>`;
}
sel.onchange = () => mostrar(sel.value);
sel.value = claves[claves.length - 1]; mostrar(sel.value);
</script>
"""

if __name__ == "__main__":
    main()
