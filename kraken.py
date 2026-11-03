"""Lectura de la cuenta de Kraken con claves de solo consulta. Radar nunca opera ni retira.

Hay dos APIs con claves distintas: la de spot (saldos y posiciones con margen, api.kraken.com) y la
de futuros (perpetuos, futures.kraken.com). Cada una se activa si el usuario guarda su clave.
"""
import base64
import hashlib
import hmac
import json
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

import datos
import mercado

SPOT = "https://api.kraken.com"
FUTUROS = "https://futures.kraken.com"
NOMBRES = {"XBT": "BTC", "XDG": "DOGE"}  # Kraken usa códigos propios para algunas monedas
FIAT = {"USD", "EUR", "GBP", "CHF", "CAD", "AUD", "JPY"}
ESTABLES = {"USDT", "USDC", "DAI", "PYUSD", "USDG", "RLUSD"}

_nonce_lock = threading.Lock()
_ultimo_nonce = 0


class ErrorKraken(Exception):
    pass


def _nonce():
    """Kraken rechaza un nonce que no sea mayor que el anterior de esa clave."""
    global _ultimo_nonce
    with _nonce_lock:
        _ultimo_nonce = max(_ultimo_nonce + 1, int(time.time() * 1000))
        return str(_ultimo_nonce)


def firma_spot(ruta, cuerpo, nonce, secreto):
    resumen = hashlib.sha256((nonce + cuerpo).encode()).digest()
    return base64.b64encode(hmac.new(base64.b64decode(secreto), ruta.encode() + resumen, hashlib.sha512).digest()).decode()


def firma_futuros(ruta, cuerpo, nonce, secreto):
    """La ruta firmada va sin el prefijo /derivatives, como en el ejemplo de la documentación."""
    resumen = hashlib.sha256((cuerpo + nonce + ruta).encode()).digest()
    return base64.b64encode(hmac.new(base64.b64decode(secreto), resumen, hashlib.sha512).digest()).decode()


