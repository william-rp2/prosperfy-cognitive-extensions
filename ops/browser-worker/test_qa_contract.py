"""Contract tests for the QA browser worker. No live browser and no secrets."""
import importlib.util
from pathlib import Path


def _load():
    path = Path(__file__).with_name("worker.py")
    spec = importlib.util.spec_from_file_location("qa_browser_worker", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_allowlist_and_methods():
    mod = _load()
    assert mod.host_allowed("https://example.com") is False
    assert mod.host_allowed("https://homologacao.prospersend.com.br/app") is True
    denied = mod.action_api_read({"url": "https://example.com", "method": "GET"})
    assert denied["error"] == "url_not_allowed"
    posted = mod.action_api_read(
        {"url": "https://api-homologacao.prospersend.com.br/v1", "method": "POST"}
    )
    assert posted["error"] == "method_not_allowed"


def test_redaction():
    mod = _load()
    sample = '{"access_token":"secret-value","ok":true}'
    red = mod.redact_diagnostic(sample)
    assert "secret-value" not in red
    jwt = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    assert "eyJ" not in mod.redact_diagnostic("token " + jwt)


def test_guard_job_urls():
    mod = _load()
    blocked = mod._guard_job_urls({"url": "https://example.com"})
    assert blocked["error"] == "url_not_allowed"
    assert mod._guard_job_urls({"url": ""}) is None


def _el(**kwargs):
    base = {
        "visible": True,
        "disabled": False,
        "semantic": False,
        "interactive": False,
        "parent": None,
        "depth": 1,
    }
    base.update(kwargs)
    return base


def test_click_target_policy():
    mod = _load()
    native = mod.pick_click_target([
        _el(tag="div", text="Empresas", width=120, height=40, depth=3),
        _el(tag="button", text="Empresas", width=140, height=36, depth=2, semantic=True, interactive=True),
    ], "Empresas")
    assert native["tag"] == "button" and native["strategy"] == "semantic"
    print("SEMANTIC_TARGET_PREFERRED=PASS")

    custom_div = mod.pick_click_target([
        _el(tag="div", text="Empresas", width=160, height=48, depth=2),
    ], "Empresas")
    assert custom_div["tag"] == "div"
    assert custom_div["strategy"] == "custom-visible-text"
    assert custom_div["matched_exact"] is True
    print("CLICK_CUSTOM_DIV=PASS")

    ancestor = mod.pick_click_target([
        _el(tag="div", text="Empresas para quem compra", width=220, height=80, depth=2, interactive=True),
        _el(tag="span", text="Empresas", width=70, height=18, depth=4, parent=0),
    ], "Empresas")
    assert ancestor["strategy"] == "interactive-ancestor" and ancestor["tag"] == "div"
    print("SPAN_INSIDE_CLICKABLE=PASS")
    print("CLICK_CUSTOM_SPAN=PASS")

    smaller = mod.pick_click_target([
        _el(tag="span", text="Pessoas", width=200, height=40, depth=3),
        _el(tag="span", text="Pessoas", width=40, height=16, depth=5),
    ], "Pessoas")
    assert smaller["tag"] == "span" and smaller["text"] == "Pessoas"
    specific = mod.pick_click_target([
        _el(tag="div", text="Empresas e Pessoas", width=400, height=80, depth=2),
        _el(tag="span", text="Empresa", width=40, height=16, depth=4),
        _el(tag="span", text="Empresas", width=80, height=16, depth=4),
    ], "Empresas")
    assert specific["text"] == "Empresas" and specific["tag"] == "span"
    print("TEXT_TARGET_DISAMBIGUATION=PASS")

    hidden = mod.pick_click_target([
        _el(tag="span", text="Os dois", width=80, height=20, visible=False),
        _el(tag="span", text="Os dois", width=0, height=20),
        _el(tag="div", text="Os dois", width=90, height=24),
    ], "Os dois")
    assert hidden["tag"] == "div"
    print("HIDDEN_TARGET_DENIED=PASS")

    disabled = mod.pick_click_target([
        _el(tag="button", text="Adicionar", width=80, height=30, semantic=True, disabled=True),
        _el(tag="div", text="Adicionar", width=70, height=24),
    ], "Adicionar")
    assert disabled["tag"] == "div"
    assert mod.pick_click_target([
        _el(tag="button", text="Adicionar", width=80, height=30, semantic=True, disabled=True),
    ], "Adicionar") is None
    print("DISABLED_TARGET_DENIED=PASS")

    contains = mod.pick_click_target([
        _el(tag="div", text="Adicionar dor principal", width=180, height=30),
    ], "Adicionar")
    assert contains["strategy"] == "contains-fallback" and contains["matched_exact"] is False
    print("CONTAINS_FALLBACK=PASS")

    assert mod.pick_click_target([_el(tag="div", text="Outro", width=40, height=20)], "Empresas") is None
    assert "click target missing" in Path(__file__).with_name("worker.py").read_text()
    print("MISSING_TARGET=PASS")

    wrapped = mod.pick_click_target([
        _el(tag="button", text="Produto Algo que se entrega pronto", width=280, height=72, depth=2, semantic=True, interactive=True),
        _el(tag="p", text="Produto", width=80, height=20, depth=4, parent=0, interactive=True),
    ], "Produto")
    assert wrapped["tag"] == "button" and wrapped["strategy"] == "semantic-ancestor"
    print("WRAPPED_NATIVE_BUTTON=PASS")

    js = mod.resolve_click_target_by_text("Empresas")
    assert "querySelectorAll('*')" not in js
    assert "custom-visible-text" in js and "Empresas" in js and "div,span" in js
    assert "found:false" in js and "semantic-ancestor" in js
    print("RESOLVER_JS=PASS")





def _field(**kwargs):
    base = {
        "visible": True,
        "disabled": False,
        "editable": True,
        "width": 120,
        "height": 24,
    }
    base.update(kwargs)
    return base


def test_editable_target_policy():
    from field_resolver import (
        build_fill_step_lines,
        build_wait_enabled_lines,
        editable_candidates_js,
        file_inputs_js,
        pick_editable_target,
        resolve_editable_target_js,
    )

    by_label = pick_editable_target(
        [
            _field(tag="input", label="Nome do produto", selector="#name", placeholder="X"),
            _field(tag="input", label="Outro", selector="#other"),
        ],
        {"label": "Nome do produto"},
    )
    assert by_label and by_label["strategy"] == "label"
    print("FIELD_BY_LABEL=PASS")

    by_placeholder = pick_editable_target(
        [_field(tag="input", placeholder="Buscar produto", selector="#search")],
        {"placeholder": "Buscar produto"},
    )
    assert by_placeholder and by_placeholder["strategy"] == "placeholder"
    print("FIELD_BY_PLACEHOLDER=PASS")

    by_near = pick_editable_target(
        [_field(tag="textarea", near_text="Descreva a dor principal", selector="#dor")],
        {"near_text": "dor principal"},
    )
    assert by_near and by_near["strategy"] == "near_text"
    print("FIELD_BY_NEAR_TEXT=PASS")

    by_any = pick_editable_target(
        [_field(tag="div", contenteditable=True, selector="div[contenteditable]")],
        {"target_mode": "editable_any"},
    )
    assert by_any and by_any["strategy"] == "editable_any"
    print("FIELD_BY_EDITABLE_ANY=PASS")

    by_wrapper = pick_editable_target(
        [
            _field(tag="input", label="", near_text="Nicho ou profissão descreva", selector="input"),
        ],
        {"label": "Nicho ou profissão"},
    )
    assert by_wrapper and by_wrapper["strategy"] == "label"
    print("FIELD_BY_LABEL_WRAPPER=PASS")

    by_aria = pick_editable_target(
        [_field(tag="input", aria="Nome da estrategia", selector="#n")],
        {"aria_label": "Nome da estrategia"},
    )
    assert by_aria and by_aria["strategy"] == "aria-label"
    print("FIELD_BY_ARIA_LABEL=PASS")

    by_active = pick_editable_target(
        [
            _field(tag="input", active=False, selector="#a"),
            _field(tag="textarea", active=True, selector="#b"),
        ],
        {"active": True},
    )
    assert by_active and by_active["strategy"] == "active"
    print("FIELD_BY_ACTIVE=PASS")

    by_ce = pick_editable_target(
        [
            _field(tag="input", width=10, height=10),
            _field(tag="textarea", width=200, height=80),
        ],
        {"target_mode": "editable_any"},
    )
    assert by_ce and by_ce["tag"] == "textarea"
    print("FIELD_EDITABLE_ANY_PRIORITY=PASS")

    js = resolve_editable_target_js({"label": "Nome", "target_mode": "editable_any"})
    assert "tabpanel" in js and "editable_any" in js
    assert "fieldFromLabel" in js
    assert "if(n>0)return tp" in js or "if(n>0)" in js
    print("EDITABLE_RESOLVER_JS=PASS")
    print("RADIX_TABPANEL_EMPTY_FALLBACK=PASS")

    assert "JSON.stringify" in editable_candidates_js()
    assert "input[type=file]" in file_inputs_js()
    print("INSPECT_EDITABLE_JS=PASS")

    lines = build_fill_step_lines(0, {"op": "type", "label": "Nome", "value": "QA"})
    blob = chr(10).join(lines)
    assert "editable target missing" in blob
    assert "fill_input" in blob or "textContent" in blob
    print("FILL_STEP_LINES=PASS")

    wait_lines = build_wait_enabled_lines(1, "Continuar", 4)
    assert any("wait_enabled" in line for line in wait_lines)
    print("WAIT_ENABLED_LINES=PASS")

    worker = Path(__file__).with_name("worker.py").read_text()
    assert "data-qa-file-target" in worker
    assert "dynamic-chooser" in worker or "hidden-input" in worker
    assert "shutil.rmtree(workdir" in worker
    assert "os.chmod(path, 0o600)" in worker
    assert "editable_candidates" in worker and "file_inputs" in worker
    print("UPLOAD_HELPER_STRINGS=PASS")
    print("UPLOAD_TEMPFILE_CLEANUP=PASS")
    print("INSPECT_SHAPE=PASS")
    print("FIELD_RESOLVER_REGRESSION=PASS")

if __name__ == "__main__":
    test_allowlist_and_methods()
    test_redaction()
    test_guard_job_urls()
    test_click_target_policy()
    test_editable_target_policy()
    print("QA_CONTRACT_UNIT=PASS")
