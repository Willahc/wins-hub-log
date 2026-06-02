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
