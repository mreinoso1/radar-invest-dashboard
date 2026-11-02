"use strict";
/* Radar: lógica de la interfaz. Todo el texto de feeds y del agente es de terceros:
   se inserta siempre escapado con esc() y los enlaces pasan por enlaceSeguro(). */

const $ = (id) => document.getElementById(id);
const S = {
  vista: null,
  simbolo: null,
  intervalo: "1d",
  cfg: null,
  cartera: { filas: [], moneda: "EUR" },
  feed: { noticia: [], social: [] },
  filtro: { noticia: { activo: null, modo: "analizadas" }, social: { activo: null, modo: "todas" } },
  edicion: null,
  sugerida: null,
  paneles: [],
  activo: 0,
  disposicion: "1",
};

const INTERVALOS = ["1m", "5m", "15m", "1h", "4h", "1d", "1w", "1M"];
const ETIQUETAS_INT = { "1m": "1m", "5m": "5m", "15m": "15m", "1h": "1H", "4h": "4H", "1d": "D", "1w": "S", "1M": "M" };
const CATEGORIAS = {
  macro: "Macro", banco_central: "Banco central", resultados: "Resultados", empresa: "Empresa", sector: "Sector",
  regulacion: "Regulación", geopolitica: "Geopolítica", materias_primas: "Materias primas", cripto: "Cripto", sentimiento: "Sentimiento",
};
const COLORES = ["#f2b33d", "#26c6b0", "#ff6a55", "#6aa8ff", "#c58bf2", "#e6ebe8"];
const ICONOS = {
  cursor: '<path d="M5 3.5 18 11l-6 1.6L9.2 18.5z"/>',
  tendencia: '<path d="M4 17 16 5"/><circle cx="4" cy="17" r="1.4"/><circle cx="16" cy="5" r="1.4"/>',
  rayo: '<path d="M4 17 19 3"/><circle cx="4" cy="17" r="1.4"/>',
  extendida: '<path d="M2 18 18 2"/><circle cx="7" cy="13" r="1.4"/><circle cx="13" cy="7" r="1.4"/>',
  horizontal: '<path d="M1.5 10h17"/><circle cx="10" cy="10" r="1.4"/>',
  vertical: '<path d="M10 1.5v17"/><circle cx="10" cy="10" r="1.4"/>',
  canal: '<path d="M2 12 14 3M6 18l12-9"/>',
  tridente: '<path d="M3 10h6M9 10l9-6M9 10h10M9 10l9 6M9 10V4M9 10v6"/>',
  fibo: '<path d="M2 4h16M2 8h16M2 12h16M2 16h16"/>',
  rect: '<rect x="3" y="5" width="14" height="10" rx="1"/>',
  elipse: '<ellipse cx="10" cy="10" rx="8" ry="5.5"/>',
  flecha: '<path d="M4 16 16 4M8 4h8v8"/>',
  pincel: '<path d="M3 15c3-7 5 2 8-3s3-7 6-8"/>',
  texto: '<path d="M4 5V3.5h12V5M10 3.5v13M7.5 16.5h5"/>',
  medir: '<path d="M10 2v16M6 6l4-4 4 4M6 14l4 4 4-4"/>',
  largo: '<path d="M3 11h14M3 3h14v8H3z" /><path d="M3 11v6h14v-6" opacity=".45"/>',
  corto: '<path d="M3 9h14M3 9v8h14V9" /><path d="M3 9V3h14v6" opacity=".45"/>',
  iman: '<path d="M4 4v6a6 6 0 0 0 12 0V4h-4v6a2 2 0 0 1-4 0V4zM4 7h4M12 7h4"/>',
  ojo: '<path d="M1.5 10S5 4.5 10 4.5 18.5 10 18.5 10 15 15.5 10 15.5 1.5 10 1.5 10z"/><circle cx="10" cy="10" r="2.4"/>',
  deshacer: '<path d="M7 5 3.5 8.5 7 12"/><path d="M3.5 8.5H12a4.5 4.5 0 0 1 0 9H8"/>',
  rehacer: '<path d="m13 5 3.5 3.5L13 12"/><path d="M16.5 8.5H8a4.5 4.5 0 0 0 0 9h4"/>',
  papelera: '<path d="M3.5 5.5h13M8 5.5V3.5h4v2M5 5.5l1 11.5h8l1-11.5M8.5 8.5v5.5M11.5 8.5v5.5"/>',
};

/* ---------- Utilidades ---------- */

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const enlaceSeguro = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");

function numero(v, dec = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toLocaleString("es-ES", { minimumFractionDigits: dec, maximumFractionDigits: dec });
}
const precioTxt = (v, minimo = 0) => numero(v, Math.max(minimo, decimalesPrecio(v)));
const dinero = (v, m) => `${numero(v)} ${m || ""}`.trim();
const pct = (v) => (v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${numero(v)} %`);
const claseVar = (v) => (v === null || v === undefined || v === 0 ? "neutro" : v > 0 ? "sube" : "baja");
const flecha = (v) => (v > 0 ? "▲" : v < 0 ? "▼" : "");

function hace(ts) {
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "ahora";
  if (s < 3600) return `hace ${Math.floor(s / 60)} min`;
  if (s < 86400) return `hace ${Math.floor(s / 3600)} h`;
  return `hace ${Math.floor(s / 86400)} d`;
}

async function api(ruta, opciones) {
  const r = await fetch(ruta, opciones);
  const datos = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(datos.error || `Error ${r.status}`);
  return datos;
}
const enviar = (ruta, cuerpo, metodo = "POST") => api(ruta, {
  method: metodo, headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo ?? {}),
});
const leerLocal = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } };
const guardarLocal = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* sin almacenamiento */ } };

function estado(tipo, texto, error = false) {
  const el = $(`estado-${tipo}`);
  if (!el) return;
  el.textContent = texto;
  el.classList.toggle("error", error);
}

/* ---------- Navegación ---------- */

function irA(vista) {
  if (!["mercado", "cartera", "noticias", "social", "ajustes"].includes(vista)) vista = "mercado";
  S.vista = vista;
  document.querySelectorAll(".vista-texto").forEach((v) => { v.hidden = v.id !== `v-${vista}`; });
  $("v-mercado").classList.toggle("en-reposo", vista !== "mercado");
  document.querySelectorAll(".rail a").forEach((a) => {
    if (a.dataset.vista === vista) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  if (vista === "cartera") pintarCartera();
  if (vista === "noticias") pintarFeed("noticia");
  if (vista === "social") { pintarFeed("social"); cargarSentimiento(); }
  if (vista === "ajustes") pintarAjustes();
}
window.addEventListener("hashchange", () => irA(location.hash.slice(1)));

function abrirActivo(simbolo) {
  location.hash = "mercado";
  cambiarSimbolo(simbolo);
}

/* ---------- Búsqueda ---------- */

function autocompletar(entrada, caja, alElegir) {
  let turno = 0, temporizador;
  const cerrar = () => { caja.hidden = true; };
  entrada.addEventListener("input", () => {
    clearTimeout(temporizador);
    const q = entrada.value.trim();
    if (!q) return cerrar();
    temporizador = setTimeout(async () => {
      const mio = ++turno;
      const lista = await api(`/api/buscar?q=${encodeURIComponent(q)}`).catch(() => []);
      if (mio !== turno) return;
      caja.innerHTML = lista.length ? "" : '<button type="button" disabled><span>Sin resultados</span></button>';
      lista.forEach((r) => {
        const b = document.createElement("button");
        b.type = "button";
        b.innerHTML = `<b>${esc(r.simbolo)}</b><span>${esc(r.nombre)}</span><i>${esc(r.tipo)} · ${esc(r.bolsa)}</i>`;
        b.addEventListener("mousedown", (e) => { e.preventDefault(); cerrar(); alElegir(r); });
        caja.append(b);
      });
      caja.hidden = false;
    }, 220);
  });
  entrada.addEventListener("keydown", (e) => {
    const botones = [...caja.querySelectorAll("button:not(:disabled)")];
    if (e.key === "Enter") {
      if (!caja.hidden && botones.length) {
        e.preventDefault();
        (caja.querySelector("button.activa") || botones[0]).dispatchEvent(new MouseEvent("mousedown"));
      }
    } else if (e.key === "Escape") cerrar();
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const i = botones.findIndex((b) => b.classList.contains("activa"));
      botones[i]?.classList.remove("activa");
      const n = (i + (e.key === "ArrowDown" ? 1 : -1) + botones.length) % botones.length;
      botones[n]?.classList.add("activa");
    }
  });
  entrada.addEventListener("blur", () => setTimeout(cerrar, 120));
}

/* ---------- Mercado ---------- */

/* Cada panel tiene su activo, temporalidad, indicadores y dibujos. La barra de herramientas
   y la cabecera son únicas y actúan sobre el panel activo, cuya gráfica es siempre `g`. */
let g;
const panelActivo = () => S.paneles[S.activo];
const DISPOSICIONES = {
  1: { n: 1, nombre: "Una gráfica", icono: '<rect x=".7" y=".7" width="14.6" height="11.6" rx="1"/>' },
  "2h": { n: 2, nombre: "Dos, lado a lado", icono: '<rect x=".7" y=".7" width="14.6" height="11.6" rx="1"/><path d="M8 .7v11.6"/>' },
  "2v": { n: 2, nombre: "Dos, una sobre otra", icono: '<rect x=".7" y=".7" width="14.6" height="11.6" rx="1"/><path d="M.7 6.5h14.6"/>' },
  4: { n: 4, nombre: "Cuatro", icono: '<rect x=".7" y=".7" width="14.6" height="11.6" rx="1"/><path d="M8 .7v11.6M.7 6.5h14.6"/>' },
};

function crearPanel(cfg) {
  const el = document.createElement("div");
  el.className = "panel-grafica";
  el.innerHTML = `<div class="grafica-envoltura"><div class="grafica"></div><canvas class="capa-dibujo" aria-hidden="true"></canvas>
    <div class="leyenda"></div><div class="grafica-aviso" hidden></div></div><div class="panel-inferior"></div>`;
  $("paneles").append(el);
  const q = (s) => el.querySelector(s);
  const p = { el, simbolo: cfg.simbolo, intervalo: cfg.intervalo, log: !!cfg.log, info: null };
  p.g = new Grafica(q(".grafica"), q(".panel-inferior"), {
    alLeyenda: (vela, indicadores) => pintarLeyenda(p, vela, indicadores),
    alHerramienta: () => { if (p === panelActivo()) pintarHerramientas(); },
    alSeleccion: () => { if (p === panelActivo()) pintarOpcionesDibujo(); },
    alGuardar: (simbolo, contenido) => {
      // Dos paneles con el mismo activo comparten dibujos: sin esto, el otro los pisaría al guardar.
      for (const o of S.paneles) if (o !== p && o.simbolo === simbolo) o.g.dibujo.recibir(JSON.parse(contenido));
      api(`/api/dibujos?s=${encodeURIComponent(simbolo)}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: contenido,
      }).catch(() => {});
    },
    alMarcador: (id) => verNoticia(id),
    esActiva: () => p === panelActivo(),
  }, q(".capa-dibujo"));
  p.g.activos = new Set(cfg.indicadores || []);
  p.g.tipo = cfg.tipo || "velas";
  p.g.crearSerie();
  p.g.escalaLog(p.log);
  el.addEventListener("mousedown", () => activarPanel(p), true);
  return p;
}

