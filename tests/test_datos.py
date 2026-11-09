"""Las tablas nuevas de ideas y menciones, sobre una base temporal."""
import time
import unittest

from tests import base

import datos  # noqa: E402

IDEA = {"simbolo": "AMD", "relacion": "competidor", "prob_subida": 62, "confianza": 55, "horizonte": "semanas",
        "mecanismo": "m", "invalidacion": "i", "que_tendria_que_pasar": "q", "precio": 150.0}


class IdeasTest(unittest.TestCase):
    def setUp(self):
        base.limpiar()
        self.ahora = int(time.time())

    def test_guardar_y_leer_con_su_noticia(self):
        datos.guardar_items([base.item("n1", self.ahora, titulo="Nvidia beats")])
        datos.guardar_ideas("n1", [IDEA], "claude-opus-5-5", "Nvidia supera previsiones")
        [idea] = datos.ideas()
        self.assertEqual(idea["simbolo"], "AMD")
        self.assertEqual(idea["titulo"], "Nvidia supera previsiones")  # el traducido, si lo hay
        self.assertEqual(idea["titulo_original"], "Nvidia beats")
        self.assertEqual(idea["url"], "https://ejemplo.com/n1")

    def test_pendientes_excluye_lo_revisado_y_lo_repetido(self):
        datos.guardar_items([base.item(f"n{i}", self.ahora - i) for i in range(4)])
        datos.guardar_ideas("n0", [], "listas")
        datos.marcar_repetidas({"n1": "n2"})
        ids = [it["id"] for it in datos.pendientes_ideas(10, self.ahora - 3600)]
        self.assertEqual(ids, ["n2", "n3"])

    def test_menciones_cuenta_por_activo(self):
        datos.guardar_items([base.item("l1", self.ahora), base.item("l2", self.ahora)])
        datos.guardar_menciones([("l1", "NVDA", self.ahora), ("l2", "NVDA", self.ahora), ("l1", "AMD", self.ahora),
                                 ("l1", "NVDA", self.ahora)])  # repetida: no cuenta dos veces
        m = datos.menciones(self.ahora - 60)
        self.assertEqual(len(m["NVDA"]), 2)
        self.assertEqual(len(m["AMD"]), 1)

    def test_limpieza_conserva_lo_que_tiene_ideas(self):
        # Se crean con fecha de hoy (guardar_items borraría al momento lo antiguo) y luego se envejecen.
        datos.guardar_items([base.item(i, self.ahora) for i in ("con_idea", "solo_lista", "nada")])
        datos.guardar_ideas("con_idea", [IDEA], "m")
        datos.guardar_ideas("solo_lista", [], "listas")
        with datos._lock, datos._con:
            datos._con.execute("UPDATE items SET fecha = ?", (self.ahora - 30 * 86400,))
        datos.guardar_items([])  # cada guardado borra lo antiguo
        quedan = {it["id"] for it in datos.items_por_id(["con_idea", "solo_lista", "nada"])}
        self.assertEqual(quedan, {"con_idea"})
        self.assertEqual(len(datos.ideas()), 1)

    def test_ajustes_nuevos_tienen_valor_por_defecto(self):
        cfg = datos.ajustes()
        self.assertEqual(cfg["max_ideas"], 5)
        self.assertEqual(cfg["comision_cripto"], 0.52)


if __name__ == "__main__":
    unittest.main()
