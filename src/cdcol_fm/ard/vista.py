"""Vista rápida del ARD: una página HTML local con imágenes por mes y capa.

No necesita internet ni servidor: escribe PNG (con rasterio, sin dependencias nuevas) y un
``index.html`` que se abre con doble clic. Si la zona se calculó por bloques, los bloques de
cada mes se pegan en un solo mosaico, reducido para que la página cargue rápido.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from cdcol_fm.ard.escritura import carpeta_producto

_PATRON_BLOQUE = re.compile(r"^x(-?\d+)_y(-?\d+)$")
_PATRON_MES = re.compile(r"^\d{4}-\d{2}$")

# Rampa de 5 colores (de bajo a alto) para las capas de una sola banda.
_RAMPA = np.array(
    [[68, 1, 84], [59, 82, 139], [33, 145, 140], [94, 201, 98], [253, 231, 37]], dtype=float
)


@dataclass(frozen=True)
class Capa:
    id: str
    titulo: str
    explicacion: str
    bandas: tuple[str, ...]
    rango: tuple[float, float]
    rampa: bool = False


CAPAS = (
    Capa(
        "color",
        "Color natural",
        "Rojo, verde y azul de Sentinel-2: la mediana del mes sin nubes. Negro = sin vista clara.",
        ("B04", "B03", "B02"),
        (0, 1500),
    ),
    Capa(
        "falso",
        "Falso color",
        "Infrarrojo cercano, rojo y verde: la vegetación sana se ve roja.",
        ("B08", "B04", "B03"),
        (0, 4000),
    ),
    Capa(
        "vv",
        "Radar VV",
        "Sentinel-1 corregido por relieve, en dB. Ve a través de las nubes.",
        ("VV",),
        (-20, 0),
    ),
    Capa("vh", "Radar VH", "Polarización cruzada, sensible a la vegetación.", ("VH",), (-28, -8)),
    Capa(
        "n_validas",
        "Observaciones ópticas válidas",
        "Cuántas fechas sin nube tuvo cada píxel en el mes (morado = 0, amarillo = 6 o más).",
        ("n_validas_s2",),
        (0, 6),
        rampa=True,
    ),
    Capa(
        "nube",
        "Nube",
        "Porcentaje de observaciones con nube o sombra (morado = 0 %, amarillo = 100 %).",
        ("prob_nube",),
        (0, 100),
        rampa=True,
    ),
    Capa(
        "dias",
        "Días desde la última vista clara",
        "Cuánto hace que el píxel se vio limpio (morado = hoy, amarillo = 60 días o más).",
        ("dias_desde_clara",),
        (0, 60),
        rampa=True,
    ),
)


def _a_bytes(datos: np.ndarray, rango: tuple[float, float]) -> np.ndarray:
    bajo, alto = rango
    escalado = np.clip((datos - bajo) / (alto - bajo), 0, 1)
    return np.where(np.isfinite(datos), escalado * 255, 0).astype("uint8")


def _rampa(datos: np.ndarray, rango: tuple[float, float]) -> np.ndarray:
    bajo, alto = rango
    t = np.clip((datos - bajo) / (alto - bajo), 0, 1) * (len(_RAMPA) - 1)
    i = np.minimum(np.floor(np.nan_to_num(t)).astype(int), len(_RAMPA) - 2)
    f = (np.nan_to_num(t) - i)[..., None]
    rgb = _RAMPA[i] * (1 - f) + _RAMPA[i + 1] * f
    rgb[~np.isfinite(datos)] = 0
    return np.moveaxis(rgb.astype("uint8"), -1, 0)


def _leer(ruta: Path, lado: int) -> np.ndarray:
    """Banda reducida a ``lado``×``lado`` px (usa las vistas internas del COG), NaN sin dato."""
    import rasterio  # type: ignore[import-untyped]

    with rasterio.open(ruta) as fuente:
        alto = max(1, round(fuente.height * lado / max(fuente.height, fuente.width)))
        ancho = max(1, round(fuente.width * lado / max(fuente.height, fuente.width)))
        datos = fuente.read(1, out_shape=(alto, ancho), masked=True).astype("float32")
    return np.ma.filled(datos, np.nan)


def _piezas(base: Path) -> dict[str, dict[tuple[int, int] | None, Path]]:
    """mes → {(columna, fila) del bloque, o None si la zona no se partió: carpeta del mes}."""
    salida: dict[str, dict[tuple[int, int] | None, Path]] = {}
    for carpeta in sorted(p for p in base.iterdir() if p.is_dir()):
        if _PATRON_MES.match(carpeta.name):
            salida.setdefault(carpeta.name, {})[None] = carpeta
            continue
        bloque = _PATRON_BLOQUE.match(carpeta.name)
        if not bloque:
            continue
        pos = (int(bloque.group(1)), int(bloque.group(2)))
        for mes in sorted(p for p in carpeta.iterdir() if _PATRON_MES.match(p.name)):
            salida.setdefault(mes.name, {})[pos] = mes
    return salida


def _mosaico(piezas: dict[tuple[int, int] | None, Path], capa: Capa, lado: int) -> np.ndarray:
    """Imagen RGB (3, alto, ancho) de una capa para un mes."""

    def una(carpeta: Path, lado_pieza: int) -> np.ndarray:
        bandas = [_leer(carpeta / f"{b}.tif", lado_pieza) for b in capa.bandas]
        if capa.rampa:
            return _rampa(bandas[0], capa.rango)
        if len(bandas) == 1:
            gris = _a_bytes(bandas[0], capa.rango)
            return np.stack([gris] * 3)
        return np.stack([_a_bytes(b, capa.rango) for b in bandas])

    if None in piezas:
        return una(piezas[None], lado)
    posiciones = [p for p in piezas if p is not None]
    cols = [c for c, _ in posiciones]
    filas = [f for _, f in posiciones]
    lienzo = np.zeros((3, (max(filas) - min(filas) + 1) * lado, (max(cols) - min(cols) + 1) * lado))
    for (c, f), carpeta in ((p, piezas[p]) for p in posiciones):
        # la fila crece hacia el norte; en la imagen el norte va arriba
        y = (max(filas) - f) * lado
        x = (c - min(cols)) * lado
        img = una(carpeta, lado)
        lienzo[:, y : y + img.shape[1], x : x + img.shape[2]] = img
    return lienzo.astype("uint8")


def _png(img: np.ndarray, ruta: Path) -> None:
    import rasterio

    ruta.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        ruta, "w", driver="PNG", width=img.shape[2], height=img.shape[1], count=3, dtype="uint8"
    ) as destino:
        destino.write(img)


def generar_vista(destino: Path, zona: str, lado_bloque: int = 256) -> Path:
    """Escribe ``<destino>/<zona>/vista/index.html`` y devuelve su ruta."""
    base = carpeta_producto(destino, zona)
    if not base.exists():
        raise FileNotFoundError(f"no hay productos de {zona} en {base}; corre antes `cdcol ard`")
    carpeta = destino / zona / "vista"
    meses = _piezas(base)
    if not meses:
        raise FileNotFoundError(f"{base} no tiene meses calculados")
    # una zona sin partir se muestra más grande que cada bloque de un mosaico
    for mes, piezas in meses.items():
        lado = 1024 if None in piezas else lado_bloque
        for capa in CAPAS:
            if all((p / f"{capa.bandas[0]}.tif").exists() for p in piezas.values()):
                _png(_mosaico(piezas, capa, lado), carpeta / mes / f"{capa.id}.png")
    datos = {
        "zona": zona,
        "meses": list(meses),
        "bloques": {m: len(p) for m, p in meses.items()},
        "capas": [{"id": c.id, "titulo": c.titulo, "explicacion": c.explicacion} for c in CAPAS],
    }
    ruta = carpeta / "index.html"
    ruta.write_text(_HTML.replace("__DATOS__", json.dumps(datos, ensure_ascii=False)), "utf-8")
    return ruta


_HTML = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cubo cdcol-fm</title>
<style>
:root { --fondo: #f6f6f4; --texto: #1d1d1b; --suave: #5f5f5a;
        --borde: #d9d9d4; --acento: #1f6f5c; }
@media (prefers-color-scheme: dark) {
  :root { --fondo: #161615; --texto: #ececea; --suave: #a3a39e;
          --borde: #3a3a37; --acento: #6cc3a8; }
}
body { margin: 0; background: var(--fondo); color: var(--texto);
       font: 15px/1.45 system-ui, sans-serif; }
main { max-width: 1100px; margin: 0 auto; padding: 16px; }
h1 { font-size: 20px; margin: 0 0 4px; }
p { color: var(--suave); margin: 4px 0 12px; }
.fila { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }
button { border: 1px solid var(--borde); background: transparent; color: var(--texto);
         border-radius: 6px; padding: 6px 10px; cursor: pointer; font: inherit; }
button.activo { border-color: var(--acento); color: var(--acento); font-weight: 600; }
img { width: 100%; height: auto; image-rendering: pixelated; border: 1px solid var(--borde);
      border-radius: 6px; background: #000; }
</style></head>
<body><main>
<h1 id="titulo"></h1>
<p>Producto ard_s1s2_mensual. Cada imagen es la mediana del mes; las capas de incertidumbre
dicen cuánto confiar en cada píxel.</p>
<div class="fila" id="meses"></div>
<div class="fila" id="capas"></div>
<p id="explicacion"></p>
<img id="imagen" alt="">
</main>
<script>
const D = __DATOS__;
let mes = D.meses[0], capa = D.capas[0].id;
function botones(id, items, actual, alElegir) {
  const caja = document.getElementById(id); caja.innerHTML = "";
  for (const [valor, texto] of items) {
    const b = document.createElement("button"); b.textContent = texto;
    if (valor === actual) b.className = "activo";
    b.onclick = () => alElegir(valor); caja.appendChild(b);
  }
}
function pintar() {
  const n = D.bloques[mes];
  document.getElementById("titulo").textContent =
    `Zona ${D.zona} · ${mes}` + (n > 1 ? ` · ${n} bloques` : "");
  botones("meses", D.meses.map(m => [m, m]), mes, m => { mes = m; pintar(); });
  botones("capas", D.capas.map(c => [c.id, c.titulo]), capa, c => { capa = c; pintar(); });
  const c = D.capas.find(x => x.id === capa);
  document.getElementById("explicacion").textContent = c.explicacion;
  const img = document.getElementById("imagen");
  img.src = `${mes}/${capa}.png`; img.alt = `${c.titulo}, ${mes}`;
}
pintar();
</script></body></html>
"""
