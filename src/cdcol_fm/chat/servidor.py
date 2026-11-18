"""Servidor de la página (``cdcol web``): la API del chat y del visor, y en local también ``web/``.

En local escucha en 127.0.0.1, sin inicio de sesión, y guarda todo en memoria. En AWS el mismo
servidor corre en Lambda con el adaptador web (ADR 0006): exige el token de Cognito
(``CDCOL_AUTH=cognito``), guarda el estado en S3 (``CDCOL_ESTADO``) y limita las preguntas por
persona y día (``CDCOL_CUOTA_DIARIA``).
"""

from __future__ import annotations

import json
import mimetypes
import os
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from cdcol_fm.chat.agente import responder
from cdcol_fm.chat.datos import Almacen
from cdcol_fm.chat.estado import EstadoLocal, EstadoS3
from cdcol_fm.chat.herramientas import CARPETA_IMAGENES, ErrorHerramienta, esquinas, mapa
from cdcol_fm.config import RAIZ_CONFIG

CARPETA_WEB = RAIZ_CONFIG.parent / "web"
USUARIO_LOCAL = "local"


class NoAutorizado(Exception):
    pass


class Cognito:
    """Valida el token de acceso con GetUser: Cognito revisa firma, vencimiento y revocación."""

    def __init__(self, cliente: Any = None) -> None:
        if cliente is None:
            import boto3  # type: ignore[import-untyped]

            cliente = boto3.client("cognito-idp")
        self.cliente = cliente
        self._cache: dict[str, tuple[str, float]] = {}

    def usuario(self, cabecera: str | None) -> str:
        if not cabecera or not cabecera.startswith("Bearer "):
            raise NoAutorizado("falta el token de acceso")
        token = cabecera.removeprefix("Bearer ").strip()
        guardado = self._cache.get(token)
        if guardado and guardado[1] > time.monotonic():
            return guardado[0]
        try:
            r = self.cliente.get_user(AccessToken=token)
        except Exception as e:  # token vencido, revocado o ajeno
            raise NoAutorizado("sesión vencida o inválida; vuelve a entrar") from e
        atributos = {a["Name"]: a["Value"] for a in r.get("UserAttributes", [])}
        usuario = atributos.get("email", r["Username"])
        # 5 min: el mapa pide muchas imágenes y cada GetUser es una llamada a Cognito
        self._cache[token] = (usuario, time.monotonic() + 300)
        return usuario


def zonas(almacen: Almacen) -> list[dict[str, Any]]:
    """Zonas con datos y, por bloque, sus meses y su contorno (para dibujarlos en el mapa)."""
    return [
        {"zona": z, "bloques": [
            {"id": b, "meses": almacen.meses(z, b), "esquinas": esquinas(b, z)}
            for b in almacen.bloques(z)
        ]}
        for z in almacen.zonas()
    ]


def _dentro(base: Path, relativa: str) -> Path | None:
    ruta = (base / relativa).resolve()
    return ruta if ruta.is_file() and ruta.is_relative_to(base.resolve()) else None


def _publicar(figura: dict[str, Any], estado: Any) -> dict[str, Any]:
    if figura.get("tipo") == "mapa":
        for pieza in figura["piezas"]:
            pieza["url"] = estado.url_imagen(pieza["imagen"])
    return figura


