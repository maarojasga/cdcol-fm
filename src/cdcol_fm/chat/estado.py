"""Lo que el servidor guarda entre peticiones: conversaciones, imágenes del mapa y cuotas.

En local vive en memoria y en una carpeta temporal. En Lambda cada petición puede caer en una
instancia distinta, así que vive en S3 (``CDCOL_ESTADO=s3://<bucket>``), bajo ``conversaciones/``,
``imagenes/`` y ``cuotas/``; el bucket los expira (ADR 0006).
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cdcol_fm.chat.agente import Conversacion
from cdcol_fm.chat.herramientas import CARPETA_IMAGENES


def a_json(contenido: Any) -> Any:
    """Bloques de la API (objetos del SDK) → dicts, tal cual, para guardarlos y reenviarlos."""
    if isinstance(contenido, list):
        return [a_json(b) for b in contenido]
    if hasattr(contenido, "model_dump"):
        return contenido.model_dump(mode="json", exclude_none=True)
    return contenido


class EstadoLocal:
    def __init__(self) -> None:
        self._conversaciones: dict[tuple[str, str], Conversacion] = {}
        self._cuotas: dict[tuple[str, str], int] = {}
        self._candado = threading.Lock()

    def conversacion(self, usuario: str, id_conv: str) -> Conversacion:
        with self._candado:
            return self._conversaciones.setdefault((usuario, id_conv), Conversacion())

    def guardar(self, usuario: str, id_conv: str, conv: Conversacion) -> None:
        pass  # en memoria ya quedó

    def contar_pregunta(self, usuario: str) -> int:
        with self._candado:
            clave = (usuario, _hoy())
            self._cuotas[clave] = self._cuotas.get(clave, 0) + 1
            return self._cuotas[clave]

    def url_imagen(self, relativa: str) -> str:
        return f"/api/imagen/{relativa}"


class EstadoS3:
    def __init__(self, uri: str, cliente: Any = None) -> None:
        from cdcol_fm.nube import partir_uri

        self.bucket, prefijo = partir_uri(uri)
        self.prefijo = f"{prefijo}/" if prefijo else ""
        if cliente is None:
            import boto3  # type: ignore[import-untyped]

            cliente = boto3.client("s3")
        self.s3 = cliente

    def _leer(self, clave: str) -> Any:
        try:
            cuerpo = self.s3.get_object(Bucket=self.bucket, Key=self.prefijo + clave)["Body"]
        except self.s3.exceptions.NoSuchKey:
            return None
        return json.loads(cuerpo.read())

    def _escribir(self, clave: str, datos: Any) -> None:
        self.s3.put_object(
            Bucket=self.bucket, Key=self.prefijo + clave,
            Body=json.dumps(datos, ensure_ascii=False).encode(), ContentType="application/json",
        )

    def conversacion(self, usuario: str, id_conv: str) -> Conversacion:
        mensajes = self._leer(f"conversaciones/{usuario}/{id_conv}.json")
        return Conversacion(mensajes or [])

    def guardar(self, usuario: str, id_conv: str, conv: Conversacion) -> None:
        mensajes = [{**m, "content": a_json(m["content"])} for m in conv.mensajes]
        self._escribir(f"conversaciones/{usuario}/{id_conv}.json", mensajes)

    def contar_pregunta(self, usuario: str) -> int:
        # leer y escribir no es atómico: dos preguntas simultáneas pueden contar una. Para un
        # grupo pequeño basta; el freno duro es el límite de gasto de la cuenta de Anthropic
        clave = f"cuotas/{_hoy()}/{usuario}.json"
        n = (self._leer(clave) or 0) + 1
        self._escribir(clave, n)
        return n

    def url_imagen(self, relativa: str) -> str:
        clave = f"{self.prefijo}imagenes/{relativa}"
        try:
            self.s3.head_object(Bucket=self.bucket, Key=clave)
        except Exception:  # no está: se sube desde /tmp de esta instancia
            self.s3.upload_file(str(Path(CARPETA_IMAGENES, relativa)), self.bucket, clave,
                                ExtraArgs={"ContentType": "image/png"})
        return str(self.s3.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": clave}, ExpiresIn=3600
        ))


def _hoy() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")
