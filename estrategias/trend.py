"""trend_v1: seguir la tendencia en cripto líquidas, con una validación preregistrada.

Todo lo que decide la estrategia está congelado en trend_v1.json (tag git prereg-trend-v1). Este módulo solo
lo ejecuta, y se niega a hacerlo si el JSON no coincide byte a byte con el del tag.

Capas (cada una es una función pura que se prueba por separado):
  1. régimen      BTC frente a su media de 100 días y su volatilidad: en bajista o extrema no se compra más.
  2. señal        cada moneda, larga si su cierre está por encima de su media de 100 días.
  3. filtro       la señal debe repetirse dos cierres; un peso solo se toca si cambia más de un 25 %.
  4. tamaño       volatilidad objetivo del 25 % anual, tope del 20 % por moneda, nunca más del 100 %.
  5. eventos      noticias y alertas junto a cada posición; solo se muestran, no deciden (fuera del backtest).
  6. registro     cada decisión semanal queda guardada con su porqué.

Sin mirar el futuro: la decisión del domingo usa cierres hasta el domingo y se ejecuta a la apertura del lunes.
Python calcula todo; aquí no hay ninguna llamada al modelo.

Uso:  python -m estrategias.trend backtest             las 8 monedas principales
      python -m estrategias.trend backtest --reserva   las 4 reservadas, una sola vez
"""
import hashlib
import json
import math
import random
import statistics
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import datos
import mercado

CARPETA = Path(__file__).resolve().parent
REPO = CARPETA.parent
PREREG = CARPETA / "trend_v1.json"
TAG = "prereg-trend-v1"
RUTA_EN_GIT = "estrategias/trend_v1.json"
DIA = 86400
RAIZ_ANIO = math.sqrt(365)

# Los números de trend_v1.json, tal cual. Cambiar uno es otra estrategia (trend_v2), con su propio preregistro.
P = {
    "media": 100,            # días de la media móvil (señal y régimen)
    "vol_peso": 60,          # días de la volatilidad que fija el tamaño
    "vol_regimen": 30,       # días de la volatilidad de BTC del régimen
    "ventana_mediana": 365,  # días de la mediana con que se compara esa volatilidad
    "extrema": 2.0,          # volatilidad extrema: más de 2 veces su mediana
    "pendiente": 20,         # alcista si la media es mayor que hace 20 días
    "tope": 0.20,            # peso máximo por moneda
    "vol_objetivo": 0.25,    # volatilidad anual objetivo de cada posición
    "cambio_min": 0.25,      # cambio relativo mínimo para operar
    "coste": 0.0036,         # por lado: 0,26 % de comisión + 0,10 % de deslizamiento
}
COSTE_ALTO = 0.0052
INICIO, FIN = "2018-01-01", "2026-11-08"
DESCARGA_DESDE = "2016-01-01"  # historia previa para las medias y la mediana de volatilidad de BTC
ANIOS = ("2022", "2023", "2024", "2025")
SHARPE_MIN, CAIDA_MAX, ANIOS_MIN = 0.8, 35.0, 3
BLOQUE, REMUESTREOS, SEMILLA, NIVEL = 20, 5000, 7, 0.95
CLAVE, CLAVE_RESERVA, CLAVE_VELAS = "trend_v1", "trend_v1_reserva", "trend_v1_velas"
ABREN = ("alcista", "lateral")  # regímenes en los que se puede comprar más


class ErrorEstrategia(Exception):
    pass


class ErrorPreregistro(ErrorEstrategia):
    pass


def dia_de(fecha):
    return int(datetime.fromisoformat(fecha).replace(tzinfo=timezone.utc).timestamp()) // DIA


def fecha_de(dia):
    return datetime.fromtimestamp(dia * DIA, timezone.utc).strftime("%Y-%m-%d")


def es_domingo(dia):
    return (dia + 3) % 7 == 6  # el día 0 (1/1/1970) fue jueves


def _hash(contenido):
    return hashlib.sha256(contenido).hexdigest()


# ---------- Preregistro ----------

