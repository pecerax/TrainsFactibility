// Motor de trazado ferroviario de alta velocidad (nivel idea).
// Funciones puras: se usan en el mapa (navegador) y en las pruebas con Node.
//
// Flujo: corredor de menor costo sobre la grilla de elevación -> simplificación ->
// trazado en planta con rectas y curvas circulares de radio mínimo según velocidad ->
// perfil de terreno -> rasante con pendiente máxima -> túneles / viaductos ->
// perfil de velocidad y tiempo de viaje -> cruces de ríos y fallas -> costo de orden de magnitud.
(function (raiz) {
  'use strict';

  const M_LAT = 110574;          // metros por grado de latitud
  const M_LON = 111320;          // metros por grado de longitud en el ecuador
  const PASO_PERFIL = 100;       // m entre puntos del perfil
  const PERALTE_MAS_INSUF = 200; // mm: peralte 150 + insuficiencia 50 (criterio de confort AV)

  // Parámetros de diseño por velocidad. Radio mínimo: R = V² · 11,8 / (D + I).
  function parametros(vDiseno, pendMax) {
    const rMin = Math.round(vDiseno * vDiseno * 11.8 / PERALTE_MAS_INSUF / 50) * 50;
    return {
      v: vDiseno, pendMax, rMin,
      rectaMin: Math.round(vDiseno * 0.6),   // recta mínima entre curvas (m), aprox. 0,6·V
      acel: 0.35, frenado: 0.5,              // m/s²
      umbralTunel: 25, umbralViaducto: 15,   // m de diferencia terreno - rasante
    };
  }

  // Velocidad máxima en curva (km/h) para un radio R (m)
  const vCurva = R => Math.sqrt(R * PERALTE_MAS_INSUF / 11.8);

  // ---------------- grilla ----------------
  // G = { lon0, lat0 (borde norte), paso, w, h, z: Float32Array (NaN = mar) }
  function cota(G, lon, lat) {
    const fx = (lon - G.lon0) / G.paso - 0.5, fy = (G.lat0 - lat) / G.paso - 0.5;
    const x0 = Math.floor(fx), y0 = Math.floor(fy);
    if (x0 < 0 || y0 < 0 || x0 + 1 >= G.w || y0 + 1 >= G.h) return NaN;
    const tx = fx - x0, ty = fy - y0, i = y0 * G.w + x0;
    const a = G.z[i], b = G.z[i + 1], c = G.z[i + G.w], d = G.z[i + G.w + 1];
    const v = [a, b, c, d], p = [(1 - tx) * (1 - ty), tx * (1 - ty), (1 - tx) * ty, tx * ty];
    let s = 0, ws = 0;
    for (let k = 0; k < 4; k++) if (!Number.isNaN(v[k])) { s += v[k] * p[k]; ws += p[k]; }
    return ws > 0.25 ? s / ws : NaN;
  }

  // ---------------- corredor de menor costo (A*) ----------------
  function corredor(G, a, b, prm, prioridad) {
    // prioridad: 0 = lo más directo posible, 1 = evita al máximo túneles y viaductos
    const k = 0.15 + 2.85 * prioridad;
    const TOPE = 1 + 3.5 * (0.4 + prioridad); // multiplicador máximo (equivale a ir en túnel/viaducto)
    const span = Math.max(Math.abs(a.lat - b.lat), Math.abs(a.lon - b.lon));
    const m = Math.max(0.35, 0.3 * span);
    const lonMin = Math.min(a.lon, b.lon) - m, lonMax = Math.max(a.lon, b.lon) + m;
    const latMin = Math.min(a.lat, b.lat) - m, latMax = Math.max(a.lat, b.lat) + m;
    const cx0 = Math.max(0, Math.floor((lonMin - G.lon0) / G.paso));
    const cx1 = Math.min(G.w - 1, Math.ceil((lonMax - G.lon0) / G.paso));
    const cy0 = Math.max(0, Math.floor((G.lat0 - latMax) / G.paso));
    const cy1 = Math.min(G.h - 1, Math.ceil((G.lat0 - latMin) / G.paso));
    const W = cx1 - cx0 + 1, H = cy1 - cy0 + 1, N = W * H;
    const zc = (x, y) => G.z[(y + cy0) * G.w + (x + cx0)];
    const celda = p => [
      Math.min(W - 1, Math.max(0, Math.floor((p.lon - G.lon0) / G.paso) - cx0)),
      Math.min(H - 1, Math.max(0, Math.floor((G.lat0 - p.lat) / G.paso) - cy0))];
    const [ax, ay] = celda(a), [bx, by] = celda(b);
    const dy = G.paso * M_LAT;
    const dxFila = new Float64Array(H);
    for (let y = 0; y < H; y++) {
      const lat = G.lat0 - (y + cy0 + 0.5) * G.paso;
      dxFila[y] = G.paso * M_LON * Math.cos(lat * Math.PI / 180);
    }
    const VEC = [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [1, -1], [-1, 1], [-1, -1],
                 [1, 2], [1, -2], [-1, 2], [-1, -2], [2, 1], [2, -1], [-2, 1], [-2, -1]];
    const dist = new Float64Array(N).fill(Infinity);
    const prev = new Int32Array(N).fill(-1);
    const cerrado = new Uint8Array(N);
    // montículo binario de mínimos
    let hi = new Int32Array(1024), hp = new Float64Array(1024), hn = 0;
    const push = (i, p) => {
      if (hn === hi.length) { const ni = new Int32Array(hn * 2); ni.set(hi); hi = ni; const np = new Float64Array(hn * 2); np.set(hp); hp = np; }
      let c = hn++;
      while (c > 0) { const pa = (c - 1) >> 1; if (hp[pa] <= p) break; hi[c] = hi[pa]; hp[c] = hp[pa]; c = pa; }
      hi[c] = i; hp[c] = p;
    };
    const pop = () => {
      const r = hi[0], li = hi[--hn], lp = hp[hn];
      let c = 0;
      for (;;) {
        let h = 2 * c + 1; if (h >= hn) break;
        if (h + 1 < hn && hp[h + 1] < hp[h]) h++;
        if (hp[h] >= lp) break;
        hi[c] = hi[h]; hp[c] = hp[h]; c = h;
      }
      hi[c] = li; hp[c] = lp; return r;
    };
    const heur = (x, y) => Math.hypot((x - bx) * dxFila[y], (y - by) * dy);
    const ini = ay * W + ax, fin = by * W + bx;
    dist[ini] = 0; push(ini, heur(ax, ay));
    while (hn > 0) {
      const i = pop();
      if (cerrado[i]) continue;
      cerrado[i] = 1;
      if (i === fin) break;
      const x = i % W, y = (i / W) | 0;
      let z0 = zc(x, y); if (Number.isNaN(z0)) z0 = 0;
      for (const [vx, vy] of VEC) {
        const nx = x + vx, ny = y + vy;
        if (nx < 0 || ny < 0 || nx >= W || ny >= H) continue;
        const j = ny * W + nx;
        if (cerrado[j]) continue;
        let z1 = zc(nx, ny);
        const mar = Number.isNaN(z1);
        if (mar && j !== fin) continue; // el trazado no va por el mar
        if (mar) z1 = 0;
        const d = Math.hypot(vx * dxFila[y], vy * dy);
        const g = Math.abs(z1 - z0) / d / prm.pendMax;
        const c = d * Math.min(TOPE, 1 + k * g * g);
        const nd = dist[i] + c;
        if (nd < dist[j]) { dist[j] = nd; prev[j] = i; push(j, nd + heur(nx, ny)); }
      }
    }
    if (prev[fin] < 0 && fin !== ini) return null;
    const camino = [];
    for (let i = fin; i >= 0; i = prev[i]) {
      const x = i % W, y = (i / W) | 0;
      camino.push({ lon: G.lon0 + (x + cx0 + 0.5) * G.paso, lat: G.lat0 - (y + cy0 + 0.5) * G.paso });
      if (i === ini) break;
    }
    camino.reverse();
    camino[0] = { lon: a.lon, lat: a.lat };
    camino[camino.length - 1] = { lon: b.lon, lat: b.lat };
    return camino;
  }

  // ---------------- proyección local (sinusoidal, meridiano central del tramo) ----------------
  function proyeccion(lon0) {
    return {
      a: p => ({ x: (p.lon - lon0) * M_LON * Math.cos(p.lat * Math.PI / 180), y: p.lat * M_LAT }),
      de: q => { const lat = q.y / M_LAT; return { lat, lon: lon0 + q.x / (M_LON * Math.cos(lat * Math.PI / 180)) }; },
    };
  }

  function douglasPeucker(P, tol) {
    if (P.length < 3) return P.slice();
    const marca = new Uint8Array(P.length); marca[0] = marca[P.length - 1] = 1;
    const pila = [[0, P.length - 1]];
    while (pila.length) {
      const [i, j] = pila.pop();
      const ax = P[i].x, ay = P[i].y, bx = P[j].x, by = P[j].y, L = Math.hypot(bx - ax, by - ay) || 1;
      let dmax = 0, kmax = -1;
      for (let k = i + 1; k < j; k++) {
        const d = Math.abs((bx - ax) * (ay - P[k].y) - (ax - P[k].x) * (by - ay)) / L;
        if (d > dmax) { dmax = d; kmax = k; }
      }
      if (dmax > tol) { marca[kmax] = 1; pila.push([i, kmax], [kmax, j]); }
    }
    return P.filter((_, i) => marca[i]);
  }

  // ---------------- trazado en planta: rectas + curvas circulares ----------------
  function geometriaVertices(P, radios) {
    const n = P.length, T = new Float64Array(n), D = new Float64Array(n);
    for (let i = 1; i < n - 1; i++) {
      const ux = P[i].x - P[i - 1].x, uy = P[i].y - P[i - 1].y, vx = P[i + 1].x - P[i].x, vy = P[i + 1].y - P[i].y;
      const ang = Math.abs(Math.atan2(ux * vy - uy * vx, ux * vx + uy * vy));
      D[i] = ang; T[i] = radios[i] * Math.tan(ang / 2);
    }
    return { T, D };
  }

  function ajustarCurvas(P, prm) {
    P = P.slice();
    // Quita vértices hasta que todas las tangentes de curva caben en sus rectas
    for (let iter = 0; iter < 10000; iter++) {
      const rad = new Float64Array(P.length).fill(prm.rMin);
      const { T, D } = geometriaVertices(P, rad);
      let peor = -1, exceso = 0;
      for (let j = 0; j < P.length - 1; j++) {
        const L = Math.hypot(P[j + 1].x - P[j].x, P[j + 1].y - P[j].y);
        const e = T[j] + T[j + 1] + ((j > 0 && j + 1 < P.length - 1) ? prm.rectaMin : 0) - L;
        if (e > exceso) { exceso = e; peor = j; }
      }
      // también se descartan quiebres > 120°, que no son trazables a alta velocidad
      let quiebre = -1;
      for (let i = 1; i < P.length - 1; i++) if (D[i] > 2.1) { quiebre = i; break; }
      if (peor < 0 && quiebre < 0) break;
      let quitar;
      if (quiebre > 0) quitar = quiebre;
      else {
        const cand = [peor, peor + 1].filter(i => i > 0 && i < P.length - 1);
        if (!cand.length) break;
        // quita el vértice cuya eliminación desvía menos el trazado
        const desvio = i => {
          const A = P[i - 1], B = P[i + 1], C = P[i], L = Math.hypot(B.x - A.x, B.y - A.y) || 1;
          return Math.abs((B.x - A.x) * (A.y - C.y) - (A.x - C.x) * (B.y - A.y)) / L;
        };
        quitar = cand.sort((p, q) => desvio(p) - desvio(q))[0];
      }
      P.splice(quitar, 1);
    }
    // Radios: el mínimo, ampliado hasta 1,6·Rmin donde la geometría lo permite (más velocidad y confort)
    const radios = new Float64Array(P.length).fill(prm.rMin);
    const { T: T0, D } = geometriaVertices(P, radios);
    for (let i = 1; i < P.length - 1; i++) {
      if (D[i] < 1e-4) continue;
      const Lp = Math.hypot(P[i].x - P[i - 1].x, P[i].y - P[i - 1].y) - T0[i - 1] - (i > 1 ? prm.rectaMin : 0);
      const Ln = Math.hypot(P[i + 1].x - P[i].x, P[i + 1].y - P[i].y) - T0[i + 1] - (i < P.length - 2 ? prm.rectaMin : 0);
      const Tmax = Math.min(Lp, Ln) / 2 + T0[i] / 2; // reparte la holgura con el vecino
      radios[i] = Math.max(prm.rMin, Math.min(1.6 * prm.rMin, Tmax / Math.tan(D[i] / 2)));
    }
    return { P, radios };
  }

  // Muestrea el eje (rectas y arcos) cada `paso` m. Cada punto lleva el radio (Infinity en recta).
  function densificar(P, radios, paso) {
    const { T } = geometriaVertices(P, radios);
    const out = [], curvas = [];
    const agregarRecta = (A, B) => {
      const L = Math.hypot(B.x - A.x, B.y - A.y), n = Math.max(1, Math.ceil(L / paso));
      for (let k = (out.length ? 1 : 0); k <= n; k++) out.push({ x: A.x + (B.x - A.x) * k / n, y: A.y + (B.y - A.y) * k / n, R: Infinity });
    };
    let actual = P[0];
    for (let i = 1; i < P.length - 1; i++) {
      if (T[i] < 1) continue;
      const ux = P[i].x - P[i - 1].x, uy = P[i].y - P[i - 1].y, lu = Math.hypot(ux, uy);
      const vx = P[i + 1].x - P[i].x, vy = P[i + 1].y - P[i].y, lv = Math.hypot(vx, vy);
      const tin = { x: P[i].x - ux / lu * T[i], y: P[i].y - uy / lu * T[i] };
      const s = Math.sign(ux * vy - uy * vx) || 1, R = radios[i];
      const C = { x: tin.x + s * R * (-uy / lu), y: tin.y + s * R * (ux / lu) };
      const a0 = Math.atan2(tin.y - C.y, tin.x - C.x);
      const delta = Math.abs(Math.atan2(ux * vy - uy * vx, ux * vx + uy * vy));
      agregarRecta(actual, tin);
      const ini = out.length - 1;
      const n = Math.max(2, Math.ceil(R * delta / paso));
      for (let k = 1; k <= n; k++) {
        const a = a0 + s * delta * k / n;
        out.push({ x: C.x + R * Math.cos(a), y: C.y + R * Math.sin(a), R });
      }
      out[ini].R = R;
      curvas.push({ R, largo: R * delta, desvio_grados: delta * 180 / Math.PI, idx: ini });
      actual = out[out.length - 1];
    }
    agregarRecta(actual, P[P.length - 1]);
    return { eje: out, curvas };
  }

  // ---------------- perfil longitudinal y rasante ----------------
  function mediaMovil(v, w) {
    const n = v.length, h = Math.max(0, Math.floor(w / 2)), out = new Float64Array(n);
    const pref = new Float64Array(n + 1);
    for (let i = 0; i < n; i++) pref[i + 1] = pref[i] + v[i];
    for (let i = 0; i < n; i++) { const a = Math.max(0, i - h), b = Math.min(n - 1, i + h); out[i] = (pref[b + 1] - pref[a]) / (b - a + 1); }
    return out;
  }

  // Rasante con |pendiente| <= pmax: la línea más cercana al terreno en mínimos cuadrados.
  // Se resuelve el problema dual con FISTA (gradiente proximal acelerado) sobre una grilla de
  // 250 m y se interpola. Al final se corrigen excesos numéricos de pendiente.
  function rasante(z, ds, pmax) {
    const n = z.length;
    const paso = Math.max(1, Math.round(250 / ds));
    const zc = [];
    for (let i = 0; i < n; i += paso) zc.push(z[i]);
    if ((n - 1) % paso) zc.push(z[n - 1]);
    const m = zc.length, dsc = paso * ds, lim = pmax * dsc;
    const Dz = new Float64Array(m - 1);
    for (let i = 0; i < m - 1; i++) Dz[i] = zc[i + 1] - zc[i];
    let mu = new Float64Array(m - 1), y = new Float64Array(m - 1), tk = 1;
    const g = new Float64Array(m);
    const primal = v => { // g = z - D^T v
      for (let i = 0; i < m; i++) g[i] = zc[i] - (i > 0 ? v[i - 1] : 0) + (i < m - 1 ? v[i] : 0);
    };
    const it = Math.min(20000, 40 * m + 2000), paso_t = 0.25;
    for (let k = 0; k < it; k++) {
      primal(y);
      const nuevo = new Float64Array(m - 1);
      for (let i = 0; i < m - 1; i++) {
        const w = y[i] + paso_t * (g[i + 1] - g[i]);          // y - t * grad, grad = -D g
        const u = paso_t * lim;
        nuevo[i] = w > u ? w - u : w < -u ? w + u : 0;        // umbral suave
      }
      const tk1 = (1 + Math.sqrt(1 + 4 * tk * tk)) / 2;
      for (let i = 0; i < m - 1; i++) y[i] = nuevo[i] + ((tk - 1) / tk1) * (nuevo[i] - mu[i]);
      mu = nuevo; tk = tk1;
    }
    primal(mu);
    for (let i = 1; i < m; i++) g[i] = Math.min(Math.max(g[i], g[i - 1] - lim), g[i - 1] + lim);
    // interpolar a la grilla original
    const out = new Float64Array(n);
    for (let i = 0; i < n; i++) {
      const f = i / paso, a = Math.min(m - 1, Math.floor(f)), b = Math.min(m - 1, a + 1), t = f - a;
      out[i] = g[a] * (1 - t) + g[b] * t;
    }
    return out;
  }

  function perfilVelocidad(eje, ds, prm) {
    const n = eje.length, v = new Float64Array(n);
    for (let i = 0; i < n; i++) v[i] = Math.min(prm.v, Number.isFinite(eje[i].R) ? vCurva(eje[i].R) : prm.v) / 3.6;
    v[0] = 0; v[n - 1] = 0;
    // aceleración limitada por potencia: plena hasta ~120 km/h, luego decae como 1/v
    const acel = vms => prm.acel * Math.min(1, (120 / 3.6) / Math.max(vms, 1));
    for (let i = 1; i < n; i++) v[i] = Math.min(v[i], Math.sqrt(v[i - 1] ** 2 + 2 * acel(v[i - 1]) * ds));
    for (let i = n - 2; i >= 0; i--) v[i] = Math.min(v[i], Math.sqrt(v[i + 1] ** 2 + 2 * prm.frenado * ds));
    let t = 0;
    for (let i = 1; i < n; i++) { const vm = (v[i] + v[i - 1]) / 2; t += ds / Math.max(vm, 0.5); }
    return { v: Array.from(v, x => x * 3.6), segundos: t };
  }

  // ---------------- cruces con capas vectoriales ----------------
  function seCortan(p1, p2, p3, p4) {
    const d = (p2.x - p1.x) * (p4.y - p3.y) - (p2.y - p1.y) * (p4.x - p3.x);
    if (Math.abs(d) < 1e-9) return null;
    const t = ((p3.x - p1.x) * (p4.y - p3.y) - (p3.y - p1.y) * (p4.x - p3.x)) / d;
    const u = ((p3.x - p1.x) * (p2.y - p1.y) - (p3.y - p1.y) * (p2.x - p1.x)) / d;
    return (t >= 0 && t <= 1 && u >= 0 && u <= 1) ? t : null;
  }

  function lineas(geo) {
    const out = [];
    for (const f of geo.features) {
      const g = f.geometry; if (!g) continue;
      const partes = g.type === 'LineString' ? [g.coordinates] : g.type === 'MultiLineString' ? g.coordinates : [];
      for (const c of partes) out.push({ props: f.properties, coords: c });
    }
    return out;
  }

  function cruces(ejeProy, km, geo, proj, filtro) {
    let xmin = Infinity, xmax = -Infinity, ymin = Infinity, ymax = -Infinity;
    for (const p of ejeProy) { xmin = Math.min(xmin, p.x); xmax = Math.max(xmax, p.x); ymin = Math.min(ymin, p.y); ymax = Math.max(ymax, p.y); }
    const out = [];
    for (const ln of lineas(geo)) {
      if (filtro && !filtro(ln.props)) continue;
      const q = ln.coords.map(c => proj.a({ lon: c[0], lat: c[1] }));
      if (q.every(p => p.x < xmin || p.x > xmax || p.y < ymin || p.y > ymax)) continue;
      for (let j = 0; j < q.length - 1; j++) {
        for (let i = 0; i < ejeProy.length - 1; i++) {
          const t = seCortan(ejeProy[i], ejeProy[i + 1], q[j], q[j + 1]);
          if (t !== null) out.push({ km: km[i] + t * (km[i + 1] - km[i]), props: ln.props });
        }
      }
    }
    out.sort((a, b) => a.km - b.km);
    return out;
  }

  // ---------------- costo (orden de magnitud, USD millones de 2025) ----------------
  // Referencias de líneas AV europeas y asiáticas: superficie 15-25, viaducto 35-60, túnel 50-100 MUSD/km.
  const COSTO = { tierra: 20, viaducto: 45, tunel: 75, puente_rio: 25, terminal: 250, contingencia: 0.30 };

  function costo(km, rios) {
    const base = km.tierra * COSTO.tierra + km.viaducto * COSTO.viaducto + km.tunel * COSTO.tunel
      + rios * COSTO.puente_rio + 2 * COSTO.terminal;
    const total = base * (1 + COSTO.contingencia);
    return { total, bajo: total * 0.7, alto: total * 1.5 };
  }

  // ---------------- todo junto ----------------
  function trazar(G, a, b, opciones, capas) {
    const prm = parametros(opciones.velocidad, opciones.pendiente);
    const t0 = Date.now();
    const camino = corredor(G, a, b, prm, opciones.prioridad);
    if (!camino) return { error: 'No encontré un corredor terrestre entre esos dos puntos.' };
    const proj = proyeccion((a.lon + b.lon) / 2);
    const P = camino.map(proj.a);
    const simple = douglasPeucker(P, 900);
    const { P: vert, radios } = ajustarCurvas(simple, prm);
    const { eje: crudo, curvas } = densificar(vert, radios, PASO_PERFIL / 4);

    // remuestreo exacto cada PASO_PERFIL m (el radio se toma del tramo en que cae cada punto)
    const acum = [0];
    for (let i = 1; i < crudo.length; i++) acum.push(acum[i - 1] + Math.hypot(crudo[i].x - crudo[i - 1].x, crudo[i].y - crudo[i - 1].y));
    const largo = acum[acum.length - 1];
    const nPts = Math.max(2, Math.round(largo / PASO_PERFIL) + 1);
    const eje = [], km = [];
    for (let k = 0, j = 0; k < nPts; k++) {
      const s = largo * k / (nPts - 1);
      while (j < crudo.length - 2 && acum[j + 1] < s) j++;
      const t = (s - acum[j]) / Math.max(1e-9, acum[j + 1] - acum[j]);
      eje.push({ x: crudo[j].x + t * (crudo[j + 1].x - crudo[j].x), y: crudo[j].y + t * (crudo[j + 1].y - crudo[j].y),
                 R: Number.isFinite(crudo[j + 1].R) ? crudo[j + 1].R : crudo[j].R });
      km.push(s);
    }
    for (const c of curvas) c.km = acum[c.idx] / 1000;
    const geo = eje.map(proj.de);
    let z = geo.map(p => cota(G, p.lon, p.lat));
    // puntos sin dato (mar, bahías): se asumen a -10 m, es decir, puente o viaducto
    z = z.map(v => Number.isNaN(v) ? -10 : v);
    const dsMedio = largo / Math.max(1, eje.length - 1);
    const g = rasante(z, dsMedio, prm.pendMax);
    const clase = z.map((zi, i) => zi - g[i] > prm.umbralTunel ? 'tunel' : g[i] - zi > prm.umbralViaducto ? 'viaducto' : 'tierra');
    const kmClase = { tierra: 0, tunel: 0, viaducto: 0 };
    for (let i = 1; i < eje.length; i++) kmClase[clase[i]] += (km[i] - km[i - 1]) / 1000;
    let pendMaxReal = 0;
    for (let i = 1; i < g.length; i++) pendMaxReal = Math.max(pendMaxReal, Math.abs(g[i] - g[i - 1]) / Math.max(1, km[i] - km[i - 1]));
    const vel = perfilVelocidad(eje, dsMedio, prm);

    const kmKm = km.map(v => v / 1000);
    let rios = [], fallas = [];
    if (capas && capas.rios) {
      rios = cruces(eje, kmKm, capas.rios, proj, p => p.UPLAND_SKM >= 1000);
      // un mismo río cortado varias veces en pocos km cuenta una vez
      rios = rios.filter((r, i) => i === 0 || r.km - rios[i - 1].km > 2);
    }
    if (capas && capas.fallas) fallas = cruces(eje, kmKm, capas.fallas, proj);

    const rUsados = curvas.map(c => c.R);
    const c = costo(kmClase, rios.length);
    return {
      prm, ms: Date.now() - t0,
      largo_km: largo / 1000,
      recta_km: Math.hypot(proj.a(a).x - proj.a(b).x, proj.a(a).y - proj.a(b).y) / 1000,
      geo, km: kmKm, z, g, clase, v: vel.v,
      curvas, radio_min_usado: rUsados.length ? Math.min(...rUsados) : null,
      km_clase: kmClase, pendiente_max_real: pendMaxReal,
      cota_min: Math.min(...z), cota_max: Math.max(...z),
      minutos: vel.segundos / 60, v_media: (largo / 1000) / (vel.segundos / 3600),
      rios, fallas, costo: c,
    };
  }

  raiz.MotorAV = { parametros, vCurva, cota, corredor, douglasPeucker, ajustarCurvas, densificar, rasante, perfilVelocidad, cruces, costo, trazar, COSTO };
  if (typeof module !== 'undefined') module.exports = raiz.MotorAV;
})(typeof window !== 'undefined' ? window : globalThis);
