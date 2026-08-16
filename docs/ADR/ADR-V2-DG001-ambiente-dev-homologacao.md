# ADR-V2-DG001: Ambiente de Desenvolvimento e Homologação

**Status:** RESOLVED — 2026-08-16  
**Decisor:** William (Product Owner)

---

## Decisão

O Prosperfy Cognitive V2 utilizará um **projeto Supabase separado de homologação** na organização atual como ambiente de desenvolvimento integrado. Não há dependência de Docker Desktop ou PostgreSQL local.

### Detalhes

| Aspecto | Decisão |
|---|---|
| **Homologação** | Projeto Supabase dedicado (separado de produção) |
| **Produção** | Banco, credentials e configurações completamente separados |
| **Docker local** | Opcional — conveniência, nunca obrigatório |
| **CI** | Pode usar infraestrutura efêmera (testcontainers) quando conveniente |
| **Dependência do desenvolvedor** | Zero — sem Docker Desktop local obrigatório |

### Supabase como Postgres: impacto no mecanismo RLS

Supabase é Postgres. O mecanismo `SET LOCAL app.current_tenant_id` + `current_setting()` nas policies é **100% compatível** com Supabase.

Mapeamento de roles:
- `cognitive_admin` → conexão via **service_role key** do Supabase (BYPASSRLS implícito)
- `cognitive_app` → role criada no Postgres do Supabase com RLS enforced
- `cognitive_worker` → role criada no Postgres do Supabase com RLS enforced

### Variáveis de ambiente por ambiente

```bash
# Homologação (Supabase homolog project)
COGNITIVE_DB_URL=postgresql://cognitive_app:<password>@db.<ref>.supabase.co:5432/postgres
COGNITIVE_DB_WORKER_URL=postgresql://cognitive_worker:<password>@db.<ref>.supabase.co:5432/postgres
COGNITIVE_DB_ADMIN_URL=postgresql://postgres:<service-role>@db.<ref>.supabase.co:5432/postgres

# Produção (separado — nunca compartilhar credentials com homolog)
COGNITIVE_DB_URL=postgresql://cognitive_app:<prod-password>@db.<prod-ref>.supabase.co:5432/postgres
```

### Consequências

1. **Migrations**: runner.py conecta via `COGNITIVE_DB_ADMIN_URL` (service_role)
2. **CI**: testes DB usam testcontainers efêmeros (skip gracioso se Docker indisponível)
3. **Dev local**: in-memory (sem COGNITIVE_DB_URL) ou apontar para Supabase homolog
4. **docker-compose.dev.yml**: mantido como conveniência, jamais como caminho obrigatório

### Itens ainda abertos após esta decisão

- **DG-001-B**: timing de provisionamento do projeto Supabase homolog
- **DG-001-C**: estratégia de criação de roles no Supabase (via migration ou dashboard)

---

*Registrado por: Antigravity (AI Coding Agent) após aprovação explícita do decisor*
