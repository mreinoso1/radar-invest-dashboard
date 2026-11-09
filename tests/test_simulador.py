"""El simulador con velas inventadas: cada cuenta se puede hacer a mano."""
import unittest

from tests import base  # noqa: F401

import simulador  # noqa: E402

DIA = simulador.DIA
D0 = 20_000  # día (desde 1970) de la primera vela
SIN_COSTES = {"desliz_acciones_bps": 0, "desliz_cripto_bps": 0, "comision_acciones": 0, "comision_cripto": 0,
              "prestamo_acciones_pct": 0, "prestamo_cripto_pct": 0}


def velas(n=40, precio=100.0, cambios=None):
    """n velas planas: apertura y cierre en `precio`, máximo +1 y mínimo -1 (rango 2, así el ATR es 2).
    cambios: {día: dict con lo que cambia esa vela}."""
    salida = []
    for i in range(n):
        v = {"time": (D0 + i) * DIA, "open": precio, "high": precio + 1, "low": precio - 1, "close": precio}
        v.update((cambios or {}).get(i, {}))
        salida.append(v)
    return salida


def senal(dia, direccion="sube", horizonte="días", simbolo="NVDA", precio=None, id_="s1"):
    return {"id": id_, "simbolo": simbolo, "direccion": direccion, "t": (D0 + dia) * DIA, "precio": precio,
            "horizonte": horizonte, "origen": "reglas", "tipo": "reglas:volumen"}


class TamanoYSalidaTest(unittest.TestCase):
    def test_atr(self):
        self.assertEqual(simulador.atr(velas(), 20), 2.0)
        self.assertIsNone(simulador.atr(velas(), 10))  # aún no hay 14 sesiones previas

    def test_entra_al_dia_siguiente_con_tamano_por_riesgo(self):
        # Riesgo 0,5 % de 10.000 = 50 $; stop a 2 ATR = 4 $ → 12,5 acciones. Entra a la apertura del día 21.
        cambios = {28: {"close": 110.0, "high": 111.0}}  # el día 28 se cumplen los 7 días: sale al cierre
        r = simulador.simular([senal(20)], {"NVDA": velas(cambios=cambios)}, SIN_COSTES)
        [o] = r["operaciones"]
        self.assertEqual((o["dia_entrada"], o["dia_salida"], o["motivo"]), (D0 + 21, D0 + 28, "horizonte"))
        self.assertAlmostEqual(o["cantidad"], 12.5)
        self.assertAlmostEqual(o["resultado"], 12.5 * 10)
        self.assertAlmostEqual(o["rentabilidad"], 10.0)

    def test_costes_en_contra(self):
        # 5 pb de deslizamiento y 0,10 % de ida y vuelta: entra a 100,05, sale a 110 × 0,9995.
        cambios = {28: {"close": 110.0, "high": 111.0}}
        r = simulador.simular([senal(20)], {"NVDA": velas(cambios=cambios)})
        [o] = r["operaciones"]
        entrada, salida = 100 * 1.0005, 110 * 0.9995
        comisiones = o["cantidad"] * (entrada + salida) * 0.0005
        self.assertAlmostEqual(o["entrada"], entrada)
        self.assertAlmostEqual(o["resultado"], o["cantidad"] * (salida - entrada) - comisiones)

    def test_stop_por_minimo(self):
        r = simulador.simular([senal(20)], {"NVDA": velas(cambios={23: {"low": 95.0}})}, SIN_COSTES)
        [o] = r["operaciones"]
        self.assertEqual((o["motivo"], o["salida"], o["dia_salida"]), ("stop", 96.0, D0 + 23))  # stop = 100 − 4
        self.assertAlmostEqual(o["resultado"], -50.0)  # pierde justo lo que arriesgaba

    def test_abre_por_debajo_del_stop(self):
        r = simulador.simular([senal(20)], {"NVDA": velas(cambios={23: {"open": 90.0, "low": 89.0}})}, SIN_COSTES)
        [o] = r["operaciones"]
        self.assertEqual((o["motivo"], o["salida"]), ("stop (abrió más allá)", 90.0))  # pierde más que lo previsto

    def test_si_el_mismo_dia_toca_stop_y_acaba_el_plazo_gana_el_stop(self):
        r = simulador.simular([senal(20)], {"NVDA": velas(cambios={28: {"low": 95.0, "close": 120.0}})}, SIN_COSTES)
        self.assertEqual(r["operaciones"][0]["motivo"], "stop")

    def test_corto_gana_si_cae_y_paga_prestamo(self):
        cambios = {i: {"open": 90.0, "high": 91.0, "low": 89.0, "close": 90.0} for i in range(22, 40)}
        sin_prestamo = simulador.simular([senal(20, "baja")], {"NVDA": velas(cambios=cambios)}, SIN_COSTES)
        con_prestamo = simulador.simular([senal(20, "baja")], {"NVDA": velas(cambios=cambios)},
                                         {**SIN_COSTES, "prestamo_acciones_pct": 10.0})
        self.assertAlmostEqual(sin_prestamo["operaciones"][0]["resultado"], 12.5 * 10)
        self.assertLess(con_prestamo["operaciones"][0]["resultado"], sin_prestamo["operaciones"][0]["resultado"])
        sin_cortos = simulador.simular([senal(20, "baja")], {"NVDA": velas()}, {"cortos": False})
        self.assertEqual(sin_cortos["descartes"], {"cortos desactivados": 1})

    def test_senal_en_vivo_entra_a_su_precio_y_vigila_el_stop_desde_manana(self):
        # La señal llega a las 15:00 del día 20 con precio 101: el stop queda en 97. Ese día el mínimo es 96,5,
        # pero pudo ocurrir antes de las 15:00: el stop no se vigila hasta mañana, y la operación sigue viva.
        en_vivo = senal(20, precio=101.0)
        en_vivo["t"] += 15 * 3600
        r = simulador.simular([en_vivo], {"NVDA": velas(cambios={20: {"low": 96.5}})}, SIN_COSTES)
        [o] = r["operaciones"]
        self.assertEqual((o["entrada"], o["dia_entrada"], o["motivo"]), (101.0, D0 + 20, "horizonte"))


