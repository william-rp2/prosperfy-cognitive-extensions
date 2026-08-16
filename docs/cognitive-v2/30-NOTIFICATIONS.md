# Notifications

## Objetivo

Padronizar notificações geradas por workflows/incidentes sem acoplar
domínio ao canal.

## Modelo

-   notification_intents
-   notification_deliveries
-   notification_preferences
-   notification_templates

## Canais

-   WhatsApp
-   e-mail
-   in-app
-   outros adapters futuros

## Fluxo

``` text
Domain event
 -> NotificationIntent
 -> preferences/policy
 -> channel adapter
 -> delivery result
```

## Regras

-   domínio não chama WhatsApp/email diretamente;
-   dedup;
-   quiet hours quando configurado;
-   prioridade;
-   retries;
-   delivery status;
-   tenant template;
-   informação sensível respeita ACL/canal;
-   reutilizar ProsperfySkill/MCP quando disponível.

## Gate

-   intent;
-   routing;
-   delivery;
-   retry;
-   dedup;
-   preference;
-   audit.
