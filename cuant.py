"""Datos cuantitativos que calcula Python y el modelo recibe ya hechos.

- Acciones: revisiones de estimaciones y posiciones cortas (Yahoo), insiders (EDGAR, en edgar.py).
- Cripto: funding e interés abierto (Hyperliquid y Kraken Futures, APIs públicas).
- Todos: volumen relativo, de las velas diarias.
- Macro: tipos de EE. UU. y curva (Yahoo), y con clave de FRED, más series.

Las funciones de cálculo son puras: reciben la respuesta ya descargada y devuelven números, o None si falta
el dato. Nunca se rellena un hueco con nada: un "s/d" es información.
"""
import json
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

import datos
import edgar
import marcador
import mercado

UA = {"User-Agent": "Radar/1.0 (app local de mercado)"}
HORAS_ANIO = 24 * 365
TIPOS_YAHOO = [("^IRX", "3 meses"), ("^FVX", "5 años"), ("^TNX", "10 años"), ("^TYX", "30 años")]
SERIES_FRED = [("DFF", "tipo efectivo de la Fed"), ("T10Y2Y", "curva 10 años menos 2"),
               ("BAMLH0A0HYM2", "diferencial high yield"), ("T10YIE", "inflación esperada a 10 años")]


def _num(v):
    """raw de Yahoo, o None."""
    return v.get("raw") if isinstance(v, dict) else v if isinstance(v, (int, float)) else None


def _cambio(nuevo, viejo):
    return (nuevo / viejo - 1) * 100 if nuevo is not None and viejo else None


# ---------- Cálculos puros ----------

def revisiones(resumen):
    """Cuánto han cambiado las estimaciones de BPA del año fiscal en curso y cuántas revisiones hubo."""
    trend = next((t for t in (resumen.get("earningsTrend") or {}).get("trend", []) if t.get("period") == "0y"), None)
    if not trend:
        return None
    eps, rev = trend.get("epsTrend") or {}, trend.get("epsRevisions") or {}
    actual = _num(eps.get("current"))
    if actual is None:
        return None
    return {"bpa": actual, "cambio_30d": _cambio(actual, _num(eps.get("30daysAgo"))),
            "cambio_90d": _cambio(actual, _num(eps.get("90daysAgo"))),
            "suben_30d": _num(rev.get("upLast30days")) or 0, "bajan_30d": _num(rev.get("downLast30days")) or 0}


def cortos(resumen):
    k = resumen.get("defaultKeyStatistics") or {}
    pct = _num(k.get("shortPercentOfFloat"))
    if pct is None:
        return None
    fecha = _num(k.get("dateShortInterest"))
    return {"pct_flotante": pct * 100, "cambio_mes": _cambio(_num(k.get("sharesShort")), _num(k.get("sharesShortPriorMonth"))),
            "dias_cubrir": _num(k.get("shortRatio")),
            "fecha": datetime.fromtimestamp(fecha, timezone.utc).date().isoformat() if fecha else None}


def volumen_relativo(velas, ahora):
    """Volumen de la última sesión completa frente a la media de las 20 anteriores. La vela de hoy está a
    medias: se usa la anterior."""
    completas = [v for v in velas if v["time"] + 86400 <= ahora]
    if len(completas) < 21:
        return None
    ultima, previas = completas[-1], completas[-21:-1]
    media = sum(v["volume"] for v in previas) / 20
    if not media or not ultima["volume"]:
        return None
    return {"relativo": ultima["volume"] / media, "movimiento": _cambio(ultima["close"], completas[-2]["close"]),
            "dia": datetime.fromtimestamp(ultima["time"], timezone.utc).date().isoformat()}


def funding_hyperliquid(respuesta, ticker):
    """Hyperliquid da el funding como tanto por uno por hora y el interés abierto en monedas."""
    meta, contextos = respuesta
    nombres = [u["name"] for u in meta["universe"]]
    if ticker not in nombres:
        return None
    c = contextos[nombres.index(ticker)]
    precio = float(c["markPx"])
    return {"funding_anual": float(c["funding"]) * HORAS_ANIO * 100, "oi_usd": float(c["openInterest"]) * precio,
            "prima": float(c.get("premium") or 0) * 100}


def funding_kraken(tickers, ticker):
    """Kraken Futures da el funding en dólares por contrato y hora: se divide por el precio para compararlo."""
    simbolo = f"PF_{'XBT' if ticker == 'BTC' else ticker}USD"
    t = next((x for x in tickers if x.get("symbol", "").upper() == simbolo), None)
    if not t or not t.get("markPrice") or t.get("fundingRate") is None:
        return None
    return {"funding_anual": t["fundingRate"] / t["markPrice"] * HORAS_ANIO * 100,
            "oi_usd": (t.get("openInterest") or 0) * t["markPrice"]}


