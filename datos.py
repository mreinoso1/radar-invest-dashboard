"""Almacenamiento local de Radar: SQLite para los datos y JSON para los ajustes.

Todo vive en %LOCALAPPDATA%\\Radar y NO en la carpeta del proyecto: el proyecto
está en OneDrive y la clave de la API no debe sincronizarse con la nube.
"""
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

DATOS = Path(os.environ.get("RADAR_DATOS") or Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Radar")
DATOS.mkdir(parents=True, exist_ok=True)
RUTA_DB = DATOS / "radar.db"
RUTA_AJUSTES = DATOS / "ajustes.json"

AJUSTES_DEFECTO = {
    "conexion": "cuenta",  # cuenta = plan de Claude; api = clave de pago por uso
    "anthropic_key": "",
    "x_token": "",
    "modelo": "claude-opus-5-5",
    "moneda": "EUR",
    "auto_analizar": False,
    "max_analisis": 30,
    "gasto_usd": 0.0,
}

ESQUEMA = """
CREATE TABLE IF NOT EXISTS posiciones (
    simbolo TEXT PRIMARY KEY,
    nombre TEXT NOT NULL,
    tipo TEXT NOT NULL,
    moneda TEXT NOT NULL,
    cantidad REAL NOT NULL,
    precio_medio REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    tipo TEXT NOT NULL,            -- noticia | social
    fuente TEXT NOT NULL,
    autor TEXT,
    titulo TEXT NOT NULL,
    texto TEXT NOT NULL,
    url TEXT NOT NULL,
    fecha INTEGER NOT NULL,
    simbolos TEXT NOT NULL,        -- activos a los que apuntaba el feed (JSON)
    sentimiento TEXT,              -- Bullish | Bearish (etiqueta de StockTwits)
    interaccion INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS items_fecha ON items (tipo, fecha DESC);
CREATE TABLE IF NOT EXISTS analisis (
    item_id TEXT PRIMARY KEY REFERENCES items (id) ON DELETE CASCADE,
    relevante INTEGER NOT NULL,
    importancia INTEGER NOT NULL,
    categoria TEXT NOT NULL,
    titulo TEXT NOT NULL,
    resumen TEXT NOT NULL,
    novedad TEXT NOT NULL,
    impactos TEXT NOT NULL,        -- lista por activo (JSON)
    senal_buy INTEGER,             -- señal global ponderada por cartera, 0-100
    modelo TEXT NOT NULL,
    creado INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS dibujos (
    simbolo TEXT PRIMARY KEY,
    contenido TEXT NOT NULL
);
"""

_lock = threading.RLock()
_con = sqlite3.connect(RUTA_DB, check_same_thread=False)
_con.row_factory = sqlite3.Row
with _lock:
    _con.execute("PRAGMA foreign_keys = ON")
    _con.executescript(ESQUEMA)


def ajustes():
    try:
        guardado = json.loads(RUTA_AJUSTES.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        guardado = {}
    return {**AJUSTES_DEFECTO, **guardado}


def guardar_ajustes(cambios):
    with _lock:
        nuevos = {**ajustes(), **cambios}
        tmp = RUTA_AJUSTES.with_suffix(".tmp")
        tmp.write_text(json.dumps(nuevos, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(RUTA_AJUSTES)
    return nuevos


def sumar_gasto(usd):
    with _lock:
        guardar_ajustes({"gasto_usd": round(ajustes()["gasto_usd"] + usd, 4)})


def posiciones():
    with _lock:
        filas = _con.execute("SELECT * FROM posiciones ORDER BY simbolo").fetchall()
    return [dict(f) for f in filas]


def guardar_posicion(p):
    with _lock, _con:
        _con.execute(
            """INSERT INTO posiciones (simbolo, nombre, tipo, moneda, cantidad, precio_medio)
               VALUES (:simbolo, :nombre, :tipo, :moneda, :cantidad, :precio_medio)
               ON CONFLICT (simbolo) DO UPDATE SET
                 nombre = excluded.nombre, tipo = excluded.tipo, moneda = excluded.moneda,
                 cantidad = excluded.cantidad, precio_medio = excluded.precio_medio""",
            p,
        )


def borrar_posicion(simbolo):
    with _lock, _con:
        _con.execute("DELETE FROM posiciones WHERE simbolo = ?", (simbolo,))


def guardar_items(items):
    """Inserta items nuevos; si ya existían, solo añade los activos que faltaran."""
    nuevos = 0
    with _lock, _con:
        for it in items:
            previo = _con.execute("SELECT simbolos FROM items WHERE id = ?", (it["id"],)).fetchone()
            if previo:
                unidos = sorted(set(json.loads(previo["simbolos"])) | set(it["simbolos"]))
                _con.execute(
                    "UPDATE items SET simbolos = ?, interaccion = ? WHERE id = ?",
                    (json.dumps(unidos), it["interaccion"], it["id"]),
                )
                continue
            nuevos += 1
            _con.execute(
                """INSERT INTO items (id, tipo, fuente, autor, titulo, texto, url, fecha, simbolos,
                                      sentimiento, interaccion)
                   VALUES (:id, :tipo, :fuente, :autor, :titulo, :texto, :url, :fecha, :simbolos_json,
                           :sentimiento, :interaccion)""",
                {**it, "simbolos_json": json.dumps(sorted(it["simbolos"]))},
            )
        limite = int(time.time()) - 14 * 86400
        _con.execute(
            "DELETE FROM items WHERE fecha < ? AND id NOT IN (SELECT item_id FROM analisis)", (limite,)
        )
    return nuevos


def _a_item(fila):
    it = dict(fila)
    it["simbolos"] = json.loads(it["simbolos"])
    if it.get("relevante") is None:
        it["analisis"] = None
    else:
        it["analisis"] = {
            "relevante": bool(it["relevante"]),
            "importancia": it["importancia"],
            "categoria": it["categoria"],
            "titulo": it["titulo_es"],
            "resumen": it["resumen"],
            "novedad": it["novedad"],
            "impactos": json.loads(it["impactos"]),
            "senal_buy": it["senal_buy"],
            "modelo": it["modelo"],
        }
    for clave in ("relevante", "importancia", "categoria", "titulo_es", "resumen", "novedad",
                  "impactos", "senal_buy", "modelo"):
        it.pop(clave, None)
    return it


def feed(tipo, limite=250):
    """Lo analizado siempre se conserva: las noticias nuevas sin analizar no deben desplazarlo."""
    consulta = """SELECT i.*, a.relevante, a.importancia, a.categoria, a.titulo AS titulo_es, a.resumen,
                         a.novedad, a.impactos, a.senal_buy, a.modelo
                  FROM items i LEFT JOIN analisis a ON a.item_id = i.id
                  WHERE i.tipo = ? AND a.item_id IS {} NULL ORDER BY i.fecha DESC LIMIT ?"""
    with _lock:
        analizadas = _con.execute(consulta.format("NOT"), (tipo, limite)).fetchall()
        pendientes = _con.execute(consulta.format(""), (tipo, limite)).fetchall()
    return sorted((_a_item(f) for f in [*analizadas, *pendientes]), key=lambda it: -it["fecha"])


def pendientes(tipo, limite, desde):
    """Items sin analizar, los más recientes primero."""
    with _lock:
        filas = _con.execute(
            """SELECT i.* FROM items i LEFT JOIN analisis a ON a.item_id = i.id
               WHERE i.tipo = ? AND a.item_id IS NULL AND i.fecha >= ?
               ORDER BY i.fecha DESC LIMIT ?""",
            (tipo, desde, limite),
        ).fetchall()
    return [dict(f, simbolos=json.loads(f["simbolos"])) for f in filas]


def items_por_id(ids):
    marcas = ",".join("?" * len(ids))
    with _lock:
        filas = _con.execute(f"SELECT * FROM items WHERE id IN ({marcas})", list(ids)).fetchall()
    return [dict(f, simbolos=json.loads(f["simbolos"])) for f in filas]


def guardar_analisis(item_id, a):
    with _lock, _con:
        _con.execute(
            """INSERT OR REPLACE INTO analisis (item_id, relevante, importancia, categoria, titulo,
                   resumen, novedad, impactos, senal_buy, modelo, creado)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item_id, int(a["relevante"]), a["importancia"], a["categoria"], a["titulo"], a["resumen"],
             a["novedad"], json.dumps(a["impactos"], ensure_ascii=False), a["senal_buy"], a["modelo"],
             int(time.time())),
        )


def sentimiento_social(desde):
    """Recuento alcista/bajista de StockTwits por activo."""
    with _lock:
        filas = _con.execute(
            "SELECT simbolos, sentimiento FROM items WHERE tipo = 'social' AND sentimiento IS NOT NULL AND fecha >= ?",
            (desde,),
        ).fetchall()
    cuenta = {}
    for f in filas:
        for s in json.loads(f["simbolos"]):
            c = cuenta.setdefault(s, {"Bullish": 0, "Bearish": 0})
            c[f["sentimiento"]] = c.get(f["sentimiento"], 0) + 1
    return cuenta


def dibujos(simbolo):
    with _lock:
        fila = _con.execute("SELECT contenido FROM dibujos WHERE simbolo = ?", (simbolo,)).fetchone()
    return json.loads(fila["contenido"]) if fila else []


def guardar_dibujos(simbolo, contenido):
    with _lock, _con:
        _con.execute(
            "INSERT OR REPLACE INTO dibujos (simbolo, contenido) VALUES (?, ?)",
            (simbolo, json.dumps(contenido, ensure_ascii=False)),
        )
