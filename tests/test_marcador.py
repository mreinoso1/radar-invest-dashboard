"""El marcador juzga todas las señales igual: dirección, índice del mismo periodo y comisiones."""
import time
import unittest
from unittest import mock

from tests import base

import datos  # noqa: E402
import marcador  # noqa: E402
import mercado  # noqa: E402

T0 = 1_790_000_000 // 3600 * 3600  # una hora en punto


def velas(precio_antes, precio_despues, desde_hora=24, horas=72):
    """Velas horarias seguidas, como las de una cripto: un precio hasta `desde_hora` y otro después."""
    return 0, [(T0 + h * 3600, precio_antes if h < desde_hora else precio_despues) for h in range(horas)]


def senal(direccion, buy_pct=65, coste=0.1, simbolo="NVDA"):
    return {"item_id": "n1", "simbolo": simbolo, "creado": T0 + 1800, "horizonte": "horas", "direccion": direccion,
            "precio": 100.0, "coste": coste, "buy_pct": buy_pct}


class JuzgarTest(unittest.TestCase):
    def test_acierto_frente_al_indice_y_neto(self):
        # El activo sube un 2 % y el índice un 1 %: acertó, le ganó al mercado por 1 punto y paga 0,1 de comisión.
        r = marcador._juzgar(senal("sube"), velas(100, 102), T0 + 72 * 3600, None, velas(400, 404))
        self.assertEqual(r["estado"], "resuelta")
        self.assertTrue(r["acierto"])
        self.assertAlmostEqual(r["movimiento"], 2.0)
        self.assertAlmostEqual(r["mov_indice"], 1.0)
        self.assertAlmostEqual(r["a_favor"], 2.0)
        self.assertAlmostEqual(r["neto"], 1.9)
        self.assertAlmostEqual(r["relativo"], 1.0)

    def test_corto_que_cae_menos_que_el_indice_pierde_frente_a_el(self):
        # Dijo "baja", el activo cae un 2 % pero el índice cae un 3 %: acierta la dirección, no le gana al mercado.
        r = marcador._juzgar(senal("baja", 35), velas(100, 98), T0 + 72 * 3600, None, velas(400, 388))
        self.assertTrue(r["acierto"])
        self.assertAlmostEqual(r["a_favor"], 2.0)
        self.assertAlmostEqual(r["relativo"], -1.0)

    def test_fallo_resta_la_comision(self):
        r = marcador._juzgar(senal("baja", 35), velas(100, 102), T0 + 72 * 3600, None, None)
        self.assertFalse(r["acierto"])
        self.assertAlmostEqual(r["neto"], -2.1)
        self.assertIsNone(r["relativo"])  # sin índice no se inventa la comparación

    def test_neutro_no_cuenta_como_acierto_ni_fallo(self):
        r = marcador._juzgar(senal("neutro", 50), velas(100, 102), T0 + 72 * 3600, None, velas(400, 404))
        self.assertIsNone(r["acierto"])
        self.assertIsNone(r["neto"])

    def test_pendiente_hasta_que_acaba_el_plazo(self):
        r = marcador._juzgar(senal("sube"), velas(100, 102), T0 + 5 * 3600, 101.0)
        self.assertEqual(r["estado"], "pendiente")
        self.assertAlmostEqual(r["movimiento"], 1.0)


class IndiceYCosteTest(unittest.TestCase):
    def test_indice_de_cada_tipo(self):
        self.assertEqual(marcador.indice_de("NVDA"), "SPY")
        self.assertEqual(marcador.indice_de("HYPE32196-USD"), "BTC-USD")
        self.assertIsNone(marcador.indice_de("BTC-USD"))
        self.assertIsNone(marcador.indice_de("SPY"))

    def test_coste_segun_tipo(self):
        cfg = {"comision_acciones": 0.1, "comision_cripto": 0.52}
        self.assertEqual(marcador.coste_de("AAPL", cfg), 0.1)
        self.assertEqual(marcador.coste_de("ETH-USD", cfg), 0.52)

    def test_wilson_valor_conocido(self):
        bajo, alto = marcador._wilson(50, 100)
        self.assertAlmostEqual(bajo, 40.38, places=1)
        self.assertAlmostEqual(alto, 59.62, places=1)


