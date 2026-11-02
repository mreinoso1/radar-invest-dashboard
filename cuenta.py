"""Conexión con la cuenta de Claude del usuario a través de Claude Code.

Radar nunca ve ni guarda credenciales: lanza el claude.exe oficial, sin modificar, y el
inicio de sesión se completa en el flujo de Anthropic. Así el análisis gasta los límites
del plan y no hace falta clave de API.
"""
import glob
import json
import os
import shutil
import subprocess
import time

import datos

ESPERA_ANALISIS = 600
_cache = (0.0, None)


class ErrorCuenta(Exception):
    pass


def ejecutable():
    """El de PATH o, si no, el más reciente que trae la app de escritorio de Claude."""
    en_path = shutil.which("claude")
    if en_path:
        return en_path
    patron = os.path.join(os.environ.get("APPDATA", ""), "Claude", "claude-code", "*", "*", "claude.exe")
    return max(glob.glob(patron), key=os.path.getmtime, default=None)


def _entorno():
    # Una ANTHROPIC_API_KEY en el entorno ganaría al plan y se cobraría aparte.
    prefijos = ("ANTHROPIC_", "CLAUDE_CODE_", "CLAUDE_AGENT_", "CLAUDECODE")
    return {k: v for k, v in os.environ.items() if not k.startswith(prefijos)}


def estado(forzar=False):
    global _cache
    if not forzar and _cache[1] and time.time() - _cache[0] < 30:
        return _cache[1]
    exe = ejecutable()
    resultado = {"instalado": bool(exe), "conectado": False, "plan": None}
    if exe:
        try:
            r = subprocess.run([exe, "auth", "status"], capture_output=True, text=True, encoding="utf-8",
                               env=_entorno(), cwd=datos.DATOS, timeout=20)
            info = json.loads(r.stdout)
            resultado.update(conectado=bool(info.get("loggedIn")), plan=info.get("subscriptionType"))
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    _cache = (time.time(), resultado)
    return resultado


def iniciar_sesion():
    """Abre el inicio de sesión oficial en su propia ventana."""
    exe = ejecutable()
    if not exe:
        raise ErrorCuenta("No encuentro Claude Code en este ordenador.")
    subprocess.Popen([exe, "auth", "login"], env=_entorno(), cwd=datos.DATOS,
                     creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))


def preguntar(sistema, contenido, esquema, modelo, esfuerzo="high"):
    """Devuelve el JSON del esquema o, sin esquema, el texto de la respuesta."""
    exe = ejecutable()
    if not exe:
        raise ErrorCuenta("No encuentro Claude Code en este ordenador.")
    # Los textos vienen de internet, así que el agente va sin herramientas, MCP ni ajustes
    # del usuario: lo peor que puede hacer una noticia maliciosa es falsear su propio análisis.
    orden = [
        exe, "-p", "--output-format", "json", "--tools", "", "--strict-mcp-config",
        "--mcp-config", '{"mcpServers":{}}', "--setting-sources", "", "--disable-slash-commands",
        "--no-session-persistence", "--model", modelo, "--effort", esfuerzo, "--max-turns", "4",
        "--system-prompt", sistema,
    ]
    if esquema:
        orden += ["--json-schema", json.dumps(esquema)]
    try:
        r = subprocess.run(orden, input=contenido, capture_output=True, text=True, encoding="utf-8",
                           env=_entorno(), cwd=datos.DATOS, timeout=ESPERA_ANALISIS)
    except subprocess.TimeoutExpired:
        raise ErrorCuenta("Claude tardó demasiado en responder.")
    try:
        salida = json.loads(r.stdout)
    except ValueError:
        raise ErrorCuenta(f"Claude Code falló: {(r.stderr or r.stdout)[-300:]}")
    if salida.get("is_error"):
        raise ErrorCuenta(_traducir(str(salida.get("result") or salida.get("subtype"))))
    if not esquema:
        return str(salida.get("result") or "")
    if not isinstance(salida.get("structured_output"), dict):
        raise ErrorCuenta("Claude no devolvió un análisis válido en este lote.")
    return salida["structured_output"]


def _traducir(mensaje):
    bajo = mensaje.lower()
    if "not logged in" in bajo or "/login" in bajo:
        global _cache
        _cache = (0.0, None)
        return "No has iniciado sesión con tu cuenta de Claude. Hazlo en Ajustes."
    if "limit" in bajo:
        return f"Has llegado a un límite de tu plan de Claude: {mensaje[:160]}"
    return mensaje[:300]
