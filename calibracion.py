"""Cuánto vale cada tipo de señal según su historial en el marcador, y el Top 5 del día.

Tipo de señal: de dónde sale y qué la causa. Por ejemplo cartera:macro, ideas:proveedor o reglas:funding.

Peso de un tipo: cuánto le ha ganado al índice, contraído hacia 0 cuando hay pocos datos (shrinkage):

    peso = efectivas / (efectivas + 30) × (acierto frente al índice − 50) / 50

Sin historial vale 0. Con 30 señales efectivas cuenta la mitad de su ventaja medida, y con muchas, casi
toda. Si un tipo pierde frente al índice, su peso es negativo. Así ningún tipo gana importancia por sonar
seguro: solo por acertar de forma medida.
"""
import marcador

CONTRACCION = 30


def tipo_de(s):
    return f"{s['origen']}:{s.get('subtipo') or 'otro'}"


def _exito(s):
    """Le ganó al índice. Si no hay índice con el que comparar (BTC contra sí mismo), acertó la dirección."""
    return s["relativo"] > 0 if s.get("relativo") is not None else s["acierto"]


def por_tipo(juzgadas):
    grupos = {}
    for s in juzgadas:
        grupos.setdefault(tipo_de(s), []).append(s)
    salida = []
    for tipo, grupo in sorted(grupos.items()):
        con_direccion = [s for s in grupo if s["estado"] == "resuelta" and s["acierto"] is not None]
        pct, intervalo = marcador._proporcion(con_direccion, _exito)
        acierto, _ = marcador._proporcion(con_direccion, lambda s: s["acierto"])
        efectivas = marcador._efectivas(con_direccion)
        salida.append({
            "tipo": tipo, "resueltas": len(con_direccion), "efectivas": efectivas,
            "pendientes": sum(s["estado"] == "pendiente" for s in grupo),
            "frente_indice": pct, "intervalo": intervalo, "acierto": acierto,
            "neto_medio": marcador._media([s.get("neto") for s in con_direccion]),
            "peso": efectivas / (efectivas + CONTRACCION) * (pct - 50) / 50 if pct is not None else 0.0,
        })
    return salida


def top(juzgadas, tipos, ahora, n=5, horas=48):
    """Las n señales pendientes más claras de las últimas `horas`: confianza × distancia a 50 × (1 + peso de su
    tipo). Quedan fuera los tipos que han demostrado perder frente al índice, y cada activo sale una vez."""
    info = {t["tipo"]: t for t in tipos}
    candidatas = []
    for s in juzgadas:
        if s["estado"] != "pendiente" or s["creado"] < ahora - horas * 3600 or s["direccion"] == "neutro":
            continue
        t = info.get(tipo_de(s), {"peso": 0.0, "efectivas": 0, "frente_indice": None, "intervalo": None})
        if t["peso"] < 0:
            continue
        puntos = s["confianza"] / 100 * abs(s["buy_pct"] - 50) * (1 + t["peso"])
        candidatas.append({**s, "tipo": tipo_de(s), "puntos": puntos, "peso": t["peso"],
                           "historial": {k: t.get(k) for k in ("efectivas", "frente_indice", "intervalo")}})
    salida, vistos = [], set()
    for s in sorted(candidatas, key=lambda s: -s["puntos"]):
        if s["simbolo"] not in vistos:
            vistos.add(s["simbolo"])
            salida.append(s)
    return salida[:n]
