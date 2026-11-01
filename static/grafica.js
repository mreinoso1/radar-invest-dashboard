"use strict";
/* Gráfica de precios y capa de dibujo.
   Lightweight Charts pinta las velas pero no trae herramientas de dibujo: encima va un
   canvas propio. Los dibujos se guardan en tiempo/precio, nunca en píxeles, para que
   sobrevivan al zoom, al desplazamiento y al cambio de temporalidad. */

const COL = {
  fondo: "#101413", rejilla: "#1b2120", eje: "#2a3230", texto: "#8d9995",
  sube: "#26c6b0", baja: "#ff6a55", acento: "#f2b33d",
};

const HERRAMIENTAS = {
  tendencia: { puntos: 2, nombre: "Línea de tendencia" },
  rayo: { puntos: 2, nombre: "Rayo" },
  extendida: { puntos: 2, nombre: "Línea extendida" },
  horizontal: { puntos: 1, nombre: "Línea horizontal" },
  vertical: { puntos: 1, nombre: "Línea vertical" },
  canal: { puntos: 3, nombre: "Canal paralelo" },
  tridente: { puntos: 3, nombre: "Tridente de Andrews" },
  fibo: { puntos: 2, nombre: "Retroceso de Fibonacci" },
  rect: { puntos: 2, nombre: "Rectángulo" },
  elipse: { puntos: 2, nombre: "Elipse" },
  flecha: { puntos: 2, nombre: "Flecha" },
  pincel: { puntos: 0, nombre: "Pincel" },
  texto: { puntos: 1, nombre: "Texto" },
  medir: { puntos: 2, nombre: "Medir" },
  largo: { puntos: 2, nombre: "Posición larga" },
  corto: { puntos: 2, nombre: "Posición corta" },
};

const NIVELES_FIBO = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1, 1.618];

const INDICADORES = {
  sma20: { nombre: "SMA 20", color: "#f2b33d" },
  sma50: { nombre: "SMA 50", color: "#6aa8ff" },
  sma200: { nombre: "SMA 200", color: "#c58bf2" },
  ema20: { nombre: "EMA 20", color: "#ff9f6b" },
  ema50: { nombre: "EMA 50", color: "#5ed1e8" },
  boll: { nombre: "Bollinger 20,2", color: "#8d9995" },
  rsi: { nombre: "RSI 14", color: "#c58bf2", panel: true },
  macd: { nombre: "MACD 12,26,9", color: "#6aa8ff", panel: true },
};

/* ---------- Cálculo de indicadores ---------- */

function sma(v, n) {
  const r = new Array(v.length).fill(null);
  let s = 0;
  for (let i = 0; i < v.length; i++) {
    s += v[i];
    if (i >= n) s -= v[i - n];
    if (i >= n - 1) r[i] = s / n;
  }
  return r;
}

function ema(v, n) {
  const r = new Array(v.length).fill(null);
  const k = 2 / (n + 1);
  let e = null;
  for (let i = 0; i < v.length; i++) {
    if (v[i] === null) continue;
    e = e === null ? v[i] : v[i] * k + e * (1 - k);
    r[i] = e;
  }
  return r;
}

function bollinger(v, n, d) {
  const media = sma(v, n), alta = [], baja = [];
  for (let i = 0; i < v.length; i++) {
    if (media[i] === null) { alta.push(null); baja.push(null); continue; }
    let s = 0;
    for (let j = i - n + 1; j <= i; j++) s += (v[j] - media[i]) ** 2;
    const de = Math.sqrt(s / n);
    alta.push(media[i] + d * de);
    baja.push(media[i] - d * de);
  }
  return { media, alta, baja };
}

function rsi(v, n) {
  const r = new Array(v.length).fill(null);
  let g = 0, p = 0;
  for (let i = 1; i < v.length; i++) {
    const c = v[i] - v[i - 1], gana = Math.max(c, 0), pierde = Math.max(-c, 0);
    if (i <= n) { g += gana / n; p += pierde / n; }
    else { g = (g * (n - 1) + gana) / n; p = (p * (n - 1) + pierde) / n; }
    if (i >= n) r[i] = p === 0 ? 100 : 100 - 100 / (1 + g / p);
  }
  return r;
}

function macd(v) {
  const a = ema(v, 12), b = ema(v, 26);
  const linea = v.map((_, i) => (i >= 25 ? a[i] - b[i] : null));
  const senal = ema(linea, 9);
  return { linea, senal, hist: linea.map((x, i) => (x === null || senal[i] === null ? null : x - senal[i])) };
}

function heikin(velas) {
  const r = [];
  velas.forEach((b, i) => {
    const close = (b.open + b.high + b.low + b.close) / 4;
    const open = i ? (r[i - 1].open + r[i - 1].close) / 2 : (b.open + b.close) / 2;
    r.push({ time: b.time, open, close, high: Math.max(b.high, open, close), low: Math.min(b.low, open, close) });
  });
  return r;
}

const aLinea = (velas, valores) => velas.map((b, i) => (valores[i] === null ? { time: b.time } : { time: b.time, value: valores[i] }));

function decimales(precio) {
  const p = Math.abs(precio || 0);
  return p >= 1 ? 2 : p >= 0.01 ? 4 : 6;
}

/* ---------- Gráfica ---------- */