def fred_ultimo(respuesta):
    """(último valor, valor de hace unos 30 días) de una serie de FRED, ordenada de más reciente a más antigua."""
    obs = [(o["date"], float(o["value"])) for o in json.loads(respuesta).get("observations", []) if o["value"] != "."]
    if not obs:
        return None, None
    limite = (date.fromisoformat(obs[0][0]) - timedelta(days=30)).isoformat()
    previo = next((v for d, v in obs if d <= limite), None)
    return obs[0][1], previo


# ---------- Descargas ----------

def _json(url, cuerpo=None):
    datos_ = json.dumps(cuerpo).encode() if cuerpo is not None else None
    peticion = urllib.request.Request(url, data=datos_, headers={**UA, "Content-Type": "application/json"})
    with urllib.request.urlopen(peticion, timeout=15) as r:
        return json.loads(r.read())


def _hyperliquid():
    return mercado._cacheado(("hyperliquid",), 600, lambda: _json("https://api.hyperliquid.xyz/info",
                                                                  {"type": "metaAndAssetCtxs"}))


def _kraken():
    return mercado._cacheado(("kraken_tickers",), 600, lambda: _json(
        "https://futures.kraken.com/derivatives/api/v3/tickers")["tickers"])


def _seguro(funcion, *args):
    try:
        return funcion(*args)
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, IndexError, TypeError, edgar.ErrorEdgar):
        return None


def cripto(simbolo, ahora):
    ticker = marcador.ticker_de(simbolo)
    hl = _seguro(lambda: funding_hyperliquid(_hyperliquid(), ticker))
    kr = _seguro(lambda: funding_kraken(_kraken(), ticker))
    if not hl and not kr:
        return None
    oi = (hl or kr)["oi_usd"]
    hace = lambda dias: (datos.cuant_de(simbolo, (datetime.fromtimestamp(ahora).date() - timedelta(days=dias)).isoformat())
                         or {}).get("cripto", {}).get("oi_usd")
    return {"funding_hl": hl and hl["funding_anual"], "funding_kraken": kr and kr["funding_anual"],
            "prima": hl and hl["prima"], "oi_usd": oi, "oi_24h": _cambio(oi, hace(1)), "oi_7d": _cambio(oi, hace(7))}


def de_activo(simbolo, ahora=None, con_insiders=True):
    """Todo lo cuantitativo de un activo. Se guarda en caché unas horas. Los insiders pueden tardar la primera
    vez (decenas de Form 4 a ritmo de la SEC): con muchos activos a la vez se pueden dejar fuera."""
    ahora = ahora or time.time()

    def cargar():
        salida = {"simbolo": simbolo}
        try:
            salida["volumen"] = volumen_relativo(mercado.velas(simbolo, "1d")["velas"], ahora)
        except mercado.ErrorMercado:
            salida["volumen"] = None
        if marcador.es_cripto(simbolo):
            salida["cripto"] = cripto(simbolo, ahora)
        else:
            resumen = mercado.resumen_yahoo(simbolo, ["earningsTrend", "defaultKeyStatistics"])
            salida["revisiones"] = revisiones(resumen)
            salida["cortos"] = cortos(resumen)
            if con_insiders:
                salida["insiders"] = _seguro(edgar.resumen, simbolo)
        return salida

    return mercado._cacheado(("cuant", simbolo, con_insiders), 3 * 3600, cargar)


def macro():
    def cargar():
        salida = {"tipos": {}, "fred": {}}
        for simbolo, nombre in TIPOS_YAHOO:
            try:
                velas = mercado.velas(simbolo, "1d")["velas"]
            except mercado.ErrorMercado:
                continue
            hace_mes = next((v["close"] for v in reversed(velas) if v["time"] <= velas[-1]["time"] - 30 * 86400), None)
            salida["tipos"][nombre] = {"valor": velas[-1]["close"], "hace_mes": hace_mes}
        clave = datos.ajustes()["fred_key"]
        for serie, nombre in SERIES_FRED if clave else []:
            url = "https://api.stlouisfed.org/fred/series/observations?" + urlencode(
                {"series_id": serie, "api_key": clave, "file_type": "json", "sort_order": "desc", "limit": 60})
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15) as r:
                    valor, previo = fred_ultimo(r.read())
            except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
                continue
            if valor is not None:
                salida["fred"][nombre] = {"valor": valor, "hace_mes": previo}
        return salida

    return mercado._cacheado(("macro",), 6 * 3600, cargar)


# ---------- Texto para el modelo ----------

