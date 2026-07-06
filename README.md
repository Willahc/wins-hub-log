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
4. **Exportar CSV** → para uso offline ou compartilhar com Mari

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





