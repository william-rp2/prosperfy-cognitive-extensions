"""Accessible editable field resolution for QA browser worker."""
from __future__ import annotations

import json
from typing import Any


def _norm(text: str) -> str:
    return " ".join(str(text or "").split())


def _hint_str(hints: dict[str, Any], key: str) -> str:
    if not isinstance(hints, dict):
        return ""
    return _norm(hints.get(key) or "")


def pick_editable_target(candidates: list[dict], hints: dict[str, Any]) -> dict | None:
    if not isinstance(candidates, list) or not candidates:
        return None
    selector = _hint_str(hints, "selector")
    label = _hint_str(hints, "label")
    placeholder = _hint_str(hints, "placeholder")
    near_text = _hint_str(hints, "near_text")
    name = _hint_str(hints, "name")
    aria_label = _hint_str(hints, "aria_label") or _hint_str(hints, "aria-label")
    target_mode = str(hints.get("target_mode") or "").strip().lower()
    want_active = bool(hints.get("active"))

    pool: list[dict] = []
    for idx, raw in enumerate(candidates):
        if not isinstance(raw, dict) or raw.get("disabled") or not raw.get("visible", True):
            continue
        item = dict(raw)
        item["_idx"] = idx
        pool.append(item)
    if not pool:
        return None

    def match_one(item: dict) -> tuple[bool, str]:
        if selector and str(item.get("selector") or "") == selector:
            return True, "selector"
        if name and _norm(item.get("name") or "") == name:
            return True, "name"
        if placeholder and _norm(item.get("placeholder") or "") == placeholder:
            return True, "placeholder"
        if aria_label and _norm(item.get("aria") or item.get("aria_label") or "") == aria_label:
            return True, "aria-label"
        if label:
            lab = _norm(item.get("label") or item.get("label_text") or "")
            if lab == label or (label in lab and len(lab) <= len(label) + 48):
                return True, "label"
        if near_text and near_text in _norm(item.get("near_text") or item.get("context") or ""):
            return True, "near_text"
        if target_mode == "editable_any" and item.get("editable"):
            return True, "editable_any"
        return False, ""

    matched: list[tuple[dict, str]] = []
    for item in pool:
        ok, strategy = match_one(item)
        if ok:
            matched.append((item, strategy))
    if want_active:
        active_only = [pair for pair in matched if pair[0].get("active")]
        if active_only:
            matched = active_only
    if not matched:
        return None

    tier = {
        "selector": 10,
        "label": 9,
        "aria-label": 8,
        "placeholder": 7,
        "name": 6,
        "near_text": 5,
        "editable_any": 4,
    }

    def score(pair: tuple[dict, str]) -> tuple:
        item, strategy = pair
        area = float(item.get("width") or 0) * float(item.get("height") or 0)
        return (-tier.get(strategy, 0), -area, item["_idx"])

    matched.sort(key=score)
    chosen, strategy = matched[0]
    return {
        "found": True,
        "tag": str(chosen.get("tag") or ""),
        "strategy": strategy,
        "selector": str(chosen.get("selector") or ""),
        "contenteditable": bool(chosen.get("contenteditable")),
    }


