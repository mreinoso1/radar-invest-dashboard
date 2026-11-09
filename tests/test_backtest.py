"""Backtest y paper trading, sin red. El test clave: cambiar el futuro no cambia las señales del pasado."""
import random
import time
import unittest
from unittest import mock

from tests import base

import backtest  # noqa: E402
import criterio  # noqa: E402
import datos  # noqa: E402
import paper  # noqa: E402
import simulador  # noqa: E402

DIA = simulador.DIA
D0 = 18_000


def velas_al_azar(n=400, semilla=1, picos=(60, 150, 250, 330)):
    """Una serie que pasea al azar, con días de volumen y movimiento grandes en `picos`."""
    azar = random.Random(semilla)
    salida, precio = [], 100.0
    for i in range(n):
        abre = precio
        precio *= 1 + (0.06 if i in picos else azar.uniform(-0.015, 0.015))
        salida.append({"time": (D0 + i) * DIA, "open": abre, "high": max(abre, precio) * 1.005,
                       "low": min(abre, precio) * 0.995, "close": precio,
                       "volume": 5000 if i in picos else 1000 + azar.randint(-100, 100)})
    return salida


class SinMirarElFuturoTest(unittest.TestCase):
    def test_cambiar_el_futuro_no_cambia_el_pasado(self):
        original = velas_al_azar()
        corte = 200
        alterado = original[:corte] + velas_al_azar(semilla=99, picos=(210, 260))[corte:]
        antes = [s for s in backtest.senales_volumen("X", original) if s["t"] < original[corte]["time"]]
        despues = [s for s in backtest.senales_volumen("X", alterado) if s["t"] < original[corte]["time"]]
        self.assertTrue(antes)  # hay señales que comparar
        self.assertEqual(antes, despues)

    def test_la_senal_es_del_dia_del_pico_y_se_opera_al_dia_siguiente(self):
        v = velas_al_azar()
        primera = backtest.senales_volumen("X", v)[0]
        self.assertEqual((primera["t"], primera["direccion"], primera["precio"]), (v[60]["time"], "sube", None))
        r = simulador.simular([primera], {"X": v})
        self.assertEqual(r["operaciones"][0]["dia_entrada"], D0 + 61)

    def test_insiders_cuentan_desde_que_se_hacen_publicos(self):
        compra = lambda nombre, fecha: {"codigo": "P", "nombre": nombre, "acciones": 10_000, "precio": 30.0,
                                        "fecha": fecha, "emisor": 1}
        # Compraron el 1 y el 2 de marzo, pero los Form 4 se presentaron el 5 y el 20: la señal es del 20.
        historia = [("2026-03-05", compra("A", "2026-03-01")), ("2026-03-20", compra("B", "2026-03-02"))]
        [s] = backtest.senales_insiders("EJEM", historia)
        self.assertEqual(time.strftime("%Y-%m-%d", time.gmtime(s["t"])), "2026-03-20")
        # Una presentación posterior no cambia esa señal.
        mas = historia + [("2026-06-01", compra("C", "2026-05-30"))]
        self.assertEqual(backtest.senales_insiders("EJEM", mas)[0], s)


class FundingTest(unittest.TestCase):
    def test_funding_diario_y_umbrales(self):
        hora = 3600 * 1000
        filas = [(0, 0.0000125), (23 * hora, 0.00005), (DIA * 1000 + hora, -0.00003), (8 * DIA * 1000, -0.00003)]
        por_dia = backtest.funding_diario(filas)
        self.assertAlmostEqual(por_dia[0], 0.00005 * 8760 * 100)  # el último dato de cada día: 43,8 % anual
        senales = backtest.senales_funding("BTC-USD", por_dia)
        # El día 1 también se cumple, pero la señal del día 0 sigue pendiente (7 días): no se repite la regla.
        self.assertEqual([(s["direccion"], s["t"]) for s in senales], [("baja", 0), ("sube", 8 * DIA)])

    def test_descarga_por_paginas_y_continua_donde_lo_dejo(self):
        base.limpiar()
        paginas = [[{"time": i, "fundingRate": "0.00001"} for i in range(500)],
                   [{"time": 500 + i, "fundingRate": "0.00002"} for i in range(3)], [],
                   [{"time": 503, "fundingRate": "0.00003"}]]
        pedidas = []

        def hl(cuerpo):
            pedidas.append(cuerpo["startTime"])
            return paginas.pop(0)

        with mock.patch.object(backtest, "_hyperliquid", side_effect=hl), mock.patch.object(backtest.time, "sleep"):
            self.assertEqual(len(backtest.descargar_funding("BTC")), 503)
            backtest.descargar_funding("BTC")  # segunda vez: solo lo nuevo
        self.assertEqual(pedidas, [0, 500, 503])


class EjecutarYCriterioTest(unittest.TestCase):
    def setUp(self):
        base.limpiar()

    def test_backtest_completo_con_datos_inventados(self):
        velas = {"X": velas_al_azar(), "Y": velas_al_azar(semilla=2)}
        r = backtest.ejecutar(velas, {"SPY": velas_al_azar(semilla=3, picos=())}, {}, {}, simulador.CONFIG, ["volumen"])
        self.assertGreater(r["senales"], 0)
        self.assertEqual([p["nombre"] for p in r["criterio"]], ["Backtest, periodo completo", "Backtest, últimos 2 años"])
        self.assertEqual(r["huella"], criterio.huella(simulador.CONFIG, ["volumen"]))
        self.assertEqual({t["tipo"] for t in r["por_regla"]}, {"reglas:volumen"})

    def test_insiders_sin_contacto_no_se_lanza(self):
        self.assertIn("contacto", backtest.lanzar(con_insiders=True))

    def test_paper_cuenta_solo_las_reglas_del_backtest_y_la_version_actual(self):
        ops = [{"tipo": "reglas:volumen", "t": 2000}, {"tipo": "reglas:volumen", "t": 500},
               {"tipo": "reglas:revisiones", "t": 3000}, {"tipo": "cartera:macro", "t": 3000}]
        self.assertEqual(paper.para_criterio(ops, ["volumen"], 1000), [ops[0]])

    def test_backtest_de_otra_version_no_vale(self):
        datos.guardar_simulacion("backtest", {"huella": "vieja", "incluidas": ["volumen"],
                                              "criterio": [{"nombre": "Backtest", "pasa": True, "puntos": []}]})
        with mock.patch.object(paper, "calcular", return_value={
                "huella": "nueva", "desde": 0, "incluidas": ["volumen"],
                "criterio": {"nombre": "Paper", "pasa": True, "puntos": []}}):
            e = paper.estado_fase5()
        self.assertFalse(e["desbloqueada"])
        self.assertIn("otra versión", e["partes"][0]["nota"])


if __name__ == "__main__":
    unittest.main()
