"""El chat con los datos: herramientas sobre un ARD sintético y el bucle con un cliente falso."""

import json
import threading
import urllib.request
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from cdcol_fm.chat import herramientas
from cdcol_fm.chat.agente import Conversacion, responder
from cdcol_fm.chat.datos import Almacen
from cdcol_fm.chat.herramientas import ErrorHerramienta, ejecutar

BLOQUES = ["x479_y182", "x480_y182"]
MESES = ["2024-01", "2024-02"]
LADO = 16


def _escribir(tmp_path: Any) -> Almacen:
    """Dos bloques × dos meses con valores conocidos.

    NDVI 0,5 (B08 3000, B04 1000) salvo una columna sin dato óptico; VV −10 dB en enero y −7 en
    febrero; n_validas_s2 = 0 en la mitad norte en febrero (sin vista limpia).
    """
    import rioxarray  # noqa: F401

    from cdcol_fm.ard.bandas import BANDAS_ARD
    from cdcol_fm.ard.escritura import escribir_mes

    for i, b in enumerate(BLOQUES):
        x = 10.0 * (i * LADO + np.arange(LADO) + 0.5)
        y = 1000.0 - 10.0 * (np.arange(LADO) + 0.5)
        for mes in MESES:
            ds = xr.Dataset(coords={"time": pd.Timestamp(f"{mes}-01"), "y": y, "x": x})
            for banda in BANDAS_ARD:
                ds[banda] = (("y", "x"), np.full((LADO, LADO), 2000.0, dtype="float32"))
            ds["B08"][:] = 3000.0
            ds["B04"][:] = 1000.0
            ds["B04"][:, 0] = np.nan  # se escribe como 0 = sin dato
            ds["VV"][:] = -10.0 if mes == "2024-01" else -7.0
            n = np.full((LADO, LADO), 4, dtype="uint8")
            if mes == "2024-02":
                n[: LADO // 2] = 0
            ds["n_validas_s2"] = (("y", "x"), n)
            ds["dias_desde_clara"] = ds["dias_desde_clara"].astype("uint16")
            ds["prob_nube"] = (("y", "x"), np.full((LADO, LADO), 30, dtype="uint8"))
            ds["n_adq_s1"] = ds["n_adq_s1"].astype("uint8")
            escribir_mes(ds.rio.write_crs("EPSG:9377"), tmp_path, "macarena", [], "abc", b)
    return Almacen(tmp_path)


@pytest.fixture
def almacen(tmp_path: Any, monkeypatch: Any) -> Almacen:
    monkeypatch.setattr(herramientas, "CARPETA_IMAGENES", tmp_path / "imagenes")
    return _escribir(tmp_path / "datos")


def test_lista_lo_calculado(almacen: Almacen) -> None:
    assert almacen.zonas() == ["macarena"]
    assert almacen.bloques("macarena") == BLOQUES
    assert almacen.meses("macarena", BLOQUES[0]) == MESES
    resumen, figura = ejecutar(almacen, "resumen_zona", {"zona": "macarena"})
    assert resumen["meses_calculados"] == MESES and resumen["bloques"] == 2 and figura is None


def test_estadistica_con_valores_conocidos(almacen: Almacen) -> None:
    salida, figura = ejecutar(almacen, "estadistica", {"zona": "macarena", "variable": "ndvi"})
    enero = salida["por_mes"][0]
    assert enero["mes"] == "2024-01" and enero["bloques"] == 2
    assert enero["p50"] == pytest.approx(0.5)
    assert enero["con_dato_pct"] == pytest.approx(100 * (LADO - 1) / LADO, abs=0.1)
    assert figura["tipo"] == "serie" and [p["mes"] for p in figura["puntos"]] == MESES


def test_calidad_y_comparar(almacen: Almacen) -> None:
    salida, _ = ejecutar(almacen, "calidad", {"zona": "macarena", "bloques": [BLOQUES[0]]})
    pct = [f["sin_vista_optica_limpia_pct"] for f in salida["por_mes"]]
    assert pct == [0.0, 50.0]
    c, _ = ejecutar(almacen, "comparar", {"zona": "macarena", "variable": "vv",
                                          "mes_a": "2024-01", "mes_b": "2024-02"})
    assert c["diferencia_b_menos_a"]["p50"] == pytest.approx(3.0)
    assert c["subio_notable_pct"] == 100.0 and c["bajo_notable_pct"] == 0.0


def test_mapa_escribe_imagenes_ubicadas(almacen: Almacen) -> None:
    salida, figura = ejecutar(almacen, "mapa", {"zona": "macarena", "capa": "color",
                                                "mes": "2024-01"})
    assert salida["bloques_pintados"] == 2
    for pieza in figura["piezas"]:
        assert (herramientas.CARPETA_IMAGENES / pieza["imagen"]).exists()
        lon, lat = np.array(pieza["esquinas"]).mean(axis=0)
        assert -80 < lon < -66 and -5 < lat < 13  # el bloque cae en Colombia


@pytest.mark.parametrize(
    "nombre,entrada,mensaje",
    [
        ("estadistica", {"zona": "macarena", "variable": "temperatura"}, "no existe"),
        ("estadistica", {"zona": "macarena", "variable": "ndvi", "meses": ["2023-05"]},
         "sin datos"),
        ("estadistica", {"zona": "otra", "variable": "ndvi"}, "no tiene datos"),
        ("calidad", {"zona": "macarena", "radio": 3}, "desconocidos"),
        ("mapa", {"zona": "macarena", "capa": "color"}, "faltan"),
        ("borrar", {}, "desconocida"),
    ],
)
def test_entradas_invalidas_vuelven_como_error(
    almacen: Almacen, nombre: str, entrada: dict[str, Any], mensaje: str
) -> None:
    with pytest.raises(ErrorHerramienta, match=mensaje):
        ejecutar(almacen, nombre, entrada)


class Bloque(SimpleNamespace):
    """Bloque de contenido como los del SDK: se serializa con model_dump."""

    def model_dump(self, **_: Any) -> dict[str, Any]:
        return dict(vars(self))


class ClienteFalso:
    """Responde con un guion: primero pide una herramienta, luego contesta con texto."""

    def __init__(self, guion: list[SimpleNamespace]) -> None:
        self.guion = guion
        self.llamadas: list[dict[str, Any]] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._crear))

    def _crear(self, **kwargs: Any) -> SimpleNamespace:
        # copia de los mensajes: la lista sigue creciendo después de la llamada
        self.llamadas.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.guion.pop(0)


