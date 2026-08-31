"""
finance/clarification_binding.py — binding determinístico de resposta do
owner -> clarification exata.

03_WHATSAPP_ACL_AND_CLARIFICATIONS.md §"Reply binding":

    outbound WhatsApp question
    -> persist delivery_message_id + clarification_id
    -> owner quotes/replies to message
    -> inbound reply references quoted message ID
    -> resolve exact clarification

Propriedades exigidas e como são obtidas aqui:

* "This must work hours or days later" / após restart: o vínculo
  delivery_message_id -> clarification_id é PERSISTIDO na Finance API
  (coluna delivery_message_id da clarification) e recuperado por consulta
  (`finance.clarification.list` com filtro deliveryMessageId). Nada é
  guardado em memória de processo, nada depende de sessão.
* "LLM conversation memory is irrelevant to exact binding": nenhuma etapa
  do caminho com quote consulta contexto conversacional. O identificador
  citado é metadado de transporte (ContextEnvelope.reply_to_message_id).
* §"Loose reply fallback": sem quote, busca um conjunto PEQUENO de
  pendências, exige confiança forte, e com duas ou mais plausíveis PERGUNTA
  qual — nunca resolve transação aleatória.
* §"Late reply": clarification já resolvida não sofre nova mutação; o
  caminho retorna ALREADY_RESOLVED sem chamar resolve.

Este módulo é puro: fala apenas com um `CapabilityCaller` (Protocol) que
executa capabilities finance.* — o mesmo contrato que FinanceService do
Hermes já implementa. Sem HTTP, sem LLM, sem transporte novo.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

logger = logging.getLogger(__name__)

CAP_LIST = "finance.clarification.list"
CAP_RESOLVE = "finance.clarification.resolve"

# Quantas pendências o fallback pode inspecionar. Deliberadamente pequeno:
# a spec pede "a small set of currently relevant/open clarifications".
DEFAULT_FALLBACK_LIMIT = 5

# Um candidato só é "forte" por texto quando cita explicitamente algo
# identificador (id de transação/clarification) ou quando há um único
# candidato aberto — nunca por semelhança vaga.
_STRONG_TOKEN_MIN = 1

_WORD_RE = re.compile(r"[a-z0-9]{3,}")

# Stopwords pt-BR curtas que jamais devem sozinhas caracterizar um match.
_STOPWORDS = frozenset(
    {
        "que", "com", "para", "dos", "das", "uma", "uns", "mas", "sim", "nao",
        "essa", "esse", "isso", "aquilo", "foi", "era", "ser", "the", "and",
    }
)


class BindingStatus(str, Enum):
    """Enum interno em inglês (texto ao usuário é pt-BR, montado fora daqui)."""

    RESOLVED = "resolved"
    ALREADY_RESOLVED = "already_resolved"
    AMBIGUOUS = "ambiguous"
    NO_CANDIDATES = "no_candidates"
    UNBOUND_QUOTE = "unbound_quote"


@dataclass(frozen=True)
class InboundReply:
    """Resposta do owner, já autorizada pela ACL e vinda do transporte."""

    text: str = ""
    reply_to_message_id: str = ""
    incoming_message_id: str = ""
    actor_id: str = ""
    competence_month: str = ""
    account: str = ""


@dataclass(frozen=True)
class BindingOutcome:
    status: BindingStatus
    clarification_id: str = ""
    message: str = ""  # pt-BR, pronto para o usuário
    candidates: list[dict[str, Any]] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)


class CapabilityCaller(Protocol):
    """Executa uma capability finance.* e devolve o `data` de sucesso."""

    async def call(self, capability_id: str, params: dict[str, Any]) -> dict[str, Any]: ...


def _normalize(text: str) -> str:
    lowered = text.lower()
    stripped = unicodedata.normalize("NFD", lowered)
    return "".join(ch for ch in stripped if unicodedata.category(ch) != "Mn")


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(_normalize(text)) if w not in _STOPWORDS}


def _candidate_haystack(candidate: dict[str, Any]) -> set[str]:
    parts = [
        str(candidate.get("merchant") or ""),
        str(candidate.get("originalDescription") or candidate.get("original_description") or ""),
        str(candidate.get("description") or ""),
    ]
    return _tokens(" ".join(parts))


def _identifiers(candidate: dict[str, Any]) -> set[str]:
    ids = {
        str(candidate.get("clarificationId") or candidate.get("clarification_id") or ""),
        str(candidate.get("transactionId") or candidate.get("transaction_id") or ""),
    }
    return {_normalize(i) for i in ids if i}


def _is_resolved(candidate: dict[str, Any]) -> bool:
    status = str(candidate.get("status") or "").lower()
    return status == "resolved" or bool(candidate.get("resolvedAt") or candidate.get("resolved_at"))


def _clarification_id(candidate: dict[str, Any]) -> str:
    return str(
        candidate.get("clarificationId")
        or candidate.get("clarification_id")
        or candidate.get("id")
        or ""
    )


def score_candidate(reply_text: str, candidate: dict[str, Any]) -> int:
    """Pontuação determinística. Sem LLM, sem embeddings, reprodutível.

    100  -> o texto cita explicitamente o id da clarification/transação
    N    -> N tokens significativos em comum com merchant/descrição
    """
    normalized = _normalize(reply_text)
    for identifier in _identifiers(candidate):
        if identifier and identifier in normalized:
            return 100
    return len(_tokens(reply_text) & _candidate_haystack(candidate))


class ClarificationBinder:
    """Liga a resposta do owner à clarification correta, deterministicamente."""

    def __init__(
        self,
        caller: CapabilityCaller,
        fallback_limit: int = DEFAULT_FALLBACK_LIMIT,
    ) -> None:
        self._caller = caller
        self._fallback_limit = fallback_limit

    async def bind(self, reply: InboundReply) -> BindingOutcome:
        """Caminho preferencial (quote) e, só se ele não vincular, o fallback."""
        if reply.reply_to_message_id:
            outcome = await self._bind_by_quote(reply)
            if outcome is not None:
                return outcome
            logger.info(
                "Quote sem clarification correspondente — caindo para fallback solto"
            )
        return await self._bind_loose(reply)

    # ---- caminho exato (quote) ----------------------------------------

    async def _bind_by_quote(self, reply: InboundReply) -> BindingOutcome | None:
        """None quando o message id citado não corresponde a clarification alguma.

        Consulta a Finance API, não a memória do processo nem o contexto do
        LLM: por isso funciona dias depois e após restart.
        """
        data = await self._caller.call(
            CAP_LIST,
            {"deliveryMessageId": reply.reply_to_message_id, "status": "any", "limit": 2},
        )
        candidates = list(data.get("clarifications") or [])
        if not candidates:
            return None

        candidate = candidates[0]
        clarification_id = _clarification_id(candidate)
        if not clarification_id:
            return None

        if _is_resolved(candidate):
            # §Late reply: NÃO duplica mutação — resolve nem é chamado.
            return BindingOutcome(
                status=BindingStatus.ALREADY_RESOLVED,
                clarification_id=clarification_id,
                message=(
                    "Essa pergunta já tinha sido respondida antes, então não "
                    "alterei nada de novo. Se quiser mudar o que ficou "
                    "registrado, é só me dizer o novo valor que eu aplico "
                    "como correção."
                ),
                data={"clarification": candidate},
            )

        return await self._resolve(clarification_id, reply)

    # ---- fallback solto ------------------------------------------------

    async def _bind_loose(self, reply: InboundReply) -> BindingOutcome:
        params: dict[str, Any] = {"status": "open", "limit": self._fallback_limit}
        if reply.competence_month:
            params["competenceMonth"] = reply.competence_month
        if reply.account:
            params["account"] = reply.account

        data = await self._caller.call(CAP_LIST, params)
        candidates = list(data.get("clarifications") or [])

        if not candidates:
            return BindingOutcome(
                status=BindingStatus.NO_CANDIDATES,
                message="Não há nenhuma pergunta financeira em aberto no momento.",
            )

        if len(candidates) == 1:
            # Sem ambiguidade possível: existe exatamente uma pendência.
            return await self._resolve(_clarification_id(candidates[0]), reply)

        scored = sorted(
            ((score_candidate(reply.text, c), c) for c in candidates),
            key=lambda pair: pair[0],
            reverse=True,
        )
        best_score, best = scored[0]
        runner_up_score = scored[1][0]

        # Confiança forte = pontuou acima do mínimo E estritamente melhor que
        # o segundo colocado. Empate no topo é ambiguidade, não "quase certo".
        if best_score >= _STRONG_TOKEN_MIN and best_score > runner_up_score:
            return await self._resolve(_clarification_id(best), reply)

        # §"if multiple plausible questions exist, ask which one" e
        # §"never resolve a random transaction": nada é mutado aqui.
        plausible = [c for score, c in scored if score == best_score] or [best]
        return BindingOutcome(
            status=BindingStatus.AMBIGUOUS,
            message=(
                "Não consegui identificar com segurança a qual pergunta você "
                "respondeu. Pode responder citando a mensagem da pergunta, ou "
                "me dizer qual destas é?"
            ),
            candidates=plausible,
        )

    # ---- mutação -------------------------------------------------------

    async def _resolve(self, clarification_id: str, reply: InboundReply) -> BindingOutcome:
        if not clarification_id:
            return BindingOutcome(
                status=BindingStatus.UNBOUND_QUOTE,
                message="Não localizei a pergunta correspondente a essa resposta.",
            )

        data = await self._caller.call(
            CAP_RESOLVE,
            {
                "clarificationId": clarification_id,
                "freeText": reply.text,
                "resolvedByActorId": reply.actor_id,
                "replyMessageId": reply.incoming_message_id,
            },
        )

        if data.get("alreadyResolved"):
            # Idempotência confirmada pelo servidor (corrida entre duas
            # respostas tardias): nenhuma mutação nova foi aplicada.
            return BindingOutcome(
                status=BindingStatus.ALREADY_RESOLVED,
                clarification_id=clarification_id,
                message=(
                    "Essa pergunta já tinha sido respondida antes, então não "
                    "alterei nada de novo."
                ),
                data=data,
            )

        return BindingOutcome(
            status=BindingStatus.RESOLVED,
            clarification_id=clarification_id,
            message="Anotado, obrigado. Atualizei o lançamento.",
            data=data,
        )
