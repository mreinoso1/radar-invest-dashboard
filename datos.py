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
    "kraken_key": "",          # claves de solo consulta: Radar nunca opera
    "kraken_secret": "",
    "kraken_fut_key": "",
    "kraken_fut_secret": "",
    "modelo": "claude-opus-5-5",
    "modelo_chat": "claude-sonnet-5-5",
    "moneda": "EUR",
    "auto_analizar": False,
    "resumen_auto": True,
    "max_analisis": 30,
    "max_oportunidades": 16,   # noticias por pasada del modo oportunidades
    "max_ideas": 5,            # activos distintos que puede proponer en cada pasada
    "comision_acciones": 0.10,  # % de ida y vuelta que el marcador descuenta a cada señal
    "comision_cripto": 0.52,    # dos veces la comisión taker de Kraken
    # Alertas: canales, umbrales y límites contra el spam.
    "alertas_windows": True,
    "alertas_telegram": False,
    "alertas_ntfy": False,
    "alertas_minimas": False,   # Telegram y ntfy reciben solo "hay una alerta", sin activos ni precios
    "telegram_token": "",
    "telegram_chat": "",
    "ntfy_servidor": "https://ntfy.sh",
    "ntfy_tema": "",
    "fred_key": "",             # gratuita, de solo lectura: fechas de IPC, empleo, PIB y PCE
    "alerta_mov_acciones": 5.0,  # % en el día que se considera un movimiento fuerte
    "alerta_mov_cripto": 8.0,
    "alertas_por_hora": 6,
    "hora_resumen": 21,
    "alertas_niveles": "analista",  # analista | todos | ninguno: qué niveles dibujados vigilar
    "sec_contacto": "",         # nombre y correo que la SEC exige a quien consulta EDGAR
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
CREATE TABLE IF NOT EXISTS resumenes (
    simbolo TEXT PRIMARY KEY,
    contenido TEXT NOT NULL,       -- resumen del agente (JSON)
    modelo TEXT NOT NULL,
    creado INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS chat (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simbolo TEXT NOT NULL,
    rol TEXT NOT NULL,             -- usuario | agente
    texto TEXT NOT NULL,
    creado INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS chat_simbolo ON chat (simbolo, id);
-- Modo oportunidades: qué noticias ya revisó (con o sin ideas) y qué propuso.
CREATE TABLE IF NOT EXISTS ideas_items (
    item_id TEXT PRIMARY KEY REFERENCES items (id) ON DELETE CASCADE,
    modelo TEXT NOT NULL,          -- "listas" si solo se extrajeron menciones, sin modelo
    titulo TEXT,                   -- titular traducido, si pasó por el modelo
    creado INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS ideas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL REFERENCES items (id) ON DELETE CASCADE,
    simbolo TEXT NOT NULL,
    relacion TEXT NOT NULL,        -- proveedor | cliente | competidor | sector | macro | directo
    prob_subida INTEGER NOT NULL,
    confianza INTEGER NOT NULL,
    horizonte TEXT NOT NULL,
    mecanismo TEXT NOT NULL,
    invalidacion TEXT NOT NULL,
    que_tendria_que_pasar TEXT NOT NULL,
    precio REAL,                   -- la cotización que tenía delante: el marcador parte de ella
    modelo TEXT NOT NULL,
    creado INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ideas_creado ON ideas (creado DESC);
-- Alertas: reglas de precio del usuario, historial de avisos, eventos de calendario manuales y el estado
-- que el vigilante necesita entre rondas (último precio visto, niveles armados...).
CREATE TABLE IF NOT EXISTS reglas_alerta (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simbolo TEXT NOT NULL,
    condicion TEXT NOT NULL,       -- sube_de | baja_de
    nivel REAL NOT NULL,
    nota TEXT NOT NULL DEFAULT '',
    activa INTEGER NOT NULL DEFAULT 1,
    creada INTEGER NOT NULL,
    disparada INTEGER
);
CREATE TABLE IF NOT EXISTS alertas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clave TEXT NOT NULL,           -- identidad: la misma clave no se avisa dos veces
    tipo TEXT NOT NULL,            -- precio | nivel | noticia | movimiento | calendario | resumen
    simbolo TEXT,
    titulo TEXT NOT NULL,
    texto TEXT NOT NULL,
    urgente INTEGER NOT NULL,
    creada INTEGER NOT NULL,
    enviada TEXT,                  -- JSON {canal: "ok" o error}; NULL = espera al resumen diario
    leida INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS alertas_creada ON alertas (creada DESC);
CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simbolo TEXT,
    titulo TEXT NOT NULL,
    fecha INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS estado_alertas (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);
-- Fase 3: foto diaria de los datos cuantitativos (para calcular cambios y para el backtest), señales que
-- genera Python con reglas fijas, y los Form 4 ya leídos de EDGAR (no cambian: no se vuelven a pedir).
CREATE TABLE IF NOT EXISTS cuant_historia (
    simbolo TEXT NOT NULL,
    dia TEXT NOT NULL,             -- AAAA-MM-DD
    datos TEXT NOT NULL,           -- JSON
    PRIMARY KEY (simbolo, dia)
);
CREATE TABLE IF NOT EXISTS senales_reglas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    regla TEXT NOT NULL,
    simbolo TEXT NOT NULL,
    direccion TEXT NOT NULL,       -- la apuesta de la regla, aparte de su probabilidad medida
    prob_subida INTEGER NOT NULL,
    horizonte TEXT NOT NULL,
    detalle TEXT NOT NULL,
    precio REAL,
    creado INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS form4 (
    acceso TEXT PRIMARY KEY,       -- número de acceso de la SEC
    simbolo TEXT NOT NULL,
    fecha TEXT NOT NULL,
    transacciones TEXT NOT NULL    -- JSON
);
-- Tickers de la watchlist citados en listas tipo "acciones para comprar": sentimiento, no hechos.
CREATE TABLE IF NOT EXISTS menciones (
    item_id TEXT NOT NULL REFERENCES items (id) ON DELETE CASCADE,
    simbolo TEXT NOT NULL,
    fecha INTEGER NOT NULL,
    PRIMARY KEY (item_id, simbolo)
);
"""

_lock = threading.RLock()
_con = sqlite3.connect(RUTA_DB, check_same_thread=False)
_con.row_factory = sqlite3.Row
with _lock:
    _con.execute("PRAGMA foreign_keys = ON")
    _con.executescript(ESQUEMA)
    # evento: id de la noticia que ya cuenta este mismo hecho. Las bases antiguas no lo traen.
    if "evento" not in {c["name"] for c in _con.execute("PRAGMA table_info(items)")}:
        _con.execute("ALTER TABLE items ADD COLUMN evento TEXT")
    # extra: dibujos que el analista propone con su respuesta (JSON).
    if "extra" not in {c["name"] for c in _con.execute("PRAGMA table_info(chat)")}:
        _con.execute("ALTER TABLE chat ADD COLUMN extra TEXT")


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
        # Lo analizado y lo que dio ideas se queda: el marcador lo juzga cuando acabe su plazo.
        _con.execute(
            """DELETE FROM items WHERE fecha < ? AND id NOT IN (SELECT item_id FROM analisis)
               AND id NOT IN (SELECT item_id FROM ideas)""", (limite,)
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
                  WHERE i.tipo = ? AND i.evento IS NULL AND a.item_id IS {} NULL
                  ORDER BY i.fecha DESC LIMIT ?"""
    with _lock:
        analizadas = _con.execute(consulta.format("NOT"), (tipo, limite)).fetchall()
        pendientes = _con.execute(consulta.format(""), (tipo, limite)).fetchall()
        repetidas = _con.execute(
            "SELECT evento, fuente, titulo, url FROM items WHERE tipo = ? AND evento IS NOT NULL ORDER BY fecha",
            (tipo,),
        ).fetchall()
    otras = {}
    for r in repetidas:
        otras.setdefault(r["evento"], []).append({"fuente": r["fuente"], "titulo": r["titulo"], "url": r["url"]})
    items = (_a_item(f) for f in [*analizadas, *pendientes])
    return sorted(({**it, "otras": otras.get(it["id"], [])} for it in items), key=lambda it: -it["fecha"])


def pendientes(tipo, limite, desde):
    """Items sin analizar, los más recientes primero."""
    with _lock:
        filas = _con.execute(
            """SELECT i.* FROM items i LEFT JOIN analisis a ON a.item_id = i.id
               WHERE i.tipo = ? AND a.item_id IS NULL AND i.evento IS NULL AND i.fecha >= ?
               ORDER BY i.fecha DESC LIMIT ?""",
            (tipo, desde, limite),
        ).fetchall()
    return [dict(f, simbolos=json.loads(f["simbolos"])) for f in filas]


def eventos_analizados(tipo, limite, desde):
    """Hechos ya analizados, para reconocer las noticias nuevas que los repiten."""
    with _lock:
        filas = _con.execute(
            """SELECT i.id, i.fuente, i.titulo FROM items i JOIN analisis a ON a.item_id = i.id
               WHERE i.tipo = ? AND i.evento IS NULL AND i.fecha >= ?
               ORDER BY i.fecha DESC LIMIT ?""",
            (tipo, desde, limite),
        ).fetchall()
    return [dict(f) for f in filas]


def marcar_repetidas(asignacion):
    """asignacion: {id de la noticia repetida: id de la noticia principal}."""
    with _lock, _con:
        _con.executemany("UPDATE items SET evento = ? WHERE id = ?", [(p, i) for i, p in asignacion.items()])


def otras_fuentes(ids):
    marcas = ",".join("?" * len(ids))
    with _lock:
        filas = _con.execute(
            f"SELECT evento, fuente, titulo FROM items WHERE evento IN ({marcas}) ORDER BY fecha", list(ids),
        ).fetchall()
    salida = {}
    for f in filas:
        salida.setdefault(f["evento"], []).append(f"{f['fuente']}: {f['titulo']}")
    return salida


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


def senales():
    """Análisis que se le enseñaron al usuario como relevantes, con sus impactos por activo."""
    with _lock:
        filas = _con.execute(
            """SELECT a.item_id, a.titulo, a.categoria, a.impactos, a.modelo, a.creado, i.tipo, i.fuente, i.url, i.fecha
               FROM analisis a JOIN items i ON i.id = a.item_id
               WHERE a.relevante = 1 ORDER BY a.creado DESC""",
        ).fetchall()
    return [dict(f, impactos=json.loads(f["impactos"])) for f in filas]


def pendientes_ideas(limite, desde):
    """Noticias que el modo oportunidades aún no ha revisado, las más recientes primero."""
    with _lock:
        filas = _con.execute(
            """SELECT i.* FROM items i LEFT JOIN ideas_items v ON v.item_id = i.id
               WHERE i.tipo = 'noticia' AND v.item_id IS NULL AND i.evento IS NULL AND i.fecha >= ?
               ORDER BY i.fecha DESC LIMIT ?""",
            (desde, limite),
        ).fetchall()
    return [dict(f, simbolos=json.loads(f["simbolos"])) for f in filas]


def guardar_ideas(item_id, ideas, modelo, titulo=None):
    """Marca la noticia como revisada y guarda sus ideas (puede no haber ninguna)."""
    ahora = int(time.time())
    with _lock, _con:
        _con.execute("INSERT OR REPLACE INTO ideas_items (item_id, modelo, titulo, creado) VALUES (?, ?, ?, ?)",
                     (item_id, modelo, titulo, ahora))
        for i in ideas:
            _con.execute(
                """INSERT INTO ideas (item_id, simbolo, relacion, prob_subida, confianza, horizonte, mecanismo,
                                      invalidacion, que_tendria_que_pasar, precio, modelo, creado)
                   VALUES (:item_id, :simbolo, :relacion, :prob_subida, :confianza, :horizonte, :mecanismo,
                           :invalidacion, :que_tendria_que_pasar, :precio, :modelo, :creado)""",
                {**i, "item_id": item_id, "modelo": modelo, "creado": ahora},
            )


def ideas(desde=0):
    """Ideas con la noticia que las originó, las más recientes primero."""
    with _lock:
        filas = _con.execute(
            """SELECT d.*, COALESCE(v.titulo, a.titulo, i.titulo) AS titulo, i.titulo AS titulo_original, i.url,
                      i.fuente, i.fecha
               FROM ideas d JOIN items i ON i.id = d.item_id LEFT JOIN ideas_items v ON v.item_id = d.item_id
                    LEFT JOIN analisis a ON a.item_id = d.item_id
               WHERE d.creado >= ? ORDER BY d.creado DESC, d.id""",
            (desde,),
        ).fetchall()
    return [dict(f) for f in filas]


def guardar_menciones(pares):
    """pares: lista de (item_id, simbolo, fecha)."""
    with _lock, _con:
        _con.executemany("INSERT OR IGNORE INTO menciones (item_id, simbolo, fecha) VALUES (?, ?, ?)", pares)


def menciones(desde):
    """Cuántas listas citan cada activo desde `desde`, con sus titulares."""
    with _lock:
        filas = _con.execute(
            """SELECT m.simbolo, i.titulo, i.fuente, i.url, m.fecha FROM menciones m JOIN items i ON i.id = m.item_id
               WHERE m.fecha >= ? ORDER BY m.fecha DESC""",
            (desde,),
        ).fetchall()
    salida = {}
    for f in filas:
        salida.setdefault(f["simbolo"], []).append({"titulo": f["titulo"], "fuente": f["fuente"], "url": f["url"],
                                                    "fecha": f["fecha"]})
    return salida


def reglas_alerta(solo_activas=False):
    with _lock:
        filas = _con.execute("SELECT * FROM reglas_alerta" + (" WHERE activa = 1" if solo_activas else "")
                             + " ORDER BY activa DESC, creada DESC").fetchall()
    return [dict(f) for f in filas]


def guardar_regla(simbolo, condicion, nivel, nota=""):
    with _lock, _con:
        return _con.execute(
            "INSERT INTO reglas_alerta (simbolo, condicion, nivel, nota, creada) VALUES (?, ?, ?, ?, ?)",
            (simbolo, condicion, nivel, nota, int(time.time())),
        ).lastrowid


def disparar_regla(regla_id, cuando):
    """Las reglas de precio avisan una vez: después quedan desactivadas."""
    with _lock, _con:
        _con.execute("UPDATE reglas_alerta SET activa = 0, disparada = ? WHERE id = ?", (cuando, regla_id))


def borrar_regla(regla_id):
    with _lock, _con:
        _con.execute("DELETE FROM reglas_alerta WHERE id = ?", (regla_id,))


def guardar_alerta(a, enviada=None, cuando=None):
    with _lock, _con:
        return _con.execute(
            """INSERT INTO alertas (clave, tipo, simbolo, titulo, texto, urgente, creada, enviada)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (a["clave"], a["tipo"], a.get("simbolo"), a["titulo"], a["texto"], int(a["urgente"]),
             cuando or int(time.time()), json.dumps(enviada, ensure_ascii=False) if enviada is not None else None),
        ).lastrowid


def marcar_enviadas(ids, enviada):
    with _lock, _con:
        _con.executemany("UPDATE alertas SET enviada = ? WHERE id = ?",
                         [(json.dumps(enviada, ensure_ascii=False), i) for i in ids])


def alertas(desde=0, limite=200):
    with _lock:
        filas = _con.execute("SELECT * FROM alertas WHERE creada >= ? ORDER BY creada DESC, id DESC LIMIT ?",
                             (desde, limite)).fetchall()
    return [dict(f, enviada=json.loads(f["enviada"]) if f["enviada"] else None) for f in filas]


def alertas_sin_enviar():
    """Las que esperan al resumen diario."""
    with _lock:
        filas = _con.execute("SELECT * FROM alertas WHERE enviada IS NULL ORDER BY creada").fetchall()
    return [dict(f) for f in filas]


def marcar_leidas():
    with _lock, _con:
        _con.execute("UPDATE alertas SET leida = 1 WHERE leida = 0")


def no_leidas():
    with _lock:
        return _con.execute("SELECT COUNT(*) FROM alertas WHERE leida = 0").fetchone()[0]


def eventos(desde=0):
    with _lock:
        filas = _con.execute("SELECT * FROM eventos WHERE fecha >= ? ORDER BY fecha", (desde,)).fetchall()
    return [dict(f) for f in filas]


def guardar_evento(simbolo, titulo, fecha):
    with _lock, _con:
        return _con.execute("INSERT INTO eventos (simbolo, titulo, fecha) VALUES (?, ?, ?)",
                            (simbolo or None, titulo, fecha)).lastrowid


def borrar_evento(evento_id):
    with _lock, _con:
        _con.execute("DELETE FROM eventos WHERE id = ?", (evento_id,))


def estado_alertas(clave, defecto=None):
    with _lock:
        fila = _con.execute("SELECT valor FROM estado_alertas WHERE clave = ?", (clave,)).fetchone()
    return json.loads(fila["valor"]) if fila else defecto


def guardar_estado_alertas(clave, valor):
    with _lock, _con:
        _con.execute("INSERT OR REPLACE INTO estado_alertas (clave, valor) VALUES (?, ?)",
                     (clave, json.dumps(valor, ensure_ascii=False)))


def analisis_importantes(desde, minimo=4):
    """Análisis relevantes de importancia alta creados desde `desde`, con sus impactos."""
    with _lock:
        filas = _con.execute(
            """SELECT a.item_id, a.titulo, a.importancia, a.impactos, a.creado, i.fuente, i.url
               FROM analisis a JOIN items i ON i.id = a.item_id
               WHERE a.relevante = 1 AND a.importancia >= ? AND a.creado > ? ORDER BY a.creado""",
            (minimo, desde),
        ).fetchall()
    return [dict(f, impactos=json.loads(f["impactos"])) for f in filas]


def guardar_cuant(simbolo, dia, valores):
    with _lock, _con:
        _con.execute("INSERT OR REPLACE INTO cuant_historia (simbolo, dia, datos) VALUES (?, ?, ?)",
                     (simbolo, dia, json.dumps(valores, ensure_ascii=False)))


def cuant_de(simbolo, dia):
    with _lock:
        fila = _con.execute("SELECT datos FROM cuant_historia WHERE simbolo = ? AND dia = ?", (simbolo, dia)).fetchone()
    return json.loads(fila["datos"]) if fila else None


def guardar_senal_regla(s):
    with _lock, _con:
        return _con.execute(
            """INSERT INTO senales_reglas (regla, simbolo, direccion, prob_subida, horizonte, detalle, precio, creado)
               VALUES (:regla, :simbolo, :direccion, :prob_subida, :horizonte, :detalle, :precio, :creado)""",
            s).lastrowid


def senales_reglas(desde=0):
    with _lock:
        filas = _con.execute("SELECT * FROM senales_reglas WHERE creado >= ? ORDER BY creado DESC", (desde,)).fetchall()
    return [dict(f) for f in filas]


def form4_guardados(simbolo, desde_fecha):
    with _lock:
        filas = _con.execute("SELECT * FROM form4 WHERE simbolo = ? AND fecha >= ?", (simbolo, desde_fecha)).fetchall()
    return {f["acceso"]: dict(f, transacciones=json.loads(f["transacciones"])) for f in filas}


def guardar_form4(acceso, simbolo, fecha, transacciones):
    with _lock, _con:
        _con.execute("INSERT OR REPLACE INTO form4 (acceso, simbolo, fecha, transacciones) VALUES (?, ?, ?, ?)",
                     (acceso, simbolo, fecha, json.dumps(transacciones, ensure_ascii=False)))


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


def resumen(simbolo):
    with _lock:
        fila = _con.execute("SELECT * FROM resumenes WHERE simbolo = ?", (simbolo,)).fetchone()
    return {**json.loads(fila["contenido"]), "modelo": fila["modelo"], "creado": fila["creado"]} if fila else None


def guardar_resumen(simbolo, contenido, modelo):
    with _lock, _con:
        _con.execute(
            "INSERT OR REPLACE INTO resumenes (simbolo, contenido, modelo, creado) VALUES (?, ?, ?, ?)",
            (simbolo, json.dumps(contenido, ensure_ascii=False), modelo, int(time.time())),
        )


def chat(simbolo, limite=40):
    with _lock:
        filas = _con.execute(
            "SELECT rol, texto, creado, extra FROM chat WHERE simbolo = ? ORDER BY id DESC LIMIT ?", (simbolo, limite),
        ).fetchall()
    return [dict(f, dibujos=json.loads(f["extra"] or "[]")) for f in reversed(filas)]


def guardar_chat(simbolo, mensajes):
    """mensajes: lista de (rol, texto, dibujos). La pregunta y su respuesta entran juntas."""
    ahora = int(time.time())
    with _lock, _con:
        _con.executemany(
            "INSERT INTO chat (simbolo, rol, texto, creado, extra) VALUES (?, ?, ?, ?, ?)",
            [(simbolo, rol, texto, ahora, json.dumps(dibujos, ensure_ascii=False) if dibujos else None)
             for rol, texto, dibujos in mensajes],
        )


def borrar_chat(simbolo):
    with _lock, _con:
        _con.execute("DELETE FROM chat WHERE simbolo = ?", (simbolo,))


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