def _respuesta(stop: str, *bloques: SimpleNamespace) -> SimpleNamespace:
    uso = SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0)
    return SimpleNamespace(stop_reason=stop, content=list(bloques), usage=uso)


def _cliente_ndvi() -> ClienteFalso:
    return ClienteFalso([
        _respuesta("tool_use", Bloque(type="tool_use", id="t1", name="estadistica",
                                               input={"variable": "ndvi"})),
        _respuesta("end_turn", Bloque(type="text", text="El NDVI mediano es 0,5.")),
    ])


def test_el_bucle_ejecuta_herramientas_y_completa_la_seleccion(almacen: Almacen) -> None:
    cliente = _cliente_ndvi()
    conv = Conversacion()
    r = responder(conv, "¿Cómo está la vegetación?", almacen, "macarena", [BLOQUES[0]], cliente)
    assert r.texto == "El NDVI mediano es 0,5."
    # la zona y los bloques que el modelo omitió salen de la selección del mapa
    assert r.pasos[0]["entrada"] == {"variable": "ndvi", "zona": "macarena",
                                     "bloques": [BLOQUES[0]]}
    assert r.pasos[0]["salida"]["por_mes"][0]["bloques"] == 1
    assert [f["tipo"] for f in r.figuras] == ["serie"]
    assert [m["role"] for m in conv.mensajes] == ["user", "assistant", "user", "assistant"]
    resultado = conv.mensajes[2]["content"][0]
    assert resultado["tool_use_id"] == "t1" and "is_error" not in resultado
    primera = cliente.llamadas[0]
    assert primera["model"] == "claude-opus-5-5"
    assert primera["extra_body"]["fallbacks"] == "default"
    assert "macarena" in primera["messages"][0]["content"]