def _en_git():
    """El JSON tal como quedó en el commit etiquetado."""
    try:
        r = subprocess.run(["git", "-C", str(REPO), "show", f"{TAG}:{RUTA_EN_GIT}"], capture_output=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        raise ErrorPreregistro("No se puede comprobar el preregistro: hace falta git instalado.")
    if r.returncode:
        raise ErrorPreregistro(f"No existe el tag {TAG} con {RUTA_EN_GIT}: sin preregistro no hay backtest.")
    return r.stdout


def verificar_preregistro():
    """Devuelve el sha256 del JSON si coincide byte a byte con el del tag; si no, se niega."""
    local = PREREG.read_bytes()
    if _hash(local) != _hash(_en_git()):
        raise ErrorPreregistro("trend_v1.json no coincide con el preregistro del tag prereg-trend-v1. Si quieres "
                               "cambiar algo, es otra estrategia: créala como trend_v2 con su propio preregistro.")
    return _hash(local)


def preregistro():
    return json.loads(PREREG.read_text(encoding="utf-8"))


# ---------- Series e indicadores ----------

def _volatilidades(rend, n):
    """Por vela, la volatilidad anual de sus n últimos rendimientos (rend[i-1] es el de la vela i)."""
    salida = [None] * (len(rend) + 1)
    for i in range(n, len(rend) + 1):
        salida[i] = statistics.stdev(rend[i - n:i]) * RAIZ_ANIO
    return salida


class Serie:
    """Las velas de una moneda con sus indicadores. El valor de la vela i solo usa velas hasta la i."""

    def __init__(self, velas, media, regimen=None):
        self.velas = velas
        self.indice = {v["time"] // DIA: i for i, v in enumerate(velas)}
        c = self.cierre = [v["close"] for v in velas]
        acum = [0.0]
        for x in c:
            acum.append(acum[-1] + x)
        self.media = [(acum[i + 1] - acum[i + 1 - media]) / media if i >= media - 1 else None for i in range(len(c))]
        rend = [c[i] / c[i - 1] - 1 for i in range(1, len(c))]
        self.vol_peso = _volatilidades(rend, P["vol_peso"])
        if regimen:  # (días de volatilidad, días de la mediana): solo para BTC
            n, ventana = regimen
            self.vol_regimen = _volatilidades(rend, n)
            self.mediana = [statistics.median(self.vol_regimen[i - ventana + 1:i + 1]) if i - ventana + 1 >= n else None
                            for i in range(len(c))]

    def en(self, dia):
        return self.indice.get(dia)


# ---------- Capas 1 a 4 ----------

def regimen(btc, dia, p=P):
    """Capa 1. Sin datos suficientes no se compra: es lo prudente."""
    i = btc.en(dia)
    if i is None or i < p["pendiente"] or None in (btc.media[i], btc.media[i - p["pendiente"]], btc.mediana[i]):
        return "sin datos"
    if btc.cierre[i] < btc.media[i]:
        return "bajista"
    if btc.vol_regimen[i] > p["extrema"] * btc.mediana[i]:
        return "extrema"
    return "alcista" if btc.media[i] > btc.media[i - p["pendiente"]] else "lateral"


def senal(serie, dia, previa):
    """Capas 2 y 3: larga si cierre > media, pero solo cambia de estado si el sábado y el domingo coinciden."""
    i, j = serie.en(dia), serie.en(dia - 1)
    if i is None or j is None or serie.media[i] is None or serie.media[j] is None:
        return previa
    hoy, ayer = serie.cierre[i] > serie.media[i], serie.cierre[j] > serie.media[j]
    return hoy if hoy == ayer else previa


def pesos_objetivo(estados, series, dia, p=P):
    """Capa 4: volatilidad objetivo con tope por moneda; si suman más del 100 %, se escalan todos."""
    pesos = {}
    for m, larga in estados.items():
        i = series[m].en(dia)
        vol = series[m].vol_peso[i] if i is not None else None
        if not larga or vol is None:
            pesos[m] = 0.0
        else:
            pesos[m] = min(p["tope"], p["vol_objetivo"] / vol) if vol > 0 else p["tope"]
    total = sum(pesos.values())
    return {m: w / total for m, w in pesos.items()} if total > 1 else pesos


def ajustar(objetivo, actual, reg, p=P):
    """Capas 1 y 3 a la hora de ejecutar: el régimen impide comprar más y el filtro ignora cambios pequeños."""
    final = {}
    for m, w in objetivo.items():
        a = actual.get(m, 0.0)
        if reg not in ABREN:
            w = min(w, a)
        cambia = (a == 0 and w > 0) or (a > 0 and w == 0) or (a > 0 and abs(w - a) > p["cambio_min"] * a)
        final[m] = w if cambia else a
    return final


# ---------- Cartera ----------

class Cartera:
    """Capital en tanto por uno (empieza en 1). Sin apalancamiento: la caja nunca queda negativa."""

    def __init__(self):
        self.caja = 1.0
        self.unidades, self.precio, self.resultado, self.costes = {}, {}, {}, {}

    def marcar(self, precios):
        for m, px in precios.items():
            u = self.unidades.get(m, 0.0)
            if u and m in self.precio:
                self.resultado[m] = self.resultado.get(m, 0.0) + u * (px - self.precio[m])
            self.precio[m] = px

    def valor(self):
        return self.caja + sum(u * self.precio[m] for m, u in self.unidades.items() if u)

    def pesos(self):
        total = self.valor()
        return {m: u * self.precio[m] / total for m, u in self.unidades.items() if u}

    def operar(self, finales, operables, coste):
        """Lleva cada moneda operable a su peso final. Devuelve {moneda: (cambio de peso, coste)}, en tanto por
        uno del capital. Si las compras más los costes no caben, se recortan las compras."""
        total = self.valor()
        actual = {m: self.unidades.get(m, 0.0) * self.precio.get(m, 0.0) for m in finales}
        deseado = {m: finales[m] * total if m in operables else actual[m] for m in finales}
        compras = sum(d - actual[m] for m, d in deseado.items() if d > actual[m])
        ventas = sum(actual[m] - d for m, d in deseado.items() if d < actual[m])
        invertido = sum(deseado.values()) + sum(u * self.precio[m] for m, u in self.unidades.items() if u and m not in finales)
        if compras and invertido + coste * (compras + ventas) > total:
            # Recorta las compras en la misma proporción k para que invertido + costes = capital (resuelto exacto).
            k = max(0.0, min(1.0, (total - invertido + compras - coste * ventas) / (compras * (1 + coste))))
            deseado = {m: actual[m] + (d - actual[m]) * k if d > actual[m] else d for m, d in deseado.items()}
        cambios = {}
        for m, d in deseado.items():
            delta = d - actual[m]
            if abs(delta) < 1e-15:
                continue
            c = coste * abs(delta)
            self.caja -= delta + c
            self.unidades[m] = d / self.precio[m] if d > 0 else 0.0
            self.costes[m] = self.costes.get(m, 0.0) + c
            cambios[m] = (delta / total, c / total)
        self.caja = max(self.caja, 0.0) if abs(self.caja) < 1e-12 else self.caja
        return cambios


def _recorrer(series, d0, d1, decidir, ejecutar):
    """El reloj de cualquier cartera: a la apertura ejecuta lo decidido el día anterior, al cierre valora y decide.
    decidir(dia) solo recibe el día: lo que mire de las series es cosa suya (y los tests vigilan que no mire el futuro)."""
    cartera, rend, curva, invertido, dias = Cartera(), [], [], [], {m: 0 for m in series}
    plan, previo = None, 1.0
    for d in range(d0 - 1, d1 + 1):
        if plan is not None:
            aperturas = {m: s.velas[i]["open"] for m, s in series.items() if (i := s.en(d)) is not None}
            cartera.marcar(aperturas)
            ejecutar(d, cartera, plan, aperturas)
            plan = None
        cartera.marcar({m: s.cierre[i] for m, s in series.items() if (i := s.en(d)) is not None})
        valor = cartera.valor()
        if d >= d0:
            rend.append(valor / previo - 1)
            curva.append((d, valor))
            invertido.append(1 - cartera.caja / valor)
            for m, u in cartera.unidades.items():
                dias[m] += u > 0
        previo = valor
        if d < d1:
            plan = decidir(d)
    return cartera, rend, curva, invertido, dias


# ---------- Simulaciones ----------

def simular(velas, monedas, btc, p=P, coste=None, inicio=INICIO, fin=FIN, _desfase=0):
    """trend_v1 completa. _desfase solo existe para los tests: con 1, la decisión del domingo vería el lunes
    (trampa a propósito, para comprobar que sin ella el resultado no mejora)."""
    coste = p["coste"] if coste is None else coste
    series = {m: Serie(velas[m], p["media"]) for m in monedas}
    sbtc = Serie(btc, p["media"], (p["vol_regimen"], p["ventana_mediana"]))
    estados = dict.fromkeys(monedas, False)
    registro, regimenes, operaciones = [], {}, {m: 0 for m in monedas}
    pagado = dict.fromkeys(monedas, 0.0)  # costes en tanto por uno del capital de cada momento
    rotacion = [0.0]

    def decidir(d):
        if not es_domingo(d):
            return None
        v = d + _desfase
        reg = regimen(sbtc, v, p)
        regimenes[reg] = regimenes.get(reg, 0) + 1
        for m in monedas:
            estados[m] = senal(series[m], v, estados[m])
        return {"dia": d, "regimen": reg, "senales": dict(estados), "objetivo": pesos_objetivo(estados, series, v, p)}

    def ejecutar(d, cartera, plan, aperturas):
        actual = cartera.pesos()
        final = ajustar(plan["objetivo"], actual, plan["regimen"], p)
        cambios = cartera.operar(final, aperturas, coste)
        for m in monedas:
            if series[m].en(plan["dia"]) is None and m not in actual:
                continue  # aún no cotiza: no hay nada que decidir
            delta, c = cambios.get(m, (0.0, 0.0))
            operaciones[m] += bool(delta)
            rotacion[0] += abs(delta)
            pagado[m] += c
            registro.append({"dia": fecha_de(d), "moneda": m, "regimen": plan["regimen"],
                             "senal": "larga" if plan["senales"][m] else "liquidez",
                             "peso_actual": round(actual.get(m, 0.0), 6), "peso_objetivo": round(plan["objetivo"][m], 6),
                             "peso_final": round(actual.get(m, 0.0) + delta, 6), "operada": bool(delta), "coste": c})

    d0, d1 = dia_de(inicio), dia_de(fin)
    cartera, rend, curva, invertido, dias = _recorrer(series, d0, d1, decidir, ejecutar)
    anios = len(rend) / 365
    return {
        "rendimientos": rend, "curva": curva, "registro": registro, "regimenes": regimenes,
        "operaciones": sum(operaciones.values()), "rotacion_anual": rotacion[0] / anios * 100 if anios else None,
        # Coste medio al año en % del capital: sumar dinero cuando el capital se multiplica no se entiende.
        "costes": sum(pagado.values()) / anios * 100 if anios else None,
        "liquidez_pct": sum(x < 1e-9 for x in invertido) / len(invertido) * 100 if invertido else None,
        "invertido_medio": statistics.fmean(invertido) * 100 if invertido else None,
        "pesos_finales": {m: round(w, 4) for m, w in cartera.pesos().items()},
        "por_moneda": {m: {"dias": dias[m], "operaciones": operaciones[m],
                           "resultado": cartera.resultado.get(m, 0.0) * 100, "costes": pagado[m] * 100}
                       for m in monedas},
    }


def comprar_y_mantener(velas_btc, coste=P["coste"], inicio=INICIO, fin=FIN):
    """Referencia: todo en BTC desde la apertura del primer día, pagando la entrada."""
    series = {"BTC": Serie(velas_btc, P["media"])}
    primero = dia_de(inicio) - 1
    _, rend, curva, _, _ = _recorrer(series, dia_de(inicio), dia_de(fin), lambda d: {} if d == primero else None,
                                     lambda d, c, plan, ap: c.operar({"BTC": 1.0}, ap, coste))
    return rend, curva


def pesos_iguales(velas, monedas, coste=P["coste"], inicio=INICIO, fin=FIN):
    """Referencia: a partes iguales entre las monedas que ya cotizan; vuelve a pesos iguales el primer lunes de mes."""
    series = {m: Serie(velas[m], P["media"]) for m in monedas}

    def decidir(d):
        lunes = datetime.fromtimestamp((d + 1) * DIA, timezone.utc)
        if not es_domingo(d) or lunes.day > 7:
            return None
        hay = [m for m in monedas if series[m].en(d) is not None]
        return {m: (1 / len(hay) if m in hay else 0.0) for m in monedas} if hay else None

    _, rend, curva, _, _ = _recorrer(series, dia_de(inicio), dia_de(fin), decidir,
                                     lambda d, c, plan, ap: c.operar(plan, ap, coste))
    return rend, curva


# ---------- Medidas ----------

def sharpe(rend):
    if len(rend) < 2:
        return None
    desv = statistics.stdev(rend)
    return statistics.fmean(rend) / desv * RAIZ_ANIO if desv > 0 else None


def caida_maxima(valores):
    """La mayor caída desde un máximo anterior, en % positivo (25 = perdió un 25 % desde el máximo)."""
    maximo, peor = valores[0], 0.0
    for v in valores:
        maximo = max(maximo, v)
        peor = max(peor, 1 - v / maximo)
    return peor * 100


def por_anio(curva, base=1.0):
    """Rentabilidad de cada año natural, del último cierre del año anterior al último de ese año."""
    salida, previo, anio, ultimo = {}, base, None, base
    for d, v in curva:
        a = fecha_de(d)[:4]
        if anio and a != anio:
            salida[anio] = (ultimo / previo - 1) * 100
            previo = ultimo
        anio, ultimo = a, v
    if anio:
        salida[anio] = (ultimo / previo - 1) * 100
    return salida


def _longitud(azar, bloque):
    """Longitud geométrica con media `bloque`: P(L = l) = (1 - q)^(l - 1) q, con q = 1 / bloque."""
    return int(math.log(1.0 - azar.random()) / math.log(1 - 1 / bloque)) + 1


def bootstrap_sharpe(rend, bloque=BLOQUE, n=REMUESTREOS, semilla=SEMILLA, nivel=NIVEL):
    """Intervalo del Sharpe por bootstrap estacionario (Politis y Romano, 1994). Remuestrea bloques seguidos de
    días, de longitud aleatoria con media `bloque`, dando la vuelta al final: así respeta que un día malo suele
    venir con otros malos. Con sumas acumuladas cada bloque cuesta lo mismo, sea largo o corto."""
    total = len(rend)
    if total < 2:
        return None
    doble = rend + rend
    suma, cuad = [0.0], [0.0]
    for x in doble:
        suma.append(suma[-1] + x)
        cuad.append(cuad[-1] + x * x)
    azar, valores = random.Random(semilla), []
    for _ in range(n):
        s = q = 0.0
        hecho = 0
        while hecho < total:
            ini = azar.randrange(total)
            largo = min(_longitud(azar, bloque), total - hecho)
            s += suma[ini + largo] - suma[ini]
            q += cuad[ini + largo] - cuad[ini]
            hecho += largo
        var = (q - s * s / total) / (total - 1)
        valores.append(s / total / math.sqrt(var) * RAIZ_ANIO if var > 0 else 0.0)
    valores.sort()
    cola = (1 - nivel) / 2
    return [valores[int(cola * n)], valores[math.ceil((1 - cola) * n) - 1]]


def medidas(rend, curva, con_intervalo=False):
    valores = [1.0] + [v for _, v in curva]
    anios = por_anio(curva)
    final = valores[-1]
    return {
        "sharpe": sharpe(rend), "intervalo": bootstrap_sharpe(rend) if con_intervalo else None,
        "caida_maxima": caida_maxima(valores), "rentabilidad": (final - 1) * 100,
        "cagr": (final ** (365 / len(rend)) - 1) * 100 if final > 0 and rend else None,
        "volatilidad": statistics.stdev(rend) * RAIZ_ANIO * 100 if len(rend) > 1 else None,
        "anios": anios, "positivos": sum((anios.get(a) or 0) > 0 for a in ANIOS),
    }


def puntos(m):
    """Los puntos 1 a 3 del criterio sobre unas medidas."""
    ic = m["intervalo"]
    return [
        {"nombre": "Sharpe neto ≥ 0,8 y límite inferior de su intervalo > 0",
         "ok": m["sharpe"] is not None and m["sharpe"] >= SHARPE_MIN and bool(ic) and ic[0] > 0,
         "valor": {"sharpe": m["sharpe"], "intervalo": ic}},
        {"nombre": "Caída máxima ≤ 35 %", "ok": m["caida_maxima"] <= CAIDA_MAX, "valor": m["caida_maxima"]},
        {"nombre": "Positiva en al menos 3 de 2022, 2023, 2024 y 2025", "ok": m["positivos"] >= ANIOS_MIN,
         "valor": m["positivos"]},
    ]


def veredicto(principal, reserva):
    """pasa / no pasa / no demostrado. Hasta ejecutar las reservadas, «pendiente»."""
    if not principal:
        return {"veredicto": "sin ejecutar", "puntos": [], "texto": "Aún no se ha ejecutado el backtest."}
    lista = list(principal["puntos"])
    lista.append({"nombre": "Las reservadas (DOT, LINK, LTC y UNI) cumplen también los puntos 1 a 3",
                  "ok": bool(reserva) and all(x["ok"] for x in reserva["puntos"]),
                  "valor": None if not reserva else sum(x["ok"] for x in reserva["puntos"]), "pendiente": not reserva})
    ic = principal["medidas"]["intervalo"]
    claramente_debajo = bool(ic) and ic[1] < SHARPE_MIN
    if not reserva:
        texto = ("Faltan las reservadas, que se ejecutan una sola vez al final."
                 + (" Con las principales ya no puede pasar." if not all(x["ok"] for x in principal["puntos"]) else ""))
        return {"veredicto": "pendiente", "puntos": lista, "texto": texto}
    if all(x["ok"] for x in lista):
        return {"veredicto": "pasa", "puntos": lista,
                "texto": "Cumple los cuatro puntos. Siguiente paso: paper trading (Fase C), nunca dinero real directamente."}
    if claramente_debajo:
        return {"veredicto": "no pasa", "puntos": lista,
                "texto": "Ni siquiera el extremo optimista del intervalo llega a un Sharpe de 0,8."}
    return {"veredicto": "no demostrado", "puntos": lista,
            "texto": "Falla algún punto. No se ajusta nada de trend_v1: una variante sería trend_v2, con su propio "
                     "preregistro, y sumaría un intento al contador."}


# ---------- Informes ----------

def _semanal(curva):
    """Un punto por domingo y el último, para la gráfica."""
    return [(d, round(v, 6)) for i, (d, v) in enumerate(curva) if es_domingo(d) or i == len(curva) - 1]


def _correlacion_btc(velas, monedas, btc, inicio=INICIO, fin=FIN):
    d0, d1 = dia_de(inicio), dia_de(fin)

    def cierres(velas_):
        return {v["time"] // DIA: v["close"] for v in velas_ if d0 - 1 <= v["time"] // DIA <= d1}

    b = cierres(btc)
    salida = {}
    for m in monedas:
        c = cierres(velas[m])
        dias = sorted(d for d in c if d in b and d - 1 in c and d - 1 in b)
        if len(dias) > 30:
            salida[m] = statistics.correlation([c[d] / c[d - 1] - 1 for d in dias], [b[d] / b[d - 1] - 1 for d in dias])
    return salida


AVISOS = [
    "Sesgo de supervivencia: el universo son monedas que existen y son grandes hoy. Las que se hundieron o "
    "desaparecieron desde 2018 no están, y eso infla cualquier backtest.",
    "Las monedas del universo se mueven casi a la vez que BTC (mira su correlación por moneda): 8 monedas no son "
    "8 apuestas independientes, sino algo más parecido a una apuesta grande sobre cripto.",
    "Un backtest es una sola historia posible del pasado. Aunque pase, el siguiente paso es el paper trading, no el dinero real.",
]


def informe(velas, monedas, btc, avance=lambda texto: None):
    """Todo lo que pinta la pestaña Estrategia para las monedas principales."""
    avance("Simulando trend_v1")
    base = simular(velas, monedas, btc)
    avance("Calculando el intervalo bootstrap (5.000 remuestreos)")
    m = medidas(base["rendimientos"], base["curva"], con_intervalo=True)
    avance("Referencias, costes y robustez")
    rb, cb = comprar_y_mantener(btc)
    ri, ci = pesos_iguales(velas, monedas)
    variantes = {"Costes de 0,52 % por lado": simular(velas, monedas, btc, coste=COSTE_ALTO),
                 "Media de 50 días": simular(velas, monedas, btc, {**P, "media": 50}),
                 "Media de 150 días": simular(velas, monedas, btc, {**P, "media": 150})}
    curva_btc, curva_ig = dict(cb), dict(ci)
    return {
        "medidas": m, "puntos": puntos(m),
        "operaciones": base["operaciones"], "rotacion_anual": base["rotacion_anual"], "costes": base["costes"],
        "liquidez_pct": base["liquidez_pct"], "invertido_medio": base["invertido_medio"],
        "regimenes": base["regimenes"], "pesos_finales": base["pesos_finales"], "por_moneda": base["por_moneda"],
        "referencias": {"BTC comprar y mantener": medidas(rb, cb), "Universo a pesos iguales": medidas(ri, ci)},
        "variantes": {k: {**medidas(v["rendimientos"], v["curva"]), "operaciones": v["operaciones"]}
                      for k, v in variantes.items()},
        "correlacion_btc": _correlacion_btc(velas, monedas, btc),
        "curva": [(d, v, curva_btc.get(d), curva_ig.get(d)) for d, v in _semanal(base["curva"])],
        "avisos": AVISOS, "registro": base["registro"],
    }


def informe_reserva(velas, monedas, btc, avance=lambda texto: None):
    """Las reservadas, solas y con el régimen de BTC: mismos puntos 1 a 3."""
    avance("Simulando trend_v1 con las reservadas")
    base = simular(velas, monedas, btc)
    avance("Calculando el intervalo bootstrap (5.000 remuestreos)")
    m = medidas(base["rendimientos"], base["curva"], con_intervalo=True)
    return {"medidas": m, "puntos": puntos(m), "operaciones": base["operaciones"], "costes": base["costes"],
            "liquidez_pct": base["liquidez_pct"], "por_moneda": base["por_moneda"],
            "correlacion_btc": _correlacion_btc(velas, monedas, btc),
            "curva": [(d, v) for d, v in _semanal(base["curva"])], "registro": base["registro"]}


# ---------- Ejecución ----------

def cargar_velas(monedas, tickers, avance=lambda texto: None):
    """Descarga una vez y guarda: repetir el backtest usa exactamente los mismos datos aunque Yahoo los corrija."""
    guardadas = datos.simulacion(CLAVE_VELAS) or {}
    guardadas.pop("creado", None)
    faltan = [m for m in monedas if m not in guardadas]
    for n, m in enumerate(faltan, 1):
        avance(f"Descargando {m} de Yahoo ({n} de {len(faltan)})")
        guardadas[m] = mercado.diarias(tickers[m], DESCARGA_DESDE, FIN)
        if not guardadas[m]:
            raise ErrorEstrategia(f"Yahoo no devolvió velas de {tickers[m]}.")
        time.sleep(0.5)
    if faltan:
        datos.guardar_simulacion(CLAVE_VELAS, guardadas)
    return {m: guardadas[m] for m in monedas}


def correr(reserva=False, avance=lambda texto: None):
    huella = verificar_preregistro()
    if reserva:
        if not datos.simulacion(CLAVE):
            raise ErrorEstrategia("Primero hay que ejecutar las monedas principales.")
        if datos.simulacion(CLAVE_RESERVA):
            raise ErrorEstrategia("Las reservadas ya se ejecutaron: el preregistro solo permite hacerlo una vez.")
    universo = preregistro()["universo"]
    monedas = universo["reservadas" if reserva else "principales"]
    velas = cargar_velas(sorted(set(monedas) | {"BTC"}), universo["tickers_yahoo"], avance)
    r = (informe_reserva if reserva else informe)(velas, monedas, velas["BTC"], avance)
    clave = CLAVE_RESERVA if reserva else CLAVE
    codigo = _hash(Path(__file__).read_bytes())
    previo = datos.simulacion(clave) or {}
    r.update(monedas=monedas, preregistro=huella, codigo=codigo, desde=INICIO, hasta=FIN,
             datos=_hash(json.dumps(velas, sort_keys=True).encode()),
             historial=previo.get("historial", []) + [{"fecha": int(time.time()), "codigo": codigo,
                                                        "sharpe": r["medidas"]["sharpe"]}])
    datos.guardar_decisiones("reserva" if reserva else "backtest", r.pop("registro"))
    datos.guardar_simulacion(clave, r)
    datos.actualizar_prueba("trend_v1", veredicto(datos.simulacion(CLAVE), datos.simulacion(CLAVE_RESERVA))["veredicto"])
    return r


_lock = threading.Lock()
_estado = {"activo": False, "fase": "", "error": None, "fin": None}


def estado():
    with _lock:
        return dict(_estado)


def _avanza(**cambios):
    with _lock:
        _estado.update(cambios)


def _hilo(reserva):
    try:
        correr(reserva, lambda texto: _avanza(fase=texto))
        _avanza(activo=False, fase="Listo", fin=time.time())
    except Exception as e:
        if not isinstance(e, ErrorEstrategia):
            traceback.print_exc()
        _avanza(activo=False, error=str(e), fin=time.time())


def lanzar(reserva=False):
    with _lock:
        if _estado["activo"]:
            return "Ya hay un backtest de trend_v1 en marcha."
        _estado.update(activo=True, fase="Empezando", error=None, fin=None)
    threading.Thread(target=_hilo, args=(reserva,), daemon=True).start()
    return None


def eventos(principal, dias=30):
    """Capa 5: noticias de importancia ≥ 4 y alertas de cada moneda con posición. Solo informan; no deciden."""
    if not principal:
        return {}
    tickers = preregistro()["universo"]["tickers_yahoo"]
    desde = int(time.time()) - dias * DIA
    noticias, alertas = datos.analisis_importantes(desde, 4), datos.alertas(desde)
    salida = {}
    for m, peso in sorted((principal.get("pesos_finales") or {}).items()):
        t = tickers[m]
        salida[m] = {
            "peso": peso, "ticker": t,
            "noticias": [{"titulo": n["titulo"], "importancia": n["importancia"], "creado": n["creado"], "url": n["url"],
                          "fuente": n["fuente"]} for n in noticias if any(i.get("simbolo") == t for i in n["impactos"])][-5:],
            "alertas": [{"titulo": a["titulo"], "tipo": a["tipo"], "creada": a["creada"]}
                        for a in alertas if a["simbolo"] == t][:5],
        }
    return salida


def vista():
    """Lo que necesita la pestaña Estrategia, sin calcular nada pesado."""
    try:
        pre = {"ok": True, "hash": verificar_preregistro(), "tag": TAG}
    except ErrorEstrategia as e:
        pre = {"ok": False, "error": str(e), "tag": TAG}
    principal, reserva = datos.simulacion(CLAVE), datos.simulacion(CLAVE_RESERVA)
    return {"preregistro": pre, "estado": estado(), "principal": principal, "reserva": reserva,
            "veredicto": veredicto(principal, reserva), "pruebas": datos.pruebas(),
            "decisiones": datos.decisiones("backtest", 24), "eventos": eventos(principal)}


# ---------- Línea de comandos ----------

def _num(v, dec=2):
    return "—" if v is None else f"{v:,.{dec}f}".replace(",", " ").replace(".", ",")


def texto(r, reserva):
    m = r["medidas"]
    lineas = [f"trend_v1 · {'reservadas' if reserva else 'principales'}: {', '.join(r['monedas'])} · {r['desde']} a {r['hasta']}",
              f"Sharpe {_num(m['sharpe'])} (intervalo 95 %: {_num(m['intervalo'][0])} a {_num(m['intervalo'][1])})",
              f"Caída máxima {_num(m['caida_maxima'], 1)} % · rentabilidad {_num(m['rentabilidad'], 1)} % · CAGR {_num(m['cagr'], 1)} %",
              "Años: " + " · ".join(f"{a} {_num(v, 1)} %" for a, v in m["anios"].items()),
              f"Operaciones {r['operaciones']} · en liquidez el {_num(r['liquidez_pct'], 1)} % de los días"]
    lineas += [f"{'✓' if p['ok'] else '✗'} {p['nombre']}" for p in r["puntos"]]
    v = veredicto(datos.simulacion(CLAVE), datos.simulacion(CLAVE_RESERVA))
    lineas.append(f"Veredicto: {v['veredicto']}. {v['texto']}")
    return "\n".join(lineas)


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if not argv or argv[0] != "backtest":
        print(__doc__)
        return 2
    reserva = "--reserva" in argv
    try:
        r = correr(reserva, print)
    except ErrorEstrategia as e:
        print(f"No se ejecuta: {e}")
        return 1
    print(texto(r, reserva))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
