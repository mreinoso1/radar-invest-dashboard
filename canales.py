"""Por dónde llegan las alertas: notificación de Windows, Telegram y ntfy.

El texto de una alerta puede venir de un titular de internet. Por eso nunca se pega dentro de un comando:
a PowerShell le llega en una variable de entorno, escapado como XML, y a Telegram y ntfy, como JSON.
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from xml.sax.saxutils import escape

# La notificación se muestra a nombre de PowerShell, que ya está registrado en Windows: así no hace falta
# instalar nada ni registrar Radar como aplicación.
APP_ID = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"
SCRIPT_WINDOWS = f"""$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($env:RADAR_AVISO)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{APP_ID}').Show([Windows.UI.Notifications.ToastNotification]::new($xml))"""
MINIMO = "Radar tiene una alerta nueva. Ábrela en Radar para verla."


class ErrorCanal(Exception):
    pass


def xml_windows(titulo, texto):
    return (f'<toast><visual><binding template="ToastGeneric"><text>{escape(titulo[:120])}</text>'
            f"<text>{escape(texto[:400])}</text></binding></visual></toast>")


def windows(titulo, texto):
    if sys.platform != "win32":
        raise ErrorCanal("Las notificaciones de Windows solo funcionan en Windows")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", SCRIPT_WINDOWS],
                       env={**os.environ, "RADAR_AVISO": xml_windows(titulo, texto)},
                       capture_output=True, text=True, timeout=20,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode:
        raise ErrorCanal(f"PowerShell no pudo mostrar la notificación: {(r.stderr or '').strip()[:200]}")


def _post_json(url, cuerpo, secreto=""):
    peticion = urllib.request.Request(url, data=json.dumps(cuerpo).encode(), method="POST",
                                      headers={"Content-Type": "application/json", "User-Agent": "Radar/1.0"})
    try:
        with urllib.request.urlopen(peticion, timeout=15) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        mensaje = f"respondió {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"
    except (urllib.error.URLError, TimeoutError) as e:
        mensaje = f"no se pudo conectar: {getattr(e, 'reason', e)}"
    # El token va en la URL de Telegram: que nunca acabe en un mensaje de error que se guarda o se enseña.
    raise ErrorCanal(mensaje.replace(secreto, "***") if secreto else mensaje)


def peticion_telegram(token, chat, titulo, texto):
    """(url, cuerpo) de un mensaje de Telegram. Aparte para poder comprobarlo sin enviarlo."""
    return f"https://api.telegram.org/bot{token}/sendMessage", {
        "chat_id": chat, "text": f"{titulo}\n\n{texto}", "disable_web_page_preview": True}


def telegram(token, chat, titulo, texto):
    if not token or not chat:
        raise ErrorCanal("Falta el token del bot o tu chat id")
    _post_json(*peticion_telegram(token, chat, titulo, texto), secreto=token)


def peticion_ntfy(servidor, tema, titulo, texto, urgente):
    # Publicar en JSON en la raíz del servidor admite acentos en el título, cosa que una cabecera no.
    return servidor.rstrip("/"), {"topic": tema, "title": titulo, "message": texto, "priority": 4 if urgente else 3,
                                  "tags": ["chart_with_upwards_trend"]}


def ntfy(servidor, tema, titulo, texto, urgente=False):
    if not tema:
        raise ErrorCanal("Falta el tema de ntfy")
    _post_json(*peticion_ntfy(servidor or "https://ntfy.sh", tema, titulo, texto, urgente), secreto=tema)


def activos(cfg):
    return [c for c in ("windows", "telegram", "ntfy") if cfg.get(f"alertas_{c}")]


def enviar(alerta, cfg, canales=None):
    """Envía una alerta por los canales activos. Devuelve {canal: "ok" o el error}: un canal que falla no
    impide los demás."""
    titulo, texto = alerta["titulo"], alerta["texto"]
    # Lo que sale del ordenador puede ir sin activos ni precios, si el usuario lo prefiere.
    fuera = ("Radar", MINIMO) if cfg.get("alertas_minimas") else (titulo, texto)
    resultado = {}
    for canal in canales or activos(cfg):
        try:
            if canal == "windows":
                windows(titulo, texto)
            elif canal == "telegram":
                telegram(cfg.get("telegram_token"), cfg.get("telegram_chat"), *fuera)
            elif canal == "ntfy":
                ntfy(cfg.get("ntfy_servidor"), cfg.get("ntfy_tema"), *fuera, urgente=bool(alerta.get("urgente")))
            resultado[canal] = "ok"
        except (ErrorCanal, OSError, subprocess.SubprocessError) as e:
            resultado[canal] = str(e)
    return resultado