def crear_servidor(
    almacen: Almacen,
    puerto: int = 8000,
    cliente: Any = None,
    estado: Any = None,
    autenticacion: Any = None,
    cuota_diaria: int | None = None,
) -> ThreadingHTTPServer:
    """``autenticacion=None`` deja entrar a todos (solo para 127.0.0.1)."""
    estado = estado or EstadoLocal()

    class Manejador(BaseHTTPRequestHandler):
        def _enviar(self, codigo: int, cuerpo: bytes, tipo: str) -> None:
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

        def _json(self, datos: Any, codigo: int = 200) -> None:
            self._enviar(codigo, json.dumps(datos, ensure_ascii=False).encode(), "application/json")

        def _archivo(self, ruta: Path | None) -> None:
            if ruta is None:
                self._json({"error": "no existe"}, 404)
                return
            tipo = mimetypes.guess_type(ruta.name)[0] or "application/octet-stream"
            self._enviar(200, ruta.read_bytes(), tipo)

        def _usuario(self) -> str:
            if autenticacion is None:
                return USUARIO_LOCAL
            return str(autenticacion.usuario(self.headers.get("Authorization")))

        def do_GET(self) -> None:  # noqa: N802 (nombre que exige http.server)
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                if not url.path.startswith("/api/"):
                    relativa = url.path.lstrip("/") or "index.html"
                    self._archivo(_dentro(CARPETA_WEB, relativa))
                    return
                if url.path.startswith("/api/imagen/"):  # en local; en S3 van firmadas
                    self._archivo(_dentro(CARPETA_IMAGENES, url.path.removeprefix("/api/imagen/")))
                    return
                self._usuario()
                if url.path == "/api/zonas":
                    self._json(zonas(almacen))
                elif url.path == "/api/mapa":
                    bloques = [b for b in q.get("bloques", "").split(",") if b] or None
                    _, figura = mapa(almacen, q["zona"], q["capa"], q["mes"], bloques)
                    self._json(_publicar(figura or {}, estado))
                else:
                    self._json({"error": "no existe"}, 404)
            except NoAutorizado as e:
                self._json({"error": str(e)}, 401)
            except (ErrorHerramienta, KeyError) as e:
                self._json({"error": str(e)}, 400)

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/api/chat":
                self._json({"error": "no existe"}, 404)
                return
            try:
                usuario = self._usuario()
            except NoAutorizado as e:
                self._json({"error": str(e)}, 401)
                return
            largo = int(self.headers.get("Content-Length", 0))
            pedido = json.loads(self.rfile.read(largo) or b"{}")
            pregunta = (pedido.get("pregunta") or "").strip()
            if not pregunta:
                self._json({"error": "falta la pregunta"}, 400)
                return
            if len(pregunta) > 2000:
                self._json({"error": "la pregunta es muy larga (máximo 2000 caracteres)"}, 400)
                return
            if cuota_diaria and estado.contar_pregunta(usuario) > cuota_diaria:
                self._json({"error": f"llegaste al máximo de {cuota_diaria} preguntas por día"}, 429)
                return
            id_conv = pedido.get("conversacion") or uuid.uuid4().hex
            if not id_conv.isalnum():
                self._json({"error": "conversación inválida"}, 400)
                return
            conv = estado.conversacion(usuario, id_conv)
            try:
                r = responder(conv, pregunta, almacen, pedido.get("zona"),
                              pedido.get("bloques") or None, cliente)
            except Exception as e:  # el error de la API (llave, cuota, red) se muestra en la página
                self._json({"error": f"{type(e).__name__}: {e}"}, 502)
                return
            estado.guardar(usuario, id_conv, conv)
            figuras = [_publicar(f, estado) for f in r.figuras]
            self._json({"conversacion": id_conv, "texto": r.texto, "pasos": r.pasos,
                        "figuras": figuras, "uso": r.uso})

        def log_message(self, formato: str, *args: Any) -> None:
            pass  # sin una línea por cada imagen del mapa

    return ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)


def servidor_de_entorno(almacen: Almacen, puerto: int) -> ThreadingHTTPServer:
    """Configuración por variables de entorno (la que usa Lambda); sin ellas, la local."""
    uri_estado = os.environ.get("CDCOL_ESTADO")
    estado = EstadoS3(uri_estado) if uri_estado else EstadoLocal()
    autenticacion = Cognito() if os.environ.get("CDCOL_AUTH") == "cognito" else None
    cuota = int(os.environ["CDCOL_CUOTA_DIARIA"]) if os.environ.get("CDCOL_CUOTA_DIARIA") else None
    return crear_servidor(almacen, puerto, estado=estado, autenticacion=autenticacion,
                          cuota_diaria=cuota)
