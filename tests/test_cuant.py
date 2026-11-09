"""Datos cuantitativos y EDGAR con respuestas guardadas o inventadas: sin red."""
import json
import os
import time
import unittest
from datetime import datetime, timezone
from unittest import mock

from tests import base

import cuant  # noqa: E402
import datos  # noqa: E402
import edgar  # noqa: E402
import mercado  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
YAHOO = {
    "earningsTrend": {"trend": [
        {"period": "0q", "epsTrend": {"current": {"raw": 1.0}}},
        {"period": "0y", "epsTrend": {"current": {"raw": 9.31}, "30daysAgo": {"raw": 9.0}, "90daysAgo": {"raw": 8.95}},
         "epsRevisions": {"upLast30days": {"raw": 4}, "downLast30days": {}}},
    ]},
    "defaultKeyStatistics": {"shortPercentOfFloat": {"raw": 0.013}, "sharesShort": {"raw": 110.0},
                             "sharesShortPriorMonth": {"raw": 100.0}, "shortRatio": {"raw": 2.8},
                             "dateShortInterest": {"raw": 1792022400}},
}


class AccionesTest(unittest.TestCase):
    def test_revisiones(self):
        r = cuant.revisiones(YAHOO)
        self.assertAlmostEqual(r["cambio_30d"], 3.444, places=2)
        self.assertAlmostEqual(r["cambio_90d"], 4.022, places=2)
        self.assertEqual((r["suben_30d"], r["bajan_30d"]), (4, 0))  # un bloque vacío de Yahoo es 0

    def test_cortos(self):
        k = cuant.cortos(YAHOO)
        self.assertAlmostEqual(k["pct_flotante"], 1.3)
        self.assertAlmostEqual(k["cambio_mes"], 10.0)
        self.assertEqual(k["fecha"], "2026-10-15")

    def test_sin_datos_es_none(self):
        self.assertIsNone(cuant.revisiones({}))
        self.assertIsNone(cuant.cortos({"defaultKeyStatistics": {}}))

    def test_volumen_relativo_usa_la_ultima_sesion_completa(self):
        dia = 86400
        velas = [{"time": i * dia, "close": 100.0, "volume": 1000} for i in range(30)]
        velas[28] = {"time": 28 * dia, "close": 105.0, "volume": 3000}   # ayer: triple de volumen y +5 %
        velas[29] = {"time": 29 * dia, "close": 106.0, "volume": 10}     # hoy, a medias: no cuenta
        v = cuant.volumen_relativo(velas, 29 * dia + 3600)
        self.assertAlmostEqual(v["relativo"], 3.0)
        self.assertAlmostEqual(v["movimiento"], 5.0)


class CriptoTest(unittest.TestCase):
    """Cada plataforma da el funding en unidades distintas: mezclarlas sin convertir daría números absurdos."""

    def test_hyperliquid_tanto_por_uno_por_hora(self):
        respuesta = [{"universe": [{"name": "BTC"}, {"name": "HYPE"}]},
                     [{"funding": "0.0000125", "openInterest": "100", "markPx": "50000", "premium": "-0.001"},
                      {"funding": "0.0000111721", "openInterest": "1000", "markPx": "73.2", "premium": "0"}]]
        f = cuant.funding_hyperliquid(respuesta, "BTC")
        self.assertAlmostEqual(f["funding_anual"], 10.95, places=2)   # 0,00125 % por hora son 10,95 % al año
        self.assertEqual(f["oi_usd"], 5_000_000)                      # 100 BTC a 50.000
        self.assertAlmostEqual(f["prima"], -0.1)
        self.assertIsNone(cuant.funding_hyperliquid(respuesta, "DOGE"))

    def test_kraken_dolares_por_contrato(self):
        tickers = [{"symbol": "PF_XBTUSD", "fundingRate": 0.5, "markPrice": 50000.0, "openInterest": 10.0}]
        f = cuant.funding_kraken(tickers, "BTC")                       # BTC se llama XBT en Kraken
        self.assertAlmostEqual(f["funding_anual"], 0.5 / 50000 * 8760 * 100)
        self.assertEqual(f["oi_usd"], 500_000)

    def test_cambio_del_interes_abierto_con_la_foto_de_ayer(self):
        base.limpiar()
        ahora = datetime(2026, 11, 10, 12).timestamp()
        datos.guardar_cuant("BTC-USD", "2026-11-09", {"cripto": {"oi_usd": 4_000_000}})
        with mock.patch.object(cuant, "_hyperliquid", return_value=[{"universe": [{"name": "BTC"}]},
                                                                   [{"funding": "0", "openInterest": "100", "markPx": "50000"}]]), \
                mock.patch.object(cuant, "_kraken", return_value=[]):
            c = cuant.cripto("BTC-USD", ahora)
        self.assertAlmostEqual(c["oi_24h"], 25.0)
        self.assertIsNone(c["oi_7d"])  # no hay foto de hace 7 días: no se inventa
        self.assertIsNone(c["funding_kraken"])


