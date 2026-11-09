"""trend_v1 sin red: look-ahead, costes, estadística con resultados conocidos, capas y preregistro.

Las velas son inventadas: así cada resultado se puede comprobar a mano, y ningún test mira datos reales de
precios (mirarlos antes de tiempo sería empezar a ajustar la estrategia).
"""
import hashlib
import math
import random
import shutil
import statistics
import unittest
from types import SimpleNamespace
from unittest import mock

from tests import base

import datos  # noqa: E402
from estrategias import trend  # noqa: E402

DIA = trend.DIA
D0 = trend.dia_de("2018-01-01")  # lunes
FIN = "2019-12-29"               # domingo: dos años bastan para los tests
D1 = trend.dia_de(FIN)


def velas_de(cierres, inicio, aperturas=None):
    """Una vela por día desde el día `inicio`. La apertura es el cierre anterior, salvo las de `aperturas`."""
    salida, previo = [], cierres[0]
    for k, c in enumerate(cierres):
        o = (aperturas or {}).get(k, previo)
        salida.append({"time": (inicio + k) * DIA, "open": o, "high": max(o, c), "low": min(o, c), "close": c, "volume": 0})
        previo = c
    return salida


def btc_tranquilo(desde=D0 - 500, hasta=D1):
    """Sube un 0,1 % al día con un vaivén fijo del 0,2 %: régimen alcista y volatilidad constante (nunca extrema)."""
    return velas_de([100 * 1.001 ** k * (1 + 0.002 * (-1) ** k) for k in range(hasta - desde + 1)], desde)


def paseo(semilla, desde=D0 - 200, hasta=D1, paso=0.03):
    azar, p, cierres = random.Random(semilla), 100.0, []
    for _ in range(hasta - desde + 1):
        p *= 1 + azar.uniform(-paso, paso * 1.15)
        cierres.append(p)
    return velas_de(cierres, desde)


class SinMirarElFuturoTest(unittest.TestCase):
    def test_cambiar_el_futuro_no_cambia_el_pasado(self):
        corte = D0 + 300
        original = {"A": paseo(1), "B": paseo(2)}
        alterado = {m: [v if v["time"] // DIA < corte else {**v, "open": v["open"] * 3, "close": v["close"] * 3}
                        for v in vs] for m, vs in original.items()}
        btc = btc_tranquilo()
        r1 = trend.simular(original, ["A", "B"], btc, fin=FIN)
        r2 = trend.simular(alterado, ["A", "B"], btc, fin=FIN)
        antes = lambda r: [f for f in r["registro"] if f["dia"] < trend.fecha_de(corte)]
        self.assertTrue(any(f["operada"] for f in antes(r1)))  # hay decisiones que comparar
        self.assertEqual(antes(r1), antes(r2))
        self.assertEqual([x for x in r1["curva"] if x[0] < corte], [x for x in r2["curva"] if x[0] < corte])

    def test_desplazar_los_datos_un_dia_no_mejora_el_resultado(self):
        """Cada semana el nivel salta el lunes (de la apertura al cierre) a 80 o a 120, al azar. Quien decide el
        domingo no puede saber el salto; quien viera el lunes (_desfase=1, trampa a propósito) sí. Si el motor
        mirase el futuro, el honesto no saldría peor que el tramposo."""
        for semilla in (3, 4, 5):
            azar = random.Random(semilla)
            desde = D0 - 200
            cierres, nivel = [], 100.0
            for d in range(desde, D1 + 1):
                if (d + 3) % 7 == 0:  # lunes
                    nivel = 100 * (1 + 0.2 * azar.choice((-1, 1)))
                cierres.append(nivel * (1 + 0.001 * (-1) ** d))
            velas = {"X": velas_de(cierres, desde)}
            honesto = trend.sharpe(trend.simular(velas, ["X"], btc_tranquilo(), fin=FIN)["rendimientos"])
            tramposo = trend.sharpe(trend.simular(velas, ["X"], btc_tranquilo(), fin=FIN, _desfase=1)["rendimientos"])
            self.assertLess(honesto, tramposo, f"semilla {semilla}")

    def test_la_decision_del_domingo_se_ejecuta_el_lunes_a_la_apertura(self):
        r = trend.simular({"A": paseo(1)}, ["A"], btc_tranquilo(), fin=FIN)
        primera = next(f for f in r["registro"] if f["operada"])
        self.assertEqual((trend.dia_de(primera["dia"]) + 3) % 7, 0)  # lunes


