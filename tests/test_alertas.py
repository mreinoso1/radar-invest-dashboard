"""Reglas de alerta y antispam con un reloj falso: cada test dice qué hora es."""
import unittest
from datetime import datetime
from unittest import mock

from tests import base

import alertas  # noqa: E402
import calendario  # noqa: E402
import canales  # noqa: E402
import datos  # noqa: E402
import mercado  # noqa: E402

AHORA = int(datetime(2026, 11, 10, 10, 0).timestamp())  # un martes a las 10:00, hora local
LINEA = {"id": "l1", "bajo": 100.0, "alto": 100.0, "texto": "Soporte"}
ZONA = {"id": "z1", "bajo": 90.0, "alto": 95.0, "texto": ""}


class ReglasTest(unittest.TestCase):
    def test_reglas_de_precio(self):
        reglas = [{"id": 1, "simbolo": "NVDA", "condicion": "baja_de", "nivel": 180, "nota": "comprar"},
                  {"id": 2, "simbolo": "NVDA", "condicion": "sube_de", "nivel": 250, "nota": ""},
                  {"id": 3, "simbolo": "AMD", "condicion": "sube_de", "nivel": 1, "nota": ""}]
        [a] = alertas.evaluar_reglas(reglas, {"NVDA": 179.5})  # AMD sin precio: no se evalúa
        self.assertEqual((a["clave"], a["regla_id"], a["urgente"]), ("regla:1", 1, True))
        self.assertEqual(a["texto"], "Cotiza a 179,5. Tu nota: comprar")
        self.assertEqual(alertas._p(1424.75), "1.424,75")
        self.assertIn("comprar", a["texto"])

    def test_que_niveles_se_vigilan(self):
        dibujos = [
            {"id": "a", "tipo": "horizontal", "puntos": [{"t": 1, "p": 100}], "analista": True, "texto": "Stop"},
            {"id": "b", "tipo": "horizontal", "puntos": [{"t": 1, "p": 120}]},
            {"id": "c", "tipo": "rect", "puntos": [{"t": 1, "p": 95}, {"t": 2, "p": 90}], "analista": True},
            {"id": "d", "tipo": "tendencia", "puntos": [{"t": 1, "p": 1}, {"t": 2, "p": 2}], "analista": True},
        ]
        self.assertEqual([n["id"] for n in alertas.niveles_de(dibujos, "analista")], ["a", "c"])
        self.assertEqual([n["id"] for n in alertas.niveles_de(dibujos, "todos")], ["a", "b", "c"])
        self.assertEqual(alertas.niveles_de(dibujos, "ninguno"), [])
        zona = alertas.niveles_de(dibujos, "analista")[1]
        self.assertEqual((zona["bajo"], zona["alto"]), (90, 95))

    def test_cruce_e_histeresis(self):
        a, armados = alertas.evaluar_niveles("NVDA", [LINEA], 100.2, 99.5, {}, AHORA)
        self.assertEqual(len(a), 1)
        self.assertIn("Soporte", a[0]["texto"])
        # Baila alrededor de la línea sin alejarse un 0,3 %: no repite.
        for previo, precio in ((100.2, 99.9), (99.9, 100.1), (100.1, 99.8)):
            a, armados = alertas.evaluar_niveles("NVDA", [LINEA], precio, previo, armados, AHORA)
            self.assertEqual(a, [])
        # Se aleja más de un 0,3 % (se rearma) y vuelve a cruzar: avisa de nuevo.
        _, armados = alertas.evaluar_niveles("NVDA", [LINEA], 99.5, 99.8, armados, AHORA)
        a, _ = alertas.evaluar_niveles("NVDA", [LINEA], 100.4, 99.5, armados, AHORA + 60)
        self.assertEqual(len(a), 1)

    def test_entrar_en_zona_y_sin_precio_previo(self):
        self.assertEqual(alertas.evaluar_niveles("X", [ZONA], 93, None, {}, AHORA)[0], [])
        self.assertEqual(len(alertas.evaluar_niveles("X", [ZONA], 93, 97, {}, AHORA)[0]), 1)
        self.assertEqual(alertas.evaluar_niveles("X", [ZONA], 94, 93, {}, AHORA)[0], [])  # ya estaba dentro

    def test_movimientos(self):
        cotiz = [{"simbolo": "NVDA", "precio": 106, "cierre_previo": 100, "var_dia": 6.0},
                 {"simbolo": "AMD", "precio": 112, "cierre_previo": 100, "var_dia": 12.0},
                 {"simbolo": "BTC-USD", "precio": 106, "cierre_previo": 100, "var_dia": 6.0},
                 {"simbolo": "AAPL", "precio": 101, "cierre_previo": 100, "var_dia": 1.0}]
        r = {a["simbolo"]: a for a in alertas.evaluar_movimientos(cotiz, 5, 8)}
        self.assertEqual(set(r), {"NVDA", "AMD"})  # BTC no llega al 8 % de las cripto
        self.assertFalse(r["NVDA"]["urgente"])     # al resumen
        self.assertTrue(r["AMD"]["urgente"])       # más del doble del umbral: inmediata
        self.assertEqual(r["NVDA"]["titulo"], "NVDA sube un 6,0 % hoy")  # coma decimal, como en español
        # El sábado, con el mismo cierre anterior, la clave es la misma y no se repetirá.
        self.assertEqual(r["NVDA"]["clave"], alertas.evaluar_movimientos(cotiz[:1], 5, 8)[0]["clave"])

    def test_noticias_solo_de_lo_tuyo(self):
        analisis = [{"item_id": "n1", "titulo": "OPEP recorta", "fuente": "CNBC", "importancia": 4,
                     "impactos": [{"simbolo": "XOM"}, {"simbolo": "CVX"}]},
                    {"item_id": "n2", "titulo": "Otra", "fuente": "CNBC", "importancia": 5,
                     "impactos": [{"simbolo": "TSLA"}]}]
        [a] = alertas.evaluar_noticias(analisis, {"XOM", "NVDA"})
        self.assertEqual((a["clave"], a["simbolo"]), ("noticia:n1", "XOM"))

    def test_calendario_24_horas_antes(self):
        eventos = [{"id": "a", "titulo": "IPC", "fecha": AHORA + 23 * 3600},
                   {"id": "b", "titulo": "Fed", "fecha": AHORA + 25 * 3600},
                   {"id": "c", "titulo": "Pasado", "fecha": AHORA - 60}]
        self.assertEqual([a["clave"] for a in alertas.evaluar_calendario(eventos, AHORA)], ["cal:a"])


