# Migrações de Banco de Dados — WiNS Hub Log

Este diretório contém a documentação e histórico de modificações estruturais (schema) do banco de dados local do sistema.

> [!IMPORTANT]
> **NUNCA** apague o arquivo `local.db` em ambiente de produção. Ele contém o histórico de notas, prospecções comerciais, follow-ups e CRM das transportadoras e embarcadores.

---

## Fluxo Seguro de Alteração de Schema

Sempre siga este passo a passo ao alterar a estrutura das tabelas (ex: adicionar novos campos em `models.py`):

### 1. Criar um Backup de Segurança
Antes de qualquer alteração no código ou banco, execute o script de backup automático:
```bash
python scripts/backup_db.py
```
O arquivo de backup será salvo na pasta `backups/` com a data e hora atual.

### 2. Alterar o arquivo `models.py`
Faça as modificações necessárias na classe correspondente do SQLAlchemy.

### 3. Executar o script de Migração Automática
O script `scripts/migrate_sqlite.py` verifica as colunas existentes nas tabelas e as adiciona caso estejam ausentes no banco atual, preservando todos os dados:
```bash
python scripts/migrate_sqlite.py
```

### 4. Executar ALTER TABLE Manual (Se necessário)
Caso necessite aplicar uma alteração manual via terminal SQLite, acesse o banco local:
```bash
sqlite3 local.db
```
E execute os comandos SQL correspondentes, por exemplo:
```sql
ALTER TABLE matches_preditivos ADD COLUMN temperatura VARCHAR(20) DEFAULT 'Frio';
```

### 5. Validar a Estrutura
Verifique a contagem de registros e tabelas ativas usando o utilitário de checagem:
```bash
python scripts/check_db.py
```
