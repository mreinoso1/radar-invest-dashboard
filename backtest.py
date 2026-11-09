"""Backtest de las reglas que se pueden reproducir con datos pasados, sin mirar el futuro.

- volumen: velas diarias de Yahoo, 10 años.
- funding: historial de Hyperliquid (desde 2023 para BTC; cada moneda desde que cotiza allí).
- insiders: Form 4 de EDGAR, con su fecha de presentación. Opcional: la primera vez son miles de peticiones.
La regla de revisiones no se puede reproducir (no hay historial gratuito de estimaciones), ni las señales del
modelo (Claude sabe lo que pasó después de las noticias antiguas): esas solo cuentan en el paper trading.

Sin mirar el futuro: la señal del día d solo usa datos hasta el cierre de d y entra a la apertura de d+1.
Las funciones que generan señales reciben solo los datos; así un test puede cambiar el futuro y comprobar
que el pasado no se entera.

Ojo con el sesgo de supervivencia: el universo es la cartera y la watchlist de hoy, empresas que sabemos que
sobrevivieron. Un backtest que pasa es una pista, no una prueba; por eso el criterio pide además paper trading.
"""
import json
import threading
import time
import traceback
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

import criterio
import cuant
import datos
import edgar
import marcador
import mercado
import reglas
import simulador

DIA = simulador.DIA
INDICES = ("SPY", "BTC-USD")
ANIOS_INSIDERS = 3
INCLUIDAS = ["volumen", "funding"]
_lock = threading.Lock()
_estado = {"activo": False, "fase": "", "hecho": 0, "total": 0, "error": None, "fin": None}


def estado():
    with _lock:
        return dict(_estado)


def _avanza(**cambios):
    with _lock:
        _estado.update(cambios)


def _senal(regla, simbolo, direccion, t, detalle):
    return {"id": f"bt:{regla}:{simbolo}:{t}", "simbolo": simbolo, "direccion": direccion, "t": t, "precio": None,
            "horizonte": reglas.HORIZONTES[regla], "origen": "reglas", "tipo": f"reglas:{regla}", "detalle": detalle}


def _sin_repetir(senales):
    """Como en vivo: una regla no repite señal sobre un activo mientras la anterior siga pendiente."""
    salida, hasta = [], {}
    for s in sorted(senales, key=lambda s: s["t"]):
        clave = (s["tipo"], s["simbolo"])
        if s["t"] >= hasta.get(clave, 0):
            salida.append(s)
            hasta[clave] = s["t"] + marcador.PLAZOS[s["horizonte"]]
    return salida


def senales_volumen(simbolo, velas):
    salida = []
    for i in range(21, len(velas)):
        # Las 22 últimas velas hasta el cierre de i: lo que se sabía ese día, nada después.
        v = cuant.volumen_relativo(velas[i - 21:i + 1], velas[i]["time"] + DIA)
        for regla, direccion, detalle in reglas.evaluar({"volumen": v}) if v else []:
            salida.append(_senal(regla, simbolo, direccion, velas[i]["time"], detalle))
    return _sin_repetir(salida)


