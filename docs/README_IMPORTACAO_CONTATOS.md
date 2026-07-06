# Fluxo de Enriquecimento e Importação de Contatos Comerciais

Este documento orienta o processo de enriquecimento e importação de informações de contato das empresas (transportadoras e embarcadores) associadas aos matches preditivos.

---

## 1. Como Preencher a Planilha de Enriquecimento
Ao baixar um arquivo de template (como o `top_20_transportadoras_teste_importacao_TEMPLATE.csv`), você deve:
* **Preencher apenas as colunas de contato:**
  * `telefone` (número com DDD)
  * `email`
  * `site` (apenas para embarcadores)
  * `socios` (apenas para transportadoras, nomes separados por vírgula)
  * `fonte_contato` (indicar de onde veio a informação: `site oficial`, `Google`, `LinkedIn`, `manual`, `outro`)
  * `observacao_contato` (informações de apoio relevantes sobre a abordagem)
* **ATENÇÃO:** Nunca altere as colunas `id`, `cnpj` ou `tipo_empresa`, pois o script usa estes identificadores para localizar os registros corretos no banco.

---

## 2. Passo a Passo da Importação

### Passo A: Executar a Simulação (Dry-Run)
Antes de efetivar as mudanças no banco, execute o script em modo de simulação. Isto validará a estrutura do CSV, conferirá os CNPJs e IDs no banco, e estimará quantos registros seriam modificados:

```bash
python scripts/importar_contatos_csv.py --dry-run caminho_do_seu_arquivo.csv
```

### Passo B: Executar a Importação Real
Com a simulação validada (conferindo se não há erros de CNPJ/IDs não encontrados), execute a importação definitiva:

```bash
python scripts/importar_contatos_csv.py caminho_do_seu_arquivo.csv
```

> [!NOTE]
> A importação real cria automaticamente um backup quente (hot backup) do banco de dados na pasta `backups/` antes de realizar a operação. Ela atualiza **apenas** campos vazios e nunca sobrescreve contatos já existentes. Se ocorrer qualquer falha durante a execução, a transação realiza rollback automático.

### Passo C: Auditar os Resultados
Após a importação real, rode o script de auditoria para conferir a nova cobertura de contatos atualizada sobre os matches gerados:

```bash
python scripts/auditar_contatos_matches.py
```

Isto também atualizará o arquivo consolidado de fila prioritária: `exports/contatos/fila_contatos_prioritarios_matches.csv`.
