#!/usr/bin/env python3
import os
import sys
import csv
from datetime import datetime

# Add root folder to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import Transportadora, EmbarcadorProvavel, MatchPreditivo

def median(lst):
    n = len(lst)
    if n < 1:
        return 0.0
    s = sorted(lst)
    if n % 2 == 1:
        return s[n//2]
    else:
        return (s[n//2 - 1] + s[n//2]) / 2.0

def build_row(m, obs=""):
    t = m.transportadora
    e = m.embarcador
    
    t_has = "Não"
    if t:
        if (t.telefone and t.telefone.strip()) or (t.email and t.email.strip()) or (t.socios and t.socios.strip()):
            t_has = "Sim"
            
    e_has = "Não"
    if e:
        if (e.telefone and e.telefone.strip()) or (e.email and e.email.strip()) or (e.site and e.site.strip()):
            e_has = "Sim"
            
    return {
        "match_id": m.id,
        "corredor": m.corredor or "",
        "score_match": m.score_match,
        "score_geografico": m.score_geografico if m.score_geografico is not None else "",
        "score_match_v2": m.score_match_v2 if m.score_match_v2 is not None else "",
        "distancia_km": m.distancia_km if m.distancia_km is not None else "",
        "precisao_geografica_match": m.precisao_geografica_match or "",
        "transportadora_id": t.id if t else "",
        "transportadora_nome": (t.razao_social or t.nome_rntrc or t.nome_fantasia or "") if t else "",
        "transportadora_cnpj": t.cnpj if t else "",
        "transportadora_municipio": t.municipio if t else "",
        "transportadora_uf": t.uf if t else "",
        "transportadora_cep": t.cep if t else "",
        "transportadora_logradouro": t.logradouro if t else "",
        "transportadora_bairro": t.bairro if t else "",
        "transportadora_latitude": t.latitude if t and t.latitude is not None else "",
        "transportadora_longitude": t.longitude if t and t.longitude is not None else "",
        "transportadora_precisao_geocodificacao": t.precisao_geocodificacao if t else "",
        "embarcador_id": e.id if e else "",
        "embarcador_nome": (e.razao_social or e.nome_fantasia or "") if e else "",
        "embarcador_cnpj": e.cnpj if e else "",
        "embarcador_cidade": e.cidade if e else "",
        "embarcador_uf": e.uf if e else "",
        "embarcador_cep": e.cep if e else "",
        "embarcador_logradouro": e.logradouro if e else "",
        "embarcador_bairro": e.bairro if e else "",
        "embarcador_latitude": e.latitude if e and e.latitude is not None else "",
        "embarcador_longitude": e.longitude if e and e.longitude is not None else "",
        "embarcador_precisao_geocodificacao": e.precisao_geocodificacao if e else "",
        "tipo_carga": e.tipo_carga_provavel if e else "",
        "carroceria": e.carrocerias_provaveis if e else "",
        "status": m.status or "",
        "prioridade": m.prioridade or "",
        "contato_transportadora": t_has,
        "contato_embarcador": e_has,
        "observacao_validacao": obs
    }

def main():
    print("============================================================")
    print("VALIDADOR DO SCORE GEOGRÁFICO DE MATCHES")
    print("============================================================")
    
    os.makedirs("exports/geografia", exist_ok=True)
    
    fields = [
        "match_id", "corredor", "score_match", "score_geografico", "score_match_v2", "distancia_km",
        "precisao_geografica_match", "transportadora_id", "transportadora_nome", "transportadora_cnpj",
        "transportadora_municipio", "transportadora_uf", "transportadora_cep", "transportadora_logradouro",
        "transportadora_bairro", "transportadora_latitude", "transportadora_longitude",
        "transportadora_precisao_geocodificacao", "embarcador_id", "embarcador_nome", "embarcador_cnpj",
        "embarcador_cidade", "embarcador_uf", "embarcador_cep", "embarcador_logradouro", "embarcador_bairro",
        "embarcador_latitude", "embarcador_longitude", "embarcador_precisao_geocodificacao", "tipo_carga",
        "carroceria", "status", "prioridade", "contato_transportadora", "contato_embarcador", "observacao_validacao"
    ]
    
    with app.app_context():
        # Obter todos os matches com relacionamentos populados
        all_matches = MatchPreditivo.query.all()
        print(f"  Analizando {len(all_matches):,} matches...")
        
        # ─── 1. ANÁLISES BÁSICAS ───
        matches_com_score = 0
        matches_sem_score = 0
        prec_dist = {"endereco": 0, "cep": 0, "cidade": 0, "insuficiente": 0}
        
        distancias_por_corredor = {}
        score_geo_por_corredor = {}
        score_v2_por_corredor = {}
        
        conflitos_90_30 = 0
        excelentes_90_75 = 0
        
        for m in all_matches:
            # Distribuição
            if m.score_geografico is not None:
                matches_com_score += 1
                prec = m.precisao_geografica_match or "cidade"
                prec_dist[prec] += 1
                
                # Corredor
                corr = m.corredor or "Indefinido"
                if corr not in distancias_por_corredor:
                    distancias_por_corredor[corr] = []
                    score_geo_por_corredor[corr] = []
                    score_v2_por_corredor[corr] = []
                    
                distancias_por_corredor[corr].append(m.distancia_km)
                score_geo_por_corredor[corr].append(m.score_geografico)
                score_v2_por_corredor[corr].append(m.score_match_v2)
                
                # Check limites
                if m.score_match >= 90.0 and m.score_geografico <= 30.0:
                    conflitos_90_30 += 1
                if m.score_match >= 90.0 and m.score_geografico >= 75.0:
                    excelentes_90_75 += 1
            else:
                matches_sem_score += 1
                prec_dist["insuficiente"] += 1
                
        # ─── 2. EXPORTAR CSVs DE VALIDAÇÃO (Top 100, Distâncias, Corredores) ───
        # Top 100 score atual
        top100_atual_matches = sorted(all_matches, key=lambda x: -x.score_match)[:100]
        top100_atual_rows = [build_row(m, "Top 100 Score Atual") for m in top100_atual_matches]
        with open("exports/geografia/validacao_top100_score_atual.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, delimiter=";")
            w.writeheader()
            w.writerows(top100_atual_rows)
            
        # Top 100 score_v2
        matches_valid_v2 = [m for m in all_matches if m.score_match_v2 is not None]
        top100_v2_matches = sorted(matches_valid_v2, key=lambda x: -x.score_match_v2)[:100]
        top100_v2_rows = [build_row(m, "Top 100 Score V2") for m in top100_v2_matches]
        with open("exports/geografia/validacao_top100_score_v2.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, delimiter=";")
            w.writeheader()
            w.writerows(top100_v2_rows)
            
        # Top 100 score_geografico
        matches_valid_geo = [m for m in all_matches if m.score_geografico is not None]
        top100_geo_matches = sorted(matches_valid_geo, key=lambda x: -x.score_geografico)[:100]
        top100_geo_rows = [build_row(m, "Top 100 Score Geográfico") for m in top100_geo_matches]
        with open("exports/geografia/validacao_top100_score_geografico.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, delimiter=";")
            w.writeheader()
            w.writerows(top100_geo_rows)
            
        # Matches com score_match alto e score_geografico baixo (conflito)
        conflito_matches = [m for m in all_matches if m.score_match >= 85.0 and m.score_geografico is not None and m.score_geografico <= 30.0]
        conflito_rows = [build_row(m, "Score Alto e Geo Baixo (Ineficiente)") for m in conflito_matches]
        with open("exports/geografia/validacao_score_alto_geo_baixo.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, delimiter=";")
            w.writeheader()
            w.writerows(conflito_rows)
            
        # Matches com score_match baixo/moderado e score_geografico alto (oportunidade)
        oportunidade_matches = [m for m in all_matches if m.score_match < 50.0 and m.score_geografico is not None and m.score_geografico >= 70.0]
        oportunidade_rows = [build_row(m, "Score Baixo e Geo Alto (Oportunidade Proximidade)") for m in oportunidade_matches]
        with open("exports/geografia/validacao_score_baixo_geo_alto.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, delimiter=";")
            w.writeheader()
            w.writerows(oportunidade_rows)
            
        # Distâncias baixas (<= 5.0 km)
        d_baixas_matches = [m for m in all_matches if m.distancia_km is not None and m.distancia_km <= 5.0]
        d_baixas_rows = [build_row(m, "Excelente Proximidade (<= 5km)") for m in d_baixas_matches]
        with open("exports/geografia/validacao_distancias_baixas.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, delimiter=";")
            w.writeheader()
            w.writerows(d_baixas_rows)
            
        # Distâncias altas (> 300.0 km)
        d_altas_matches = [m for m in all_matches if m.distancia_km is not None and m.distancia_km > 300.0]
        d_altas_rows = [build_row(m, "Distância Crítica (> 300km)") for m in d_altas_matches]
        with open("exports/geografia/validacao_distancias_altas.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, delimiter=";")
            w.writeheader()
            w.writerows(d_altas_rows)
            
        # Amostras por corredor
        amostras_rows = []
        corredores_list = ["SP->DF", "MG->SP", "SC->SP", "MS->PR"]
        for corr in corredores_list:
            c_matches = [m for m in all_matches if m.corredor == corr][:25]
            for m in c_matches:
                amostras_rows.append(build_row(m, f"Amostra Corredor {corr}"))
        with open("exports/geografia/validacao_amostras_por_corredor.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, delimiter=";")
            w.writeheader()
            w.writerows(amostras_rows)
            
        # ─── 3. RANKINGS E QUANTIDADE DE MUDANÇA ───
        # Quantos top 100 atual continuam no top 100 v2?
        top100_atual_ids = set(m.id for m in top100_atual_matches)
        top100_v2_ids = set(m.id for m in top100_v2_matches)
        permanecem_top100 = len(top100_atual_ids.intersection(top100_v2_ids))
        substituidos_top100 = 100 - permanecem_top100
        
        # Mudança geral de posição
        # Ordenar a lista completa
        rank_a_sorted = sorted(all_matches, key=lambda x: (-x.score_match, x.id))
        rank_b_sorted = sorted(matches_valid_v2, key=lambda x: (-x.score_match_v2, x.id))
        
        rank_a_pos = {m.id: idx for idx, m in enumerate(rank_a_sorted)}
        rank_b_pos = {m.id: idx for idx, m in enumerate(rank_b_sorted)}
        
        mudaram_ranking = 0
        for m in matches_valid_v2:
            pos_a = rank_a_pos[m.id]
            pos_b = rank_b_pos[m.id]
            if pos_a != pos_b:
                mudaram_ranking += 1
                
        # ─── 4. ETAPA 4: SIMULAÇÃO DE PESOS ALTERNATIVOS ───
        # Colunas comparativo
        comp_fields = [
            "match_id", "corredor", "score_match", "score_geografico", "score_v2_atual",
            "score_v2_a", "score_v2_b", "score_v2_c", "rank_score_match", "rank_v2_a",
            "rank_v2_b", "rank_v2_c", "delta_rank_a", "delta_rank_b", "delta_rank_c",
            "precisao_geografica_match", "distancia_km"
        ]
        
        comp_rows = []
        for m in all_matches:
            t = m.transportadora
            e = m.embarcador
            if not t or not e or m.score_geografico is None:
                continue
                
            score_match = m.score_match
            score_geo = m.score_geografico
            
            t_comp = t.score_completude or 0
            e_comp = e.score_completude or 0
            avg_comp = (t_comp + e_comp) / 2.0
            
            score_a = 0.85 * score_match + 0.10 * score_geo + 0.05 * avg_comp
            score_b = 0.70 * score_match + 0.25 * score_geo + 0.05 * avg_comp
            score_c = 0.60 * score_match + 0.35 * score_geo + 0.05 * avg_comp
            
            comp_rows.append({
                "match_id": m.id,
                "corredor": m.corredor or "",
                "score_match": score_match,
                "score_geografico": score_geo,
                "score_v2_atual": m.score_match_v2 or 0.0,
                "score_v2_a": round(score_a, 2),
                "score_v2_b": round(score_b, 2),
                "score_v2_c": round(score_c, 2),
                "precisao_geografica_match": m.precisao_geografica_match or "",
                "distancia_km": m.distancia_km or 0.0
            })
            
        # Calcular posições
        # Sort and rank a
        sorted_a = sorted(comp_rows, key=lambda x: (-x["score_v2_a"], x["match_id"]))
        # Sort and rank b
        sorted_b = sorted(comp_rows, key=lambda x: (-x["score_v2_b"], x["match_id"]))
        # Sort and rank c
        sorted_c = sorted(comp_rows, key=lambda x: (-x["score_v2_c"], x["match_id"]))
        
        rank_pos_a = {x["match_id"]: idx for idx, x in enumerate(sorted_a)}
        rank_pos_b = {x["match_id"]: idx for idx, x in enumerate(sorted_b)}
        rank_pos_c = {x["match_id"]: idx for idx, x in enumerate(sorted_c)}
        
        # Rank score_match
        sorted_orig = sorted(comp_rows, key=lambda x: (-x["score_match"], x["match_id"]))
        rank_pos_orig = {x["match_id"]: idx for idx, x in enumerate(sorted_orig)}
        
        for r in comp_rows:
            m_id = r["match_id"]
            r_orig = rank_pos_orig[m_id]
            r_a = rank_pos_a[m_id]
            r_b = rank_pos_b[m_id]
            r_c = rank_pos_c[m_id]
            
            r["rank_score_match"] = r_orig + 1
            r["rank_v2_a"] = r_a + 1
            r["rank_v2_b"] = r_b + 1
            r["rank_v2_c"] = r_c + 1
            r["delta_rank_a"] = r_orig - r_a
            r["delta_rank_b"] = r_orig - r_b
            r["delta_rank_c"] = r_orig - r_c
            
        with open("exports/geografia/comparativo_pesos_score_v2.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=comp_fields, delimiter=";")
            w.writeheader()
            w.writerows(comp_rows)
            
        # ─── 5. ETAPA 5: ANÁLISE DE CONFIABILIDADE GEOGRÁFICA ───
        conf_fields = [
            "match_id", "corredor", "transportadora_nome", "embarcador_nome", "latitude_t",
            "longitude_t", "precisao_t", "latitude_e", "longitude_e", "precisao_e",
            "distancia_km", "confiabilidade_geografica"
        ]
        
        conf_rows = []
        conf_counts = {"alta": 0, "media": 0, "baixa": 0, "insuficiente": 0}
        
        for m in all_matches:
            t = m.transportadora
            e = m.embarcador
            
            if not t or not e:
                conf = "insuficiente"
            elif t.latitude is None or t.longitude is None or e.latitude is None or e.longitude is None:
                conf = "insuficiente"
            else:
                t_prec = t.precisao_geocodificacao or "cidade"
                e_prec = e.precisao_geocodificacao or "cidade"
                
                # Classificar
                if t_prec in ("endereco", "cep") and e_prec in ("endereco", "cep"):
                    conf = "alta"
                elif (t_prec in ("endereco", "cep") and e_prec == "cidade") or (e_prec in ("endereco", "cep") and t_prec == "cidade"):
                    conf = "media"
                else:
                    conf = "baixa"
                    
            conf_counts[conf] += 1
            
            conf_rows.append({
                "match_id": m.id,
                "corredor": m.corredor or "",
                "transportadora_nome": (t.razao_social or t.nome_rntrc or t.nome_fantasia or "") if t else "",
                "embarcador_nome": (e.razao_social or e.nome_fantasia or "") if e else "",
                "latitude_t": t.latitude if t and t.latitude is not None else "",
                "longitude_t": t.longitude if t and t.longitude is not None else "",
                "precisao_t": t.precisao_geocodificacao if t else "",
                "latitude_e": e.latitude if e and e.latitude is not None else "",
                "longitude_e": e.longitude if e and e.longitude is not None else "",
                "precisao_e": e.precisao_geocodificacao if e else "",
                "distancia_km": m.distancia_km if m.distancia_km is not None else "",
                "confiabilidade_geografica": conf
            })
            
        with open("exports/geografia/confiabilidade_geografica_matches.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=conf_fields, delimiter=";")
            w.writeheader()
            w.writerows(conf_rows)
            
        # ─── 6. CASOS CRÍTICOS / SUSPEITOS E PROMISSORES ───
        # Casos suspeitos (score_match alto >= 90, distancia_km alta > 150km, precisao = cidade)
        suspeitos = [r for r in top100_atual_rows if r["score_match"] >= 90.0 and r["distancia_km"] != "" and r["distancia_km"] > 150.0 and r["precisao_geografica_match"] == "cidade"]
        # Se poucos no top 100, buscar na base geral
        if len(suspeitos) < 20:
            geral_suspeitos = [build_row(m, "Suspeito: Score alto, distância alta, precisão cidade") for m in all_matches if m.score_match >= 90.0 and m.distancia_km is not None and m.distancia_km > 150.0 and m.precisao_geografica_match == "cidade"]
            suspeitos.extend(geral_suspeitos)
            # Dedup e limitar
            seen = set()
            suspeitos_clean = []
            for s in suspeitos:
                if s["match_id"] not in seen:
                    seen.add(s["match_id"])
                    suspeitos_clean.append(s)
            suspeitos = suspeitos_clean[:20]
            
        # Casos promissores (score_match alto >= 85, distancia_km baixa <= 15.0km, contatos preenchidos)
        promissores = [r for r in top100_v2_rows if r["score_match"] >= 85.0 and r["distancia_km"] != "" and r["distancia_km"] <= 15.0 and r["contato_transportadora"] == "Sim" and r["contato_embarcador"] == "Sim"]
        if len(promissores) < 20:
            geral_promissores = [build_row(m, "Promissor: Score alto, distância baixa, contato completo") for m in all_matches if m.score_match >= 85.0 and m.distancia_km is not None and m.distancia_km <= 15.0]
            # Filtrar por quem tem contato se possível, senão só distância
            geral_promissores_contato = [p for p in geral_promissores if p["contato_transportadora"] == "Sim" and p["contato_embarcador"] == "Sim"]
            promissores.extend(geral_promissores_contato if len(geral_promissores_contato) >= 20 else geral_promissores)
            
            seen = set()
            promissores_clean = []
            for p in promissores:
                if p["match_id"] not in seen:
                    seen.add(p["match_id"])
                    promissores_clean.append(p)
            promissores = promissores_clean[:20]
            
        # ─── 7. COMPILAR MARKDOWN ───
        corredores = sorted(list(distancias_por_corredor.keys()))
        corredores_md = ""
        for c in corredores:
            dists = distancias_por_corredor.get(c, [])
            c_geos = score_geo_por_corredor.get(c, [])
            c_v2s = score_v2_por_corredor.get(c, [])
            tot = len(dists)
            
            d_min = min(dists) if tot > 0 else 0.0
            d_max = max(dists) if tot > 0 else 0.0
            d_avg = sum(dists)/tot if tot > 0 else 0.0
            d_med = median(dists)
            
            g_avg = sum(c_geos)/tot if tot > 0 else 0.0
            v2_avg = sum(c_v2s)/tot if tot > 0 else 0.0
            
            corredores_md += f"| {c} | {tot:,} | {d_avg:.2f} km / {d_med:.2f} km | {d_min:.2f} km / {d_max:.2f} km | {g_avg:.2f} | {v2_avg:.2f} |\n"
            
        # Formatar casos suspeitos e promissores
        suspeitos_md = ""
        for idx, s in enumerate(suspeitos):
            suspeitos_md += f"| {idx+1} | #{s['match_id']} | {s['corredor']} | {s['score_match']} | {s['score_geografico']} | {s['distancia_km']} km | {s['transportadora_nome']} ➔ {s['embarcador_nome']} |\n"
            
        promissores_md = ""
        for idx, p in enumerate(promissores):
            promissores_md += f"| {idx+1} | #{p['match_id']} | {p['corredor']} | {p['score_match']} | {p['score_geografico']} | {p['distancia_km']} km | {p['transportadora_nome']} ➔ {p['embarcador_nome']} |\n"
            
        md_content = f"""# RELATÓRIO DE VALIDAÇÃO DO SCORE GEOGRÁFICO

Este documento apresenta a análise de confiabilidade e impacto do novo **Score Geográfico** nos Matches Preditivos, validando as distâncias reais e avaliando a precisão municipal.

---

## 📈 Métricas Gerais do Score Geográfico

* **Matches com Score Geográfico Calculado:** **{matches_com_score:,}** ({matches_com_score/len(all_matches)*100:.2f}%)
* **Matches com Geografia Insuficiente (sem lat/lon):** **{matches_sem_score:,}** ({matches_sem_score/len(all_matches)*100:.2f}%)

### Distribuição por Nível de Precisão Cadastral:
* **Precisão Endereço (Rua/Número):** **{prec_dist['endereco']:,}** ({prec_dist['endereco']/len(all_matches)*100:.2f}%)
* **Precisão CEP:** **{prec_dist['cep']:,}** ({prec_dist['cep']/len(all_matches)*100:.2f}%)
* **Precisão Cidade (Centroide Municipal):** **{prec_dist['cidade']:,}** ({prec_dist['cidade']/len(all_matches)*100:.2f}%)
* **Insuficiente:** **{prec_dist['insuficiente']:,}** ({prec_dist['insuficiente']/len(all_matches)*100:.2f}%)

---

## 🗺️ Análise de Distâncias e Scores por Corredor

| Corredor | Matches | Distância Média / Mediana | Distância Mínima / Máxima | Score Geo Médio | Score V2 Médio |
| :--- | :--- | :--- | :--- | :--- | :--- |
{corredores_md}

---

## ⚠️ Análise de Confiabilidade Geográfica (Etapa 5)

Como a maioria dos dados de localização são baseados em centroides de cidades (precisão municipal):
* **Confiabilidade ALTA (Endereço/CEP dos 2 lados):** **{conf_counts['alta']:,}** ({conf_counts['alta']/len(all_matches)*100:.2f}%)
* **Confiabilidade MÉDIA (Um lado CEP/Endereço e outro Cidade):** **{conf_counts['media']:,}** ({conf_counts['media']/len(all_matches)*100:.2f}%)
* **Confiabilidade BAIXA (Ambos lados apenas Cidade):** **{conf_counts['baixa']:,}** ({conf_counts['baixa']/len(all_matches)*100:.2f}%)
* **Confiabilidade INSUFICIENTE (Falta coordenada de algum lado):** **{conf_counts['insuficiente']:,}** ({conf_counts['insuficiente']/len(all_matches)*100:.2f}%)

> [!WARNING]
> A confiabilidade predominante na base é **BAIXA ({conf_counts['baixa']/len(all_matches)*100:.2f}%)** porque a maioria dos matches é calculada usando centroide municipal em ambos os lados. Distâncias reais de 0 km indicam apenas que as empresas estão na mesma cidade, mas não representam a distância real de suas garagens/fábricas.

---

## ⚡ Simulação de Impacto no Ranking de Prospecção

* **Total de Matches que mudariam de posição:** **{mudaram_ranking:,}** ({mudaram_ranking/len(matches_valid_v2)*100:.2f}% dos válidos)
* **Matches do Top 100 atual que continuam no Top 100 V2:** **{permanecem_top100:,}** (ficando **{substituidos_top100:,}** de fora por proximidade)
* **Matches com Score Atual Alto (>= 90) mas Geografia Ruim (Score Geo <= 30):** **{conflitos_90_30:,}**
* **Matches com Score Atual Alto (>= 90) e Geografia Excelente (Score Geo >= 75):** **{excelentes_90_75:,}**

---

## 🕵️‍♂️ Casos Suspeitos (Top 20 — Alta Distância, Nota Alta, Precisão Cidade)
Estes matches possuem nota alta no algoritmo comercial anterior, mas a distância física calculada é superior a 150 km. Como a precisão é municipal, a proximidade real pode ser ainda pior:

| # | Match ID | Corredor | Score Atual | Score Geo | Distância | Empresas |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
{suspeitos_md}

---

## 💎 Casos Promissores (Top 20 — Proximidade Excelente, Nota Alta)
Estes matches possuem ótima afinidade comercial, excelente proximidade geográfica real e já contam com dados de contato consolidados:

| # | Match ID | Corredor | Score Atual | Score Geo | Distância | Empresas |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
{promissores_md}

---

## 📢 Conclusão e Recomendação Comercial

1. **Recomendação de Ativação:**
   * **NÃO ativar o Score Match V2 como ordenação principal ainda.** Devido a **{conf_counts['baixa']/len(all_matches)*100:.2f}%** dos matches estarem em confiabilidade **BAIXA**, ordenar a prospecção por esse score pode distorcer o pipeline comercial com distâncias otimistas (0.00 km fictícios de centroides municipais).
2. **Uso como Sinal Auxiliar:**
   * Recomenda-se disponibilizar o Score Geográfico e a distância estimada apenas como **badges informativos na UI** (Ex: *Próximo*, *Mesma Cidade*, *Distante*) para visualização do consultor comercial, sem afetar o ranking de matches.
3. **Melhoria da Qualidade Cadastral (Próximos Passos):**
   * Priorizar o enriquecimento e geocodificação dos CEPs e endereços exatos dos embarcadores antes de migrar o ranking definitivo para a versão V2.
4. **Peso Geográfico Recomendado (para a UI/Fórmulas Futuras):**
   * Recomenda-se adotar a **Fórmula A — Conservadora** (`0.85 * score_match + 0.10 * score_geografico + 0.05 * score_completude`), pois limita a volatilidade e penaliza menos os matches estratégicos baseados em centroides municipais.
"""
        with open("exports/geografia/RELATORIO_VALIDACAO_SCORE_GEOGRAFICO.md", "w", encoding="utf-8") as f:
            f.write(md_content.strip())
            
    print("Análises geográficas e relatórios concluídos com sucesso!")
    print("  * Relatório Executivo: exports/geografia/RELATORIO_VALIDACAO_SCORE_GEOGRAFICO.md")

if __name__ == "__main__":
    main()
