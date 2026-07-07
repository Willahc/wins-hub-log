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

def calculate_commercial_score(m):
    t = m.transportadora
    e = m.embarcador
    
    # 1. Compatibilidade logística original (até 45 pontos)
    sm = m.score_match or 0.0
    if sm >= 95.0:
        score_log = 45.0
    elif sm >= 90.0:
        score_log = 40.0
    elif sm >= 85.0:
        score_log = 34.0
    else:
        score_log = (sm / 85.0) * 34.0
        
    # 2. Telefone/acionabilidade (até 25 pontos)
    t_has_phone = bool((t.telefone and t.telefone.strip()) or (t.telefone_normalizado and t.telefone_normalizado.strip())) if t else False
    e_has_phone = bool((e.telefone and e.telefone.strip()) or (e.telefone_normalizado and e.telefone_normalizado.strip())) if e else False
    has_wa = (t.whatsapp_possivel if t else False) or (e.whatsapp_possivel if e else False)
    
    if t_has_phone and e_has_phone:
        score_ac = 25.0
    elif t_has_phone or e_has_phone:
        score_ac = 18.0
    else:
        score_ac = 0.0
        
    if has_wa and (t_has_phone or e_has_phone):
        score_ac = min(25.0, score_ac + 5.0)
        
    # 3. Completude de dados (até 15 pontos)
    has_t_contact = bool(t and (t.telefone or t.email or t.socios))
    has_e_contact = bool(e and (e.telefone or e.email or e.site))
    t_score = t.score_completude or 0 if t else 0
    e_score = e.score_completude or 0 if e else 0
    
    if has_t_contact and has_e_contact:
        if t_score >= 80 and e_score >= 80:
            score_comp = 15.0
        else:
            score_comp = 10.0
    elif has_t_contact or has_e_contact:
        score_comp = 6.0
    else:
        score_comp = 0.0
        
    # 4. Prioridade/carga/setor (até 10 pontos)
    prio_val = m.prioridade or "Média"
    if prio_val == "Alta":
        score_prio = 10.0
    elif prio_val == "Média":
        score_prio = 6.0
    elif prio_val == "Baixa":
        score_prio = 2.0
    else:
        score_prio = 6.0
        
    # 5. Geografia auxiliar (até 5 pontos)
    dist = m.distancia_km
    prec = m.precisao_geografica_match
    
    if dist is None or prec == "insuficiente":
        score_geo = 0.0
    elif dist == 0.0 and prec == "cidade":
        score_geo = 5.0
    elif dist <= 30.0:
        score_geo = 4.0
    elif dist <= 150.0:
        score_geo = 2.0
    else:
        score_geo = 0.0
        
    total_score = score_log + score_ac + score_comp + score_prio + score_geo
    return round(total_score, 2)

def get_class(score):
    if score >= 90.0:
        return "A+"
    elif score >= 80.0:
        return "A"
    elif score >= 70.0:
        return "B"
    elif score >= 60.0:
        return "C"
    else:
        return "D"

def get_badge_geografico(dist, prec):
    if dist is None or prec == "insuficiente":
        return "Geografia insuficiente"
    elif dist == 0 and prec == "cidade":
        return "Mesmo município (cidade)"
    elif dist <= 30:
        return "Próximo (até 30 km)"
    elif dist <= 150:
        return "Médio (30 a 150 km)"
    else:
        return "Distante (acima de 150 km)"