class CostesTest(unittest.TestCase):
    def test_coste_en_cada_cambio_de_peso(self):
        c = trend.Cartera()
        c.marcar({"A": 10.0})
        cambios = c.operar({"A": 0.5}, {"A": 10.0}, 0.0036)
        self.assertAlmostEqual(cambios["A"][1], 0.0036 * 0.5)
        self.assertAlmostEqual(c.caja, 1 - 0.5 - 0.0018)
        total = c.valor()
        cambios = c.operar({"A": 0.2}, {"A": 10.0}, 0.0036)  # vender también paga
        self.assertAlmostEqual(cambios["A"][1] * total, 0.0036 * (0.5 - 0.2 * total))
        self.assertAlmostEqual(c.valor(), total - 0.0036 * (0.5 - 0.2 * total))

    def test_sin_apalancamiento_aunque_los_pesos_sumen_100(self):
        c = trend.Cartera()
        c.marcar({"A": 10.0, "B": 5.0})
        c.operar({"A": 0.5, "B": 0.5}, {"A": 10.0, "B": 5.0}, 0.0036)
        self.assertGreaterEqual(c.caja, 0.0)
        self.assertAlmostEqual(c.caja, 0.0, places=12)
        self.assertAlmostEqual(c.valor(), 1 - sum(c.costes.values()))

    def test_lo_que_no_cotiza_ese_dia_no_se_opera(self):
        c = trend.Cartera()
        c.marcar({"A": 10.0})
        self.assertEqual(c.operar({"A": 0.5}, {}, 0.0036), {})

    def test_en_el_backtest_cada_operacion_paga_lo_que_cambia_su_peso(self):
        r = trend.simular({"A": paseo(1), "B": paseo(2)}, ["A", "B"], btc_tranquilo(), fin=FIN)
        operadas = [f for f in r["registro"] if f["operada"]]
        self.assertTrue(operadas)
        for f in operadas:
            self.assertAlmostEqual(f["coste"], 0.0036 * abs(f["peso_final"] - f["peso_actual"]), places=5)
        anios = len(r["rendimientos"]) / 365  # el informe da el coste medio al año, en % del capital
        self.assertAlmostEqual(r["costes"], sum(f["coste"] for f in operadas) / anios * 100)
        sin_costes = trend.simular({"A": paseo(1), "B": paseo(2)}, ["A", "B"], btc_tranquilo(), fin=FIN, coste=0)
        self.assertGreater(sin_costes["curva"][-1][1], r["curva"][-1][1])


class EstadisticaTest(unittest.TestCase):
    def test_sharpe_conocido(self):
        self.assertAlmostEqual(trend.sharpe([0.01, -0.01] * 50), 0.0)
        # media 0,01 y desviación típica muestral 0,01·√(100/99)
        self.assertAlmostEqual(trend.sharpe([0.02, 0.0] * 50), math.sqrt(365) * math.sqrt(99 / 100))
        self.assertIsNone(trend.sharpe([0.01] * 10))  # sin variación no hay Sharpe

    def test_caida_maxima_y_anios(self):
        self.assertAlmostEqual(trend.caida_maxima([1.0, 1.2, 0.9, 1.3, 1.17]), 25.0)
        curva = [(trend.dia_de("2021-12-31"), 1.1), (trend.dia_de("2022-06-30"), 0.55), (trend.dia_de("2022-12-31"), 0.99)]
        anios = trend.por_anio(curva)
        self.assertAlmostEqual(anios["2021"], 10.0)
        self.assertAlmostEqual(anios["2022"], -10.0)

    def test_bloques_de_media_20(self):
        azar = random.Random(1)
        self.assertAlmostEqual(statistics.fmean(trend._longitud(azar, 20) for _ in range(40_000)), 20, delta=0.5)

    def test_bootstrap_con_resultado_conocido(self):
        azar = random.Random(2)
        con_ventaja = [0.004 + azar.gauss(0, 0.01) for _ in range(1500)]
        sin_ventaja = [x - statistics.fmean(con_ventaja) for x in con_ventaja]  # misma serie, media exactamente 0
        ic = trend.bootstrap_sharpe(con_ventaja, n=1000)
        self.assertGreater(ic[0], 0)
        self.assertLess(ic[0], trend.sharpe(con_ventaja))
        self.assertGreater(ic[1], trend.sharpe(con_ventaja))
        ic = trend.bootstrap_sharpe(sin_ventaja, n=1000)
        self.assertLess(ic[0], 0)
        self.assertGreater(ic[1], 0)

    def test_bootstrap_reproducible(self):
        r = [random.Random(3).gauss(0.001, 0.02) for _ in range(300)]
        self.assertEqual(trend.bootstrap_sharpe(r, n=500), trend.bootstrap_sharpe(r, n=500))


