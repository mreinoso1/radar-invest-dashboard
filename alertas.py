"""Alertas: reglas que vigilan precios, niveles, noticias, movimientos y calendario, y el vigilante que las
comprueba cada minuto mientras Radar está abierto.

Las reglas son funciones puras: reciben precios, el momento actual y lo que pasó antes, y devuelven
alertas. No llaman a la red ni miran el reloj, así que se pueden probar con un reloj falso.

Una alerta es un dict con: clave (su identidad: la misma clave nunca se avisa dos veces), tipo, simbolo,
titulo, texto y urgente (si no lo es, espera al resumen diario).

Las alertas no son predicciones (no dicen "subirá"), así que no pasan por el marcador. Las de noticias
importantes salen de análisis cuyas señales el marcador ya juzga.
"""
import sys
import threading
import time
import traceback
from datetime import datetime

import calendario
import calibracion
import canales
import cuant
import datos
import marcador
import mercado
import reglas

CICLO = 60             # segundos entre rondas
HORA_DIARIA = 22       # tras el cierre de Wall Street: foto de datos cuantitativos y señales por reglas
HISTERESIS = 0.3       # % que el precio debe alejarse de un nivel antes de poder volver a avisar de él
HORA = 3600
SIN_LIMITE = {"precio", "calendario"}  # las que pides tú o tienen fecha fija no se frenan por activo
TIPOS_DIBUJO = ("horizontal", "rect")
_diario = threading.Lock()


def _p(v, formato=",.6g"):
    """Número a la española: 1.424,75. Se intercambian el punto y la coma del formato inglés."""
    return format(v, formato).translate(str.maketrans(",.", ".,"))


# ---------- Reglas ----------

def evaluar_reglas(reglas, precios):
    """Reglas que creaste tú ("avísame si NVDA baja de 180"). Avisan una vez y quedan desactivadas."""
    salida = []
    for r in reglas:
        p = precios.get(r["simbolo"])
        if p is None:
            continue
        if (r["condicion"] == "sube_de" and p >= r["nivel"]) or (r["condicion"] == "baja_de" and p <= r["nivel"]):
            verbo = "ha subido de" if r["condicion"] == "sube_de" else "ha bajado de"
            salida.append({"clave": f"regla:{r['id']}", "tipo": "precio", "simbolo": r["simbolo"], "urgente": True,
                           "regla_id": r["id"], "titulo": f"{r['simbolo']} {verbo} {_p(r['nivel'])}",
                           "texto": f"Cotiza a {_p(p)}." + (f" Tu nota: {r['nota']}" if r["nota"] else "")})
    return salida


def niveles_de(dibujos, modo):
    """Los niveles que vigilar de los dibujos de una gráfica: líneas horizontales y zonas."""
    if modo == "ninguno":
        return []
    salida = []
    for d in dibujos:
        if d.get("tipo") not in TIPOS_DIBUJO or (modo == "analista" and not d.get("analista")):
            continue
        precios = [pt["p"] for pt in d.get("puntos", []) if isinstance(pt.get("p"), (int, float))]
        if d["tipo"] == "horizontal" and precios:
            salida.append({"id": d["id"], "bajo": precios[0], "alto": precios[0], "texto": d.get("texto") or ""})
        elif d["tipo"] == "rect" and len(precios) >= 2:
            salida.append({"id": d["id"], "bajo": min(precios[:2]), "alto": max(precios[:2]), "texto": d.get("texto") or ""})
    return salida


def evaluar_niveles(simbolo, niveles, precio, previo, armados, ahora):
    """Avisa cuando el precio cruza una línea o entra en una zona. Tras avisar, el nivel se "desarma" hasta
    que el precio se aleje un HISTERESIS %: así un precio que baila sobre la línea no manda diez avisos.

    armados: {id del nivel: bool}. Devuelve (alertas, armados actualizados)."""
    salida, armados = [], dict(armados)
    for n in niveles:
        armado = armados.get(n["id"], True)
        linea = n["bajo"] == n["alto"]
        rango = _p(n["bajo"]) if linea else f"{_p(n['bajo'])}–{_p(n['alto'])}"
        nombre = f"«{n['texto']}»" if n["texto"] else ("tu nivel" if linea else "tu zona")
        dentro = n["bajo"] <= precio <= n["alto"]
        cruzo = previo is not None and ((previo < n["bajo"] <= precio) or (previo > n["alto"] >= precio)
                                        or (dentro and not n["bajo"] <= previo <= n["alto"]))
        if cruzo and armado:
            # Un nivel puede volver a avisar tras rearmarse: la clave lleva el momento del cruce.
            salida.append({"clave": f"nivel:{simbolo}:{n['id']}:{int(ahora)}", "tipo": "nivel", "simbolo": simbolo,
                           "urgente": True,
                           "titulo": f"{simbolo} {'sube' if precio > previo else 'baja'} a {_p(precio)}",
                           "texto": f"Ha llegado a {nombre} ({rango}), dibujado en la gráfica."})
            armados[n["id"]] = False
        elif not armado:
            distancia = min(abs(precio / n["bajo"] - 1), abs(precio / n["alto"] - 1)) * 100
            if not dentro and distancia >= HISTERESIS:
                armados[n["id"]] = True
    return salida, armados


