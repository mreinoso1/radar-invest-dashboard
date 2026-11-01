"""Radar: mercado, cartera y noticias analizadas. Servidor local.

Ejecuta:  py server.py   y abre http://127.0.0.1:8770
Los datos se guardan en %LOCALAPPDATA%\\Radar (fuera de OneDrive, por la clave de la API).
"""
import json
import mimetypes
import os
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import agente
import datos
import mercado
import noticias

HOST, PORT = "127.0.0.1", int(os.environ.get("RADAR_PUERTO", 8770))
STATIC = Path(__file__).resolve().parent / "static"
HOSTS_VALIDOS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
MONEDAS = ("EUR", "USD", "GBP")


class ErrorApi(Exception):
    def __init__(self, estado, mensaje):
        super().__init__(mensaje)
        self.estado = estado
        self.mensaje = mensaje


def ajustes_publicos():
    """Nunca devuelve las claves al navegador, solo si existen."""
    cfg = datos.ajustes()
    publicos = {k: v for k, v in cfg.items() if k not in ("anthropic_key", "x_token")}
    return {
        **publicos,
        "tiene_clave": bool(cfg["anthropic_key"]),
        "tiene_x": bool(cfg["x_token"]),
        "modelos": agente.MODELOS,
        "datos_en": str(datos.DATOS),
    }


def cartera():
    cfg = datos.ajustes()
    posiciones = datos.posiciones()
    cotiz = {c["simbolo"]: c for c in mercado.cotizaciones([p["simbolo"] for p in posiciones])}
    filas, total_valor, total_coste, total_dia, sin_cambio = [], 0.0, 0.0, 0.0, []
    for p in posiciones:
        c = cotiz[p["simbolo"]]
        fx = mercado.cambio(p["moneda"], cfg["moneda"])
        if fx is None:
            sin_cambio.append(p["moneda"])
            fx = 1.0
        precio = c["precio"]
        valor = (precio or 0) * p["cantidad"] * fx
        coste = p["precio_medio"] * p["cantidad"] * fx
        dia = valor * (1 - 1 / (1 + c["var_dia"] / 100)) if c["var_dia"] is not None else 0.0
        total_valor += valor
        total_coste += coste
        total_dia += dia
        filas.append({**p, "precio": precio, "var_dia": c["var_dia"], "var_5d": c["var_5d"],
                      "valor": valor, "coste": coste, "dia": dia,
                      "ganancia": valor - coste if precio else None})
    for f in filas:
        f["peso"] = f["valor"] / total_valor * 100 if total_valor else 0
    return {
        "moneda": cfg["moneda"], "filas": filas, "valor": total_valor, "coste": total_coste,
        "ganancia": total_valor - total_coste, "dia": total_dia,
        "avisos": [f"Sin tipo de cambio para {m}" for m in sorted(set(sin_cambio))],
    }


def guardar_posicion(cuerpo):
    simbolo = str(cuerpo.get("simbolo", "")).strip().upper()
    if not simbolo or len(simbolo) > 24:
        raise ErrorApi(400, "Símbolo no válido")
    try:
        cantidad = float(cuerpo.get("cantidad", 0))
        precio = float(cuerpo.get("precio_medio", 0))
    except (TypeError, ValueError):
        raise ErrorApi(400, "Cantidad y precio deben ser números")
    if cantidad < 0 or precio < 0:
        raise ErrorApi(400, "Cantidad y precio no pueden ser negativos")
    if cantidad > 0 and precio == 0:
        raise ErrorApi(400, "Indica el precio medio de compra")
    existente = next((p for p in datos.posiciones() if p["simbolo"] == simbolo), None)
    if cuerpo.get("sumar") and existente and cantidad > 0:
        # Comprar más del mismo activo promedia el precio de entrada.
        total = existente["cantidad"] + cantidad
        precio = (existente["cantidad"] * existente["precio_medio"] + cantidad * precio) / total
        cantidad = total
    if existente:
        base = {k: existente[k] for k in ("nombre", "tipo", "moneda")}
    else:
        info = mercado.velas(simbolo, "1d", corto=True)
        tipo = str(cuerpo.get("tipo") or "")
        if info["tipo_yahoo"] == "CRYPTOCURRENCY":
            tipo = "cripto"
        base = {"nombre": str(cuerpo.get("nombre") or info["nombre"])[:120],
                "tipo": tipo or "acción", "moneda": info["moneda"] or "USD"}
    datos.guardar_posicion({"simbolo": simbolo, "cantidad": cantidad, "precio_medio": precio, **base})


def guardar_ajustes(cuerpo):
    cambios = {}
    for clave in ("anthropic_key", "x_token"):
        if clave in cuerpo:  # vacío = borrar la clave guardada
            cambios[clave] = str(cuerpo[clave]).strip()
    if cuerpo.get("modelo") in agente.MODELOS:
        cambios["modelo"] = cuerpo["modelo"]
    if cuerpo.get("moneda") in MONEDAS:
        cambios["moneda"] = cuerpo["moneda"]
    if "auto_analizar" in cuerpo:
        cambios["auto_analizar"] = bool(cuerpo["auto_analizar"])
    if "max_analisis" in cuerpo:
        try:
            cambios["max_analisis"] = max(1, min(100, int(cuerpo["max_analisis"])))
        except (TypeError, ValueError):
            raise ErrorApi(400, "Número de noticias no válido")
    datos.guardar_ajustes(cambios)
    return ajustes_publicos()