def resolve_editable_target_js(hints: dict[str, Any]) -> str:
    payload = json.dumps(
        {
            "selector": _hint_str(hints, "selector"),
            "label": _hint_str(hints, "label"),
            "placeholder": _hint_str(hints, "placeholder"),
            "near_text": _hint_str(hints, "near_text"),
            "name": _hint_str(hints, "name"),
            "aria_label": _hint_str(hints, "aria_label") or _hint_str(hints, "aria-label"),
            "target_mode": str(hints.get("target_mode") or ""),
            "active": bool(hints.get("active")),
        }
    )
    return (
        "(function(){var H=" + payload + ";"
        "function norm(s){return String(s||'').replace(/[ \\t\\r\\n]+/g,' ').trim();}"
        "function vis(el){if(!el||el.disabled||el.getAttribute('aria-disabled')==='true')return false;"
        "var r=el.getBoundingClientRect();if(r.width<2||r.height<2)return false;"
        "var s=getComputedStyle(el);if(s.visibility==='hidden'||s.display==='none'||s.pointerEvents==='none')return false;return true;}"
        "function editable(el){if(!el)return false;var tag=el.tagName.toLowerCase();"
        "if(tag==='textarea'||tag==='select')return true;if(tag==='input'){var tp=(el.type||'text').toLowerCase();"
        "return tp!=='hidden'&&tp!=='file'&&tp!=='submit'&&tp!=='button';}"
        "return !!(el.isContentEditable||el.getAttribute('contenteditable')==='true');}"
        "function rootPanel(){return document.querySelector('[role=tabpanel]:not([hidden])')||document;}"
        "function labelFor(el){var id=el.id;if(id){var lb=document.querySelector('label[for=\"'+id+'\"]');"
        "if(lb)return norm(lb.innerText||lb.textContent||'');}var wrap=el.closest('label');"
        "if(wrap)return norm(wrap.innerText||wrap.textContent||'');var lid=el.getAttribute('aria-labelledby');"
        "if(lid){var parts=lid.split(/\\s+/).map(function(x){var n=document.getElementById(x);"
        "return n?norm(n.innerText||n.textContent||''):'';}).filter(Boolean);if(parts.length)return parts.join(' ');}"
        "return '';}"
        "function nearText(el){var p=el.parentElement;var hops=0;var bits=[];while(p&&hops<3){"
        "bits.push(norm(p.innerText||p.textContent||''));p=p.parentElement;hops++;}return bits.join(' ').slice(0,240);}"
        "function sel(el){if(el.id)return '#'+CSS.escape(el.id);var tag=el.tagName.toLowerCase();"
        "var nm=el.getAttribute('name');if(nm)return tag+'[name=\"'+nm+'\"]';return tag;}"
        "function cand(el){var r=el.getBoundingClientRect();return {el:el,tag:el.tagName.toLowerCase(),selector:sel(el),"
        "placeholder:norm(el.placeholder||''),name:norm(el.name||''),aria:norm(el.getAttribute('aria-label')||''),"
        "label:labelFor(el),near_text:nearText(el),editable:editable(el),"
        "contenteditable:!!(el.isContentEditable||el.getAttribute('contenteditable')==='true'),"
        "active:document.activeElement===el,width:r.width,height:r.height,visible:vis(el)};}"
        "function score(c,st){var tier={selector:10,label:9,'aria-label':8,placeholder:7,name:6,near_text:5,editable_any:4}[st]||0;"
        "return tier*10000+c.width*c.height;}"
        "var root=rootPanel();var nodes=root.querySelectorAll('input,textarea,select,[contenteditable=\"true\"],[contenteditable=\"\"]');"
        "var list=[];for(var i=0;i<nodes.length;i++){var el=nodes[i];if(!editable(el))continue;var c=cand(el);"
        "if(H.active&&!c.active)continue;list.push(c);}"
        "if(H.selector){var q=root.querySelector(H.selector)||document.querySelector(H.selector);"
        "if(q&&editable(q)){var cq=cand(q);cq.el.scrollIntoView({block:'center',inline:'center'});"
        "var rr=cq.el.getBoundingClientRect();return {found:true,strategy:'selector',tag:cq.tag,selector:cq.selector,"
        "contenteditable:cq.contenteditable,x:rr.left+cq.width/2,y:rr.top+cq.height/2};}}"
        "var best=null,bst=-1,bstr='';for(var j=0;j<list.length;j++){var c=list[j];if(!c.visible)continue;var st='';"
        "if(H.name&&c.name===norm(H.name))st='name';else if(H.placeholder&&c.placeholder===norm(H.placeholder))st='placeholder';"
        "else if(H.aria_label&&c.aria===norm(H.aria_label))st='aria-label';"
        "else if(H.label&&(c.label===norm(H.label)||c.label.indexOf(norm(H.label))>=0))st='label';"
        "else if(H.near_text&&c.near_text.indexOf(norm(H.near_text))>=0)st='near_text';"
        "else if((H.target_mode||'').toLowerCase()==='editable_any'&&c.editable)st='editable_any';"
        "if(!st)continue;var sc=score(c,st);if(sc>bst){bst=sc;best=c;bstr=st;}}"
        "if(!best)return {found:false};best.el.scrollIntoView({block:'center',inline:'center'});"
        "var br=best.el.getBoundingClientRect();return {found:true,strategy:bstr,tag:best.tag,selector:best.selector,"
        "contenteditable:best.contenteditable,x:br.left+best.width/2,y:br.top+best.height/2};})()"
    )