class MacroYTextoTest(unittest.TestCase):
    def test_fred_ultimo_y_hace_un_mes(self):
        obs = {"observations": [{"date": "2026-11-06", "value": "4.10"}, {"date": "2026-10-20", "value": "."},
                                {"date": "2026-10-06", "value": "4.35"}, {"date": "2026-10-01", "value": "4.40"}]}
        self.assertEqual(cuant.fred_ultimo(json.dumps(obs)), (4.10, 4.35))

    def test_texto_dice_lo_que_falta(self):
        lineas = cuant.texto_activo({"revisiones": cuant.revisiones(YAHOO), "insiders": None, "cortos": None,
                                     "volumen": None})
        self.assertIn("+3,4 % en 30 días", lineas[0])
        self.assertIn("s/d", lineas[1])
        m = cuant.texto_macro({"tipos": {"3 meses": {"valor": 4.0, "hace_mes": 4.2},
                                         "10 años": {"valor": 4.86, "hace_mes": None}}, "fred": {}})
        self.assertIn("3 meses 4,00 % (-0,20 pp en un mes)", m[0])
        self.assertIn("Curva 10 años menos 3 meses: +0,86 pp", m[1])


class EdgarTest(unittest.TestCase):
    def setUp(self):
        base.limpiar()
        mercado._cache.clear()
        with open(os.path.join(FIXTURES, "form4.xml"), encoding="utf-8") as f:
            self.xml = f.read().encode()

    def test_solo_compras_y_ventas_de_acciones(self):
        transacciones = edgar.leer_form4(self.xml)
        self.assertEqual([t["codigo"] for t in transacciones], ["P", "S", "A", "G"])  # sin la de derivados
        self.assertEqual(transacciones[0]["cargo"], "CFO")
        r = edgar.resumir(transacciones)
        self.assertEqual((r["compras"], r["ventas"], r["otros"], r["compradores"]), (1, 1, 2, 1))
        self.assertEqual(r["valor_compras"], 50_500)  # el premio y la donación no cuentan como dinero

    def test_form4_de_otra_empresa_no_cuenta(self):
        # Una empresa que es accionista de otra presenta Form 4 de esa otra: aparecen en su lista pero no son suyos.
        ajeno = self.xml.replace(b"<issuerCik>0000000001</issuerCik>", b"<issuerCik>0000000999</issuerCik>")
        self.assertEqual(edgar.leer_form4(ajeno)[0]["emisor"], 999)
        datos.guardar_form4("propio", "EJEM", "2026-11-01", edgar.leer_form4(self.xml))
        datos.guardar_form4("ajeno", "EJEM", "2026-11-01", edgar.leer_form4(ajeno))
        with mock.patch.object(edgar, "_cik", return_value=1), \
                mock.patch.object(mercado, "_cacheado", return_value={"filings": {"recent": {
                    "form": [], "filingDate": [], "accessionNumber": [], "primaryDocument": []}}}):
            r = edgar.resumen("EJEM", dias=36500)
        self.assertEqual(r["compras"], 1)  # la del Form 4 propio; el ajeno no suma

    def test_sin_contacto_no_pide_nada(self):
        with mock.patch.object(edgar.urllib.request, "urlopen") as abrir:
            with self.assertRaises(edgar.ErrorEdgar):
                edgar._pedir("https://www.sec.gov/files/company_tickers.json")
        abrir.assert_not_called()

    def test_se_identifica_y_guarda_lo_leido(self):
        datos.guardar_ajustes({"sec_contacto": "Prueba prueba@example.com"})
        hoy = datetime.now().date().isoformat()
        respuestas = {
            "company_tickers.json": json.dumps({"0": {"cik_str": 1, "ticker": "EJEM"}}).encode(),
            "CIK0000000001.json": json.dumps({"filings": {"recent": {
                "form": ["4", "8-K", "4"], "filingDate": [hoy, hoy, "2020-01-01"],
                "accessionNumber": ["0001-26-000001", "0001-26-000002", "0001-20-000003"],
                "primaryDocument": ["xslF345X06/f4.xml", "x.htm", "xslF345X06/viejo.xml"]}}}).encode(),
            "f4.xml": self.xml,
        }
        pedidas = []

        def abrir(peticion, timeout):
            pedidas.append((peticion.full_url, peticion.get_header("User-agent")))
            return mock.MagicMock(__enter__=lambda s: mock.Mock(read=lambda: respuestas[peticion.full_url.split("/")[-1]]),
                                  __exit__=lambda *a: None)

        with mock.patch.object(edgar, "PAUSA", 0), mock.patch.object(edgar.urllib.request, "urlopen", side_effect=abrir):
            r = edgar.resumen("EJEM")
            self.assertEqual(r["compras"], 1)
            antes = len(pedidas)
            mercado._cache.clear()
            edgar.resumen("EJEM")
        self.assertTrue(all(ua == "Radar Prueba prueba@example.com" for _, ua in pedidas))
        self.assertTrue(pedidas[2][0].endswith("/1/000126000001/f4.xml"))  # el XML en bruto, sin la carpeta xsl
        self.assertEqual(len(pedidas) - antes, 2)  # la segunda vez no vuelve a pedir el Form 4: lo tenía guardado


if __name__ == "__main__":
    unittest.main()
