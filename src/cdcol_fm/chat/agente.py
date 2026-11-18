"""El bucle de conversación: Claude decide qué herramientas llamar y responde con sus números.

La conversación se guarda tal cual vuelve de la API (bloques de razonamiento incluidos) y solo se
le agregan turnos al final: así se reaprovecha la caché del prompt y el modelo no rechaza el
historial por editado.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from cdcol_fm.chat.datos import Almacen
from cdcol_fm.chat.herramientas import HERRAMIENTAS, ErrorHerramienta, definiciones, ejecutar

MODELO = "claude-opus-5-5"
MAX_VUELTAS = 10  # llamadas al modelo por pregunta; corta un bucle de herramientas que no acaba

SISTEMA = """\
Eres el asistente del cubo de datos cdcol-fm (Universidad de los Andes). Respondes preguntas sobre \
imágenes satelitales ya procesadas de zonas de Colombia, en español, para investigadores.

Los datos son el producto ard_s1s2_mensual: un compuesto por mes en bloques de 10,24 km de la \
grilla nacional (EPSG:9377, píxeles de 10 m). Cada mes trae Sentinel-2 (mediana de las \
observaciones sin nube, 10 bandas) y Sentinel-1 (radar VV y VH en dB, corregido por relieve), \
más capas de calidad: observaciones ópticas limpias, porcentaje de nube, días desde la última \
vista clara, dispersión óptica y adquisiciones de radar.

Cómo responder:
- Todo número sale de una herramienta; no inventes ni estimes valores que no consultaste.
- En el trópico la nube manda: antes de concluir algo con variables ópticas, revisa la calidad de \
esos meses y dilo si el dato no es confiable. El radar sirve cuando el óptico falla.
- Di qué meses y cuántos bloques usaste. Si la pregunta pide algo que estos datos no pueden \
responder (por ejemplo, cuánto bosque hay: no hay un clasificador validado), dilo y ofrece lo \
más cercano que sí se puede medir, aclarando que es una aproximación.
- Cuando una imagen ayude, usa la herramienta mapa: la página la muestra sobre el mapa.
- Respuestas breves: párrafos cortos y viñetas, sin tablas ni títulos.
"""


@dataclass
class Conversacion:
    mensajes: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Respuesta:
    texto: str
    pasos: list[dict[str, Any]]  # cada llamada a herramienta, con su entrada y su salida
    figuras: list[dict[str, Any]]
    uso: dict[str, int]


def _cliente() -> Any:
    import anthropic

    return anthropic.Anthropic()


def _contexto(zona: str | None, bloques: list[str] | None, pregunta: str) -> str:
    if not zona:
        return pregunta
    seleccion = f"bloques {', '.join(bloques)}" if bloques else "todos sus bloques"
    return f"[Selección en el mapa: zona {zona}, {seleccion}]\n\n{pregunta}"


def _con_seleccion(
    nombre: str, entrada: dict[str, Any], zona: str | None, bloques: list[str] | None
) -> dict[str, Any]:
    """Lo que el modelo omite se toma de la selección del mapa (así lo dicen las herramientas)."""
    if nombre not in HERRAMIENTAS:
        return entrada
    propiedades = HERRAMIENTAS[nombre][1]["input_schema"]["properties"]
    completa = dict(entrada)
    if zona and "zona" in propiedades:
        completa.setdefault("zona", zona)
    if bloques and "bloques" in propiedades and completa.get("zona") == zona:
        completa.setdefault("bloques", bloques)
    return completa


def responder(
    conversacion: Conversacion,
    pregunta: str,
    almacen: Almacen,
    zona: str | None = None,
    bloques: list[str] | None = None,
    cliente: Any = None,
) -> Respuesta:
    cliente = cliente or _cliente()
    conversacion.mensajes.append({"role": "user", "content": _contexto(zona, bloques, pregunta)})
    pasos: list[dict[str, Any]] = []
    figuras: list[dict[str, Any]] = []
    uso = {"entrada": 0, "salida": 0, "cache_leida": 0}
    for _ in range(MAX_VUELTAS):
        r = cliente.beta.messages.create(
            model=MODELO,
            max_tokens=16000,
            system=SISTEMA,
            tools=definiciones(),
            messages=conversacion.mensajes,
            betas=["server-side-fallback-2026-07-01"],
            extra_body={
                # si el modelo declina, el servidor reintenta con el respaldo recomendado
                "fallbacks": "default",
                "output_config": {"effort": "medium"},
                "cache_control": {"type": "ephemeral"},
            },
        )
        uso["entrada"] += r.usage.input_tokens
        uso["salida"] += r.usage.output_tokens
        uso["cache_leida"] += getattr(r.usage, "cache_read_input_tokens", 0) or 0
        conversacion.mensajes.append({"role": "assistant", "content": r.content})
        if r.stop_reason == "refusal":
            return Respuesta("No puedo responder esa pregunta. Prueba a formularla de otra manera.",
                             pasos, figuras, uso)
        if r.stop_reason == "pause_turn":
            continue
        usos = [b for b in r.content if b.type == "tool_use"]
        if r.stop_reason != "tool_use" or not usos:
            texto = "\n\n".join(b.text for b in r.content if b.type == "text").strip()
            if r.stop_reason == "max_tokens":
                texto += "\n\n(La respuesta se cortó por largo.)"
            return Respuesta(texto, pasos, figuras, uso)
        resultados = []
        for uso_h in usos:
            entrada = uso_h.input if isinstance(uso_h.input, dict) else json.loads(uso_h.input)
            entrada = _con_seleccion(uso_h.name, entrada, zona, bloques)
            try:
                salida, figura = ejecutar(almacen, uso_h.name, entrada)
                error = False
            except (ErrorHerramienta, FileNotFoundError) as e:
                salida, figura, error = {"error": str(e)}, None, True
            pasos.append({"herramienta": uso_h.name, "entrada": entrada, "salida": salida,
                          "error": error})
            if figura:
                figuras.append(figura)
            resultado = {"type": "tool_result", "tool_use_id": uso_h.id,
                         "content": json.dumps(salida, ensure_ascii=False)}
            if error:
                resultado["is_error"] = True
            resultados.append(resultado)
        # todos los resultados en un solo mensaje, para que siga llamando en paralelo
        conversacion.mensajes.append({"role": "user", "content": resultados})
    return Respuesta("Me quedé sin vueltas antes de terminar; intenta una pregunta más acotada.",
                     pasos, figuras, uso)