def editable_candidates_js() -> str:
    return (
        "(function(){function norm(s){return String(s||'').replace(/[ \\t\\r\\n]+/g,' ').trim();}"
        "function vis(el){if(!el||el.disabled)return false;var r=el.getBoundingClientRect();"
        "if(r.width<2||r.height<2)return false;var s=getComputedStyle(el);"
        "if(s.visibility==='hidden'||s.display==='none')return false;return true;}"
        "function editable(el){var tag=el.tagName.toLowerCase();if(tag==='textarea'||tag==='select')return true;"
        "if(tag==='input'){var tp=(el.type||'text').toLowerCase();"
        "return tp!=='hidden'&&tp!=='file'&&tp!=='submit'&&tp!=='button';}"
        "return !!(el.isContentEditable||el.getAttribute('contenteditable')==='true');}"
        "function rootPanel(){return document.querySelector('[role=tabpanel]:not([hidden])')||document;}"
        "function labelFor(el){var id=el.id;if(id){var lb=document.querySelector('label[for=\"'+id+'\"]');"
        "if(lb)return norm(lb.innerText||'');}var w=el.closest('label');return w?norm(w.innerText||''):'';}"
        "function sel(el){if(el.id)return '#'+CSS.escape(el.id);var tag=el.tagName.toLowerCase();"
        "var nm=el.name;if(nm)return tag+'[name=\"'+nm+'\"]';return tag;}"
        "var root=rootPanel();var out=[];"
        "var nodes=root.querySelectorAll('input,textarea,select,[contenteditable=\"true\"],[contenteditable=\"\"]');"
        "for(var i=0;i<nodes.length;i++){var el=nodes[i];if(!editable(el)||!vis(el))continue;"
        "var r=el.getBoundingClientRect();out.push({index:i,tag:el.tagName.toLowerCase(),type:el.type||'',"
        "id:el.id||'',name:el.name||'',placeholder:el.placeholder||'',label:labelFor(el).slice(0,120),"
        "aria:el.getAttribute('aria-label')||'',selector:sel(el),contenteditable:!!(el.isContentEditable||"
        "el.getAttribute('contenteditable')==='true'),editable:true,visible:true,width:r.width,height:r.height,"
        "active:document.activeElement===el,near_text:''});if(out.length>=80)break;}return JSON.stringify(out);})()"
    )


def file_inputs_js() -> str:
    return (
        "(function(){function norm(s){return String(s||'').replace(/[ \\t\\r\\n]+/g,' ').trim();}"
        "var nodes=document.querySelectorAll('input[type=file]');var out=[];"
        "for(var i=0;i<nodes.length;i++){var el=nodes[i];var r=el.getBoundingClientRect();var s=getComputedStyle(el);"
        "var vis=r.width>2&&r.height>2&&s.visibility!=='hidden'&&s.display!=='none';"
        "var dz=el.closest('[data-qa-dropzone],[class*=dropzone],[class*=upload]');"
        "out.push({index:i,id:el.id||'',name:el.name||'',accept:el.accept||'',multiple:!!el.multiple,visible:vis,"
        "marked:el.getAttribute('data-qa-file-target')==='1',"
        "selector:el.id?'#'+CSS.escape(el.id):'input[type=file]:nth-of-type('+(i+1)+')',"
        "dropzone_text:dz?norm(dz.innerText||'').slice(0,160):''});if(out.length>=40)break;}"
        "return JSON.stringify(out);})()"
    )


def step_field_hints(raw_step: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_step, dict):
        return {}
    out: dict[str, Any] = {}
    for key in (
        "selector", "label", "placeholder", "near_text", "target_mode", "active", "name", "aria_label", "aria-label",
    ):
        val = raw_step.get(key)
        if val not in (None, ""):
            out[key] = val
    return out


