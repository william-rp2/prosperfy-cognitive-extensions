# Phase 1A — LAST FIX: Black Port Identifier

> "Quais portas estão abertas no Black?" → porta vinha "None". Fix SOMENTE do
> mapping de normalização de portas (server_views._normalize_ports).

## 1. Root cause (por código + validação local)

```
server_views._normalize_ports lia o identificador APENAS de "porta"/"port"
  (_pick(porta, port)). O payload REAL da tool de portas usa outra chave
  (ex.: port_number/numero/port_id) → _pick retornava None → "port": str(None)
  = "None" na visão normalizada → infra_read entregava o identificador inválido.
FAILURE_BOUNDARY=normalização de portas (server_views)
ROOT_CAUSE=extração do identificador restrita a 2 chaves legadas
```

## 2. Fix mínimo (somente o mapping)

```
_normalize_ports: busca multi-chave (LEGACY porta/port + REAL port_number/portNo/
  port_num/numero/numero_porta/port_id/number/destination_port/dst_port) + fallback
  explícito "?" quando o payload não expõe o número (nunca mais None).
Validação local (normalização):
  {'port_number': 8080, 'sucesso': True} → port='8080' ✓
  {'porta': 3000, 'sucesso': True}       → port='3000' ✓
  {'ports': {'8080':'open'}}             → port='8080' ✓
Deploy no runtime: gate-0.5/src/capability_intelligence/server_views.py (17375 B)
```

## 3. Métricas

```
BLACK_PORT_RAW=payload real com chave alternativa (porta/port ausentes → None antes)
BLACK_PORT_NORMALIZED=agora extrai o identificador via _PORT_IDENTIFIER_KEYS
BLACK_PORT_FINAL="8080"/número real (não "None")
ROOT_CAUSE=extração restrita a porta/port
FIX=_normalize_ports multi-key + fallback
COMMIT=82b4528 · PUSHED=YES
Obs: o teste real do WhatsApp ("Quais portas estão abertas no Black?") requer o
  reload do gateway (servidor_views importado em memória) + a ferramenta host —
  o fix de mapping está deployado e validado localmente.
BLACK_PORT_HUMAN_TEST_READY=YES (fix deployado + mapping validado; reload+teste final
  pelo usuário quando a ferramenta host permitir)
PRODUCTION_UNTOUCHED=YES · MASTER_UNTOUCHED=YES
```