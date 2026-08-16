# Permissions and Profiles

## Conceitos

-   Tenant: boundary organizacional.
-   Actor: quem/que está agindo.
-   Profile: conjunto de comportamento e grants.
-   Capability Grant: permissão para capability/scope.
-   Resource Grant: acesso a resource lógico.
-   Data Scope: acesso a domínio/dados.

## Perfis iniciais

### owner

Acesso amplo ao próprio tenant, sujeito a CONFIRM/DENY.

### finance-owner

Finance read/write autorizado; sem infra destrutiva.

### spouse-finance

Finance/budgets definidos; sem áreas privadas não autorizadas.

### operator

Projects/tasks/customer operations.

### customer-agent

Somente cliente/projeto/conversa e capabilities explícitas.

### infra-read

Read-only infra.

### worker

Somente capabilities necessárias ao job.

## Regras

-   deny by default;
-   grants por tenant;
-   profile não substitui policy;
-   capability + resource + data scope precisam ser compatíveis;
-   service identity não herda owner;
-   impersonation somente se explicitamente projetada/auditada.

## Finance

Criar scopes próprios, por exemplo: - finance.summary.read -
finance.transactions.read - finance.transactions.write -
finance.budgets.read - finance.admin

## Gate

Testes por matriz actor × capability × resource × tenant.
