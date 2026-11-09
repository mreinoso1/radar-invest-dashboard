"""La API, con el servidor de verdad en un puerto libre: las rutas de siempre no cambian y las nuevas funcionan."""
import json
import os
import socket
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

from tests import base

with socket.socket() as s:  # un puerto libre, fijado antes de importar el servidor, que lo lee al cargarse
    s.bind(("127.0.0.1", 0))
    PUERTO = s.getsockname()[1]
os.environ["RADAR_PUERTO"] = str(PUERTO)

import cuenta  # noqa: E402
import datos  # noqa: E402
import mercado  # noqa: E402
import server  # noqa: E402


def pedir(ruta, cuerpo=None, cabeceras=None):
    """(código, JSON) de una petición a la API local."""
    datos_ = json.dumps(cuerpo).encode() if cuerpo is not None else None
    peticion = urllib.request.Request(f"http://127.0.0.1:{PUERTO}{ruta}", data=datos_, headers=cabeceras or {},
                                      method="POST" if cuerpo is not None else "GET")
    try:
        with urllib.request.urlopen(peticion, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.servidor = server.Servidor(("127.0.0.1", PUERTO), server.Manejador)
        threading.Thread(target=cls.servidor.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()

    def setUp(self):
        base.limpiar()
        base.posicion("BTC-USD", 0.5)
        base.posicion("NVDA", 0)
        parches = [
            mock.patch.object(cuenta, "estado", return_value={"conectado": False}),
            mock.patch.object(mercado, "cotizaciones", side_effect=lambda ss: [
                {"simbolo": s, "nombre": s, "precio": 100.0, "var_dia": 1.0, "var_5d": 2.0, "moneda": "USD"}
                for s in ss]),
            mock.patch.object(mercado, "cambio", return_value=1.0),
            mock.patch.object(mercado, "horas", return_value=(0, [])),
            mock.patch.object(mercado, "velas", side_effect=lambda s, i, corto=False: {
                "nombre": s, "tipo_yahoo": "EQUITY", "moneda": "USD"}),
            mock.patch.object(mercado, "cotizacion", side_effect=lambda s: {"simbolo": s, "precio": 100.0}),
            mock.patch.object(server.calendario, "_automaticos", return_value=([], [])),
        ]
        for p in parches:
            p.start()
        self.addCleanup(mock.patch.stopall)

    def test_cartera_conserva_su_forma(self):
        codigo, r = pedir("/api/cartera")
        self.assertEqual(codigo, 200)
        self.assertEqual(set(r), {"moneda", "filas", "valor", "coste", "ganancia", "dia", "avisos"})
        self.assertEqual({f["simbolo"] for f in r["filas"]}, {"BTC-USD", "NVDA"})  # la watchlist sigue ahí

    def test_ajustes_nuevos_acotados_y_sin_claves(self):
        codigo, r = pedir("/api/ajustes", {"max_ideas": 999, "comision_cripto": 0.4})
        self.assertEqual(codigo, 200)
        self.assertEqual(r["max_ideas"], 20)
        self.assertEqual(r["comision_cripto"], 0.4)
        self.assertNotIn("anthropic_key", r)
        self.assertNotIn("kraken_secret", r)
        codigo, r = pedir("/api/ajustes", {"max_ideas": "muchas"})
        self.assertEqual(codigo, 400)

    def test_aciertos_por_origen(self):
        for origen in ("cartera", "ideas", "todas"):
            codigo, r = pedir(f"/api/aciertos?origen={origen}")
            self.assertEqual((codigo, r["origen"]), (200, origen))
        codigo, r = pedir("/api/aciertos")
        self.assertEqual(r["origen"], "cartera")

    def test_ideas(self):
        codigo, r = pedir("/api/ideas")
        self.assertEqual(codigo, 200)
        self.assertEqual(set(r), {"ideas", "estado", "watchlist", "menciones"})
        self.assertEqual(r["watchlist"], ["NVDA"])

    def test_sin_cuenta_no_lanza_nada(self):
        codigo, r = pedir("/api/ideas/analizar", {})
        self.assertEqual(codigo, 200)
        self.assertIn("Conecta tu cuenta", r["error"])
        self.assertFalse(pedir("/api/ideas/estado")[1]["activo"])

    def test_cartera_solo_con_watchlist_remite_a_ideas(self):
        base.limpiar()
        base.posicion("NVDA", 0)
        with mock.patch.object(server.agente, "listo", return_value=True):
            codigo, r = pedir("/api/agente", {"tipo": "noticia"})
        self.assertIn("Ideas", r["error"])

    def test_watchlist_inicial(self):
        codigo, r = pedir("/api/watchlist/inicial", {})
        self.assertEqual(codigo, 200)
        self.assertEqual(r["anadidos"], len(server.oportunidades.WATCHLIST_INICIAL) - 2)

    def borrar(self, ruta):
        peticion = urllib.request.Request(f"http://127.0.0.1:{PUERTO}{ruta}", method="DELETE")
        with urllib.request.urlopen(peticion, timeout=10) as r:
            return r.status

    def test_secretos_de_alertas_no_vuelven(self):
        codigo, r = pedir("/api/ajustes", {"telegram_token": "123:SECRETO", "fred_key": "CLAVEFRED",
                                           "telegram_chat": "42", "alertas_telegram": True})
        self.assertEqual(codigo, 200)
        texto = json.dumps(r)
        self.assertNotIn("SECRETO", texto)
        self.assertNotIn("CLAVEFRED", texto)
        self.assertTrue(r["tiene_telegram"] and r["tiene_fred"])
        self.assertEqual(r["telegram_chat"], "42")

    def test_ntfy_crea_un_tema_aleatorio_y_valida(self):
        _, r = pedir("/api/ajustes", {"alertas_ntfy": True})
        self.assertRegex(r["ntfy_tema"], r"^radar-[A-Za-z0-9]{12,}$")
        self.assertEqual(pedir("/api/ajustes", {"ntfy_tema": "con espacios"})[0], 400)
        self.assertEqual(pedir("/api/ajustes", {"ntfy_servidor": "http://otro.example"})[0], 400)

    def test_reglas_de_precio(self):
        self.assertEqual(pedir("/api/alertas/reglas", {"simbolo": "TSLA", "condicion": "sube_de", "nivel": 1})[0], 400)
        codigo, r = pedir("/api/alertas/reglas", {"simbolo": "NVDA", "condicion": "sube_de", "nivel": 90})
        self.assertEqual(codigo, 400)  # cotiza a 100: saltaría al momento
        self.assertIn("ya cotiza", r["error"])
        codigo, r = pedir("/api/alertas/reglas", {"simbolo": "NVDA", "condicion": "baja_de", "nivel": 90})
        self.assertEqual(codigo, 200)
        self.assertEqual([g["nivel"] for g in pedir("/api/alertas")[1]["reglas"]], [90.0])
        self.assertEqual(self.borrar(f"/api/alertas/reglas?id={r['id']}"), 200)
        self.assertEqual(pedir("/api/alertas")[1]["reglas"], [])

    def test_eventos_manuales_en_el_calendario(self):
        fecha = int(time.time()) + 3 * 86400
        _, r = pedir("/api/eventos", {"simbolo": "hype32196-usd", "titulo": "Desbloqueo de HYPE", "fecha": fecha})
        _, cal = pedir("/api/calendario")
        self.assertEqual([(e["titulo"], e["simbolo"]) for e in cal["eventos"]], [("Desbloqueo de HYPE", "HYPE32196-USD")])
        self.borrar(f"/api/eventos?id={r['id']}")
        self.assertEqual(pedir("/api/calendario")[1]["eventos"], [])
        self.assertEqual(pedir("/api/eventos", {"titulo": "", "fecha": fecha})[0], 400)

    def test_leidas_y_prueba_de_canal(self):
        datos.guardar_alerta({"clave": "x", "tipo": "nivel", "simbolo": "NVDA", "titulo": "t", "texto": "",
                              "urgente": True}, {"windows": "ok"})
        self.assertEqual(pedir("/api/alertas/no_leidas")[1]["n"], 1)
        pedir("/api/alertas/leidas", {})
        self.assertEqual(pedir("/api/alertas/no_leidas")[1]["n"], 0)
        with mock.patch.object(server.canales, "windows") as windows:
            self.assertEqual(pedir("/api/alertas/probar", {"canal": "windows"})[1], {"windows": "ok"})
        windows.assert_called_once()

    def test_sigue_rechazando_otras_webs(self):
        codigo, _ = pedir("/api/cartera", cabeceras={"Origin": "https://malicioso.example"})
        self.assertEqual(codigo, 403)


if __name__ == "__main__":
    unittest.main()
