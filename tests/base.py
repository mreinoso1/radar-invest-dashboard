"""Común a todos los tests. Se importa antes que cualquier módulo de Radar.

datos.py abre la base de datos al importarse, en la carpeta de RADAR_DATOS: por eso esa variable se fija
aquí, a una carpeta temporal, antes de nada. Así los tests nunca tocan los datos reales.
"""
import atexit
import os
import shutil
import sys
import tempfile

CARPETA = tempfile.mkdtemp(prefix="radar_tests_")
os.environ["RADAR_DATOS"] = CARPETA
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
atexit.register(shutil.rmtree, CARPETA, ignore_errors=True)

import datos  # noqa: E402

TABLAS = ("menciones", "ideas", "ideas_items", "analisis", "chat", "resumenes", "dibujos", "items", "posiciones")


def limpiar():
    """Deja la base temporal vacía: cada test empieza de cero."""
    with datos._lock, datos._con:
        for tabla in TABLAS:
            datos._con.execute(f"DELETE FROM {tabla}")
    if os.path.exists(datos.RUTA_AJUSTES):
        os.remove(datos.RUTA_AJUSTES)


def item(id_, fecha, titulo="Titular", fuente="CNBC", texto="", tipo="noticia"):
    """Una noticia mínima, con el formato que devuelve noticias.py."""
    return {"id": id_, "tipo": tipo, "fuente": fuente, "autor": None, "titulo": titulo, "texto": texto,
            "url": f"https://ejemplo.com/{id_}", "fecha": fecha, "simbolos": [], "sentimiento": None,
            "interaccion": 0}


def posicion(simbolo, cantidad, nombre=None):
    datos.guardar_posicion({"simbolo": simbolo, "nombre": nombre or simbolo, "tipo": "acción", "moneda": "USD",
                            "cantidad": cantidad, "precio_medio": 100.0 if cantidad else 0})
