"""Contract tests — capability_router (Sprint 0.7.8). Deterministic pre-LLM routing."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from capability_intelligence.capability_router import (
    resolve_specialist_route,
    route_toolsets,
)


def check(msg, expected):
    got = resolve_specialist_route(msg)
    status = "PASS" if got == expected else "FAIL"
    print(f"{status} | {msg[:55]!r} -> {got} (expected {expected})")
    return got == expected


cases = [
    # NORMAL
    ("Oi", "NORMAL"),
    ("Explique o que é memória RAM.", "NORMAL"),
    ("Como funciona busca semântica?", "NORMAL"),
    ("Obrigado", "NORMAL"),
    ("Ok", "NORMAL"),
    # CRON (scheduling temporal claro)
    ("Me lembre amanhã às 9h de enviar o relatório.", "CRON"),
    ("Daqui a 30 minutos me lembre de ligar.", "CRON"),
    ("Me lembre em 5 minutos de testar o Cron do Hermes.", "CRON"),
    ("/cron listar", "CRON"),
    # SESSION_SEARCH (recall)
    ("Me lembre o que decidimos sobre o Hermes.", "SESSION_SEARCH"),
    ("O que conversamos ontem sobre o Cognitive?", "SESSION_SEARCH"),
    ("Na outra sessão falamos sobre Browser Harness. O que decidimos?", "SESSION_SEARCH"),
    ("Qual foi a conclusão da nossa conversa sobre X?", "SESSION_SEARCH"),
    # MEMORY
    ("Lembre que meu código de teste é ABC123.", "MEMORY"),
    ("O que você lembra sobre meu código de teste?", "MEMORY"),
    ("Memorize que o projeto usa o Hermes clean.", "MEMORY"),
    ("Guarde esta informação para depois: o deploy é às 10h.", "MEMORY"),
    # SKILLS
    ("Quais skills você possui?", "SKILLS"),
    ("Mostre a skill X.", "SKILLS"),
    ("Crie uma skill para o procedimento X.", "SKILLS"),
    ("Existe uma skill para Y?", "SKILLS"),
    # Collision: recall "me lembre" sem scheduling -> NÃO é cron
    ("Me lembre o que conversamos ontem.", "SESSION_SEARCH"),
    # INFRA_READ (Phase 1A)
    ("Como estão meus servidores?", "INFRA_READ"),
    ("Como está o Prosperfy?", "INFRA_READ"),
    ("Quais containers estão rodando no Prosperfy?", "INFRA_READ"),
    ("Quais portas estão abertas no Black?", "INFRA_READ"),
    ("Tem algum container parado no Manager1?", "INFRA_READ"),
    ("O que está acontecendo com o Hostinger One?", "INFRA_READ"),
    ("Quantos containers existem no Black?", "INFRA_READ"),
    # INFRA_READ negativos (conceitual → NORMAL)
    ("O que significa servidor web?", "NORMAL"),
    ("Qual a diferença entre Docker e VM?", "NORMAL"),
    ("Explique como funciona um servidor.", "NORMAL"),
    ("Como funciona busca semântica?", "NORMAL"),
]

fails = 0
for msg, exp in cases:
    if not check(msg, exp):
        fails += 1

# toolset maps
assert route_toolsets("NORMAL") == [], route_toolsets("NORMAL")
assert route_toolsets("CRON") == ["cronjob"]
assert route_toolsets("SESSION_SEARCH") == ["session_search"]
assert route_toolsets("MEMORY") == ["memory"]
assert route_toolsets("SKILLS") == ["skills"]

print(f"TOTAL={len(cases)} FAILS={fails}")
print("ROUTE_TOOLSETS_OK")
print("CONTRACT=" + ("PASS" if fails == 0 else "FAIL"))