"""Comando ``cdcol``."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from cdcol_fm import __version__
from cdcol_fm.config import cargar_pais, listar_zonas

app = typer.Typer(help="cdcol-fm: cubo de datos con modelos fundacionales.", no_args_is_help=True)


@app.command()
def version() -> None:
    """Versión del paquete."""
    typer.echo(__version__)


@app.command()
def zonas() -> None:
    """Lista las zonas configuradas y su estado."""
    for z in listar_zonas():
        typer.echo(f"{z.id:<16} {z.estado.value:<10} {z.pais:<10} {z.descripcion}")


@app.command("validar-config")
def validar_config() -> None:
    """Valida todos los archivos de config/ (también corre en la CI)."""
    zs = listar_zonas()
    for id_pais in sorted({z.pais for z in zs}):
        cargar_pais(id_pais)
    typer.echo(f"OK: {len(zs)} zonas válidas")


def _pendiente(fase: int) -> None:
    typer.echo(f"Todavía no implementado (fase {fase} del plan).", err=True)
    raise typer.Exit(code=2)


@app.command()
def ard(
    zona: str,
    salida: Annotated[Path, typer.Option(help="Carpeta raíz de los productos")] = Path("data"),
) -> None:
    """Calcula el producto ard_s1s2_mensual con sus capas de incertidumbre."""
    from cdcol_fm.ard.pipeline import construir_ard

    manifiesto = construir_ard(zona, salida, avisar=typer.echo)
    ruta = salida / zona / "manifiesto.json"
    manifiesto.guardar(ruta)
    typer.echo(f"Manifiesto: {ruta}")


@app.command()
def escenas(zona: str) -> None:
    """Cuenta las escenas S2 y S1 de la zona por mes y fecha (para revisar cobertura)."""
    from collections import Counter

    from cdcol_fm.config import cargar_zona
    from cdcol_fm.fuentes.stac import S1_GRD_ES, S1_GRD_PC, S1_RTC, S2_L2A, buscar

    z = cargar_zona(zona)
    for fuente in (S2_L2A, S1_RTC, S1_GRD_PC, S1_GRD_ES):
        items = buscar(fuente, z)
        por_mes = Counter(it.datetime.strftime("%Y-%m") for it in items)
        fechas = sorted({it.datetime.strftime("%m-%d") for it in items})
        conteo = dict(sorted(por_mes.items()))
        typer.echo(f"{fuente.nombre} {fuente.coleccion}: {conteo} fechas={fechas}")


@app.command()
def resumen(
    zona: str,
    salida: Annotated[Path, typer.Option(help="Carpeta raíz de los productos")] = Path("data"),
) -> None:
    """Tabla por mes de las capas de incertidumbre de una zona ya calculada."""
    from cdcol_fm.ard.resumen import resumen_markdown

    typer.echo(resumen_markdown(salida, zona))


@app.command()
def embeber(zona: str, receta: str) -> None:
    """Calcula el producto de embeddings de una receta sobre una zona."""
    _pendiente(2)


@app.command("verificar-linaje")
def verificar_linaje(item: str) -> None:
    """Recalcula una tesela del ítem y compara su hash."""
    _pendiente(2)


@app.command()
def archivar(zona: str) -> None:
    """Escribe el manifiesto y borra los productos de la zona (no se deshace)."""
    _pendiente(1)


@app.command()
def reconstruir(zona: str) -> None:
    """Rehace una zona archivada desde su config y su manifiesto."""
    _pendiente(1)
