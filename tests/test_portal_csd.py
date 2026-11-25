"""CertiSAT (CSD/renovación) sin navegador real: envío, sesión y errores del portal."""

from unittest.mock import MagicMock

import pytest

from sat_descarga.core.errores import ErrorEsperado
from sat_descarga.portal import csd, setup
from sat_descarga.portal.renovacion import RenovacionPortalClient


@pytest.fixture(params=[csd.CSDPortalClient, RenovacionPortalClient])
def cliente(request):
    return request.param("no-existe.cer", "no-existe.key", "x")


@pytest.fixture
def navegador(monkeypatch):
    pytest.importorskip("playwright")
    browser = MagicMock()
    monkeypatch.setattr(setup, "asegurar_chromium", lambda *a, **k: None)
    monkeypatch.setattr(setup, "lanzar_chromium", lambda *a, **k: browser)
    monkeypatch.setattr("playwright.sync_api.sync_playwright", MagicMock())
    return browser


def test_enviar_llega_a_subir_y_cierra_sesion(cliente, navegador, monkeypatch, tmp_path):
    fases, cierres = [], []
    cliente._on_progreso = lambda fase, data: fases.append((fase, data))
    monkeypatch.setattr(cliente, "_login", lambda page: None)
    monkeypatch.setattr(cliente, "_subir_sdg", lambda page, ruta: "123")
    monkeypatch.setattr(cliente, "_seguimiento", lambda *a: ("Aceptada", None))
    monkeypatch.setattr(cliente, "_cerrar_sesion", lambda ctx: cierres.append(1))

    res = cliente.enviar("/x/tramite.ren", directorio_salida=str(tmp_path), recuperar=False)

    assert res["numero_operacion"] == "123"
    assert ("subiendo", {"archivo": "tramite.ren"}) in fases
    assert cierres == [1]
    navegador.close.assert_called_once()


def test_tope_de_sesiones_no_reintenta(cliente, monkeypatch):
    pytest.importorskip("playwright")
    logins = []

    def login(*a, **k):
        logins.append(1)
        raise RuntimeError("Login e.firma no completado")

    monkeypatch.setattr(csd, "iniciar_sesion_fiel", login)
    page = MagicMock(url="https://loginc.mat.sat.gob.mx/nidp/app?id=")
    page.inner_text.return_value = (
        "The maximum number of allowable sessions has been reached. (300101051)"
    )
    with pytest.raises(ErrorEsperado, match="demasiadas sesiones"):
        cliente._login(page)
    assert logins == [1]


def test_pagina_colgada_tras_subir_conserva_el_error(cliente):
    pytest.importorskip("playwright")
    from playwright.sync_api import TimeoutError as PWTimeout

    page = MagicMock()
    page.wait_for_selector.side_effect = [None, PWTimeout("60s")]
    page.inner_text.side_effect = PWTimeout("body")
    with pytest.raises(RuntimeError, match="no devolvió número de operación"):
        cliente._subir_sdg(page, "/x/tramite.ren")


def test_cerrar_sesion_nunca_lanza(cliente):
    context = MagicMock()
    context.new_page.side_effect = RuntimeError("contexto cerrado")
    cliente._cerrar_sesion(context)
