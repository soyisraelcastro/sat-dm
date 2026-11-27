"""/descargar no vuelve a pedirle al SAT una solicitud que ya está descargada.

El poller baja los paquetes solo; si después el usuario pide la descarga, el SAT
responde el paquete "vacío" (ya lo entregó). La guarda devuelve lo que ya hay.
"""

import pytest

pytest.importorskip("fastapi")  # el router importa FastAPI; el CI corre sin el extra server

from sat_descarga.api.routers import webservice as ws  # noqa: E402


def _cat(monkeypatch, sol):
    from sat_descarga.cli import config_store

    monkeypatch.setattr(config_store, "get_solicitud", lambda rfc, id_: sol)


def test_descargada_con_archivos_devuelve_lo_que_hay(tmp_path, monkeypatch):
    (tmp_path / "a.xml").write_text("<x/>", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.xml").write_text("<x/>", encoding="utf-8")
    _cat(monkeypatch, {"estado": "descargada"})
    archivos = ws._ya_descargada("AAA010101AAA", "id", str(tmp_path))
    assert archivos is not None and len(archivos) == 2


def test_lista_sin_descargar_va_al_sat(tmp_path, monkeypatch):
    (tmp_path / "a.xml").write_text("<x/>", encoding="utf-8")
    _cat(monkeypatch, {"estado": "3"})
    assert ws._ya_descargada("AAA010101AAA", "id", str(tmp_path)) is None


def test_descargada_pero_carpeta_vacia_o_borrada_va_al_sat(tmp_path, monkeypatch):
    _cat(monkeypatch, {"estado": "descargada"})
    assert ws._ya_descargada("AAA010101AAA", "id", str(tmp_path)) is None
    assert ws._ya_descargada("AAA010101AAA", "id", str(tmp_path / "no-existe")) is None


def test_sin_registro_va_al_sat(tmp_path, monkeypatch):
    _cat(monkeypatch, None)
    assert ws._ya_descargada("AAA010101AAA", "id", str(tmp_path)) is None
