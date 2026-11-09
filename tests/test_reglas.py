"""Señales por reglas, pesos por tipo de señal y Top 5. Sin red: los datos se inventan."""
import time
import unittest
from unittest import mock

from tests import base

import calibracion  # noqa: E402
import cuant  # noqa: E402
import datos  # noqa: E402
import marcador  # noqa: E402
import mercado  # noqa: E402
import reglas  # noqa: E402


def revision(cambio, suben=3, bajan=1):
    return {"revisiones": {"cambio_30d": cambio, "suben_30d": suben, "bajan_30d": bajan}}


class EvaluarTest(unittest.TestCase):
    """Cada regla salta justo en su umbral y no justo por debajo."""

    def nombres(self, c):
        return [(r, d) for r, d, _ in reglas.evaluar(c)]

    def test_revisiones(self):
        self.assertEqual(self.nombres(revision(3.0)), [("revisiones", "sube")])
        self.assertEqual(self.nombres(revision(2.9)), [])
        self.assertEqual(self.nombres(revision(5.0, suben=2, bajan=2)), [])  # tantas a la baja como al alza

    def test_insiders(self):
        compra = lambda n, compras, ventas: {"insiders": {"compradores": n, "valor_compras": compras, "valor_ventas": ventas}}
        self.assertEqual(self.nombres(compra(2, 2e6, 1e6)), [("insiders", "sube")])
        self.assertEqual(self.nombres(compra(1, 2e6, 0)), [])
        self.assertEqual(self.nombres(compra(31, 530_000 / 2.2, 0)), [])  # muchas compras rutinarias y pequeñas
        self.assertEqual(self.nombres(compra(3, 1e6, 5e6)), [])  # venden más de lo que compran

    def test_funding(self):
        cripto = lambda hl, kr=None: {"cripto": {"funding_hl": hl, "funding_kraken": kr}}
        self.assertEqual(self.nombres(cripto(40.0)), [("funding", "baja")])
        self.assertEqual(self.nombres(cripto(39.9)), [])
        self.assertEqual(self.nombres(cripto(-20.0)), [("funding", "sube")])
        self.assertEqual(self.nombres(cripto(None, 55.0)), [("funding", "baja")])  # sin Hyperliquid, usa Kraken

    def test_volumen(self):
        vol = lambda rel, mov: {"volumen": {"relativo": rel, "movimiento": mov, "dia": "2026-11-09"}}
        self.assertEqual(self.nombres(vol(3.0, -4.0)), [("volumen", "baja")])
        self.assertEqual(self.nombres(vol(2.9, 8.0)), [])
        self.assertEqual(self.nombres(vol(5.0, 3.9)), [])
        [(_, _, detalle)] = reglas.evaluar(vol(3.25, 4.5))
        self.assertIn("3,2 veces", detalle)
        self.assertIn("+4,5 %", detalle)


class ProbTest(unittest.TestCase):
    def test_sin_historial_es_la_ventaja_minima(self):
        self.assertEqual(reglas.prob("funding", "sube", []), 55)
        self.assertEqual(reglas.prob("funding", "baja", []), 45)
        poco = [{"tipo": "reglas:funding", "efectivas": 10, "acierto": 80.0}]
        self.assertEqual(reglas.prob("funding", "sube", poco), 55)  # 10 no bastan

    def test_con_historial_es_lo_medido_aunque_sea_malo(self):
        bueno = [{"tipo": "reglas:funding", "efectivas": 40, "acierto": 62.4}]
        malo = [{"tipo": "reglas:funding", "efectivas": 40, "acierto": 41.0}]
        self.assertEqual(reglas.prob("funding", "baja", bueno), 38)
        self.assertEqual(reglas.prob("funding", "sube", malo), 41)


