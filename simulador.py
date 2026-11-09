"""Simulador: opera señales con dinero ficticio, con costes, tamaño por riesgo y límites, sobre velas diarias.

Es una función pura, como el marcador: recibe señales, velas y configuración, y devuelve operaciones, curva
de capital y métricas. No guarda estado que pueda corromperse: se recalcula entero cada vez. El paper trading
y el backtest usan este mismo simulador; solo cambia de dónde salen las señales.

Supuestos, siempre del lado prudente:
- Una señal sin precio (las del backtest, calculadas con el cierre) entra a la apertura del día siguiente.
  Una señal en vivo entra a su precio ese mismo día y su stop se vigila desde el día siguiente.
- Con velas diarias no se sabe qué pasó antes dentro del día: si una vela toca el stop y además acaba el
  horizonte, gana el stop. Si abre más allá del stop, se sale a la apertura, no al stop.
- Deslizamiento en contra al entrar y al salir, comisión por cada lado y coste de préstamo en los cortos.
- Sin apalancamiento: la suma de posiciones no pasa del capital.
"""
import math
import statistics

import marcador

DIA = 86400
CONFIG = {
    "capital": 10_000.0,          # dinero ficticio con el que empieza
    "riesgo_pct": 0.5,            # % del capital que se pierde si salta el stop
    "stop_atr": 2.0,              # distancia del stop, en ATR de 14 sesiones
    "max_posiciones": 10,
    "max_peso_pct": 20.0,         # % del capital como mucho en una posición
    "perdida_diaria_pct": 2.0,    # si el capital cae más en un día, no se abre nada al siguiente
    "desliz_acciones_bps": 5.0,   # puntos básicos en contra al entrar y al salir
    "desliz_cripto_bps": 10.0,
    "comision_acciones": 0.10,    # % de ida y vuelta (la mitad en cada lado)
    "comision_cripto": 0.52,
    "cortos": True,
    "prestamo_acciones_pct": 1.0,  # % anual que cuesta un corto
    "prestamo_cripto_pct": 11.0,   # más o menos el funding fijo de los perpetuos
}


def config_actual(ajustes):
    """La configuración en uso: la de serie, las comisiones del marcador y lo que el usuario cambió."""
    return {**CONFIG, "comision_acciones": ajustes["comision_acciones"], "comision_cripto": ajustes["comision_cripto"],
            **{k: v for k, v in (ajustes.get("simulacion") or {}).items() if k in CONFIG}}


def atr(velas, i, n=14):
    """ATR de las n sesiones anteriores a la vela i (sin incluirla: al abrir aún no se conoce)."""
    if i < n + 1:
        return None
    rangos = [max(velas[k]["high"], velas[k - 1]["close"]) - min(velas[k]["low"], velas[k - 1]["close"])
              for k in range(i - n, i)]
    return sum(rangos) / n


