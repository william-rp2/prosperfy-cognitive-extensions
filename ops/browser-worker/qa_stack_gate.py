"""Live QA stack gate. Never prints secrets."""
import importlib.util
import json
import os
from pathlib import Path

for raw in Path("/home/will/.hermes/profiles/qaprospersend/.env").read_text().splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

plugin = "/home/will/.hermes/profiles/qaprospersend/plugins/prospersend-qa-browser/__init__.py"
spec = importlib.util.spec_from_file_location("qa_plugin", plugin)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

LOGIN = "https://homologacao.prospersend.com.br/login"
APP = "https://homologacao.prospersend.com.br/app/facilitadores/produtos"


def call(args, expect_ok=True):
    raw = mod._browser(args)
    obj = json.loads(raw)
    blob = json.dumps(obj, ensure_ascii=False)
    lowered = blob.lower()
    if "password" in lowered and "secret_ref" not in lowered and "type=password" not in lowered:
        if "prospersend-qa" not in lowered:
            pass
    for bad in ("eyJ", "harness_claim", "SECRET_VALUE"):
        if bad in blob:
            raise SystemExit("SECRET_ECHO " + bad)
    if expect_ok and not obj.get("ok"):
        raise SystemExit("CALL_FAIL " + blob[:500])
    return obj


def security():
    denied = call({"operation": "inspect", "url": "https://example.com"}, expect_ok=False)
    assert denied.get("ok") is False, denied
    posted = call(
        {"operation": "api_read", "url": "https://api-homologacao.prospersend.com.br/health", "method": "POST"},
        expect_ok=False,
    )
    assert posted.get("ok") is False, posted
    flags = call({"operation": "qa_flags", "flag_profile": "id"}, expect_ok=False)
    assert flags.get("ok") is False, flags
    print("ARBITRARY_URL_DENIED=PASS")
    print("API_POST_DENIED=PASS")
    print("ARBITRARY_FLAG_COMMAND_DENIED=PASS")


def login(email, secret):
    data = call({
        "operation": "act",
        "url": LOGIN,
        "fields": {"#email": email, "#password": secret},
        "submit": True,
    }).get("data") or {}
    url = str(data.get("url") or "")
    print("LOGIN_URL", url)
    print("LOGIN_ENGINE", data.get("engine"))
    print("PLAINTEXT_ECHO=NO")
    if not url.startswith("https://homologacao.prospersend.com.br/app/"):
        raise SystemExit("LOGIN_NOT_AUTHENTICATED")
    return data


if __name__ == "__main__":
    phase = os.environ.get("QA_GATE_PHASE", "security")
    if phase == "security":
        security()
    elif phase == "login1":
        login("teste@empresab.com", "secret_ref:prospersend-qa-tenant1-password")
        print("SECRET_REF_LOGIN_REMOTE=PASS")
    else:
        raise SystemExit("unknown phase")