def juzgadas(n=40, aciertos_por_lado=16, relativo=1.0, neto=1.0, mismo_item=False):
    """n señales resueltas en días distintos, la mitad "sube" y la mitad "baja"."""
    salida = []
    for i in range(n):
        sube = i < n // 2
        acierta = (i % (n // 2)) < aciertos_por_lado
        subio = sube == acierta
        salida.append({
            "estado": "resuelta", "item_id": "x" if mismo_item else f"n{i}", "simbolo": "NVDA",
            "creado": T0 + i * 86400, "horizonte": "días", "direccion": "sube" if sube else "baja",
            "buy_pct": 65 if sube else 35, "acierto": acierta, "subio": subio, "movimiento": 2.0 if subio else -2.0,
            "a_favor": 2.0 if acierta else -2.0, "neto": neto if acierta else -abs(neto) - 1,
            "relativo": relativo if acierta else -abs(relativo), "mov_indice": 0.5, "coste": 0.1,
        })
    return salida


class ResumirTest(unittest.TestCase):
    def test_buena_senal_supera_todo(self):
        r, *_ = marcador._resumir(juzgadas())
        self.assertAlmostEqual(r["acierto"], 80.0)
        self.assertAlmostEqual(r["siempre_sube"], 50.0)
        self.assertEqual(r["efectivas"], 40)
        self.assertGreater(r["intervalo"][0], 50)
        self.assertAlmostEqual(r["acierto_relativo"], 80.0)
        self.assertIn("le gana al índice", r["veredicto"])

    def test_no_cubre_comisiones(self):
        r, *_ = marcador._resumir(juzgadas(neto=-0.5))
        self.assertLess(r["neto_medio"], 0)
        self.assertIn("comisiones", r["veredicto"])

    def test_no_le_gana_al_indice(self):
        r, *_ = marcador._resumir(juzgadas(relativo=-1.0))
        self.assertIn("seguir al índice", r["veredicto"])

    def test_pocas_senales(self):
        r, *_ = marcador._resumir(juzgadas(n=10, aciertos_por_lado=5))
        self.assertIn("pocas", r["veredicto"])

    def test_noticias_distintas_es_la_cuenta_prudente(self):
        r, *_ = marcador._resumir(juzgadas(mismo_item=True))
        self.assertEqual(r["noticias"], 1)
        self.assertEqual(r["efectivas"], 40)


class CalcularTest(unittest.TestCase):
    """calcular() con la base temporal y precios falsos: la API conserva sus campos y separa por origen."""

    CAMPOS_ANTIGUOS = ["total", "resueltas", "pendientes", "sin_datos", "con_direccion", "aciertos", "acierto",
                       "efectivas", "intervalo", "siempre_sube", "brier", "habilidad", "a_favor", "minimo", "veredicto"]

    def setUp(self):
        base.limpiar()
        ahora = int(time.time())
        datos.guardar_items([base.item("c1", ahora), base.item("i1", ahora)])
        datos.guardar_analisis("c1", {
            "relevante": True, "importancia": 3, "categoria": "macro", "titulo": "t", "resumen": "r", "novedad": "n",
            "senal_buy": 60, "modelo": "m",
            "impactos": [{"simbolo": "AAPL", "buy_pct": 60, "short_pct": 40, "direccion": "sube", "confianza": 50,
                          "magnitud": "media", "horizonte": "días", "mecanismo": "x", "invalidacion": "y",
                          "precio": 100.0}],
        })
        datos.guardar_ideas("i1", [{"simbolo": "ETH-USD", "relacion": "macro", "prob_subida": 35, "confianza": 60,
                                    "horizonte": "días", "mecanismo": "x", "invalidacion": "y",
                                    "que_tendria_que_pasar": "z", "precio": 3000.0}], "m", "Titular")
        horas = mock.patch.object(mercado, "horas", return_value=(0, [(ahora - 7200, 100.0)]))
        cotiz = mock.patch.object(mercado, "cotizaciones",
                                  side_effect=lambda ss: [{"simbolo": s, "precio": 100.0} for s in ss])
        horas.start(), cotiz.start()
        self.addCleanup(mock.patch.stopall)

    def test_campos_antiguos_y_origen(self):
        r = marcador.calcular()
        for campo in ("resumen", "calibracion", "por_activo", "por_horizonte", "senales"):
            self.assertIn(campo, r)
        for campo in self.CAMPOS_ANTIGUOS:
            self.assertIn(campo, r["resumen"])
        self.assertEqual({s["simbolo"] for s in r["senales"]}, {"AAPL"})  # por defecto, lo de siempre

    def test_ideas_y_todas(self):
        ideas = marcador.calcular("ideas")["senales"]
        self.assertEqual([(s["simbolo"], s["direccion"], s["coste"]) for s in ideas], [("ETH-USD", "baja", 0.52)])
        self.assertEqual({s["origen"] for s in marcador.calcular("todas")["senales"]}, {"cartera", "ideas"})

    def test_origen_desconocido_es_cartera(self):
        self.assertEqual(marcador.calcular("otra cosa")["origen"], "cartera")


if __name__ == "__main__":
    unittest.main()
