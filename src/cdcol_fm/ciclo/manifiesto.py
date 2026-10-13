"""Manifiesto de una zona: lo que realmente se usó, para poder reconstruirla.

La config dice qué se pidió; el manifiesto dice qué se obtuvo. Hace falta porque los
proveedores reprocesan colecciones y una búsqueda repetida puede devolver otras escenas.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field


class ItemFuente(BaseModel):
    coleccion: str
    id: str
    href: str
    checksum: str | None = None


class Producto(BaseModel):
    nombre: str
    version: str
    sha256: str


class Manifiesto(BaseModel):
    zona: str
    sha256_config: str
    commit_repo: str
    sha256_lockfile: str
    creado: datetime = Field(default_factory=lambda: datetime.now(UTC))
    items_fuente: list[ItemFuente] = []
    pesos: dict[str, str] = Field(default_factory=dict, description="modelo → sha256 de pesos")
    productos: list[Producto] = []

    def guardar(self, ruta: Path) -> None:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(self.model_dump_json(indent=2) + "\n", encoding="utf-8")

    @classmethod
    def leer(cls, ruta: Path) -> Manifiesto:
        return cls.model_validate_json(ruta.read_text(encoding="utf-8"))

    def diferencias(self, otro: Manifiesto) -> list[str]:
        """Lo que cambió al reconstruir. Vacío significa reconstrucción idéntica."""
        difs: list[str] = []
        ids_antes = {(i.coleccion, i.id) for i in self.items_fuente}
        ids_ahora = {(i.coleccion, i.id) for i in otro.items_fuente}
        for col, id_ in sorted(ids_antes - ids_ahora):
            difs.append(f"falta ítem fuente {col}/{id_}")
        for col, id_ in sorted(ids_ahora - ids_antes):
            difs.append(f"ítem fuente nuevo {col}/{id_}")
        for modelo in sorted(set(self.pesos) | set(otro.pesos)):
            if self.pesos.get(modelo) != otro.pesos.get(modelo):
                difs.append(f"pesos distintos para {modelo}")
        prod_antes = {(p.nombre, p.version): p.sha256 for p in self.productos}
        prod_ahora = {(p.nombre, p.version): p.sha256 for p in otro.productos}
        for clave in sorted(set(prod_antes) | set(prod_ahora)):
            if prod_antes.get(clave) != prod_ahora.get(clave):
                difs.append(f"producto distinto {clave[0]} {clave[1]}")
        return difs
