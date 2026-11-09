"""Calendario: la web de la Fed (copia guardada), FRED (respuesta de ejemplo), zonas horarias y fuentes que fallan."""
import json
import os
import sys
import time
import unittest
from datetime import datetime, timezone
from unittest import mock

from tests import base

import calendario  # noqa: E402
import datos  # noqa: E402
import mercado  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "fomc.html")
utc = lambda *a: int(datetime(*a, tzinfo=timezone.utc).timestamp())


class FedTest(unittest.TestCase):
    def test_lee_la_copia_guardada(self):
        with open(FIXTURE, encoding="utf-8") as f:
            reuniones = calendario.reuniones_fed(f.read())
        self.assertEqual(len(reuniones), 16)  # 8 en 2026 y 8 en 2027
        self.assertEqual(reuniones[0], {"fecha": utc(2026, 1, 28, 19), "proyecciones": False})  # 14:00 en invierno
        self.assertEqual(reuniones[1], {"fecha": utc(2026, 3, 18, 18), "proyecciones": True})   # 14:00 en verano

    def test_reunion_entre_dos_meses(self):
        html = ('2026 FOMC Meetings <div class="fomc-meeting__month x"><strong>April/May</strong></div>\n'
                '<div class="fomc-meeting__date y">30-1</div>')
        [r] = calendario.reuniones_fed(html)
        self.assertEqual(r["fecha"], utc(2026, 5, 1, 18))

    def test_si_cambia_el_formato_lo_dice(self):
        with self.assertRaises(calendario.ErrorCalendario):
            calendario.reuniones_fed("<html>La Fed estrena web</html>")


class HoraTest(unittest.TestCase):
    def test_horario_de_verano(self):
        self.assertEqual(calendario.hora_nueva_york(2026, 7, 29, 14), utc(2026, 7, 29, 18))
        self.assertEqual(calendario.hora_nueva_york(2026, 12, 9, 14), utc(2026, 12, 9, 19))

    def test_sin_base_de_zonas_horarias_sale_lo_mismo(self):
        fechas = [(2026, 3, 7, 8, 30), (2026, 3, 9, 8, 30), (2026, 10, 31, 14), (2026, 11, 2, 14), (2027, 6, 15, 14)]
        con = [calendario.hora_nueva_york(*f) for f in fechas]
        with mock.patch.dict(sys.modules, {"zoneinfo": None}):  # importar zoneinfo fallará
            sin = [calendario.hora_nueva_york(*f) for f in fechas]
        self.assertEqual(con, sin)


class FredTest(unittest.TestCase):
    def test_fechas_a_las_ocho_y_media(self):
        respuesta = json.dumps({"release_dates": [{"release_id": 10, "date": "2026-11-12"}]})
        [e] = calendario.fechas_fred(respuesta, 10)
        self.assertEqual((e["titulo"], e["fecha"]), ("IPC de EE. UU.", utc(2026, 11, 12, 13, 30)))

    def test_la_clave_no_aparece_en_los_errores(self):
        error = calendario.urllib.error.URLError("fallo con api_key=MICLAVE123")
        with mock.patch.object(calendario.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(calendario.ErrorCalendario) as e:
                calendario._pedir("https://x?api_key=MICLAVE123", secreto="MICLAVE123")
        self.assertNotIn("MICLAVE123", str(e.exception))


class ProximosTest(unittest.TestCase):
    def setUp(self):
        base.limpiar()
        mercado._cache.clear()
        self.ahora = time.time()

    def test_una_fuente_que_falla_no_tapa_las_demas(self):
        evento = {"id": "res:NVDA:1", "tipo": "resultados", "simbolo": "NVDA", "titulo": "Resultados de NVDA",
                  "fecha": self.ahora + 86400}
        with mock.patch.object(calendario, "_resultados", return_value=[evento]), \
                mock.patch.object(calendario, "_fed", side_effect=calendario.ErrorCalendario("sin red")):
            eventos, errores = calendario._automaticos(["NVDA"], "")
        self.assertEqual(eventos, [evento])
        self.assertEqual(errores, ["No se pudo leer la Fed: sin red"])

    def test_ventana_y_eventos_manuales(self):
        datos.guardar_evento("HYPE32196-USD", "Desbloqueo de HYPE", int(self.ahora + 3 * 86400))
        lejos = {"id": "fed:x", "tipo": "fed", "simbolo": None, "titulo": "Fed", "fecha": self.ahora + 30 * 86400}
        with mock.patch.object(calendario, "_automaticos", return_value=([lejos], [])):
            eventos, _ = calendario.proximos(["NVDA"], self.ahora, dias=14)
        self.assertEqual([e["titulo"] for e in eventos], ["Desbloqueo de HYPE"])


if __name__ == "__main__":
    unittest.main()