class Grafica {
  constructor(contenedor, panel, eventos) {
    this.el = contenedor;
    this.elPanel = panel;
    this.ev = eventos;
    this.velas = [];
    this.tipo = "velas";
    this.activos = new Set();
    this.series = {};
    this.seriesPanel = [];
    this.marcadores = [];
    this.lineaMedia = null;
    this.precioMedio = null;

    const base = {
      autoSize: true,
      layout: { background: { color: COL.fondo }, textColor: COL.texto, fontFamily: "IBM Plex Mono, Consolas, monospace", fontSize: 11 },
      grid: { vertLines: { color: COL.rejilla }, horzLines: { color: COL.rejilla } },
      rightPriceScale: { borderColor: COL.eje, minimumWidth: 78 },
      timeScale: { borderColor: COL.eje, rightOffset: 8, tickMarkFormatter: (t, tipo) => this.marcaTiempo(t, tipo) },
      localization: { locale: "es-ES", timeFormatter: (t) => this.textoTiempo(t) },
      crosshair: { mode: 0, vertLine: { color: "#59645f" }, horzLine: { color: "#59645f" } },
    };
    this.chart = LightweightCharts.createChart(contenedor, base);
    this.sub = LightweightCharts.createChart(panel, { ...base, timeScale: { ...base.timeScale, visible: true } });
    this.volumen = this.chart.addHistogramSeries({
      priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false,
    });
    this.chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });
    this.crearSerie();

    this.chart.timeScale().subscribeVisibleLogicalRangeChange((r) => {
      if (r && this.elPanel.classList.contains("visible")) this.sub.timeScale().setVisibleLogicalRange(r);
    });
    this.chart.subscribeCrosshairMove((p) => this.leyenda(p));
    this.chart.subscribeClick((p) => { if (p.hoveredObjectId) this.ev.alMarcador?.(p.hoveredObjectId); });
    this.dibujo = new CapaDibujo(this);
  }

  intradia() { return ["1m", "5m", "15m", "1h", "4h"].includes(this.intervalo); }

  textoTiempo(t) {
    const d = new Date(t * 1000);
    return this.intradia()
      ? d.toLocaleString("es-ES", { day: "2-digit", month: "short", year: "2-digit", hour: "2-digit", minute: "2-digit" })
      : d.toLocaleDateString("es-ES", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });
  }

  marcaTiempo(t, tipo) {
    const d = new Date(t * 1000);
    if (tipo === 0) return String(d.getUTCFullYear());
    if (tipo === 1) return d.toLocaleDateString("es-ES", { month: "short", timeZone: "UTC" });
    if (tipo === 2) return d.toLocaleDateString("es-ES", { day: "numeric", month: "short", timeZone: "UTC" });
    return d.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
  }

  crearSerie() {
    const previa = this.serie;
    if (previa) this.chart.removeSeries(previa);
    const velas = {
      upColor: COL.sube, downColor: COL.baja, borderUpColor: COL.sube, borderDownColor: COL.baja,
      wickUpColor: COL.sube, wickDownColor: COL.baja,
    };
    if (this.tipo === "barras") this.serie = this.chart.addBarSeries({ upColor: COL.sube, downColor: COL.baja });
    else if (this.tipo === "linea") this.serie = this.chart.addLineSeries({ color: COL.acento, lineWidth: 2 });
    else if (this.tipo === "area") {
      this.serie = this.chart.addAreaSeries({
        lineColor: COL.acento, lineWidth: 2, topColor: "rgba(242,179,61,.28)", bottomColor: "rgba(242,179,61,0)",
      });
    } else this.serie = this.chart.addCandlestickSeries(velas);
    this.lineaMedia = null;
  }

  datosSerie(velas) {
    if (this.tipo === "linea" || this.tipo === "area") return velas.map((b) => ({ time: b.time, value: b.close }));
    return this.tipo === "heikin" ? heikin(velas) : velas;
  }

  datosVolumen(velas) {
    return velas.map((b) => ({
      time: b.time, value: b.volume,
      color: b.close >= b.open ? "rgba(38,198,176,.32)" : "rgba(255,106,85,.32)",
    }));
  }

  ponerDatos(info, intervalo) {
    this.info = info;
    this.intervalo = intervalo;
    this.velas = info.velas;
    const ultimo = this.velas.at(-1)?.close;
    const d = decimales(ultimo);
    this.serie.applyOptions({ priceFormat: { type: "price", precision: d, minMove: 10 ** -d } });
    this.serie.setData(this.datosSerie(this.velas));
    this.volumen.setData(this.datosVolumen(this.velas));
    this.pintarIndicadores();
    this.aplicarMarcadores();
    this.aplicarPrecioMedio();
    this.dibujo.datosCambiados();
    this.leyenda({});
  }

  cambiarTipo(tipo) {
    this.tipo = tipo;
    this.crearSerie();
    if (this.info) this.ponerDatos(this.info, this.intervalo);
  }

  /* Refresco periódico: actualiza solo la cola de la serie. */
  actualizarCola(info) {
    if (!this.velas.length) return;
    const ultimo = this.velas.at(-1).time;
    let nuevas = false;
    for (const b of info.velas) {
      if (b.time < ultimo) continue;
      const i = this.velas.findLastIndex((v) => v.time === b.time);
      if (i >= 0) this.velas[i] = b;
      else { this.velas.push(b); nuevas = true; }
    }
    const dato = this.datosSerie(this.velas);
    const ventana = this.tipo === "heikin" ? dato.slice(-3) : dato.filter((x) => x.time >= ultimo);
    ventana.forEach((x) => this.serie.update(x));
    this.datosVolumen(this.velas.filter((v) => v.time >= ultimo)).forEach((x) => this.volumen.update(x));
    if (nuevas) { this.pintarIndicadores(); this.dibujo.datosCambiados(); }
    this.leyenda({});
  }

  alternarIndicador(id) {
    if (this.activos.has(id)) this.activos.delete(id); else this.activos.add(id);
    // RSI y MACD comparten el panel inferior: solo uno a la vez.
    if (this.activos.has(id) && INDICADORES[id].panel) {
      for (const otro of ["rsi", "macd"]) if (otro !== id) this.activos.delete(otro);
    }
    this.pintarIndicadores();
  }

  pintarIndicadores() {
    for (const lista of Object.values(this.series)) lista.forEach((s) => this.chart.removeSeries(s));
    this.series = {};
    this.seriesPanel.forEach((s) => this.sub.removeSeries(s));
    this.seriesPanel = [];
    const v = this.velas, cierres = v.map((b) => b.close);
    const linea = (id, valores, opciones = {}) => {
      const s = this.chart.addLineSeries({
        color: INDICADORES[id].color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false,
        crosshairMarkerVisible: false, ...opciones,
      });
      s.setData(aLinea(v, valores));
      (this.series[id] ||= []).push(s);
    };
    for (const id of this.activos) {
      if (id.startsWith("sma")) linea(id, sma(cierres, +id.slice(3)));
      else if (id.startsWith("ema")) linea(id, ema(cierres, +id.slice(3)));
      else if (id === "boll") {
        const b = bollinger(cierres, 20, 2);
        linea(id, b.media, { lineWidth: 1, lineStyle: 2 });
        linea(id, b.alta, { lineWidth: 1 });
        linea(id, b.baja, { lineWidth: 1 });
      }
    }
    const conPanel = this.activos.has("rsi") || this.activos.has("macd");
    this.elPanel.classList.toggle("visible", conPanel);
    if (conPanel) {
      const linPanel = (valores, color, ancho = 2) => {
        const s = this.sub.addLineSeries({ color, lineWidth: ancho, priceLineVisible: false, lastValueVisible: true });
        s.setData(aLinea(v, valores));
        this.seriesPanel.push(s);
        return s;
      };
      if (this.activos.has("rsi")) {
        const s = linPanel(rsi(cierres, 14), INDICADORES.rsi.color);
        for (const nivel of [70, 30]) s.createPriceLine({ price: nivel, color: COL.eje, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "" });
      } else {
        const m = macd(cierres);
        const h = this.sub.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false });
        h.setData(v.map((b, i) => (m.hist[i] === null ? { time: b.time } : {
          time: b.time, value: m.hist[i], color: m.hist[i] >= 0 ? "rgba(38,198,176,.5)" : "rgba(255,106,85,.5)",
        })));
        this.seriesPanel.push(h);
        linPanel(m.linea, INDICADORES.macd.color);
        linPanel(m.senal, COL.acento);
      }
      const rango = this.chart.timeScale().getVisibleLogicalRange();
      if (rango) requestAnimationFrame(() => this.sub.timeScale().setVisibleLogicalRange(rango));
    }
    this.leyenda({});
  }

  fijarPrecioMedio(precio) {
    this.precioMedio = precio;
    this.aplicarPrecioMedio();
  }

  aplicarPrecioMedio() {
    if (this.lineaMedia) this.serie.removePriceLine(this.lineaMedia);
    this.lineaMedia = this.precioMedio ? this.serie.createPriceLine({
      price: this.precioMedio, color: COL.acento, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "Mi entrada",
    }) : null;
  }

  fijarMarcadores(lista) {
    this.marcadores = lista;
    this.aplicarMarcadores();
  }

  aplicarMarcadores() {
    const t = this.velas.map((b) => b.time);
    if (!t.length) return;
    const salida = [];
    for (const m of this.marcadores) {
      if (m.tiempo < t[0]) continue;
      let lo = 0, hi = t.length - 1;  // última vela que empieza antes de la noticia
      while (lo < hi) { const c = (lo + hi + 1) >> 1; if (t[c] <= m.tiempo) lo = c; else hi = c - 1; }
      salida.push({
        id: m.id, time: t[lo],
        position: m.buy >= 55 ? "belowBar" : m.buy <= 45 ? "aboveBar" : "inBar",
        shape: m.buy >= 55 ? "arrowUp" : m.buy <= 45 ? "arrowDown" : "circle",
        color: m.buy >= 55 ? COL.sube : m.buy <= 45 ? COL.baja : COL.texto,
      });
    }
    this.serie.setMarkers(salida.sort((a, b) => a.time - b.time));
  }

  leyenda(p) {
    const vela = p.time ? this.velas.find((b) => b.time === p.time) : this.velas.at(-1);
    this.ev.alLeyenda?.(vela, [...this.activos].map((id) => INDICADORES[id]));
  }

  ajustar() { this.chart.timeScale().fitContent(); }

  escalaLog(activa) { this.chart.priceScale("right").applyOptions({ mode: activa ? 1 : 0 }); }
}

