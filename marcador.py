"""Marcador de aciertos: compara cada señal del agente con lo que hizo el precio después.

Una señal es el impacto de una noticia relevante sobre un activo. prob_subida promete que el
activo cotizará por encima del precio que el agente tenía delante al terminar el horizonte, y
eso es exactamente lo que se mide. Se calcula al pedirlo, con precios de Yahoo: no gasta plan.
"""
import bisect
import math
import time
from concurrent.futures import ThreadPoolExecutor

import datos
import mercado

PLAZOS = {"horas": 86400, "días": 7 * 86400, "semanas": 30 * 86400, "meses": 90 * 86400}
TRAMOS = [(0, 35, "35 o menos"), (36, 45, "36-45"), (46, 54, "46-54"), (55, 64, "55-64"), (65, 100, "65 o más")]
MINIMO = 30  # señales resueltas en días distintos para empezar a sacar conclusiones


def _precio_en(filas, inicios, t):
    """Cierre de la última vela horaria que empezó en t o antes."""
    i = bisect.bisect_right(inicios, t) - 1
    return filas[i][1] if i >= 0 else None


def _juzgar(s, historia, ahora, actual):
    """Añade a la señal su precio de entrada y, si su plazo ya pasó, el de salida."""
    desfase, filas = historia
    inicios = [t for t, _ in filas]
    # Los análisis anteriores al marcador no guardaban precio: se toma el de la vela de ese momento.
    entrada = s["precio"] or _precio_en(filas, inicios, s["creado"])
    if not entrada:
        return {**s, "estado": "sin_datos"}
    objetivo = s["creado"] + PLAZOS.get(s["horizonte"], PLAZOS["días"])
    siguiente = bisect.bisect_right(inicios, s["creado"])
    if siguiente == len(filas):  # aún no ha cotizado desde la señal
        return {**s, "entrada": entrada, "estado": "pendiente", "objetivo": objetivo,
                "movimiento": _mov(actual, entrada)}
    if inicios[siguiente] > objetivo:
        # No cotizó dentro del plazo (de noche o en fin de semana): una señal de "horas" se juzga al
        # cierre de la primera sesión siguiente, no con el mismo precio con que empezó.
        dia = (inicios[siguiente] + desfase) // 86400
        ultima = siguiente
        while ultima + 1 < len(filas) and (inicios[ultima + 1] + desfase) // 86400 == dia:
            ultima += 1
        objetivo = inicios[ultima]
        cerrada = ultima + 1 < len(filas) or ahora - objetivo > 6 * 3600
    else:
        cerrada = ahora >= objetivo + 3600
    if not cerrada:
        return {**s, "entrada": entrada, "estado": "pendiente", "objetivo": objetivo,
                "movimiento": _mov(actual, entrada)}
    salida = _precio_en(filas, inicios, objetivo)
    movimiento = _mov(salida, entrada)
    subio = movimiento > 0
    if s["direccion"] == "neutro" or movimiento == 0:
        acierto = None
    else:
        acierto = subio == (s["direccion"] == "sube")
    return {**s, "entrada": entrada, "salida": salida, "objetivo": objetivo, "movimiento": movimiento,
            "subio": subio, "acierto": acierto, "estado": "resuelta"}


def _mov(precio, entrada):
    return (precio / entrada - 1) * 100 if precio and entrada else None


def _wilson(aciertos, n, z=1.96):
    """Intervalo del 95 % para un porcentaje de aciertos medido con n casos."""
    if n <= 0:
        return None
    p = aciertos / n
    base = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / base
    margen = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / base
    return [max(0.0, centro - margen) * 100, min(1.0, centro + margen) * 100]