function guardarPaneles() {
  guardarLocal("radar.paneles", {
    disposicion: S.disposicion, activo: S.activo,
    lista: S.paneles.map((p) => ({ simbolo: p.simbolo, intervalo: p.intervalo, tipo: p.g.tipo, indicadores: [...p.g.activos], log: p.log })),
  });
}

function pintarControles() {
  document.querySelectorAll("#intervalos button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.i === S.intervalo));
  document.querySelectorAll("#disposicion button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.d === S.disposicion));
  document.querySelectorAll("#lista-indicadores input").forEach((c) => { c.checked = g.activos.has(c.dataset.id); });
  $("tipo-grafica").value = g.tipo;
  $("b-log").setAttribute("aria-pressed", panelActivo().log);
  document.querySelector('#herramientas [data-id="iman"]')?.setAttribute("aria-pressed", g.dibujo.iman);
  document.querySelector('#herramientas [data-id="ojo"]')?.setAttribute("aria-pressed", g.dibujo.ocultos);
  pintarHerramientas();
}

function marcarActivo(p) {
  S.activo = S.paneles.indexOf(p);
  g = p.g;
  S.simbolo = p.simbolo;
  S.intervalo = p.intervalo;
  S.paneles.forEach((x) => x.el.classList.toggle("activo", x === p));
}

function activarPanel(p) {
  const previo = panelActivo();
  if (previo === p) return;
  const herramienta = previo?.g.dibujo.herramienta;
  if (herramienta && herramienta !== "cursor") previo.g.dibujo.usarHerramienta("cursor");
  marcarActivo(p);
  if (herramienta && herramienta !== "cursor") g.dibujo.usarHerramienta(herramienta);  // se dibuja donde se hace clic
  pintarControles();
  if (p.info) pintarCabeceraGrafica(p.info);
  $("g-var").textContent = "";
  refrescarVariacion();
  pintarListaActivos();
  pintarNoticiasActivo();
  abrirAnalista(p.simbolo);
  guardarPaneles();
}

function siguienteSimbolo() {
  const usados = new Set(S.paneles.map((p) => p.simbolo));
  return S.cartera.filas.find((f) => !usados.has(f.simbolo))?.simbolo || S.simbolo;
}

function ponerDisposicion(id) {
  S.disposicion = id;
  $("paneles").dataset.disposicion = id;
  const n = DISPOSICIONES[id].n;
  while (S.paneles.length > n) {
    const p = S.paneles.pop();
    p.g.destruir();
    p.el.remove();
  }
  if (S.activo >= n) activarPanel(S.paneles[0]);
  while (S.paneles.length < n) {
    const a = panelActivo();
    const p = crearPanel({ simbolo: siguienteSimbolo(), intervalo: a.intervalo, tipo: a.g.tipo });
    S.paneles.push(p);
    cambiarSimbolo(p.simbolo, p);
  }
  S.paneles.forEach((p) => p.g.leyenda({}));
  pintarControles();
  guardarPaneles();
}

function iniciarGrafica() {
  const guardado = leerLocal("radar.paneles", null);
  const inicial = {
    simbolo: leerLocal("radar.simbolo", null) || S.cartera.filas[0]?.simbolo || "SPY",
    intervalo: leerLocal("radar.intervalo", "1d"), tipo: leerLocal("radar.tipo", "velas"), indicadores: leerLocal("radar.indicadores", []),
  };
  const lista = guardado?.lista?.length ? guardado.lista : [inicial];
  S.disposicion = DISPOSICIONES[guardado?.disposicion] ? guardado.disposicion : "1";
  $("paneles").dataset.disposicion = S.disposicion;
  S.paneles = lista.slice(0, DISPOSICIONES[S.disposicion].n).map(crearPanel);
  marcarActivo(S.paneles[Math.min(guardado?.activo || 0, S.paneles.length - 1)]);

  const icono = (id) => `<svg viewBox="0 0 20 20">${ICONOS[id]}</svg>`;
  const caja = $("herramientas");
  const boton = (id, titulo, accion, atributos = "") => {
    const b = document.createElement("button");
    b.innerHTML = icono(id);
    b.title = titulo;
    b.setAttribute("aria-label", titulo);
    b.dataset.id = id;
    if (atributos) b.dataset.tipo = atributos;
    b.addEventListener("click", accion);
    caja.append(b);
    return b;
  };
  const separador = () => caja.append(document.createElement("hr"));
  boton("cursor", "Cursor (Esc)", () => g.dibujo.usarHerramienta("cursor"), "herramienta");
  separador();
  for (const [id, h] of Object.entries(HERRAMIENTAS)) {
    boton(id, h.nombre, () => g.dibujo.usarHerramienta(g.dibujo.herramienta === id ? "cursor" : id), "herramienta");
    if (["vertical", "fibo", "texto"].includes(id)) separador();
  }
  separador();
  boton("iman", "Imán: pega los puntos a la vela", () => {
    g.dibujo.iman = !g.dibujo.iman;
    pintarControles();
  });
  const ojo = boton("ojo", "Ocultar o mostrar dibujos", () => ojo.setAttribute("aria-pressed", g.dibujo.alternarOcultos()));
  boton("deshacer", "Deshacer (Ctrl+Z)", () => g.dibujo.deshacerUno());
  boton("rehacer", "Rehacer (Ctrl+Y)", () => g.dibujo.rehacerUno());
  boton("papelera", "Borrar todos los dibujos de este activo", () => {
    if (g.dibujo.dibujos.length && confirm(`¿Borrar todos los dibujos de ${S.simbolo}?`)) g.dibujo.borrarTodo();
  });

  const intervalos = $("intervalos");
  INTERVALOS.forEach((i) => {
    const b = document.createElement("button");
    b.textContent = ETIQUETAS_INT[i];
    b.dataset.i = i;
    b.addEventListener("click", () => cambiarIntervalo(i));
    intervalos.append(b);
  });

  for (const [id, d] of Object.entries(DISPOSICIONES)) {
    const b = document.createElement("button");
    b.innerHTML = `<svg viewBox="0 0 16 13" aria-hidden="true">${d.icono}</svg>`;
    b.dataset.d = id;
    b.title = d.nombre;
    b.setAttribute("aria-label", d.nombre);
    b.addEventListener("click", () => ponerDisposicion(id));
    $("disposicion").append(b);
  }

  const indicadores = $("lista-indicadores");
  for (const [id, ind] of Object.entries(INDICADORES)) {
    const l = document.createElement("label");
    l.innerHTML = `<input type="checkbox" data-id="${id}"> ${ind.nombre}<i style="background:${ind.color}"></i>`;
    indicadores.append(l);
  }
  indicadores.addEventListener("change", (e) => {
    g.alternarIndicador(e.target.dataset.id);
    pintarControles();
    guardarPaneles();
  });
  document.addEventListener("click", (e) => { if (!$("menu-indicadores").contains(e.target)) $("menu-indicadores").open = false; });

  $("tipo-grafica").addEventListener("change", (e) => { g.cambiarTipo(e.target.value); guardarPaneles(); });
  $("b-ajustar").addEventListener("click", () => g.ajustar());
  $("b-log").addEventListener("click", () => {
    const p = panelActivo();
    p.log = !p.log;
    g.escalaLog(p.log);
    pintarControles();
    guardarPaneles();
  });
  $("b-tv").addEventListener("click", alternarTradingView);
  $("b-lateral").addEventListener("click", (e) => {
    e.currentTarget.setAttribute("aria-pressed", $("lateral").classList.toggle("abierta"));
  });

  COLORES.forEach((c) => {
    const b = document.createElement("button");
    b.style.background = c;
    b.dataset.c = c;
    b.setAttribute("aria-label", `Color ${c}`);
    b.addEventListener("click", () => { g.dibujo.aplicarEstilo({ color: c }); pintarOpcionesDibujo(); });
    $("colores").append(b);
  });
  [1, 2, 3].forEach((n) => {
    const b = document.createElement("button");
    b.textContent = n;
    b.dataset.n = n;
    b.setAttribute("aria-label", `Grosor ${n}`);
    b.addEventListener("click", () => { g.dibujo.aplicarEstilo({ grosor: n }); pintarOpcionesDibujo(); });
    $("grosores").append(b);
  });
  [["—", 0, "Continua"], ["- -", 1, "Discontinua"], ["···", 2, "Punteada"]].forEach(([t, n, nombre]) => {
    const b = document.createElement("button");
    b.textContent = t;
    b.dataset.n = n;
    b.setAttribute("aria-label", nombre);
    b.addEventListener("click", () => { g.dibujo.aplicarEstilo({ trazo: n }); pintarOpcionesDibujo(); });
    $("trazos").append(b);
  });
  $("b-borrar-dibujo").addEventListener("click", () => g.dibujo.borrarSeleccion());
  pintarControles();
}

function pintarHerramientas() {
  document.querySelectorAll('#herramientas [data-tipo="herramienta"]').forEach((b) => {
    b.setAttribute("aria-pressed", b.dataset.id === g.dibujo.herramienta);
  });
  pintarOpcionesDibujo();
}

function pintarOpcionesDibujo() {
  const d = g.dibujo;
  $("opciones-dibujo").hidden = !d.seleccion && d.herramienta === "cursor";
  $("b-borrar-dibujo").hidden = !d.seleccion;
  document.querySelectorAll("#colores button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.c === d.estilo.color));
  document.querySelectorAll("#grosores button").forEach((b) => b.setAttribute("aria-pressed", +b.dataset.n === d.estilo.grosor));
  document.querySelectorAll("#trazos button").forEach((b) => b.setAttribute("aria-pressed", +b.dataset.n === d.estilo.trazo));
}

function pintarLeyenda(p, vela, indicadores) {
  const leyenda = p.el.querySelector(".leyenda");
  if (!vela) { leyenda.innerHTML = ""; return; }
  const dif = vela.close - vela.open, tono = claseVar(dif);
  const dato = (e, v) => `<span><em>${e}</em><span class="${tono}">${precioTxt(v, p.info?.decimales)}</span></span>`;
  const nombre = S.paneles.length > 1 ? `<div class="panel-nombre"><b>${esc(p.simbolo)}</b><span>${ETIQUETAS_INT[p.intervalo]}</span></div>` : "";
  leyenda.innerHTML = `${nombre}<div>${dato("A", vela.open)}${dato("M", vela.high)}${dato("B", vela.low)}${dato("C", vela.close)}
    <span><em>Vol</em>${numero(vela.volume, 0)}</span></div>
    ${indicadores.length ? `<div>${indicadores.map((i) => `<span><i style="background:${i.color}"></i>${i.nombre}</span>`).join("")}</div>` : ""}`;
}

async function cargarGrafica(p = panelActivo()) {
  const { simbolo, intervalo } = p;
  const aviso = p.el.querySelector(".grafica-aviso");
  aviso.hidden = true;
  try {
    const info = await api(`/api/velas?s=${encodeURIComponent(simbolo)}&i=${intervalo}`);
    if (simbolo !== p.simbolo || intervalo !== p.intervalo) return;
    if (!info.velas.length) throw new Error("Yahoo no tiene datos para esta temporalidad.");
    p.info = info;
    p.g.ponerDatos(info, intervalo);
    p.g.irAlFinal();
    if (p === panelActivo()) pintarCabeceraGrafica(info);
  } catch (e) {
    aviso.textContent = e.message;
    aviso.hidden = false;
  }
}

function pintarCabeceraGrafica(info) {
  $("g-simbolo").textContent = S.simbolo;
  $("g-nombre").textContent = `${info.nombre}${info.bolsa ? " · " + info.bolsa : ""}`;
  $("g-precio").textContent = `${precioTxt(info.precio, info.decimales)} ${info.moneda}`;
  document.title = `${S.simbolo} ${precioTxt(info.precio, info.decimales)} · Radar`;
}

async function cambiarSimbolo(simbolo, p = panelActivo()) {
  p.simbolo = simbolo;
  const activo = p === panelActivo();
  if (activo) {
    S.simbolo = simbolo;
    $("g-simbolo").textContent = simbolo;
    $("g-var").textContent = "";
    pintarListaActivos();
    abrirAnalista(simbolo);
  }
  guardarPaneles();
  const dibujos = await api(`/api/dibujos?s=${encodeURIComponent(simbolo)}`).catch(() => []);
  if (simbolo !== p.simbolo) return;
  p.g.dibujo.cargar(simbolo, dibujos);
  const pos = S.cartera.filas.find((f) => f.simbolo === simbolo);
  p.g.fijarPrecioMedio(pos?.cantidad > 0 ? pos.precio_medio : null);
  actualizarMarcadores();
  if (p === panelActivo()) pintarNoticiasActivo();
  await cargarGrafica(p);
  if (p === panelActivo()) {
    refrescarVariacion();
    if (!$("tv").hidden) montarTradingView();
  }
}

function cambiarIntervalo(i) {
  const p = panelActivo();
  S.intervalo = p.intervalo = i;
  guardarPaneles();
  pintarControles();
  p.g.leyenda({});
  cargarGrafica(p);
  if (!$("tv").hidden) montarTradingView();
}

async function refrescarVariacion() {
  const [c] = await api(`/api/cotizaciones?s=${encodeURIComponent(S.simbolo)}`).catch(() => [null]);
  if (!c || c.simbolo !== S.simbolo) return;
  const el = $("g-var");
  el.textContent = `${flecha(c.var_dia)} ${pct(c.var_dia)}`;
  el.className = `num ${claseVar(c.var_dia)}`;
}

function refrescarCola() {
  if (S.vista !== "mercado" || document.hidden) return;
  S.paneles.forEach(async (p) => {
    if (!p.g.velas.length) return;
    const { simbolo, intervalo } = p;
    const info = await api(`/api/velas?s=${encodeURIComponent(simbolo)}&i=${intervalo}&corto=1`).catch(() => null);
    if (!info || simbolo !== p.simbolo || intervalo !== p.intervalo || !info.velas.length) return;
    p.g.actualizarCola(info);
    if (p === panelActivo()) pintarCabeceraGrafica(info);
  });
}

/* Widget oficial de TradingView: todas sus herramientas, pero sus dibujos no se guardan en Radar. */
function simboloTV(s) {
  if (s.endsWith("-USD")) return `COINBASE:${s.replace("-", "")}`;
  const bolsas = { MC: "BME", DE: "XETR", PA: "EURONEXT", AS: "EURONEXT", L: "LSE", MI: "MIL", SW: "SIX", T: "TSE", HK: "HKEX" };
  const [base, sufijo] = s.split(".");
  return sufijo && bolsas[sufijo] ? `${bolsas[sufijo]}:${base}` : base;
}

function cargarScript(url) {
  return new Promise((ok, mal) => {
    if (window.TradingView) return ok();
    const s = document.createElement("script");
    s.src = url; s.onload = ok; s.onerror = () => mal(new Error("No se pudo cargar TradingView"));
    document.head.append(s);
  });
}

async function montarTradingView() {
  const caja = $("tv");
  caja.innerHTML = '<div id="tv-contenedor"></div>';
  await cargarScript("https://s3.tradingview.com/tv.js");
  const intervalos = { "1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D", "1w": "W", "1M": "M" };
  new TradingView.widget({
    container_id: "tv-contenedor", autosize: true, symbol: simboloTV(S.simbolo), interval: intervalos[S.intervalo],
    timezone: "Europe/Madrid", theme: "dark", style: "1", locale: "es", allow_symbol_change: true,
    hide_side_toolbar: false, withdateranges: true, details: false, save_image: true,
  });
}

function alternarTradingView() {
  const caja = $("tv"), abrir = caja.hidden;
  caja.hidden = !abrir;
  $("b-tv").setAttribute("aria-pressed", abrir);
  $("herramientas").style.visibility = abrir ? "hidden" : "";
  if (abrir) montarTradingView().catch((e) => { caja.innerHTML = `<div class="grafica-aviso">${esc(e.message)}</div>`; });
  else caja.innerHTML = "";
}

function pintarListaActivos() {
  const caja = $("lista-activos");
  if (!S.cartera.filas.length) {
    caja.innerHTML = '<p class="vacio-mini">Añade tus inversiones en <a href="#cartera">Cartera</a> para verlas aquí.</p>';
    return;
  }
  caja.innerHTML = S.cartera.filas.map((f) => `
    <button class="fila-activo ${f.simbolo === S.simbolo ? "activa" : ""}" data-s="${esc(f.simbolo)}">
      <b>${esc(f.simbolo)}</b><span class="num">${precioTxt(f.precio)}</span>
      <small>${esc(f.nombre)}</small><small class="num ${claseVar(f.var_dia)}">${flecha(f.var_dia)} ${pct(f.var_dia)}</small>
    </button>`).join("");
}
$("lista-activos").addEventListener("click", (e) => {
  const b = e.target.closest("[data-s]");
  if (b) cambiarSimbolo(b.dataset.s);
});

function afecta(item, simbolo) {
  return item.analisis?.impactos.find((i) => i.simbolo === simbolo);
}

function pintarNoticiasActivo() {
  $("lateral-noticias-titulo").textContent = `Noticias de ${S.simbolo}`;
  const relacionadas = S.feed.noticia
    .filter((n) => (n.analisis ? n.analisis.relevante && afecta(n, S.simbolo) : n.simbolos.includes(S.simbolo)))
    .sort((a, b) => !!b.analisis - !!a.analisis || b.fecha - a.fecha)
    .slice(0, 30);
  const caja = $("lista-noticias-activo");
  if (!relacionadas.length) { caja.innerHTML = '<p class="vacio-mini">Sin noticias relacionadas todavía.</p>'; return; }
  caja.innerHTML = relacionadas.map((n) => {
    const imp = afecta(n, S.simbolo);
    const senal = imp ? `<span class="num ${imp.direccion === "sube" ? "sube" : imp.direccion === "baja" ? "baja" : "neutro"}">${imp.direccion === "baja" ? `SHORT ${imp.short_pct}%` : `BUY ${imp.buy_pct}%`}</span>` : "<span>sin analizar</span>";
    return `<button class="mini-noticia" data-id="${esc(n.id)}">${esc(n.analisis?.titulo || n.titulo)}<small><span>${esc(n.fuente)} · ${hace(n.fecha)}</span>${senal}</small></button>`;
  }).join("");
}
$("lista-noticias-activo").addEventListener("click", (e) => {
  const b = e.target.closest("[data-id]");
  if (b) verNoticia(b.dataset.id);
});

function verNoticia(id) {
  S.resaltada = id;
  const f = S.filtro.noticia;
  f.activo = null;
  f.modo = "todas";
  location.hash = "noticias";
  if (S.vista === "noticias") pintarFeed("noticia");
  document.querySelector(`[data-tarjeta="${CSS.escape(id)}"]`)?.scrollIntoView({ block: "center" });
}

function actualizarMarcadores() {
  for (const p of S.paneles) {
    const lista = [];
    for (const n of S.feed.noticia) {
      const imp = afecta(n, p.simbolo);
      if (n.analisis?.relevante && imp && n.analisis.importancia >= 3) lista.push({ id: n.id, tiempo: n.fecha, buy: imp.buy_pct });
    }
    p.g.fijarMarcadores(lista);
  }
}

/* ---------- Analista ---------- */

const PREGUNTAS = ["¿Qué lo ha movido esta semana?", "¿Qué riesgos tiene ahora mismo?", "¿Cómo encaja en mi cartera?"];
let turnoAnalista = 0, temporizadorResumen;

function verPestana(id) {
  for (const t of ["analista", "noticias"]) {
    $(`t-${t}`).setAttribute("aria-selected", t === id);
    $(`p-${t}`).hidden = t !== id;
  }
}
$("t-analista").addEventListener("click", () => verPestana("analista"));
$("t-noticias").addEventListener("click", () => verPestana("noticias"));

async function abrirAnalista(simbolo) {
  const turno = ++turnoAnalista;
  clearTimeout(temporizadorResumen);
  $("an-ficha").innerHTML = '<p class="nota">Cargando datos…</p>';
  $("an-resumen").innerHTML = "";
  $("an-chat").innerHTML = "";
  let f;
  try {
    f = await api(`/api/ficha?s=${encodeURIComponent(simbolo)}`);
  } catch (e) {
    if (turno === turnoAnalista) $("an-ficha").innerHTML = `<p class="nota">${esc(e.message)}</p>`;
    return;
  }
  if (turno !== turnoAnalista) return;
  pintarFicha(f);
  pintarResumen(f.resumen);
  pintarChat(f.chat);
  // Espera un poco: quien va pasando por varios activos no debe gastar un resumen en cada uno.
  if (f.resumen_viejo && S.cfg.resumen_auto && S.cfg.agente_listo) temporizadorResumen = setTimeout(() => generarResumen(simbolo), 1500);
}

function pintarFicha(f) {
  const celdas = Object.entries(f.rendimientos).map(([nombre, v]) => `<div><span>${esc(nombre)}</span><b class="${claseVar(v)}">${pct(v)}</b></div>`).join("");
  const filas = [["Precio", `${precioTxt(f.precio)} ${esc(f.moneda)}`]];
  if (f.posicion) {
    const v = f.posicion.precio_medio ? (f.precio / f.posicion.precio_medio - 1) * 100 : null;
    filas.push(["Tu posición", `${numero(f.posicion.cantidad, f.posicion.cantidad % 1 ? 4 : 0)} a ${precioTxt(f.posicion.precio_medio)} · <span class="${claseVar(v)}">${pct(v)}</span>`]);
  }
  filas.push(["Desde el máximo de 1 año", pct(f.desde_maximo)]);
  if (f.rsi !== null) filas.push(["RSI 14", numero(f.rsi, 0)]);
  if (f.sma200) filas.push(["Frente a su media de 200", pct((f.precio / f.sma200 - 1) * 100)]);
  if (f.volatilidad !== null) filas.push(["Volatilidad anual", `${numero(f.volatilidad, 0)} %`]);
  const c = f.consenso;
  if (c?.objetivo_medio) {
    filas.push([`Objetivo medio de ${c.analistas || "los"} analistas`, `${precioTxt(c.objetivo_medio)} · ${pct((c.objetivo_medio / f.precio - 1) * 100)}`]);
    if (c.objetivo_bajo && c.objetivo_alto) filas.push(["Rango de objetivos", `${precioTxt(c.objetivo_bajo)} a ${precioTxt(c.objetivo_alto)}`]);
  }
  if (c?.proximos_resultados) filas.push(["Próximos resultados", new Date(c.proximos_resultados * 1000).toLocaleDateString("es-ES", { day: "numeric", month: "short", year: "numeric" })]);
  // Los valores de `filas` llevan marcado propio: lo que viene de fuera ya va escapado arriba.
  $("an-ficha").innerHTML = `<div class="rendimientos">${celdas}</div>
    <ul class="datos-activo">${filas.map(([e, v]) => `<li><span>${esc(e)}</span><span>${v}</span></li>`).join("")}</ul>`;
}

function pintarResumen(r) {
  const caja = $("an-resumen");
  if (!r) {
    caja.innerHTML = `<div class="resumen"><p>${S.cfg.agente_listo ? "Aún no hay resumen de este activo." : "Conecta tu cuenta de Claude en Ajustes para ver el resumen."}</p>
      ${S.cfg.agente_listo ? '<button class="enlace" data-resumen>Generar resumen</button>' : ""}</div>`;
    return;
  }
  const vigilar = r.a_vigilar.length ? `<ul>${r.a_vigilar.map((v) => `<li>${esc(v)}</li>`).join("")}</ul>` : "";
  caja.innerHTML = `<div class="resumen"><h3>${esc(r.titular)}</h3>
    <p>${esc(r.como_ha_ido)}</p><p>${esc(r.motivos)}</p>
    <p><b>Qué se espera:</b> ${esc(r.que_se_espera)}</p>
    ${vigilar ? `<p><b>A vigilar:</b></p>${vigilar}` : ""}
    <div class="resumen-pie"><span>Generado ${hace(r.creado)}. No es asesoramiento financiero.</span><button class="enlace" data-resumen>Actualizar</button></div></div>`;
}

async function generarResumen(simbolo, forzar = false) {
  const turno = turnoAnalista;
  const previo = $("an-resumen").innerHTML;
  $("an-resumen").innerHTML = '<div class="resumen"><p class="pensando">El analista está preparando el resumen…</p></div>';
  try {
    const r = await enviar("/api/resumen", { simbolo, forzar });
    if (turno === turnoAnalista) pintarResumen(r);
  } catch (e) {
    if (turno !== turnoAnalista) return;
    $("an-resumen").innerHTML = previo;
    $("an-resumen").insertAdjacentHTML("beforeend", `<p class="nota">${esc(e.message)}</p>`);
  }
}
$("an-resumen").addEventListener("click", (e) => {
  if (e.target.closest("[data-resumen]")) generarResumen(S.simbolo, true);
});

function mensajeHTML(rol, texto, clase = "") {
  return `<div class="mensaje ${rol} ${clase}">${esc(texto)}</div>`;
}

function pintarChat(lista) {
  S.chat = lista;
  const sugerencias = S.cfg.agente_listo ? `<div class="chat-sugerencias">${PREGUNTAS.map((p) => `<button class="chip" data-pregunta="${esc(p)}">${esc(p)}</button>`).join("")}</div>` : "";
  $("an-chat").innerHTML = lista.length
    ? `<div class="chat-cab"><h2>Conversación</h2><button class="enlace" data-borrar-chat>Borrar</button></div>${lista.map((m) => mensajeHTML(m.rol, m.texto)).join("")}`
    : sugerencias;
  $("an-form").hidden = !S.cfg.agente_listo;
  bajarChat();
}

function bajarChat() {
  const c = $("an-cuerpo");
  c.scrollTop = c.scrollHeight;
}

async function preguntar(texto) {
  const simbolo = S.simbolo, turno = turnoAnalista, caja = $("an-chat");
  caja.querySelector(".chat-sugerencias")?.remove();
  caja.insertAdjacentHTML("beforeend", mensajeHTML("usuario", texto) + mensajeHTML("agente", "Pensando…", "pensando"));
  bajarChat();
  $("an-enviar").disabled = true;
  try {
    const r = await enviar("/api/chat", { simbolo, texto });
    if (turno === turnoAnalista) pintarChat([...S.chat, { rol: "usuario", texto }, { rol: "agente", texto: r.texto }]);
  } catch (e) {
    if (turno !== turnoAnalista) return;
    caja.querySelector(".pensando")?.remove();
    caja.insertAdjacentHTML("beforeend", mensajeHTML("agente", e.message, "error"));
    bajarChat();
  } finally {
    $("an-enviar").disabled = false;
  }
}

$("an-chat").addEventListener("click", async (e) => {
  const s = e.target.closest("[data-pregunta]");
  if (s) preguntar(s.dataset.pregunta);
  if (e.target.closest("[data-borrar-chat]") && confirm(`¿Borrar la conversación sobre ${S.simbolo}?`)) {
    await api(`/api/chat?s=${encodeURIComponent(S.simbolo)}`, { method: "DELETE" });
    pintarChat([]);
  }
});
$("an-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const caja = $("an-texto"), texto = caja.value.trim();
  if (!texto || $("an-enviar").disabled) return;
  caja.value = "";
  caja.style.height = "";
  preguntar(texto);
});
$("an-texto").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("an-form").requestSubmit(); }
});
$("an-texto").addEventListener("input", (e) => {
  e.target.style.height = "";
  e.target.style.height = `${e.target.scrollHeight + 2}px`;
});