def _leer(peticion):
    try:
        with urllib.request.urlopen(peticion, timeout=12) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise ErrorKraken(f"Kraken respondió {e.code}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        raise ErrorKraken(f"No se pudo consultar Kraken: {e}")


def _publico(ruta, params=None):
    url = f"{SPOT}{ruta}" + (f"?{urlencode(params)}" if params else "")
    r = _leer(urllib.request.Request(url, headers={"User-Agent": mercado.UA}))
    if r.get("error"):
        raise ErrorKraken(", ".join(r["error"]))
    return r["result"]


def _privado(ruta, clave, secreto, params=None):
    nonce = _nonce()
    cuerpo = urlencode({"nonce": nonce, **(params or {})})
    try:
        firma = firma_spot(ruta, cuerpo, nonce, secreto)
    except (ValueError, TypeError):
        raise ErrorKraken("La clave privada de Kraken no tiene un formato válido.")
    r = _leer(urllib.request.Request(f"{SPOT}{ruta}", data=cuerpo.encode(), headers={
        "API-Key": clave, "API-Sign": firma, "User-Agent": mercado.UA,
        "Content-Type": "application/x-www-form-urlencoded"}))
    if r.get("error"):
        raise ErrorKraken(_traducir(r["error"]))
    return r["result"]


def _futuros(ruta, clave, secreto):
    nonce = _nonce()
    try:
        firma = firma_futuros(ruta, "", nonce, secreto)
    except (ValueError, TypeError):
        raise ErrorKraken("La clave privada de Kraken Futures no tiene un formato válido.")
    r = _leer(urllib.request.Request(f"{FUTUROS}/derivatives{ruta}", headers={
        "APIKey": clave, "Nonce": nonce, "Authent": firma, "User-Agent": mercado.UA}))
    if r.get("result") == "error":
        raise ErrorKraken(f"Kraken Futures: {r.get('error') or 'error desconocido'}")
    return r


def _traducir(errores):
    texto = ", ".join(errores)
    if "Invalid key" in texto or "Invalid signature" in texto:
        return "Kraken no acepta la clave: revisa la clave pública y la privada en Ajustes."
    if "Permission denied" in texto:
        return "A la clave de Kraken le falta el permiso de consultar fondos y operaciones abiertas."
    if "Invalid nonce" in texto:
        return "Kraken rechazó la petición por el nonce: no uses esta clave en otro programa a la vez."
    return f"Kraken: {texto}"


def _base(codigo):
    """XXBT, XBT.F o HYPE.S -> BTC, BTC, HYPE. Los sufijos son saldos en staking o en Earn."""
    codigo = codigo.split(".")[0]
    if len(codigo) == 4 and codigo[0] in "XZ" and codigo[1:] in NOMBRES | {c: c for c in FIAT}:
        codigo = codigo[1:]
    elif len(codigo) == 4 and codigo[0] in "XZ" and codigo in _activos():
        codigo = _activos()[codigo]
    return NOMBRES.get(codigo, codigo)


def _activos():
    return mercado._cacheado(("kraken", "activos"), 86400,
                             lambda: {k: v.get("altname", k) for k, v in _publico("/0/public/Assets").items()})


def _precio_usd(base):
    if base == "USD":
        return 1.0
    if base in FIAT:
        return mercado.cambio(base, "USD")

    def cargar():
        try:
            r = _publico("/0/public/Ticker", {"pair": f"{'XBT' if base == 'BTC' else 'XDG' if base == 'DOGE' else base}USD"})
        except ErrorKraken:
            return 1.0 if base in ESTABLES else None
        return float(next(iter(r.values()))["c"][0])

    return mercado._cacheado(("kraken", "precio", base), 30, cargar)


def simbolo_radar(base):
    """Símbolo de Yahoo del mismo activo, para abrir su gráfica. Un token y una acción pueden compartir
    ticker (PURR), así que solo se buscan criptomonedas."""
    if base in FIAT:
        return None
    propios = [p["simbolo"] for p in datos.posiciones() if re.fullmatch(rf"{re.escape(base)}\d*-USD", p["simbolo"])]
    if propios:
        return propios[0]

    def cargar():
        try:
            cripto = next((r["simbolo"] for r in mercado.buscar(base)
                           if r["tipo"] == "cripto" and re.fullmatch(rf"{re.escape(base)}\d*-USD", r["simbolo"])), None)
            if cripto or not base.endswith("X"):
                return cripto
            # Los perpetuos de acciones tokenizadas se llaman como la acción más una X: AAPLX -> AAPL.
            return next((r["simbolo"] for r in mercado.buscar(base[:-1])
                         if r["tipo"] in ("acción", "etf") and r["simbolo"] == base[:-1]), None)
        except mercado.ErrorMercado:
            return None

    return mercado._cacheado(("kraken", "simbolo", base), 86400, cargar)


def _spot(clave, secreto):
    saldos = {}
    for codigo, cantidad in _privado("/0/private/Balance", clave, secreto).items():
        cantidad = float(cantidad)
        if cantidad > 0:
            base = _base(codigo)
            saldos[base] = saldos.get(base, 0) + cantidad
    posiciones = {}
    abiertas = _privado("/0/private/OpenPositions", clave, secreto, {"docalcs": "true"})
    pares = _publico("/0/public/AssetPairs") if abiertas else {}
    for p in abiertas.values():
        par = pares.get(p["pair"], {})
        base = _base(par.get("base", p["pair"]))
        clave_pos = (base, p["type"])
        vol = float(p["vol"]) - float(p.get("vol_closed") or 0)
        acumulada = posiciones.setdefault(clave_pos, {"vol": 0.0, "coste": 0.0, "resultado": 0.0})
        acumulada["vol"] += vol
        acumulada["coste"] += float(p["cost"]) * (vol / float(p["vol"]) if float(p["vol"]) else 1)
        acumulada["resultado"] += float(p.get("net") or 0)
    return saldos, [
        {"base": b, "lado": "corto" if tipo == "sell" else "largo", "cantidad": a["vol"],
         "entrada": a["coste"] / a["vol"] if a["vol"] else None, "resultado_usd": a["resultado"], "mercado": "margen"}
        for (b, tipo), a in posiciones.items()
    ]


def _futuros_cuenta(clave, secreto):
    abiertas = _futuros("/api/v3/openpositions", clave, secreto).get("openPositions") or []
    tickers = {}
    if abiertas:
        r = _leer(urllib.request.Request(f"{FUTUROS}/derivatives/api/v3/tickers", headers={"User-Agent": mercado.UA}))
        tickers = {t["symbol"].upper(): t for t in r.get("tickers", [])}
    posiciones = []
    for p in abiertas:
        simbolo = p["symbol"].upper()  # PF_XBTUSD
        par = simbolo.split("_")[-1]
        base = NOMBRES.get(par[:-3], par[:-3]) if par.endswith("USD") else par
        entrada, tamano = float(p["price"]), float(p["size"])
        marca = tickers.get(simbolo, {}).get("markPrice")
        signo = -1 if p["side"] == "short" else 1
        posiciones.append({
            "base": base, "lado": "corto" if signo < 0 else "largo", "cantidad": tamano, "entrada": entrada,
            "resultado_usd": (float(marca) - entrada) * tamano * signo if marca else None, "mercado": "futuros",
            "contrato": simbolo,
        })
    try:
        cuentas = _futuros("/api/v3/accounts", clave, secreto).get("accounts", {})
        valor = (cuentas.get("flex") or {}).get("portfolioValue")
    except ErrorKraken:
        valor = None
    return posiciones, valor


def resumen(forzar=False):
    """Todo lo que tiene en Kraken, valorado en USD. Los fallos de una API no tapan la otra."""
    cfg = datos.ajustes()
    spot = bool(cfg["kraken_key"] and cfg["kraken_secret"])
    futuros = bool(cfg["kraken_fut_key"] and cfg["kraken_fut_secret"])
    if not spot and not futuros:
        return {"conectado": False}

    def cargar():
        errores, saldos, posiciones, valor_futuros = [], [], [], None
        if spot:
            try:
                crudos, posiciones = _spot(cfg["kraken_key"], cfg["kraken_secret"])
                with ThreadPoolExecutor(6) as pool:
                    precios = dict(zip(crudos, pool.map(_precio_usd, crudos)))
                for base, cantidad in sorted(crudos.items()):
                    precio = precios[base]
                    saldos.append({"base": base, "cantidad": cantidad, "precio_usd": precio,
                                   "valor_usd": cantidad * precio if precio else None})
            except ErrorKraken as e:
                errores.append(str(e))
        if futuros:
            try:
                de_futuros, valor_futuros = _futuros_cuenta(cfg["kraken_fut_key"], cfg["kraken_fut_secret"])
                posiciones += de_futuros
            except ErrorKraken as e:
                errores.append(str(e))
        for fila in saldos + posiciones:
            fila["simbolo"] = simbolo_radar(fila["base"])
        saldos.sort(key=lambda s: -(s["valor_usd"] or 0))
        return {
            "conectado": True, "saldos": saldos, "posiciones": posiciones, "errores": errores,
            "valor_spot_usd": sum(s["valor_usd"] or 0 for s in saldos),
            "valor_futuros_usd": float(valor_futuros) if valor_futuros is not None else None,
            "actualizado": int(time.time()),
        }

    if forzar:
        with mercado._lock:
            mercado._cache.pop(("kraken", "resumen"), None)
    return mercado._cacheado(("kraken", "resumen"), 20, cargar)


def para_analista():
    """Texto breve con lo que tiene en Kraken, o "" si no está conectado o falla."""
    try:
        r = resumen()
    except Exception:
        return ""
    if not r.get("conectado"):
        return ""
    lineas = []
    for p in r["posiciones"]:
        resultado = "" if p["resultado_usd"] is None else f", resultado {p['resultado_usd']:+.2f} USD"
        lineas.append(f"Posición {p['lado']} en {p['base']} ({p['mercado']}{', ' + p['contrato'] if p.get('contrato') else ''}): "
                      f"{p['cantidad']:g} a {p['entrada']:.6g}{resultado}")
    for s in r["saldos"][:15]:
        valor = "" if s["valor_usd"] is None else f" (~{s['valor_usd']:.0f} USD)"
        lineas.append(f"Saldo {s['base']}: {s['cantidad']:g}{valor}")
    return "\n".join(lineas)