class LimitesTest(unittest.TestCase):
    def test_limite_de_perdida_diaria_bloquea_el_dia_siguiente(self):
        # Dos posiciones grandes que pierden mucho el día 25; la señal del día 25 (entra el 26) no se abre.
        cfg = {**SIN_COSTES, "riesgo_pct": 5.0, "max_peso_pct": 50.0}
        caida = {25: {"open": 99.0, "low": 96.5, "close": 97.0}}
        r = simulador.simular([senal(20, simbolo="A", id_="a"), senal(20, simbolo="B", id_="b"),
                               senal(25, simbolo="C", id_="c")],
                              {"A": velas(cambios=caida), "B": velas(cambios=caida), "C": velas()}, cfg)
        self.assertEqual(r["descartes"].get("límite de pérdida diaria"), 1)

    def test_maximo_de_posiciones_y_un_activo_cada_vez(self):
        r = simulador.simular([senal(20, simbolo="A", id_="a"), senal(20, simbolo="A", id_="a2"),
                               senal(20, simbolo="B", id_="b")],
                              {"A": velas(), "B": velas()}, {**SIN_COSTES, "max_posiciones": 1})
        self.assertEqual(r["descartes"], {"máximo de posiciones": 1, "ya había posición en ese activo": 1})


class MetricasTest(unittest.TestCase):
    def test_caida_maxima_y_rentabilidad(self):
        curva = [(D0, 100.0), (D0 + 1, 110.0), (D0 + 2, 99.0), (D0 + 3, 121.0)]
        m = simulador.metricas(curva, [], 100.0)
        self.assertAlmostEqual(m["rentabilidad"], 21.0)
        self.assertAlmostEqual(m["max_caida"], -10.0)  # de 110 a 99

    def test_exceso_frente_al_indice(self):
        # El índice sube un 5 % mientras dura la operación (del cierre anterior a la entrada al de salida).
        indice = velas(cambios={i: {"close": 105.0, "open": 105.0, "high": 106.0, "low": 104.0} for i in range(21, 40)})
        cambios = {28: {"close": 110.0, "high": 111.0}}
        r = simulador.simular([senal(20)], {"NVDA": velas(cambios=cambios)}, SIN_COSTES, {"SPY": indice})
        [o] = r["operaciones"]
        self.assertAlmostEqual(o["mov_indice"], 5.0)
        self.assertAlmostEqual(o["exceso"], 5.0)  # ganó un 10 %, el índice un 5 %

    def test_la_curva_empieza_con_la_primera_entrada(self):
        r = simulador.simular([senal(20)], {"NVDA": velas()}, SIN_COSTES)
        self.assertEqual(r["curva"][0][0], D0 + 21)  # no en el día 0: la estrategia aún no existía
        self.assertEqual(simulador.simular([], {"NVDA": velas()})["curva"], [])

    def test_curva_del_indice_con_el_mismo_capital(self):
        indice = velas(5, cambios={4: {"close": 110.0}})
        curva = simulador.curva_indice(indice, [D0 + i for i in range(5)], 10_000)
        self.assertEqual((curva[0][1], curva[-1][1]), (10_000, 11_000))


if __name__ == "__main__":
    unittest.main()