/* ---------- Índices y cartera ---------- */

async function refrescarIndices() {
  if (document.hidden) return;
  const lista = await api("/api/indices").catch(() => null);
  if (!lista) return;
  $("indices").innerHTML = lista.map((i) => `<div><span>${esc(i.nombre)}</span><b class="num ${claseVar(i.var_dia)}">${flecha(i.var_dia)} ${pct(i.var_dia)}</b></div>`).join("");
}

async function refrescarCartera() {
  const c = await api("/api/cartera").catch(() => null);
  if (!c) return;
  S.cartera = c;
  pintarListaActivos();
  if (S.vista === "cartera") pintarCartera();
}

function pintarCartera() {
  const c = S.cartera, m = c.moneda, hay = c.filas.length > 0;
  const pctGan = c.coste ? c.ganancia / c.coste * 100 : null;
  const previo = c.valor - c.dia;
  $("cartera-aviso").textContent = c.avisos?.join(" · ") || "Precios de Yahoo Finance, pueden llevar retraso.";
  $("metricas").innerHTML = hay ? `
    <div class="metrica"><span>Valor total</span><b>${dinero(c.valor, m)}</b><small>Invertido ${dinero(c.coste, m)}</small></div>
    <div class="metrica"><span>Ganancia total</span><b class="${claseVar(c.ganancia)}">${flecha(c.ganancia)} ${dinero(c.ganancia, m)}</b><small class="${claseVar(c.ganancia)}">${pct(pctGan)}</small></div>
    <div class="metrica"><span>Hoy</span><b class="${claseVar(c.dia)}">${flecha(c.dia)} ${dinero(c.dia, m)}</b><small class="${claseVar(c.dia)}">${pct(previo ? c.dia / previo * 100 : null)}</small></div>` : "";
  $("cartera-vacia").hidden = hay;
  $("tabla-cartera").hidden = !hay;
  if (!hay) return;
  const ordenadas = [...c.filas].sort((a, b) => b.valor - a.valor);
  $("tabla-cartera").innerHTML = `<thead><tr><th>Activo</th><th>Cantidad</th><th>Precio medio</th><th>Precio</th><th>Hoy</th><th>5 días</th><th>Valor (${esc(m)})</th><th>Ganancia (${esc(m)})</th><th>Peso</th><th><span hidden>Acciones</span></th></tr></thead>
  <tbody>${ordenadas.map((f) => {
    const ganPct = f.coste && f.ganancia !== null ? f.ganancia / f.coste * 100 : null;
    const s = esc(f.simbolo);
    return `<tr>
      <td><button class="activo" data-abrir="${s}"><b>${s}</b><small>${esc(f.nombre)}</small></button></td>
      <td>${numero(f.cantidad, f.cantidad % 1 ? 4 : 0)}</td>
      <td>${f.cantidad ? `${precioTxt(f.precio_medio)} ${esc(f.moneda)}` : "—"}</td>
      <td>${precioTxt(f.precio)} ${esc(f.moneda)}</td>
      <td class="${claseVar(f.var_dia)}">${flecha(f.var_dia)} ${pct(f.var_dia)}</td>
      <td class="${claseVar(f.var_5d)}">${flecha(f.var_5d)} ${pct(f.var_5d)}</td>
      <td>${f.cantidad ? numero(f.valor) : "—"}</td>
      <td class="${claseVar(f.ganancia)}">${f.cantidad ? `${numero(f.ganancia)} <small>${pct(ganPct)}</small>` : "—"}</td>
      <td><span class="peso"><i><u style="width:${Math.min(100, f.peso).toFixed(1)}%"></u></i>${numero(f.peso, 1)} %</span></td>
      <td><span class="acciones-fila"><button class="enlace" data-editar="${s}">Editar</button><button class="enlace" data-borrar="${s}">Quitar</button></span></td>
    </tr>`;
  }).join("")}</tbody>`;
}