/* ---------- Capa de dibujo ---------- */

class CapaDibujo {
  constructor(g) {
    this.g = g;
    this.canvas = document.getElementById("capa-dibujo");
    this.ctx = this.canvas.getContext("2d");
    this.envoltura = g.el.parentElement;
    this.dibujos = [];
    this.herramienta = "cursor";
    this.borrador = null;
    this.seleccion = null;
    this.iman = false;
    this.ocultos = false;
    this.estilo = { color: COL.acento, grosor: 2, trazo: 0 };
    this.deshacer = [];
    this.rehacer = [];
    this.tiempos = [];
    this.paso = 60;
    this.W = this.H = 0;
    this.x0 = 0; this.esp = 1;
    this.sucio = true;

    const w = this.envoltura;
    w.addEventListener("mousedown", (e) => this.alBajar(e), true);
    window.addEventListener("mousemove", (e) => this.alMover(e), true);
    window.addEventListener("mouseup", (e) => this.alSubir(e), true);
    w.addEventListener("dblclick", (e) => this.alDobleClic(e), true);
    window.addEventListener("keydown", (e) => this.alTeclado(e));
    requestAnimationFrame(() => this.bucle());
  }

  /* --- Conversión tiempo/precio <-> píxel --- */

  datosCambiados() {
    const t = this.g.velas.map((b) => b.time);
    this.tiempos = t;
    const difs = t.slice(1).map((x, i) => x - t[i]).sort((a, b) => a - b);
    this.paso = difs[difs.length >> 1] || 60;
    this.sucio = true;
  }

