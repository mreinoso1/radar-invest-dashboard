"""Señales por reglas: Python mira los datos cuantitativos y apuesta por una dirección cuando se cumple una
condición fijada de antemano. No usan el modelo, pero son señales: el marcador las juzga como a todas
(Wilson, Brier, "siempre sube", índice y comisiones).

Los umbrales se fijaron el 2026-11-09, antes de ver ningún resultado, y no se tocan mirando el marcador:
eso sería ajustarlos al ruido. Se revisarán con el backtest de la Fase 4, sobre datos que no hayan visto.

La probabilidad no se decide a ojo: empieza en 55 (o 45), la ventaja mínima para tener dirección, y en
cuanto la regla tiene MIN_HISTORIAL señales efectivas resueltas pasa a ser su tasa de acierto medida.
"""
import time

import calibracion
import cuant
import datos
import marcador
import mercado

REVISION_MIN = 3.0        # % de subida del BPA estimado en 30 días
INSIDERS_MIN = 2          # directivos distintos que compran en el mercado en 90 días
# Añadido el mismo día, antes de cualquier resultado: los datos reales mostraron compras rutinarias de planes
# periódicos (31 directivos de TSMC por 0,53 M$ en total), que no son la apuesta discrecional que busca la regla.
INSIDERS_VALOR_MIN = 250_000  # $ comprados en total
FUNDING_ALTO = 40.0       # % anual: demasiada gente apalancada al alza
FUNDING_BAJO = -20.0      # % anual: demasiada gente apalancada a la baja
VOLUMEN_MIN = 3.0         # veces el volumen medio de 20 sesiones
MOVIMIENTO_MIN = 4.0      # % en esa sesión
HORIZONTES = {"revisiones": "semanas", "insiders": "meses", "funding": "días", "volumen": "días"}
PROB_INICIAL = 55
MIN_HISTORIAL = 30


def _es(v, formato="+.1f"):
    """Número con coma decimal, como se escribe en español."""
    return format(v, formato).replace(".", ",")


def evaluar(c):
    """[(regla, dirección, detalle)] que se cumplen con los datos de un activo. Función pura."""
    salida = []
    r = c.get("revisiones")
    if r and r["cambio_30d"] is not None and r["cambio_30d"] >= REVISION_MIN and r["suben_30d"] > r["bajan_30d"]:
        salida.append(("revisiones", "sube", f"BPA estimado {_es(r['cambio_30d'])} % en 30 días, con "
                                             f"{r['suben_30d']} revisiones al alza y {r['bajan_30d']} a la baja"))
    i = c.get("insiders")
    if (i and i["compradores"] >= INSIDERS_MIN and i["valor_compras"] >= INSIDERS_VALOR_MIN
            and i["valor_compras"] > i["valor_ventas"]):
        salida.append(("insiders", "sube", f"{i['compradores']} directivos compran en el mercado en 90 días "
                                           f"({_es(i['valor_compras'] / 1e6, '.2f')} M$ frente a "
                                           f"{_es(i['valor_ventas'] / 1e6, '.2f')} M$ en ventas)"))
    k = c.get("cripto")
    funding = k and (k["funding_hl"] if k["funding_hl"] is not None else k["funding_kraken"])
    if funding is not None and funding >= FUNDING_ALTO:
        salida.append(("funding", "baja", f"funding {_es(funding)} % anual: muchos largos apalancados que pagan por estarlo"))
    elif funding is not None and funding <= FUNDING_BAJO:
        salida.append(("funding", "sube", f"funding {_es(funding)} % anual: muchos cortos apalancados que pagan por estarlo"))
    v = c.get("volumen")
    if v and v["movimiento"] is not None and v["relativo"] >= VOLUMEN_MIN and abs(v["movimiento"]) >= MOVIMIENTO_MIN:
        salida.append(("volumen", "sube" if v["movimiento"] > 0 else "baja",
                       f"volumen {_es(v['relativo'], '.1f')} veces lo normal con un movimiento de "
                       f"{_es(v['movimiento'])} % el {v['dia']}"))
    return salida


def prob(regla, direccion, tipos):
    """55 o 45 mientras no haya historial; después, la tasa de acierto medida de la regla, aunque salga peor
    que el azar. La dirección se guarda aparte, así una regla mala sigue juzgándose en vez de volverse neutra."""
    t = next((x for x in tipos if x["tipo"] == f"reglas:{regla}"), None)
    acierto = PROB_INICIAL if not t or t["efectivas"] < MIN_HISTORIAL or t["acierto"] is None else round(t["acierto"])
    acierto = max(5, min(95, acierto))
    return acierto if direccion == "sube" else 100 - acierto


def pendientes(ahora):
    """(regla, símbolo) con una señal aún sin juzgar: no se repite mientras tanto."""
    return {(s["regla"], s["simbolo"]) for s in datos.senales_reglas(int(ahora) - 100 * 86400)
            if s["creado"] + marcador.PLAZOS[s["horizonte"]] > ahora}


def generar(simbolos, ahora=None, tipos=None):
    """Evalúa las reglas sobre cada activo y guarda las señales nuevas. Devuelve las guardadas."""
    ahora = ahora or time.time()
    if tipos is None:
        tipos = marcador.calcular("reglas")["por_tipo"]
    abiertas = pendientes(ahora)
    nuevas = []
    for s in simbolos:
        for regla, direccion, detalle in evaluar(cuant.de_activo(s, ahora)):
            if (regla, s) in abiertas:
                continue
            try:
                precio = mercado.cotizacion(s)["precio"]
            except mercado.ErrorMercado:
                continue
            senal = {"regla": regla, "simbolo": s, "direccion": direccion, "prob_subida": prob(regla, direccion, tipos),
                     "horizonte": HORIZONTES[regla], "detalle": f"{s}: {detalle}", "precio": precio,
                     "creado": int(ahora)}
            datos.guardar_senal_regla(senal)
            nuevas.append(senal)
    return nuevas