def evaluar_movimientos(cotizaciones, umbral_acciones, umbral_cripto):
    """Movimientos de más de X % en el día. Al resumen diario, salvo que pasen del doble de X.
    La clave usa el cierre anterior: identifica la sesión, así el viernes no se repite el sábado."""
    salida = []
    for c in cotizaciones:
        v, s = c.get("var_dia"), c["simbolo"]
        if v is None or not c.get("cierre_previo"):
            continue
        umbral = umbral_cripto if marcador.es_cripto(s) else umbral_acciones
        if abs(v) < umbral:
            continue
        fuerte = abs(v) >= 2 * umbral
        salida.append({"clave": f"mov{2 if fuerte else 1}:{s}:{c['cierre_previo']:.6g}", "tipo": "movimiento",
                       "simbolo": s, "urgente": fuerte,
                       "titulo": f"{s} {'sube' if v > 0 else 'cae'} un {_p(abs(v), '.1f')} % hoy",
                       "texto": f"Cotiza a {_p(c['precio'])} frente a {_p(c['cierre_previo'])} del cierre anterior."})
    return salida


def evaluar_noticias(analisis, simbolos):
    """Noticias de importancia 4 o 5 que afectan a algo tuyo."""
    salida = []
    for a in analisis:
        tocados = [i["simbolo"] for i in a["impactos"] if i["simbolo"] in simbolos]
        if tocados:
            salida.append({"clave": f"noticia:{a['item_id']}", "tipo": "noticia", "simbolo": tocados[0],
                           "urgente": True, "titulo": f"Noticia importante para {', '.join(tocados)}",
                           "texto": f"{a['titulo']} ({a['fuente']}). Importancia {a['importancia']} de 5."})
    return salida


def evaluar_calendario(eventos, ahora, antelacion=24 * HORA):
    """Aviso en las 24 h previas a cada evento."""
    salida = []
    for e in eventos:
        if ahora < e["fecha"] <= ahora + antelacion:
            cuando = datetime.fromtimestamp(e["fecha"]).strftime("%d/%m a las %H:%M")
            salida.append({"clave": f"cal:{e['id']}", "tipo": "calendario", "simbolo": e.get("simbolo"),
                           "urgente": True, "titulo": f"En menos de 24 h: {e['titulo']}",
                           "texto": f"{e['titulo']} el {cuando} (tu hora)."})
    return salida


# ---------- Antispam ----------

def filtrar(nuevas, historial, ahora, max_por_hora):
    """Decide qué se avisa ya y qué espera al resumen diario. No tira nada que sea nuevo de verdad.

    - Una clave ya avisada no se repite.
    - Como mucho un aviso por activo y tipo cada hora (salvo reglas tuyas y calendario).
    - Si en la última hora ya se mandaron max_por_hora urgentes, el resto pasa al resumen.
    historial: alertas guardadas, con clave, tipo, simbolo, creada y enviada."""
    vistas = {a["clave"] for a in historial}
    recientes = [a for a in historial if a["creada"] > ahora - HORA and a["enviada"]]
    ocupados = {(a["simbolo"], a["tipo"]) for a in recientes}
    enviadas = sum(1 for a in recientes if a["urgente"])
    inmediatas, resumen = [], []
    for a in nuevas:
        if a["clave"] in vistas:
            continue
        vistas.add(a["clave"])
        par = (a.get("simbolo"), a["tipo"])
        if a["tipo"] not in SIN_LIMITE and par in ocupados:
            resumen.append({**a, "urgente": False})
            continue
        if a["urgente"] and enviadas < max_por_hora:
            inmediatas.append(a)
            ocupados.add(par)
            enviadas += 1
        else:
            resumen.append({**a, "urgente": False})
    return inmediatas, resumen


def toca_resumen(ahora, hora_resumen, ultimo):
    """El resumen diario sale una vez al día, a partir de la hora elegida (hora local)."""
    momento = datetime.fromtimestamp(ahora)
    return momento.hour >= hora_resumen and ultimo != momento.date().isoformat()


def linea_top(s):
    h = s["historial"]
    historial = (f"{h['efectivas']} resueltas, {_p(h['frente_indice'], '.0f')} % frente al índice"
                 if h.get("efectivas") else "sin historial")
    flecha = "▲" if s["direccion"] == "sube" else "▼"
    return f"• {s['simbolo']} {flecha} {s['buy_pct']} % · {s['tipo']} · {historial}"


def componer_resumen(pendientes, ahora, top=()):
    lineas = [f"• {a['titulo']}" for a in pendientes[:20]]
    if len(pendientes) > 20:
        lineas.append(f"… y {len(pendientes) - 20} más en Radar.")
    if top:
        lineas += ["", "Top 5 señales (estimaciones, no recomendaciones):"] + [linea_top(s) for s in top]
    return {"clave": f"resumen:{datetime.fromtimestamp(ahora):%Y-%m-%d}", "tipo": "resumen", "simbolo": None,
            "urgente": True,
            "titulo": f"Resumen del día: {len(pendientes)} {'aviso' if len(pendientes) == 1 else 'avisos'}",
            "texto": "\n".join(lineas)}


