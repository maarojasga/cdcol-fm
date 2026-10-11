# cdcol-fm

Open Data Cube con modelos fundacionales para Latinoamérica, con Colombia como caso.

Es la continuación de CDCol (Uniandes + IDEAM, 2016-2021), uno de los primeros cubos nacionales de datos del mundo. CDCol demostró que un cubo nacional era posible y dejó documentado por qué no se sostuvo. Este repositorio retoma esa idea con tres cambios:

1. **Una capa de embeddings de modelos fundacionales** (Sentinel-1 + Sentinel-2, adaptados al trópico) en vez de un algoritmo por tarea.
2. **La incertidumbre y la densidad de observación como bandas de primera clase** del cubo, no como un apéndice.
3. **El linaje viaja con el dato** (STAC), y casi no hay infraestructura que mantener, para que el cubo sobreviva a su financiación.

## Estado

Fase 0: esqueleto. Nada procesa datos todavía.

## Empezar

```bash
uv sync                    # entorno base
uv run cdcol --help
uv run pytest
uv sync --extra cubo       # agrega Open Data Cube y STAC
make cubo-local            # Postgres/PostGIS + datacube en Docker
```

## Estructura

| Carpeta | Qué hay |
|---|---|
| `config/` | Países, zonas, productos ODC, recetas de adaptación y manifiestos. Lo único que se conserva de una zona archivada. |
| `src/cdcol_fm/` | El paquete. Un módulo por componente del plan. |
| `docs/adr/` | Decisiones de arquitectura. |
| `infra/` | Cubo local para desarrollo. |
| `experimentos/` | Un directorio por experimento de la tesis. |

## Ciclo de vida de una zona

Los datos de una zona existen solo mientras un proyecto la usa. `cdcol archivar <zona>` borra los productos y deja en git la configuración y un manifiesto con lo que realmente se usó, y `cdcol reconstruir <zona>` lo rehace. Ver [ADR 0003](docs/adr/0003-ciclo-de-vida-de-zonas.md).

## Licencias

Código: Apache-2.0. Datos y benchmark publicados: CC BY 4.0.
