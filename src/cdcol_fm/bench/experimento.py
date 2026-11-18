"""Config de un experimento (``experimentos/<id>-*/config.yaml``): el pre-registro."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from cdcol_fm.config import RAIZ_CONFIG, _leer_yaml

RAIZ_EXPERIMENTOS = RAIZ_CONFIG.parent / "experimentos"


class Referencia(BaseModel):
    fuente: str
    ruta: Path
    reclasificacion: dict[int, int] = {}
    otros_a: int | None = None  # clase para los códigos que no están en la reclasificación
    nodata: int | None = None
    radio_homogeneo: int = Field(default=0, ge=0)


class Estratos(BaseModel):
    variable: str
    nombres: list[str] = Field(min_length=2)
    # fijados por `cdcol estratos <id> --escribir` antes de cargar la referencia; None = sin fijar
    cortes: list[float] | None = None

    @model_validator(mode="after")
    def _cortes_coherentes(self) -> Estratos:
        c = self.cortes
        if c is not None and (len(c) != len(self.nombres) - 1 or sorted(c) != c):
            raise ValueError(f"cortes {c}: hacen falta {len(self.nombres) - 1}, en orden")
        return self


class Evaluacion(BaseModel):
    pliegues: int = Field(ge=2)
    etiquetas_por_clase: list[int] = Field(min_length=1)
    presupuesto_principal: int
    prueba_por_clase_y_estrato: int = Field(gt=0)
    semillas: list[int] = Field(min_length=1)
    bootstrap: int = Field(ge=100)
    metrica: str = "exactitud_balanceada"
    delta: float = Field(ge=0)

    @model_validator(mode="after")
    def _principal_en_presupuestos(self) -> Evaluacion:
        if self.presupuesto_principal not in self.etiquetas_por_clase:
            raise ValueError("presupuesto_principal debe estar en etiquetas_por_clase")
        return self


class PruebaNubes(BaseModel):
    """Nube simulada: a los píxeles de prueba del estrato despejado se les vacían meses ópticos."""

    nivel: int = Field(ge=1, le=2)  # 1: meses enteros al azar; 2: máscaras reales trasplantadas
    estrato: str
    meses_vaciados: list[int] = Field(min_length=1)
    brazos: list[str] = Field(min_length=2)  # solo brazos que se pueden recalcular sin esos meses


class Brazo(BaseModel):
    id: str
    tipo: str
    rasgos: str
    referencia: bool = False
    # externo: no corre sobre el ARD (p. ej. AlphaEarth); se reporta pero no decide H1/H2
    externo: bool = False


class Experimento(BaseModel):
    id: str
    nombre: str
    zona: str
    anio: int
    bloques: list[str] = []
    tarea: str
    clases: dict[int, str] = Field(min_length=2)
    referencia: Referencia
    estratos: Estratos
    evaluacion: Evaluacion
    brazos: list[Brazo] = Field(min_length=2)
    prueba_nubes: PruebaNubes | None = None

    @model_validator(mode="after")
    def _un_brazo_de_referencia(self) -> Experimento:
        if sum(b.referencia for b in self.brazos) != 1:
            raise ValueError(f"{self.id}: debe haber exactamente un brazo con referencia: true")
        return self

    @model_validator(mode="after")
    def _prueba_nubes_coherente(self) -> Experimento:
        p = self.prueba_nubes
        if p is None:
            return self
        if p.estrato not in self.estratos.nombres:
            raise ValueError(f"{self.id}: prueba_nubes.estrato '{p.estrato}' no es un estrato")
        por_id = {b.id: b for b in self.brazos}
        for b in p.brazos:
            if b not in por_id:
                raise ValueError(f"{self.id}: prueba_nubes usa el brazo '{b}', que no existe")
            if por_id[b].externo:
                raise ValueError(f"{self.id}: '{b}' es externo; no se le pueden vaciar meses")
        return self

    @property
    def brazo_referencia(self) -> Brazo:
        return next(b for b in self.brazos if b.referencia)


def carpeta_experimento(id_exp: str, raiz: Path = RAIZ_EXPERIMENTOS) -> Path:
    candidatas = sorted(raiz.glob(f"{id_exp}-*"))
    if len(candidatas) != 1:
        raise FileNotFoundError(f"no hay un único directorio {id_exp}-* en {raiz}")
    return candidatas[0]


def cargar_experimento(id_exp: str, raiz: Path = RAIZ_EXPERIMENTOS) -> Experimento:
    return Experimento.model_validate(_leer_yaml(carpeta_experimento(id_exp, raiz) / "config.yaml"))