def _indices_por_dia(velas):
    return {v["time"] // DIA: k for k, v in enumerate(velas)}


def _cierre_hasta(velas, dias, dia):
    """Último cierre de una serie en `dia` o antes."""
    for d in range(dia, dia - 10, -1):
        if d in dias:
            return velas[dias[d]]["close"]
    return None


def _entrada(s, velas, dias):
    """(índice de la vela, precio base, ¿vigilar el stop ese mismo día?) o None si no hay vela posible."""
    dia = int(s["t"]) // DIA
    if s.get("precio") and dia in dias:
        return dias[dia], s["precio"], False
    siguientes = [d for d in dias if d > dia]
    if not siguientes:
        return None
    k = dias[min(siguientes)]
    return k, velas[k]["open"], True


def simular(senales, velas, cfg=None, indices=None):
    """senales: dicts con id, simbolo, direccion ("sube"/"baja"), t, precio (None = apertura siguiente),
    horizonte, origen y tipo. velas: {símbolo: velas diarias}. indices: {"SPY": velas, "BTC-USD": velas}."""
    c = {**CONFIG, **(cfg or {})}
    indices = indices or {}
    dias_de = {s: _indices_por_dia(v) for s, v in {**velas, **indices}.items()}
    programadas = {}
    descartes = {}
    for s in sorted(senales, key=lambda s: s["t"]):
        if s["direccion"] not in ("sube", "baja") or s["simbolo"] not in velas:
            descartes["sin datos"] = descartes.get("sin datos", 0) + 1
            continue
        e = _entrada(s, velas[s["simbolo"]], dias_de[s["simbolo"]])
        if e is None:
            descartes["aún sin vela de entrada"] = descartes.get("aún sin vela de entrada", 0) + 1
            continue
        dia = velas[s["simbolo"]][e[0]]["time"] // DIA
        programadas.setdefault(dia, []).append((s, *e))

    # La curva empieza el día de la primera entrada: antes la estrategia no existía, y comparar con lo que el
    # índice subió en esos años sería injusto con ella.
    primera = min(programadas) if programadas else None
    todos = sorted(d for d in {d for s in velas for d in dias_de[s]} if primera is not None and d >= primera)
    efectivo, abiertas, cerradas, curva = c["capital"], [], [], []
    bloqueado_hasta, previo, ultimo_dia = None, c["capital"], None

    def descartar(motivo):
        descartes[motivo] = descartes.get(motivo, 0) + 1

    for dia in todos:
        referencia = curva[-1][1] if curva else c["capital"]
        # 1. Entradas del día, antes que nada: se ejecutan a la apertura o al precio de la señal.
        for s, k, base, vigilar_hoy in programadas.get(dia, []):
            sentido = 1 if s["direccion"] == "sube" else -1
            cripto = marcador.es_cripto(s["simbolo"])
            if bloqueado_hasta is not None and dia <= bloqueado_hasta:
                descartar("límite de pérdida diaria")
                continue
            if sentido < 0 and not c["cortos"]:
                descartar("cortos desactivados")
                continue
            if any(p["simbolo"] == s["simbolo"] for p in abiertas):
                descartar("ya había posición en ese activo")
                continue
            if len(abiertas) >= c["max_posiciones"]:
                descartar("máximo de posiciones")
                continue
            vs = velas[s["simbolo"]]
            rango = atr(vs, k)
            if not rango:
                descartar("sin historial para el ATR")
                continue
            desliz = (c["desliz_cripto_bps"] if cripto else c["desliz_acciones_bps"]) / 10_000
            precio = base * (1 + desliz * sentido)  # en contra: el largo compra más caro, el corto vende más barato
            distancia = c["stop_atr"] * rango
            cantidad = referencia * c["riesgo_pct"] / 100 / distancia
            cantidad = min(cantidad, referencia * c["max_peso_pct"] / 100 / precio)
            expuesto = sum(p["cantidad"] * p["ultimo"] for p in abiertas)
            cantidad = min(cantidad, max(0.0, referencia - expuesto) / precio)  # sin apalancamiento
            if cantidad * precio < 1:
                descartar("sin capital libre")
                continue
            comision = cantidad * precio * (c["comision_cripto"] if cripto else c["comision_acciones"]) / 200
            efectivo += -sentido * cantidad * precio - comision
            fin = (s["t"] if not vigilar_hoy else dia * DIA) + marcador.PLAZOS.get(s["horizonte"], marcador.PLAZOS["días"])
            abiertas.append({**{k2: s.get(k2) for k2 in ("id", "simbolo", "direccion", "origen", "tipo", "horizonte", "t")},
                             "sentido": sentido, "cantidad": cantidad, "entrada": precio, "dia_entrada": dia,
                             "stop": precio - sentido * distancia, "fin": fin, "vigilar_desde": dia if vigilar_hoy else dia + 1,
                             "costes": comision, "ultimo": precio, "cripto": cripto, "desliz": desliz})

        # 2. Salidas: stop (primero, por prudencia) u horizonte cumplido.
        for p in list(abiertas):
            k = dias_de[p["simbolo"]].get(dia)
            if k is None:
                continue
            v = velas[p["simbolo"]][k]
            if ultimo_dia is not None and p["sentido"] < 0:  # el corto paga préstamo por cada día que pasa
                tasa = c["prestamo_cripto_pct"] if p["cripto"] else c["prestamo_acciones_pct"]
                coste = p["cantidad"] * p["ultimo"] * tasa / 100 / 365 * (dia - ultimo_dia)
                efectivo -= coste
                p["costes"] += coste
            salida, motivo = None, None
            if dia >= p["vigilar_desde"]:
                abre_mal = v["open"] <= p["stop"] if p["sentido"] > 0 else v["open"] >= p["stop"]
                toca = v["low"] <= p["stop"] if p["sentido"] > 0 else v["high"] >= p["stop"]
                if abre_mal:
                    salida, motivo = v["open"], "stop (abrió más allá)"
                elif toca:
                    salida, motivo = p["stop"], "stop"
            if salida is None and dia * DIA + DIA > p["fin"]:
                salida, motivo = v["close"], "horizonte"
            p["ultimo"] = v["close"]
            if salida is None:
                continue
            precio = salida * (1 - p["desliz"] * p["sentido"])
            comision = p["cantidad"] * precio * (c["comision_cripto"] if p["cripto"] else c["comision_acciones"]) / 200
            efectivo += p["sentido"] * p["cantidad"] * precio - comision
            p["costes"] += comision
            abiertas.remove(p)
            cerradas.append(_cerrar(p, precio, dia, motivo, indices, dias_de))

        # 3. Valoración al cierre y límite de pérdida diaria.
        capital = efectivo + sum(p["sentido"] * p["cantidad"] * p["ultimo"] for p in abiertas)
        curva.append((dia, capital))
        if capital < previo * (1 - c["perdida_diaria_pct"] / 100):
            bloqueado_hasta = dia + 1
            descartes.setdefault("días bloqueados", 0)
            descartes["días bloqueados"] += 1
        previo, ultimo_dia = capital, dia

    return {"operaciones": cerradas, "abiertas": [_vista_abierta(p) for p in abiertas], "curva": curva,
            "descartes": descartes, "config": c, "metricas": metricas(curva, cerradas, c["capital"])}


def _cerrar(p, salida, dia, motivo, indices, dias_de):
    bruto = p["sentido"] * p["cantidad"] * (salida - p["entrada"])
    resultado = bruto - p["costes"]
    rentab = resultado / (p["cantidad"] * p["entrada"]) * 100
    indice = marcador.indice_de(p["simbolo"])
    mov_indice = None
    if indice in indices:
        a = _cierre_hasta(indices[indice], dias_de[indice], p["dia_entrada"] - 1)
        b = _cierre_hasta(indices[indice], dias_de[indice], dia)
        mov_indice = (b / a - 1) * 100 if a and b else None
    # Exceso: lo que ganó frente a lo que habría hecho su índice en esos días (un corto gana si cae más que él).
    exceso = rentab - p["sentido"] * mov_indice if mov_indice is not None else rentab
    return {k: p[k] for k in ("id", "simbolo", "direccion", "origen", "tipo", "horizonte", "t", "cantidad", "entrada",
                              "dia_entrada", "cripto")} | {
        "salida": salida, "dia_salida": dia, "motivo": motivo, "resultado": resultado, "costes": p["costes"],
        "rentabilidad": rentab, "mov_indice": mov_indice, "exceso": exceso}


def _vista_abierta(p):
    return {k: p[k] for k in ("id", "simbolo", "direccion", "origen", "tipo", "cantidad", "entrada", "dia_entrada",
                              "stop", "ultimo")} | {
        "resultado": p["sentido"] * p["cantidad"] * (p["ultimo"] - p["entrada"]) - p["costes"]}


def metricas(curva, operaciones, capital):
    if len(curva) < 2:
        return {"operaciones": len(operaciones), "rentabilidad": None}
    valores = [v for _, v in curva]
    anios = max((curva[-1][0] - curva[0][0]) / 365.25, 1 / 365.25)
    por_anio = len(curva) / anios  # puntos por año: 252 con solo acciones, 365 si hay cripto
    diarias = [b / a - 1 for a, b in zip(valores, valores[1:]) if a > 0]
    media, desv = (statistics.mean(diarias), statistics.stdev(diarias)) if len(diarias) > 1 else (0, 0)
    pico, caida = valores[0], 0.0
    for v in valores:
        pico = max(pico, v)
        caida = min(caida, v / pico - 1)
    ganadas = [o["resultado"] for o in operaciones if o["resultado"] > 0]
    perdidas = [-o["resultado"] for o in operaciones if o["resultado"] <= 0]
    return {
        "operaciones": len(operaciones),
        "rentabilidad": (valores[-1] / capital - 1) * 100,
        "cagr": ((valores[-1] / capital) ** (1 / anios) - 1) * 100 if valores[-1] > 0 else None,
        "volatilidad": desv * math.sqrt(por_anio) * 100,
        "sharpe": media / desv * math.sqrt(por_anio) if desv else None,  # sin tipo libre de riesgo
        "max_caida": caida * 100,
        "aciertos": len(ganadas) / len(operaciones) * 100 if operaciones else None,
        "profit_factor": sum(ganadas) / sum(perdidas) if perdidas and sum(perdidas) else None,
        "exceso_medio": statistics.mean(o["exceso"] for o in operaciones) if operaciones else None,
        "costes": sum(o["costes"] for o in operaciones),
        "capital_final": valores[-1],
    }


def curva_indice(velas_indice, dias, capital):
    """Comprar y mantener el índice durante los mismos días, empezando con el mismo capital."""
    por_dia = _indices_por_dia(velas_indice)
    salida, inicial, ultimo = [], None, None
    for d in dias:
        cierre = _cierre_hasta(velas_indice, por_dia, d)
        if cierre is None:
            continue
        inicial = inicial or cierre
        ultimo = capital * cierre / inicial
        salida.append((d, ultimo))
    return salida
