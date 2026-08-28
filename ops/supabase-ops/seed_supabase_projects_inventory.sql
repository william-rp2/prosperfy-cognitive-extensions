-- Seed operacional do registry supabase_projects (P0) — 35 projetos.
--
-- CRITÉRIO DEFINITIVO (confirmado pelo owner em 28/08/2026):
--   TODOS os projetos Supabase são FREE. Não se gasta chamada tentando
--   descobrir plano. plan='free' para os 35, e keepalive_enabled=true para
--   TODOS — inclusive os pausados, que voltam a ser protegidos assim que o
--   owner reativá-los manualmente. Plano deixa de ser critério de proteção.
--
-- STATUS VERIFICADO AO VIVO (não presumido), 28/08/2026:
--   healthy = 15 · SELECT 1 executado com sucesso via Compose MCP agora.
--   failed  =  2 · API do Supabase reporta ACTIVE_HEALTHY, mas o banco
--                  recusa conexão (status 544, connection timeout) em 3
--                  tentativas. Control plane saudável != banco alcançável.
--   paused  = 18 · status INACTIVE confirmado projeto a projeto.
--
-- CORREÇÃO IMPORTANTE: os nomes em composio_account agora carregam os
-- ACENTOS EXATOS da conexão Composio ("Produção", "Homologação", "Chácara
-- Fácil", "Método Manente"). A versão anterior usava nomes normalizados sem
-- acento, herdados do TSV de inventário — o Composio exige match exato e
-- devolvia "No account found matching ...". Essa era a causa real das 2
-- falhas de alias da família ProsperSend, agora resolvidas e comprovadas.
--
-- EXCLUSAO DE PRODUCTION: wioorhtdwnfujkrynxij (projeto "Hermes") e
-- Production/legado e foi declarado PROIBIDO pelo owner em 28/08/2026.
-- Fica registrado no inventario apenas como metadata, com
-- keepalive_enabled=false — o scheduler nunca o alcanca. Se ele for Free e
-- ficar inativo, pode hibernar; essa e uma decisao consciente do owner.
--
-- Idempotente. Requer permissão de escrita SQL no Homolog
-- (ref esvjfkknrzzziafovwrv, conta Composio "Supabase - Hermes").

INSERT INTO supabase_projects
  (tenant_id, composio_account, project_ref, display_name, region, plan, plan_source, keepalive_enabled, status)
VALUES
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - Patricia Candido','ulghzvebrbvlqncjjiir','NailsDesigner','sa-east-1','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'healthy'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - Hermes','wioorhtdwnfujkrynxij','Hermes','sa-east-1','free','PRODUCTION/LEGADO — proibido pelo owner em 28/08/2026',false,'unknown'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - Hermes','esvjfkknrzzziafovwrv','Prosperfy Cognitive Homolog','sa-east-1','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'healthy'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - Agify (Planner)','mkpjtvpstdjfmidvruor','Planner','us-east-1','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'healthy'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - ProsperSend - Produção','heuwncftykogedukklbz','ProsperSend-Producao','us-east-2','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'healthy'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - TimerProsper','nqxqojzvfpaoljraehqx','TimerProsper','sa-east-1','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'healthy'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - ProsperPay','zuhnxpkxgzwrszlaheuq','ProsperPay-Homologacao','us-west-2','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'healthy'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - Campos Paulino Advocacia','ymmisrniczklltjejlpq','DireitoHomologacao','us-east-1','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'healthy'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - SaudeSync','crjjjjfatkrhihnbefgs','Kompara-Homologacao','sa-east-1','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'healthy'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - SaudeSync','lbugvlvtvythaadupver','ProsperfyOfertas','sa-east-1','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'healthy'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - GCM','iefqdgbuuisbegsvmegi','GCM Project','sa-east-1','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'healthy'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - ProsperSend - Homologação','xkahwzwdvgmjqzykarvs','Disparador','us-east-2','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'healthy'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - GuiaNotify','fxauevfteellisidtjeq','GuiaNotify','sa-east-1','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'healthy'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - william.rp2@gmail.com','jpdsefyblbgjlldksjlq','AVS Career','sa-east-1','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'healthy'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - william.rp2@gmail.com','ztinxsudsrtudlkbgkfu','AVS Career Prod','sa-east-1','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'healthy'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - Campos Paulino Advocacia','vxcuwfnsdqbkipmlfnxv','DireitoHomolog','sa-east-1','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'failed'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - ProsperFootball','xszptvnjgxsqnntqqisb','ProsperFootball-Prod','sa-east-1','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'failed'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - ProsperfyBusiness (PB)','hncjfxetdtcbiddegoxv','ProsperfyBusiness-Homologacao','us-east-1','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - Casamento Picante','eqgmqzgstjksfbfssnmg','CasamentoPicante','sa-east-1','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - Casamento Picante','hydkdvedduaxqcbtupog','CasamentoPicante-Homologacao','us-west-2','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - AVS Homologação - Veivo','rascxrzjsedqztfhcijv','AVSCareer-Homologacao','us-west-2','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - ProsperAgents','vnoowkgaykhijocifyzh','ProsperAgents-Homologacao','us-west-2','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - SaudeSync','phnrvvezzejhqnbratbt','SaudeSync-Homologacao','us-west-2','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - SaudeSync','tvjjaxsuvknvvaneusgy','SaudeSync','us-west-2','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - ProsperMail','oafrffphaojjqdfmfvkp','ProsperMail-Homologacao','us-west-2','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - GCM','aowcvvptwxauwodfmkti','GCM-Homologacao','us-east-1','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - Arenas Esportivas','mosewsitsiqpolabrwdt','ArenasEsportivas','sa-east-1','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - Chácara Fácil','zxiwijqxcxshxcpstdko','ChacaraFacil','sa-east-1','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - Chácara Fácil','tnvihkmzzjbbmkqrzkoh','ChacaraFacil-Homologacao','sa-east-1','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - Método Manente','ijzmqmbftmbwvdiqmhtm','LancadorPro','us-west-2','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - Método Manente','wrlqukqeyxisdxqcklrt','MetodoManente','us-west-2','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - ProsperDance','zuaecyewemirhmqudfni','ProsperDance-Homologacao','us-west-2','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - rankanime','kwzfdbttlwsyhgrijngm','Rankanime','sa-east-1','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - GuiaNotify','kfbfezzadqincqwvgsnz','BackSaas','sa-east-1','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - william.rp2@gmail.com','caiunqdrzjlltaeaexqm','SaasCore','sa-east-1','free','owner confirmou em 28/08/2026: todos os projetos sao Free',true,'paused')
ON CONFLICT DO NOTHING;