def _es(v, decimales=1, signo=False):
    if v is None:
        return "s/d"
    texto = format(v, f"{'+' if signo else ''},.{decimales}f").translate(str.maketrans(",.", ".,"))
    return texto


def _millones(v):
    return "s/d" if v is None else f"{_es(v / 1e6, 0)} M$"


def texto_activo(c):
    """Líneas en español con lo que se ha medido. Lo que no hay se dice."""
    lineas = []
    if c.get("revisiones"):
        r = c["revisiones"]
        lineas.append(f"Revisiones del BPA estimado del año fiscal: {_es(r['cambio_30d'], signo=True)} % en 30 días y "
                      f"{_es(r['cambio_90d'], signo=True)} % en 90; {r['suben_30d']} revisiones al alza y "
                      f"{r['bajan_30d']} a la baja en 30 días.")
    if "insiders" in c:
        i = c["insiders"]
        lineas.append("Insiders (Form 4 de la SEC, 90 días): " + (
            f"{i['compras']} compras en el mercado por {_millones(i['valor_compras'])} de {i['compradores']} personas; "
            f"{i['ventas']} ventas por {_millones(i['valor_ventas'])}. No cuentan premios, ejercicios de opciones ni "
            "donaciones." if i else "s/d (sin contacto para la SEC o sin datos)."))
    if c.get("cortos"):
        k = c["cortos"]
        lineas.append(f"Posiciones cortas: {_es(k['pct_flotante'])} % del capital flotante, {_es(k['cambio_mes'], signo=True)} % "
                      f"frente al mes anterior; {_es(k['dias_cubrir'])} días para cubrirlas (dato del {k['fecha'] or 's/d'}).")
    if c.get("cripto"):
        k = c["cripto"]
        lineas.append(f"Perpetuos: funding {_es(k['funding_hl'], signo=True)} % anual en Hyperliquid (incluye un interés "
                      f"fijo de unos +11 % anuales: ese valor es neutro) y "
                      f"{_es(k['funding_kraken'], signo=True)} % en Kraken; prima {_es(k['prima'], 2, True)} %; interés "
                      f"abierto {_millones(k['oi_usd'])} ({_es(k['oi_24h'], signo=True)} % en 24 h, "
                      f"{_es(k['oi_7d'], signo=True)} % en 7 días).")
    if c.get("volumen"):
        v = c["volumen"]
        lineas.append(f"Volumen de la última sesión completa ({v['dia']}): {_es(v['relativo'])} veces la media de 20 "
                      f"sesiones, con un movimiento de {_es(v['movimiento'], signo=True)} %.")
    return lineas


def texto_macro(m):
    t = m["tipos"]
    partes = [f"{n} {_es(x['valor'], 2)} % ({_es(x['valor'] - x['hace_mes'], 2, True) if x['hace_mes'] else 's/d'} pp en un mes)"
              for n, x in t.items()]
    lineas = ["Bonos de EE. UU.: " + "; ".join(partes) + "." if partes else "Bonos de EE. UU.: s/d."]
    if "10 años" in t and "3 meses" in t:
        lineas.append(f"Curva 10 años menos 3 meses: {_es(t['10 años']['valor'] - t['3 meses']['valor'], 2, True)} pp.")
    for nombre, x in m["fred"].items():
        cambio = _es(x["valor"] - x["hace_mes"], 2, True) if x["hace_mes"] is not None else "s/d"
        lineas.append(f"FRED, {nombre}: {_es(x['valor'], 2)} ({cambio} en un mes).")
    return lineas


def bloque(simbolos, con_macro=True, con_insiders=True):
    """El bloque <datos_cuantitativos> para el modelo."""
    lineas = []
    for s in simbolos:
        filas = texto_activo(de_activo(s, con_insiders=con_insiders))
        if filas:
            lineas.append(f"{s}:\n  " + "\n  ".join(filas))
    if con_macro:
        lineas += texto_macro(macro())
    return "<datos_cuantitativos>\n" + "\n".join(lineas) + "\n</datos_cuantitativos>\n" if lineas else ""


def bloque_seguro(simbolos, con_macro=True, con_insiders=True):
    """bloque(), pero un fallo inesperado deja el bloque vacío en vez de tumbar un análisis."""
    try:
        return bloque(simbolos, con_macro, con_insiders)
    except Exception:
        return ""


def foto_diaria(simbolos, ahora=None):
    """Guarda los datos de hoy de cada activo: dan los cambios de mañana y el historial para el backtest."""
    ahora = ahora or time.time()
    dia = datetime.fromtimestamp(ahora).date().isoformat()
    for s in simbolos:
        datos.guardar_cuant(s, dia, de_activo(s, ahora))
