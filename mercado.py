"""Precios de mercado desde los endpoints públicos de Yahoo Finance (sin clave)."""
import http.cookiejar
import json
import math
import statistics
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import quote, urlencode

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"

# intervalo de la app -> (intervalo Yahoo, rango completo, rango corto para refrescar, segundos)
INTERVALOS = {
    "1m": ("1m", "5d", "1d", 60),
    "5m": ("5m", "1mo", "1d", 300),
    "15m": ("15m", "1mo", "5d", 900),
    "1h": ("60m", "1y", "5d", 3600),
    "4h": ("60m", "2y", "1mo", 14400),
    "1d": ("1d", "10y", "5d", 86400),
    # Con range=max Yahoo ignora el intervalo y devuelve velas trimestrales.
    "1w": ("1wk", "25y", "3mo", 604800),
    "1M": ("1mo", "25y", "1y", None),
}

INDICES = [
    ("^GSPC", "S&P 500"), ("^IXIC", "Nasdaq"), ("^STOXX50E", "Euro Stoxx 50"), ("^VIX", "VIX"),
    ("^TNX", "Bono 10A"), ("DX-Y.NYB", "Dólar"), ("GC=F", "Oro"), ("CL=F", "Petróleo"), ("BTC-USD", "Bitcoin"),
]

TIPOS = {"EQUITY": "acción", "ETF": "etf", "CRYPTOCURRENCY": "cripto", "INDEX": "índice",
         "FUTURE": "futuro", "CURRENCY": "divisa", "MUTUALFUND": "fondo"}

_cache = {}
_lock = threading.Lock()
_pool = ThreadPoolExecutor(8)
_sesion = None


class ErrorMercado(Exception):
    pass


