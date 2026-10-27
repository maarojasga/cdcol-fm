"""Comando ``cdcol``."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from cdcol_fm import __version__
from cdcol_fm.config import cargar_pais, listar_zonas

app = typer.Typer(
    help="cdcol-fm: cubo de datos con modelos fundacionales.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


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
    s1: Annotated[
        str,
        typer.Option(help="pc: RTC de Planetary Computer; cdse: GRD de Copernicus + RTC"),
    ] = "pc",
    bloque: Annotated[
        str | None, typer.Option(help="Solo este bloque (x<col>_y<fila>); ver `cdcol bloques`")
    ] = None,
    desde: Annotated[str | None, typer.Option(help="Primer mes, AAAA-MM")] = None,
    hasta: Annotated[str | None, typer.Option(help="Último mes, AAAA-MM")] = None,
) -> None:
    """Calcula el producto ard_s1s2_mensual con sus capas de incertidumbre."""
    from cdcol_fm.ard.pipeline import construir_ard

    manifiesto = construir_ard(
        zona, salida, avisar=typer.echo, fuente_s1=s1, id_bloque=bloque, desde=desde, hasta=hasta
    )
    partes = [p for p in (bloque, desde, hasta) if p]
    ruta = salida / zona / ("manifiesto" + "".join(f"_{p}" for p in partes) + ".json")
    manifiesto.guardar(ruta)
    typer.echo(f"Manifiesto: {ruta}")


@app.command("ard-mes")
def ard_mes(
    zona: str,
    mes: Annotated[str, typer.Argument(help="AAAA-MM")],
    salida: Annotated[Path, typer.Option(help="Carpeta raíz de los productos")] = Path("data"),
    bloques: Annotated[
        str | None, typer.Option(help="Bloques separados por coma; por defecto, todos")
    ] = None,
) -> None:
    """Un mes de la zona por bloques, corrigiendo cada escena S1 de CDSE una sola vez."""
    from cdcol_fm.ard.pipeline import construir_ard_mes

    ids = [b.strip() for b in bloques.split(",")] if bloques else None
    for id_bloque, manifiesto in construir_ard_mes(zona, salida, mes, ids, typer.echo).items():
        manifiesto.guardar(salida / zona / f"manifiesto_{id_bloque}_{mes}.json")
    typer.echo(f"{mes}: listo")


@app.command()
def bloques(
    zona: str,
    json_: Annotated[
        bool, typer.Option("--json", help="Lista JSON (para una matriz de CI)")
    ] = False,
) -> None:
    """Bloques de la grilla nacional que cubren la zona."""
    import json

    from cdcol_fm.ard.bloques import bloques_de_zona
    from cdcol_fm.config import cargar_zona

    z = cargar_zona(zona)
    lista = bloques_de_zona(z, cargar_pais(z.pais))
    if json_:
        typer.echo(json.dumps([b.id for b in lista]))
        return
    lado_km = lista[0].lado_m / 1000 if lista else 0
    typer.echo(f"{zona}: {len(lista)} bloques de {lado_km:g} km")
    for b in lista:
        typer.echo(b.id)


@app.command()
def escenas(zona: str) -> None:
    """Cuenta las escenas S2 y S1 de la zona por mes y fecha (para revisar cobertura)."""
    from collections import Counter

    from cdcol_fm.config import cargar_zona
    from cdcol_fm.fuentes.stac import S1_GRD_CDSE, S1_GRD_ES, S1_GRD_PC, S1_RTC, S2_L2A, buscar

    z = cargar_zona(zona)
    for fuente in (S2_L2A, S1_RTC, S1_GRD_PC, S1_GRD_ES, S1_GRD_CDSE):
        items = buscar(fuente, z)
        por_mes = Counter(it.datetime.strftime("%Y-%m") for it in items)
        fechas = sorted({it.datetime.strftime("%m-%d") for it in items})
        conteo = dict(sorted(por_mes.items()))
        typer.echo(f"{fuente.nombre} {fuente.coleccion}: {conteo} fechas={fechas}")


@app.command()
def resumen(
    zona: str,
    salida: Annotated[Path, typer.Option(help="Carpeta raíz de los productos")] = Path("data"),
    bloque: Annotated[str | None, typer.Option(help="Bloque, si se calculó por bloques")] = None,
) -> None:
    """Tabla por mes de las capas de incertidumbre de una zona ya calculada."""
    from cdcol_fm.ard.resumen import resumen_markdown

    typer.echo(resumen_markdown(salida, zona, bloque))


@app.command()
def vista(
    zona: str,
    salida: Annotated[Path, typer.Option(help="Carpeta raíz de los productos")] = Path("data"),
    abrir: Annotated[bool, typer.Option(help="Abrir la página en el navegador")] = True,
) -> None:
    """Página HTML local para ver el ARD de una zona, mes por mes y capa por capa."""
    import webbrowser

    from cdcol_fm.ard.vista import generar_vista

    ruta = generar_vista(salida, zona)
    typer.echo(f"Vista: {ruta}")
    if abrir:
        webbrowser.open(ruta.resolve().as_uri())


@app.command()
def experimento(
    id_exp: Annotated[str, typer.Argument(help="Id del experimento, p. ej. e01")],
    salida: Annotated[Path, typer.Option(help="Carpeta raíz de los productos")] = Path("data"),
    solo_validar: Annotated[
        bool, typer.Option("--solo-validar", help="Solo revisa el config (pre-registro)")
    ] = False,
) -> None:
    """Corre un experimento pre-registrado de experimentos/ y escribe su veredicto."""
    from cdcol_fm.bench.experimento import cargar_experimento

    exp = cargar_experimento(id_exp)
    if solo_validar:
        typer.echo(f"OK: {exp.id} ({len(exp.brazos)} brazos, {len(exp.bloques)} bloques)")
        return

    from cdcol_fm.bench.correr import cargar_datos, evaluar, guardar, veredicto

    # rutas relativas del config (la referencia) desde donde se corre: en Docker, /datos
    datos = cargar_datos(exp, salida, Path.cwd())
    sin_datos = [b.id for b in exp.brazos if b.id not in datos.rasgos]
    if sin_datos:
        typer.echo(f"Sin datos, no corren: {', '.join(sin_datos)}", err=True)
    filas, preds = evaluar(exp, datos)
    texto, _ = veredicto(exp, preds)
    carpeta = salida / "experimentos" / exp.id
    guardar(exp, filas, texto, datos, carpeta)
    typer.echo(texto)
    typer.echo(f"Resultados: {carpeta}")


@app.command("elegir-bloques")
def elegir_bloques(
    id_exp: Annotated[str, typer.Argument(help="Id del experimento, p. ej. e01")],
    franjas: Annotated[int, typer.Option(help="Franjas sur-norte")] = 5,
    por_franja: Annotated[int, typer.Option(help="Bloques por franja")] = 3,
    escribir: Annotated[
        bool, typer.Option("--escribir", help="Guarda la lista en el config.yaml del experimento")
    ] = False,
) -> None:
    """Elige los bloques de un experimento con la regla fija de bench/seleccion.py."""
    import csv
    import re

    from cdcol_fm.bench.experimento import cargar_experimento, carpeta_experimento
    from cdcol_fm.bench.seleccion import candidatos_worldcover, elegir
    from cdcol_fm.config import cargar_zona

    exp = cargar_experimento(id_exp)
    zona = cargar_zona(exp.zona)
    candidatos = candidatos_worldcover(zona, cargar_pais(zona.pais))
    elegidos = elegir(candidatos, franjas, por_franja)
    ids = {c.id for c in elegidos}
    carpeta = carpeta_experimento(id_exp)
    with (carpeta / "bloques.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["bloque", "columna", "fila", "dentro", "bosque", "elegible", "elegido"])
        for c in sorted(candidatos, key=lambda c: (c.fila, c.columna)):
            fila = [c.id, c.columna, c.fila, f"{c.dentro:.3f}", f"{c.bosque:.3f}"]
            w.writerow([*fila, int(c.elegible), int(c.id in ids)])
    n_eleg = sum(c.elegible for c in candidatos)
    typer.echo(f"{len(candidatos)} bloques, {n_eleg} elegibles, {len(elegidos)} elegidos:")
    for c in elegidos:
        typer.echo(f"  {c.id}  fila {c.fila}  bosque {c.bosque:.0%}")
    lista = "bloques: [" + ", ".join(sorted(ids)) + "]"
    if escribir:
        ruta = carpeta / "config.yaml"
        texto = ruta.read_text(encoding="utf-8")
        nuevo, n = re.subn(r"^bloques: \[.*\]$", lista, texto, flags=re.M)
        if n != 1:
            raise typer.BadParameter(f"no encontré una línea 'bloques: [...]' en {ruta}")
        ruta.write_text(nuevo, encoding="utf-8")
        typer.echo(f"Guardado en {ruta} y {carpeta / 'bloques.csv'}")
    else:
        typer.echo(lista)


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
