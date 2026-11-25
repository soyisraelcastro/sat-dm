"""Salida cuando el SAT rechaza el .ren por "solicitud anterior"."""

import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from tests.test_server_certifica import (  # noqa: F401 — fixtures
    _alta_fiel, _esperar_job, _fases_del_stream, aislar, client, vigente,
)
from sat_descarga.api.routers import certifica
from sat_descarga.cli import config_store
from sat_descarga.portal.csd import SolicitudAnteriorError

PUBLICA = "sat_descarga.portal.recuperacion_publica."


@pytest.fixture
def rechazada(client, tmp_path, test_cer, test_key, test_password, vigente):  # noqa: F811
    rfc = _alta_fiel(client, test_cer, test_key, test_password)
    key, ren = tmp_path / "vieja.key", tmp_path / "vieja.ren"
    shutil.copy2(test_key, key)
    ren.write_bytes(b"REN")
    config_store.set_renovacion_pendiente(rfc, {
        "etapa": "generada", "numero_operacion": None, "acuse_pdf": None,
        "ren_path": str(ren), "key_path": str(key), "rechazada_en": "2026-11-25T00:00:00",
    })
    return rfc, key


def _buscar(client, monkeypatch, rfc, series, empareja=False):  # noqa: F811
    monkeypatch.setattr(PUBLICA + "buscar_series", lambda *a, **k: series)
    cer = Path(config_store.get_empresa(rfc)["cer_path"]).read_bytes() if empareja else None
    monkeypatch.setattr(PUBLICA + "bajar_cer", lambda s: cer)
    r = client.post("/renovar/recuperar", json={"rfc": rfc})
    return _esperar_job(client, r.json()["job_id"])["resultado"]


def test_serie_sat(tmp_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    n = x509.Name([])
    c = (x509.CertificateBuilder().subject_name(n).issuer_name(n).public_key(k.public_key())
         .serial_number(int.from_bytes(b"00001000000512345678", "big"))
         .not_valid_before(datetime(2026, 1, 1)).not_valid_after(datetime(2030, 1, 1))
         .sign(k, hashes.SHA256()))
    f = tmp_path / "c.cer"
    f.write_bytes(c.public_bytes(serialization.Encoding.DER))
    assert certifica._serie_sat(str(f)) == "00001000000512345678"


def test_rechazo_se_marca_y_avisa(client, monkeypatch, test_cer, test_key, test_password, vigente):  # noqa: F811
    rfc = _alta_fiel(client, test_cer, test_key, test_password)

    def enviar(*a, on_progreso=None, **k):
        on_progreso("login_ok", {})
        raise SolicitudAnteriorError("pertenece a una solicitud anterior")

    monkeypatch.setattr("sat_descarga.portal.renovacion.enviar_renovacion_fiel", enviar)
    monkeypatch.setattr("sat_descarga.portal.renovacion.recuperar_renovacion_fiel",
                        lambda *a, **k: {"cer": None})
    r = client.post("/renovar", json={"rfc": rfc, "password": test_password, "confirmar": True})
    job = r.json()["job_id"]
    assert _esperar_job(client, job)["estado"] == "error"
    fases = [e["fase"] for e in _fases_del_stream(client, job) if e["event"] == "fase"]
    assert fases[-1] == "rechazada"
    assert config_store.get_renovacion_pendiente(rfc)["rechazada_en"]
    estado = client.get(f"/renovar/estado?rfc={rfc}").json()
    assert estado["rechazada"] and not estado["reintento_seguro"]
    assert estado["siguiente_paso"] == "recuperar"


def test_busqueda_limpia_habilita_otra_y_conserva_la_llave(
    client, monkeypatch, rechazada, test_password,  # noqa: F811
):
    rfc, key = rechazada
    serie = "00001000000512345678"   # el cert de pruebas no trae serie del SAT
    monkeypatch.setattr(certifica, "_serie_sat", lambda p: serie)
    res = _buscar(client, monkeypatch, rfc, [serie])
    assert res["puede_generar_otra"] and not res["renovada"]

    r = client.post("/renovar/generar", json={"rfc": rfc, "password": test_password, "otra": True})
    assert r.status_code == 200 and r.json()["reutilizada"] is False
    p = config_store.get_renovacion_pendiente(rfc)
    assert p["key_path"] != str(key) and key.exists()
    assert p["anteriores"][0]["key_path"] == str(key) and not p.get("rechazada_en")
    # Repetir con `otra` ya no procede; sin ella reutiliza y no pierde la anterior.
    cuerpo = {"rfc": rfc, "password": test_password}
    assert client.post("/renovar/generar", json={**cuerpo, "otra": True}).status_code == 409
    assert client.post("/renovar/generar", json=cuerpo).json()["reutilizada"] is True
    assert config_store.get_renovacion_pendiente(rfc)["anteriores"] == p["anteriores"]

    # Si al final el SAT emite el de la llave ANTERIOR, se instala con esa llave.
    res = _buscar(client, monkeypatch, rfc, ["00001000000999999999"], empareja=True)
    assert res["renovada"] is True
    assert Path(config_store.get_empresa(rfc)["key_path"]).read_bytes() == key.read_bytes()


@pytest.mark.parametrize("series", [[], ["00009999999999999999"]])
def test_sin_poder_confirmar_no_habilita(client, monkeypatch, rechazada, test_password, series):  # noqa: F811
    rfc, key = rechazada
    res = _buscar(client, monkeypatch, rfc, series)
    assert res["puede_generar_otra"] is False and "por seguridad" in res["mensaje"]
    r = client.post("/renovar/generar", json={"rfc": rfc, "password": test_password, "otra": True})
    assert r.status_code == 409
    assert config_store.get_renovacion_pendiente(rfc)["key_path"] == str(key)


@pytest.mark.parametrize("cambios", [
    {}, {"verificada_en": (datetime.now() - timedelta(hours=2)).isoformat()},
    {"verificada_en": datetime.now().isoformat(), "rechazada_en": None},
    {"verificada_en": datetime.now().isoformat(), "numero_operacion": "1"},
])
def test_candado(client, rechazada, test_password, cambios):  # noqa: F811
    rfc, key = rechazada
    p = {**config_store.get_renovacion_pendiente(rfc), **cambios}
    config_store.set_renovacion_pendiente(rfc, p)
    r = client.post("/renovar/generar", json={"rfc": rfc, "password": test_password, "otra": True})
    assert r.status_code == 409
    assert config_store.get_renovacion_pendiente(rfc)["key_path"] == str(key)