$("tabla-cartera").addEventListener("click", async (e) => {
  const t = e.target.closest("[data-abrir],[data-editar],[data-borrar]");
  if (!t) return;
  if (t.dataset.abrir) abrirActivo(t.dataset.abrir);
  if (t.dataset.editar) empezarEdicion(t.dataset.editar);
  if (t.dataset.borrar && confirm(`¿Quitar ${t.dataset.borrar} de tu cartera?`)) {
    await api(`/api/cartera?s=${encodeURIComponent(t.dataset.borrar)}`, { method: "DELETE" });
    await refrescarCartera();
    pintarCartera();
  }
});

function empezarEdicion(simbolo) {
  const f = S.cartera.filas.find((x) => x.simbolo === simbolo);
  S.edicion = simbolo;
  S.sugerida = { simbolo, nombre: f.nombre, tipo: f.tipo };
  $("f-activo").value = simbolo;
  $("f-activo").disabled = true;
  $("f-cantidad").value = f.cantidad;
  $("f-precio").value = f.precio_medio;
  $("f-enviar").textContent = "Guardar cambios";
  $("f-cancelar").hidden = false;
  $("f-nota").textContent = `Editando ${simbolo}: los valores sustituyen a los actuales.`;
  $("f-cantidad").focus();
}

function limpiarFormulario() {
  S.edicion = null;
  S.sugerida = null;
  $("form-posicion").reset();
  $("f-activo").disabled = false;
  $("f-enviar").textContent = "Añadir";
  $("f-cancelar").hidden = true;
  $("f-nota").textContent = "";
  $("f-moneda").textContent = "";
}

