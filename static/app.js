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
  if (!["mercado", "cartera", "noticias", "ideas", "social", "aciertos", "simulacion", "alertas", "ajustes"].includes(vista)) vista = "mercado";
  S.vista = vista;
  document.querySelectorAll(".vista-texto").forEach((v) => { v.hidden = v.id !== `v-${vista}`; });
  $("v-mercado").classList.toggle("en-reposo", vista !== "mercado");
  document.querySelectorAll(".rail a").forEach((a) => {
    if (a.dataset.vista === vista) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  if (vista === "cartera") { pintarCartera(); cargarKraken(); }
  if (vista === "noticias") pintarFeed("noticia");
  if (vista === "ideas") cargarIdeas();
  if (vista === "social") { pintarFeed("social"); cargarSentimiento(); }
  if (vista === "aciertos") cargarAciertos();
  if (vista === "alertas") { cargarAlertas(); cargarCalendario(); }
  if (vista === "simulacion") cargarSimulacion();
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
  // Los datos cuantitativos llegan aparte: la primera vez pueden tardar (EDGAR va despacio).
  api(`/api/cuant?s=${encodeURIComponent(simbolo)}`).then((c) => {
    if (turno !== turnoAnalista || !c.lineas.length) return;
    $("an-ficha").insertAdjacentHTML("beforeend", `<details class="datos-cuant"><summary>Datos cuantitativos</summary>
      <ul>${[...c.lineas, ...c.macro].map((l) => `<li>${esc(l)}</li>`).join("")}</ul></details>`);
  }).catch(() => {});
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

function mensajeHTML(rol, texto, clase = "", indice = null, dibujos = []) {
  let boton = "";
  if (dibujos?.length) {
    const puestos = dibujosPuestos(dibujos);
    boton = `<button class="enlace boton-dibujos" data-dibujos="${indice}">${puestos ? "Quitar de la gráfica" : `Ver en la gráfica (${dibujos.length})`}</button>`;
  }
  return `<div class="mensaje ${rol} ${clase}">${esc(texto)}${boton}</div>`;
}

/* Los dibujos del analista se añaden a los del usuario: luego se mueven o borran como cualquier otro. */
function dibujosPuestos(dibujos) {
  const capa = panelActivo()?.g.dibujo;
  return !!capa && panelActivo().simbolo === S.simbolo && dibujos.every((d) => capa.dibujos.some((x) => x.id === d.id));
}

function alternarDibujos(dibujos) {
  const p = panelActivo();
  if (!p || p.simbolo !== S.simbolo) return;
  const capa = p.g.dibujo, ids = new Set(dibujos.map((d) => d.id));
  const puestos = dibujosPuestos(dibujos);
  capa.apuntar();
  capa.dibujos = capa.dibujos.filter((d) => !ids.has(d.id));
  if (!puestos) capa.dibujos.push(...structuredClone(dibujos));
  capa.seleccionar(null);
  capa.persistir();
}

function pintarChat(lista) {
  S.chat = lista;
  const sugerencias = S.cfg.agente_listo ? `<div class="chat-sugerencias">${PREGUNTAS.map((p) => `<button class="chip" data-pregunta="${esc(p)}">${esc(p)}</button>`).join("")}</div>` : "";
  $("an-chat").innerHTML = lista.length
    ? `<div class="chat-cab"><h2>Conversación</h2><button class="enlace" data-borrar-chat>Borrar</button></div>${lista.map((m, i) => mensajeHTML(m.rol, m.texto, "", i, m.dibujos)).join("")}`
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
    if (turno !== turnoAnalista) return;
    pintarChat([...S.chat, { rol: "usuario", texto }, { rol: "agente", texto: r.texto, dibujos: r.dibujos }]);
    if (r.dibujos.length) { alternarDibujos(r.dibujos); pintarChat(S.chat); }
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
  const d = e.target.closest("[data-dibujos]");
  if (d) {
    alternarDibujos(S.chat[+d.dataset.dibujos].dibujos);
    pintarChat(S.chat);
  }
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

// Las posiciones con cantidad 0 son la watchlist: se siguen sin tenerlas y son el universo de las ideas.
const tenidas = () => S.cartera.filas.filter((f) => f.cantidad > 0);
const seguidas = () => S.cartera.filas.filter((f) => !f.cantidad);

function pintarCartera() {
  const c = S.cartera, m = c.moneda, hay = tenidas().length > 0;
  const pctGan = c.coste ? c.ganancia / c.coste * 100 : null;
  const previo = c.valor - c.dia;
  $("cartera-aviso").textContent = c.avisos?.join(" · ") || "Precios de Yahoo Finance, pueden llevar retraso.";
  $("metricas").innerHTML = hay ? `
    <div class="metrica"><span>Valor total</span><b>${dinero(c.valor, m)}</b><small>Invertido ${dinero(c.coste, m)}</small></div>
    <div class="metrica"><span>Ganancia total</span><b class="${claseVar(c.ganancia)}">${flecha(c.ganancia)} ${dinero(c.ganancia, m)}</b><small class="${claseVar(c.ganancia)}">${pct(pctGan)}</small></div>
    <div class="metrica"><span>Hoy</span><b class="${claseVar(c.dia)}">${flecha(c.dia)} ${dinero(c.dia, m)}</b><small class="${claseVar(c.dia)}">${pct(previo ? c.dia / previo * 100 : null)}</small></div>` : "";
  $("cartera-vacia").hidden = hay;
  $("tabla-cartera").hidden = !hay;
  pintarWatchlist();
  if (!hay) return;
  const ordenadas = tenidas().sort((a, b) => b.valor - a.valor);
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

function pintarWatchlist() {
  const filas = seguidas().sort((a, b) => a.simbolo.localeCompare(b.simbolo));
  $("watchlist-vacia").hidden = filas.length > 0;
  $("tabla-watchlist").hidden = !filas.length;
  if (!filas.length) return;
  $("tabla-watchlist").innerHTML = `<thead><tr><th>Activo</th><th>Precio</th><th>Hoy</th><th>5 días</th><th><span hidden>Acciones</span></th></tr></thead>
  <tbody>${filas.map((f) => {
    const s = esc(f.simbolo);
    return `<tr>
      <td><button class="activo" data-abrir="${s}"><b>${s}</b><small>${esc(f.nombre)}</small></button></td>
      <td>${precioTxt(f.precio)} ${esc(f.moneda)}</td>
      <td class="${claseVar(f.var_dia)}">${flecha(f.var_dia)} ${pct(f.var_dia)}</td>
      <td class="${claseVar(f.var_5d)}">${flecha(f.var_5d)} ${pct(f.var_5d)}</td>
      <td><span class="acciones-fila"><button class="enlace" data-editar="${s}">Comprar</button><button class="enlace" data-borrar="${s}">Quitar</button></span></td>
    </tr>`;
  }).join("")}</tbody>`;
}

async function alClicTabla(e) {
  const t = e.target.closest("[data-abrir],[data-editar],[data-borrar]");
  if (!t) return;
  if (t.dataset.abrir) abrirActivo(t.dataset.abrir);
  if (t.dataset.editar) empezarEdicion(t.dataset.editar);
  if (t.dataset.borrar && confirm(`¿Quitar ${t.dataset.borrar} de tu cartera?`)) {
    await api(`/api/cartera?s=${encodeURIComponent(t.dataset.borrar)}`, { method: "DELETE" });
    await refrescarCartera();
    pintarCartera();
  }
}
$("tabla-cartera").addEventListener("click", alClicTabla);
$("tabla-watchlist").addEventListener("click", alClicTabla);

$("b-watchlist-inicial").addEventListener("click", async () => {
  $("b-watchlist-inicial").disabled = true;
  estado("watchlist", "Añadiendo…");
  try {
    const r = await enviar("/api/watchlist/inicial");
    estado("watchlist", r.anadidos ? `${r.anadidos} añadidos` : "Ya estaban todos");
    await refrescarCartera();
    pintarCartera();
  } catch (err) {
    estado("watchlist", err.message, true);
  } finally {
    $("b-watchlist-inicial").disabled = false;
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

/* ---------- Ideas nuevas ---------- */

const RELACIONES = { directo: "Directo", proveedor: "Proveedor", cliente: "Cliente", competidor: "Competidor", sector: "Sector", macro: "Macro" };
S.ideas = null;
S.juicioIdeas = null;  // cómo va cada idea según el marcador; llega aparte porque consulta precios

async function cargarIdeas() {
  try {
    S.ideas = await api("/api/ideas");
  } catch (e) {
    estado("ideas", e.message, true);
    return;
  }
  pintarIdeas();
  if (S.ideas.estado.activo) vigilarIdeas();
  api("/api/aciertos?origen=ideas").then((a) => { S.juicioIdeas = a; pintarIdeas(); }).catch(() => {});
  api("/api/top").then(pintarTop).catch(() => { $("ideas-top").innerHTML = ""; });
}

function pintarTop(r) {
  const historial = (s) => (s.historial.efectivas
    ? `${s.historial.efectivas} resueltas · ${pctSimple(s.historial.frente_indice)} frente al índice${s.historial.intervalo ? ` (${numero(s.historial.intervalo[0], 0)}–${numero(s.historial.intervalo[1], 0)} %)` : ""}`
    : "sin historial");
  $("ideas-top").innerHTML = `<h2>Top 5 señales de las últimas 48 h</h2>${r.top.length ? `<ol>${r.top.map((s) => `<li>
      <button class="activo" data-abrir="${esc(s.simbolo)}"><b>${esc(s.simbolo)}</b></button>
      <span class="${s.direccion}">${s.direccion === "sube" ? "▲" : "▼"} BUY ${s.buy_pct}%</span>
      <span class="etiqueta">${esc(s.tipo)}</span>
      ${s.url ? `<a href="${esc(enlaceSeguro(s.url))}" target="_blank" rel="noopener noreferrer">${esc(s.titulo)}</a>` : `<span>${esc(s.titulo)}</span>`}
      <small>${historial(s)} · peso ${numero(s.peso, 2)}</small></li>`).join("")}</ol>`
    : '<p class="nota">No hay señales pendientes de las últimas 48 h.</p>'}
    <p class="legal">Ordenadas por confianza, distancia a 50 y el acierto medido de su tipo frente al índice. Los tipos que han demostrado perder quedan fuera. Son estimaciones, no recomendaciones.</p>`;
}

function juicioDe(idea) {
  return S.juicioIdeas?.senales.find((s) => s.item_id === idea.item_id && s.simbolo === idea.simbolo);
}

function estadoIdea(j) {
  if (!j) return '<span class="neutro">Comprobando…</span>';
  if (j.estado === "sin_datos") return '<span class="neutro">Sin precios</span>';
  if (j.estado === "pendiente") return `<span class="neutro">${faltan(j.objetivo)}</span> · ahora <b class="${claseVar(j.movimiento)}">${pct(j.movimiento)}</b>`;
  const marca = j.acierto ? '<span class="sube">✓ Acierto</span>' : '<span class="baja">✗ Fallo</span>';
  const frente = j.relativo === null ? "" : ` · frente al índice <b class="${claseVar(j.relativo)}">${pct(j.relativo)}</b>`;
  return `${marca} · neto <b class="${claseVar(j.neto)}">${pct(j.neto)}</b>${frente}`;
}

function ideaHTML(i) {
  const direccion = i.prob_subida >= 55 ? "sube" : "baja";
  return `<article class="tarjeta idea">
    <div class="tarjeta-cab"><span class="etiqueta">${esc(RELACIONES[i.relacion] || i.relacion)}</span>
      <span>${esc(HORIZONTES[i.horizonte] || i.horizonte)} · confianza ${i.confianza}% · ${hace(i.creado)}</span>
      <span class="derecha">${estadoIdea(juicioDe(i))}</span></div>
    <div class="idea-cuerpo">
      <div class="impacto-activo"><button data-abrir="${esc(i.simbolo)}">${esc(i.simbolo)}</button>
        <small class="${direccion}">${direccion === "sube" ? "▲ Sube" : "▼ Baja"}</small>
        <small class="neutro">a ${i.precio ? precioTxt(i.precio) : "—"}</small></div>
      <div class="impacto-texto">${esc(i.mecanismo)}
        <small><b>Qué tendría que pasar:</b> ${esc(i.que_tendria_que_pasar)}</small>
        <small>Se invalida si: ${esc(i.invalidacion)}</small></div>
      <div class="impacto-datos">${barraSenal(i.prob_subida, 100 - i.prob_subida)}</div>
    </div>
    <p class="otras-fuentes">Por <a href="${esc(enlaceSeguro(i.url))}" target="_blank" rel="noopener noreferrer" title="${esc(i.titulo_original)}">${esc(i.titulo)}</a> · ${esc(i.fuente)}</p>
  </article>`;
}

function pintarIdeas() {
  const d = S.ideas;
  if (!d) return;
  const r = S.juicioIdeas?.resumen;
  const metrica = (titulo, valor, nota, clase = "") => `<div class="metrica"><span>${titulo}</span><b class="${clase}">${valor}</b><small>${nota}</small></div>`;
  $("ideas-metricas").innerHTML = metrica("Ideas", d.ideas.length, `últimos 90 días · ${d.watchlist.length} activos en la watchlist`)
    + (r ? metrica("Aciertos de dirección", pctSimple(r.acierto), `${r.aciertos} de ${r.con_direccion} resueltas · ${r.pendientes} pendientes`)
      + metrica("Frente al índice", pctSimple(r.acierto_relativo), `le ganaron al índice · media ${pct(r.relativo_medio)}`, "")
      + metrica("Neto de comisiones", pct(r.neto_medio), `media por idea · comisión media ${pct(r.coste_medio)}`, claseVar(r.neto_medio)) : "");
  let vacio = "Aún no hay ideas. Pulsa «Buscar oportunidades» después de actualizar las noticias.";
  if (!d.watchlist.length) vacio = 'Tu watchlist está vacía: añade activos con cantidad 0 en <a href="#cartera">Cartera</a> o carga allí la lista inicial.';
  else if (!S.cfg.agente_listo) vacio = 'Conecta tu cuenta de Claude en <a href="#ajustes">Ajustes</a> para buscar oportunidades.';
  $("ideas-lista").innerHTML = d.ideas.length ? d.ideas.map(ideaHTML).join("") : `<p class="vacio">${vacio}</p>`;
  $("ideas-menciones").innerHTML = d.menciones.length ? d.menciones.map((m) => `<div class="mencion">
      <div><button class="activo" data-abrir="${esc(m.simbolo)}"><b>${esc(m.simbolo)}</b></button><span>${m.n} ${m.n === 1 ? "lista" : "listas"}</span></div>
      ${m.ultimas.map((u) => `<a href="${esc(enlaceSeguro(u.url))}" target="_blank" rel="noopener noreferrer">${esc(u.titulo)}</a>`).join("")}
    </div>`).join("") : '<p class="nota">Ninguna mención reciente.</p>';
}

async function vigilarIdeas() {
  if (S.vigilandoIdeas) return;  // un solo bucle aunque se entre varias veces en la vista
  S.vigilandoIdeas = true;
  $("b-ideas").disabled = true;
  for (;;) {
    const e = await api("/api/ideas/estado").catch(() => null);
    if (!e) break;
    if (!e.activo) {
      estado("ideas", e.error || `Listo: ${e.ideas} ${e.ideas === 1 ? "idea nueva" : "ideas nuevas"}`, Boolean(e.error));
      break;
    }
    estado("ideas", e.total ? `Revisando ${e.hechos} de ${e.total} noticias…` : "Preparando las noticias…");
    await new Promise((ok) => setTimeout(ok, 3000));
  }
  S.vigilandoIdeas = false;
  $("b-ideas").disabled = false;
  if (S.vista === "ideas") cargarIdeas();
}

$("b-ideas").addEventListener("click", async () => {
  try {
    const r = await enviar("/api/ideas/analizar");
    if (r.error) { estado("ideas", r.error, true); return; }
    vigilarIdeas();
  } catch (err) {
    estado("ideas", err.message, true);
  }
});
$("v-ideas").addEventListener("click", (e) => {
  const b = e.target.closest("[data-abrir]");
  if (b) abrirActivo(b.dataset.abrir);
});

/* ---------- Simulación ---------- */

S.sim = { modo: "paper", datos: {}, grafica: null, vigilando: false };
const SIM_EXPLICA = {
  paper: "Todas las señales reales de Radar (cartera, ideas y reglas), operadas con dinero ficticio desde que existen: entran a su precio, con tamaño por riesgo, stop a 2 ATR, comisiones y deslizamiento. Es la única prueba libre de sesgos, pero tarda en acumular operaciones.",
  backtest: "Las reglas que se pueden reproducir con datos pasados (volumen, funding y, si lo eliges, insiders), simuladas sin mirar el futuro: la señal del día d solo usa datos hasta su cierre y entra a la apertura del día siguiente. Las señales del modelo no entran: Claude sabe lo que pasó después de las noticias antiguas.",
};
const SIM_CONFIG = {
  capital: ["Capital inicial ($)", 0], riesgo_pct: ["Riesgo por operación (%)", 2], stop_atr: ["Stop (veces el ATR)", 1],
  max_posiciones: ["Posiciones a la vez", 0], max_peso_pct: ["Peso máximo por posición (%)", 0],
  perdida_diaria_pct: ["Pérdida diaria que bloquea el día siguiente (%)", 1], desliz_acciones_bps: ["Deslizamiento en acciones (pb)", 0],
  desliz_cripto_bps: ["Deslizamiento en cripto (pb)", 0], comision_acciones: ["Comisión de ida y vuelta, acciones (%)", 2],
  comision_cripto: ["Comisión de ida y vuelta, cripto (%)", 2], prestamo_acciones_pct: ["Préstamo de un corto, acciones (% anual)", 1],
  prestamo_cripto_pct: ["Préstamo de un corto, cripto (% anual)", 1],
};

async function cargarSimulacion() {
  document.querySelectorAll("#sim-modo button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.modo === S.sim.modo));
  $("sim-explica").textContent = SIM_EXPLICA[S.sim.modo];
  $("sim-acciones").hidden = S.sim.modo !== "backtest";
  estado("simulacion", S.sim.modo === "paper" ? "Simulando…" : "");
  api("/api/criterio").then(pintarCriterio).catch((e) => { $("sim-criterio").innerHTML = `<p class="nota error">${esc(e.message)}</p>`; });
  try {
    if (S.sim.modo === "paper") {
      pintarSimulacion(await api("/api/paper"));
      estado("simulacion", "");
    } else {
      const b = await api("/api/backtest");
      if (b.estado.activo) vigilarBacktest();
      else estado("simulacion", b.estado.error || "", Boolean(b.estado.error));
      if (b.resultado) pintarSimulacion(b.resultado);
      else vaciarSimulacion("Aún no has lanzado ningún backtest. Pulsa «Lanzar backtest»: tarda unos minutos la primera vez.");
    }
  } catch (e) {
    estado("simulacion", e.message, true);
  }
}

function vaciarSimulacion(texto) {
  if (S.sim.grafica) { S.sim.grafica.remove(); S.sim.grafica = null; }
  $("sim-grafica").innerHTML = `<p class="vacio">${esc(texto)}</p>`;
  for (const id of ["sim-leyenda", "sim-metricas", "sim-tipos", "sim-descartes", "sim-config", "sim-operaciones", "sim-avisos"]) $(id).innerHTML = "";
}

function valorPunto(p) {
  const v = p.valor;
  if (Array.isArray(v) && v.length === 2 && p.nombre.startsWith("Rentabilidad")) return `${pct(v[0])} frente a ${pct(v[1])}`;
  if (Array.isArray(v)) return `de ${pct(v[0])} a ${pct(v[1])}`;
  if (typeof v === "number" && !Number.isInteger(v)) return pct(v);
  return v ?? "—";
}

function pintarCriterio(c) {
  const parte = (p) => `<div class="criterio-parte ${p.pasa ? "ok" : ""}"><b>${p.pasa ? "✓" : "✗"} ${esc(p.nombre)}</b>
    ${p.nota ? `<small>${esc(p.nota)}</small>` : ""}
    <ul>${(p.puntos || []).map((x) => `<li class="${x.ok ? "sube" : "baja"}">${x.ok ? "✓" : "✗"} ${esc(x.nombre)} <span>${esc(valorPunto(x))}</span></li>`).join("")}</ul></div>`;
  $("sim-criterio").innerHTML = `<h2>${c.desbloqueada ? "Fase 5 desbloqueada" : "Fase 5 bloqueada"} <small>· versión ${esc(c.huella)} · reglas: ${esc(c.incluidas.join(", ") || "ninguna aún")}</small></h2>
    <div class="criterio-partes">${c.partes.map(parte).join("")}</div>
    <p class="nota">Tienen que cumplirse las tres partes. El paper trading solo cuenta señales de esas reglas creadas desde ${new Date(c.desde * 1000).toLocaleDateString("es-ES")}, cuando empezó esta versión.</p>`;
}

function pintarSimulacion(r) {
  const capital = r.config.capital, m = r.metricas;
  // Gráfica: capital de la estrategia frente a comprar y mantener SPY y BTC con el mismo dinero.
  if (S.sim.grafica) S.sim.grafica.remove();
  $("sim-grafica").innerHTML = "";
  const g = LightweightCharts.createChart($("sim-grafica"), {
    autoSize: true, layout: { background: { color: COL.fondo }, textColor: COL.texto, fontFamily: "IBM Plex Mono, Consolas, monospace", fontSize: 11 },
    grid: { vertLines: { color: COL.rejilla }, horzLines: { color: COL.rejilla } },
    rightPriceScale: { borderColor: COL.eje, mode: 1 }, timeScale: { borderColor: COL.eje }, handleScroll: false, handleScale: false,
    localization: { priceFormatter: (v) => `${numero(v, 0)} $` },
  });
  S.sim.grafica = g;
  const lineas = [["Estrategia", COL.acento, r.curva], ["SPY", "#6aa8ff", r.indices?.SPY || []], ["BTC", "#c58bf2", r.indices?.["BTC-USD"] || []]];
  for (const [, color, curva] of lineas) {
    if (curva.length) g.addLineSeries({ color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false })
      .setData(curva.map(([d, v]) => ({ time: d * 86400, value: v })));
  }
  g.timeScale().fitContent();
  const final = (curva) => (curva.length ? (curva[curva.length - 1][1] / curva[0][1] - 1) * 100 : null);
  $("sim-leyenda").innerHTML = lineas.map(([n, color, curva]) => `<span><i style="background:${color}"></i>${n} <b class="${claseVar(final(curva))}">${pct(final(curva))}</b></span>`).join("")
    + '<span class="nota">Escala logarítmica</span>';

  const metrica = (t, v, nota, clase = "") => `<div class="metrica"><span>${t}</span><b class="${clase}">${v}</b><small>${nota}</small></div>`;
  $("sim-metricas").innerHTML = !m.rentabilidad && m.rentabilidad !== 0 ? "" :
    metrica("Rentabilidad neta", pct(m.rentabilidad), `${dinero(capital, "$")} → ${dinero(m.capital_final, "$")}`, claseVar(m.rentabilidad))
    + metrica("Al año (CAGR)", pct(m.cagr), `volatilidad ${pctSimple(m.volatilidad, 1)}`)
    + metrica("Sharpe", numero(m.sharpe, 2), "sin tipo libre de riesgo")
    + metrica("Caída máxima", pct(m.max_caida), "desde el máximo anterior", "baja")
    + metrica("Operaciones", m.operaciones, `${pctSimple(m.aciertos)} ganadoras · profit factor ${numero(m.profit_factor, 2)}`)
    + metrica("Exceso medio", pct(m.exceso_medio), "por operación frente a su índice", claseVar(m.exceso_medio))
    + metrica("Costes", dinero(m.costes, "$"), "comisiones, deslizamiento y préstamo");

  const tipos = r.por_regla || Object.values(r.operaciones.reduce((acc, o) => {
    const t = acc[o.tipo] ||= { tipo: o.tipo, operaciones: 0, suma: 0, ganadas: 0 };
    t.operaciones += 1; t.suma += o.exceso; t.ganadas += o.resultado > 0;
    return acc;
  }, {})).map((t) => ({ tipo: t.tipo, operaciones: t.operaciones, exceso_medio: t.suma / t.operaciones, aciertos: t.ganadas / t.operaciones * 100 }));
  $("sim-tipos").innerHTML = `<thead><tr><th>Tipo</th><th>Operaciones</th><th>Ganadoras</th><th>Exceso medio</th></tr></thead>
    <tbody>${tipos.length ? tipos.map((t) => `<tr><td>${esc(t.tipo)}</td><td>${t.operaciones}</td><td>${pctSimple(t.aciertos)}</td><td class="${claseVar(t.exceso_medio)}">${pct(t.exceso_medio)}</td></tr>`).join("")
      : '<tr><td colspan="4" class="vacio-mini">Aún no hay operaciones cerradas.</td></tr>'}</tbody>`;
  const descartes = Object.entries(r.descartes || {});
  $("sim-descartes").innerHTML = descartes.length ? descartes.map(([k, n]) => `<li><span>${esc(k)}</span><span>${n}</span></li>`).join("") : "<li><span>Ninguna</span><span></span></li>";
  $("sim-config").innerHTML = Object.entries(SIM_CONFIG).map(([k, [t, d]]) => `<li><span>${esc(t)}</span><span>${numero(r.config[k], d)}</span></li>`).join("")
    + `<li><span>Cortos</span><span>${r.config.cortos ? "sí" : "no"}</span></li>`;
  $("sim-avisos").innerHTML = (r.avisos || []).map((a) => `<p class="nota error">${esc(a)}</p>`).join("")
    + (r.universo ? `<p class="nota">Universo: ${r.universo.length} activos de tu cartera y watchlist · ${r.senales} señales${r.con_funding?.length ? ` · funding de ${esc(r.con_funding.join(", "))}` : ""}${r.creado ? ` · calculado ${hace(r.creado)}` : ""}</p>` : "");

  const dia = (d) => new Date(d * 86400000).toLocaleDateString("es-ES", { day: "2-digit", month: "2-digit", year: "2-digit" });
  const filas = [...(r.abiertas || []).map((o) => ({ ...o, abierta: true })), ...[...r.operaciones].sort((a, b) => b.dia_salida - a.dia_salida)].slice(0, 150);
  $("sim-operaciones").innerHTML = `<thead><tr><th>Activo</th><th>Tipo</th><th>Lado</th><th>Entrada</th><th>Salida</th><th>Motivo</th><th>Resultado ($)</th><th>Rentabilidad</th><th>Vs índice</th></tr></thead>
    <tbody>${filas.length ? filas.map((o) => `<tr>
      <td><button class="activo" data-abrir="${esc(o.simbolo)}"><b>${esc(o.simbolo)}</b></button></td><td>${esc(o.tipo)}</td>
      <td class="${o.direccion}">${o.direccion === "sube" ? "Largo" : "Corto"}</td>
      <td>${dia(o.dia_entrada)} · ${precioTxt(o.entrada)}</td>
      <td>${o.abierta ? `abierta · ${precioTxt(o.ultimo)}` : `${dia(o.dia_salida)} · ${precioTxt(o.salida)}`}</td>
      <td>${o.abierta ? `stop ${precioTxt(o.stop)}` : esc(o.motivo)}</td>
      <td class="${claseVar(o.resultado)}">${numero(o.resultado)}</td>
      <td class="${claseVar(o.rentabilidad)}">${o.abierta ? "—" : pct(o.rentabilidad)}</td>
      <td class="${claseVar(o.exceso)}">${o.abierta ? "—" : pct(o.exceso)}</td></tr>`).join("")
      : '<tr><td colspan="9" class="vacio-mini">Aún no hay operaciones.</td></tr>'}</tbody>`;
}

async function vigilarBacktest() {
  if (S.sim.vigilando) return;
  S.sim.vigilando = true;
  $("b-backtest").disabled = true;
  for (;;) {
    const b = await api("/api/backtest").catch(() => null);
    if (!b || !b.estado.activo) {
      estado("simulacion", b?.estado.error || "Backtest terminado", Boolean(b?.estado.error));
      break;
    }
    const e = b.estado;
    estado("simulacion", `${e.fase}${e.total ? ` · ${e.hecho} de ${e.total}` : ""}`);
    await new Promise((ok) => setTimeout(ok, 3000));
  }
  S.sim.vigilando = false;
  $("b-backtest").disabled = false;
  if (S.vista === "simulacion" && S.sim.modo === "backtest") cargarSimulacion();
}

$("sim-modo").addEventListener("click", (e) => {
  const b = e.target.closest("[data-modo]");
  if (!b || b.dataset.modo === S.sim.modo) return;
  S.sim.modo = b.dataset.modo;
  cargarSimulacion();
});
$("b-backtest").addEventListener("click", async () => {
  const r = await enviar("/api/backtest", { insiders: $("sim-insiders").checked }).catch((e) => ({ error: e.message }));
  if (r.error) { estado("simulacion", r.error, true); return; }
  vigilarBacktest();
});
$("v-simulacion").addEventListener("click", (e) => {
  const b = e.target.closest("[data-abrir]");
  if (b) abrirActivo(b.dataset.abrir);
});

/* ---------- Alertas ---------- */

const TIPOS_ALERTA = { precio: "Precio", nivel: "Nivel", noticia: "Noticia", movimiento: "Movimiento", calendario: "Calendario", resumen: "Resumen" };
const CANALES = { windows: "Windows", telegram: "Telegram", ntfy: "ntfy", resumen: "resumen diario" };
const TIPOS_EVENTO = { resultados: "Resultados", fed: "Fed", macro: "Macro", manual: "Tuyo" };
S.alertas = null;

async function refrescarInsignia() {
  const r = await api("/api/alertas/no_leidas").catch(() => null);
  if (!r) return;
  $("insignia-alertas").hidden = !r.n;
  $("insignia-alertas").textContent = r.n > 99 ? "99+" : r.n;
}

function envioTexto(enviada) {
  if (!enviada) return '<span class="neutro">Espera al resumen diario</span>';
  return Object.entries(enviada).map(([canal, r]) => (r === "ok"
    ? `<span class="sube">✓ ${esc(CANALES[canal] || canal)}</span>`
    : `<span class="baja" title="${esc(r)}">✗ ${esc(CANALES[canal] || canal)}: ${esc(r)}</span>`)).join(" · ") || '<span class="neutro">Sin canales activos</span>';
}

async function cargarAlertas() {
  try {
    S.alertas = await api("/api/alertas");
  } catch (e) {
    estado("alertas", e.message, true);
    return;
  }
  const a = S.alertas;
  $("al-historial").innerHTML = a.alertas.length ? a.alertas.map((x) => `<article class="tarjeta alerta ${x.leida ? "" : "nueva"}">
      <div class="tarjeta-cab"><span class="etiqueta">${esc(TIPOS_ALERTA[x.tipo] || x.tipo)}</span>
        ${x.simbolo ? `<button class="chip" data-abrir="${esc(x.simbolo)}">${esc(x.simbolo)}</button>` : ""}
        <span>${hace(x.creada)}</span><span class="derecha">${envioTexto(x.enviada)}</span></div>
      <h3>${esc(x.titulo)}</h3>${x.texto ? `<p class="alerta-texto">${esc(x.texto)}</p>` : ""}
    </article>`).join("")
    : '<p class="vacio">Aún no ha saltado ninguna alerta. Crea una de precio a la derecha, o deja que Radar vigile los niveles del analista y el calendario.</p>';
  const condicion = { sube_de: "suba de", baja_de: "baje de" };
  $("al-reglas").innerHTML = a.reglas.length ? a.reglas.map((r) => `<div class="regla ${r.activa ? "" : "hecha"}">
      <div><b>${esc(r.simbolo)}</b> ${condicion[r.condicion]} <b class="num">${precioTxt(r.nivel)}</b>
        <button class="enlace" data-borrar-regla="${r.id}">Quitar</button></div>
      <small>${r.activa ? "Vigilando" : `Saltó ${hace(r.disparada)}`}${r.nota ? ` · ${esc(r.nota)}` : ""}</small></div>`).join("")
    : '<p class="nota">Ninguna todavía.</p>';
  pintarSelectoresAlerta();
  if (S.vista === "alertas" && a.no_leidas) refrescarInsignia();
}

async function cargarCalendario() {
  estado("calendario", "Consultando…");
  try {
    const c = await api("/api/calendario");
    estado("calendario", c.errores.join(" · "), c.errores.length > 0);
    const dia = (ts) => new Date(ts * 1000).toLocaleString("es-ES", { weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
    $("al-calendario").innerHTML = `<thead><tr><th>Cuándo (tu hora)</th><th>Qué</th><th>Tipo</th><th>Activo</th><th><span hidden>Acciones</span></th></tr></thead>
      <tbody>${c.eventos.length ? c.eventos.map((e) => `<tr>
        <td>${dia(e.fecha)} <small class="neutro">${faltan(e.fecha)}</small></td><td>${esc(e.titulo)}</td>
        <td>${esc(TIPOS_EVENTO[e.tipo] || e.tipo)}</td>
        <td>${e.simbolo ? `<button class="activo" data-abrir="${esc(e.simbolo)}"><b>${esc(e.simbolo)}</b></button>` : "—"}</td>
        <td>${e.evento_id ? `<button class="enlace" data-borrar-evento="${e.evento_id}">Quitar</button>` : ""}</td></tr>`).join("")
      : '<tr><td colspan="5" class="vacio-mini">Nada en los próximos 14 días.</td></tr>'}</tbody>`;
  } catch (e) {
    estado("calendario", e.message, true);
  }
}

function pintarSelectoresAlerta() {
  const opciones = S.cartera.filas.map((f) => `<option value="${esc(f.simbolo)}">${esc(f.simbolo)}</option>`).join("");
  const elegido = $("r-simbolo").value;
  $("r-simbolo").innerHTML = opciones;
  if (elegido) $("r-simbolo").value = elegido;
  if (S.rellenarAlerta) {  // viene del botón «Alerta aquí» de la gráfica
    $("r-simbolo").value = S.rellenarAlerta.simbolo;
    $("r-nivel").value = S.rellenarAlerta.nivel;
    S.rellenarAlerta = null;
    $("r-nivel").focus();
  }
  const evento = $("e-simbolo").value;
  $("e-simbolo").innerHTML = `<option value="">Ninguno (macro)</option>${opciones}`;
  $("e-simbolo").value = evento;
  mostrarPrecioRegla();
}

function mostrarPrecioRegla() {
  const f = S.cartera.filas.find((x) => x.simbolo === $("r-simbolo").value);
  $("r-actual").textContent = f?.precio ? `· ahora ${precioTxt(f.precio)} ${f.moneda}` : "";
}

$("r-simbolo").addEventListener("change", mostrarPrecioRegla);
$("b-alerta").addEventListener("click", () => {
  const f = S.cartera.filas.find((x) => x.simbolo === S.simbolo);
  $("r-estado").textContent = f ? "" : `Añade ${S.simbolo} a tu cartera o watchlist para vigilarlo.`;
  if (f) S.rellenarAlerta = { simbolo: f.simbolo, nivel: f.precio ? Number(f.precio.toPrecision(6)) : "" };
  location.hash = "alertas";
});

$("form-regla").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await enviar("/api/alertas/reglas", { simbolo: $("r-simbolo").value, condicion: $("r-condicion").value,
      nivel: $("r-nivel").value, nota: $("r-nota").value });
    $("r-estado").textContent = "Creada. Te avisará una vez y quedará desactivada.";
    $("r-estado").classList.remove("error");
    $("r-nivel").value = "";
    $("r-nota").value = "";
    cargarAlertas();
  } catch (err) {
    $("r-estado").textContent = err.message;
    $("r-estado").classList.add("error");
  }
});

$("form-evento").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await enviar("/api/eventos", { titulo: $("e-titulo").value, simbolo: $("e-simbolo").value,
      fecha: Math.floor(new Date($("e-fecha").value).getTime() / 1000) });
    $("e-estado").textContent = "Añadido: te avisará 24 h antes.";
    $("form-evento").reset();
    cargarCalendario();
  } catch (err) {
    $("e-estado").textContent = err.message;
  }
});

$("b-leidas").addEventListener("click", async () => {
  await enviar("/api/alertas/leidas").catch(() => {});
  refrescarInsignia();
  cargarAlertas();
});

$("v-alertas").addEventListener("click", async (e) => {
  const t = e.target.closest("[data-abrir],[data-borrar-regla],[data-borrar-evento]");
  if (!t) return;
  if (t.dataset.abrir) return abrirActivo(t.dataset.abrir);
  const ruta = t.dataset.borrarRegla ? `/api/alertas/reglas?id=${t.dataset.borrarRegla}` : `/api/eventos?id=${t.dataset.borrarEvento}`;
  await api(ruta, { method: "DELETE" }).catch(() => {});
  if (t.dataset.borrarRegla) cargarAlertas(); else cargarCalendario();
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
  $("a-max-oport").value = c.max_oportunidades;
  $("a-max-ideas").value = c.max_ideas;
  $("a-com-acciones").value = c.comision_acciones;
  $("a-com-cripto").value = c.comision_cripto;
  $("a-al-windows").checked = c.alertas_windows;
  $("a-al-telegram").checked = c.alertas_telegram;
  $("a-al-ntfy").checked = c.alertas_ntfy;
  $("a-al-minimas").checked = c.alertas_minimas;
  $("a-tg-token").value = "";
  $("a-tg-token").placeholder = c.tiene_telegram ? "Guardado. Escribe otro para cambiarlo" : "Créalo hablando con @BotFather en Telegram";
  $("a-tg-estado").textContent = c.tiene_telegram ? "● Guardado" : "";
  $("a-tg-chat").value = c.telegram_chat;
  $("a-ntfy-tema").value = c.ntfy_tema;
  $("a-ntfy-servidor-txt").textContent = `Servidor: ${c.ntfy_servidor}`;
  $("a-al-niveles").value = c.alertas_niveles;
  $("a-al-mov-acc").value = c.alerta_mov_acciones;
  $("a-al-mov-cri").value = c.alerta_mov_cripto;
  $("a-al-hora").value = c.alertas_por_hora;
  $("a-al-resumen").value = c.hora_resumen;
  $("a-fred").value = "";
  $("a-fred").placeholder = c.tiene_fred ? "Guardada. Escribe otra para cambiarla" : "Opcional: fechas de IPC, empleo, PIB y PCE";
  $("a-fred-estado").textContent = c.tiene_fred ? "● Configurada" : "";
  // Simulación: las comisiones ya se ajustan arriba (son las del marcador); aquí, el resto.
  const sim = c.simulacion_efectiva;
  $("a-sim").innerHTML = Object.entries(SIM_CONFIG).filter(([k]) => !k.startsWith("comision"))
    .map(([k, [t]]) => `<div class="campo"><label for="a-sim-${k}">${esc(t)}</label><input id="a-sim-${k}" data-sim="${k}" type="number" step="any" min="0" value="${sim[k]}"></div>`).join("");
  $("a-sim-cortos").checked = sim.cortos;
  $("a-sec").value = "";
  $("a-sec").placeholder = c.tiene_sec ? "Guardado. Escribe otro para cambiarlo" : "Nombre correo@ejemplo.com";
  $("a-sec-estado").textContent = c.tiene_sec ? "● Configurado" : "";
  $("a-auto").checked = c.auto_analizar;
  $("a-resumen-auto").checked = c.resumen_auto;
  $("a-moneda").value = c.moneda;
  $("a-clave").value = "";
  $("a-x").value = "";
  $("a-clave").placeholder = c.tiene_clave ? "Guardada. Escribe otra para cambiarla" : "sk-ant-…";
  $("a-x").placeholder = c.tiene_x ? "Guardado. Escribe otro para cambiarlo" : "Opcional";
  $("a-clave-estado").textContent = c.tiene_clave ? "● Configurada" : "";
  $("a-x-estado").textContent = c.tiene_x ? "● Configurado" : "";
  for (const id of ["a-kraken-key", "a-kraken-secret", "a-kraken-fut-key", "a-kraken-fut-secret"]) $(id).value = "";
  $("a-kraken-key").placeholder = c.tiene_kraken ? "Guardada. Escribe otra para cambiarla" : "";
  $("a-kraken-fut-key").placeholder = c.tiene_kraken_fut ? "Guardada. Escribe otra para cambiarla" : "Opcional";
  $("a-kraken-estado").textContent = c.tiene_kraken ? "● Conectado" : "";
  $("a-kraken-fut-estado").textContent = c.tiene_kraken_fut ? "● Conectado" : "";
  $("b-kraken-quitar").hidden = !c.tiene_kraken && !c.tiene_kraken_fut;
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
    moneda: $("a-moneda").value, max_oportunidades: $("a-max-oport").value, max_ideas: $("a-max-ideas").value,
    comision_acciones: $("a-com-acciones").value, comision_cripto: $("a-com-cripto").value,
    alertas_windows: $("a-al-windows").checked, alertas_telegram: $("a-al-telegram").checked,
    alertas_ntfy: $("a-al-ntfy").checked, alertas_minimas: $("a-al-minimas").checked,
    telegram_chat: $("a-tg-chat").value, ntfy_tema: $("a-ntfy-tema").value, alertas_niveles: $("a-al-niveles").value,
    alerta_mov_acciones: $("a-al-mov-acc").value, alerta_mov_cripto: $("a-al-mov-cri").value,
    alertas_por_hora: $("a-al-hora").value, hora_resumen: $("a-al-resumen").value,
  };
  if ($("a-tg-token").value.trim()) cuerpo.telegram_token = $("a-tg-token").value.trim();
  if ($("a-fred").value.trim()) cuerpo.fred_key = $("a-fred").value.trim();
  if ($("a-sec").value.trim()) cuerpo.sec_contacto = $("a-sec").value.trim();
  // Solo se guardan los valores que difieren de los actuales: así un guardado sin cambios no crea una versión nueva.
  const sim = { ...S.cfg.simulacion };
  document.querySelectorAll("[data-sim]").forEach((el) => {
    if (Number(el.value) !== S.cfg.simulacion_efectiva[el.dataset.sim]) sim[el.dataset.sim] = Number(el.value);
  });
  if ($("a-sim-cortos").checked !== S.cfg.simulacion_efectiva.cortos) sim.cortos = $("a-sim-cortos").checked;
  cuerpo.simulacion = sim;
  if ($("a-clave").value.trim()) cuerpo.anthropic_key = $("a-clave").value;
  if ($("a-x").value.trim()) cuerpo.x_token = $("a-x").value;
  for (const [pub, priv, cPub, cPriv] of [["a-kraken-key", "a-kraken-secret", "kraken_key", "kraken_secret"],
    ["a-kraken-fut-key", "a-kraken-fut-secret", "kraken_fut_key", "kraken_fut_secret"]]) {
    const a = $(pub).value.trim(), b = $(priv).value.trim();
    if (!a && !b) continue;
    if (!a || !b) {
      $("ajustes-estado").textContent = "Kraken necesita la clave pública y la privada juntas.";
      $("ajustes-estado").classList.add("error");
      return;
    }
    cuerpo[cPub] = a;
    cuerpo[cPriv] = b;
  }
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

$("form-ajustes").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-probar]");
  if (!b) return;
  e.preventDefault();  // el botón está dentro de la etiqueta de la casilla: que no la marque
  $("ajustes-estado").textContent = "Enviando prueba…";
  $("ajustes-estado").classList.remove("error");
  try {
    const r = await enviar("/api/alertas/probar", { canal: b.dataset.probar });
    const resultado = r[b.dataset.probar];
    $("ajustes-estado").textContent = resultado === "ok" ? `Prueba enviada por ${CANALES[b.dataset.probar]}` : resultado;
    $("ajustes-estado").classList.toggle("error", resultado !== "ok");
  } catch (err) {
    $("ajustes-estado").textContent = err.message;
    $("ajustes-estado").classList.add("error");
  }
});

$("b-kraken-quitar").addEventListener("click", async () => {
  if (!confirm("¿Borrar de este ordenador las claves de Kraken?")) return;
  S.cfg = await enviar("/api/ajustes", { kraken_key: "", kraken_secret: "", kraken_fut_key: "", kraken_fut_secret: "" });
  pintarAjustes();
  $("ajustes-estado").textContent = "Kraken desconectado";
});

/* ---------- Kraken ---------- */

async function cargarKraken(forzar = false) {
  const conectado = S.cfg.tiene_kraken || S.cfg.tiene_kraken_fut;
  $("b-kraken").hidden = !conectado;
  if (!conectado) {
    $("kraken-cuerpo").innerHTML = '<p class="nota">Conecta tu cuenta de Kraken en <a href="#ajustes">Ajustes</a> para ver aquí lo que tienes allí, con claves de solo consulta. El analista también lo tendrá en cuenta.</p>';
    return;
  }
  $("estado-kraken").textContent = "Consultando Kraken…";
  $("estado-kraken").classList.remove("error");
  try {
    pintarKraken(await api(`/api/kraken${forzar ? "?forzar=1" : ""}`));
    $("estado-kraken").textContent = "";
  } catch (e) {
    $("estado-kraken").textContent = e.message;
    $("estado-kraken").classList.add("error");
  }
}

function pintarKraken(k) {
  const activo = (f) => f.simbolo
    ? `<button class="activo" data-abrir="${esc(f.simbolo)}"><b>${esc(f.base)}</b><small>${esc(f.simbolo)}</small></button>`
    : `<b>${esc(f.base)}</b>`;
  const errores = k.errores.map((e) => `<p class="nota error">${esc(e)}</p>`).join("");
  const posiciones = k.posiciones.length ? `<div class="tabla-envoltura"><table class="tabla">
    <thead><tr><th>Posición abierta</th><th>Lado</th><th>Dónde</th><th>Cantidad</th><th>Entrada</th><th>Resultado (USD)</th></tr></thead>
    <tbody>${k.posiciones.map((p) => `<tr><td>${activo(p)}</td>
      <td class="${p.lado === "corto" ? "baja" : "sube"}">${p.lado === "corto" ? "Corto" : "Largo"}</td>
      <td>${esc(p.mercado === "futuros" ? `Futuros ${p.contrato || ""}` : "Margen")}</td>
      <td>${numero(p.cantidad, p.cantidad % 1 ? 4 : 0)}</td><td>${precioTxt(p.entrada)}</td>
      <td class="${claseVar(p.resultado_usd)}">${p.resultado_usd === null ? "—" : `${flecha(p.resultado_usd)} ${numero(p.resultado_usd)}`}</td></tr>`).join("")}</tbody></table></div>` : "";
  const saldos = k.saldos.length ? `<div class="tabla-envoltura"><table class="tabla">
    <thead><tr><th>Saldo</th><th>Cantidad</th><th>Precio (USD)</th><th>Valor (USD)</th></tr></thead>
    <tbody>${k.saldos.map((s) => `<tr><td>${activo(s)}</td><td>${numero(s.cantidad, s.cantidad % 1 ? 6 : 0)}</td>
      <td>${s.precio_usd ? precioTxt(s.precio_usd) : "—"}</td><td>${s.valor_usd === null ? "—" : numero(s.valor_usd)}</td></tr>`).join("")}</tbody></table></div>` : "";
  const totales = [`Spot: ${numero(k.valor_spot_usd)} USD`];
  if (k.valor_futuros_usd !== null) totales.push(`Cuenta de futuros: ${numero(k.valor_futuros_usd)} USD`);
  $("kraken-cuerpo").innerHTML = `${errores}<p class="nota">${totales.join(" · ")} · actualizado ${hace(k.actualizado)}</p>${posiciones}${saldos}`
    + (!posiciones && !saldos && !errores ? '<p class="nota">No hay saldos ni posiciones abiertas.</p>' : "");
}

$("b-kraken").addEventListener("click", () => cargarKraken(true));
$("kraken-cuerpo").addEventListener("click", (e) => {
  const b = e.target.closest("[data-abrir]");
  if (b) abrirActivo(b.dataset.abrir);
});

/* ---------- Aciertos del agente ---------- */

const HORIZONTES = { horas: "Horas", "días": "Días", semanas: "Semanas", meses: "Meses" };
S.aciertos = null;
S.filtroAciertos = { estado: "todas", activo: null };
S.origenAciertos = "cartera";
const VACIO_ACIERTOS = {
  cartera: "Aún no hay señales de tu cartera. Cuando analices noticias con IA, cada efecto sobre uno de tus activos se guarda aquí y se juzga al terminar su horizonte.",
  ideas: "Aún no hay ideas. Las que proponga el modo oportunidades se juzgan aquí igual que las señales de tu cartera.",
  reglas: "Aún no hay señales por reglas. Radar las evalúa cada día a partir de las 22:00 si la ventana está abierta.",
  todas: "Aún no hay señales.",
};

const fechaCorta = (ts) => new Date(ts * 1000).toLocaleString("es-ES", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
const pctSimple = (v, dec = 0) => (v === null || v === undefined ? "—" : `${numero(v, dec)} %`);

function faltan(ts) {
  const s = ts - Date.now() / 1000;
  if (s <= 3600) return "falta < 1 h";
  if (s < 86400) return `faltan ${Math.ceil(s / 3600)} h`;
  return `faltan ${Math.ceil(s / 86400)} d`;
}

async function cargarAciertos() {
  $("b-act-aciertos").disabled = true;
  $("estado-aciertos").textContent = "Comprobando precios…";
  $("estado-aciertos").classList.remove("error");
  try {
    S.aciertos = await api(`/api/aciertos?origen=${S.origenAciertos}`);
    $("estado-aciertos").textContent = "";
    pintarAciertos();
  } catch (e) {
    $("estado-aciertos").textContent = e.message;
    $("estado-aciertos").classList.add("error");
  } finally {
    $("b-act-aciertos").disabled = false;
  }
}

function pintarAciertos() {
  const a = S.aciertos;
  if (!a) return;
  const r = a.resumen;
  document.querySelectorAll("#ac-origen button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.origen === a.origen));
  $("ac-vacio").textContent = VACIO_ACIERTOS[a.origen];
  $("ac-vacio").hidden = r.total > 0;
  $("ac-contenido").hidden = r.total === 0;
  if (!r.total) return;
  const margen = (i) => (i ? `entre ${numero(i[0], 0)} y ${numero(i[1], 0)} % (margen 95 %)` : "sin datos aún");
  const vsMoneda = r.habilidad === null ? null : r.habilidad * 100;
  $("ac-metricas").innerHTML = `
    <div class="metrica"><span>Señales resueltas</span><b>${r.resueltas}</b><small>${r.pendientes} pendientes · ${r.efectivas} en días distintos · ${r.noticias} noticias distintas</small></div>
    <div class="metrica"><span>Aciertos de dirección</span><b>${pctSimple(r.acierto)}</b><small>${r.aciertos} de ${r.con_direccion} · ${margen(r.intervalo)}</small></div>
    <div class="metrica"><span>Decir siempre «sube»</span><b>${pctSimple(r.siempre_sube)}</b><small>en esas mismas señales</small></div>
    <div class="metrica"><span>Le ganó al índice</span><b>${pctSimple(r.acierto_relativo)}</b><small>${r.con_indice} comparables · media ${pct(r.relativo_medio)} · ${margen(r.intervalo_relativo)}</small></div>
    <div class="metrica"><span>Neto de comisiones</span><b class="${claseVar(r.neto_medio)}">${pct(r.neto_medio)}</b><small>media por señal · gana en ${pctSimple(r.acierto_neto)} · comisión ${pct(r.coste_medio)}</small></div>
    <div class="metrica"><span>Calidad de las probabilidades</span><b class="${claseVar(vsMoneda)}">${pct(vsMoneda)}</b><small>frente a decir siempre 50 %</small></div>
    <div class="metrica"><span>Movimiento a favor</span><b class="${claseVar(r.a_favor)}">${pct(r.a_favor)}</b><small>media por señal, antes de comisiones</small></div>`;
  $("ac-veredicto").textContent = r.veredicto;

  $("ac-calibracion").innerHTML = `<thead><tr><th>Cuando dijo BUY</th><th>Señales</th><th>Prometía</th><th>Subió de verdad</th></tr></thead>
  <tbody>${a.calibracion.map((c) => `<tr>
    <td>${esc(c.tramo)}</td><td>${c.n}</td><td>${pctSimple(c.prob_media)}</td>
    <td>${c.n ? `<span class="calibre" title="Prometía ${numero(c.prob_media, 0)} %, subió ${numero(c.subio_pct, 0)} %"><i><u style="width:${c.subio_pct.toFixed(1)}%"></u><s style="left:${c.prob_media.toFixed(1)}%"></s></i>${pctSimple(c.subio_pct)}</span>` : "—"}</td>
  </tr>`).join("")}</tbody>`;

  const filaAcierto = (nombre, g, extra = "") => `<tr><td>${nombre}</td><td>${g.n}</td><td>${g.n ? `${g.aciertos} · ${pctSimple(g.pct)}` : "—"}</td>${extra}</tr>`;
  $("ac-activos").innerHTML = `<thead><tr><th>Activo</th><th>Con dirección</th><th>Aciertos</th><th>Pendientes</th></tr></thead>
    <tbody>${a.por_activo.map((g) => filaAcierto(`<button class="activo" data-abrir="${esc(g.simbolo)}"><b>${esc(g.simbolo)}</b></button>`, g, `<td>${g.pendientes}</td>`)).join("")}</tbody>`;
  $("ac-horizontes").innerHTML = `<thead><tr><th>Horizonte</th><th>Con dirección</th><th>Aciertos</th></tr></thead>
    <tbody>${a.por_horizonte.map((g) => filaAcierto(esc(HORIZONTES[g.horizonte] || g.horizonte), g)).join("")}</tbody>`;
  $("ac-tipos").innerHTML = `<thead><tr><th>Tipo de señal</th><th title="Señales en días distintos">Efectivas</th><th>Frente al índice</th><th>Neto medio</th><th title="Su ventaja medida, contraída hacia 0 con pocos datos">Peso</th></tr></thead>
    <tbody>${(a.por_tipo || []).map((t) => `<tr><td>${esc(t.tipo)}</td><td>${t.efectivas}${t.pendientes ? ` <small class="neutro">+${t.pendientes} pend.</small>` : ""}</td>
      <td>${t.frente_indice === null ? "—" : `${pctSimple(t.frente_indice)}${t.intervalo ? ` <small class="neutro">${numero(t.intervalo[0], 0)}–${numero(t.intervalo[1], 0)}</small>` : ""}`}</td>
      <td class="${claseVar(t.neto_medio)}">${pct(t.neto_medio)}</td><td class="${claseVar(t.peso)}">${numero(t.peso, 2)}</td></tr>`).join("")}</tbody>`;
  pintarSenales();
}

function pintarSenales() {
  const a = S.aciertos, f = S.filtroAciertos;
  const simbolos = [...new Set(a.senales.map((s) => s.simbolo))].sort();
  const chip = (attr, valor, texto, activo) => `<button class="chip" ${attr}="${esc(valor)}" aria-pressed="${activo}">${esc(texto)}</button>`;
  $("ac-filtros").innerHTML = [["todas", "Todas"], ["resuelta", "Resueltas"], ["pendiente", "Pendientes"]]
    .map(([v, t]) => chip("data-estado", v, t, f.estado === v)).join("")
    + `<span class="sep"></span>` + chip("data-activo", "", "Todos", !f.activo)
    + simbolos.map((s) => chip("data-activo", s, s, f.activo === s)).join("");
  const lista = a.senales.filter((s) => (f.estado === "todas" || s.estado === f.estado) && (!f.activo || s.simbolo === f.activo));
  const resultado = (s) => {
    if (s.estado === "pendiente") return `<span class="neutro">${faltan(s.objetivo)}</span>`;
    if (s.estado === "sin_datos") return `<span class="neutro">Sin precios</span>`;
    if (s.acierto === true) return `<span class="sube">✓ Acierto</span>`;
    if (s.acierto === false) return `<span class="baja">✗ Fallo</span>`;
    return `<span class="neutro">${s.direccion === "neutro" ? "Sin dirección" : "Empate"}</span>`;
  };
  $("ac-senales").innerHTML = `<thead><tr><th>Emitida</th><th>Activo</th><th>Noticia</th><th>BUY</th><th>Horizonte</th><th>Entrada</th><th>Salida o ahora</th><th>Movimiento</th><th title="Lo que ganó la señal menos lo que hizo el índice en el mismo periodo">Vs índice</th><th title="A favor de la señal, menos la comisión de ida y vuelta">Neto</th><th>Resultado</th></tr></thead>
  <tbody>${lista.length ? lista.map((s) => {
    const precio = s.estado === "resuelta" ? s.salida : s.entrada && s.movimiento !== null ? s.entrada * (1 + s.movimiento / 100) : null;
    return `<tr>
      <td>${fechaCorta(s.creado)}</td>
      <td><button class="activo" data-abrir="${esc(s.simbolo)}"><b>${esc(s.simbolo)}</b></button></td>
      <td class="ac-noticia"><a href="${esc(enlaceSeguro(s.url))}" target="_blank" rel="noopener noreferrer" title="${esc(s.titulo)}">${esc(s.titulo)}</a></td>
      <td class="${s.direccion === "sube" ? "sube" : s.direccion === "baja" ? "baja" : "neutro"}">${s.buy_pct}</td>
      <td>${esc(HORIZONTES[s.horizonte] || s.horizonte)}</td>
      <td>${s.entrada ? precioTxt(s.entrada) : "—"}</td>
      <td>${precio ? precioTxt(precio) : "—"}</td>
      <td class="${claseVar(s.movimiento)}">${pct(s.movimiento)}</td>
      <td class="${claseVar(s.relativo)}">${s.relativo === undefined ? "—" : pct(s.relativo)}</td>
      <td class="${claseVar(s.neto)}">${s.neto === undefined ? "—" : pct(s.neto)}</td>
      <td>${resultado(s)}</td>
    </tr>`;
  }).join("") : `<tr><td colspan="11" class="vacio-mini">No hay señales con este filtro.</td></tr>`}</tbody>`;
}

$("b-act-aciertos").addEventListener("click", cargarAciertos);
$("ac-origen").addEventListener("click", (e) => {
  const b = e.target.closest("[data-origen]");
  if (!b || b.dataset.origen === S.origenAciertos) return;
  S.origenAciertos = b.dataset.origen;
  S.filtroAciertos.activo = null;
  cargarAciertos();
});
$("ac-filtros").addEventListener("click", (e) => {
  const b = e.target.closest("[data-estado],[data-activo]");
  if (!b) return;
  if (b.dataset.estado !== undefined) S.filtroAciertos.estado = b.dataset.estado;
  if (b.dataset.activo !== undefined) S.filtroAciertos.activo = b.dataset.activo || null;
  pintarSenales();
});
$("v-aciertos").addEventListener("click", (e) => {
  const b = e.target.closest("[data-abrir]");
  if (b) abrirActivo(b.dataset.abrir);
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
  const ideas = await api("/api/ideas/estado").catch(() => null);
  if (ideas?.activo) vigilarIdeas();

  refrescarInsignia();
  setInterval(refrescarInsignia, 30000);
  setInterval(refrescarCola, 10000);
  setInterval(refrescarIndices, 30000);
  setInterval(() => { refrescarCartera(); if (S.vista === "mercado") refrescarVariacion(); }, 30000);
  setInterval(() => { actualizarFeed("noticia", true); actualizarFeed("social", true); }, 10 * 60000);
}

arrancar().catch((e) => {
  document.querySelector("main").innerHTML = `<p class="vacio">No se pudo iniciar: ${esc(e.message)}</p>`;
});