def test_un_error_de_herramienta_vuelve_al_modelo(almacen: Almacen) -> None:
    cliente = ClienteFalso([
        _respuesta("tool_use", Bloque(type="tool_use", id="t1", name="estadistica",
                                               input={"variable": "lluvia"})),
        _respuesta("end_turn", Bloque(type="text", text="No hay lluvia en el cubo.")),
    ])
    conv = Conversacion()
    r = responder(conv, "¿Cuánto llovió?", almacen, "macarena", None, cliente)
    assert r.pasos[0]["error"] is True
    assert conv.mensajes[2]["content"][0]["is_error"] is True


def test_rechazo_del_modelo(almacen: Almacen) -> None:
    cliente = ClienteFalso([_respuesta("refusal")])
    r = responder(Conversacion(), "...", almacen, "macarena", None, cliente)
    assert "No puedo responder" in r.texto


def test_servidor_local(almacen: Almacen) -> None:
    from cdcol_fm.chat.servidor import crear_servidor

    servidor = crear_servidor(almacen, 0, _cliente_ndvi())
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    base = f"http://127.0.0.1:{servidor.server_address[1]}"
    try:
        zonas = json.load(urllib.request.urlopen(f"{base}/api/zonas"))
        assert zonas[0]["zona"] == "macarena" and len(zonas[0]["bloques"]) == 2
        pedido = urllib.request.Request(
            f"{base}/api/chat", method="POST", headers={"Content-Type": "application/json"},
            data=json.dumps({"zona": "macarena", "pregunta": "¿Vegetación?"}).encode(),
        )
        r = json.load(urllib.request.urlopen(pedido))
        assert r["texto"] == "El NDVI mediano es 0,5." and r["conversacion"]
        figura = json.load(urllib.request.urlopen(
            f"{base}/api/mapa?zona=macarena&capa=ndvi&mes=2024-01"))
        imagen = urllib.request.urlopen(f"{base}/api/imagen/{figura['piezas'][0]['imagen']}")
        assert imagen.headers["Content-Type"] == "image/png"
        assert urllib.request.urlopen(f"{base}/").headers["Content-Type"].startswith("text/html")
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(f"{base}/api/imagen/..%2F..%2Fsecreto.txt")
        assert e.value.code == 404
    finally:
        servidor.shutdown()
        servidor.server_close()


class S3Falso:
    """Lo mínimo de boto3 S3 que usa EstadoS3, en memoria."""

    class _NoSuchKey(Exception):
        pass

    def __init__(self) -> None:
        self.objetos: dict[tuple[str, str], bytes] = {}
        self.exceptions = SimpleNamespace(NoSuchKey=self._NoSuchKey)

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        if (Bucket, Key) not in self.objetos:
            raise self._NoSuchKey(Key)
        cuerpo = self.objetos[(Bucket, Key)]
        return {"Body": SimpleNamespace(read=lambda: cuerpo)}

    def put_object(self, Bucket: str, Key: str, Body: bytes, **_: Any) -> None:  # noqa: N803
        self.objetos[(Bucket, Key)] = Body

    def head_object(self, Bucket: str, Key: str) -> None:  # noqa: N803
        if (Bucket, Key) not in self.objetos:
            raise KeyError(Key)

    def upload_file(self, ruta: str, bucket: str, clave: str, **_: Any) -> None:
        with open(ruta, "rb") as f:
            self.objetos[(bucket, clave)] = f.read()

    def generate_presigned_url(self, _op: str, Params: dict[str, str], **_: Any) -> str:  # noqa: N803
        return f"https://firmada/{Params['Key']}"


