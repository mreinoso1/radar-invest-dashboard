"""La API, con el servidor de verdad en un puerto libre: las rutas de siempre no cambian y las nuevas funcionan."""
import json
import os
import socket
import threading
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

    def test_sigue_rechazando_otras_webs(self):
        codigo, _ = pedir("/api/cartera", cabeceras={"Origin": "https://malicioso.example"})
        self.assertEqual(codigo, 403)


if __name__ == "__main__":
    unittest.main()