def uses_field_resolver(raw_step: dict[str, Any]) -> bool:
    hints = step_field_hints(raw_step)
    if hints.get("selector"):
        return True
    for key in ("label", "placeholder", "near_text", "target_mode", "active"):
        if hints.get(key) not in (None, "", False):
            return True
    return False


def _harness_js_fill(idx: int, value: str, mode: str) -> str:
    val = json.dumps(value)
    i = str(idx)
    if mode == "select":
        body = (
            "print('===STEP" + i + "===', js('(function(){var e=document.querySelector('+json.dumps(_s_"
            + i
            + ")+');if(!e)return \"missing\";var p=Object.getPrototypeOf(e);"
            "var d=Object.getOwnPropertyDescriptor(p,\\\"value\\\");"
            "if(d&&d.set){d.set.call(e," + val + ");}else{e.value=" + val + ";}"
            "try{e.dispatchEvent(new InputEvent(\\\"input\\\",{bubbles:true,inputType:\\\"insertText\\\",data:"
            + val
            + "}));}catch(_){e.dispatchEvent(new Event(\\\"input\\\",{bubbles:true}));}"
            "e.dispatchEvent(new Event(\\\"change\\\",{bubbles:true}));return e.value;})()'))"
        )
        return body
    body = (
        "  print('===STEP" + i + "===', js('(function(){var e=document.querySelector('+json.dumps(_s_"
        + i
        + ")+');if(!e)return \"missing\";var v=" + val + ";e.focus();e.textContent=v;"
        "try{e.dispatchEvent(new InputEvent(\\\"input\\\",{bubbles:true,inputType:\\\"insertText\\\",data:v}));}"
        "catch(_){e.dispatchEvent(new Event(\\\"input\\\",{bubbles:true}));}return \"ce\";})()'))"
    )
    return body


def build_fill_step_lines(idx: int, raw_step: dict[str, Any]) -> list[str]:
    op = str(raw_step.get("op") or "type").strip().lower()
    value = str(raw_step.get("value") or "")
    hints = step_field_hints(raw_step)
    lines = [
        f"_field_target_{idx}=js({resolve_editable_target_js(hints)!r})",
        f"if not _field_target_{idx} or _field_target_{idx}.get('found') is False: raise RuntimeError('editable target missing')",
        f"_s_{idx}=_field_target_{idx}.get('selector') or ''",
    ]
    if op == "select":
        lines.append(_harness_js_fill(idx, value, "select"))
        lines.append("wait(0.8)")
        return lines
    lines.append(f"if _field_target_{idx}.get('contenteditable'):")
    lines.append(_harness_js_fill(idx, value, "type"))
    lines.append("else:")
    lines.append(f"  fill_input(_s_{idx}, {value!r}, clear_first=True, timeout=8.0)")
    lines.append(f"  print('===STEP{idx}=== typed')")
    lines.append("wait(0.8)")
    return lines


def build_wait_enabled_lines(idx: int, text: str, timeout: float) -> list[str]:
    try:
        sec = max(0.0, min(float(timeout), 30.0))
    except Exception:
        sec = 8.0
    query = json.dumps(_norm(text))
    poll_js = (
        "(function(){var t="
        + query
        + ";var deadline=Date.now()+"
        + str(int(sec * 1000))
        + ";function norm(s){return String(s||'').replace(/[\\t\\r\\n ]+/g,' ').trim();}"
        "while(Date.now()<deadline){var nodes=document.querySelectorAll('button,input,select,textarea,[role=button]');"
        "for(var i=0;i<nodes.length;i++){var el=nodes[i];if(el.disabled||el.getAttribute('aria-disabled')==='true')continue;"
        "var label=norm(el.innerText||el.value||el.getAttribute('aria-label')||'');"
        "if(label===t||label.indexOf(t)>=0)return true;} }return false;})()"
    )
    return [
        f"_wait_enabled_{idx}=js({poll_js!r})",
        f"if not _wait_enabled_{idx}: raise RuntimeError('wait_enabled timeout')",
        f"print('===STEP{idx}=== wait_enabled ok')",
    ]
