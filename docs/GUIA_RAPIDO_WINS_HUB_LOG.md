# Guia Rápido de Uso — WiNS Hub Log

Este guia contém as instruções resumidas de inicialização para operadores comerciais. Para o detalhamento completo, consulte o [Manual de Uso](MANUAL_USO_WINS_HUB_LOG.md).

---

## 1. Como Abrir a Ferramenta
1. Mantenha o terminal com o túnel SSH aberto.
2. Acesse no navegador: **http://127.0.0.1:5055**

---

## 2. Como Filtrar o Corredor SP->DF
1. Na tela principal, localize a barra de filtros.
2. No campo **Corredor**, selecione `SP->DF`.
3. Clique em **Filtrar** para ver apenas as oportunidades dessa rota.

---

## 3. Como Identificar um Match Excelente (A+)
Procure por cartões que contenham os seguintes badges:
* **Score Comercial:** Badge `A+` (Comercial >= 90) e `Score Match >= 90`.
* **Telefone:** Badge green `Tel. dos dois lados`.
* **WhatsApp:** Badge green `WhatsApp possível` (indica celular estruturado válido).
* **Geografia:** Proximidade preferencial de `Mesmo município` ou `Próximo` (como sinal operacional de menor custo).

---

## 4. Como Operar a Lista Piloto 100
1. Acesse o arquivo `exports/pilotos/controle_manual_piloto_100_sp_df.csv`.
2. Pegue os contatos ordenados de **1 a 20** (ordem de prioridade).
3. Faça a abordagem da **Transportadora** primeiro. Não aborde o embarcador antes!

---

## 5. Script Base de Abordagem (Copiável)

> *"Olá, tudo bem? Meu nome é [Seu Nome], da WiNS Hub Log. Estamos validando oportunidades de rotas e frete de retorno no corredor SP→DF. Vocês costumam atender esse trecho ou têm interesse em posicionar caminhões nessa rota?"*

Se a resposta for **SIM**:
> *"Legal! Vocês rodam com carga seca/paletizada e qual o tipo de carroceria (sider, baú) que operam nessa linha?"*

---

## 6. Regras de Ouro (O que NÃO Fazer)
* **NÃO** prometa cargas ou fretes fechados.
* **NÃO** faça disparos massivos ou contatos automatizados.
* **NÃO** mova os cards no Kanban sem ter entrado em contato real com a empresa.
* **NÃO** passe dados cadastrais sigilosos de uma empresa para a outra.

---

## 7. Comandos Rápidos de Emergência (VPS)
```bash
# Reiniciar o sistema (caso trave ou fique lento)
sudo systemctl restart wins-hub-log

# Consultar logs de erros
sudo journalctl -u wins-hub-log -n 50 --no-pager
```
