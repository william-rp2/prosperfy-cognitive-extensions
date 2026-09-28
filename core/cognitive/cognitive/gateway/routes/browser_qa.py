"""QA Browser route: Cognitive -> private Browser Worker over Tailscale.

This route is authenticated by ActorContextDep and preserves the QA Browser
security model:
- only prospersend-qa-* secret refs may be materialized;
- materialization is one-time harness_claim, never plaintext to Hermes/LLM;
- worker is private Tailscale + dedicated bearer token;
- MFA/CAPTCHA/payment/destructive gates remain enforced by worker.py;
- screenshots are uploaded back to the QA profile through the private bridge.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import urllib.error
import urllib.request
import uuid
from typing import Any
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..deps import AUTH_HEADER_DOCS, ActorContextDep

router = APIRouter()

_ALLOWED_HOSTS = {
    "homologacao.prospersend.com.br",
    "api-homologacao.prospersend.com.br",
}


def _check_url(url: str) -> None:
    if not url:
        return
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in _ALLOWED_HOSTS:
        raise HTTPException(status_code=403, detail="url fora da allowlist")




class BrowserQaRequest(BaseModel):
    operation: str
    urls: list[str] = Field(default_factory=list)
    task: str = ""
    url: str = ""
    action: str = ""
    selector: str = ""
    text: str = ""
    value: str = ""
    key: str = ""
    seconds: float = 0.8
    fields: dict[str, Any] = Field(default_factory=dict)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    flag_profile: str = ""
    method: str = "GET"
    submit: bool = False
    accept_standard_terms: bool = False
    plan: str = "free"
    session_id: str = ""
    full: bool = False
    max_dim: int = Field(default=1600, ge=480, le=1800)
    attachment_name: str = ""
    label: str = ""
    placeholder: str = ""
    near_text: str = ""
    target_mode: str = ""
    dropzone_text: str = ""


def _unwrap_skill_result(result: Any) -> dict[str, Any]:
    payload = result.get("data", {}) if isinstance(result, dict) else {}
    if isinstance(payload, dict) and payload.get("status") == "success":
        payload = payload.get("data", {})
    return payload if isinstance(payload, dict) else {}


async def _materialize_fields(
    request: Request,
    body: BrowserQaRequest,
    ctx,
) -> tuple[dict[str, Any], list[str]]:
    if not body.fields:
        return {}, []
    adapter = request.app.state.skills_adapter
    domain = (urlparse(body.url).hostname or "").strip().lower()
    out: dict[str, Any] = {}
    mids: list[str] = []
    for selector, value in body.fields.items():
        if not (isinstance(value, str) and value.startswith("secret_ref:")):
            out[selector] = value
            continue
        secret_id = value.split(":", 1)[1].strip()
        if not secret_id.startswith("prospersend-qa-"):
            raise HTTPException(status_code=403, detail="secret_ref fora do prefixo QA permitido")
        raw = await adapter.invoke_tool(
            "prosperfy_secret_materialize",
            {
                "secret_id": secret_id,
                "target": "harness_inject",
                "purpose": "qa-browser-fill",
                "ttl_seconds": 180,
                "harness": {
                    "domain": domain,
                    "selector": str(selector),
                    "field_ref": str(selector),
                },
                "actor": "qaprospersend",
                "reason": "QA Browser one-time secret fill",
            },
            ctx.tenant_id,
            ctx.correlation_id,
        )
        payload = _unwrap_skill_result(raw)
        claim = str(payload.get("harness_claim_token") or "")
        mid = str(payload.get("materialize_id") or "")
        if payload.get("status") != "materialized" or not claim or not mid:
            raise HTTPException(status_code=502, detail="secret materialize não emitiu claim one-time")
        out[selector] = {"harness_claim_token": claim, "materialize_id": mid}
        mids.append(mid)
    return out, mids


async def _cleanup(request: Request, ctx, mids: list[str]) -> None:
    adapter = request.app.state.skills_adapter
    for mid in mids:
        try:
            await adapter.invoke_tool(
                "prosperfy_secret_dematerialize",
                {
                    "materialize_id": mid,
                    "actor": "qaprospersend",
                    "reason": "QA Browser one-time cleanup",
                },
                ctx.tenant_id,
                ctx.correlation_id,
            )
        except Exception:
            pass



def _is_transient(data: dict[str, Any]) -> bool:
    if data.get("success") is True:
        return False
    err = str(data.get("error") or "").lower()
    return any(
        marker in err
        for marker in (
            "timeout", "timed out", "ipc", "transport",
            "connection reset", "broken pipe", "inspect_failed",
            "worker_error",
        )
    )


def run_with_failover(remote_healthy: bool, send_remote, send_local) -> dict[str, Any]:
    """Primary remote, one retry on transient failure, then local."""
    if remote_healthy:
        remote = None
        for _attempt in range(2):
            try:
                remote = send_remote()
            except Exception:
                remote = None
                continue
            if isinstance(remote, dict) and not _is_transient(remote):
                return remote
    try:
        return send_local()
    except Exception as exc:
        raise RuntimeError("QA_BROWSER_UNAVAILABLE") from exc


async def _worker(job: dict[str, Any]) -> dict[str, Any]:
    base = os.getenv("BROWSER_WORKER_URL", "").strip().rstrip("/")
    token = os.getenv("BROWSER_WORKER_TOKEN", "").strip()
    local_worker = os.getenv(
        "QA_LOCAL_BROWSER_WORKER",
        "/home/will/.hermes/local-browser-worker.py",
    ).strip()

    def remote_healthy() -> bool:
        if not base:
            return False
        req = urllib.request.Request(base + "/health", method="GET")
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.load(resp)
            return isinstance(data, dict) and str(data.get("status") or "").lower() == "ok"
        except Exception:
            return False

    def send_remote() -> dict[str, Any]:
        if not base or not token:
            raise RuntimeError("Browser Worker privado não configurado")
        req = urllib.request.Request(
            base + "/run",
            data=json.dumps(job, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Browser Worker HTTP {exc.code}") from None
        if not isinstance(data, dict):
            raise RuntimeError("Browser Worker retornou payload inválido")
        data.setdefault("engine", "browser-harness-remote")
        return data

    def send_local() -> dict[str, Any]:
        if not local_worker or not os.path.isfile(local_worker):
            raise RuntimeError("Local Browser Worker não configurado")
        proc = subprocess.run(
            ["/usr/bin/python3", local_worker],
            input=json.dumps(job, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=150,
            check=False,
        )
        lines = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
        data = None
        for line in reversed(lines):
            try:
                parsed = json.loads(line)
            except Exception:
                continue
            if isinstance(parsed, dict):
                data = parsed
                break
        if not isinstance(data, dict):
            raise RuntimeError("Local Browser Worker retornou payload inválido")
        data.setdefault("engine", "browser-local")
        return data

    try:
        return await asyncio.to_thread(
            run_with_failover,
            remote_healthy(),
            send_remote,
            send_local,
        )
    except Exception:
        raise HTTPException(status_code=502, detail="QA_BROWSER_UNAVAILABLE") from None


@router.post(
    "/v1/browser/qa",
    tags=["browser"],
    summary="QA Browser Harness execution through private worker",
    openapi_extra={"parameters": AUTH_HEADER_DOCS},
)
async def browser_qa(
    body: BrowserQaRequest,
    ctx: ActorContextDep,
    request: Request,
) -> dict[str, Any]:
    op = body.operation.strip().lower()
    allowed = {"read", "act", "create_account", "screenshot", "inspect", "interact", "upload", "qa_flags", "api_read", "network_read"}
    if op not in allowed:
        raise HTTPException(status_code=422, detail="operation não suportada")

    if op == "qa_flags":
        profile = body.flag_profile.strip().lower()
        allowed_profiles = {
            "status", "restore", "all_on",
            "produtos_off", "estrategias_off", "aprendizados_off",
        }
        if profile not in allowed_profiles:
            raise HTTPException(status_code=422, detail="flag_profile inválido")

        ssh_host = os.getenv("QA_FLAGS_SSH_HOST", "46.225.5.64").strip()
        ssh_key = os.getenv(
            "QA_FLAGS_SSH_KEY",
            "/home/will/.hermes/keys/prospersend-qa-flags",
        ).strip()

        def run_flag_gate() -> dict[str, Any]:
            proc = subprocess.run(
                [
                    "ssh",
                    "-i", ssh_key,
                    "-o", "BatchMode=yes",
                    "-o", "ConnectTimeout=8",
                    "-o", "StrictHostKeyChecking=accept-new",
                    f"root@{ssh_host}",
                    profile,
                ],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            if proc.returncode != 0:
                raise RuntimeError("qa_flags ssh gate failed")
            lines = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
            if not lines:
                raise RuntimeError("qa_flags ssh gate empty")
            payload = json.loads(lines[-1])
            if not isinstance(payload, dict) or payload.get("ok") is not True:
                raise RuntimeError("qa_flags ssh gate invalid")
            return payload

        try:
            data = await asyncio.to_thread(run_flag_gate)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"qa_flags Cognitive gate {type(exc).__name__}",
            ) from None

        return {"ok": True, "operation": op, "data": data}

    _check_url(body.url)
    for item in body.urls:
        _check_url(item)
    if op == "network_read":
        op = "api_read"

    mids: list[str] = []
    try:
        fields, mids = await _materialize_fields(request, body, ctx)
        job_id = f"{ctx.tenant_id}-{uuid.uuid4().hex}"

        if op == "api_read":
            if not body.url:
                raise HTTPException(status_code=422, detail="url obrigatório")
            method = (body.method or "GET").strip().upper()
            if method not in {"GET", "HEAD"}:
                raise HTTPException(status_code=422, detail="api_read aceita somente GET ou HEAD")
            job = {
                "job_id": job_id,
                "correlation_id": ctx.correlation_id,
                "action": "api_read",
                "url": body.url,
                "method": method,
            }
        elif op == "read":
            if not body.urls:
                raise HTTPException(status_code=422, detail="urls obrigatório")
            job = {
                "job_id": job_id,
                "correlation_id": ctx.correlation_id,
                "action": "read_links",
                "urls": body.urls,
                "task": body.task,
            }
        elif op == "act":
            if fields and not body.url:
                raise HTTPException(status_code=422, detail="url obrigatório")
            if fields:
                job = {
                    "job_id": job_id,
                    "correlation_id": ctx.correlation_id,
                    "action": "fill_form",
                    "url": body.url,
                    "fields": fields,
                    "submit": body.submit,
                    "submit_selector": "form button[type='submit'],form input[type='submit'],form button:not([type])" if body.submit else "",
                }
            else:
                action = body.action.strip().lower()
                task = body.task.strip()
                task_target = task
                if not action and task:
                    first, sep, rest = task.partition(" ")
                    if first.lower() in {"click", "type", "select", "press", "wait"}:
                        action = first.lower()
                        task_target = rest.strip()
                if action not in {"click", "type", "select", "press", "wait"}:
                    raise HTTPException(
                        status_code=422,
                        detail="act sem fields exige action click/type/select/press/wait",
                    )
                step: dict[str, Any] = {"op": action}
                if action == "click":
                    if body.selector:
                        step["selector"] = body.selector
                    else:
                        target = body.text.strip() or task_target
                        if not target:
                            raise HTTPException(status_code=422, detail="click exige selector/text/task")
                        for prefix in ("no botão ", "no botao ", "botão ", "botao ", "em "):
                            if target.lower().startswith(prefix):
                                target = target[len(prefix):].strip()
                                break
                        step["text"] = target
                elif action in {"type", "select"}:
                    has_target = any(str(getattr(body, key, "") or "").strip() for key in ("selector", "label", "placeholder", "near_text", "target_mode"))
                    if not has_target: raise HTTPException(status_code=422, detail=f"{action} exige selector, label, placeholder, near_text ou target_mode")
                    if body.selector: step["selector"]=body.selector
                    if body.label: step["label"]=body.label
                    if body.placeholder: step["placeholder"]=body.placeholder
                    if body.near_text: step["near_text"]=body.near_text
                    if body.target_mode: step["target_mode"]=body.target_mode
                    step["value"]=body.value if body.value!="" else (body.text or task_target)
                elif action == "press":
                    key = body.key.strip() or body.text.strip() or task_target
                    if not key:
                        raise HTTPException(status_code=422, detail="press exige key")
                    step["key"] = key
                elif action == "wait":
                    step["seconds"] = max(0.0, min(float(body.seconds or 0.8), 10.0))
                job = {
                    "job_id": job_id,
                    "correlation_id": ctx.correlation_id,
                    "action": "interact",
                    "url": body.url,
                    "steps": [step],
                }
        elif op == "create_account":
            if not body.url or not fields:
                raise HTTPException(status_code=422, detail="url e fields obrigatórios")
            job = {
                "job_id": job_id,
                "correlation_id": ctx.correlation_id,
                "action": "create_account",
                "url": body.url,
                "fields": fields,
                "submit": body.submit,
                "submit_selector": "form button[type='submit'],form input[type='submit'],form button:not([type])" if body.submit else "",
                "accept_standard_terms": body.accept_standard_terms,
                "plan": body.plan or "free",
            }
        elif op == "interact":
            if not body.steps:
                raise HTTPException(status_code=422, detail="steps obrigatório")
            job = {
                "job_id": job_id,
                "correlation_id": ctx.correlation_id,
                "action": "interact",
                "url": body.url,
                "steps": body.steps,
            }
        elif op == "upload":
            upload_target = bool(body.selector or body.text or body.dropzone_text)
            if not body.attachment_name or not upload_target:
                raise HTTPException(status_code=422, detail="upload exige attachment_name e selector, text ou dropzone_text")
            root = Path(
                os.getenv(
                    "QA_ATTACHMENTS_ROOT",
                    "/home/will/.hermes/profiles/qaprospersend/attachments",
                )
            ).resolve()
            candidate = (root / body.attachment_name).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                raise HTTPException(status_code=403, detail="attachment fora do escopo QA") from None
            if not candidate.is_file():
                raise HTTPException(status_code=404, detail="attachment não encontrado")
            size = candidate.stat().st_size
            if size > 25 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="attachment acima de 25 MB")
            content_b64 = base64.b64encode(candidate.read_bytes()).decode("ascii")
            job = {
                "job_id": job_id,
                "correlation_id": ctx.correlation_id,
                "action": "upload_file",
                "url": body.url,
                "selector": body.selector,
                "text": body.text or body.dropzone_text,
                "dropzone_text": body.dropzone_text,
                "filename": candidate.name,
                "content_b64": content_b64,
            }
        elif op == "screenshot":
            job = {
                "job_id": job_id,
                "correlation_id": ctx.correlation_id,
                "action": "screenshot",
                "url": body.url,
                "full": body.full,
                "max_dim": body.max_dim,
            }
        else:
            job = {
                "job_id": job_id,
                "correlation_id": ctx.correlation_id,
                "action": "inspect",
                "url": body.url,
            }

        result = await _worker(job)
        return {"ok": bool(result.get("success")), "operation": op, "data": result}
    finally:
        await _cleanup(request, ctx, mids)