async function elegirActivoFormulario(r) {
  S.sugerida = r;
  $("f-activo").value = `${r.simbolo} · ${r.nombre}`;
  const previa = S.cartera.filas.find((f) => f.simbolo === r.simbolo);
  $("f-nota").textContent = previa
    ? `Ya tienes ${r.simbolo}: la compra se sumará y se recalculará tu precio medio.`
    : "Con cantidad 0 lo sigues sin registrar una compra.";
  const [c] = await api(`/api/cotizaciones?s=${encodeURIComponent(r.simbolo)}`).catch(() => [null]);
  if (c?.precio && S.sugerida === r) {
    $("f-moneda").textContent = c.moneda ? `(${c.moneda})` : "";
    $("f-precio").placeholder = `Actual: ${precioTxt(c.precio)}`;
  }
  $("f-cantidad").focus();
}

$("form-posicion").addEventListener("submit", async (e) => {
  e.preventDefault();
  const s = S.sugerida;
  if (!s) { $("f-nota").textContent = "Elige un activo de la lista de sugerencias."; return; }
  const enviar_btn = $("f-enviar");
  enviar_btn.disabled = true;
  try {
    await enviar("/api/cartera", {
      simbolo: s.simbolo, nombre: s.nombre, tipo: s.tipo,
      cantidad: parseFloat($("f-cantidad").value || "0"),
      precio_medio: parseFloat($("f-precio").value || "0"),
      sumar: !S.edicion,
    });
    limpiarFormulario();
    await refrescarCartera();
    if (!g.dibujo.simbolo || S.simbolo === s.simbolo) cambiarSimbolo(s.simbolo);
    actualizarFeed("noticia", true);
  } catch (err) {
    $("f-nota").textContent = err.message;
  } finally {
    enviar_btn.disabled = false;
  }
});
$("f-cancelar").addEventListener("click", limpiarFormulario);

