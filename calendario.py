"""Calendario: lo que va a pasar y conviene saber antes.

- Resultados de empresas: Yahoo (calendarEvents), para tu cartera y tu watchlist.
- Decisiones de la Fed: su página oficial del calendario del FOMC.
- IPC, empleo, PIB y PCE: la API oficial de FRED, si tienes su clave gratuita. La web del BLS rechaza
  programas, y no se intenta saltar ese bloqueo.
- Eventos que añades tú, por ejemplo desbloqueos de tokens: no hay una fuente gratuita y fiable de ellos.
"""
import json
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

import datos
import marcador
import mercado

FED_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
FRED_URL = "https://api.stlouisfed.org/fred/release/dates"
FRED_PUBLICACIONES = {10: "IPC de EE. UU.", 50: "Empleo de EE. UU. (nóminas)", 53: "PIB de EE. UU.",
                      54: "Gasto personal y PCE de EE. UU."}
MESES = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                     "dec"], 1)}
UA = "Radar/1.0 (app local de mercado)"  # se presenta como lo que es
HORAS_CACHE = 6


class ErrorCalendario(Exception):
    pass


def _verano_eeuu(dia):
    """Horario de verano de EE. UU.: del segundo domingo de marzo al primer domingo de noviembre."""
    domingo = lambda d: d + timedelta(days=(6 - d.weekday()) % 7)
    return domingo(date(dia.year, 3, 8)) <= dia < domingo(date(dia.year, 11, 1))


def hora_nueva_york(anio, mes, dia, hora, minuto=0):
    """Timestamp de una hora de Nueva York, donde se publican los datos de EE. UU."""
    try:
        from zoneinfo import ZoneInfo
        return int(datetime(anio, mes, dia, hora, minuto, tzinfo=ZoneInfo("America/New_York")).timestamp())
    except Exception:  # Python sin base de zonas horarias: se aplica la regla a mano
        desfase = 4 if _verano_eeuu(date(anio, mes, dia)) else 5
        return int(datetime(anio, mes, dia, hora, minuto, tzinfo=timezone.utc).timestamp()) + desfase * 3600


def _pedir(url, secreto=""):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=15) as r:
            return r.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError) as e:
        mensaje = str(getattr(e, "reason", e))
        raise ErrorCalendario(mensaje.replace(secreto, "***") if secreto else mensaje)


def reuniones_fed(html):
    """Decisiones del FOMC: el último día de cada reunión a las 14:00 de Nueva York. "*" = con proyecciones."""
    salida = []
    for bloque in re.split(r"(?=\d{4} FOMC Meetings)", html):
        anio = re.match(r"(\d{4}) FOMC Meetings", bloque)
        if not anio:
            continue
        for mes, dias in re.findall(r'fomc-meeting__month[^"]*"><strong>([^<]+)</strong></div>\s*'
                                    r'<div class="fomc-meeting__date[^"]*">([^<]+)</div>', bloque):
            # "Apr/May" con "30-1": la decisión es el último día, en el segundo mes.
            numero = MESES.get(mes.split("/")[-1].strip().lower()[:3])
            dia = re.findall(r"\d+", dias)
            if numero and dia:
                salida.append({"fecha": hora_nueva_york(int(anio.group(1)), numero, int(dia[-1]), 14),
                               "proyecciones": "*" in dias})
    if not salida:
        raise ErrorCalendario("la web de la Fed ha cambiado de formato y no se encuentran las reuniones")
    return salida


def fechas_fred(respuesta, id_publicacion):
    """Fechas de una publicación de FRED. Salen a las 8:30 de Nueva York."""
    salida = []
    for f in json.loads(respuesta).get("release_dates", []):
        anio, mes, dia = map(int, f["date"].split("-"))
        salida.append({"id": f"fred:{id_publicacion}:{f['date']}", "tipo": "macro", "simbolo": None,
                       "titulo": FRED_PUBLICACIONES[id_publicacion], "fecha": hora_nueva_york(anio, mes, dia, 8, 30)})
    return salida


def _fred(clave):
    hoy = date.today().isoformat()
    eventos = []
    for id_publicacion in FRED_PUBLICACIONES:
        url = FRED_URL + "?" + urlencode({"release_id": id_publicacion, "api_key": clave, "file_type": "json",
                                          "realtime_start": hoy, "include_release_dates_with_no_data": "true",
                                          "sort_order": "asc", "limit": 12})
        eventos += fechas_fred(_pedir(url, secreto=clave), id_publicacion)
    return eventos


def _fed():
    return [{"id": f"fed:{r['fecha']}", "tipo": "fed", "simbolo": None, "fecha": r["fecha"],
             "titulo": "Decisión de tipos de la Fed" + (" con proyecciones" if r["proyecciones"] else "")}
            for r in reuniones_fed(_pedir(FED_URL))]


def _resultados(simbolos):
    def uno(s):
        c = mercado.consenso(s)
        t = c and c.get("proximos_resultados")
        return {"id": f"res:{s}:{t}", "tipo": "resultados", "simbolo": s, "titulo": f"Resultados de {s}",
                "fecha": t} if t else None

    with ThreadPoolExecutor(6) as pool:
        return [e for e in pool.map(uno, [s for s in simbolos if not marcador.es_cripto(s)]) if e]


def _automaticos(simbolos, clave_fred):
    eventos, errores = [], []
    fuentes = [("resultados", lambda: _resultados(simbolos)), ("la Fed", _fed)]
    if clave_fred:
        fuentes.append(("FRED", lambda: _fred(clave_fred)))
    for nombre, fuente in fuentes:  # una fuente que falla no tapa las demás
        try:
            eventos += fuente()
        except (ErrorCalendario, ValueError, KeyError) as e:
            errores.append(f"No se pudo leer {nombre}: {e}")
    return eventos, errores


def proximos(simbolos, ahora=None, dias=14):
    """(eventos, errores) de los próximos días. Lo automático se lee como mucho cada pocas horas; los
    eventos manuales, siempre."""
    ahora = ahora or time.time()
    clave = datos.ajustes()["fred_key"]
    eventos, errores = mercado._cacheado(("calendario", tuple(sorted(simbolos)), bool(clave)), HORAS_CACHE * 3600,
                                         lambda: _automaticos(simbolos, clave))
    manuales = [{"id": f"man:{e['id']}", "tipo": "manual", "simbolo": e["simbolo"], "titulo": e["titulo"],
                 "fecha": e["fecha"], "evento_id": e["id"]} for e in datos.eventos(int(ahora) - 86400)]
    dentro = [e for e in eventos + manuales if ahora - 3600 <= e["fecha"] <= ahora + dias * 86400]
    return sorted(dentro, key=lambda e: e["fecha"]), errores
