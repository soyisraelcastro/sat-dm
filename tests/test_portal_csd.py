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


def _pagina_real(html):
    """Corre `_subir_sdg` contra un formulario local que responde `html`."""
    # La ruta del navegador se fija ANTES de importar Playwright.
    if not setup._navegadores_instalados(setup.configurar_playwright_browsers_path()):
        pytest.skip("sin Chromium")
    sync = pytest.importorskip("playwright.sync_api")
    with sync.sync_playwright() as p:
        b = setup.lanzar_chromium(p, headless=True)
        try:
            page = b.new_page()
            form = ('<meta charset="utf-8"><form method="post" enctype="multipart/form-data">'
                    '<input type="file" id="f" name="f"><input type="submit" name="enviar"></form>')
            page.route("**/*", lambda r: r.fulfill(
                content_type="text/html; charset=utf-8",
                body=form if r.request.method == "GET" else html))
            k = csd.CSDPortalClient("x.cer", "x.key", "x")
            k.MENU_URL, k.FILE_INPUT = "http://sat.test/", "#f"
            return k._subir_sdg(page, __file__)
        finally:
            b.close()


def test_numero_de_operacion_con_input_oculto_duplicado():
    html = ('<input name="numeroOperacion" value="123">'
            '<input type="hidden" name="numeroOperacion" value="123">')
    assert _pagina_real(html) == "123"


def test_solicitud_anterior_se_reconoce_sin_agotar_la_espera():
    with pytest.raises(csd.SolicitudAnteriorError, match="reenviarlo no sirve"):
        _pagina_real("<p>¡Ocurrió un error durante su solicitud! Este requerimiento "
                     "pertenece a una\n solicitud anterior, favor de solicitar su seguimiento</p>")


def test_otro_error_del_sat_no_es_solicitud_anterior():
    with pytest.raises(RuntimeError, match="Pudo haber recibido") as e:
        _pagina_real("<p>¡Ocurrió un error durante su solicitud! Certificado inválido</p>")
    assert not isinstance(e.value, csd.SolicitudAnteriorError)