def alerta(clave, simbolo="NVDA", tipo="nivel", urgente=True):
    return {"clave": clave, "simbolo": simbolo, "tipo": tipo, "urgente": urgente, "titulo": clave, "texto": ""}


class AntispamTest(unittest.TestCase):
    def test_no_repite_una_clave(self):
        historial = [{**alerta("x"), "creada": AHORA - 86400, "enviada": {"windows": "ok"}}]
        self.assertEqual(alertas.filtrar([alerta("x")], historial, AHORA, 6), ([], []))

    def test_un_aviso_por_activo_y_tipo_cada_hora(self):
        historial = [{**alerta("a"), "creada": AHORA - 600, "enviada": {"windows": "ok"}}]
        inmediatas, resumen = alertas.filtrar([alerta("b"), alerta("c", tipo="precio")], historial, AHORA, 6)
        self.assertEqual([a["clave"] for a in inmediatas], ["c"])  # las reglas tuyas no se frenan
        self.assertEqual([(a["clave"], a["urgente"]) for a in resumen], [("b", False)])

    def test_tope_por_hora_manda_el_resto_al_resumen(self):
        nuevas = [alerta(f"k{i}", simbolo=f"S{i}") for i in range(5)]
        inmediatas, resumen = alertas.filtrar(nuevas, [], AHORA, 3)
        self.assertEqual((len(inmediatas), len(resumen)), (3, 2))

    def test_hora_del_resumen(self):
        nueve = int(datetime(2026, 11, 10, 20, 59).timestamp())
        nueve_y_algo = int(datetime(2026, 11, 10, 21, 5).timestamp())
        self.assertFalse(alertas.toca_resumen(nueve, 21, None))
        self.assertTrue(alertas.toca_resumen(nueve_y_algo, 21, "2026-11-09"))
        self.assertFalse(alertas.toca_resumen(nueve_y_algo, 21, "2026-11-10"))


