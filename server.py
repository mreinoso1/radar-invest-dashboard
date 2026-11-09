"""Radar: mercado, cartera y noticias analizadas. Servidor local.

Ejecuta:  py server.py   y abre http://127.0.0.1:8770
Los datos se guardan en %LOCALAPPDATA%\\Radar (fuera de OneDrive, por la clave de la API).
"""
import json
import mimetypes
import os
import re
import secrets
import sys
import threading
import time
import urllib.request
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import agente
import alertas
import analista
import calendario
import calibracion
import canales
import cuant
import cuenta
import datos
import kraken
import marcador
import mercado
import noticias
import oportunidades

HOST, PORT = "127.0.0.1", int(os.environ.get("RADAR_PUERTO", 8770))
STATIC = Path(__file__).resolve().parent / "static"
HOSTS_VALIDOS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
MONEDAS = ("EUR", "USD", "GBP")
SECRETOS = ("anthropic_key", "x_token", "kraken_key", "kraken_secret", "kraken_fut_key", "kraken_fut_secret",
            "telegram_token", "fred_key", "sec_contacto")
CONTACTO_SEC = re.compile(r".+\s\S+@\S+\.\S+")  # "Nombre correo@dominio", como pide la SEC
LIMITES = [  # ajustes numéricos: (clave, tipo, mínimo, máximo, error)
    ("max_analisis", int, 1, 100, "Número de noticias no válido"),
    ("max_oportunidades", int, 1, 60, "Número de noticias para ideas no válido"),
    ("max_ideas", int, 1, 20, "Número de ideas no válido"),
    ("comision_acciones", float, 0.0, 5.0, "Comisión de acciones no válida"),
    ("comision_cripto", float, 0.0, 5.0, "Comisión de cripto no válida"),
    ("alerta_mov_acciones", float, 0.5, 50.0, "Umbral de movimiento no válido"),
    ("alerta_mov_cripto", float, 0.5, 50.0, "Umbral de movimiento no válido"),
    ("alertas_por_hora", int, 1, 60, "Límite de alertas no válido"),
    ("hora_resumen", int, 0, 23, "Hora del resumen no válida"),
]
CASILLAS = ("auto_analizar", "resumen_auto", "alertas_windows", "alertas_telegram", "alertas_ntfy", "alertas_minimas")
TEMA_NTFY = re.compile(r"[A-Za-z0-9_-]{6,64}")
DIAS_IDEAS = 90  # las ideas con horizonte de meses tardan eso en resolverse


class ErrorApi(Exception):
    def __init__(self, estado, mensaje):
        super().__init__(mensaje)
        self.estado = estado
        self.mensaje = mensaje