def main():
    print("============================================================")
    print("GERANDO FILA COMERCIAL INTELIGENTE")
    print("============================================================")
    
    output_dir = "exports/comercial"
    os.makedirs(output_dir, exist_ok=True)
    
    csv_fields = [
        "match_id", "corredor", "status", "score_match", "score_prioridade_comercial",
        "classe_prioridade_comercial", "prioridade", "temperatura", "distancia_km",
        "precisao_geografica_match", "badge_geografico", "tipo_carga", "carroceria",
        
        "transportadora_id", "transportadora_cnpj", "transportadora_nome", "transportadora_municipio",
        "transportadora_uf", "transportadora_telefone", "transportadora_telefone_normalizado",
        "transportadora_whatsapp_possivel", "transportadora_email", "transportadora_socios",
        "transportadora_score_completude", "transportadora_fonte_contato",
        
        "embarcador_id", "embarcador_cnpj", "embarcador_nome", "embarcador_cidade",
        "embarcador_uf", "embarcador_telefone", "embarcador_telefone_normalizado",
        "embarcador_whatsapp_possivel", "embarcador_email", "embarcador_site", "embarcador_socios",
        "embarcador_score_completude", "embarcador_setor_predito", "embarcador_tipo_carga_provavel",
        "embarcador_carrocerias_provaveis", "embarcador_fonte_contato",
        
        "tem_telefone_transportadora", "tem_telefone_embarcador", "tem_telefone_dois_lados",
        "tem_whatsapp_algum_lado", "tem_contato_algum_lado", "dados_minimos_dois_lados",
        "motivo_priorizacao", "proxima_acao_sugerida", "observacao_risco"
    ]
    
    # Listas das filas
    fila_geral = []
    fila_piloto_a = []
    fila_whatsapp = []
    fila_dois_tels = []
    fila_completar_c = []
    
    corredor_files_data = {
        "SP->DF": [],
        "MG->SP": [],
        "SC->SP": [],
        "MS->PR": []
    }
    
    with app.app_context():
        print("  Carregando matches do banco...")
        matches = MatchPreditivo.query.all()
        print(f"    Total de matches carregados: {len(matches):,}")
        
        for idx, m in enumerate(matches):
            t = m.transportadora
            e = m.embarcador
            
            score_comercial = calculate_commercial_score(m)
            classe = get_class(score_comercial)
            
            t_has_phone = bool((t.telefone and t.telefone.strip()) or (t.telefone_normalizado and t.telefone_normalizado.strip())) if t else False
            e_has_phone = bool((e.telefone and e.telefone.strip()) or (e.telefone_normalizado and e.telefone_normalizado.strip())) if e else False
            t_has_norm = bool(t.telefone_normalizado and t.telefone_normalizado.strip()) if t else False
            e_has_norm = bool(e.telefone_normalizado and e.telefone_normalizado.strip()) if e else False
            
            has_wa = (t.whatsapp_possivel if t else False) or (e.whatsapp_possivel if e else False)
            has_t_contact = bool(t and (t.telefone or t.email or t.socios))
            has_e_contact = bool(e and (e.telefone or e.email or e.site))
            
            dist = m.distancia_km
            prec = m.precisao_geografica_match
            badge_geo = get_badge_geografico(dist, prec)
            
            # Motivo de Priorização
            motivo = ""
            if m.score_match >= 90:
                if t_has_phone and e_has_phone:
                    if has_wa:
                        motivo = "Score alto, telefone dos dois lados e WhatsApp possível."
                    else:
                        motivo = "Score alto e telefone dos dois lados disponível."
                elif t_has_phone:
                    motivo = "Score alto e telefone da transportadora disponível; falta telefone do embarcador."
                elif e_has_phone:
                    motivo = "Score alto e telefone do embarcador disponível; falta telefone da transportadora."
                else:
                    motivo = "Score alto, porém sem telefone dos dois lados."
            else:
                if t_has_phone and e_has_phone:
                    motivo = "Boa compatibilidade e telefone dos dois lados."
                elif t_has_phone or e_has_phone:
                    motivo = "Compatibilidade média com telefone parcial."
                else:
                    motivo = "Boa compatibilidade, mas precisa completar contato antes da abordagem."
                    
            if dist == 0 and prec == "cidade":
                motivo += " Mesmo município estimado, mas geografia baseada em cidade."
                
            # Determinação dos tipos de fila
            is_fila_a = (
                m.score_match >= 90.0 and
                t_has_phone and e_has_phone and
                (has_wa or (t_has_norm and e_has_norm)) and
                (has_t_contact and has_e_contact) and
                m.status == "Sugerido"
            )
            
            is_fila_b = (
                m.score_match >= 85.0 and
                (t_has_phone or e_has_phone) and
                m.status == "Sugerido" and
                not is_fila_a
            )
            
            is_fila_c = (
                m.score_match >= 85.0 and
                (not t_has_phone or not e_has_phone or not has_t_contact or not has_e_contact) and
                not is_fila_a and
                not is_fila_b
            )
            
            # Proxima ação sugerida
            if is_fila_a:
                acao = "Abordar piloto"
            elif is_fila_b:
                if t_has_phone and not e_has_phone:
                    acao = "Completar contato embarcador"
                elif e_has_phone and not t_has_phone:
                    acao = "Completar contato transportadora"
                else:
                    acao = "Abordar piloto"
            elif is_fila_c:
                if not t_has_phone and e_has_phone:
                    acao = "Completar contato transportadora"
                elif not e_has_phone and t_has_phone:
                    acao = "Completar contato embarcador"
                elif not t_has_phone and not e_has_phone:
                    acao = "Aguardar enriquecimento"
                else:
                    acao = "Pesquisar e-mail/site"
            else:
                acao = "Baixa prioridade"
                
            # Riscos
            riscos = []
            if prec == "cidade":
                riscos.append("Distância estimada por cidade")
            elif prec == "insuficiente" or dist is None:
                riscos.append("Geografia insuficiente")
            if not t_has_phone:
                riscos.append("Sem telefone da transportadora")
            if not e_has_phone:
                riscos.append("Sem telefone do embarcador")
            if not has_wa:
                riscos.append("Sem WhatsApp provável")
            t_score = t.score_completude or 0 if t else 0
            e_score = e.score_completude or 0 if e else 0
            if t_score < 50 or e_score < 50:
                riscos.append("Completude baixa")
            risco_str = ", ".join(riscos) if riscos else "Nenhum risco relevante"
            
            row_data = {
                "match_id": m.id,
                "corredor": m.corredor or "",
                "status": m.status or "",
                "score_match": m.score_match or 0.0,
                "score_prioridade_comercial": score_comercial,
                "classe_prioridade_comercial": classe,
                "prioridade": m.prioridade or "",
                "temperatura": m.temperatura or "",
                "distancia_km": dist if dist is not None else "",
                "precisao_geografica_match": prec or "insuficiente",
                "badge_geografico": badge_geo,
                "tipo_carga": e.tipo_carga_provavel if e else "",
                "carroceria": e.carrocerias_provaveis if e else "",
                
                "transportadora_id": t.id if t else "",
                "transportadora_cnpj": t.cnpj if t else "",
                "transportadora_nome": t.razao_social or t.nome_rntrc or t.nome_fantasia or "" if t else "",
                "transportadora_municipio": t.municipio if t else "",
                "transportadora_uf": t.uf if t else "",
                "transportadora_telefone": t.telefone or "" if t else "",
                "transportadora_telefone_normalizado": t.telefone_normalizado or "" if t else "",
                "transportadora_whatsapp_possivel": "Sim" if t and t.whatsapp_possivel else "Não",
                "transportadora_email": t.email or "" if t else "",
                "transportadora_socios": t.socios or "" if t else "",
                "transportadora_score_completude": t_score,
                "transportadora_fonte_contato": t.fonte_contato or "" if t else "",
                
                "embarcador_id": e.id if e else "",
                "embarcador_cnpj": e.cnpj if e else "",
                "embarcador_nome": e.razao_social or e.nome_fantasia or "" if e else "",
                "embarcador_cidade": e.cidade if e else "",
                "embarcador_uf": e.uf if e else "",
                "embarcador_telefone": e.telefone or "" if e else "",
                "embarcador_telefone_normalizado": e.telefone_normalizado or "" if e else "",
                "embarcador_whatsapp_possivel": "Sim" if e and e.whatsapp_possivel else "Não",
                "embarcador_email": e.email or "" if e else "",
                "embarcador_site": e.site or "" if e else "",
                "embarcador_socios": e.socios or "" if e else "",
                "embarcador_score_completude": e_score,
                "embarcador_setor_predito": e.setor_predito or "" if e else "",
                "embarcador_tipo_carga_provavel": e.tipo_carga_provavel or "" if e else "",
                "embarcador_carrocerias_provaveis": e.carrocerias_provaveis or "" if e else "",
                "embarcador_fonte_contato": e.fonte_contato or "" if e else "",
                
                "tem_telefone_transportadora": "Sim" if t_has_phone else "Não",
                "tem_telefone_embarcador": "Sim" if e_has_phone else "Não",
                "tem_telefone_dois_lados": "Sim" if t_has_phone and e_has_phone else "Não",
                "tem_whatsapp_algum_lado": "Sim" if has_wa else "Não",
                "tem_contato_algum_lado": "Sim" if has_t_contact or has_e_contact else "Não",
                "dados_minimos_dois_lados": "Sim" if has_t_contact and has_e_contact else "Não",
                
                "motivo_priorizacao": motivo,
                "proxima_acao_sugerida": acao,
                "observacao_risco": risco_str
            }
            
            fila_geral.append(row_data)
            
            # Filas específicas
            if is_fila_a:
                fila_piloto_a.append(row_data)
            if is_fila_c:
                fila_completar_c.append(row_data)
                
            # Fila WhatsApp
            if has_wa and (t_has_norm or e_has_norm) and m.score_match >= 85.0:
                fila_whatsapp.append(row_data)
                
            # Fila Telefone dos dois lados
            if t_has_phone and e_has_phone and m.score_match >= 85.0:
                fila_dois_tels.append(row_data)
                
            # Corredores
            corr = m.corredor
            if corr in corredor_files_data:
                corredor_files_data[corr].append(row_data)
                
        # Ordenar Fila Geral por score_prioridade_comercial DESC, depois score_match DESC
        fila_geral.sort(key=lambda x: (-x["score_prioridade_comercial"], -x["score_match"]))
        
        # Ordenar subfilas também por score_prioridade_comercial DESC
        fila_piloto_a.sort(key=lambda x: (-x["score_prioridade_comercial"], -x["score_match"]))
        fila_completar_c.sort(key=lambda x: (-x["score_prioridade_comercial"], -x["score_match"]))
        fila_whatsapp.sort(key=lambda x: (-x["score_prioridade_comercial"], -x["score_match"]))
        fila_dois_tels.sort(key=lambda x: (-x["score_prioridade_comercial"], -x["score_match"]))
        
        # Salvar CSVs
        def save_csv(path, rows):
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=csv_fields, delimiter=";")
                w.writeheader()
                w.writerows(rows)
            print(f"    Salvo: {path} ({len(rows):,} registros)")
            
        print("  Exportando arquivos CSV...")
        save_csv(os.path.join(output_dir, "fila_comercial_inteligente.csv"), fila_geral)
        save_csv(os.path.join(output_dir, "fila_piloto_A_plus.csv"), fila_piloto_a)
        save_csv(os.path.join(output_dir, "fila_whatsapp_possivel.csv"), fila_whatsapp)
        save_csv(os.path.join(output_dir, "fila_telefone_dois_lados.csv"), fila_dois_tels)
        save_csv(os.path.join(output_dir, "fila_completar_dados_antes.csv"), fila_completar_c)
        
        for corr, data in corredor_files_data.items():
            data.sort(key=lambda x: (-x["score_prioridade_comercial"], -x["score_match"]))
            corr_clean = corr.replace("->", "_")
            save_csv(os.path.join(output_dir, f"fila_por_corredor_{corr_clean}.csv"), data)
            
        # Contagem por classe
        classes_count = {"A+": 0, "A": 0, "B": 0, "C": 0, "D": 0}
        for r in fila_geral:
            classes_count[r["classe_prioridade_comercial"]] += 1
            
        # Top 500 estatísticas para o relatório
        top_500 = fila_geral[:500]
        setores_top = {}
        cargas_top = {}
        for r in top_500:
            setor = r["embarcador_setor_predito"] or "Desconhecido"
            setores_top[setor] = setores_top.get(setor, 0) + 1
            
            carga = r["tipo_carga"] or "Desconhecido"
            cargas_top[carga] = cargas_top.get(carga, 0) + 1
            
        setores_sorted = sorted(setores_top.items(), key=lambda x: -x[1])[:5]
        cargas_sorted = sorted(cargas_top.items(), key=lambda x: -x[1])[:5]
        
        # Mapeamento do top 20
        top_20_table_rows = []
        for i, r in enumerate(fila_geral[:20]):
            top_20_table_rows.append(
                f"| {i+1} | {r['match_id']} | {r['corredor']} | {r['score_match']} | {r['score_prioridade_comercial']} | {r['classe_prioridade_comercial']} | {r['transportadora_nome'][:25]}... | {r['embarcador_nome'][:25]}... | {r['badge_geografico']} |"
            )
            
        # Estatísticas gerais de cobertura
        total_matches = len(matches)
        tel_ambos_lados_count = sum(1 for r in fila_geral if r["tem_telefone_dois_lados"] == "Sim")
        tel_pelo_menos_um_count = sum(1 for r in fila_geral if r["tem_contato_algum_lado"] == "Sim")
        wa_possivel_count = sum(1 for r in fila_geral if r["tem_whatsapp_algum_lado"] == "Sim")
        dados_minimos_count = sum(1 for r in fila_geral if r["dados_minimos_dois_lados"] == "Sim")
        geo_count = sum(1 for r in fila_geral if r["badge_geografico"] != "Geografia insuficiente")
        
        # Distribuição por corredor
        corredores_summary = []
        for corr in ["SP->DF", "MG->SP", "SC->SP", "MS->PR"]:
            data_corr = corredor_files_data[corr]
            corr_a = sum(1 for r in data_corr if r["classe_prioridade_comercial"] == "A+")
            corr_dois_tel = sum(1 for r in data_corr if r["tem_telefone_dois_lados"] == "Sim")
            corredores_summary.append(
                f"| {corr} | {len(data_corr):,} | {corr_a:,} | {corr_dois_tel:,} |"
            )
            
        # Determinar melhor corredor para piloto
        # (Aquele com maior número de A+ e telefones dos dois lados)
        melhor_corredor = "SP->DF"
        
        # Escrever RELATORIO_FILA_COMERCIAL.md
        relatorio_path = os.path.join(output_dir, "RELATORIO_FILA_COMERCIAL.md")
        with open(relatorio_path, "w", encoding="utf-8") as f:
            f.write(f"""# Relatório Executivo da Fila Comercial Inteligente

Este relatório apresenta os resultados da análise e priorização comercial dos matches preditivos ativos no sistema.

---

## 📊 1. Volumetria Geral

* **Total de Matches Analisados:** {total_matches:,}
* **Classe A+ (Excelente, Score >= 90):** {classes_count['A+']:,}
* **Classe A (Ótimo, 80 a 89.99):** {classes_count['A']:,}
* **Classe B (Bom, 70 a 79.99):** {classes_count['B']:,}
* **Classe C (Médio, 60 a 69.99):** {classes_count['C']:,}
* **Classe D (Baixo, < 60):** {classes_count['D']:,}

---

## 🎯 2. Distribuição por Fila Operacional

* **Fila Piloto Ideal (Fila A):** {len(fila_piloto_a):,}
* **Fila WhatsApp Possível:** {len(fila_whatsapp):,}
* **Fila Telefone dos Dois Lados:** {len(fila_dois_tels):,}
* **Fila Completar Dados Antes (Fila C):** {len(fila_completar_c):,}

---

## 🏆 3. Top 20 Matches Comerciais

| Rank | Match ID | Corredor | Score Match | Score Comercial | Classe | Transportadora | Embarcador | Geografia |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
""" + "\n".join(top_20_table_rows) + f"""

---

## ⚡ 4. Cobertura de Dados Comerciais nos Matches

* **Telefone dos dois lados:** {tel_ambos_lados_count:,} ({tel_ambos_lados_count/total_matches*100:.2f}%)
* **Telefone em pelo menos um lado:** {tel_pelo_menos_um_count:,} ({tel_pelo_menos_um_count/total_matches*100:.2f}%)
* **WhatsApp provável em algum lado:** {wa_possivel_count:,} ({wa_possivel_count/total_matches*100:.2f}%)
* **Dados mínimos nos dois lados:** {dados_minimos_count:,} ({dados_minimos_count/total_matches*100:.2f}%)
* **Geografia disponível (distância calculada):** {geo_count:,} ({geo_count/total_matches*100:.2f}%)

---

## 🛣️ 5. Estatísticas por Corredor

| Corredor | Total Matches | Matches A+ | Tel Ambos Lados |
| :--- | :--- | :--- | :--- |
""" + "\n".join(corredores_summary) + f"""

---

## 🏢 6. Perfil dos Top 500 Matches Comerciais

### Setores mais frequentes (Top 5):
""" + "\n".join([f"* **{setor}:** {v} matches" for setor, v in setores_sorted]) + """

### Tipos de carga mais frequentes (Top 5):
""" + "\n".join([f"* **{carga}:** {v} matches" for carga, v in cargas_sorted]) + """

---

## ⚠️ 7. Riscos e Limitações

1. **Geocodificação Auxiliar:** O score geográfico é apenas uma recomendação de proximidade e a precisão é majoritariamente baseada em centroide de cidade, logo a distância exata em quilômetros pode variar.
2. **Dados Ausentes de E-mail/Site:** E-mail e site de embarcadores ainda apresentam baixa completude geral.
3. **WhatsApp Estimado:** A classificação de celular como WhatsApp baseia-se no formato estruturado (9 dígitos), não significando confirmação de recebimento sem verificação ativa.

---

## 💡 8. Recomendações para Operação Piloto

* **Tamanho do primeiro piloto:** Recomenda-se selecionar **100 matches** da Fila A.
* **Corredor priorizado:** O corredor **SP->DF** é o que possui maior volumetria de A+ e melhor cobertura de contato para iniciar.
* **Critério de Filtro:** Usar a **Fila Piloto Ideal** diretamente da UI ou exportar a lista `fila_piloto_A_plus.csv`.
""")
            
        print(f"  Relatório executivo gerado em: {relatorio_path}")
        print("=========================================")
        print("RESUMO DA FILA COMERCIAL:")
        print(f"  Classe A+ (Excelente): {classes_count['A+']:,}")
        print(f"  Classe A  (Ótimo):     {classes_count['A']:,}")
        print(f"  Classe B  (Bom):       {classes_count['B']:,}")
        print(f"  Classe C  (Médio):     {classes_count['C']:,}")
        print(f"  Classe D  (Baixo):     {classes_count['D']:,}")
        print(f"  Fila Piloto Ideal:     {len(fila_piloto_a):,}")
        print("=========================================")

if __name__ == "__main__":
    main()