def _efectivas(senales):
    """Varias noticias del mismo día sobre un activo apuestan casi por lo mismo: cuentan como una."""
    return len({(s["simbolo"], s["creado"] // 86400, s["direccion"]) for s in senales})


def _acierto(grupo):
    con_direccion = [s for s in grupo if s["acierto"] is not None]
    aciertos = sum(s["acierto"] for s in con_direccion)
    n = len(con_direccion)
    return {"n": n, "aciertos": aciertos, "pct": aciertos / n * 100 if n else None}


def _veredicto(r):
    n_ef, intervalo = r["efectivas"], r["intervalo"]
    if not r["resueltas"]:
        return "Aún no hay señales resueltas. Cada una se juzga cuando termina su horizonte."
    if n_ef < MINIMO:
        return (f"Aún son pocas: {n_ef} de unas {MINIMO} señales en días distintos que hacen falta para "
                "sacar conclusiones. Con tan pocas, el porcentaje puede ser pura suerte.")
    if intervalo[0] > 50 and r["acierto"] > r["siempre_sube"]:
        return ("Acierta la dirección más de lo que daría el azar y más que decir siempre «sube». "
                "Aun así, un acierto pasado no garantiza los siguientes.")
    if intervalo[1] < 50:
        return "Acierta menos que el azar: no conviene fiarse de sus señales."
    return "No se distingue del azar: el margen de error todavía incluye el 50 %."


def calcular():
    ahora = int(time.time())
    senales = []
    for a in datos.senales():
        for imp in a["impactos"]:
            senales.append({
                "item_id": a["item_id"], "titulo": a["titulo"], "url": a["url"], "fuente": a["fuente"],
                "modelo": a["modelo"], "creado": a["creado"], "simbolo": imp["simbolo"],
                "buy_pct": imp["buy_pct"], "direccion": imp["direccion"], "confianza": imp["confianza"],
                "horizonte": imp["horizonte"], "precio": imp.get("precio"),
            })
    simbolos = sorted({s["simbolo"] for s in senales})
    desde = {sim: min(s["creado"] for s in senales if s["simbolo"] == sim) for sim in simbolos}

    def historia(sim):
        try:
            return sim, mercado.horas(sim, desde[sim])
        except mercado.ErrorMercado:
            return sim, None

    with ThreadPoolExecutor(6) as pool:
        historias = dict(pool.map(historia, simbolos))
    actuales = {c["simbolo"]: c["precio"] for c in mercado.cotizaciones(simbolos)}

    juzgadas = [_juzgar(s, historias[s["simbolo"]], ahora, actuales.get(s["simbolo"]))
                if historias[s["simbolo"]] else {**s, "estado": "sin_datos"} for s in senales]
    resueltas = [s for s in juzgadas if s["estado"] == "resuelta"]
    con_direccion = [s for s in resueltas if s["acierto"] is not None]
    total = _acierto(resueltas)
    efectivas = _efectivas(con_direccion)
    # El intervalo se calcula con las señales efectivas: es más ancho, pero no finge más datos de los que hay.
    escala = efectivas / total["n"] if total["n"] else 0
    puntuables = [s for s in resueltas if s["movimiento"] != 0]
    brier = (sum((s["buy_pct"] / 100 - s["subio"]) ** 2 for s in puntuables) / len(puntuables)
             if puntuables else None)

    calibracion = []
    for bajo, alto, nombre in TRAMOS:
        tramo = [s for s in puntuables if bajo <= s["buy_pct"] <= alto]
        calibracion.append({
            "tramo": nombre, "n": len(tramo),
            "prob_media": sum(s["buy_pct"] for s in tramo) / len(tramo) if tramo else None,
            "subio_pct": sum(s["subio"] for s in tramo) / len(tramo) * 100 if tramo else None,
        })

    resumen = {
        "total": len(juzgadas),
        "resueltas": len(resueltas),
        "pendientes": sum(s["estado"] == "pendiente" for s in juzgadas),
        "sin_datos": sum(s["estado"] == "sin_datos" for s in juzgadas),
        "con_direccion": total["n"],
        "aciertos": total["aciertos"],
        "acierto": total["pct"],
        "efectivas": efectivas,
        "intervalo": _wilson(total["aciertos"] * escala, efectivas),
        # Lo que habría acertado alguien sin criterio que dijera siempre «sube» en esas mismas señales.
        "siempre_sube": sum(s["subio"] for s in con_direccion) / len(con_direccion) * 100 if con_direccion else None,
        "brier": brier,
        # 1 = probabilidades perfectas; 0 = igual que decir 50 % siempre; negativo = peor que eso.
        "habilidad": 1 - brier / 0.25 if brier is not None else None,
        "a_favor": (sum(s["movimiento"] if s["direccion"] == "sube" else -s["movimiento"] for s in con_direccion)
                    / len(con_direccion) if con_direccion else None),
        "minimo": MINIMO,
    }
    resumen["veredicto"] = _veredicto(resumen)
    por_activo = [{"simbolo": sim, **_acierto([s for s in resueltas if s["simbolo"] == sim]),
                   "pendientes": sum(s["estado"] == "pendiente" and s["simbolo"] == sim for s in juzgadas)}
                  for sim in simbolos]
    por_horizonte = [{"horizonte": h, **_acierto([s for s in resueltas if s["horizonte"] == h])} for h in PLAZOS]
    return {
        "resumen": resumen,
        "calibracion": calibracion,
        "por_activo": por_activo,
        "por_horizonte": por_horizonte,
        "senales": sorted(juzgadas, key=lambda s: -s["creado"])[:400],
    }