  indiceDe(t) {
    const a = this.tiempos, n = a.length;
    if (!n) return 0;
    if (t <= a[0]) return (t - a[0]) / this.paso;
    if (t >= a[n - 1]) return n - 1 + (t - a[n - 1]) / this.paso;
    let lo = 0, hi = n - 1;
    while (hi - lo > 1) { const c = (lo + hi) >> 1; if (a[c] <= t) lo = c; else hi = c; }
    return lo + (t - a[lo]) / (a[hi] - a[lo]);
  }

  tiempoDe(i) {
    const a = this.tiempos, n = a.length;
    if (!n) return 0;
    if (i <= 0) return a[0] + i * this.paso;
    if (i >= n - 1) return a[n - 1] + (i - n + 1) * this.paso;
    const f = Math.floor(i);
    return a[f] + (i - f) * (a[f + 1] - a[f]);
  }

  xDe(t) { return this.x0 + this.indiceDe(t) * this.esp; }
  yDe(p) { return this.g.serie.priceToCoordinate(p) ?? -9999; }
  punto(q) { return { x: this.xDe(q.t), y: this.yDe(q.p) }; }

  aDato(x, y) {
    const i = (x - this.x0) / this.esp;
    let p = this.g.serie.coordinateToPrice(y);
    let t = this.tiempoDe(i);
    if (this.iman && !this.borradorLibre()) {
      const r = Math.round(i);
      const b = this.g.velas[Math.max(0, Math.min(this.g.velas.length - 1, r))];
      if (b) {
        t = b.time;
        p = [b.open, b.high, b.low, b.close].reduce((m, v) => (Math.abs(v - p) < Math.abs(m - p) ? v : m));
      }
    }
    return { t, p };
  }

  borradorLibre() { return this.herramienta === "pincel"; }

  posicion(e) {
    const r = this.canvas.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  }

  dentro(q) { return q.x >= 0 && q.y >= 0 && q.x <= this.W && q.y <= this.H; }

  /* --- Geometría: cada dibujo se reduce a primitivas, que sirven para pintar y para acertar con el ratón --- */

  extender(a, b) {
    const dx = b.x - a.x, dy = b.y - a.y, largo = Math.hypot(dx, dy) || 1;
    const k = (this.W + this.H) * 2 / largo;
    return { x: b.x + dx * k, y: b.y + dy * k };
  }

  texto(x, y, s, opciones = {}) { return { k: "texto", x, y, s, ...opciones }; }