/* ---------- Noticias y social ---------- */

function barraSenal(buy, short) {
  return `<div class="senal"><span class="b">BUY ${buy}%</span>
    <div class="senal-barra" role="img" aria-label="Buy ${buy} por ciento, short ${short} por ciento"><i style="flex:${Math.max(buy, 1)}"></i><i style="flex:${Math.max(short, 1)}"></i></div>
    <span class="s">SHORT ${short}%</span></div>`;
}

function impactoHTML(i) {
  const texto = { sube: "▲ Sube", baja: "▼ Baja", neutro: "● Incierto" }[i.direccion];
  return `<div class="impacto">
    <div class="impacto-activo"><button data-abrir="${esc(i.simbolo)}">${esc(i.simbolo)}</button><small class="${i.direccion === "neutro" ? "neutro" : i.direccion}">${texto}</small></div>
    <div class="impacto-texto">${esc(i.mecanismo)}<small>Se invalida si: ${esc(i.invalidacion)}</small></div>
    <div class="impacto-datos">${barraSenal(i.buy_pct, i.short_pct)}<small>Impacto ${esc(i.magnitud)} · ${esc(i.horizonte)} · confianza ${i.confianza}%</small></div>
  </div>`;
}

function tarjetaHTML(n) {
  const a = n.analisis;
  const relacionados = a?.relevante ? a.impactos.map((i) => i.simbolo) : n.simbolos;
  const chips = [...new Set(relacionados)].map((s) => `<button class="chip" data-abrir="${esc(s)}">${esc(s)}</button>`).join("");
  const autor = n.autor ? ` · @${esc(n.autor)}` : "";
  const fuente = `${esc(n.fuente)}${autor} · ${hace(n.fecha)}`;
  const url = esc(enlaceSeguro(n.url));
  const reanalizar = `<button class="enlace" data-reanalizar="${esc(n.id)}">${a ? "Reanalizar" : "Analizar"}</button>`;
  const cuerpo = n.tipo === "social" ? n.texto : n.texto.slice(0, 280);
  const social = n.sentimiento ? `<span class="${n.sentimiento === "Bullish" ? "sube" : "baja"}">${n.sentimiento === "Bullish" ? "▲ Alcista" : "▼ Bajista"}</span>` : "";
  const otras = n.otras?.length ? `<p class="otras-fuentes">También en ${n.otras.slice(0, 4).map((o) => `<a href="${esc(enlaceSeguro(o.url))}" target="_blank" rel="noopener noreferrer" title="${esc(o.titulo)}">${esc(o.fuente)}</a>`).join(", ")}${n.otras.length > 4 ? ` y ${n.otras.length - 4} más` : ""}</p>` : "";

  if (!a) {
    return `<article class="tarjeta" data-tarjeta="${esc(n.id)}">
      <div class="tarjeta-cab"><span>${fuente}</span>${social}<span class="derecha">Sin analizar</span></div>
      <h3><a href="${url}" target="_blank" rel="noopener noreferrer">${esc(n.titulo)}</a></h3>
      ${cuerpo && cuerpo !== n.titulo ? `<p>${esc(cuerpo)}</p>` : ""}
      ${otras}
      <div class="tarjeta-pie">${chips}<span class="derecha">${reanalizar}</span></div>
    </article>`;
  }
  const importancia = [1, 2, 3, 4, 5].map((v) => `<i class="${v <= a.importancia ? "on" : ""}"></i>`).join("");
  const global = a.relevante && a.senal_buy !== null
    ? `<div class="senal-global"><small>Señal para tu cartera, ponderada por peso y confianza</small>${barraSenal(a.senal_buy, 100 - a.senal_buy)}</div>` : "";
  return `<article class="tarjeta ${a.relevante ? "" : "descartada"} ${S.resaltada === n.id ? "resaltada" : ""}" data-tarjeta="${esc(n.id)}">
    <div class="tarjeta-cab"><span class="etiqueta">${esc(CATEGORIAS[a.categoria] || a.categoria)}</span>
      <span class="puntos" title="Importancia ${a.importancia} de 5" role="img" aria-label="Importancia ${a.importancia} de 5">${importancia}</span>
      <span>${fuente}</span>${social}${a.relevante ? "" : '<span class="derecha">Descartada por el agente</span>'}</div>
    <h3><a href="${url}" target="_blank" rel="noopener noreferrer">${esc(a.titulo)}</a></h3>
    <p class="original">${esc(n.titulo)}</p>
    <p>${esc(a.resumen)}</p>
    <p class="novedad"><b>Lo nuevo:</b> ${esc(a.novedad)}</p>
    ${otras}
    ${global}
    ${a.impactos.length ? `<div class="impactos">${a.impactos.map(impactoHTML).join("")}</div>` : ""}
    <div class="tarjeta-pie">${chips}<span class="derecha">${reanalizar}</span></div>
  </article>`;
}

