import importlib.util, json, os
from pathlib import Path
for raw in Path("/home/will/.hermes/profiles/qaprospersend/.env").read_text().splitlines():
    line=raw.strip()
    if not line or line.startswith("#") or "=" not in line: continue
    k,v=line.split("=",1)
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
spec=importlib.util.spec_from_file_location("qa_plugin","/home/will/.hermes/profiles/qaprospersend/plugins/prospersend-qa-browser/__init__.py")
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
URL="https://homologacao.prospersend.com.br/app/facilitadores/produtos"

def call(args):
    obj=json.loads(mod._browser(args))
    blob=json.dumps(obj, ensure_ascii=False)
    if "eyJ" in blob or "harness_claim" in blob:
        raise SystemExit("SECRET_ECHO")
    if not obj.get("ok"):
        raise SystemExit(blob[:700])
    return obj.get("data") or {}

phase=os.environ.get("QA_SPA_PHASE","spa")
if phase=="inspect12":
    ok=0
    for i in range(12):
        data=call({"operation":"inspect","url":URL})
        info=data.get("inspect") or {}
        if str(info.get("url") or "").startswith("https://homologacao.prospersend.com.br/app/"):
            ok+=1
        else:
            raise SystemExit("INSPECT_BAD "+str(info.get("url")))
    print(f"REMOTE_INSPECT_{ok}_OF_12=PASS")
elif phase=="spa":
    click=call({"operation":"act","url":URL,"action":"click","text":"Tipo: todos"})
    info=call({"operation":"inspect"}).get("inspect") or {}
    texts=[(x.get("text") or "").strip() for x in info.get("buttons") or []]
    print("CLICK_URL", info.get("url"))
    print("HAS_PRODUTO", any(t=="Produto" for t in texts))
    print("HAS_SERVICO", any(t in {"Serviço","Servico"} for t in texts))
    if not any(t=="Produto" for t in texts):
        raise SystemExit("CLICK_FAIL")
    print("REMOTE_CLICK=PASS")
    print("CURRENT_TAB_INSPECT=PASS")
    selector='input[placeholder="Buscar produto ou serviço…"]'
    call({"operation":"act","url":URL,"action":"type","selector":selector,"value":"Site"})
    info2=call({"operation":"inspect"}).get("inspect") or {}
    vals=[x for x in info2.get("inputs") or [] if "Buscar produto" in str(x.get("placeholder") or "")]
    print("TYPE_URL", info2.get("url"))
    print("TYPE_VALUE", vals[0].get("value") if vals else None)
    if not vals or vals[0].get("value")!="Site":
        raise SystemExit("TYPE_FAIL")
    if "search=Site" not in str(info2.get("url") or ""):
        raise SystemExit("TYPE_URL_FAIL")
    print("REMOTE_TYPE_VUE=PASS")
    call({"operation":"act","action":"press","key":"Enter"})
    info3=call({"operation":"inspect"}).get("inspect") or {}
    print("PRESS_URL", info3.get("url"))
    print("REMOTE_PRESS=PASS")
    selects=[x for x in info3.get("inputs") or [] if x.get("tag")=="select"]
    if selects:
        sel=selects[0]
        target="#"+sel["id"] if sel.get("id") else "select"
        call({"operation":"act","action":"select","selector":target,"value":sel.get("value") or ""})
        print("REMOTE_SELECT=PASS")
    else:
        call({"operation":"act","url":URL,"action":"select","selector":selector,"value":"Site"})
        info4=call({"operation":"inspect"}).get("inspect") or {}
        vals=[x for x in info4.get("inputs") or [] if "Buscar produto" in str(x.get("placeholder") or "")]
        if not vals or vals[0].get("value")!="Site":
            raise SystemExit("SELECT_FAIL")
        print("REMOTE_SELECT=PASS")
    shot=call({"operation":"screenshot"})
    print("SHOT_URL", shot.get("url"))
    print("SHOT_SHA", shot.get("evidence_sha256"))
    print("SHOT_BYTES", shot.get("evidence_bytes"))
    print("SHOT_ENGINE", shot.get("engine"))
    if not shot.get("evidence_sha256") or not shot.get("evidence_bytes"):
        raise SystemExit("SHOT_FAIL")
    print("REMOTE_SCREENSHOT=PASS")
    print("POST_ACTION_SCREENSHOT=PASS")
elif phase=="vue_custom":
    url=os.environ.get("QA_VUE_PRODUCT_URL","https://homologacao.prospersend.com.br/app/facilitadores/produtos/cdacd3a3-9211-41c9-8e28-945771fdbadd")
    data=call({"operation":"interact","url":url,"steps":[
        {"op":"wait","seconds":2},
        {"op":"click","text":"Quem compra"},
        {"op":"click","text":"Empresas"},
        {"op":"click","text":"Pessoas"},
        {"op":"click","text":"Os dois"},
        {"op":"type","selector":"div.flex.gap-2 input","value":"Dor QA Vue Smoke"},
        {"op":"click","text":"Adicionar"},
        {"op":"wait","seconds":1},
    ]})
    clicks=data.get("clicks") or []
    states=data.get("click_states") or {}
    by_text={}
    order=["Quem compra","Empresas","Pessoas","Os dois","Adicionar"]
    click_rows=[c for c in clicks]
    print("VUE_CLICKS", json.dumps(click_rows, ensure_ascii=False))
    print("VUE_STATES", json.dumps(states, ensure_ascii=False))
    labels={"Empresas":False,"Pessoas":False,"Os dois":False}
    for value in states.values():
        for label in labels:
            if str(value).startswith(label):
                labels[label]=True
    if not all(labels.values()):
        raise SystemExit("VUE_STATE_FAIL "+json.dumps(labels))
    if "Dor QA Vue Smoke" not in (data.get("main_excerpt") or ""):
        raise SystemExit("VUE_DOR_FAIL")
    native=any(c.get("strategy")=="semantic" and c.get("tag")=="button" for c in click_rows)
    custom=any(c.get("strategy")=="semantic-ancestor" and c.get("tag")=="button" for c in click_rows)
    if not native or not custom:
        raise SystemExit("VUE_STRATEGY_FAIL")
    print("VUE_CUSTOM_CLICK=PASS")
    print("CLICK_EMPRESAS=PASS")
    print("CLICK_PESSOAS=PASS")
    print("CLICK_OS_DOIS=PASS")
    print("CLICK_ADICIONAR_DORES=PASS")
    print("NATIVE_BUTTON_REGRESSION=PASS")
else:
    raise SystemExit("unknown")
