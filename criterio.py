"""Criterio para desbloquear la Fase 5 (bot real). Lo calcula el código: no se decide a ojo.

Criterio mixto, elegido por el usuario el 2026-11-09:
1. Backtest de las reglas, periodo completo: al menos 100 operaciones, rentabilidad neta mayor que su índice
   y un intervalo de confianza del exceso medio por operación que no incluye el 0.
2. Lo mismo en los dos últimos años por separado, con al menos 30 operaciones: que no apruebe solo gracias a
   un pasado lejano que quizá ya no se repite.
3. Paper trading de esas mismas reglas, con señales reales de la versión actual: al menos 30 operaciones y un
   exceso medio positivo. Es lo único libre del sesgo de supervivencia del backtest.

El intervalo se calcula con bootstrap por bloques de días (las operaciones del mismo día no son
independientes) y se ensancha con la corrección de Bonferroni según cuántas reglas se prueban a la vez.
"""
import hashlib
import json
import random
import statistics
import time

import datos
import reglas
import simulador

MIN_BACKTEST = 100
MIN_RECIENTE = 30
MIN_PAPER = 30
ANIOS_RECIENTES = 2
REMUESTREOS = 2000
SEMILLA = 7  # fija: el mismo resultado da siempre el mismo intervalo


def bootstrap(operaciones, confianza, semilla=SEMILLA, n=REMUESTREOS):
    """Intervalo del exceso medio por operación, remuestreando días enteros con reemplazo."""
    por_dia = {}
    for o in operaciones:
        por_dia.setdefault(o["dia_entrada"], []).append(o["exceso"])
    dias = list(por_dia.values())
    if len(dias) < 2:
        return None
    azar = random.Random(semilla)
    medias = sorted(statistics.mean([x for dia in (azar.choice(dias) for _ in dias) for x in dia]) for _ in range(n))
    cola = (1 - confianza) / 2
    return [medias[int(cola * n)], medias[min(n - 1, int((1 - cola) * n))]]


def rentabilidades(resultado, indices, desde=None):
    """(rentabilidad de la estrategia, {índice: rentabilidad}) entre `desde` (un día) y el final."""
    curva = [(d, v) for d, v in resultado["curva"] if desde is None or d >= desde]
    if len(curva) < 2:
        return None, {}
    propia = (curva[-1][1] / curva[0][1] - 1) * 100
    dias = [d for d, _ in curva]
    de_indices = {}
    for nombre, velas in indices.items():
        c = simulador.curva_indice(velas, dias, 1.0)
        if len(c) >= 2:
            de_indices[nombre] = (c[-1][1] / c[0][1] - 1) * 100
    return propia, de_indices


def mezcla(operaciones, de_indices):
    """El índice con el que compararse: SPY y BTC en la proporción de operaciones de acciones y de cripto."""
    if not operaciones:
        return None
    cripto = sum(o["cripto"] for o in operaciones) / len(operaciones)
    spy, btc = de_indices.get("SPY"), de_indices.get("BTC-USD")
    if spy is None or btc is None:
        return spy if btc is None else btc
    return (1 - cripto) * spy + cripto * btc


def evaluar(operaciones, rentabilidad, de_indices, n_reglas, minimo, nombre):
    confianza = 1 - 0.05 / max(1, n_reglas)  # Bonferroni: con 3 reglas, 98,33 %
    intervalo = bootstrap(operaciones, confianza)
    indice = mezcla(operaciones, de_indices)
    puntos = [
        {"nombre": f"Al menos {minimo} operaciones", "ok": len(operaciones) >= minimo, "valor": len(operaciones)},
        {"nombre": "Rentabilidad neta mayor que la del índice", "valor": [rentabilidad, indice],
         "ok": rentabilidad is not None and indice is not None and rentabilidad > indice},
        {"nombre": f"Intervalo del {confianza * 100:.2f} % del exceso medio por encima de 0", "valor": intervalo,
         "ok": bool(intervalo) and intervalo[0] > 0},
    ]
    return {"nombre": nombre, "pasa": all(p["ok"] for p in puntos), "puntos": puntos, "confianza": confianza,
            "exceso_medio": statistics.mean(o["exceso"] for o in operaciones) if operaciones else None}


def evaluar_backtest(resultado, indices, n_reglas):
    """Periodo completo y últimos dos años, con el mismo resultado de la simulación."""
    total = evaluar(resultado["operaciones"], *rentabilidades(resultado, indices), n_reglas, MIN_BACKTEST,
                    "Backtest, periodo completo")
    if not resultado["curva"]:
        return [total]
    corte = resultado["curva"][-1][0] - int(ANIOS_RECIENTES * 365.25)
    recientes = [o for o in resultado["operaciones"] if o["dia_entrada"] >= corte]
    reciente = evaluar(recientes, *rentabilidades(resultado, indices, corte), n_reglas, MIN_RECIENTE,
                       f"Backtest, últimos {ANIOS_RECIENTES} años")
    return [total, reciente]


def evaluar_paper(operaciones):
    media = statistics.mean(o["exceso"] for o in operaciones) if operaciones else None
    puntos = [{"nombre": f"Al menos {MIN_PAPER} operaciones reales", "ok": len(operaciones) >= MIN_PAPER,
               "valor": len(operaciones)},
              {"nombre": "Exceso medio por operación positivo", "ok": media is not None and media > 0, "valor": media}]
    return {"nombre": "Paper trading de esas reglas", "pasa": all(p["ok"] for p in puntos), "puntos": puntos,
            "exceso_medio": media}


def huella(cfg, incluidas):
    """Identifica la versión de la estrategia. Si cambia algo (riesgo, stop, umbrales, reglas), cambia la huella
    y el paper trading vuelve a contar desde 0: así no se puede retocar hasta que apruebe."""
    umbrales = {k: v for k, v in vars(reglas).items() if k.isupper() and isinstance(v, (int, float, dict))}
    contenido = json.dumps({"simulador": {k: cfg[k] for k in sorted(simulador.CONFIG)}, "umbrales": umbrales,
                            "reglas": sorted(incluidas)}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(contenido.encode()).hexdigest()[:12]


def inicio_version(clave, ahora=None):
    """Desde cuándo existe esta versión. La primera vez que se ve, empieza a contar."""
    versiones = datos.estado_alertas("versiones_simulacion", {})
    if clave not in versiones:
        versiones[clave] = int(ahora or time.time())
        datos.guardar_estado_alertas("versiones_simulacion", versiones)
    return versiones[clave]


def desbloqueada(partes):
    return bool(partes) and all(p["pasa"] for p in partes)