class RondaTest(unittest.TestCase):
    """El vigilante completo, con la base temporal, precios falsos y los canales sustituidos."""

    def setUp(self):
        base.limpiar()
        base.posicion("NVDA", 10)
        base.posicion("AMD", 0)
        datos.guardar_dibujos("NVDA", [{"id": "s1", "tipo": "horizontal", "puntos": [{"t": 1, "p": 100}],
                                        "analista": True, "texto": "Soporte"}])
        self.precios = {"NVDA": 101.0, "AMD": 150.0}
        self.enviadas = []
        parches = [
            mock.patch.object(mercado, "cotizaciones", side_effect=lambda ss: [
                {"simbolo": s, "precio": self.precios[s], "cierre_previo": self.precios[s], "var_dia": 0.0}
                for s in ss]),
            mock.patch.object(calendario, "proximos", return_value=([], [])),
            mock.patch.object(canales, "enviar", side_effect=lambda a, cfg, c=None: self.enviadas.append(a)
                              or {"windows": "ok"}),
            mock.patch.object(alertas, "top5", return_value=[]),
        ]
        for p in parches:
            p.start()
        self.addCleanup(mock.patch.stopall)

    def test_primera_ronda_no_avisa_y_la_segunda_ve_el_cruce(self):
        self.assertEqual(alertas.ronda(AHORA), [])  # aún no hay precio anterior con el que comparar
        self.precios["NVDA"] = 99.0
        enviadas = alertas.ronda(AHORA + 60)
        self.assertEqual([a["tipo"] for a in enviadas], ["nivel"])
        self.assertEqual(len(datos.alertas()), 1)
        self.assertEqual(datos.no_leidas(), 1)

    def test_regla_avisa_una_vez(self):
        datos.guardar_regla("AMD", "sube_de", 160)
        alertas.ronda(AHORA)
        self.precios["AMD"] = 161.0
        alertas.ronda(AHORA + 60)
        alertas.ronda(AHORA + 120)
        self.assertEqual([a["clave"] for a in self.enviadas], ["regla:1"])
        self.assertEqual(datos.reglas_alerta(True), [])

    def test_resumen_diario_agrupa_lo_que_espero(self):
        datos.guardar_alerta({"clave": "mov1:NVDA:100", "tipo": "movimiento", "simbolo": "NVDA",
                              "titulo": "NVDA sube un 6 %", "texto": "", "urgente": False}, None, AHORA)
        alertas.ronda(int(datetime(2026, 11, 10, 21, 1).timestamp()))
        [resumen] = self.enviadas
        self.assertEqual(resumen["tipo"], "resumen")
        self.assertIn("NVDA sube un 6 %", resumen["texto"])
        self.assertEqual(datos.alertas_sin_enviar(), [])

    def test_resumen_con_top5_aunque_no_haya_avisos(self):
        senal = {"simbolo": "NVDA", "direccion": "sube", "buy_pct": 65, "tipo": "cartera:macro",
                 "historial": {"efectivas": 0, "frente_indice": None, "intervalo": None}}
        with mock.patch.object(alertas, "top5", return_value=[senal]):
            alertas.ronda(int(datetime(2026, 11, 10, 21, 1).timestamp()))
        [resumen] = self.enviadas
        self.assertIn("Top 5 señales", resumen["texto"])
        self.assertIn("• NVDA ▲ 65 % · cartera:macro · sin historial", resumen["texto"])

    def test_trabajo_diario_una_vez_al_dia_tras_el_cierre(self):
        lanzados = []

        class HiloFalso:  # solo apunta que se lanzó: el trabajo de verdad iría a internet
            def __init__(self, target, args, daemon):
                self.args = args

            def start(self):
                lanzados.append(set(self.args[0]))

        with mock.patch.object(alertas.threading, "Thread", HiloFalso):
            alertas.ronda(int(datetime(2026, 11, 10, 21, 30).timestamp()))  # antes de las 22: nada
            alertas.ronda(int(datetime(2026, 11, 10, 22, 5).timestamp()))
            alertas.ronda(int(datetime(2026, 11, 10, 22, 6).timestamp()))   # ya hecho hoy
        self.assertEqual(lanzados, [{"NVDA", "AMD"}])

    def test_noticias_viejas_no_avisan_al_arrancar(self):
        datos.guardar_items([base.item("n1", AHORA)])
        datos.guardar_analisis("n1", {"relevante": True, "importancia": 5, "categoria": "macro", "titulo": "t",
                                      "resumen": "r", "novedad": "n", "senal_buy": 50, "modelo": "m",
                                      "impactos": [{"simbolo": "NVDA"}]})
        with datos._lock, datos._con:  # analizada hace dos horas, antes de abrir Radar
            datos._con.execute("UPDATE analisis SET creado = ?", (AHORA - 7200,))
        alertas.ronda(AHORA)
        self.assertEqual([a for a in self.enviadas if a["tipo"] == "noticia"], [])


if __name__ == "__main__":
    unittest.main()