def funding_diario(filas):
    """{día: funding anual en %} con el último dato de cada día (UTC). filas: (t en ms, tasa por hora)."""
    salida = {}
    for t, tasa in filas:
        salida[t // 1000 // DIA] = tasa * cuant.HORAS_ANIO * 100
    return salida


def senales_funding(simbolo, por_dia):
    salida = []
    for dia, anual in sorted(por_dia.items()):
        for regla, direccion, detalle in reglas.evaluar({"cripto": {"funding_hl": anual, "funding_kraken": None}}):
            salida.append(_senal(regla, simbolo, direccion, dia * DIA, detalle))
    return _sin_repetir(salida)


def senales_insiders(simbolo, transacciones):
    """transacciones: [(fecha de presentación AAAA-MM-DD, transacción)]. Se evalúa cada día en que se presentó
    algo, con lo presentado en los 90 días anteriores."""
    salida = []
    fechas = sorted({f for f, _ in transacciones})
    for f in fechas:
        hasta = date.fromisoformat(f)
        ventana = [t for g, t in transacciones if hasta - timedelta(days=90) < date.fromisoformat(g) <= hasta]
        for regla, direccion, detalle in reglas.evaluar({"insiders": edgar.resumir(ventana)}):
            dia = int(datetime(hasta.year, hasta.month, hasta.day, tzinfo=timezone.utc).timestamp())
            salida.append(_senal(regla, simbolo, direccion, dia, detalle))
    return _sin_repetir(salida)


def ejecutar(velas, indices, funding_por_simbolo, insiders_por_simbolo, cfg, incluidas):
    """El backtest con los datos ya descargados: señales, simulación, desglose por regla y criterio."""
    senales = []
    for s, v in velas.items():
        if "volumen" in incluidas:
            senales += senales_volumen(s, v)
        if "funding" in incluidas and s in funding_por_simbolo:
            senales += senales_funding(s, funding_por_simbolo[s])
        if "insiders" in incluidas and s in insiders_por_simbolo:
            senales += senales_insiders(s, insiders_por_simbolo[s])
    r = simulador.simular(senales, velas, cfg, indices)
    dias = [d for d, _ in r["curva"]]
    por_regla = {}
    for o in r["operaciones"]:
        por_regla.setdefault(o["tipo"], []).append(o)
    return {
        **r,
        "senales": len(senales),
        "incluidas": sorted(incluidas),
        "huella": criterio.huella(cfg, incluidas),
        "indices": {n: simulador.curva_indice(v, dias, cfg["capital"]) for n, v in indices.items()},
        "por_regla": [{"tipo": t, "operaciones": len(ops), "exceso_medio": sum(o["exceso"] for o in ops) / len(ops),
                       "aciertos": sum(o["resultado"] > 0 for o in ops) / len(ops) * 100} for t, ops in sorted(por_regla.items())],
        "criterio": criterio.evaluar_backtest(r, indices, len(incluidas)),
    }


PAUSA_HL = 1.0       # segundos entre páginas: Hyperliquid limita el ritmo
REINTENTOS_HL = 5


def _hyperliquid(cuerpo):
    peticion = urllib.request.Request("https://api.hyperliquid.xyz/info", data=json.dumps(cuerpo).encode(),
                                      headers={**cuant.UA, "Content-Type": "application/json"})
    for intento in range(REINTENTOS_HL):
        try:
            with urllib.request.urlopen(peticion, timeout=20) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code != 429 or intento == REINTENTOS_HL - 1:
                raise
            time.sleep(2 ** (intento + 1))  # nos pide ir más despacio: 2, 4, 8, 16 segundos


def descargar_funding(moneda):
    """Completa el historial guardado de una moneda: 500 registros horarios por petición. Lo descargado se
    guarda página a página, así un fallo a medias no pierde lo anterior."""
    guardado = datos.funding(moneda)
    inicio = guardado[-1][0] + 1 if guardado else 0
    while True:
        filas = _hyperliquid({"type": "fundingHistory", "coin": moneda, "startTime": inicio})
        if not filas:
            break
        datos.guardar_funding(moneda, [(f["time"], float(f["fundingRate"])) for f in filas])
        inicio = filas[-1]["time"] + 1
        if len(filas) < 500:
            break
        time.sleep(PAUSA_HL)
    return datos.funding(moneda)


def _correr(con_insiders):
    try:
        cfg = simulador.config_actual(datos.ajustes())
        incluidas = INCLUIDAS + (["insiders"] if con_insiders else [])
        simbolos = [p["simbolo"] for p in datos.posiciones()]
        _avanza(fase="Descargando velas diarias", hecho=0, total=len(simbolos) + len(INDICES))
        velas, indices = {}, {}
        for n, s in enumerate(simbolos + list(INDICES), 1):
            try:
                v = mercado.velas(s, "1d")["velas"]
            except mercado.ErrorMercado:
                v = None
            if v:
                (indices if s in INDICES else velas)[s] = v
                if s in INDICES and s in simbolos:
                    velas[s] = v
            _avanza(hecho=n)
        cripto = [s for s in velas if marcador.es_cripto(s)]
        _avanza(fase="Descargando el funding de Hyperliquid", hecho=0, total=len(cripto))
        funding, avisos = {}, []
        for n, s in enumerate(cripto, 1):
            moneda = marcador.ticker_de(s)
            try:
                filas = descargar_funding(moneda)
            except (urllib.error.URLError, TimeoutError, ValueError) as e:
                # Nunca en silencio: se usa lo que ya estuviera guardado y se avisa de que está incompleto.
                filas = datos.funding(moneda)
                avisos.append(f"El funding de {moneda} quedó incompleto ({getattr(e, 'reason', e)}); "
                              f"se usan {len(filas)} horas guardadas. Vuelve a lanzar el backtest para completarlo.")
            if filas:  # una moneda que no cotiza en Hyperliquid no tiene historial: esa regla no se le aplica
                funding[s] = funding_diario(filas)
            _avanza(hecho=n)
        insiders = {}
        if con_insiders:
            desde = (date.today() - timedelta(days=int(ANIOS_INSIDERS * 365.25))).isoformat()
            acciones = [s for s in velas if not marcador.es_cripto(s)]
            for n, s in enumerate(acciones, 1):
                _avanza(fase=f"Leyendo Form 4 de {s} en EDGAR ({n} de {len(acciones)})", hecho=0, total=0)
                try:
                    insiders[s] = edgar.historial(s, desde, lambda h, t: _avanza(hecho=h, total=t))
                except edgar.ErrorEdgar as e:
                    raise RuntimeError(f"EDGAR: {e}")
        _avanza(fase="Simulando", hecho=0, total=0)
        resultado = ejecutar(velas, indices, funding, insiders, cfg, incluidas)
        resultado["universo"] = sorted(velas)
        resultado["avisos"] = avisos
        resultado["con_funding"] = sorted(funding)
        datos.guardar_simulacion("backtest", resultado)
        _avanza(activo=False, fase="Listo", fin=time.time())
    except Exception as e:
        traceback.print_exc()
        _avanza(activo=False, error=str(e), fin=time.time())


def lanzar(con_insiders=False):
    with _lock:
        if _estado["activo"]:
            return "Ya hay un backtest en marcha."
        if con_insiders and not datos.ajustes()["sec_contacto"]:
            return "Para incluir insiders hace falta el contacto para la SEC en Ajustes."
        _estado.update(activo=True, fase="Empezando", hecho=0, total=0, error=None, fin=None)
    threading.Thread(target=_correr, args=(con_insiders,), daemon=True).start()
    return None