class GenerarTest(unittest.TestCase):
    def setUp(self):
        base.limpiar()
        parches = [mock.patch.object(cuant, "de_activo", return_value=revision(4.0)),
                   mock.patch.object(mercado, "cotizacion", return_value={"precio": 100.0})]
        for p in parches:
            p.start()
        self.addCleanup(mock.patch.stopall)
        self.ahora = time.time()

    def test_no_repite_mientras_esta_pendiente(self):
        [s] = reglas.generar(["NVDA"], self.ahora, tipos=[])
        self.assertEqual((s["regla"], s["direccion"], s["prob_subida"], s["horizonte"]), ("revisiones", "sube", 55, "semanas"))
        self.assertEqual(reglas.generar(["NVDA"], self.ahora + 86400, tipos=[]), [])
        self.assertEqual(len(reglas.generar(["NVDA"], self.ahora + 31 * 86400, tipos=[])), 1)  # ya se juzgó

    def test_el_marcador_las_juzga_con_su_direccion(self):
        datos.guardar_senal_regla({"regla": "funding", "simbolo": "ETH-USD", "direccion": "sube", "prob_subida": 41,
                                   "horizonte": "días", "detalle": "x", "precio": 100.0, "creado": int(self.ahora)})
        with mock.patch.object(mercado, "horas", return_value=(0, [])), \
                mock.patch.object(mercado, "cotizaciones", return_value=[]):
            r = marcador.calcular("reglas")
        [s] = r["senales"]
        self.assertEqual((s["origen"], s["direccion"], s["buy_pct"], s["coste"]), ("reglas", "sube", 41, 0.52))
        self.assertEqual(r["por_tipo"][0]["tipo"], "reglas:funding")


def juzgada(tipo, i, gana, estado="resuelta", creado=None, simbolo=None, buy=65, confianza=60):
    origen, subtipo = tipo.split(":")
    return {"origen": origen, "subtipo": subtipo, "simbolo": simbolo or f"S{i}", "item_id": f"{tipo}{i}",
            "creado": creado if creado is not None else i * 86400, "direccion": marcador.direccion_de(buy),
            "estado": estado, "acierto": gana if estado == "resuelta" else None, "relativo": 1.0 if gana else -1.0,
            "neto": 1.0 if gana else -1.0, "buy_pct": buy, "confianza": confianza}


class CalibracionTest(unittest.TestCase):
    def test_peso_contraido_hacia_cero(self):
        historial = ([juzgada("cartera:macro", i, i < 30) for i in range(40)]      # 75 % frente al índice
                     + [juzgada("ideas:sector", i, i < 10) for i in range(40)]      # 25 %
                     + [juzgada("reglas:funding", 0, True, estado="pendiente")])    # sin resolver
        tipos = {t["tipo"]: t for t in calibracion.por_tipo(historial)}
        self.assertAlmostEqual(tipos["cartera:macro"]["peso"], 40 / 70 * 0.5)
        self.assertAlmostEqual(tipos["ideas:sector"]["peso"], -40 / 70 * 0.5)
        self.assertEqual(tipos["reglas:funding"]["peso"], 0.0)
        self.assertEqual(tipos["reglas:funding"]["pendientes"], 1)

    def test_top_excluye_lo_malo_lo_viejo_y_repite_activo_una_vez(self):
        ahora = 100 * 86400
        tipos = [{"tipo": "cartera:macro", "peso": 0.3, "efectivas": 40, "frente_indice": 70, "intervalo": [55, 82]},
                 {"tipo": "ideas:sector", "peso": -0.2, "efectivas": 40, "frente_indice": 35, "intervalo": [22, 50]}]
        pendientes = [
            juzgada("cartera:macro", 1, None, "pendiente", ahora - 3600, "NVDA", buy=65, confianza=60),  # 9 × 1,3
            juzgada("cartera:macro", 2, None, "pendiente", ahora - 7200, "NVDA", buy=60, confianza=50),  # mismo activo
            juzgada("ideas:sector", 3, None, "pendiente", ahora - 3600, "AMD", buy=80, confianza=90),    # tipo que pierde
            juzgada("reglas:volumen", 4, None, "pendiente", ahora - 3600, "XLE", buy=45, confianza=50),  # sin historial
            juzgada("cartera:macro", 5, None, "pendiente", ahora - 72 * 3600, "TSLA", buy=90),           # de hace 3 días
            juzgada("cartera:macro", 6, None, "pendiente", ahora - 3600, "AAPL", buy=50),                # sin dirección
        ]
        top = calibracion.top(pendientes, tipos, ahora)
        self.assertEqual([s["simbolo"] for s in top], ["NVDA", "XLE"])
        self.assertAlmostEqual(top[0]["puntos"], 0.6 * 15 * 1.3)
        self.assertEqual(top[1]["historial"]["efectivas"], 0)  # se muestra como «sin historial»


if __name__ == "__main__":
    unittest.main()
