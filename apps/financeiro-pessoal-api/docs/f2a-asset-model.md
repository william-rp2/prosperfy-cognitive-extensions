# Finance V2 — F2A: modelo de ativos e UX

## Tipos canônicos

| Tipo | Semântica |
|------|-----------|
| `CHECKING_ACCOUNT` | Conta corrente — entra em saldo em contas |
| `PAYMENT_ACCOUNT` | Conta pagamento — entra em saldo em contas |
| `SAVINGS_ACCOUNT` | Poupança — entra em saldo em contas |
| `CREDIT_CARD` | Cartão — fatura/limite; **não** soma como saldo bancário |
| `INVESTMENT` | Investimento — compõe patrimônio financeiro, separado de cash |
| `RESERVE` | Reserva — só quando evidência explícita no payload Pluggy |
| `OTHER` | Fallback seguro / classificação incerta |

Normalização: `financialAssetNormalizer.ts` (determinística, sem LLM).

## Agregações

- **Saldo em contas** (`cashBalance`): apenas CHECKING / PAYMENT / SAVINGS.
- **Patrimônio financeiro** (`financialWealth`): cash + investimentos (sem limite/fatura).
- **Cartões**: fatura em aberto e limite exibidos separadamente.

## Onboarding de conexão existente

1. Owner conecta banco no MeuPluggy e copia o Item ID (UUID).
2. UI: Contas e Integrações → "Adicionar conexão existente".
3. `POST /api/finance/integrations/add-existing` valida UUID, busca Item na Pluggy, deduplica e reutiliza `PluggyItemRegistrationService.registerItem` + `syncOne(initial)`.

## Apresentação pt-BR

API mantém enums em inglês. Frontend traduz via `financePresentation.ts`.

## POC / demo

Rota `/poc/pluggy` permanece no código, mas fora do menu normal (`VITE_FINANCE_ADMIN_POC=true`).
