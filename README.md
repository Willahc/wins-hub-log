# WiNS Hub Log

Dashboard de inteligência de frete para os corredores com maior assimetria de retorno vazio no Brasil.

**Corredores mapeados (dados CIOT ANTT):**
- SC → SP · 84,3% de retorno vazio
- SP → DF · 79,2% de retorno vazio  
- MS → PR · 77,7% de retorno vazio

---

## Deploy no Render

### 1. Criar repositório no GitHub

```bash
git init
git add .
git commit -m "feat: setup inicial wins-hub-log"
git remote add origin https://github.com/Willahc/wins-hub-log.git
git push -u origin main
```

### 2. Criar serviço no Render

1. Acesse [render.com](https://render.com) → **New** → **Blueprint**
2. Conecte o repositório `wins-hub-log`
3. O Render detecta o `render.yaml` automaticamente
4. Defina a variável de ambiente **`ADMIN_PASSWORD`** com sua senha
5. Clique em **Apply** — aguarde ~3 minutos

### 3. Acessar o dashboard

URL fornecida pelo Render após deploy. Login com a senha definida em `ADMIN_PASSWORD`.

---

## Uso local (desenvolvimento)

```bash
# Criar .env a partir do exemplo
cp .env.example .env
# Edite .env com suas configurações

# Instalar dependências
pip install -r requirements.txt

# Rodar
python app.py
# Acesse: http://localhost:5000
```

Para usar SQLite local (sem PostgreSQL), o `.env.example` já usa `sqlite:///local.db` por padrão.

---

## Fluxo de uso

1. **Importar corredor** → botão no dashboard → aguardar enriquecimento (~5 min por corredor)
2. **Filtrar** por corredor, UF, status CRM, CNAE de frete
3. **Clicar no lápis** → atualizar status + notas após cada contato
4. **Exportar CSV** → para uso offline ou compartilhar com a equipe

## Status CRM

| Status | Significado |
|---|---|
| Não contatada | Ainda não abordada |
| Tentativa | Ligação sem resposta |
| Contatada | Falou, apresentou o serviço |
| Interessada | Demonstrou interesse |
| Negociando | Em negociação ativa |
| Cliente | Contrato fechado |
| Descartada | Não tem interesse ou não é o perfil |

---

## Uso atual recomendado: VPS/local sem Render

Este projeto pode rodar localmente na VPS usando SQLite, sem dependência do Render.

### Rodar manualmente

```bash
cd /home/william/repos/wins-hub-log
source .venv/bin/activate
python app.py
```

### Rodar com Gunicorn

```bash
gunicorn app:app --bind 127.0.0.1:5055 --workers 2
```

### Serviço systemd

```bash
sudo systemctl status wins-hub-log
sudo systemctl restart wins-hub-log
journalctl -u wins-hub-log -n 80 --no-pager
```

### Banco local

Por padrão:
```env
DATABASE_URL=sqlite:///local.db
```

Não subir `.env`, `local.db`, backups ou exports para o GitHub.


## Cadência Comercial e Métricas

### Como registrar resultado de contato:
1. Abra a tela de **Matches Preditivos**.
2. Clique no ícone de lápis para abrir o offcanvas de negociação comercial.
3. No card de **Prospecção Assistida & Cadência**, preencha o formulário de log manual:
   - Selecione o destinatário (Embarcador ou Transportadora) e o canal de contato (WhatsApp, Ligação, E-mail, Outro).
   - Registre o **Resultado do Contato** comercial (ex: "Pediu cotação", "Respondeu").
   - Atribua a **Temperatura** do Lead (Quente, Morno, Frio, Fechado, Perdido) para priorização.
4. Clique em **Registrar Ação Comercial**. O status do match será atualizado e o histórico comercial ficará salvo no log permanente.

### Como definir próxima ação:
Ao registrar a ação comercial, defina também a próxima atividade:
1. Digite a descrição da atividade planejada no campo **Próxima ação** (ex: "Enviar cotação de retorno").
2. Defina a data da atividade no campo **Data próxima ação**.
3. Ao salvar, se a data de ação expirar sem a resolução da tarefa, um alerta vermelho piscante indicará **VENCIDA** na tabela de Matches.

### Onde ver follow-ups:
Acesse a tela de **Follow-ups** (ou pelo menu superior ou através do atalho em Métricas) para visualizar a agenda de tarefas comerciais estruturada por período (Vencidos, Hoje, Próximos 7 dias).

### Onde ver métricas de conversão:
Acesse a tela de **Métricas** no menu superior para acompanhar a taxa de resposta, taxa de negociação e taxa de fechamento consolidada por corredor, setor industrial do embarcador e canal de abordagem comercial.


## Segurança do banco local

O banco local SQLite (`local.db`) armazena os dados comerciais ativos (notas, CRM, histórico de prospecção, datas de follow-up). Por isso, **nunca** apague o arquivo `local.db` em produção e garanta que ele esteja listado no `.gitignore`.

### 1. Criar Backup Manual
Para gerar um backup com data e hora atual na pasta `backups/`:
```bash
python scripts/backup_db.py
```
O script mantém automaticamente apenas os últimos 20 backups para otimizar espaço em disco.

### 2. Restaurar um Backup
Para restaurar um backup anterior, execute o script passando o caminho do arquivo desejado:
```bash
python scripts/restore_db.py backups/local_YYYYMMDD_HHMMSS.db
```
*Nota: Um backup preventivo do estado atual do banco é criado de forma automática antes da restauração.*

### 3. Verificar Contagem de Registros e Tabelas
Para visualizar um relatório simples de integridade e contagem de registros principais nas tabelas:
```bash
python scripts/check_db.py
```

### 4. Aplicar Migrações de Schema de Forma Segura
Caso o código sofra atualizações que alterem a estrutura das tabelas em `models.py`, você pode rodar as migrações automáticas sem risco de perda de dados:
```bash
python scripts/migrate_sqlite.py
```
*Nota: Este script faz uma cópia preventiva de segurança do banco antes de executar os comandos `ALTER TABLE`.*


## Kanban Comercial

O **Kanban Comercial** oferece uma visualização de pipeline das negociações baseadas nos Matches Preditivos.

### Como acessar o Kanban:
- Acesse a rota `/kanban` ou clique no link **Kanban** no menu superior.

### Como mover cards:
- **Arrastar e Soltar (Drag & Drop)**: Segure o card de interesse com o mouse e mova-o para a coluna do status correspondente. O status do banco será sincronizado de forma transparente.
- **Botões Rápidos**: Caso esteja acessando de um celular ou o arrastar falhe, utilize as siglas ou ícones rápidos na base do card para trocar de status instantaneamente (ex: **V** para Validar, **A** para Abordar, **C** para Em contato, **N** para Negociando, **Check** para Fechado, etc.).

### Quais são os status:
O funil comercial é composto pelas colunas:
1. **Sugerido**: Match inicial gerado pelo algoritmo preditivo.
2. **Validar**: Qualificação inicial do lead por parte do comercial.
3. **Abordar**: Agendado para contato comercial.
4. **Em contato**: Abordagem em andamento.
5. **Negociando**: Fit comercial ativo e alinhado.
6. **Fechado**: Carga de retorno gerada com sucesso.
7. **Perdido**: Oportunidade perdida.
8. **Descartado**: Fora do perfil operacional.

### Como os status impactam as métricas:
A movimentação de um card para **Negociando** incrementa as métricas comerciais de funil. Quando movido para **Fechado**, a taxa de fechamento consolidada é atualizada no dashboard de **Métricas**. Mover para **Perdido** ou **Descartado** fecha a oportunidade com falha, refletindo de imediato nos cards estatísticos gerais.


## Auditoria do Kanban e Ações Rápidas

Para garantir a confiabilidade dos dados e agilizar o dia a dia comercial, o Kanban foi equipado com inteligência de auditoria e atalhos rápidos.

### 1. Auditoria Automática de Mudança de Status
- Toda vez que um card de Match Preditivo é movimentado de coluna no Kanban (seja via Drag & Drop ou Botões Rápidos), ou quando o status é atualizado de dentro da página de Matches via modal de CRM, o sistema cria automaticamente uma entrada de log em **`ProspeccaoLog`**.
- O log gerado registra o status anterior e o novo status (ex: `Status alterado: Sugerido → Validar`), salvando a data e a temperatura comercial do match.
- **Evita duplicação**: Caso a movimentação seja para o mesmo status atual, a gravação automática é ignorada para manter o histórico conciso.

### 2. Tratamento do Canal "Sistema" nas Estatísticas
- Logs automáticos criados pelo sistema recebem a flag `canal = 'Sistema'`.
- Visando manter a exatidão estatística de conversão, logs com canal **`Sistema`** são exibidos no histórico de auditoria do match e no histórico geral de prospecção, mas são **excluídos** do cálculo de métricas de envio e conversão. Isso impede que a taxa de resposta seja distorcida por ações administrativas automáticas.

### 3. Ações Rápidas de Contato no Card
- Cada card exibe botões rápidos de **WhatsApp (WA)** e **E-mail (Mail)** para o **Embarcador** e para a **Transportadora** (se houver dados correspondentes cadastrados).
- Ao clicar em um atalho, o navegador abrirá o WhatsApp Web com a mensagem de abordagem logística formatada (via API do WhatsApp) ou o cliente de e-mail (mailto) preenchendo assunto e corpo automaticamente.
- **Registro Silencioso**: Em segundo plano (sem travar a ação do usuário), o clique dispara uma chamada assíncrona para a rota `/kanban/match/<id>/contato-rapido` que insere o log de contato imediato (`status = 'Copiada'`) para registrar a iniciativa comercial na cadência.


## Importação segura

O WiNS Hub Log possui um pipeline de importação robusto e seguro projetado para receber cargas de dados reais sem comprometer a estabilidade do sistema ou a integridade do banco de dados.

### 1. Formatos Aceitos
O sistema aceita o upload de planilhas nos formatos:
- **CSV (.csv)**: Codificados em UTF-8 (com ou sem BOM) ou Latin-1. O delimitador de colunas é detectado automaticamente (suporta `;` ou `,`).
- **Excel (.xlsx)**: Planilhas eletrônicas nativas do Excel lidas de maneira eficiente com suporte a tipos numéricos e de data.

### 2. Campos Esperados (Cabeçalhos)
Os cabeçalhos da planilha podem ser escritos de forma normalizada ou com acentuação. O sistema reconhece sinônimos comuns. Os campos esperados são:
- `cnpj`: CNPJ da empresa (normalizado apenas para números ao salvar).
- `razao_social`: Razão social da empresa.
- `nome_fantasia`: Nome fantasia da empresa.
- `cidade`: Cidade (campo obrigatório).
- `uf`: Estado com exatamente 2 letras (ex: `SC`, `SP`).
- `cnae`: Código do CNAE principal (apenas números).
- `cnae_descricao`: Descrição da atividade do CNAE.
- `telefone`: Telefone comercial (limpo de parênteses e traços).
- `email`: E-mail de contato comercial (validado em formato válido).
- `site`: URL do site da empresa.
- `corredor_alvo`: Nome do corredor (ex: `SC→SP`, `SP→DF`). Campo obrigatório.
- `origem_provavel` / `destino_provavel`: Detalhes de tráfego regional.
- `fonte`: Nome da fonte dos dados (ex: `CargaReal`, `CSV Manual`).
- `notas`: Anotações gerais.

### 3. Tratamento de Erros e Linhas Inválidas
- **Sem interrupção total**: Uma linha mal formatada ou com dados inválidos (ex: e-mail em formato incorreto ou UF com tamanho errado) não quebra a importação inteira. 
- O validador **Pydantic** analisa cada linha individualmente. As linhas corretas são gravadas transacionalmente, enquanto as linhas ruins são salvas temporariamente em um relatório de erros detalhado exibido ao usuário após o lote.

### 4. Deduplicação Leve com RapidFuzz
- **CNPJ Duplicado**: Se for enviado um CNPJ que já existe para o **mesmo corredor alvo**, o sistema evita a duplicação física e atualiza os dados do registro existente no banco de dados.
- **Fuzzy Matching**: Usando a biblioteca **RapidFuzz**, o sistema compara as razões sociais e nomes fantasia das empresas enviadas com as já cadastradas.
  - Se houver similaridade >= 97% na mesma localidade (Cidade/UF), é considerada uma *duplicidade muito provável*.
  - Se houver similaridade >= 92%, é considerada uma *possível duplicidade*.
  - **Ação:** O sistema avisa o usuário no painel de resumo e registra as linhas suspeitas, mas **não as deleta automaticamente**, preservando os dados para triagem e tomada de decisão manual da equipe comercial.

### 5. Como Fazer Backup Preventivo
Sempre faça um backup quente antes de importar grandes lotes de dados reais:
```bash
python scripts/backup_db.py
```
O script utiliza a conexão nativa `sqlite3.Connection.backup` para realizar uma cópia consistente do banco local em disco sem interromper as operações do dashboard comercial.

---

## Importação real de embarcadores

Siga o fluxo operacional para testar e validar o sistema com dados reais de embarcadores:

1. **Acessar `/embarcadores`**: Clique no link **Embarcadores** no menu superior.
2. **Importar CSV**: Use a ferramenta de importação no final da tela para fazer upload de uma lista de embarcadores no formato esperado. (Você pode utilizar como base o arquivo de modelo fictício [`data_import/modelo_embarcadores.csv`](file:///home/william/repos/wins-hub-log/data_import/modelo_embarcadores.csv)).
3. **Acessar `/matches`**: Vá em **Matches Preditivos** e clique no botão **Gerar Matches Preditivos** para cruzar a frota de transportadoras de retorno vazio com os embarcadores recém-importados.
4. **Visualizar em `/kanban`**: Acesse a tela do **Kanban** comercial para gerenciar visualmente o funil de prospecções.
5. **Realizar Abordagem Comercial**: Utilize as ações rápidas de WhatsApp/E-mail nos cards para disparar os contatos e registrar o log comercial em tempo real.
6. **Acompanhar `/metricas` e `/followups`**: Monitore as taxas de resposta e a agenda de follow-ups agendados na cadência.

---

## Checklist Operacional de Teste

Para validar a integridade do WiNS Hub Log no ambiente de testes:

- [ ] **Transportadoras Semeadas**: Executar o script `python scripts/seed_transportadoras.py` para popular transportadoras fictícias no corredor `SC→SP` caso o banco local esteja vazio.
- [ ] **Embarcadores Importados**: Importar o arquivo `data_import/modelo_embarcadores.csv` com sucesso pela interface na tela `/embarcadores`.
- [ ] **Matches Gerados**: Clicar em **Gerar Matches Preditivos** e verificar a criação dos registros cruzados na listagem de matches.
- [ ] **Kanban Populado**: Acessar `/kanban` e certificar-se de que os cards de match estão visíveis nas respectivas colunas do pipeline.
- [ ] **Prospecção Registrada**: Clicar em um atalho de contato rápido ou preencher o formulário manual de log de contato e verificar se o indicador atualizou o card e inseriu o log no histórico.
- [ ] **Métricas Atualizadas**: Acessar `/metricas` e conferir se as estatísticas gerais do funil e as taxas de resposta/conversão comercial computaram os registros.

## Diagnóstico de importação de transportadoras

A importação de frotas ativas é realizada de forma multithread diretamente pelo dashboard através da integração de dados públicos da ANTT (RNTRC) com enriquecimento via BrasilAPI.

### Como iniciar e monitorar a importação:
1. Acesse a tela de **Transportadoras** no dashboard.
2. Clique em **Importar corredor** e selecione o trecho desejado (ex: `SC→SP`).
3. Uma barra de progresso em tempo real acompanhará as etapas e exibirá alertas imediatos caso ocorram instabilidades nas fontes externas.

### Como rodar o script de diagnóstico técnico:
Caso a importação apresente travamentos ou queiras testar as conexões e os dados da ANTT localmente, você pode rodar o utilitário de testes:
```bash
python scripts/debug_import_corredor.py
```
Esse script executará o download, o filtro do corredor e a inserção síncrona de 50 registros no banco SQLite, detalhando qualquer falha de rede ou timeout.

### Principais causas de erros na importação:
*   **Fonte ANTT Indisponível/Instável**: O portal de Dados Abertos da ANTT pode retornar timeouts. O sistema captura a falha e mostra a mensagem `"Falha ao baixar dados ANTT/RNTRC"` em vermelho na tela.
*   **Rate Limit da BrasilAPI**: A API pública de CNPJ possui limites de requisições por minuto por IP. Por isso, a importação no SQLite possui a trava de segurança `IMPORT_LIMIT = 50` em `Config` para processar em lotes seguros.
*   **Banco Bloqueado (Database Locked)**: Ocorre se múltiplas threads tentarem escrever simultaneamente no SQLite. O sistema gerencia as transações de forma controlada a cada commit de processamento para evitar conflitos de gravação.
