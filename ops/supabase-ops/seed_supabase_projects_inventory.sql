-- Seed operacional do registry supabase_projects (P0) — 35 projetos do
-- inventario (P0_INVENTARIO_SUPABASE.tsv), classificados:
--   17 ACTIVE_HEALTHY -> keepalive_enabled=true, status inicial 'unknown'
--     (o primeiro round real do scheduler atualiza para healthy/warning/failed).
--   18 INACTIVE (ja pausados) -> keepalive_enabled=false, status='paused'
--     (doc: keepalive NAO ressuscita projeto pausado — restore e acao manual
--     do titular no dashboard Supabase; ver REMAINING_GAPS do relatorio).
--
-- plan='unknown' para 34/35 — causa: o toolkit "SUPABASE" do Composio (as
-- tools usadas nesta track: GET_PROJECT/LIST_ALL_PROJECTS/
-- LIST_ALL_ORGANIZATIONS) nao expoe billing/plan (LIST_ALL_ORGANIZATIONS
-- devolve so id+name, confirmado ao vivo). Os toolkits alternativos com
-- GET_ORGANIZATION completo (supabase_mcp / supabase_read_mcp) NAO estao
-- conectados neste workspace Composio — conectar exigiria um novo fluxo de
-- OAuth, fora do escopo autonomo desta track (HUMAN_STEP).
-- 1/35 confirmado: Disparador (xkahwzwdvgmjqzykarvs) = free, via o MCP
-- oficial do Supabase (mcp__9ab86842, get_organization) que por acaso esta
-- escopado exatamente para esse projeto/org (Will Rodrigo).
--
-- keepalive_enabled=true nos 16 ACTIVE restantes com plan=unknown E UM
-- DEFAULT FAIL-SAFE deliberado: politica do operador e "nenhuma Free pode
-- hibernar" (doc §8 "Free novo descoberto -> habilita automaticamente") —
-- manter keepalive ligado num projeto que acaba sendo Paid so custa 3
-- SELECTs/dia irrelevantes; deixar desligado num projeto que e Free de
-- verdade e o exato risco que esta track existe para eliminar.
--
-- NOTA (E2E ao vivo desta track, 27/08/2026): das contas Composio ligadas
-- a familia "ProsperSend" (linhas Disparador e ProsperSend-Producao
-- abaixo), NENHUM alias testado (com/sem sufixo "- Producao"/
-- "- Homologacao", com/sem sufixo nenhum) resolveu no COMPOSIO_MULTI_EXECUTE_TOOL
-- ("No account found matching ..."). O composio_account gravado abaixo p/
-- essas 2 linhas e o valor do inventario original (nao confirmado
-- funcionalmente) — HUMAN_STEP: confirmar o nome exato da conexao Composio
-- para essa conta antes do primeiro round do scheduler incluir esses 2
-- projetos com sucesso.
--
-- HUMAN_BLOCKER: esta escrita foi bloqueada pelo classifier de auto mode
-- (mesma categoria da seed de capability_grants). Rodar manualmente contra
-- o Cognitive Homolog (ref esvjfkknrzzziafovwrv, conta Composio
-- "Supabase - Hermes") via SUPABASE_BETA_RUN_SQL_QUERY ou equivalente, com
-- read_only=false. Idempotente (ON CONFLICT DO NOTHING).