def top5(ahora):
    """El Top 5 de señales pendientes, con el peso de su tipo. Consulta precios: puede fallar sin red."""
    r = marcador.calcular("todas")
    return calibracion.top(r["senales"], r["por_tipo"], ahora)


def trabajo_diario(simbolos, ahora):
    """Foto de los datos cuantitativos y señales por reglas. Tarda (EDGAR va despacio): va en su propio hilo."""
    if not _diario.acquire(blocking=False):
        return
    try:
        cuant.foto_diaria(simbolos, ahora)
        reglas.generar(simbolos, ahora)
    except Exception:
        traceback.print_exc(file=sys.stderr)
    finally:
        _diario.release()


# ---------- Vigilante ----------

def ronda(ahora=None):
    """Una pasada completa: lee precios y estado, evalúa las reglas, filtra y envía. Devuelve lo enviado."""
    ahora = ahora or time.time()
    cfg = datos.ajustes()
    posiciones = datos.posiciones()
    simbolos = [p["simbolo"] for p in posiciones]
    if not simbolos:
        return []
    cotiz = mercado.cotizaciones(simbolos)
    precios = {c["simbolo"]: c["precio"] for c in cotiz if c.get("precio")}
    previos = datos.estado_alertas("precios", {})
    armados = datos.estado_alertas("armados", {})

    nuevas = evaluar_reglas([r for r in datos.reglas_alerta(True) if r["simbolo"] in precios], precios)
    for s, precio in precios.items():
        niveles = niveles_de(datos.dibujos(s), cfg["alertas_niveles"])
        alertas, armados[s] = evaluar_niveles(s, niveles, precio, previos.get(s), armados.get(s, {}), ahora)
        nuevas += alertas
    nuevas += evaluar_movimientos(cotiz, cfg["alerta_mov_acciones"], cfg["alerta_mov_cripto"])
    # Al arrancar por primera vez no se avisa de noticias viejas: se empieza desde una hora antes.
    desde_noticias = datos.estado_alertas("noticias_desde", int(ahora) - HORA)
    nuevas += evaluar_noticias(datos.analisis_importantes(desde_noticias), set(simbolos))
    try:
        eventos, _ = calendario.proximos(simbolos, ahora, dias=2)
    except Exception:
        eventos = []  # el calendario no debe tumbar las alertas de precio
    nuevas += evaluar_calendario(eventos, ahora)

    historial = datos.alertas(int(ahora) - 7 * 86400, 2000)
    inmediatas, para_resumen = filtrar(nuevas, historial, ahora, int(cfg["alertas_por_hora"]))
    for a in inmediatas:
        datos.guardar_alerta(a, canales.enviar(a, cfg), int(ahora))
        if a.get("regla_id"):
            datos.disparar_regla(a["regla_id"], int(ahora))
    for a in para_resumen:
        datos.guardar_alerta(a, None, int(ahora))
        if a.get("regla_id"):
            datos.disparar_regla(a["regla_id"], int(ahora))

    hoy = datetime.fromtimestamp(ahora).date().isoformat()
    if datetime.fromtimestamp(ahora).hour >= HORA_DIARIA and datos.estado_alertas("ultimo_diario") != hoy:
        datos.guardar_estado_alertas("ultimo_diario", hoy)
        threading.Thread(target=trabajo_diario, args=(simbolos, ahora), daemon=True).start()

    if toca_resumen(ahora, int(cfg["hora_resumen"]), datos.estado_alertas("ultimo_resumen")):
        pendientes = datos.alertas_sin_enviar()
        try:
            top = top5(ahora)
        except Exception:
            top = []  # sin el Top 5, el resumen sale igual
        if pendientes or top:
            resumen = componer_resumen(pendientes, ahora, top)
            envio = canales.enviar(resumen, cfg)
            datos.guardar_alerta(resumen, envio, int(ahora))
            if pendientes:
                datos.marcar_enviadas([a["id"] for a in pendientes], {"resumen": "ok"})
        datos.guardar_estado_alertas("ultimo_resumen", datetime.fromtimestamp(ahora).date().isoformat())

    datos.guardar_estado_alertas("precios", {**previos, **precios})
    datos.guardar_estado_alertas("armados", armados)
    datos.guardar_estado_alertas("noticias_desde", int(ahora))
    return inmediatas


class Vigilante(threading.Thread):
    """Hace una ronda cada minuto. Se arranca desde server.main(), nunca al importar."""

    def __init__(self):
        super().__init__(daemon=True, name="vigilante")
        self.parar = threading.Event()

    def run(self):
        while not self.parar.is_set():
            try:
                ronda()
            except Exception:  # un fallo de una ronda (sin red, Yahoo caído) no debe parar las siguientes
                traceback.print_exc(file=sys.stderr)
            self.parar.wait(CICLO)
