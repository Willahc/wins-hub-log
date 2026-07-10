-- Migration 006: Adicionar colunas de snapshot e auditoria ao prospeccao_logs
-- Criado em: 2026-07-10
-- Idempotente: usa IF NOT EXISTS / coluna por coluna
-- Reversivel: migrate_down no final deste arquivo

BEGIN TRANSACTION;

-- Colunas de snapshot dos scores no momento do registro
ALTER TABLE prospeccao_logs ADD COLUMN score_oportunidade_no_momento REAL;
ALTER TABLE prospeccao_logs ADD COLUMN score_logistico_origem_momento REAL;
ALTER TABLE prospeccao_logs ADD COLUMN score_logistico_destino_momento REAL;
ALTER TABLE prospeccao_logs ADD COLUMN score_retorno_no_momento REAL;
ALTER TABLE prospeccao_logs ADD COLUMN confianca_no_momento REAL;
ALTER TABLE prospeccao_logs ADD COLUMN classificacao_oportunidade_no_momento VARCHAR(30);

-- Colunas de status anterior/novo para auditoria
ALTER TABLE prospeccao_logs ADD COLUMN status_anterior VARCHAR(20);
ALTER TABLE prospeccao_logs ADD COLUMN status_novo VARCHAR(20);

-- Origem da interface (web, api, sistema)
ALTER TABLE prospeccao_logs ADD COLUMN origem_interface VARCHAR(50) DEFAULT 'web';

-- Indices para consulta de historico por match
CREATE INDEX IF NOT EXISTS idx_prospeccao_logs_match_resultado ON prospeccao_logs(match_id, resultado);
CREATE INDEX IF NOT EXISTS idx_prospeccao_logs_match_canal ON prospeccao_logs(match_id, canal);
CREATE INDEX IF NOT EXISTS idx_prospeccao_logs_match_data ON prospeccao_logs(match_id, created_at);

COMMIT;

-- =========================================================================
-- Rollback (migrate_down)
-- =========================================================================
-- BEGIN TRANSACTION;
-- DROP INDEX IF EXISTS idx_prospeccao_logs_match_data;
-- DROP INDEX IF EXISTS idx_prospeccao_logs_match_canal;
-- DROP INDEX IF EXISTS idx_prospeccao_logs_match_resultado;
-- ALTER TABLE prospeccao_logs DROP COLUMN origem_interface;
-- ALTER TABLE prospeccao_logs DROP COLUMN status_novo;
-- ALTER TABLE prospeccao_logs DROP COLUMN status_anterior;
-- ALTER TABLE prospeccao_logs DROP COLUMN classificacao_oportunidade_no_momento;
-- ALTER TABLE prospeccao_logs DROP COLUMN confianca_no_momento;
-- ALTER TABLE prospeccao_logs DROP COLUMN score_retorno_no_momento;
-- ALTER TABLE prospeccao_logs DROP COLUMN score_logistico_destino_momento;
-- ALTER TABLE prospeccao_logs DROP COLUMN score_logistico_origem_momento;
-- ALTER TABLE prospeccao_logs DROP COLUMN score_oportunidade_no_momento;
-- COMMIT;
