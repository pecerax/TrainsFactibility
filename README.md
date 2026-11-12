# Trains Factibility: tren longitudinal en Chile

Herramientas para estudiar la factibilidad de un trazado ferroviario a lo largo de Chile, tramo a tramo:

1. **Mapa base** con topografía, geología, hidrología y fallas activas de Chile.
2. **Trazados candidatos** dibujados sobre ese mapa, ya sea a mano (puntos de paso) o como corredor de menor pendiente sobre el modelo de elevación.
3. **Evaluación de cada tramo** contra las capas: perfil longitudinal, rasante con pendiente máxima, largo en túnel y viaducto, cruces de ríos, unidades geológicas y fallas.

El nivel de análisis es **idea / perfil temprano**. Sirve para comparar corredores y detectar los puntos difíciles, no para diseñar.

## Primer caso: Santiago–Antofagasta

| Trazado | Cómo se trazó | Largo | Túnel (2,5 %) | Viaducto (2,5 %) |
|---|---|---|---|---|
| [v1](reportes/santiago-antofagasta/resumen.md) | Rectas entre puntos de paso sobre la Ruta 5 | 1.175 km | 238 km | 387 km |
| [v2](reportes/santiago-antofagasta-v2/resumen.md) | Corredor de menor pendiente entre ciudades-estación | 1.519 km | 44 km | 63 km |

El corredor v2 es un 29 % más largo pero reduce las obras mayores (túnel + viaducto) de 625 km a 107 km. Los puntos más exigentes son la subida desde Copiapó hacia Diego de Almagro y la bajada final a Antofagasta por el farellón costero.

## Trazado interactivo de alta velocidad

Abre [`mapa/index.html`](mapa/index.html) en el navegador (archivo único, no requiere servidor). Haz click en un origen y un destino y el mapa calcula, en menos de un segundo:

1. **Corredor de menor costo** sobre una grilla de elevación de Chile de ~1,3 km (A* con 16 vecinos). El costo de cada paso crece con el cuadrado de su pendiente respecto de la pendiente máxima, con un tope que equivale a ir en túnel o viaducto.
2. **Trazado en planta** con rectas y curvas circulares. El radio mínimo sale de `R = V² · 11,8 / (D + I)` con peralte más insuficiencia de 200 mm: 3.700 m a 250 km/h, 5.300 m a 300 km/h y 7.250 m a 350 km/h, en línea con las líneas AVE, LGV y Shinkansen. Se exige una recta mínima de 0,6·V m entre curvas y se amplía el radio hasta 1,6·Rmin donde cabe.
3. **Rasante óptima**: la línea más cercana al terreno en mínimos cuadrados con pendiente máxima de 2,5 %, 3,5 % o 4 % (dual resuelto con FISTA). Más de 25 m bajo el terreno es túnel; más de 15 m sobre él, viaducto.
4. **Velocidad y tiempo de viaje** con límite por curva, aceleración limitada por potencia y frenado de servicio, sin paradas intermedias.
5. **Cruces** de ríos con cuenca sobre 1.000 km² y de fallas activas.
6. **Costo de orden de magnitud** con valores unitarios típicos de alta velocidad (20 / 45 / 75 MUSD por km de superficie / viaducto / túnel, puentes mayores, terminales y 30 % de contingencia), con rango de −30 % a +50 %.

El botón *Copiar GeoJSON* entrega el eje para pasarlo a `scripts/evaluar_tramo.py`, que agrega geología a mayor detalle y el perfil en PNG. El motor está en [`web/motor.js`](web/motor.js) y se puede usar también desde Node.

## Estructura

```
trenes/            módulos: DEM, geología, rasante, corredor de menor costo, teselas y grilla del mapa
web/               motor de trazado de alta velocidad (JS) y plantilla del mapa
scripts/
  preparar_capas.py     descarga y recorta ríos, cuencas y fallas a Chile
  trazar_corredor.py    genera un trazado de menor costo desde un archivo de paradas
  evaluar_tramo.py      evalúa un trazado y escribe el reporte
  construir_mapa.py     genera mapa/index.html
tramos/            trazados (GeoJSON) y archivos de paradas (JSON)
reportes/<trazado>/  resumen.md, perfiles PNG, resumen.json, trazado_evaluado.geojson
data/procesado/    capas livianas recortadas a Chile (versionadas)
data/cache/        descargas pesadas (no versionadas)
```

## Uso

```bash
pip install -r requirements.txt
python scripts/preparar_capas.py                                  # una vez
python scripts/trazar_corredor.py tramos/santiago-antofagasta_paradas.json
python scripts/evaluar_tramo.py tramos/santiago-antofagasta-v2.geojson
python scripts/construir_mapa.py
```

Para probar un tramo nuevo: copia un archivo `tramos/*_paradas.json`, cambia las paradas y corre los tres últimos comandos. También puedes dibujar la línea en cualquier SIG (QGIS, geojson.io) y pasarla directo a `evaluar_tramo.py`.

## Método

- **Perfil**: el eje se muestrea cada 200 m sobre Copernicus DEM GLO-90.
- **Rasante**: la línea vertical más cercana al terreno (mínimos cuadrados) con pendiente máxima de 1,5 % (carga) y 2,5 % (mixto/pasajeros). Donde el terreno queda más de 30 m sobre la rasante se cuenta túnel; más de 20 m bajo ella, viaducto; el resto es corte o terraplén.
- **Corredor de menor costo**: camino de costo mínimo sobre el DEM (celdas de ~180 m) con costo creciente según el cuadrado de la pendiente del terreno. Encuentra valles y cuestas suaves, pero no impone radios de curva.
- **Ríos**: cruces con HydroRIVERS (cauces con cuenca > 10 km²); se informa cuenca aportante y caudal medio como indicador del tamaño del puente.
- **Geología**: unidad del mapa Macrostrat cada 5 km; se marcan depósitos cuaternarios no consolidados (licuefacción, asentamientos, aluviones) y rocas volcánicas.
- **Fallas**: cruces y cercanía (< 10 km) a fallas de la base GEM Global Active Faults.

## Limitaciones conocidas

- El trazado interactivo usa curvas circulares sin clotoides de transición ni curvas verticales de diseño; las longitudes de obra son indicativas.
- La grilla de ~1,3 km no ve quebradas angostas ni cerros pequeños.
- El mapa geológico es de escala 1:1.000.000; un estudio de prefactibilidad necesita cartas 1:100.000 o 1:250.000 de Sernageomin.
- HydroRIVERS es un modelo global; en el norte muchas quebradas son secas la mayor parte del año pero tienen riesgo de aluvión.
- No incluye todavía: uso de suelo, áreas protegidas (SNASPE), tierras indígenas, faja ferroviaria existente de EFE/Ferronor ni demanda.

## Fuentes

- Elevación: [Copernicus DEM GLO-90](https://registry.opendata.aws/copernicus-dem/) (ESA) y [Terrain Tiles](https://registry.opendata.aws/terrain-tiles/) para el relieve del mapa.
- Ríos y cuencas: [HydroRIVERS y HydroBASINS](https://www.hydrosheds.org/) (WWF / HydroSHEDS).
- Geología: [Macrostrat](https://macrostrat.org/), que integra el Mapa Geológico de Chile 1:1.000.000 de Sernageomin.
- Fallas activas: [GEM Global Active Faults Database](https://github.com/GEMScienceTools/gem-global-active-faults).