def pedir(url, cabeceras=None, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", **(cabeceras or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _cacheado(clave, ttl, funcion):
    ahora = time.time()
    with _lock:
        guardado = _cache.get(clave)
    if guardado and ahora - guardado[0] < ttl:
        return guardado[1]
    valor = funcion()
    with _lock:
        _cache[clave] = (ahora, valor)
    return valor


def _grafico(simbolo, intervalo, rango):
    url = f"{BASE}{quote(simbolo, safe='')}?" + urlencode({"range": rango, "interval": intervalo})
    try:
        datos = json.loads(pedir(url))
    except urllib.error.HTTPError as e:
        raise ErrorMercado(f"Yahoo no reconoce {simbolo}" if e.code == 404 else f"Yahoo respondió {e.code}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        raise ErrorMercado(f"No se pudo consultar Yahoo: {e}")
    resultado = (datos.get("chart") or {}).get("result")
    if not resultado:
        raise ErrorMercado(f"Sin datos para {simbolo}")
    return resultado[0]


def _alinear(t, segundos, desfase, vivo):
    """Inicio de la vela. Las de un día o más se fechan con el calendario de la bolsa."""
    if segundos and segundos < 86400:
        return t - t % segundos
    # Yahoo las sella a medianoche local y el cambio de hora la mueve una hora: el margen
    # evita caer en el día anterior. La fila en vivo trae la hora real y no lo necesita.
    dia = (t + desfase + (0 if vivo else 7200)) // 86400 * 86400
    if segundos == 86400:
        return dia
    if segundos == 604800:  # semanas desde el lunes 5/1/1970
        return (dia - 345600) // 604800 * 604800 + 345600
    d = datetime.fromtimestamp(dia, timezone.utc)
    return int(datetime(d.year, d.month, 1, tzinfo=timezone.utc).timestamp())


def _velas(resultado, segundos, agrupar):
    tiempos = resultado.get("timestamp") or []
    cotiz = (resultado.get("indicators", {}).get("quote") or [{}])[0]
    columnas = [cotiz.get(k) or [None] * len(tiempos) for k in ("open", "high", "low", "close", "volume")]
    meta = resultado.get("meta", {})
    desfase = meta.get("gmtoffset") or 0
    velas, fases, ultima = {}, {}, None
    for t, o, h, l, c, v in zip(tiempos, *columnas):
        if None in (o, h, l, c):
            continue
        h, l = max(h, o, c), min(l, o, c)  # Yahoo trae velas con el máximo por debajo del cierre
        vivo = t >= (meta.get("regularMarketTime") or t + 1)
        if segundos in (3600, 14400):  # las horas cuentan desde la apertura, que puede ser a y media
            fase = fases.setdefault((t + desfase) // 86400, t)
            clave = t - (t - fase) % segundos
        else:
            clave = _alinear(t, segundos, desfase, vivo)
        previa = velas.get(clave)
        if previa:  # la fila en vivo es un solo tick: completa la vela en curso, no la sustituye
            previa.update(high=max(previa["high"], h), low=min(previa["low"], l), close=c,
                          volume=previa["volume"] + (v or 0) if agrupar else max(previa["volume"], v or 0))
            continue
        if h == l and not v and ultima:  # divisas: Yahoo solo da el precio, sin apertura real
            o, h, l = ultima["close"], max(h, ultima["close"]), min(l, ultima["close"])
        ultima = velas[clave] = {"time": clave, "open": o, "high": h, "low": l, "close": c, "volume": v or 0}
    return sorted(velas.values(), key=lambda b: b["time"])


def velas(simbolo, intervalo, corto=False):
    if intervalo not in INTERVALOS:
        raise ErrorMercado("Intervalo no válido")
    yahoo, rango, rango_corto, segundos = INTERVALOS[intervalo]
    rango = rango_corto if corto else rango

    def cargar():
        r = _grafico(simbolo, yahoo, rango)
        meta = r.get("meta", {})
        return {
            "simbolo": meta.get("symbol", simbolo),
            "nombre": meta.get("longName") or meta.get("shortName") or simbolo,
            "moneda": meta.get("currency") or "",
            "bolsa": meta.get("fullExchangeName") or meta.get("exchangeName") or "",
            "tipo_yahoo": meta.get("instrumentType") or "",
            "precio": meta.get("regularMarketPrice"),
            "decimales": meta.get("priceHint"),
            "velas": _velas(r, segundos, intervalo == "4h"),
        }

    return _cacheado(("velas", simbolo, intervalo, corto), 4 if corto else 20, cargar)


def horas(simbolo, desde):
    """Cierres horarios sin retocar desde `desde`, para comprobar señales: (desfase, [(inicio, cierre)])."""
    dias = (time.time() - desde) / 86400
    rango = next((r for d, r in ((25, "1mo"), (85, "3mo"), (175, "6mo")) if dias < d), "1y")

    def cargar():
        r = _grafico(simbolo, "60m", rango)
        cierres = ((r.get("indicators", {}).get("quote") or [{}])[0].get("close")) or []
        filas = [(t, c) for t, c in zip(r.get("timestamp") or [], cierres) if c is not None]
        return (r.get("meta") or {}).get("gmtoffset") or 0, filas

    return _cacheado(("horas", simbolo, rango), 900, cargar)


def cotizacion(simbolo):
    def cargar():
        r = _grafico(simbolo, "1d", "5d")
        meta = r.get("meta", {})
        cierres = [c for c in ((r.get("indicators", {}).get("quote") or [{}])[0].get("close") or []) if c is not None]
        precio = meta.get("regularMarketPrice") or (cierres[-1] if cierres else None)
        previo = cierres[-2] if len(cierres) > 1 else meta.get("chartPreviousClose")
        inicio = cierres[0] if cierres else None
        return {
            "simbolo": simbolo,
            "nombre": meta.get("longName") or meta.get("shortName") or simbolo,
            "moneda": meta.get("currency") or "",
            "precio": precio,
            "var_dia": (precio / previo - 1) * 100 if precio and previo else None,
            "var_5d": (precio / inicio - 1) * 100 if precio and inicio else None,
        }

    return _cacheado(("cotizacion", simbolo), 12, cargar)


def cotizaciones(simbolos):
    def segura(s):
        try:
            return cotizacion(s)
        except ErrorMercado:
            return {"simbolo": s, "precio": None, "var_dia": None, "var_5d": None, "moneda": "", "nombre": s}

    return list(_pool.map(segura, simbolos))


def _sesion_yahoo():
    """quoteSummary exige una cookie y un crumb, que no son credenciales del usuario."""
    global _sesion
    if not _sesion:
        abridor = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        abridor.addheaders = [("User-Agent", UA)]
        try:
            abridor.open("https://fc.yahoo.com", timeout=10)
        except urllib.error.HTTPError:
            pass  # responde 404, pero deja la cookie
        crumb = abridor.open("https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=10).read().decode()
        _sesion = (abridor, crumb)
    return _sesion


def consenso(simbolo):
    """Precio objetivo de analistas y próximos resultados. No existe para cripto ni para algunos ETF."""

    def cargar():
        global _sesion
        try:
            abridor, crumb = _sesion_yahoo()
            url = (f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{quote(simbolo, safe='')}?"
                   + urlencode({"modules": "financialData,calendarEvents", "crumb": crumb}))
            d = json.loads(abridor.open(url, timeout=10).read())["quoteSummary"]["result"][0]
        except urllib.error.HTTPError as e:
            if e.code == 401:
                _sesion = None  # el crumb caduca
            return None
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, IndexError, TypeError):
            return None
        f = d.get("financialData") or {}
        crudo = lambda v: (v or {}).get("raw")
        fechas = [crudo(x) for x in (d.get("calendarEvents") or {}).get("earnings", {}).get("earningsDate", [])]
        proxima = min((t for t in fechas if t and t > time.time()), default=None)
        if not crudo(f.get("targetMeanPrice")) and not proxima:
            return None
        return {
            "objetivo_medio": crudo(f.get("targetMeanPrice")),
            "objetivo_alto": crudo(f.get("targetHighPrice")),
            "objetivo_bajo": crudo(f.get("targetLowPrice")),
            "analistas": crudo(f.get("numberOfAnalystOpinions")),
            "recomendacion": f.get("recommendationKey"),
            "proximos_resultados": proxima,
        }

    return _cacheado(("consenso", simbolo), 21600, cargar)


def _rsi(cierres, n=14):
    if len(cierres) <= n:
        return None
    sube = baja = 0.0
    for i in range(1, len(cierres)):
        c = cierres[i] - cierres[i - 1]
        g, p = max(c, 0), max(-c, 0)
        if i <= n:
            sube, baja = sube + g / n, baja + p / n
        else:
            sube, baja = (sube * (n - 1) + g) / n, (baja * (n - 1) + p) / n
    return 100.0 if baja == 0 else 100 - 100 / (1 + sube / baja)


def ficha(simbolo):
    """Datos objetivos de un activo, calculados aquí: no gastan el plan de Claude."""
    info = velas(simbolo, "1d")
    v = info["velas"]
    if len(v) < 2:
        raise ErrorMercado(f"Sin histórico para {simbolo}")
    cierres = [b["close"] for b in v]
    precio = info["precio"] or cierres[-1]
    ultimo = v[-1]["time"]

    def desde(limite):
        previas = [b["close"] for b in v if b["time"] <= limite]
        return (precio / previas[-1] - 1) * 100 if previas else None

    inicio_ano = int(datetime(datetime.now(timezone.utc).year, 1, 1, tzinfo=timezone.utc).timestamp())
    ano = [b for b in v if b["time"] > ultimo - 365 * 86400]
    maximo, minimo = max(b["high"] for b in ano), min(b["low"] for b in ano)
    media = lambda n: sum(cierres[-n:]) / n if len(cierres) >= n else None
    diarias = [math.log(b / a) for a, b in zip(cierres[-31:], cierres[-30:]) if a > 0 and b > 0]
    dias_ano = 365 if info["tipo_yahoo"] == "CRYPTOCURRENCY" else 252
    return {
        "simbolo": simbolo, "nombre": info["nombre"], "moneda": info["moneda"], "bolsa": info["bolsa"],
        "precio": precio,
        "rendimientos": {
            "1 día": (precio / cierres[-2] - 1) * 100, "1 semana": desde(ultimo - 7 * 86400),
            "1 mes": desde(ultimo - 30 * 86400), "3 meses": desde(ultimo - 91 * 86400),
            "Este año": desde(inicio_ano - 1), "1 año": desde(ultimo - 365 * 86400),
        },
        "maximo_1a": maximo, "minimo_1a": minimo, "desde_maximo": (precio / maximo - 1) * 100,
        "rsi": _rsi(cierres[-250:]), "sma50": media(50), "sma200": media(200),
        "volatilidad": statistics.stdev(diarias) * math.sqrt(dias_ano) * 100 if len(diarias) > 2 else None,
        "consenso": consenso(simbolo),
    }


def indices():
    nombres = dict(INDICES)
    return [{**c, "nombre": nombres[c["simbolo"]]} for c in cotizaciones(list(nombres))]


def cambio(origen, destino):
    """Cuántas unidades de `destino` vale una de `origen`."""
    if not origen or origen == destino:
        return 1.0
    try:
        return cotizacion(f"{origen}{destino}=X")["precio"] or 1.0
    except ErrorMercado:
        return None


def buscar(texto):
    url = "https://query2.finance.yahoo.com/v1/finance/search?" + urlencode(
        {"q": texto, "quotesCount": 8, "newsCount": 0, "enableFuzzyQuery": "false"}
    )
    try:
        datos = json.loads(pedir(url))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        raise ErrorMercado(f"No se pudo buscar: {e}")
    salida = []
    for q in datos.get("quotes", []):
        if q.get("symbol") and q.get("quoteType") in TIPOS:
            salida.append({
                "simbolo": q["symbol"],
                "nombre": q.get("longname") or q.get("shortname") or q["symbol"],
                "tipo": TIPOS[q["quoteType"]],
                "bolsa": q.get("exchDisp") or "",
            })
    return salida
