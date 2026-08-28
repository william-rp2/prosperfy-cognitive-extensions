"""
adapters/browser_harness/client.py -- BrowserAdapter real (Track BH).

Implementa SkillsAdapterPort (mesmo contrato de ProsperfySkillsAdapter) para
que ExecutionOrchestrator possa despachar browser.read/act/account pelo
mesmo pipeline Registry -> Grant -> Policy -> Adapter -> Audit -> Telemetry
das capabilities infra.* (execution/orchestrator.py, adapter_registry --
ver ADR de dispatch por capability.adapter).

Transporte: NAO abre uma conexao propria. Compoe um SkillsAdapterPort ja
existente (tipicamente ProsperfySkillsAdapter) e reusa
prosperfy_vps_escrever_arquivo / prosperfy_vps_executar -- o mesmo
transporte MCP ja guardado/testado -- para:
  1. escrever o job JSON num arquivo temporario no host do Browser Worker;
  2. rodar `python3 <worker_path> < <jobfile>` sob BU_CDP_URL;
  3. ler a UNICA linha JSON que o worker imprime em stdout (contrato em
     ops/browser-worker/worker.py) e devolve-la como resultado estruturado.

O Browser Worker (host isolado, doc 00 Sec.5) e quem de fato resolve
secret_ref:<alias> e fala CDP com o Chrome dedicado -- este adapter nunca
ve um valor de secret, so a referencia que o caller (BrowserService/policy
de capability) ja preparou.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from ...contracts.capability import SkillsAdapterPort
from ...gate.redaction import sanitize_exception
from .guard import guard_browser_tool

logger = logging.getLogger(__name__)

_TOOL_TO_ACTION = {
    "browser_read_links": "read_links",
    "browser_fill_form": "fill_form",
    "browser_create_account": "create_account",
    "browser_doctor": "doctor",
}

_DEFAULT_WORKER_PATH = "/opt/browser-worker/worker.py"
_DEFAULT_JOBS_DIR = "/tmp/bh-jobs-in"
_DEFAULT_BU_CDP_URL = "http://127.0.0.1:9222"
_DEFAULT_EXEC_TIMEOUT = 120


class BrowserAdapter:
    """
    Adapter real para o Browser Worker isolado (doc 00 Sec.5).

    Implementa SkillsAdapterPort. Unico boundary do Cognitive para o
    Browser Worker -- nunca chama browser-harness/CDP diretamente daqui;
    sempre via o script remoto (ops/browser-worker/worker.py), que e quem
    aplica isolamento de job, timeout e o scan fail-closed antes de
    qualquer submit.
    """

    def __init__(
        self,
        inner_adapter: SkillsAdapterPort,
        host: str,
        worker_path: str = _DEFAULT_WORKER_PATH,
        jobs_dir: str = _DEFAULT_JOBS_DIR,
        bu_cdp_url: str = _DEFAULT_BU_CDP_URL,
        exec_timeout_seconds: int = _DEFAULT_EXEC_TIMEOUT,
    ) -> None:
        self._inner = inner_adapter
        self._host = host
        self._worker_path = worker_path
        self._jobs_dir = jobs_dir.rstrip("/")
        self._bu_cdp_url = bu_cdp_url
        self._exec_timeout_seconds = exec_timeout_seconds

    async def invoke_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        tenant_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        guard_browser_tool(tool_name, arguments)
        action = _TOOL_TO_ACTION[tool_name]

        job_id = f"{tenant_id}-{uuid.uuid4().hex}"
        job = {"job_id": job_id, "correlation_id": correlation_id, "action": action, **arguments}
        job_path = f"{self._jobs_dir}/{job_id}.json"

        try:
            await self._inner.invoke_tool(
                tool_name="prosperfy_vps_escrever_arquivo",
                arguments={
                    "host": self._host,
                    "caminho": job_path,
                    "conteudo": json.dumps(job, ensure_ascii=False) + "\n",
                    "confirmar": True,
                },
                tenant_id=tenant_id,
                correlation_id=correlation_id,
            )
            comando = (
                'export PATH="/root/.local/bin:$PATH"; '
                f'export BU_CDP_URL="{self._bu_cdp_url}"; '
                f"python3 {self._worker_path} < {job_path}; "
                f"rm -f {job_path}"
            )
            exec_result = await self._inner.invoke_tool(
                tool_name="prosperfy_vps_executar",
                arguments={
                    "host": self._host,
                    "comando": comando,
                    "confirmar": True,
                    "timeout": self._exec_timeout_seconds,
                },
                tenant_id=tenant_id,
                correlation_id=correlation_id,
            )
        except Exception as exc:
            raise RuntimeError(
                f"BrowserAdapter.invoke_tool falhou tool={tool_name}: {sanitize_exception(exc)}"
            ) from None

        return self._parse_worker_result(exec_result, job_id)

    @staticmethod
    def _parse_worker_result(exec_result: Any, job_id: str) -> dict[str, Any]:
        """Extrai a ultima linha JSON do stdout do worker (contrato de worker.py)."""
        stdout = ""
        if isinstance(exec_result, dict):
            data = exec_result.get("data", exec_result)
            if isinstance(data, dict):
                stdout = str(data.get("stdout", ""))
        lines = [line for line in stdout.strip().splitlines() if line.strip()]
        if not lines:
            raise RuntimeError(f"BrowserAdapter: worker sem stdout para job_id={job_id}")
        try:
            return json.loads(lines[-1])
        except json.JSONDecodeError as exc:
            # Nunca fabrica sucesso silencioso a partir de payload
            # desconhecido (mesmo principio do ProsperfySkillsAdapter).
            raise RuntimeError(
                f"BrowserAdapter: stdout do worker nao e JSON valido (job_id={job_id}): {exc}"
            ) from None

    async def health(self) -> bool:
        try:
            result = await self.invoke_tool(
                tool_name="browser_doctor",
                arguments={},
                tenant_id="__health__",
                correlation_id=str(uuid.uuid4()),
            )
        except Exception as exc:  # noqa: BLE001 -- health-check boundary, nunca propaga
            logger.warning("BrowserAdapter.health falhou: %s", sanitize_exception(exc))
            return False
        return bool(result.get("success") or result.get("chrome_reachable"))