INSERT INTO supabase_projects (tenant_id, composio_account, project_ref, display_name, region, plan, plan_source, keepalive_enabled, status) VALUES
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - Patricia Candido','ulghzvebrbvlqncjjiir','NailsDesigner','sa-east-1','unknown','composio SUPABASE toolkit nao expoe plan; supabase_mcp/supabase_read_mcp (com plan) nao conectados neste workspace',true,'unknown'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - Hermes','wioorhtdwnfujkrynxij','Hermes','sa-east-1','unknown','composio SUPABASE toolkit nao expoe plan',true,'unknown'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - Hermes','esvjfkknrzzziafovwrv','Prosperfy Cognitive Homolog','sa-east-1','unknown','composio SUPABASE toolkit nao expoe plan',true,'unknown'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - Agify (Planner)','mkpjtvpstdjfmidvruor','Planner','us-east-1','unknown','composio SUPABASE toolkit nao expoe plan',true,'unknown'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - ProsperfyBusiness (PB)','hncjfxetdtcbiddegoxv','ProsperfyBusiness-Homologacao','us-east-1','unknown','projeto ja INACTIVE na descoberta - plano nao verificado',false,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - ProsperSend - Producao','heuwncftykogedukklbz','ProsperSend-Producao','us-east-2','unknown','composio SUPABASE toolkit nao expoe plan; ALIAS NAO CONFIRMADO ao vivo (ver nota acima)',true,'unknown'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - Casamento Picante','eqgmqzgstjksfbfssnmg','CasamentoPicante','sa-east-1','unknown','projeto ja INACTIVE na descoberta - plano nao verificado',false,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - Casamento Picante','hydkdvedduaxqcbtupog','CasamentoPicante-Homologacao','us-west-2','unknown','projeto ja INACTIVE na descoberta - plano nao verificado',false,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - AVS Homologacao - Veivo','rascxrzjsedqztfhcijv','AVSCareer-Homologacao','us-west-2','unknown','projeto ja INACTIVE na descoberta - plano nao verificado',false,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - TimerProsper','nqxqojzvfpaoljraehqx','TimerProsper','sa-east-1','unknown','composio SUPABASE toolkit nao expoe plan',true,'unknown'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - ProsperPay','zuhnxpkxgzwrszlaheuq','ProsperPay-Homologacao','us-west-2','unknown','composio SUPABASE toolkit nao expoe plan',true,'unknown'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - Campos Paulino Advocacia','ymmisrniczklltjejlpq','DireitoHomologacao','us-east-1','unknown','composio SUPABASE toolkit nao expoe plan',true,'unknown'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - Campos Paulino Advocacia','vxcuwfnsdqbkipmlfnxv','DireitoHomolog','sa-east-1','unknown','composio SUPABASE toolkit nao expoe plan; keepalive ao vivo desta track: timeout de conexao (544) 2x — ver REMAINING_GAPS',true,'unknown'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - ProsperAgents','vnoowkgaykhijocifyzh','ProsperAgents-Homologacao','us-west-2','unknown','projeto ja INACTIVE na descoberta - plano nao verificado',false,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - SaudeSync','phnrvvezzejhqnbratbt','SaudeSync-Homologacao','us-west-2','unknown','projeto ja INACTIVE na descoberta - plano nao verificado',false,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - SaudeSync','crjjjjfatkrhihnbefgs','Kompara-Homologacao','sa-east-1','unknown','composio SUPABASE toolkit nao expoe plan',true,'unknown'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - SaudeSync','tvjjaxsuvknvvaneusgy','SaudeSync','us-west-2','unknown','projeto ja INACTIVE na descoberta - plano nao verificado',false,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - SaudeSync','lbugvlvtvythaadupver','ProsperfyOfertas','sa-east-1','unknown','composio SUPABASE toolkit nao expoe plan',true,'unknown'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - ProsperMail','oafrffphaojjqdfmfvkp','ProsperMail-Homologacao','us-west-2','unknown','projeto ja INACTIVE na descoberta - plano nao verificado',false,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - GCM','iefqdgbuuisbegsvmegi','GCM Project','sa-east-1','unknown','composio SUPABASE toolkit nao expoe plan',true,'unknown'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - GCM','aowcvvptwxauwodfmkti','GCM-Homologacao','us-east-1','unknown','projeto ja INACTIVE na descoberta - plano nao verificado',false,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - Arenas Esportivas','mosewsitsiqpolabrwdt','ArenasEsportivas','sa-east-1','unknown','projeto ja INACTIVE na descoberta - plano nao verificado',false,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - ProsperFootball','xszptvnjgxsqnntqqisb','ProsperFootball-Prod','sa-east-1','unknown','composio SUPABASE toolkit nao expoe plan; keepalive ao vivo desta track: timeout de conexao (544) 2x — ver REMAINING_GAPS',true,'unknown'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - Chacara Facil','zxiwijqxcxshxcpstdko','ChacaraFacil','sa-east-1','unknown','projeto ja INACTIVE na descoberta - plano nao verificado',false,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - Chacara Facil','tnvihkmzzjbbmkqrzkoh','ChacaraFacil-Homologacao','sa-east-1','unknown','projeto ja INACTIVE na descoberta - plano nao verificado',false,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - Metodo Manente','ijzmqmbftmbwvdiqmhtm','LancadorPro','us-west-2','unknown','projeto ja INACTIVE na descoberta - plano nao verificado',false,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - Metodo Manente','wrlqukqeyxisdxqcklrt','MetodoManente','us-west-2','unknown','projeto ja INACTIVE na descoberta - plano nao verificado',false,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - ProsperDance','zuaecyewemirhmqudfni','ProsperDance-Homologacao','us-west-2','unknown','projeto ja INACTIVE na descoberta - plano nao verificado',false,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - ProsperSend - Homologacao','xkahwzwdvgmjqzykarvs','Disparador','us-east-2','free','supabase_mcp_direto.get_organization(org=Will Rodrigo,vxfpirmaqigcvrqhrgmi) confirmado ao vivo; ALIAS COMPOSIO NAO CONFIRMADO ao vivo (ver nota acima)',true,'unknown'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - rankanime','kwzfdbttlwsyhgrijngm','Rankanime','sa-east-1','unknown','projeto ja INACTIVE na descoberta - plano nao verificado',false,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - GuiaNotify','fxauevfteellisidtjeq','GuiaNotify','sa-east-1','unknown','composio SUPABASE toolkit nao expoe plan',true,'unknown'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - GuiaNotify','kfbfezzadqincqwvgsnz','BackSaas','sa-east-1','unknown','projeto ja INACTIVE na descoberta - plano nao verificado',false,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - william.rp2@gmail.com','caiunqdrzjlltaeaexqm','SaasCore','sa-east-1','unknown','projeto ja INACTIVE na descoberta - plano nao verificado',false,'paused'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - william.rp2@gmail.com','jpdsefyblbgjlldksjlq','AVS Career','sa-east-1','unknown','composio SUPABASE toolkit nao expoe plan',true,'unknown'),
('11a26649-91d0-4971-8d1f-2afc57f8b5ae','Supabase - william.rp2@gmail.com','ztinxsudsrtudlkbgkfu','AVS Career Prod','sa-east-1','unknown','composio SUPABASE toolkit nao expoe plan',true,'unknown')
ON CONFLICT (tenant_id, project_ref) DO NOTHING;

-- Verificacao pos-seed (deve retornar 35):
-- SELECT count(*) FROM supabase_projects WHERE tenant_id = '11a26649-91d0-4971-8d1f-2afc57f8b5ae';
-- Deve retornar 17:
-- SELECT count(*) FROM supabase_projects WHERE tenant_id = '11a26649-91d0-4971-8d1f-2afc57f8b5ae' AND keepalive_enabled = true;