def ajustes_publicos():
    """Nunca devuelve las claves al navegador, solo si existen."""
    cfg = datos.ajustes()
    publicos = {k: v for k, v in cfg.items() if k not in SECRETOS}
    return {
        **publicos,
        "tiene_clave": bool(cfg["anthropic_key"]),
        "tiene_x": bool(cfg["x_token"]),
        "tiene_kraken": bool(cfg["kraken_key"] and cfg["kraken_secret"]),
        "tiene_kraken_fut": bool(cfg["kraken_fut_key"] and cfg["kraken_fut_secret"]),
        "tiene_telegram": bool(cfg["telegram_token"]),
        "tiene_fred": bool(cfg["fred_key"]),
        "tiene_sec": bool(cfg["sec_contacto"]),
        "agente_listo": agente.listo(cfg),
        "cuenta": cuenta.estado(),
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


def ideas():
    """Lo que pinta la vista Ideas. Cómo va cada idea lo da /api/aciertos?origen=ideas, que usa la red."""
    menciones = datos.menciones(int(time.time()) - oportunidades.HORAS_PENDIENTES * 3600)
    return {
        "ideas": datos.ideas(int(time.time()) - DIAS_IDEAS * 86400),
        "estado": oportunidades.estado(),
        "watchlist": sorted(oportunidades.watchlist()),
        "menciones": [{"simbolo": s, "n": len(v), "ultimas": v[:3]}
                      for s, v in sorted(menciones.items(), key=lambda kv: -len(kv[1]))],
    }


def crear_regla(cuerpo):
    """Una regla de precio sobre algo que el vigilante sigue (cartera o watchlist), aún sin cumplir."""
    simbolo = str(cuerpo.get("simbolo", "")).strip().upper()
    condicion = cuerpo.get("condicion")
    if simbolo not in {p["simbolo"] for p in datos.posiciones()}:
        raise ErrorApi(400, "Solo se vigila lo que está en tu cartera o tu watchlist: añádelo antes allí")
    if condicion not in ("sube_de", "baja_de"):
        raise ErrorApi(400, "Condición no válida")
    try:
        nivel = float(cuerpo.get("nivel"))
    except (TypeError, ValueError):
        raise ErrorApi(400, "El nivel debe ser un número")
    precio = mercado.cotizacion(simbolo)["precio"]
    if precio and ((condicion == "sube_de" and precio >= nivel) or (condicion == "baja_de" and precio <= nivel)):
        raise ErrorApi(400, f"{simbolo} ya cotiza a {precio:g}: la alerta saltaría al momento")
    return {"id": datos.guardar_regla(simbolo, condicion, nivel, str(cuerpo.get("nota", "")).strip()[:200])}


def crear_evento(cuerpo):
    titulo = str(cuerpo.get("titulo", "")).strip()[:160]
    try:
        fecha = int(cuerpo.get("fecha"))
    except (TypeError, ValueError):
        raise ErrorApi(400, "Fecha no válida")
    if not titulo:
        raise ErrorApi(400, "Escribe qué pasa ese día")
    simbolo = str(cuerpo.get("simbolo") or "").strip().upper()[:24]
    return {"id": datos.guardar_evento(simbolo, titulo, fecha)}


def probar_canal(cuerpo):
    canal = cuerpo.get("canal")
    if canal not in ("windows", "telegram", "ntfy"):
        raise ErrorApi(400, "Canal no válido")
    prueba = {"titulo": "Radar: alerta de prueba", "texto": "Si ves esto, este canal funciona.", "urgente": False}
    return canales.enviar(prueba, datos.ajustes(), [canal])


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
    for clave in SECRETOS:
        if clave in cuerpo:  # vacío = borrar la clave guardada
            cambios[clave] = str(cuerpo[clave]).strip()
    if cambios.get("sec_contacto") and not CONTACTO_SEC.fullmatch(cambios["sec_contacto"]):
        raise ErrorApi(400, "El contacto para la SEC debe ser un nombre y un correo, por ejemplo «Ana Pérez ana@correo.com»")
    if cuerpo.get("conexion") in ("cuenta", "api"):
        cambios["conexion"] = cuerpo["conexion"]
    for clave in ("modelo", "modelo_chat"):
        if cuerpo.get(clave) in agente.MODELOS:
            cambios[clave] = cuerpo[clave]
    if cuerpo.get("moneda") in MONEDAS:
        cambios["moneda"] = cuerpo["moneda"]
    for clave in CASILLAS:
        if clave in cuerpo:
            cambios[clave] = bool(cuerpo[clave])
    if cuerpo.get("alertas_niveles") in ("analista", "todos", "ninguno"):
        cambios["alertas_niveles"] = cuerpo["alertas_niveles"]
    if "telegram_chat" in cuerpo:
        cambios["telegram_chat"] = str(cuerpo["telegram_chat"]).strip()[:40]
    if "ntfy_servidor" in cuerpo:
        servidor = str(cuerpo["ntfy_servidor"]).strip().rstrip("/") or "https://ntfy.sh"
        if not servidor.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            raise ErrorApi(400, "El servidor de ntfy debe empezar por https://")
        cambios["ntfy_servidor"] = servidor
    if "ntfy_tema" in cuerpo:
        tema = str(cuerpo["ntfy_tema"]).strip()
        if tema and not TEMA_NTFY.fullmatch(tema):
            raise ErrorApi(400, "El tema de ntfy solo admite letras, números, - y _ (de 6 a 64)")
        cambios["ntfy_tema"] = tema
    # Quien adivine el tema de ntfy lee tus avisos: si no hay uno, se crea largo y aleatorio.
    if cambios.get("alertas_ntfy") and not cambios.get("ntfy_tema", datos.ajustes()["ntfy_tema"]):
        cambios["ntfy_tema"] = "radar-" + secrets.token_urlsafe(16).replace("_", "").replace("-", "")[:20]
    for clave, tipo, bajo, alto, error in LIMITES:
        if clave in cuerpo:
            try:
                cambios[clave] = max(bajo, min(alto, tipo(cuerpo[clave])))
            except (TypeError, ValueError):
                raise ErrorApi(400, error)
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
        except (mercado.ErrorMercado, cuenta.ErrorCuenta, kraken.ErrorKraken) as e:
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
        elif ruta == "/api/ficha":
            self._json(analista.ficha(q.get("s", "")))
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
        elif ruta == "/api/aciertos":
            self._json(marcador.calcular(q.get("origen", "cartera")))
        elif ruta == "/api/ideas":
            self._json(ideas())
        elif ruta == "/api/ideas/estado":
            self._json(oportunidades.estado())
        elif ruta == "/api/alertas":
            self._json({"alertas": datos.alertas(int(time.time()) - 30 * 86400), "no_leidas": datos.no_leidas(),
                        "reglas": datos.reglas_alerta()})
        elif ruta == "/api/cuant":
            simbolo = q.get("s", "")
            self._json({"lineas": cuant.texto_activo(cuant.de_activo(simbolo)), "macro": cuant.texto_macro(cuant.macro())})
        elif ruta == "/api/top":
            r = marcador.calcular("todas")
            self._json({"top": calibracion.top(r["senales"], r["por_tipo"], time.time()), "tipos": r["por_tipo"]})
        elif ruta == "/api/alertas/no_leidas":
            self._json({"n": datos.no_leidas()})
        elif ruta == "/api/calendario":  # aparte: la primera vez consulta varias webs y tarda
            eventos, errores = calendario.proximos([p["simbolo"] for p in datos.posiciones()])
            self._json({"eventos": eventos, "errores": errores})
        elif ruta == "/api/kraken":
            self._json(kraken.resumen(q.get("forzar") == "1"))
        elif ruta == "/api/cuenta":
            cuenta.estado(forzar=True)
            self._json(ajustes_publicos())
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
        elif url.path == "/api/apagar":
            # Un Radar nuevo que arranca pide paso; sin esto seguiría contestando el código viejo.
            self._json({"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        elif url.path == "/api/cuenta/iniciar":
            cuenta.iniciar_sesion()
            self._json({"ok": True})
        elif url.path == "/api/feed/actualizar":
            self._json(actualizar_feed(cuerpo))
        elif url.path == "/api/agente":
            ids = cuerpo.get("ids") if isinstance(cuerpo.get("ids"), list) else None
            error = agente.analizar("social" if cuerpo.get("tipo") == "social" else "noticia", ids)
            self._json({"error": error} if error else {"ok": True})
        elif url.path == "/api/ideas/analizar":
            error = oportunidades.analizar()
            self._json({"error": error} if error else {"ok": True})
        elif url.path == "/api/alertas/reglas":
            self._json(crear_regla(cuerpo))
        elif url.path == "/api/alertas/leidas":
            datos.marcar_leidas()
            self._json({"ok": True})
        elif url.path == "/api/alertas/probar":
            self._json(probar_canal(cuerpo))
        elif url.path == "/api/eventos":
            self._json(crear_evento(cuerpo))
        elif url.path == "/api/watchlist/inicial":
            self._json({"anadidos": oportunidades.cargar_watchlist_inicial()})
        elif url.path == "/api/resumen":
            self._json(analista.generar_resumen(str(cuerpo.get("simbolo", "")), bool(cuerpo.get("forzar"))))
        elif url.path == "/api/chat":
            self._json(analista.responder(str(cuerpo.get("simbolo", "")), str(cuerpo.get("texto", ""))))
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
        if url.path in ("/api/alertas/reglas", "/api/eventos"):  # estas se borran por id
            if not q.get("id", "").isdigit():
                raise ErrorApi(400, "Falta el id")
            (datos.borrar_regla if url.path == "/api/alertas/reglas" else datos.borrar_evento)(int(q["id"]))
            return self._json({"ok": True})
        if not q.get("s"):
            raise ErrorApi(404, "No encontrado")
        if url.path == "/api/cartera":
            datos.borrar_posicion(q["s"])
        elif url.path == "/api/chat":
            datos.borrar_chat(q["s"])
        else:
            raise ErrorApi(404, "No encontrado")
        self._json({"ok": True})


class Servidor(ThreadingHTTPServer):
    # En Windows, reutilizar la dirección deja escuchar a dos Radar en el mismo puerto, y contesta el viejo
    # con su código antiguo: las rutas nuevas dan "No encontrado".
    allow_reuse_address = False
    daemon_threads = True


def _cerrar_anterior():
    """Pide al Radar que siga abierto en el puerto que se cierre. Los anteriores a esta versión no saben."""
    peticion = urllib.request.Request(f"http://{HOST}:{PORT}/api/apagar", data=b"{}", method="POST",
                                      headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(peticion, timeout=3).read()
    except OSError:
        return
    time.sleep(1.5)


def main():
    _cerrar_anterior()
    try:
        servidor = Servidor((HOST, PORT), Manejador)
    except OSError:
        print(f"El puerto {PORT} está ocupado, seguramente por un Radar antiguo que sigue abierto.\n"
              "Cierra su ventana negra (o reinicia el ordenador) y vuelve a abrir iniciar.bat.")
        return
    url = f"http://{HOST}:{PORT}"
    print(f"Radar en {url}  (Ctrl+C para salir)")
    alertas.Vigilante().start()  # las alertas solo funcionan mientras esta ventana siga abierta
    if "--sin-navegador" not in sys.argv:
        threading.Timer(0.7, webbrowser.open, args=(url,)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
