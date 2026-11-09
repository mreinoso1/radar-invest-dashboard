"""Canales de aviso sin enviar nada de verdad: se comprueba qué se enviaría."""
import json
import subprocess
import unittest
import urllib.error
from unittest import mock

from tests import base  # noqa: F401

import canales  # noqa: E402

TOKEN = "123456:SECRETO-DEL-BOT"
ALERTA = {"titulo": "NVDA baja de 180", "texto": "Cotiza a 179,5.", "urgente": True}
CFG = {"alertas_windows": True, "alertas_telegram": True, "alertas_ntfy": True, "alertas_minimas": False,
       "telegram_token": TOKEN, "telegram_chat": "42", "ntfy_servidor": "https://ntfy.sh", "ntfy_tema": "radar-abc"}


class WindowsTest(unittest.TestCase):
    def test_el_texto_no_entra_en_el_comando(self):
        titular = 'Ataque <script>"; Remove-Item C:\\ -Recurse; "</script> & más'
        with mock.patch.object(canales.sys, "platform", "win32"), \
                mock.patch.object(subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            canales.windows(titular, "texto")
        args, kwargs = run.call_args
        self.assertNotIn("Remove-Item", " ".join(args[0]))  # el comando es siempre el mismo
        xml = kwargs["env"]["RADAR_AVISO"]
        self.assertIn("&lt;script&gt;", xml)  # llega escapado como XML
        self.assertNotIn("<script>", xml)

    def test_fallo_de_powershell(self):
        with mock.patch.object(canales.sys, "platform", "win32"), \
                mock.patch.object(subprocess, "run", return_value=mock.Mock(returncode=1, stderr="sin permiso")):
            with self.assertRaises(canales.ErrorCanal):
                canales.windows("t", "x")


class RedTest(unittest.TestCase):
    def test_telegram_y_ntfy(self):
        url, cuerpo = canales.peticion_telegram(TOKEN, "42", "Título", "Texto")
        self.assertEqual(url, f"https://api.telegram.org/bot{TOKEN}/sendMessage")
        self.assertEqual((cuerpo["chat_id"], cuerpo["text"]), ("42", "Título\n\nTexto"))
        url, cuerpo = canales.peticion_ntfy("https://ntfy.sh/", "radar-abc", "Título con acentos", "x", True)
        self.assertEqual((url, cuerpo["topic"], cuerpo["priority"]), ("https://ntfy.sh", "radar-abc", 4))

    def test_el_token_no_aparece_en_los_errores(self):
        error = urllib.error.URLError(f"fallo al abrir https://api.telegram.org/bot{TOKEN}/sendMessage")
        with mock.patch.object(canales.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(canales.ErrorCanal) as e:
                canales.telegram(TOKEN, "42", "t", "x")
        self.assertNotIn(TOKEN, str(e.exception))
        self.assertIn("***", str(e.exception))

    def test_faltan_datos(self):
        with self.assertRaises(canales.ErrorCanal):
            canales.telegram("", "42", "t", "x")
        with self.assertRaises(canales.ErrorCanal):
            canales.ntfy("https://ntfy.sh", "", "t", "x")


class EnviarTest(unittest.TestCase):
    def setUp(self):
        self.enviado = {}
        patch_win = mock.patch.object(canales, "windows", side_effect=lambda t, x: self.enviado.update(windows=(t, x)))

        def post(url, cuerpo, secreto=""):
            if "telegram" in url:
                raise canales.ErrorCanal("respondió 401")
            self.enviado["ntfy"] = cuerpo

        patch_post = mock.patch.object(canales, "_post_json", side_effect=post)
        patch_win.start(), patch_post.start()
        self.addCleanup(mock.patch.stopall)

    def test_un_canal_que_falla_no_frena_los_demas(self):
        r = canales.enviar(ALERTA, CFG)
        self.assertEqual(r, {"windows": "ok", "telegram": "respondió 401", "ntfy": "ok"})

    def test_mensaje_minimo_fuera_del_ordenador(self):
        canales.enviar(ALERTA, {**CFG, "alertas_minimas": True})
        self.assertEqual(self.enviado["windows"][0], "NVDA baja de 180")  # en tu PC, el texto completo
        self.assertNotIn("NVDA", json.dumps(self.enviado["ntfy"]))      # fuera, nada de activos ni precios

    def test_solo_los_canales_activos(self):
        self.assertEqual(canales.activos({**CFG, "alertas_telegram": False}), ["windows", "ntfy"])


if __name__ == "__main__":
    unittest.main()
