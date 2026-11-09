"""El criterio de la Fase 5: bootstrap, Bonferroni, ventanas y huella."""
import unittest
from unittest import mock

from tests import base

import criterio  # noqa: E402
import simulador  # noqa: E402


def operaciones(excesos, por_dia=1, cripto=False):
    return [{"exceso": e, "dia_entrada": 20_000 + i // por_dia, "cripto": cripto} for i, e in enumerate(excesos)]


class BootstrapTest(unittest.TestCase):
    def test_ventaja_clara_excluye_el_cero(self):
        ic = criterio.bootstrap(operaciones([1.0, 2.0, 1.5, 0.5, 1.2] * 30), 0.95)
        self.assertGreater(ic[0], 0)

    def test_ruido_incluye_el_cero(self):
        ic = criterio.bootstrap(operaciones([1.0, -1.0] * 60), 0.95)
        self.assertLess(ic[0], 0)
        self.assertGreater(ic[1], 0)

    def test_misma_semilla_mismo_intervalo(self):
        ops = operaciones([0.3, -0.1, 0.8, -0.4, 0.2] * 20)
        self.assertEqual(criterio.bootstrap(ops, 0.95), criterio.bootstrap(ops, 0.95))

    def test_un_dia_con_muchas_operaciones_cuenta_como_un_bloque(self):
        # 100 operaciones ganadoras, pero todas del mismo día: no hay forma de saber si fue suerte de ese día.
        self.assertIsNone(criterio.bootstrap(operaciones([1.0] * 100, por_dia=100), 0.95))

    def test_bonferroni_ensancha_el_intervalo(self):
        ops = operaciones([0.6, -0.3, 0.9, -0.5, 0.4] * 25)
        uno = criterio.bootstrap(ops, 1 - 0.05)
        tres = criterio.bootstrap(ops, 1 - 0.05 / 3)
        self.assertLessEqual(tres[0], uno[0])
        self.assertGreaterEqual(tres[1], uno[1])


class EvaluarTest(unittest.TestCase):
    def test_pasa_y_no_pasa(self):
        buenas = operaciones([1.0, 2.0, 1.5, 0.5, 1.2] * 30)
        r = criterio.evaluar(buenas, 25.0, {"SPY": 10.0, "BTC-USD": 40.0}, 1, 100, "x")
        self.assertTrue(r["pasa"])
        r = criterio.evaluar(buenas, 5.0, {"SPY": 10.0, "BTC-USD": 40.0}, 1, 100, "x")
        self.assertEqual([p["ok"] for p in r["puntos"]], [True, False, True])  # no le gana al índice
        r = criterio.evaluar(buenas[:50], 25.0, {"SPY": 10.0}, 1, 100, "x")
        self.assertFalse(r["puntos"][0]["ok"])  # pocas operaciones

    def test_indice_mezclado_por_tipo_de_activo(self):
        ops = operaciones([1] * 3) + operaciones([1], cripto=True)
        self.assertAlmostEqual(criterio.mezcla(ops, {"SPY": 10.0, "BTC-USD": 50.0}), 0.75 * 10 + 0.25 * 50)

    def test_ventana_reciente(self):
        dias = [20_000 + i for i in range(1000)]
        resultado = {"curva": [(d, 100.0 + (d - 20_000) * 0.1) for d in dias],
                     "operaciones": operaciones([1.0] * 50) + [{"exceso": 1.0, "dia_entrada": 20_900 + i, "cripto": False}
                                                              for i in range(40)]}
        total, reciente = criterio.evaluar_backtest(resultado, {}, 1)
        self.assertEqual(total["puntos"][0]["valor"], 90)
        self.assertEqual(reciente["puntos"][0]["valor"], 40)  # solo las de los dos últimos años

    def test_paper(self):
        self.assertTrue(criterio.evaluar_paper(operaciones([0.2] * 30))["pasa"])
        self.assertFalse(criterio.evaluar_paper(operaciones([0.2] * 29))["pasa"])
        self.assertFalse(criterio.evaluar_paper(operaciones([-0.1] * 40))["pasa"])
        self.assertFalse(criterio.desbloqueada([]))


class HuellaTest(unittest.TestCase):
    def test_cualquier_cambio_cambia_la_huella(self):
        base_ = criterio.huella(simulador.CONFIG, ["volumen", "funding"])
        self.assertEqual(base_, criterio.huella(dict(simulador.CONFIG), ["funding", "volumen"]))  # el orden da igual
        self.assertNotEqual(base_, criterio.huella({**simulador.CONFIG, "stop_atr": 2.5}, ["volumen", "funding"]))
        self.assertNotEqual(base_, criterio.huella(simulador.CONFIG, ["volumen"]))
        with mock.patch.object(criterio.reglas, "VOLUMEN_MIN", 2.5):
            self.assertNotEqual(base_, criterio.huella(simulador.CONFIG, ["volumen", "funding"]))

    def test_la_version_empieza_a_contar_la_primera_vez(self):
        base.limpiar()
        self.assertEqual(criterio.inicio_version("abc", 1000), 1000)
        self.assertEqual(criterio.inicio_version("abc", 5000), 1000)  # no se reinicia


if __name__ == "__main__":
    unittest.main()