def actualizar_feed(cuerpo):
    if cuerpo.get("tipo") == "social":
        return noticias.actualizar_social(bool(cuerpo.get("incluir_x")))
    return noticias.actualizar_noticias()


class Manejador(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _permitido(self):
        # Sirve solo a esta app: impide que una web abierta en el navegador hable con la API local.
        if self.headers.get("Host") not in HOSTS_VALIDOS:
            return False
        origen = self.headers.get("Origin")
        return not origen or urlparse(origen).netloc in HOSTS_VALIDOS

    def _responder(self, estado, cuerpo, tipo):
        self.send_response(estado)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _json(self, valor, estado=200):
        self._responder(estado, json.dumps(valor, ensure_ascii=False).encode("utf-8"),
                        "application/json; charset=utf-8")

    def _cuerpo(self):
        largo = int(self.headers.get("Content-Length") or 0)
        if largo > 2_000_000:
            raise ErrorApi(413, "Petición demasiado grande")
        if not largo:
            return {}
        try:
            valor = json.loads(self.rfile.read(largo))
        except json.JSONDecodeError:
            raise ErrorApi(400, "JSON no válido")
        return valor if isinstance(valor, (dict, list)) else {}

    def _gestionar(self, funcion):
        try:
            if not self._permitido():
                raise ErrorApi(403, "Origen no permitido")
            funcion()
        except ErrorApi as e:
            self._json({"error": e.mensaje}, e.estado)
        except mercado.ErrorMercado as e:
            self._json({"error": str(e)}, 502)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass
        except Exception as e:
            print("Error:", repr(e), file=sys.stderr)
            self._json({"error": f"Error interno: {e}"}, 500)

    def _estatico(self, ruta):
        destino = (STATIC / (ruta.lstrip("/") or "index.html")).resolve()
        if STATIC not in destino.parents or not destino.is_file():
            raise ErrorApi(404, "No encontrado")
        tipo = mimetypes.guess_type(destino.name)[0] or "application/octet-stream"
        if tipo.startswith("text/") or tipo.endswith("javascript"):
            tipo += "; charset=utf-8"
        self._responder(200, destino.read_bytes(), tipo)

    def do_GET(self):
        self._gestionar(self._get)

    def do_POST(self):
        self._gestionar(self._post)

    def do_PUT(self):
        self._gestionar(self._post)

    def do_DELETE(self):
        self._gestionar(self._delete)

    def _get(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        ruta = url.path
        if not ruta.startswith("/api/"):
            return self._estatico(ruta)
        if ruta == "/api/ajustes":
            self._json(ajustes_publicos())
        elif ruta == "/api/velas":
            self._json(mercado.velas(q.get("s", ""), q.get("i", "1d"), q.get("corto") == "1"))
        elif ruta == "/api/cotizaciones":
            self._json(mercado.cotizaciones([s for s in q.get("s", "").split(",") if s][:40]))
        elif ruta == "/api/indices":
            self._json(mercado.indices())
        elif ruta == "/api/buscar":
            self._json(mercado.buscar(q.get("q", ""))[:8] if q.get("q") else [])
        elif ruta == "/api/cartera":
            self._json(cartera())
        elif ruta == "/api/feed":
            tipo = "social" if q.get("tipo") == "social" else "noticia"
            self._json(datos.feed(tipo))
        elif ruta == "/api/social/sentimiento":
            self._json(datos.sentimiento_social(int(time.time()) - 3 * 86400))
        elif ruta == "/api/agente":
            self._json(agente.estado())
        elif ruta == "/api/dibujos":
            self._json(datos.dibujos(q.get("s", "")))
        else:
            raise ErrorApi(404, "No encontrado")

    def _post(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        cuerpo = self._cuerpo()
        if url.path == "/api/cartera":
            guardar_posicion(cuerpo)
            self._json({"ok": True})
        elif url.path == "/api/ajustes":
            self._json(guardar_ajustes(cuerpo))
        elif url.path == "/api/feed/actualizar":
            self._json(actualizar_feed(cuerpo))
        elif url.path == "/api/agente":
            ids = cuerpo.get("ids") if isinstance(cuerpo.get("ids"), list) else None
            error = agente.analizar("social" if cuerpo.get("tipo") == "social" else "noticia", ids)
            self._json({"error": error} if error else {"ok": True})
        elif url.path == "/api/dibujos":
            if not q.get("s") or not isinstance(cuerpo, list):
                raise ErrorApi(400, "Dibujos no válidos")
            datos.guardar_dibujos(q["s"], cuerpo)
            self._json({"ok": True})
        else:
            raise ErrorApi(404, "No encontrado")

    def _delete(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path != "/api/cartera" or not q.get("s"):
            raise ErrorApi(404, "No encontrado")
        datos.borrar_posicion(q["s"])
        self._json({"ok": True})


def main():
    servidor = ThreadingHTTPServer((HOST, PORT), Manejador)
    servidor.daemon_threads = True
    url = f"http://{HOST}:{PORT}"
    print(f"Radar en {url}  (Ctrl+C para salir)")
    if "--sin-navegador" not in sys.argv:
        threading.Timer(0.7, webbrowser.open, args=(url,)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