function filtrar(tipo) {
  const f = S.filtro[tipo];
  return S.feed[tipo].filter((n) => {
    const a = n.analisis;
    if (f.activo) {
      const toca = a ? a.relevante && afecta(n, f.activo) : n.simbolos.includes(f.activo);
      if (!toca) return false;
    }
    if (f.modo === "analizadas") return a?.relevante;
    if (f.modo === "importantes") return a?.relevante && a.importancia >= 4;
    if (f.modo === "pendientes") return !a;
    if (f.modo === "descartadas") return a && !a.relevante;
    return tipo === "social" ? !a || a.relevante : true;
  });
}

function pintarFiltros(tipo) {
  const f = S.filtro[tipo];
  const modos = tipo === "noticia"
    ? [["analizadas", "Analizadas"], ["importantes", "Importantes"], ["pendientes", "Sin analizar"], ["descartadas", "Descartadas"], ["todas", "Todas"]]
    : [["todas", "Todas"], ["analizadas", "Analizadas"]];
  const chips = S.cartera.filas.map((p) => `<button class="chip" data-activo="${esc(p.simbolo)}" aria-pressed="${f.activo === p.simbolo}">${esc(p.simbolo)}</button>`).join("");
  $(`filtros-${tipo}`).innerHTML = modos.map(([id, t]) => `<button class="chip" data-modo="${id}" aria-pressed="${f.modo === id}">${t}</button>`).join("")
    + (chips ? `<span class="sep"></span>${chips}` : "");
}

function vacioFeed(tipo) {
  const f = S.filtro[tipo];
  if (!S.feed[tipo].length) return "Pulsa Actualizar para traer lo último.";
  if (!S.cfg.agente_listo && f.modo !== "todas" && f.modo !== "pendientes") return 'Conecta tu cuenta de Claude en <a href="#ajustes">Ajustes</a> para activar el análisis. Mientras tanto puedes ver el filtro «Sin analizar».';
  if (!S.cartera.filas.length) return 'Añade tus activos en <a href="#cartera">Cartera</a>: el agente analiza cada noticia sobre ellos.';
  return "Nada con este filtro. Pulsa «Analizar con IA» o prueba otro.";
}

function pintarFeed(tipo) {
  pintarFiltros(tipo);
  const lista = filtrar(tipo).slice(0, 120);
  $(`feed-${tipo}`).innerHTML = lista.length ? lista.map(tarjetaHTML).join("") : `<p class="vacio">${vacioFeed(tipo)}</p>`;
  if (tipo === "noticia") pintarBalance();
  if (tipo === "social") {
    $("nota-social").textContent = S.cfg.tiene_x
      ? "StockTwits, Reddit y X. Son opiniones, no hechos: el agente les da poco peso."
      : "StockTwits y Reddit. Para ver tweets de X añade tu token en Ajustes.";
  }
}

function pintarBalance() {
  const limite = Date.now() / 1000 - 72 * 3600;
  const filas = S.cartera.filas.map((p) => {
    let peso = 0, suma = 0, n = 0;
    for (const item of S.feed.noticia) {
      const imp = afecta(item, p.simbolo);
      if (!imp || !item.analisis.relevante || item.fecha < limite) continue;
      const w = imp.confianza * item.analisis.importancia;
      peso += w; suma += w * imp.buy_pct; n++;
    }
    return { simbolo: p.simbolo, n, buy: peso ? Math.round(suma / peso) : null };
  }).sort((a, b) => b.n - a.n);
  $("balance").innerHTML = filas.length ? filas.map((f) => `
    <button class="balance-fila" data-activo="${esc(f.simbolo)}">
      <div><b>${esc(f.simbolo)}</b><small>${f.n} ${f.n === 1 ? "noticia" : "noticias"}</small></div>
      ${f.buy === null ? '<small class="neutro">Sin noticias analizadas</small>' : barraSenal(f.buy, 100 - f.buy)}
    </button>`).join("") : '<p class="nota">Añade activos a tu cartera.</p>';
}

function alClicFeed(tipo) {
  return async (e) => {
    const t = e.target.closest("[data-abrir],[data-activo],[data-modo],[data-reanalizar]");
    if (!t) return;
    const f = S.filtro[tipo];
    if (t.dataset.abrir) return abrirActivo(t.dataset.abrir);
    if (t.dataset.activo) { f.activo = f.activo === t.dataset.activo ? null : t.dataset.activo; pintarFeed(tipo); }
    if (t.dataset.modo) { f.modo = t.dataset.modo; pintarFeed(tipo); }
    if (t.dataset.reanalizar) lanzarAnalisis(tipo, [t.dataset.reanalizar]);
  };
}
for (const tipo of ["noticia", "social"]) {
  $(`feed-${tipo}`).addEventListener("click", alClicFeed(tipo));
  $(`filtros-${tipo}`).addEventListener("click", alClicFeed(tipo));
  $(`b-act-${tipo}`).addEventListener("click", () => actualizarFeed(tipo, false, true));
  $(`b-ana-${tipo}`).addEventListener("click", () => lanzarAnalisis(tipo));
}
$("balance").addEventListener("click", alClicFeed("noticia"));

async function cargarFeed(tipo) {
  S.feed[tipo] = await api(`/api/feed?tipo=${tipo}`).catch(() => S.feed[tipo]);
  if (S.vista === (tipo === "noticia" ? "noticias" : "social")) pintarFeed(tipo);
  if (tipo === "noticia") { pintarNoticiasActivo(); actualizarMarcadores(); }
}

