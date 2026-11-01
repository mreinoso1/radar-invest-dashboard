"""Precios de mercado desde los endpoints públicos de Yahoo Finance (sin clave)."""
import json
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


def _alinear(t, segundos):
    """Alinea el tiempo al inicio de su vela: la vela en curso llega con la hora actual."""
    if segundos == 86400:
        return t - t % 86400
    if segundos == 604800:  # semanas desde el lunes 5/1/1970
        return (t - 345600) // 604800 * 604800 + 345600
    if segundos is None:
        d = datetime.fromtimestamp(t, timezone.utc)
        return int(datetime(d.year, d.month, 1, tzinfo=timezone.utc).timestamp())
    return t - t % segundos


def _velas(resultado, segundos, agrupar):
    tiempos = resultado.get("timestamp") or []
    cotiz = (resultado.get("indicators", {}).get("quote") or [{}])[0]
    columnas = [cotiz.get(k) or [None] * len(tiempos) for k in ("open", "high", "low", "close", "volume")]
    velas = {}
    for t, o, h, l, c, v in zip(tiempos, *columnas):
        if None in (o, h, l, c):
            continue
        clave = _alinear(t, segundos)
        previa = velas.get(clave)
        if previa and agrupar:
            previa.update(high=max(previa["high"], h), low=min(previa["low"], l), close=c,
                          volume=previa["volume"] + (v or 0))
        else:  # sin agrupar, la última fila de esa vela es la más reciente
            velas[clave] = {"time": clave, "open": o, "high": h, "low": l, "close": c, "volume": v or 0}
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
            "velas": _velas(r, segundos, intervalo == "4h"),
        }

    return _cacheado(("velas", simbolo, intervalo, corto), 4 if corto else 20, cargar)


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