def serie_falsa(cierres, medias, vol=None):
    return SimpleNamespace(en=lambda d: d if 0 <= d < len(cierres) else None, cierre=cierres, media=medias,
                           vol_peso=vol or [0.5] * len(cierres))


class CapasTest(unittest.TestCase):
    def test_regimen(self):
        sube = trend.Serie(btc_tranquilo(), 100, (30, 365))
        self.assertEqual(trend.regimen(sube, D0), "alcista")
        cae = [100 * 0.999 ** k * (1 + 0.002 * (-1) ** k) for k in range(600)]
        self.assertEqual(trend.regimen(trend.Serie(velas_de(cae, D0 - 599), 100, (30, 365)), D0), "bajista")
        # Lleva meses bajando despacio y rebota justo por encima de la media: la media aún no sube.
        rebote = [100 * 0.9995 ** k * (1 + 0.01 * (-1) ** k) for k in range(595)]
        rebote += [100 * 0.9995 ** 594 * 1.01 ** k for k in range(1, 6)]  # cinco días de +1 %
        self.assertEqual(trend.regimen(trend.Serie(velas_de(rebote, D0 - 599), 100, (30, 365)), D0), "lateral")
        loco = [100 * 1.01 ** k * (1 + (0.1 if k > 570 else 0.002) * (-1) ** k) for k in range(600)]
        self.assertEqual(trend.regimen(trend.Serie(velas_de(loco, D0 - 599), 100, (30, 365)), D0), "extrema")
        corta = trend.Serie(velas_de([100.0] * 150, D0 - 149), 100, (30, 365))
        self.assertEqual(trend.regimen(corta, D0), "sin datos")

    def test_senal_pide_dos_cierres(self):
        s = serie_falsa([10, 12, 9, 12, 12], [11] * 5)
        self.assertTrue(trend.senal(s, 4, False))    # sábado y domingo por encima
        self.assertFalse(trend.senal(s, 3, False))   # sábado debajo, domingo encima: sigue como estaba
        self.assertTrue(trend.senal(s, 2, True))     # sábado encima, domingo debajo: sigue como estaba
        self.assertFalse(trend.senal(s, 0, False))   # sin el día anterior no cambia

    def test_tamano_por_volatilidad_con_tope_y_suma(self):
        series = {"A": serie_falsa([1], [1], [0.5]), "B": serie_falsa([1], [1], [2.5]), "C": serie_falsa([1], [1], [1])}
        pesos = trend.pesos_objetivo({"A": True, "B": True, "C": False}, series, 0)
        self.assertEqual(pesos, {"A": 0.2, "B": 0.1, "C": 0.0})  # min(20 %, 25 % / vol)
        muchas = {m: serie_falsa([1], [1], [0.5]) for m in "ABCDEF"}
        pesos = trend.pesos_objetivo(dict.fromkeys("ABCDEF", True), muchas, 0)
        self.assertAlmostEqual(sum(pesos.values()), 1.0)  # 6 × 20 % = 120 %: se escala
        self.assertAlmostEqual(pesos["A"], 1 / 6)

    def test_filtro_del_25_por_ciento(self):
        a = {"A": 0.10}
        self.assertEqual(trend.ajustar({"A": 0.12}, a, "alcista"), {"A": 0.10})  # +20 %: no se toca
        self.assertEqual(trend.ajustar({"A": 0.13}, a, "alcista"), {"A": 0.13})  # +30 %: sí
        self.assertEqual(trend.ajustar({"A": 0.08}, a, "alcista"), {"A": 0.10})
        self.assertEqual(trend.ajustar({"A": 0.0}, a, "alcista"), {"A": 0.0})    # cerrar siempre
        self.assertEqual(trend.ajustar({"A": 0.01}, {}, "lateral"), {"A": 0.01})  # abrir siempre

    def test_regimen_malo_no_deja_comprar_mas(self):
        for reg in ("bajista", "extrema", "sin datos"):
            self.assertEqual(trend.ajustar({"A": 0.2, "B": 0.2, "C": 0.0, "D": 0.02}, {"B": 0.1, "C": 0.1, "D": 0.1}, reg),
                             {"A": 0.0, "B": 0.1, "C": 0.0, "D": 0.02})  # ni abrir ni subir; cerrar y bajar sí