class CognitoFalso:
    def __init__(self) -> None:
        self.llamadas = 0

    def get_user(self, AccessToken: str) -> dict[str, Any]:  # noqa: N803
        self.llamadas += 1
        if AccessToken != "bueno":
            raise ValueError("token inválido")
        return {"Username": "abc", "UserAttributes": [{"Name": "email", "Value": "a@b.co"}]}


def test_estado_s3_guarda_la_conversacion_y_publica_imagenes(almacen: Almacen) -> None:
    from cdcol_fm.chat.estado import EstadoS3

    s3 = S3Falso()
    estado = EstadoS3("s3://cubo", s3)
    conv = estado.conversacion("a@b.co", "c1")
    responder(conv, "¿Vegetación?", almacen, "macarena", None, _cliente_ndvi())
    estado.guardar("a@b.co", "c1", conv)
    # al volver a leerla (otra instancia de Lambda) los bloques son dicts reenviables
    leida = estado.conversacion("a@b.co", "c1")
    assert [m["role"] for m in leida.mensajes] == ["user", "assistant", "user", "assistant"]
    assert leida.mensajes[1]["content"][0] == {"type": "tool_use", "id": "t1",
                                               "name": "estadistica", "input": {"variable": "ndvi"}}
    assert estado.conversacion("otra@persona.co", "c1").mensajes == []
    assert [estado.contar_pregunta("a@b.co") for _ in range(3)] == [1, 2, 3]
    _, figura = ejecutar(almacen, "mapa", {"zona": "macarena", "capa": "ndvi", "mes": "2024-01"})
    url = estado.url_imagen(figura["piezas"][0]["imagen"])
    assert url == "https://firmada/imagenes/macarena/x479_y182_2024-01_ndvi.png"
    assert ("cubo", "imagenes/macarena/x479_y182_2024-01_ndvi.png") in s3.objetos


def test_servidor_exige_sesion_y_respeta_la_cuota(almacen: Almacen) -> None:
    from cdcol_fm.chat.servidor import Cognito, crear_servidor

    cognito = CognitoFalso()
    guion = [*_cliente_ndvi().guion, *_cliente_ndvi().guion]
    servidor = crear_servidor(almacen, 0, ClienteFalso(guion),
                              autenticacion=Cognito(cognito), cuota_diaria=2)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{servidor.server_address[1]}"

    def pedir(ruta: str, token: str | None, datos: dict[str, Any] | None = None) -> int:
        cabeceras = {"Content-Type": "application/json"}
        if token:
            cabeceras["Authorization"] = f"Bearer {token}"
        cuerpo = json.dumps(datos).encode() if datos is not None else None
        pedido = urllib.request.Request(f"{base}{ruta}", data=cuerpo, headers=cabeceras,
                                        method="POST" if cuerpo else "GET")
        try:
            return int(urllib.request.urlopen(pedido).status)
        except urllib.error.HTTPError as e:
            return int(e.code)

    try:
        assert pedir("/api/zonas", None) == 401
        assert pedir("/api/zonas", "malo") == 401
        assert pedir("/api/zonas", "bueno") == 200
        assert pedir("/api/zonas", "bueno") == 200
        assert cognito.llamadas == 2  # el token bueno se valida una vez y queda en caché
        pregunta = {"zona": "macarena", "pregunta": "¿Vegetación?"}
        assert pedir("/api/chat", None, pregunta) == 401
        assert [pedir("/api/chat", "bueno", pregunta) for _ in range(3)] == [200, 200, 429]
        assert pedir("/api/chat", "bueno", {**pregunta, "conversacion": "../otra"}) in (400, 429)
    finally:
        servidor.shutdown()
        servidor.server_close()
