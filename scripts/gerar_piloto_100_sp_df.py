#!/usr/bin/env python3
import os
import sys
import csv
import argparse
from datetime import datetime

# Add root folder to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import Transportadora, EmbarcadorProvavel, MatchPreditivo
from scripts.gerar_fila_comercial_inteligente import calculate_commercial_score, get_class, get_badge_geografico

def get_lado_recomendado(t, e):
    t_wa = t.whatsapp_possivel if t else False
    e_wa = e.whatsapp_possivel if e else False
    
    t_tipo = t.tipo_telefone if t else "fixo"
    e_tipo = e.tipo_telefone if e else "fixo"
    
    if t_wa and e_wa:
        return "transportadora"
    if not t_wa and e_wa:
        return "embarcador"
    if t_tipo == "fixo" and e_tipo == "celular":
        return "embarcador"
    return "transportadora"

def get_aviso_geografia(prec):
    if prec == "cidade":
        return "Atenção: Distância baseada no centroide da cidade. Proximidade exata requer validação de endereço."
    elif prec == "insuficiente":
        return "Atenção: Sem dados de coordenadas válidos."
    return "Distância calculada com base em CEP/endereço."

def main():
    parser = argparse.ArgumentParser(description="Gera lista piloto de 100 matches SP->DF.")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--corredor", default="SP->DF")
    parser.add_argument("--max-por-transportadora", type=int, default=3)
    parser.add_argument("--max-por-embarcador", type=int, default=3)
    parser.add_argument("--output", default="exports/pilotos/piloto_100_sp_df.csv")
    args = parser.parse_args()
    
    print("============================================================")
    print("GERANDO LISTA PILOTO DE 100 MATCHES SP->DF")
    print("============================================================")
    
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    
    with app.app_context():
        # Obter todos os matches SP->DF
        print(f"  Carregando matches do corredor {args.corredor}...")
        matches_sp_df = MatchPreditivo.query.filter_by(corredor=args.corredor).all()
        print(f"    Total no corredor: {len(matches_sp_df):,}")
        
        candidates = []
        for m in matches_sp_df:
            t = m.transportadora
            e = m.embarcador
            
            # Filtros obrigatórios
            t_has_phone = bool((t.telefone and t.telefone.strip()) or (t.telefone_normalizado and t.telefone_normalizado.strip())) if t else False
            e_has_phone = bool((e.telefone and e.telefone.strip()) or (e.telefone_normalizado and e.telefone_normalizado.strip())) if e else False
            t_has_norm = bool(t.telefone_normalizado and t.telefone_normalizado.strip()) if t else False
            e_has_norm = bool(e.telefone_normalizado and e.telefone_normalizado.strip()) if e else False
            
            has_t_contact = bool(t and (t.telefone or t.email or t.socios))
            has_e_contact = bool(e and (e.telefone or e.email or e.site))
            
            if m.status != "Sugerido":
                continue
            if m.score_match < 90.0:
                continue
            if not (t_has_phone and e_has_phone):
                continue
            if not (t_has_norm or e_has_norm):
                continue
            if not (has_t_contact and has_e_contact):
                continue
                
            # Score comercial
            score_comercial = calculate_commercial_score(m)
            classe = get_class(score_comercial)
            
            if classe != "A+":
                continue
                
            has_wa = (t.whatsapp_possivel if t else False) or (e.whatsapp_possivel if e else False)
            t_score = t.score_completude or 0 if t else 0
            e_score = e.score_completude or 0 if e else 0
            avg_comp = (t_score + e_score) / 2.0
            
            dist = m.distancia_km
            dist_val = dist if dist is not None else 999999.0
            
            candidates.append({
                "match": m,
                "score_comercial": score_comercial,
                "score_match": m.score_match,
                "has_wa": has_wa,
                "avg_comp": avg_comp,
                "dist_val": dist_val,
                "dist": dist,
                "t_id": t.id if t else None,
                "e_id": e.id if e else None,
                "id": m.id
            })
            
        print(f"  Total de candidatos qualificados (Classe A+, score >= 90): {len(candidates):,}")
        
        # Ordenação
        candidates.sort(key=lambda x: (
            -x["score_comercial"],
            -x["score_match"],
            -1 if x["has_wa"] else 0,
            -x["avg_comp"],
            x["dist_val"],
            x["id"]
        ))
        
        # Seleção com limite de diversidade
        def select_matches(max_t, max_e):
            sel = []
            t_counts = {}
            e_counts = {}
            for c in candidates:
                t_id = c["t_id"]
                e_id = c["e_id"]
                if t_counts.get(t_id, 0) < max_t and e_counts.get(e_id, 0) < max_e:
                    t_counts[t_id] = t_counts.get(t_id, 0) + 1
                    e_counts[e_id] = e_counts.get(e_id, 0) + 1
                    sel.append(c)
                    if len(sel) >= args.limit:
                        break
            return sel, t_counts, e_counts
            
        print(f"  Aplicando limite de diversidade (max {args.max_por_transportadora} matches por empresa)...")
        selected, t_counts, e_counts = select_matches(args.max_por_transportadora, args.max_por_embarcador)
        
        relaxed_diversity = False
        if len(selected) < args.limit:
            relaxed_diversity = True
            print(f"    [Aviso] Apenas {len(selected)} matches encontrados com limite de {args.max_por_transportadora} por empresa. Relaxando para max 5...")
            selected, t_counts, e_counts = select_matches(5, 5)
            
        print(f"    Total final selecionado: {len(selected)}")
        
        # Preparar dados para escrita
        csv_fields = [
            "ordem_abordagem", "match_id", "corredor", "status", "classe_prioridade_comercial",
            "score_prioridade_comercial", "score_match", "prioridade", "temperatura", "motivo_priorizacao",
            "proxima_acao_sugerida", "lado_recomendado_primeiro", "objetivo_do_contato", "risco_observado",
            "observacao_manual",
            
            "distancia_km", "precisao_geografica_match", "badge_geografico", "aviso_geografia",
            
            "transportadora_id", "transportadora_cnpj", "transportadora_nome", "transportadora_municipio",
            "transportadora_uf", "transportadora_telefone", "transportadora_telefone_normalizado",
            "transportadora_ddd", "transportadora_tipo_telefone", "transportadora_whatsapp_possivel",
            "transportadora_email", "transportadora_socios", "transportadora_score_completude",
            "transportadora_fonte_contato",
            
            "embarcador_id", "embarcador_cnpj", "embarcador_nome", "embarcador_cidade",
            "embarcador_uf", "embarcador_telefone", "embarcador_telefone_normalizado",
            "embarcador_ddd", "embarcador_tipo_telefone", "embarcador_whatsapp_possivel",
            "embarcador_email", "embarcador_site", "embarcador_socios", "embarcador_score_completude",
            "embarcador_setor_predito", "embarcador_tipo_carga_provavel", "embarcador_carrocerias_provaveis",
            "embarcador_fonte_contato",
            
            "tipo_carga", "carroceria", "setor_predito", "tipo_carga_provavel", "carrocerias_provaveis",
            
            "tem_telefone_transportadora", "tem_telefone_embarcador", "tem_telefone_dois_lados",
            "tem_whatsapp_transportadora", "tem_whatsapp_embarcador", "tem_whatsapp_algum_lado",
            "dados_minimos_dois_lados", "contato_dos_dois_lados"
        ]
        
        rows = []
        for idx, item in enumerate(selected):
            c = item
            m = c["match"]
            t = m.transportadora
            e = m.embarcador
            
            t_wa = t.whatsapp_possivel if t else False
            e_wa = e.whatsapp_possivel if e else False
            t_has_phone = bool((t.telefone and t.telefone.strip()) or (t.telefone_normalizado and t.telefone_normalizado.strip())) if t else False
            e_has_phone = bool((e.telefone and e.telefone.strip()) or (e.telefone_normalizado and e.telefone_normalizado.strip())) if e else False
            
            lado_primeiro = get_lado_recomendado(t, e)
            
            if lado_primeiro == "transportadora":
                objetivo = "Validar interesse no corredor SP->DF e disponibilidade de carga seca"
            else:
                objetivo = "Validar demanda recorrente de fretes no corredor SP->DF e se necessitam de transportadora"
                
            aviso_geo = get_aviso_geografia(m.precisao_geografica_match)
            badge_geo = get_badge_geografico(m.distancia_km, m.precisao_geografica_match)
            
            # Motivo
            motivo = "Score alto, telefone dos dois lados"
            if t_wa or e_wa:
                motivo += " e WhatsApp possível."
            else:
                motivo += " disponível."
                
            # Riscos
            riscos = []
            if m.precisao_geografica_match == "cidade":
                riscos.append("Distância estimada por cidade")
            if not t_wa:
                riscos.append("Sem WhatsApp na transportadora")
            if not e_wa:
                riscos.append("Sem WhatsApp no embarcador")
            risco_str = ", ".join(riscos) if riscos else "Nenhum risco relevante"
            
            row = {
                "ordem_abordagem": idx + 1,
                "match_id": m.id,
                "corredor": m.corredor or "",
                "status": m.status or "",
                "classe_prioridade_comercial": "A+",
                "score_prioridade_comercial": c["score_comercial"],
                "score_match": m.score_match or 0.0,
                "prioridade": m.prioridade or "",
                "temperatura": m.temperatura or "",
                "motivo_priorizacao": motivo,
                "proxima_acao_sugerida": "Abordar piloto",
                "lado_recomendado_primeiro": lado_primeiro,
                "objetivo_do_contato": objetivo,
                "risco_observado": risco_str,
                "observacao_manual": "",
                
                "distancia_km": m.distancia_km if m.distancia_km is not None else "",
                "precisao_geografica_match": m.precisao_geografica_match or "",
                "badge_geografico": badge_geo,
                "aviso_geografia": aviso_geo,
                
                "transportadora_id": t.id if t else "",
                "transportadora_cnpj": t.cnpj if t else "",
                "transportadora_nome": t.razao_social or t.nome_rntrc or "" if t else "",
                "transportadora_municipio": t.municipio if t else "",
                "transportadora_uf": t.uf if t else "",
                "transportadora_telefone": t.telefone or "" if t else "",
                "transportadora_telefone_normalizado": t.telefone_normalizado or "" if t else "",
                "transportadora_ddd": t.ddd or "" if t else "",
                "transportadora_tipo_telefone": t.tipo_telefone or "" if t else "",
                "transportadora_whatsapp_possivel": "Sim" if t_wa else "Não",
                "transportadora_email": t.email or "" if t else "",
                "transportadora_socios": t.socios or "" if t else "",
                "transportadora_score_completude": t.score_completude or 0 if t else 0,
                "transportadora_fonte_contato": t.fonte_contato or "" if t else "",
                
                "embarcador_id": e.id if e else "",
                "embarcador_cnpj": e.cnpj if e else "",
                "embarcador_nome": e.razao_social or e.nome_fantasia or "" if e else "",
                "embarcador_cidade": e.cidade if e else "",
                "embarcador_uf": e.uf if e else "",
                "embarcador_telefone": e.telefone or "" if e else "",
                "embarcador_telefone_normalizado": e.telefone_normalizado or "" if e else "",
                "embarcador_ddd": e.ddd or "" if e else "",
                "embarcador_tipo_telefone": e.tipo_telefone or "" if e else "",
                "embarcador_whatsapp_possivel": "Sim" if e_wa else "Não",
                "embarcador_email": e.email or "" if e else "",
                "embarcador_site": e.site or "" if e else "",
                "embarcador_socios": e.socios or "" if e else "",
                "embarcador_score_completude": e.score_completude or 0 if e else 0,
                "embarcador_setor_predito": e.setor_predito or "" if e else "",
                "embarcador_tipo_carga_provavel": e.tipo_carga_provavel or "" if e else "",
                "embarcador_carrocerias_provaveis": e.carrocerias_provaveis or "" if e else "",
                "embarcador_fonte_contato": e.fonte_contato or "" if e else "",
                
                "tipo_carga": e.tipo_carga_provavel if e else "",
                "carroceria": e.carrocerias_provaveis if e else "",
                "setor_predito": e.setor_predito if e else "",
                "tipo_carga_provavel": e.tipo_carga_provavel if e else "",
                "carrocerias_provaveis": e.carrocerias_provaveis if e else "",
                
                "tem_telefone_transportadora": "Sim" if t_has_phone else "Não",
                "tem_telefone_embarcador": "Sim" if e_has_phone else "Não",
                "tem_telefone_dois_lados": "Sim",
                "tem_whatsapp_transportadora": "Sim" if t_wa else "Não",
                "tem_whatsapp_embarcador": "Sim" if e_wa else "Não",
                "tem_whatsapp_algum_lado": "Sim" if t_wa or e_wa else "Não",
                "dados_minimos_dois_lados": "Sim",
                "contato_dos_dois_lados": "Sim"
            }
            rows.append(row)
            
        # Gravar piloto_100_sp_df.csv
        with open(args.output, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=csv_fields, delimiter=";")
            w.writeheader()
            w.writerows(rows)
        print(f"  Salvo: {args.output}")
        
        # Gravar controle_manual_piloto_100_sp_df.csv
        ctrl_fields = [
            "ordem_abordagem", "data_abordagem", "responsavel", "canal_usado", "lado_abordado",
            "telefone_usado", "empresa_abordada", "respondeu", "status_validacao", "interesse_no_corredor",
            "tipo_carga_confirmado", "whatsapp_confirmado", "observacao_contato", "proxima_acao", "atualizar_kanban_depois"
        ]
        ctrl_rows = []
        for r in rows:
            ctrl_rows.append({
                "ordem_abordagem": r["ordem_abordagem"],
                "data_abordagem": "",
                "responsavel": "",
                "canal_usado": "",
                "lado_abordado": r["lado_recomendado_primeiro"],
                "telefone_usado": r["transportadora_telefone_normalizado"] if r["lado_recomendado_primeiro"] == "transportadora" else r["embarcador_telefone_normalizado"],
                "empresa_abordada": r["transportadora_nome"] if r["lado_recomendado_primeiro"] == "transportadora" else r["embarcador_nome"],
                "respondeu": "",
                "status_validacao": "Pendente",
                "interesse_no_corredor": "",
                "tipo_carga_confirmado": "",
                "whatsapp_confirmado": "",
                "observacao_contato": "",
                "proxima_acao": "",
                "atualizar_kanban_depois": ""
            })
            
        ctrl_output = "exports/pilotos/controle_manual_piloto_100_sp_df.csv"
        with open(ctrl_output, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=ctrl_fields, delimiter=";")
            w.writeheader()
            w.writerows(ctrl_rows)
        print(f"  Salvo: {ctrl_output}")
        
        # Gerar RELATORIO_PILOTO_100_SP_DF.md
        t_unicas = len(set(r["transportadora_id"] for r in rows))
        e_unicas = len(set(r["embarcador_id"] for r in rows))
        
        scores_com = [r["score_prioridade_comercial"] for r in rows]
        scores_match = [r["score_match"] for r in rows]
        
        wa_possivel = sum(1 for r in rows if r["tem_whatsapp_algum_lado"] == "Sim")
        wa_t = sum(1 for r in rows if r["tem_whatsapp_transportadora"] == "Sim")
        wa_e = sum(1 for r in rows if r["tem_whatsapp_embarcador"] == "Sim")
        
        t_tel_norm_both = sum(1 for r in rows if r["transportadora_telefone_normalizado"] and r["embarcador_telefone_normalizado"])
        
        # Top 20 table
        top_20_table = []
        for i, r in enumerate(rows[:20]):
            top_20_table.append(
                f"| {i+1} | {r['match_id']} | {r['score_match']} | {r['score_prioridade_comercial']} | {r['transportadora_nome'][:25]}... | {r['embarcador_nome'][:25]}... | {r['lado_recomendado_primeiro']} | {r['badge_geografico']} |"
            )
            
        # Setores e cargas
        setores = {}
        cargas = {}
        cidades_origem = {}
        for r in rows:
            setores[r["setor_predito"]] = setores.get(r["setor_predito"], 0) + 1
            cargas[r["tipo_carga"]] = cargas.get(r["tipo_carga"], 0) + 1
            cidades_origem[r["transportadora_municipio"]] = cidades_origem.get(r["transportadora_municipio"], 0) + 1
            
        setores_sorted = sorted(setores.items(), key=lambda x: -x[1])[:5]
        cargas_sorted = sorted(cargas.items(), key=lambda x: -x[1])[:5]
        cidades_sorted = sorted(cidades_origem.items(), key=lambda x: -x[1])[:5]
        
        relatorio_path = "exports/pilotos/RELATORIO_PILOTO_100_SP_DF.md"
        with open(relatorio_path, "w", encoding="utf-8") as f:
            f.write(f"""# Relatório Executivo do Piloto Manual 100 SP->DF

Este relatório apresenta o detalhamento estatístico e de qualidade dos 100 matches selecionados para o piloto operacional manual no corredor SP->DF.

---

## 📊 1. Volumetria Geral

* **Total de Matches Avaliados no Corredor:** {len(matches_sp_df):,}
* **Total Selecionado para Piloto:** {len(rows)}
* **Transportadoras Únicas:** {t_unicas}
* **Embarcadores Únicos:** {e_unicas}
* **Limite de Diversidade Aplicado (max 3/empresa):** {"Sim" if not relaxed_diversity else "Não (relaxado para max 5)"}

---

## 📈 2. Estatísticas de Scores

* **Score Comercial:** Médio: {sum(scores_com)/len(scores_com):.2f} | Mín: {min(scores_com)} | Máx: {max(scores_com)}
* **Score Match:** Médio: {sum(scores_match)/len(scores_match):.2f} | Mín: {min(scores_match)} | Máx: {max(scores_match)}

---

## 📞 3. Qualidade de Contatos e WhatsApp

* **Matches com WhatsApp possível (algum lado):** {wa_possivel} ({wa_possivel}%)
* **WhatsApp na Transportadora:** {wa_t} ({wa_t}%)
* **WhatsApp no Embarcador:** {wa_e} ({wa_e}%)
* **Telefone Normalizado nos Dois Lados:** {t_tel_norm_both} ({t_tel_norm_both}%)

---

## 🏆 4. Top 20 Matches do Piloto

| Ordem | Match ID | Score Match | Score Comercial | Transportadora | Embarcador | Primeiro Contato | Geografia |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
""" + "\n".join(top_20_table) + f"""

---

## 🏢 5. Perfil Logístico e Operacional

### Setores de Atuação (Top 5):
""" + "\n".join([f"* **{setor}:** {v} matches" for setor, v in setores_sorted]) + """

### Tipos de Carga (Top 5):
""" + "\n".join([f"* **{carga}:** {v} matches" for carga, v in cargas_sorted]) + """

### Cidades de Origem mais frequentes (Top 5):
""" + "\n".join([f"* **{cidade}:** {v} matches" for cidade, v in cidades_sorted]) + """

---

## ⚠️ 6. Observações de Risco

1. **Geocodificação Auxiliar:** 100% dos matches utilizam coordenadas baseadas em centroides municipais. A distância em km é estimada a nível de prefeitura-prefeitura, necessitando de confirmação de endereço físico.
2. **WhatsApp Estimado:** A flag indica formato celular compatível, mas não valida se o número possui conta ativa.
3. **Validação Manual:** O processo de contato deve ser 100% manual e consultivo, sem envios automatizados ou promessas contratuais.

---

## 💡 7. Recomendações de Execução

1. **Abordagem Inicial (Foco 20 primeiros):** Iniciar as ligações/contatos pelos primeiros 20 matches da lista de ordem.
2. **Seguir o Roteiro:** Utilizar estritamente o roteiro de abordagem manual.
3. **Registrar na Planilha:** Preencher cada campo no arquivo `controle_manual_piloto_100_sp_df.csv` após o contato.
""")
        print(f"  Salvo: {relatorio_path}")
        
        # Gerar ROTEIRO_ABORDAGEM_PILOTO_100_SP_DF.md
        roteiro_path = "exports/pilotos/ROTEIRO_ABORDAGEM_PILOTO_100_SP_DF.md"
        with open(roteiro_path, "w", encoding="utf-8") as f:
            f.write("""# Roteiro de Abordagem Manual - Piloto 100 SP->DF

Este documento fornece as diretrizes, scripts de abordagem e regras para contato no primeiro piloto operacional de validação comercial.

---

## 🎯 1. Objetivo do Piloto

Validar a acionabilidade comercial dos matches preditivos no corredor **SP->DF**, confirmando o interesse da transportadora e a demanda do embarcador sem criar expectativas comerciais falsas ou prometer negócios fechados.

---

## 🚨 2. Regras de Segurança e Boas Práticas

> [!IMPORTANT]
> **O que NÃO fazer:**
> 1. **Não prometer carga:** Nunca diga à transportadora que já existe uma carga garantida ou separada para ela.
> 2. **Não prometer frete fechado:** Não apresente valores de tarifas ou frete como oficiais ou fechados.
> 3. **Não alegar contrato existente:** Não sugira que o WiNS Hub Log já possui um contrato ativo com o embarcador para essa carga específica.
> 4. **Não compartilhar dados confidenciais:** Não envie dados de CNPJ, contatos ou informações de faturamento de uma ponta para a outra sem consentimento prévio.
> 5. **Não disparar em massa:** Todos os contatos devem ser feitos manualmente e de forma personalizada.

---

## 📞 3. Script de Abordagem para Transportadora

### Contato Inicial (Preferencialmente WhatsApp ou Ligação):
> "Olá, tudo bem? Meu nome é [Nome], falo em nome da equipe WiNS Hub Log. Estamos realizando uma validação logística de rotas e oportunidades comerciais no corredor SP→DF. Vocês costumam atender este trecho ou têm interesse em cargas eventuais/recorrentes nesta rota?"

### Se responder SIM:
> "Perfeito! A ideia é entender se vocês operam com carga seca e paletizada nesse sentido e qual a disponibilidade de frota na região de origem. Qual tipo de carroceria vocês costumam rodar mais para o Distrito Federal?"

### Se responder NÃO:
> "Sem problemas, agradeço a atenção. Posso deixar registrado em nosso sistema que essa rota não é prioritária para vocês no momento para não incomodarmos no futuro?"

---

## 🏢 4. Perguntas de Validação (Lista de Checagem)

Durante o contato com a transportadora, tente obter as seguintes confirmações de forma amigável:
* Atende SP→DF?
* Trabalha com carga seca/paletizada?
* Qual tipo de veículo/carroceria utiliza nesse trecho?
* Prefere alguma cidade específica de origem em São Paulo?
* O número de contato atual é WhatsApp comercial direto do setor de expedição?

---

## 🏷️ 5. Status da Validação Manual

Após o contato, registre o resultado no arquivo de controle utilizando um dos seguintes status:
* **Interessado:** Respondeu positivamente e confirmou interesse na rota.
* **Sem interesse:** Respondeu que não opera no corredor ou não tem frota.
* **Telefone inválido:** O número de telefone não completa chamada ou não existe.
* **Não respondeu:** Tentativas realizadas sem retorno da empresa.
* **Validar depois:** Solicitou retorno em outro horário/data.
* **Dados incorretos:** O telefone pertence a outra empresa ou pessoa física.

---

## 🔄 6. Próximo Passo

A abordagem do **embarcador** só deve ocorrer após termos uma transportadora validada e com interesse firme no corredor!
""")
        print(f"  Salvo: {roteiro_path}")
        print("=========================================")

if __name__ == "__main__":
    main()
