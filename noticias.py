"""Recogida de noticias y publicaciones sociales. Aquí no se decide nada: el criterio
sobre qué importa y a qué activos afecta lo pone el agente (agente.py)."""
import hashlib
import html
import ipaddress
import json
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import quote_plus, urlencode, urlparse

import datos
from mercado import pedir

MAX_DIAS = 7
ATOM = "{http://www.w3.org/2005/Atom}"


def google(consulta):
    return "https://news.google.com/rss/search?" + urlencode(
        {"q": consulta, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    )


# Fuentes generales: la macro afecta a la cartera aunque no nombre ningún activo.
GENERALES = [
    ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("CNBC Economía", "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("Reserva Federal", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    (None, google("Federal Reserve interest rates FOMC when:3d")),
    (None, google("ECB interest rates Lagarde when:3d")),
    (None, google("US inflation CPI jobs report when:3d")),
    (None, google("oil prices OPEC when:3d")),
    (None, google("tariffs trade sanctions markets when:3d")),
]
SUBREDDITS = ["stocks", "wallstreetbets", "investing"]


def limpiar(texto):
    sin_html = re.sub(r"<[^>]+>", " ", texto or "")
    return re.sub(r"\s+", " ", html.unescape(sin_html)).strip()


def _fecha(valor):
    if not valor:
        return int(time.time())
    try:
        return int(parsedate_to_datetime(valor).timestamp())
    except (TypeError, ValueError):
        pass
    try:
        return int(datetime.fromisoformat(valor.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return int(time.time())


def _id(*partes):
    return hashlib.sha1("|".join(partes).encode("utf-8")).hexdigest()[:20]


def _id_titulo(titulo):
    # Por título y no por URL: así la misma historia en dos feeds es un solo item.
    return _id(re.sub(r"[^a-z0-9]+", "", titulo.lower())[:90])


def _rss(contenido, fuente, simbolos):
    items = []
    for nodo in ET.fromstring(contenido).iter("item"):
        titulo = limpiar(nodo.findtext("title"))
        url = (nodo.findtext("link") or "").strip()
        if not titulo or not url.startswith("http"):
            continue
        origen = fuente or (nodo.findtext("source") or "Google News").strip()
        if not fuente:  # Google News añade " - Medio" al final del título
            titulo = re.sub(r"\s+-\s+[^-]{2,60}$", "", titulo)
        items.append({
            "id": _id_titulo(titulo), "tipo": "noticia", "fuente": origen, "autor": None,
            "titulo": titulo,
            # La descripción de Google News solo repite el título con enlaces.
            "texto": limpiar(nodo.findtext("description"))[:1500] if fuente else "",
            "url": url, "fecha": _fecha(nodo.findtext("pubDate")), "simbolos": list(simbolos),
            "sentimiento": None, "interaccion": 0,
        })
    return items


def _reddit(contenido, tickers):
    items = []
    for e in ET.fromstring(contenido).iter(f"{ATOM}entry"):
        titulo = limpiar(e.findtext(f"{ATOM}title"))
        enlace = e.find(f"{ATOM}link")
        url = enlace.get("href") if enlace is not None else ""
        if not titulo or not url or re.search(r"daily|megathread|quarterly thread|rate my portfolio", titulo, re.I):
            continue
        cuerpo = limpiar(e.findtext(f"{ATOM}content"))
        cuerpo = re.sub(r"submitted by|/u/\S+|to r/\S+|\[link\]|\[comments\]", " ", cuerpo)
        cuerpo = re.sub(r"\s+", " ", cuerpo).strip()
        categoria = e.find(f"{ATOM}category")
        sub = categoria.get("term") if categoria is not None else "reddit"
        items.append({
            "id": _id("reddit", e.findtext(f"{ATOM}id") or url), "tipo": "social", "fuente": f"r/{sub}",
            "autor": limpiar(e.findtext(f"{ATOM}author/{ATOM}name")), "titulo": titulo,
            "texto": cuerpo[:1200], "url": url,
            "fecha": _fecha(e.findtext(f"{ATOM}published") or e.findtext(f"{ATOM}updated")),
            "simbolos": _mencionados(f"{titulo} {cuerpo}", tickers), "sentimiento": None, "interaccion": 0,
        })
    return items


def _mencionados(texto, tickers):
    return [simbolo for corto, simbolo in tickers.items()
            if re.search(rf"(?<![A-Za-z0-9])\$?{re.escape(corto)}(?![A-Za-z0-9])", texto)]


def simbolo_social(posicion):
    """Ticker corto: BTC-USD -> BTC, SAN.MC -> SAN."""
    return re.split(r"[-.=]", posicion["simbolo"])[0]


def _stocktwits(pos):
    corto = simbolo_social(pos)
    ticker = f"{corto}.X" if pos["tipo"] == "cripto" else corto
    datos_json = json.loads(pedir(f"https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"))
    items = []
    for m in datos_json.get("messages", []):
        cuerpo = limpiar(m.get("body"))
        usuario = m.get("user") or {}
        items.append({
            "id": _id("st", str(m["id"])), "tipo": "social", "fuente": "StockTwits",
            "autor": usuario.get("username"), "titulo": cuerpo[:140], "texto": cuerpo[:1000],
            "url": f"https://stocktwits.com/{usuario.get('username')}/message/{m['id']}",
            "fecha": _fecha(m.get("created_at")), "simbolos": [pos["simbolo"]],
            "sentimiento": ((m.get("entities") or {}).get("sentiment") or {}).get("basic"),
            "interaccion": (m.get("likes") or {}).get("total", 0),
        })
    return items


def _x(token, posiciones):
    tickers = {simbolo_social(p): p["simbolo"] for p in posiciones}
    consulta = "(" + " OR ".join(f"${t}" for t in tickers) + ") -is:retweet lang:en"
    url = "https://api.x.com/2/tweets/search/recent?" + urlencode({
        "query": consulta[:512], "max_results": 25, "tweet.fields": "created_at,public_metrics",
        "expansions": "author_id", "user.fields": "username",
    })
    datos_json = json.loads(pedir(url, {"Authorization": f"Bearer {token}"}))
    usuarios = {u["id"]: u["username"] for u in datos_json.get("includes", {}).get("users", [])}
    items = []
    for t in datos_json.get("data", []):
        texto = limpiar(t.get("text"))
        metricas = t.get("public_metrics") or {}
        autor = usuarios.get(t.get("author_id"), "desconocido")
        items.append({
            "id": _id("x", t["id"]), "tipo": "social", "fuente": "X", "autor": autor,
            "titulo": texto[:140], "texto": texto, "url": f"https://x.com/{autor}/status/{t['id']}",
            "fecha": _fecha(t.get("created_at")), "simbolos": _mencionados(texto, tickers),
            "sentimiento": None,
            "interaccion": metricas.get("like_count", 0) + metricas.get("retweet_count", 0),
        })
    return items


def _lanzar(tareas):
    """Ejecuta (nombre, función) en paralelo: una fuente caída no tumba las demás."""
    items, avisos = [], []

    def correr(tarea):
        nombre, funcion = tarea
        try:
            return funcion(), None
        except Exception as e:
            return [], f"{nombre}: {e}"

    with ThreadPoolExecutor(8) as pool:
        for resultado, aviso in pool.map(correr, tareas):
            items.extend(resultado)
            if aviso:
                avisos.append(aviso)
    return items, avisos


def _unir(items):
    unicos = {}
    limite = time.time() - MAX_DIAS * 86400
    for it in items:
        if it["fecha"] < limite:
            continue
        previo = unicos.get(it["id"])
        if previo:
            previo["simbolos"] = sorted(set(previo["simbolos"]) | set(it["simbolos"]))
            previo["texto"] = previo["texto"] or it["texto"]
        else:
            unicos[it["id"]] = it
    return list(unicos.values())


def nombre_corto(nombre):
    # "Hyperliquid Strategies Inc." o "Bitcoin USD": con el sufijo entre comillas, Google casi no encuentra nada.
    return re.sub(r"[,.]?\s+(Inc|Corp|Corporation|Ltd|plc|S\.?A|SE|AG|NV|Co|USD|EUR)\.?$", "", nombre, flags=re.I).strip()


def _tareas_activo(simbolo, nombre, cripto, dias):
    consulta = f'"{nombre_corto(nombre)}" {"crypto" if cripto else "stock"} when:{dias}d'
    return [
        (f"Yahoo {simbolo}", lambda: _rss(
            pedir(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={quote_plus(simbolo)}&region=US&lang=en-US"),
            "Yahoo Finance", [simbolo])),
        (f"Google {simbolo}", lambda: _rss(pedir(google(consulta)), None, [simbolo])),
    ]


def actualizar_noticias():
    posiciones = datos.posiciones()
    tareas = [
        (fuente or "Google News", lambda f=fuente, u=url: _rss(pedir(u), f, []))
        for fuente, url in GENERALES
    ]
    for p in posiciones:
        tareas += _tareas_activo(p["simbolo"], p["nombre"], p["tipo"] == "cripto", 3)
    items, avisos = _lanzar(tareas)
    return {"nuevos": datos.guardar_items(_unir(items)), "avisos": avisos}


def del_activo(simbolo, nombre, cripto):
    """Titulares de un activo buscados al momento, sin guardarlos: sirve también para los que no están en
    la cartera, que el feed no sigue."""
    items, _ = _lanzar(_tareas_activo(simbolo, nombre, cripto, 7))
    return sorted(_unir(items), key=lambda it: -it["fecha"])


def actualizar_social(incluir_x=False):
    posiciones = datos.posiciones()
    tickers = {simbolo_social(p): p["simbolo"] for p in posiciones}
    subs = SUBREDDITS + (["CryptoCurrency"] if any(p["tipo"] == "cripto" for p in posiciones) else [])
    # Reddit corta (429) la segunda petición seguida: todos los subreddits van en una sola URL.
    tareas = [("Reddit", lambda: _reddit(
        pedir(f"https://www.reddit.com/r/{'+'.join(subs)}/hot.rss?limit=60"), tickers))]
    tareas += [(f"StockTwits {p['simbolo']}", lambda p=p: _stocktwits(p)) for p in posiciones]
    token = datos.ajustes()["x_token"]
    if incluir_x and token and posiciones:
        tareas.append(("X", lambda: _x(token, posiciones)))
    items, avisos = _lanzar(tareas)
    return {"nuevos": datos.guardar_items(_unir(items)), "avisos": avisos}


class _Parrafos(HTMLParser):
    IGNORAR = {"script", "style", "nav", "footer", "aside", "form", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.dentro = 0
        self.ignorando = 0
        self.partes = []

    def handle_starttag(self, tag, attrs):
        if tag in self.IGNORAR:
            self.ignorando += 1
        elif tag == "p":
            self.dentro += 1

    def handle_endtag(self, tag):
        if tag in self.IGNORAR:
            self.ignorando = max(0, self.ignorando - 1)
        elif tag == "p":
            self.dentro = max(0, self.dentro - 1)

    def handle_data(self, data):
        if self.dentro and not self.ignorando and data.strip():
            self.partes.append(data.strip())


def _url_publica(url):
    p = urlparse(url)
    if p.scheme != "https" or not p.hostname or p.hostname == "localhost":
        return False
    try:
        ipaddress.ip_address(p.hostname)
        return False
    except ValueError:
        return True


def texto_articulo(url, maximo=3000):
    """Cuerpo del artículo si la web lo deja leer; si no, el agente trabaja con el RSS."""
    host = urlparse(url).hostname or ""
    if "news.google.com" in host or "reddit.com" in host or not _url_publica(url):
        return ""
    try:
        contenido = pedir(url, timeout=6)[:800_000].decode("utf-8", "ignore")
    except Exception:
        return ""
    lector = _Parrafos()
    try:
        lector.feed(contenido)
    except Exception:
        return ""
    return re.sub(r"\s+", " ", " ".join(lector.partes))[:maximo]