  primitivas(d) {
    const pts = d.puntos.map((q) => this.punto(q));
    const [a, b, c] = pts;
    const color = d.color, sal = [];
    const seg = (p, q, o = {}) => sal.push({ k: "seg", a: p, b: q, color, ...o });
    const fmt = (v) => v.toLocaleString("es-ES", { minimumFractionDigits: decimales(v), maximumFractionDigits: decimales(v) });

    switch (d.tipo) {
      case "tendencia": if (b) seg(a, b); break;
      case "rayo": if (b) seg(a, this.extender(a, b)); break;
      case "extendida": if (b) seg(this.extender(b, a), this.extender(a, b)); break;
      case "flecha":
        if (b) {
          seg(a, b);
          const ang = Math.atan2(b.y - a.y, b.x - a.x), l = 12;
          for (const giro of [2.6, -2.6]) seg(b, { x: b.x + Math.cos(ang + giro) * l, y: b.y + Math.sin(ang + giro) * l });
        }
        break;
      case "horizontal":
        seg({ x: 0, y: a.y }, { x: this.W, y: a.y });
        sal.push(this.texto(this.W - 6, a.y - 6, fmt(d.puntos[0].p), { alinear: "right", color }));
        break;
      case "vertical": seg({ x: a.x, y: 0 }, { x: a.x, y: this.H }); break;
      case "rect":
        if (b) sal.push({ k: "rect", x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), w: Math.abs(b.x - a.x), h: Math.abs(b.y - a.y), color, relleno: color + "22" });
        break;
      case "elipse":
        if (b) sal.push({ k: "elipse", cx: (a.x + b.x) / 2, cy: (a.y + b.y) / 2, rx: Math.abs(b.x - a.x) / 2, ry: Math.abs(b.y - a.y) / 2, color, relleno: color + "22" });
        break;
      case "canal":
        if (b) {
          seg(a, b);
          if (c) {
            const pend = (b.y - a.y) / ((b.x - a.x) || 1), dy = c.y - (a.y + (c.x - a.x) * pend);
            const a2 = { x: a.x, y: a.y + dy }, b2 = { x: b.x, y: b.y + dy };
            seg(a2, b2);
            seg({ x: a.x, y: a.y + dy / 2 }, { x: b.x, y: b.y + dy / 2 }, { trazo: 1, ancho: 1 });
            sal.push({ k: "poli", pts: [a, b, b2, a2], relleno: color + "18" });
          }
        }
        break;
      case "tridente":
        if (b) {
          seg(a, b);
          if (c) {
            seg(b, c, { trazo: 1, ancho: 1 });
            const m = { x: (b.x + c.x) / 2, y: (b.y + c.y) / 2 };
            const dir = { x: m.x - a.x, y: m.y - a.y };
            for (const o of [m, b, c]) seg(o, this.extender(o, { x: o.x + dir.x, y: o.y + dir.y }));
          }
        }
        break;
      case "fibo":
        if (b) {
          const [q0, q1] = d.puntos, izq = Math.min(a.x, b.x), der = Math.max(a.x, b.x);
          NIVELES_FIBO.forEach((nivel, i) => {
            const precio = q1.p + (q0.p - q1.p) * nivel, y = this.yDe(precio);
            seg({ x: izq, y }, { x: der, y }, { ancho: 1 });
            sal.push(this.texto(izq + 4, y - 4, `${nivel}  ${fmt(precio)}`, { color }));
            if (i + 1 < NIVELES_FIBO.length) {
              const y2 = this.yDe(q1.p + (q0.p - q1.p) * NIVELES_FIBO[i + 1]);
              sal.push({ k: "rect", x: izq, y: Math.min(y, y2), w: der - izq, h: Math.abs(y2 - y), relleno: color + (i % 2 ? "10" : "1c"), sinBorde: true });
            }
          });
        }
        break;
      case "medir":
        if (b) {
          const [q0, q1] = d.puntos, dif = q1.p - q0.p, tono = dif >= 0 ? COL.sube : COL.baja;
          sal.push({ k: "rect", x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), w: Math.abs(b.x - a.x), h: Math.abs(b.y - a.y), color: tono, relleno: tono + "26" });
          const barras = Math.round(this.indiceDe(q1.t) - this.indiceDe(q0.t));
          const signo = dif >= 0 ? "+" : "";
          sal.push(this.texto((a.x + b.x) / 2, Math.min(a.y, b.y) - 8, `${signo}${fmt(dif)}  (${signo}${(dif / q0.p * 100).toFixed(2)} %)  ·  ${barras} velas`, { alinear: "center", color: "#e6ebe8", fondo: tono + "cc" }));
        }
        break;
      case "largo":
      case "corto":
        if (b) {
          const [q0, q1, q2] = d.puntos;
          const entrada = q0.p, objetivo = q1.p, stop = q2 ? q2.p : 2 * entrada - objetivo;
          const yS = this.yDe(stop), izq = Math.min(a.x, b.x), ancho = Math.abs(b.x - a.x);
          sal.push({ k: "rect", x: izq, y: Math.min(a.y, b.y), w: ancho, h: Math.abs(b.y - a.y), relleno: "#26c6b033", color: COL.sube });
          sal.push({ k: "rect", x: izq, y: Math.min(a.y, yS), w: ancho, h: Math.abs(yS - a.y), relleno: "#ff6a5533", color: COL.baja });
          const pct = (v) => `${v >= entrada ? "+" : ""}${((v / entrada - 1) * 100).toFixed(2)} %`;
          const ratio = Math.abs(objetivo - entrada) / (Math.abs(stop - entrada) || 1);
          sal.push(this.texto(izq + ancho / 2, b.y + (b.y < a.y ? -7 : 15), `Objetivo ${fmt(objetivo)}  ${pct(objetivo)}`, { alinear: "center", color: "#e6ebe8" }));
          sal.push(this.texto(izq + ancho / 2, yS + (yS < a.y ? -7 : 15), `Stop ${fmt(stop)}  ${pct(stop)}`, { alinear: "center", color: "#e6ebe8" }));
          sal.push(this.texto(izq + ancho / 2, a.y + 4, `Riesgo/beneficio ${ratio.toFixed(2)}`, { alinear: "center", color: "#e6ebe8", fondo: "#101413cc" }));
        }
        break;
      case "pincel": sal.push({ k: "traza", pts, color }); break;
      case "texto": sal.push(this.texto(a.x, a.y, d.texto || "", { color, cuerpo: 14, acertable: true })); break;
    }
    return sal;
  }

  anclas(d) {
    if (d.tipo === "pincel") return [];
    const pts = d.puntos.map((q) => this.punto(q));
    if (d.tipo === "horizontal") return [{ x: this.W / 2, y: pts[0].y }];
    if (d.tipo === "vertical") return [{ x: pts[0].x, y: this.H / 2 }];
    if (d.tipo === "texto") return [];
    return pts;
  }

  /* --- Pintado --- */

  bucle() {
    requestAnimationFrame(() => this.bucle());
    const { chart, serie } = this.g;
    const ts = chart.timeScale();
    const W = Math.max(0, this.g.el.clientWidth - chart.priceScale("right").width());
    const H = Math.max(0, this.g.el.clientHeight - ts.height());
    const x0 = ts.logicalToCoordinate(0), x1 = ts.logicalToCoordinate(1);
    if (x0 === null || x1 === null) return;
    const ref = this.g.velas.at(-1)?.close;
    const firma = [W, H, x0, x1, ref ? serie.priceToCoordinate(ref) : 0, ref ? serie.priceToCoordinate(ref * 1.05) : 0].join();
    if (firma === this.firma && !this.sucio) return;
    this.firma = firma;
    this.sucio = false;
    this.x0 = x0;
    this.esp = (x1 - x0) || 1;
    if (W !== this.W || H !== this.H) {
      const r = devicePixelRatio || 1;
      this.W = W; this.H = H;
      this.canvas.width = W * r; this.canvas.height = H * r;
      this.canvas.style.width = W + "px"; this.canvas.style.height = H + "px";
      this.ctx.setTransform(r, 0, 0, r, 0, 0);
    }
    this.pintar();
  }

  pintar() {
    const c = this.ctx;
    c.clearRect(0, 0, this.W, this.H);
    if (this.ocultos) return;
    const lista = this.borrador ? [...this.dibujos, this.borrador] : this.dibujos;
    for (const d of lista) {
      if (d.puntos.length) this.primitivas(d).forEach((p) => this.pintarPrimitiva(p, d));
    }
    const sel = this.borrador || this.seleccionado();
    if (sel) {
      for (const q of this.anclas(sel)) {
        c.beginPath();
        c.arc(q.x, q.y, 5, 0, Math.PI * 2);
        c.fillStyle = COL.fondo;
        c.strokeStyle = sel.color;
        c.lineWidth = 2;
        c.setLineDash([]);
        c.fill();
        c.stroke();
      }
    }
  }

  pintarPrimitiva(p, d) {
    const c = this.ctx;
    const trazo = p.trazo ?? d.trazo ?? 0;
    c.setLineDash(trazo === 1 ? [7, 5] : trazo === 2 ? [2, 4] : []);
    c.lineWidth = p.ancho ?? d.grosor ?? 2;
    c.strokeStyle = p.color || d.color;
    c.lineCap = "round";
    switch (p.k) {
      case "seg":
        c.beginPath(); c.moveTo(p.a.x, p.a.y); c.lineTo(p.b.x, p.b.y); c.stroke();
        break;
      case "rect":
        if (p.relleno) { c.fillStyle = p.relleno; c.fillRect(p.x, p.y, p.w, p.h); }
        if (!p.sinBorde) c.strokeRect(p.x, p.y, p.w, p.h);
        break;
      case "elipse":
        c.beginPath(); c.ellipse(p.cx, p.cy, p.rx, p.ry, 0, 0, Math.PI * 2);
        c.fillStyle = p.relleno; c.fill(); c.stroke();
        break;
      case "poli":
        c.beginPath();
        p.pts.forEach((q, i) => (i ? c.lineTo(q.x, q.y) : c.moveTo(q.x, q.y)));
        c.closePath(); c.fillStyle = p.relleno; c.fill();
        break;
      case "traza":
        c.beginPath(); c.lineJoin = "round";
        p.pts.forEach((q, i) => (i ? c.lineTo(q.x, q.y) : c.moveTo(q.x, q.y)));
        c.stroke();
        break;
      case "texto": {
        c.font = `${p.cuerpo || 11}px "IBM Plex Mono", Consolas, monospace`;
        c.textAlign = p.alinear || "left";
        c.textBaseline = "alphabetic";
        if (p.fondo) {
          const w = c.measureText(p.s).width + 12, x = p.alinear === "center" ? p.x - w / 2 : p.x - 6;
          c.fillStyle = p.fondo;
          c.fillRect(x, p.y - 13, w, 18);
        }
        c.fillStyle = p.color || d.color;
        c.fillText(p.s, p.x, p.y);
        break;
      }
    }
  }

  /* --- Acierto con el ratón --- */

  distSeg(q, a, b) {
    const dx = b.x - a.x, dy = b.y - a.y, l = dx * dx + dy * dy;
    const t = l ? Math.max(0, Math.min(1, ((q.x - a.x) * dx + (q.y - a.y) * dy) / l)) : 0;
    return Math.hypot(q.x - a.x - t * dx, q.y - a.y - t * dy);
  }

  acierto(q) {
    if (this.ocultos) return null;
    const sel = this.seleccionado();
    if (sel) {
      const i = this.anclas(sel).findIndex((a) => Math.hypot(a.x - q.x, a.y - q.y) < 9);
      if (i >= 0) return { dibujo: sel, ancla: i };
    }
    for (const d of [...this.dibujos].reverse()) {
      for (const p of this.primitivas(d)) {
        if (this.tocaPrimitiva(q, p)) {
          const i = this.anclas(d).findIndex((a) => Math.hypot(a.x - q.x, a.y - q.y) < 9);
          return { dibujo: d, ancla: i >= 0 && d === sel ? i : -1 };
        }
      }
    }
    return null;
  }

  tocaPrimitiva(q, p) {
    if (p.k === "seg") return this.distSeg(q, p.a, p.b) < 6;
    if (p.k === "rect") {
      const dentro = q.x >= p.x && q.x <= p.x + p.w && q.y >= p.y && q.y <= p.y + p.h;
      return dentro;
    }
    if (p.k === "elipse") {
      if (!p.rx || !p.ry) return false;
      return ((q.x - p.cx) / p.rx) ** 2 + ((q.y - p.cy) / p.ry) ** 2 <= 1;
    }
    if (p.k === "traza") return p.pts.some((a, i) => i && this.distSeg(q, p.pts[i - 1], a) < 6);
    if (p.k === "texto" && p.acertable) {
      this.ctx.font = `${p.cuerpo}px "IBM Plex Mono", Consolas, monospace`;
      const w = this.ctx.measureText(p.s).width;
      return q.x >= p.x - 3 && q.x <= p.x + w + 3 && q.y >= p.y - p.cuerpo - 2 && q.y <= p.y + 4;
    }
    return false;
  }

  /* --- Interacción --- */

  seleccionado() { return this.dibujos.find((d) => d.id === this.seleccion) || null; }

  seleccionar(id) {
    this.seleccion = id;
    this.sucio = true;
    const d = this.seleccionado();
    if (d) Object.assign(this.estilo, { color: d.color, grosor: d.grosor, trazo: d.trazo });
    this.g.ev.alSeleccion?.(d, this.herramienta);
  }

  usarHerramienta(id) {
    this.herramienta = id;
    this.borrador = null;
    this.seleccionar(null);
    this.envoltura.classList.toggle("dibujando", id !== "cursor");
    this.g.ev.alHerramienta?.(id);
    this.sucio = true;
  }

  nuevo(tipo, puntos) {
    return { id: crypto.randomUUID(), tipo, puntos, color: this.estilo.color, grosor: this.estilo.grosor, trazo: this.estilo.trazo };
  }

  alBajar(e) {
    // La barra de opciones y el editor de texto viven sobre la gráfica pero no son gráfica.
    if (e.button !== 0 || e.target.closest(".opciones-dibujo, .editor-texto")) return;
    if (this.editor) { this.editor.blur(); return; }
    const q = this.posicion(e);
    if (!this.dentro(q)) return;
    if (this.herramienta === "cursor") {
      const a = this.acierto(q);
      if (!a) { this.seleccionar(null); return; }
      e.stopPropagation(); e.preventDefault();
      this.seleccionar(a.dibujo.id);
      this.arrastre = { ...a, inicio: q, base: a.dibujo.puntos.map((p) => this.punto(p)), estado: JSON.stringify(this.dibujos), movido: false };
      return;
    }
    e.stopPropagation(); e.preventDefault();
    const dato = this.aDato(q.x, q.y), cfg = HERRAMIENTAS[this.herramienta];
    if (this.herramienta === "pincel") { this.borrador = this.nuevo("pincel", [dato]); this.trazando = true; return; }
    if (this.herramienta === "texto") { this.pedirTexto(q, dato); return; }
    if (!this.borrador) {
      this.borrador = this.nuevo(this.herramienta, [dato]);
      if (cfg.puntos === 1) return this.confirmar();
      this.borrador.puntos.push({ ...dato });
      this.inicioBorrador = q;
      return;
    }
    this.borrador.puntos[this.borrador.puntos.length - 1] = dato;
    if (this.borrador.puntos.length >= cfg.puntos) return this.confirmar();
    this.borrador.puntos.push({ ...dato });
  }

  alMover(e) {
    const q = this.posicion(e);
    if (this.arrastre) {
      e.stopPropagation();
      this.moverArrastre(q);
      return;
    }
    if (this.trazando) {
      e.stopPropagation();
      this.borrador.puntos.push(this.aDato(q.x, q.y));
      this.sucio = true;
      return;
    }
    if (this.borrador) {
      this.borrador.puntos[this.borrador.puntos.length - 1] = this.aDato(q.x, q.y);
      this.sucio = true;
      return;
    }
    if (this.herramienta === "cursor" && e.target.closest?.("#grafica-envoltura")) {
      this.envoltura.classList.toggle("sobre-dibujo", this.dentro(q) && !!this.acierto(q));
    }
  }

  alSubir(e) {
    if (this.arrastre) {
      e.stopPropagation();
      if (this.arrastre.movido) { this.apuntar(this.arrastre.estado); this.persistir(); }
      this.arrastre = null;
      return;
    }
    if (this.trazando) {
      this.trazando = false;
      this.confirmar();
      return;
    }
    // Arrastrar y soltar también dibuja: no hace falta un segundo clic.
    if (this.borrador && this.inicioBorrador && HERRAMIENTAS[this.borrador.tipo].puntos === 2) {
      const q = this.posicion(e);
      if (Math.hypot(q.x - this.inicioBorrador.x, q.y - this.inicioBorrador.y) > 8) this.confirmar();
    }
    this.inicioBorrador = null;
  }

  moverArrastre(q) {
    const a = this.arrastre, d = a.dibujo;
    const dx = q.x - a.inicio.x, dy = q.y - a.inicio.y;
    if (!a.movido && Math.hypot(dx, dy) < 3) return;
    a.movido = true;
    if (a.ancla >= 0) {
      const p = this.aDato(q.x, q.y);
      if (d.tipo === "horizontal") d.puntos[0].p = p.p;
      else if (d.tipo === "vertical") d.puntos[0].t = p.t;
      else if ((d.tipo === "largo" || d.tipo === "corto") && a.ancla === 2) d.puntos[2].p = p.p;
      else {
        d.puntos[a.ancla] = p;
        if ((d.tipo === "largo" || d.tipo === "corto") && a.ancla === 1) d.puntos[2].t = p.t;
      }
    } else {
      d.puntos = a.base.map((b, i) => {
        const r = this.aDatoSinIman(b.x + dx, b.y + dy);
        if (d.tipo === "horizontal") return { t: d.puntos[i].t, p: r.p };
        if (d.tipo === "vertical") return { t: r.t, p: d.puntos[i].p };
        return r;
      });
    }
    this.sucio = true;
  }

  aDatoSinIman(x, y) {
    const iman = this.iman;
    this.iman = false;
    const r = this.aDato(x, y);
    this.iman = iman;
    return r;
  }

  confirmar() {
    const d = this.borrador;
    this.borrador = null;
    this.inicioBorrador = null;
    if (d.tipo === "largo" || d.tipo === "corto") {
      const [q0, q1] = d.puntos;
      // Una larga tiene el objetivo arriba y una corta abajo, aunque se dibuje al revés.
      const arriba = q1.p > q0.p;
      if ((d.tipo === "largo") !== arriba) q1.p = 2 * q0.p - q1.p;
      d.puntos[2] = { t: q1.t, p: 2 * q0.p - q1.p };
    }
    this.apuntar();
    this.dibujos.push(d);
    this.persistir();
    if (this.herramienta !== "cursor") this.usarHerramienta("cursor");
    this.seleccionar(d.tipo === "pincel" ? null : d.id);
  }

  alDobleClic(e) {
    const q = this.posicion(e);
    if (this.herramienta !== "cursor" || !this.dentro(q)) return;
    const a = this.acierto(q);
    if (a?.dibujo.tipo === "texto") { e.stopPropagation(); this.pedirTexto(q, null, a.dibujo); }
  }

  alTeclado(e) {
    if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || "")) return;
    if (!this.g.el.offsetParent) return;  // la gráfica no está a la vista
    if (e.key === "Escape") {
      if (this.borrador || this.herramienta !== "cursor") this.usarHerramienta("cursor");
      else this.seleccionar(null);
    } else if ((e.key === "Delete" || e.key === "Backspace") && this.seleccion) {
      e.preventDefault();
      this.borrarSeleccion();
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
      e.preventDefault();
      this.deshacerUno();
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") {
      e.preventDefault();
      this.rehacerUno();
    }
  }

  pedirTexto(q, dato, existente) {
    const caja = document.createElement("input");
    caja.className = "editor-texto";
    caja.placeholder = "Escribe y pulsa Enter";
    caja.value = existente?.texto || "";
    caja.style.left = q.x + "px";
    caja.style.top = q.y - 14 + "px";
    this.envoltura.append(caja);
    this.editor = caja;
    setTimeout(() => caja.focus());
    let terminado = false;
    const cerrar = (guardar) => {
      if (terminado) return;
      terminado = true;
      const valor = caja.value.trim();
      caja.remove();
      this.editor = null;
      if (guardar && valor) {
        if (existente) { this.apuntar(); existente.texto = valor; this.persistir(); }
        else { const d = this.nuevo("texto", [dato]); d.texto = valor; this.borrador = d; this.confirmar(); return; }
      }
      if (this.herramienta !== "cursor") this.usarHerramienta("cursor");
      this.sucio = true;
    };
    caja.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "Enter") cerrar(true);
      if (e.key === "Escape") cerrar(false);
    });
    caja.addEventListener("blur", () => cerrar(true));
  }

  /* --- Estilo, historial y guardado --- */

  aplicarEstilo(cambios) {
    Object.assign(this.estilo, cambios);
    const d = this.seleccionado();
    if (d) { this.apuntar(); Object.assign(d, cambios); this.persistir(); }
    this.sucio = true;
  }

  apuntar(estado) {
    this.deshacer.push(estado ?? JSON.stringify(this.dibujos));
    if (this.deshacer.length > 80) this.deshacer.shift();
    this.rehacer = [];
  }

  deshacerUno() {
    if (!this.deshacer.length) return;
    this.rehacer.push(JSON.stringify(this.dibujos));
    this.dibujos = JSON.parse(this.deshacer.pop());
    this.seleccionar(null);
    this.persistir();
  }

  rehacerUno() {
    if (!this.rehacer.length) return;
    this.deshacer.push(JSON.stringify(this.dibujos));
    this.dibujos = JSON.parse(this.rehacer.pop());
    this.seleccionar(null);
    this.persistir();
  }

  borrarSeleccion() {
    this.apuntar();
    this.dibujos = this.dibujos.filter((d) => d.id !== this.seleccion);
    this.seleccionar(null);
    this.persistir();
  }

  borrarTodo() {
    if (!this.dibujos.length) return;
    this.apuntar();
    this.dibujos = [];
    this.seleccionar(null);
    this.persistir();
  }

  alternarOcultos() { this.ocultos = !this.ocultos; this.sucio = true; return this.ocultos; }

  cargar(simbolo, dibujos) {
    this.simbolo = simbolo;
    this.dibujos = dibujos;
    this.deshacer = [];
    this.rehacer = [];
    this.borrador = null;
    this.seleccionar(null);
    this.sucio = true;
  }

  persistir() {
    this.sucio = true;
    const simbolo = this.simbolo, contenido = JSON.stringify(this.dibujos);
    clearTimeout(this.temporizador);
    this.temporizador = setTimeout(() => this.g.ev.alGuardar?.(simbolo, contenido), 350);
  }
}

window.Grafica = Grafica;
window.HERRAMIENTAS = HERRAMIENTAS;
window.INDICADORES = INDICADORES;
window.decimalesPrecio = decimales;
