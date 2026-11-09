"""Insiders desde SEC EDGAR: lo que compran y venden en el mercado los directivos de una empresa, según
sus Form 4.

Normas de la SEC para programas: identificarse con un nombre y un correo de contacto (ajuste sec_contacto)
y no pasar de 10 peticiones por segundo. Un Form 4 no cambia una vez presentado: se guarda y no se vuelve a
pedir.

Solo cuentan las compras (código P) y ventas (S) en el mercado de acciones. Premios (A), ejercicios de
opciones (M), retenciones de impuestos (F) y donaciones (G) son ruido: nadie apuesta su dinero en ellos.
"""
import json
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import datos
import mercado

PAUSA = 0.15            # segundos entre peticiones: unas 6 por segundo, por debajo del límite de 10
MAX_FORMULARIOS = 40    # Form 4 nuevos que se leen por empresa y vez
CODIGOS = {"P": "compra", "S": "venta", "A": "premio", "M": "ejercicio", "F": "impuestos", "G": "donación"}
_turno = threading.Lock()
_ultima = [0.0]


class ErrorEdgar(Exception):
    pass


def _contacto():
    contacto = datos.ajustes()["sec_contacto"].strip()
    if not contacto:
        raise ErrorEdgar("falta el contacto para la SEC en Ajustes")
    return contacto


def _pedir(url):
    with _turno:  # una petición cada vez, con pausa: es lo que pide la SEC
        espera = _ultima[0] + PAUSA - time.time()
        if espera > 0:
            time.sleep(espera)
        _ultima[0] = time.time()
        peticion = urllib.request.Request(url, headers={"User-Agent": f"Radar {_contacto()}",
                                                        "Accept-Encoding": "identity"})
        try:
            with urllib.request.urlopen(peticion, timeout=20) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError) as e:
            raise ErrorEdgar(str(getattr(e, "reason", e)))


def _cik(ticker):
    tabla = mercado._cacheado(("sec_tickers",), 86400, lambda: json.loads(_pedir(
        "https://www.sec.gov/files/company_tickers.json")))
    return next((v["cik_str"] for v in tabla.values() if v["ticker"] == ticker.replace("-", ".")), None)


def formularios(submissions, desde):
    """(acceso, fecha, documento) de los Form 4 presentados desde `desde`, del JSON de submissions."""
    r = submissions["filings"]["recent"]
    return [(r["accessionNumber"][i], r["filingDate"][i], r["primaryDocument"][i])
            for i in range(len(r["form"])) if r["form"][i] == "4" and r["filingDate"][i] >= desde]


def leer_form4(xml):
    """Las transacciones de acciones (no de opciones) de un Form 4."""
    raiz = ET.fromstring(xml)
    texto = lambda nodo, ruta: (nodo.findtext(ruta) or "").strip()
    emisor = int(texto(raiz, "issuer/issuerCik") or 0)
    nombre = texto(raiz, "reportingOwner/reportingOwnerId/rptOwnerName")
    rel = raiz.find("reportingOwner/reportingOwnerRelationship")
    cargo = (texto(rel, "officerTitle") or ("Consejero" if texto(rel, "isDirector") in ("1", "true") else "")) if rel is not None else ""
    salida = []
    for t in raiz.findall("nonDerivativeTable/nonDerivativeTransaction"):
        try:
            acciones = float(texto(t, "transactionAmounts/transactionShares/value") or 0)
            precio = float(texto(t, "transactionAmounts/transactionPricePerShare/value") or 0)
        except ValueError:
            continue
        salida.append({"emisor": emisor, "nombre": nombre, "cargo": cargo,
                       "codigo": texto(t, "transactionCoding/transactionCode"),
                       "fecha": texto(t, "transactionDate/value"), "acciones": acciones, "precio": precio})
    return salida


def resumir(transacciones):
    """Compras y ventas en el mercado; lo demás solo se cuenta."""
    compras = [t for t in transacciones if t["codigo"] == "P"]
    ventas = [t for t in transacciones if t["codigo"] == "S"]
    return {"compras": len(compras), "compradores": len({t["nombre"] for t in compras}),
            "valor_compras": sum(t["acciones"] * t["precio"] for t in compras),
            "ventas": len(ventas), "valor_ventas": sum(t["acciones"] * t["precio"] for t in ventas),
            "otros": len(transacciones) - len(compras) - len(ventas),
            "ultimas": sorted(compras + ventas, key=lambda t: t["fecha"], reverse=True)[:5]}


def _descargar(simbolo, cik, desde, limite=None, avance=None):
    """Los Form 4 presentados desde `desde`, descargando solo los que aún no estaban guardados."""
    guardados = datos.form4_guardados(simbolo, desde)
    sub = mercado._cacheado(("sec_sub", cik), 6 * 3600, lambda: json.loads(_pedir(
        f"https://data.sec.gov/submissions/CIK{cik:010d}.json")))
    nuevos = [f for f in formularios(sub, desde) if f[0] not in guardados][:limite]
    for n, (acceso, fecha, documento) in enumerate(nuevos, 1):
        # primaryDocument apunta a la versión con estilo ("xslF345X06/…"); el XML en bruto está sin esa carpeta.
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acceso.replace('-', '')}/{documento.split('/')[-1]}"
        try:
            transacciones = leer_form4(_pedir(url))
        except ET.ParseError:
            transacciones = []
        datos.guardar_form4(acceso, simbolo, fecha, transacciones)
        guardados[acceso] = {"fecha": fecha, "transacciones": transacciones}
        if avance:
            avance(n, len(nuevos))
    return guardados


def resumen(simbolo, dias=90):
    """Insiders de los últimos `dias`. None si no es una empresa de EE. UU. con CIK en la SEC."""
    cik = _cik(simbolo)
    if not cik:
        return None
    guardados = _descargar(simbolo, cik, (date.today() - timedelta(days=dias)).isoformat(), MAX_FORMULARIOS)
    # La lista de un CIK incluye los Form 4 que esa empresa presenta como accionista de otras: no son suyos.
    return resumir([t for f in guardados.values() for t in f["transacciones"] if t.get("emisor") == cik])


def historial(simbolo, desde, avance=None):
    """[(fecha de presentación, transacción)] desde `desde`. En un backtest cuenta la fecha de presentación, no
    la de la compra: hasta entonces nadie de fuera podía saberla."""
    cik = _cik(simbolo)
    if not cik:
        return []
    guardados = _descargar(simbolo, cik, desde, avance=avance)
    return sorted(((f["fecha"], t) for f in guardados.values() for t in f["transacciones"] if t.get("emisor") == cik),
                  key=lambda par: par[0])