class ReferenciasTest(unittest.TestCase):
    def test_comprar_y_mantener_paga_la_entrada(self):
        btc = velas_de([100.0] * 10 + [110.0] * 10, D0 - 10)
        rend, curva = trend.comprar_y_mantener(btc, inicio="2018-01-01", fin=trend.fecha_de(D0 + 9))
        # Invierte x con x + 0,36 % de x = 1 (el coste sale del mismo capital): x = 1 / 1,0036.
        self.assertAlmostEqual(curva[-1][1], 1.1 / 1.0036, places=9)

    def test_pesos_iguales_entre_las_que_cotizan(self):
        velas = {"A": velas_de([100.0] * 40, D0 - 1), "B": velas_de([50.0] * 20, D0 + 20)}
        _, curva = trend.pesos_iguales(velas, ["A", "B"], coste=0, inicio="2018-01-01", fin=trend.fecha_de(D0 + 38))
        self.assertAlmostEqual(curva[-1][1], 1.0)


class VeredictoTest(unittest.TestCase):
    def principal(self, sharpe, ic, caida, positivos):
        m = {"sharpe": sharpe, "intervalo": ic, "caida_maxima": caida, "positivos": positivos}
        return {"medidas": m, "puntos": trend.puntos(m)}

    def test_veredictos(self):
        bueno = self.principal(1.1, [0.3, 1.9], 30.0, 3)
        self.assertEqual(trend.veredicto(None, None)["veredicto"], "sin ejecutar")
        self.assertEqual(trend.veredicto(bueno, None)["veredicto"], "pendiente")
        self.assertEqual(trend.veredicto(bueno, self.principal(0.9, [0.1, 1.7], 33.0, 4))["veredicto"], "pasa")
        self.assertEqual(trend.veredicto(bueno, self.principal(0.9, [-0.1, 1.7], 33.0, 4))["veredicto"], "no demostrado")
        self.assertEqual(trend.veredicto(self.principal(0.2, [-0.5, 0.7], 30.0, 3), bueno)["veredicto"], "no pasa")
        self.assertEqual(trend.veredicto(self.principal(1.0, [0.2, 1.8], 40.0, 3), bueno)["veredicto"], "no demostrado")
        self.assertEqual(trend.veredicto(self.principal(1.0, [0.2, 1.8], 30.0, 2), bueno)["veredicto"], "no demostrado")

    def test_sharpe_justo_en_08_pasa_ese_punto(self):
        self.assertTrue(trend.puntos({"sharpe": 0.8, "intervalo": [0.01, 1.5], "caida_maxima": 35.0, "positivos": 3})[0]["ok"])


class PreregistroTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("git"), "hace falta git")
    def test_el_preregistro_real_coincide_con_el_tag(self):
        self.assertEqual(trend.verificar_preregistro(), hashlib.sha256(trend.PREREG.read_bytes()).hexdigest())

    def test_se_niega_si_el_json_cambio(self):
        with mock.patch.object(trend, "_en_git", return_value=b'{"otro": 1}'):
            with self.assertRaises(trend.ErrorPreregistro):
                trend.verificar_preregistro()

    def test_se_niega_sin_tag(self):
        fallo = SimpleNamespace(returncode=128, stdout=b"", stderr=b"fatal")
        with mock.patch.object(trend.subprocess, "run", return_value=fallo):
            with self.assertRaises(trend.ErrorPreregistro):
                trend.verificar_preregistro()

    def test_el_backtest_no_corre_ni_descarga_si_el_preregistro_cambio(self):
        base.limpiar()
        with mock.patch.object(trend, "_en_git", return_value=b"cambiado"), \
                mock.patch.object(trend.mercado, "diarias", side_effect=AssertionError("no debía descargar")):
            with self.assertRaises(trend.ErrorPreregistro):
                trend.correr()
        self.assertIsNone(datos.simulacion(trend.CLAVE))

    def test_el_codigo_usa_lo_preregistrado(self):
        pre = trend.preregistro()
        self.assertEqual((pre["datos"]["inicio"], pre["datos"]["fin"]), (trend.INICIO, trend.FIN))
        u = pre["universo"]
        self.assertEqual(sorted(u["principales"] + u["reservadas"]), sorted(u["monedas"]))
        nunca = sorted(set(u["monedas"]) - {"BTC", "ETH", "SOL", "XRP"})
        self.assertEqual(sorted(random.Random("trend_v1").sample(nunca, 4)), sorted(u["reservadas"]))  # el sorteo se repite


class EjecucionTest(unittest.TestCase):
    def setUp(self):
        base.limpiar()
        datos.actualizar_prueba("trend_v1", "pendiente")
        self.parches = [mock.patch.object(trend, "verificar_preregistro", return_value="h"),
                        mock.patch.object(trend, "cargar_velas", side_effect=lambda ms, t, a: {m: [] for m in ms})]
        for p in self.parches:
            p.start()
        self.addCleanup(mock.patch.stopall)

    def resultado(self, ok):
        m = {"sharpe": 1.0 if ok else 0.1, "intervalo": [0.2, 1.8] if ok else [-0.6, 0.7], "caida_maxima": 20.0,
             "positivos": 3, "anios": {}}
        return lambda velas, monedas, btc, avance: {"medidas": m, "puntos": trend.puntos(m), "registro": [
            {"dia": "2026-11-02", "moneda": monedas[0], "regimen": "alcista", "senal": "larga", "peso_actual": 0.0,
             "peso_objetivo": 0.1, "peso_final": 0.1, "operada": True, "coste": 0.00036}]}

    def test_reservadas_una_sola_vez_y_despues_de_las_principales(self):
        with self.assertRaises(trend.ErrorEstrategia):
            trend.correr(reserva=True)  # aún no hay principales
        with mock.patch.object(trend, "informe", self.resultado(False)):
            trend.correr()
        self.assertEqual(datos.pruebas()[2]["veredicto"], "pendiente")
        with mock.patch.object(trend, "informe_reserva", self.resultado(True)):
            trend.correr(reserva=True)
            with self.assertRaises(trend.ErrorEstrategia):
                trend.correr(reserva=True)  # el preregistro solo permite una
        self.assertEqual(datos.pruebas()[2]["veredicto"], "no pasa")
        self.assertEqual(len(datos.pruebas()), 3)  # el contador recuerda los intentos anteriores
        self.assertEqual([d["moneda"] for d in datos.decisiones("reserva")], ["DOT"])

    def test_repetir_deja_rastro(self):
        with mock.patch.object(trend, "informe", self.resultado(True)):
            trend.correr()
            trend.correr()
        self.assertEqual(len(datos.simulacion(trend.CLAVE)["historial"]), 2)
        self.assertEqual(len(datos.decisiones("backtest")), 1)  # las decisiones se sustituyen, no se duplican


if __name__ == "__main__":
    unittest.main()
