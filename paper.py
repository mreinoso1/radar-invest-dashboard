"""Paper trading: las señales reales de Radar (cartera, ideas y reglas) operadas con dinero ficticio, desde que
existen, con el mismo simulador que el backtest.

Es la única prueba sin sesgo de supervivencia ni conocimiento del futuro: cada señal se generó antes de
saber qué pasaría. Para el criterio de la Fase 5 solo cuentan las reglas que entraron en el backtest y las
señales creadas desde que existe la versión actual de la estrategia (su huella).
"""
import time

import calibracion
import criterio
import datos
import marcador
import mercado
import simulador

INDICES = ("SPY", "BTC-USD")


def senales_reales():
    """Las señales con dirección que el marcador juzga, en el formato del simulador."""
    salida = []
    for s in marcador._senales("todas", datos.ajustes()):
        if s["direccion"] in ("sube", "baja"):
            salida.append({"id": f"{s['origen']}:{s['item_id']}:{s['simbolo']}", "simbolo": s["simbolo"],
                           "direccion": s["direccion"], "t": s["creado"], "precio": s["precio"],
                           "horizonte": s["horizonte"], "origen": s["origen"], "tipo": calibracion.tipo_de(s)})
    return salida


def para_criterio(operaciones, incluidas, desde):
    """Las operaciones que cuentan para la Fase 5: reglas del backtest, de la versión actual."""
    tipos = {f"reglas:{r}" for r in incluidas}
    return [o for o in operaciones if o["tipo"] in tipos and o["t"] >= desde]


def calcular(ahora=None):
    ahora = ahora or time.time()
    cfg = simulador.config_actual(datos.ajustes())
    senales = senales_reales()
    velas = {}
    for s in sorted({x["simbolo"] for x in senales} | set(INDICES)):
        try:
            velas[s] = mercado.velas(s, "1d")["velas"]
        except mercado.ErrorMercado:
            pass
    indices = {s: velas[s] for s in INDICES if s in velas}
    operables = {s: v for s, v in velas.items() if any(x["simbolo"] == s for x in senales)}
    r = simulador.simular(senales, operables, cfg, indices)
    dias = [d for d, _ in r["curva"]]
    backtest = datos.simulacion("backtest")
    incluidas = backtest["incluidas"] if backtest else []
    huella = criterio.huella(cfg, incluidas)
    desde = criterio.inicio_version(huella, ahora)
    cuentan = para_criterio(r["operaciones"], incluidas, desde)
    return {**r, "indices": {n: simulador.curva_indice(v, dias, cfg["capital"]) for n, v in indices.items()},
            "huella": huella, "desde": desde, "incluidas": incluidas, "cuentan": len(cuentan),
            "criterio": criterio.evaluar_paper(cuentan)}


def estado_fase5(ahora=None):
    """Lo que decide si la Fase 5 se desbloquea: backtest (completo y reciente) y paper trading, de la misma
    versión de la estrategia. Un backtest de otra versión no vale."""
    backtest = datos.simulacion("backtest")
    paper = calcular(ahora)
    partes = []
    if backtest:
        vigente = backtest["huella"] == paper["huella"]
        for p in backtest["criterio"]:
            partes.append(p if vigente else {**p, "pasa": False,
                                             "nota": "El backtest es de otra versión de la estrategia: vuelve a lanzarlo."})
    else:
        partes.append({"nombre": "Backtest", "pasa": False, "puntos": [], "nota": "Aún no se ha lanzado."})
    partes.append(paper["criterio"])
    return {"desbloqueada": criterio.desbloqueada(partes), "partes": partes, "huella": paper["huella"],
            "desde": paper["desde"], "incluidas": paper["incluidas"]}