async function actualizarFeed(tipo, silencioso = false, manual = false) {
  if (!silencioso) estado(tipo, "Actualizando…");
  try {
    const r = await enviar("/api/feed/actualizar", { tipo, incluir_x: manual });
    await cargarFeed(tipo);
    const fallos = r.avisos.length ? ` · ${r.avisos.length} ${r.avisos.length === 1 ? "fuente no respondió" : "fuentes no respondieron"}` : "";
    if (!silencioso) estado(tipo, `${r.nuevos} ${r.nuevos === 1 ? "nueva" : "nuevas"}${fallos}`);
    if (r.nuevos && S.cfg.auto_analizar && S.cfg.agente_listo && tipo === "noticia") lanzarAnalisis(tipo);
  } catch (e) {
    if (!silencioso) estado(tipo, e.message, true);
  }
}

let vigilando = false;

async function lanzarAnalisis(tipo, ids) {
  estado(tipo, "");
  try {
    const r = await enviar("/api/agente", { tipo, ids });
    if (r.error) { estado(tipo, r.error, true); return; }
    vigilarAgente();
  } catch (e) {
    estado(tipo, e.message, true);
  }
}

async function vigilarAgente() {
  if (vigilando) return;
  vigilando = true;
  document.querySelectorAll('[id^="b-ana-"]').forEach((b) => { b.disabled = true; });
  let e;
  do {
    await new Promise((ok) => setTimeout(ok, 1500));
    e = await api("/api/agente").catch(() => e);
    if (e?.activo) {
      estado(e.tipo, `Analizando ${e.hechos} de ${e.total}…`);
      if (e.hechos) await cargarFeed(e.tipo);
    }
  } while (e?.activo);
  vigilando = false;
  document.querySelectorAll('[id^="b-ana-"]').forEach((b) => { b.disabled = false; });
  if (!e) return;
  await cargarFeed(e.tipo);
  S.cfg = await api("/api/ajustes");
  const coste = S.cfg.conexion === "cuenta" ? "con tu plan de Claude" : `≈ ${e.coste.toFixed(3)} $`;
  if (e.error) estado(e.tipo, `${e.error} (${e.hechos} de ${e.total} hechos)`, true);
  else estado(e.tipo, `${e.hechos} analizadas · ${coste}`);
}

async function cargarSentimiento() {
  const datos = await api("/api/social/sentimiento").catch(() => ({}));
  $("sentimiento").innerHTML = Object.entries(datos).map(([s, c]) => {
    const total = c.Bullish + c.Bearish, buy = total ? Math.round(c.Bullish / total * 100) : 50;
    return `<button data-s="${esc(s)}"><b>${esc(s)}<span>${total} ${total === 1 ? "voto" : "votos"} en StockTwits, 3 días</span></b>
      <div class="senal"><span class="b">▲ ${buy}%</span><div class="senal-barra" role="img" aria-label="${buy} por ciento alcista"><i style="flex:${Math.max(buy, 1)}"></i><i style="flex:${Math.max(100 - buy, 1)}"></i></div><span class="s">▼ ${100 - buy}%</span></div></button>`;
  }).join("");
}
$("sentimiento").addEventListener("click", (e) => {
  const b = e.target.closest("[data-s]");
  if (b) { S.filtro.social.activo = b.dataset.s; pintarFeed("social"); }
});

/* ---------- Ajustes ---------- */

function pintarAjustes() {
  const c = S.cfg;
  $("a-conexion").value = c.conexion;
  pintarConexion();
  $("a-modelo").innerHTML = Object.entries(c.modelos).map(([id, m]) => `<option value="${esc(id)}">${esc(m.nombre)} · ${m.entrada} / ${m.salida} $ por millón de tokens en API</option>`).join("");
  $("a-modelo").value = c.modelo;
  $("a-modelo-chat").innerHTML = $("a-modelo").innerHTML;
  $("a-modelo-chat").value = c.modelo_chat;
  $("a-max").value = c.max_analisis;
  $("a-auto").checked = c.auto_analizar;
  $("a-resumen-auto").checked = c.resumen_auto;
  $("a-moneda").value = c.moneda;
  $("a-clave").value = "";
  $("a-x").value = "";
  $("a-clave").placeholder = c.tiene_clave ? "Guardada. Escribe otra para cambiarla" : "sk-ant-…";
  $("a-x").placeholder = c.tiene_x ? "Guardado. Escribe otro para cambiarlo" : "Opcional";
  $("a-clave-estado").textContent = c.tiene_clave ? "● Configurada" : "";
  $("a-x-estado").textContent = c.tiene_x ? "● Configurado" : "";
  $("a-gasto").textContent = `${c.gasto_usd.toFixed(3)} $`;
  $("a-ruta").textContent = `Tus datos están en ${c.datos_en}`;
}

function pintarConexion() {
  const conCuenta = $("a-conexion").value === "cuenta", c = S.cfg.cuenta;
  $("bloque-cuenta").hidden = !conCuenta;
  $("bloque-api").hidden = conCuenta;
  $("a-cuenta-estado").textContent = !c.instalado
    ? "No encuentro Claude Code en este ordenador. Abre la app de Claude una vez o usa una clave de API."
    : c.conectado ? `● Conectado${c.plan ? ` · plan ${c.plan}` : ""}` : "Sin conectar";
  $("b-login").hidden = !c.instalado || c.conectado;
  $("b-comprobar").hidden = !c.instalado || c.conectado;
}

$("a-conexion").addEventListener("change", pintarConexion);
$("b-login").addEventListener("click", async () => {
  try {
    await enviar("/api/cuenta/iniciar");
    $("ajustes-estado").textContent = "Completa el inicio de sesión en la ventana que se ha abierto.";
    $("ajustes-estado").classList.remove("error");
  } catch (err) {
    $("ajustes-estado").textContent = err.message;
    $("ajustes-estado").classList.add("error");
  }
});
$("b-comprobar").addEventListener("click", async () => {
  S.cfg = await api("/api/cuenta");
  pintarAjustes();
  $("ajustes-estado").textContent = S.cfg.cuenta.conectado ? "Cuenta conectada" : "Aún no aparece la sesión iniciada.";
});

$("form-ajustes").addEventListener("submit", async (e) => {
  e.preventDefault();
  const cuerpo = {
    conexion: $("a-conexion").value, modelo: $("a-modelo").value, modelo_chat: $("a-modelo-chat").value,
    max_analisis: $("a-max").value, auto_analizar: $("a-auto").checked, resumen_auto: $("a-resumen-auto").checked,
    moneda: $("a-moneda").value,
  };
  if ($("a-clave").value.trim()) cuerpo.anthropic_key = $("a-clave").value;
  if ($("a-x").value.trim()) cuerpo.x_token = $("a-x").value;
  try {
    S.cfg = await enviar("/api/ajustes", cuerpo);
    pintarAjustes();
    $("ajustes-estado").textContent = "Guardado";
    $("ajustes-estado").classList.remove("error");
    refrescarCartera();
  } catch (err) {
    $("ajustes-estado").textContent = err.message;
    $("ajustes-estado").classList.add("error");
  }
});

/* ---------- Arranque ---------- */

async function arrancar() {
  S.cfg = await api("/api/ajustes");
  if (!S.cfg.agente_listo) S.filtro.noticia.modo = "todas";
  autocompletar($("buscador"), $("sugerencias"), (r) => { $("buscador").value = ""; abrirActivo(r.simbolo); });
  autocompletar($("f-activo"), $("f-sugerencias"), elegirActivoFormulario);
  await refrescarCartera();
  iniciarGrafica();
  irA(location.hash.slice(1) || "mercado");
  S.paneles.forEach((p) => cambiarSimbolo(p.simbolo, p));
  refrescarIndices();
  await cargarFeed("noticia");
  cargarFeed("social");
  actualizarFeed("noticia", true);
  actualizarFeed("social", true);
  const agente = await api("/api/agente").catch(() => null);
  if (agente?.activo) vigilarAgente();

  setInterval(refrescarCola, 10000);
  setInterval(refrescarIndices, 30000);
  setInterval(() => { refrescarCartera(); if (S.vista === "mercado") refrescarVariacion(); }, 30000);
  setInterval(() => { actualizarFeed("noticia", true); actualizarFeed("social", true); }, 10 * 60000);
}

arrancar().catch((e) => {
  document.querySelector("main").innerHTML = `<p class="vacio">No se pudo iniciar: ${esc(e.message)}</p>`;
});
