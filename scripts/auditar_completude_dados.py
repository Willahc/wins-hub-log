#!/usr/bin/env python3
import os
import sys
import csv

# Add root folder to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import Transportadora, EmbarcadorProvavel, MatchPreditivo

def calculate_transportadora_score(t):
    score = 0
    missing = []
    
    # 1. CNPJ/razão/cidade/UF: 20
    if t.cnpj: score += 5
    else: missing.append("cnpj")
    if t.razao_social or t.nome_fantasia or t.nome_rntrc: score += 5
    else: missing.append("razao_social/nome")
    if t.municipio: score += 5
    else: missing.append("municipio")
    if t.uf: score += 5
    else: missing.append("uf")
    
    # 2. CNAE/RNTRC/corredor: 20
    if t.cnae_principal: score += 7
    else: missing.append("cnae_principal")
    if t.numero_rntrc: score += 7
    else: missing.append("numero_rntrc")
    if t.corredor_alvo or t.corredor: score += 6
    else: missing.append("corredor")
    
    # 3. telefone: 25
    if t.telefone: score += 25
    else: missing.append("telefone")
    
    # 4. sócios/QSA: 15
    if t.socios: score += 15
    else: missing.append("socios")
    
    # 5. endereço/CEP/bairro/logradouro: 10
    if t.logradouro: score += 4
    else: missing.append("logradouro")
    if t.bairro: score += 3
    else: missing.append("bairro")
    if t.cep: score += 3
    else: missing.append("cep")
    
    # 6. e-mail/site: 10 (Transportadora nao tem site, email recebe 10)
    if t.email: score += 10
    else: missing.append("email")
    
    return score, missing

def calculate_embarcador_score(e):
    score = 0
    missing = []
    
    # 1. CNPJ/razão/cidade/UF: 20
    if e.cnpj: score += 5
    else: missing.append("cnpj")
    if e.razao_social or e.nome_fantasia: score += 5
    else: missing.append("razao_social/nome")
    if e.cidade: score += 5
    else: missing.append("cidade")
    if e.uf: score += 5
    else: missing.append("uf")
    
    # 2. CNAE/setor/tipo de carga/carroceria: 25
    if e.cnae: score += 7
    else: missing.append("cnae")
    if e.setor_predito: score += 6
    else: missing.append("setor_predito")
    if e.tipo_carga_provavel: score += 6
    else: missing.append("tipo_carga_provavel")
    if e.carrocerias_provaveis: score += 6
    else: missing.append("carrocerias_provaveis")
    
    # 3. telefone: 25
    if e.telefone: score += 25
    else: missing.append("telefone")
    
    # 4. sócios/QSA: 10
    if e.socios: score += 10
    else: missing.append("socios")
    
    # 5. endereço/site/email: 10
    if e.email: score += 5
    else: missing.append("email")
    if e.site: score += 5
    else: missing.append("site")
    
    # 6. prioridade/score_demanda/corredor: 10
    if e.prioridade: score += 3
    else: missing.append("prioridade")
    if e.score_demanda is not None: score += 4
    else: missing.append("score_demanda")
    if e.corredor_alvo: score += 3
    else: missing.append("corredor_alvo")
    
    return score, missing

def main():
    print("============================================================")
    print("AUDITORIA DE COMPLETUDE DE DADOS")
    print("============================================================")
    
    os.makedirs("exports/completude", exist_ok=True)
    
    with app.app_context():
        # 1. Transportadoras
        print("  Auditando Transportadoras...")
        t_fields = [
            "cnpj", "razao_social", "nome_fantasia", "nome_rntrc", "municipio",
            "uf", "corredor_alvo", "telefone", "email", "socios", "cnae_principal",
            "cnaes_secundarios", "tem_cnae_frete", "porte", "capital_social",
            "situacao_rf", "numero_rntrc", "logradouro", "bairro", "cep",
            "data_abertura", "status_crm", "notas", "origem_provavel", "destino_provavel"
        ]
        t_total = 0
        t_counts = {f: 0 for f in t_fields}
        t_scores = []
        t_incompletas = []
        
        # Obter transportadoras dos matches ou geral?
        # Para ser justo, vamos auditar todas as transportadoras da base.
        all_trans = Transportadora.query.all()
        t_total = len(all_trans)
        for t in all_trans:
            score, missing = calculate_transportadora_score(t)
            t_scores.append(score)
            
            # Atualizar completude na tabela, se necessário (vamos atualizar em modo real)
            t.score_completude = score
            db.session.add(t)
            
            if score < 100:
                t_incompletas.append({
                    "id": t.id,
                    "cnpj": t.cnpj,
                    "nome": t.razao_social or t.nome_rntrc or t.nome_fantasia or "",
                    "score_completude": score,
                    "campos_faltantes": ", ".join(missing)
                })
                
            for f in t_fields:
                val = getattr(t, f, None)
                if val is not None and str(val).strip() != "":
                    t_counts[f] += 1
                    
        # 2. Embarcadores
        print("  Auditando Embarcadores...")
        e_fields = [
            "cnpj", "razao_social", "nome_fantasia", "cidade", "uf", "cnae",
            "cnae_descricao", "setor_predito", "tipo_carga_provavel", "carrocerias_provaveis",
            "corredor_alvo", "origem_provavel", "destino_provavel", "score_demanda",
            "prioridade", "fonte", "telefone", "email", "site", "status_crm", "notas"
        ]
        e_total = 0
        e_counts = {f: 0 for f in e_fields}
        e_scores = []
        e_incompletas = []
        
        all_embs = EmbarcadorProvavel.query.all()
        e_total = len(all_embs)
        for e in all_embs:
            score, missing = calculate_embarcador_score(e)
            e_scores.append(score)
            
            e.score_completude = score
            db.session.add(e)
            
            if score < 100:
                e_incompletas.append({
                    "id": e.id,
                    "cnpj": e.cnpj,
                    "nome": e.razao_social or e.nome_fantasia or "",
                    "score_completude": score,
                    "campos_faltantes": ", ".join(missing)
                })
                
            for f in e_fields:
                val = getattr(e, f, None)
                if val is not None and str(val).strip() != "":
                    e_counts[f] += 1

        db.session.commit() # Salva scores no banco

        # 3. Matches
        print("  Auditando Matches...")
        m_fields = [
            "total", "corredor", "score_match", "status", "prioridade", "temperatura",
            "cidade_origem", "uf_origem", "cidade_destino", "uf_destino", "tipo_carga",
            "carroceria", "contato_transportadora", "contato_embarcador", "dados_minimos_completos"
        ]
        m_total = 0
        m_counts = {f: 0 for f in m_fields if f != "total"}
        m_incompletos = []
        
        all_matches = MatchPreditivo.query.all()
        m_total = len(all_matches)
        
        for m in all_matches:
            t = m.transportadora
            e = m.embarcador
            
            m_counts["corredor"] += 1
            if m.score_match is not None: m_counts["score_match"] += 1
            if m.status: m_counts["status"] += 1
            if m.prioridade: m_counts["prioridade"] += 1
            if m.temperatura: m_counts["temperatura"] += 1
            if m.cidade_origem: m_counts["cidade_origem"] += 1
            if m.uf_origem: m_counts["uf_origem"] += 1
            if m.cidade_destino: m_counts["cidade_destino"] += 1
            if m.uf_destino: m_counts["uf_destino"] += 1
            
            # Carga e carroceria
            tipo_carga = e.tipo_carga_provavel if e else None
            carroceria = e.carrocerias_provaveis if e else None
            if tipo_carga: m_counts["tipo_carga"] += 1
            if carroceria: m_counts["carroceria"] += 1
            
            # Contato
            has_t_contact = bool(t and (t.telefone or t.email or t.socios))
            has_e_contact = bool(e and (e.telefone or e.email or e.site))
            if has_t_contact: m_counts["contato_transportadora"] += 1
            if has_e_contact: m_counts["contato_embarcador"] += 1
            
            # Dados mínimos
            if has_t_contact and has_e_contact:
                m_counts["dados_minimos_completos"] += 1
                is_complete = True
            else:
                is_complete = False
                
            if not is_complete:
                m_incompletos.append({
                    "match_id": m.id,
                    "corredor": m.corredor,
                    "score_match": m.score_match,
                    "transportadora_cnpj": t.cnpj if t else "",
                    "transportadora_nome": t.razao_social if t else "",
                    "has_transportadora_contato": "Sim" if has_t_contact else "Não",
                    "embarcador_cnpj": e.cnpj if e else "",
                    "embarcador_nome": e.razao_social if e else "",
                    "has_embarcador_contato": "Sim" if has_e_contact else "Não"
                })

        # Salvar Relatórios de Completude
        # Transportadoras
        with open("exports/completude/completude_transportadoras.csv", "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["campo", "preenchidos", "vazios", "percentual"])
            for field in t_fields:
                pre = t_counts[field]
                vaz = t_total - pre
                pct = (pre / t_total * 100) if t_total > 0 else 0
                writer.writerow([field, pre, vaz, f"{pct:.2f}%"])
                
        # Embarcadores
        with open("exports/completude/completude_embarcadores.csv", "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["campo", "preenchidos", "vazios", "percentual"])
            for field in e_fields:
                pre = e_counts[field]
                vaz = e_total - pre
                pct = (pre / e_total * 100) if e_total > 0 else 0
                writer.writerow([field, pre, vaz, f"{pct:.2f}%"])
                
        # Matches
        with open("exports/completude/completude_matches.csv", "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["campo", "preenchidos", "vazios", "percentual"])
            for field, pre in m_counts.items():
                vaz = m_total - pre
                pct = (pre / m_total * 100) if m_total > 0 else 0
                writer.writerow([field, pre, vaz, f"{pct:.2f}%"])
                
        # Salvar Filas de Dados Incompletos
        with open("exports/completude/transportadoras_dados_incompletos.csv", "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["id", "cnpj", "nome", "score_completude", "campos_faltantes"], delimiter=";")
            writer.writeheader()
            writer.writerows(t_incompletas)
            
        with open("exports/completude/embarcadores_dados_incompletos.csv", "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["id", "cnpj", "nome", "score_completude", "campos_faltantes"], delimiter=";")
            writer.writeheader()
            writer.writerows(e_incompletas)
            
        with open("exports/completude/matches_dados_incompletos.csv", "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["match_id", "corredor", "score_match", "transportadora_cnpj", "transportadora_nome", "has_transportadora_contato", "embarcador_cnpj", "embarcador_nome", "has_embarcador_contato"], delimiter=";")
            writer.writeheader()
            writer.writerows(m_incompletos)

        # Salvar Relatório de Score de todas as empresas
        with open("exports/completude/score_completude_empresas.csv", "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["tipo_empresa", "id", "cnpj", "nome", "score_completude"])
            for t in all_trans:
                writer.writerow([
                    "transportadora", t.id, t.cnpj, 
                    t.razao_social or t.nome_rntrc or t.nome_fantasia or "",
                    t.score_completude or 0
                ])
            for e in all_embs:
                writer.writerow([
                    "embarcador", e.id, e.cnpj, 
                    e.razao_social or e.nome_fantasia or "",
                    e.score_completude or 0
                ])

        # Relatório de Console
        t_avg = sum(t_scores) / t_total if t_total > 0 else 0
        e_avg = sum(e_scores) / e_total if e_total > 0 else 0
        m_complete_pct = (m_counts["dados_minimos_completos"] / m_total * 100) if m_total > 0 else 0
        
        print("\n=========================================")
        print("RESUMO DA COMPLETUDE DE DADOS:")
        print(f"Transportadoras Totais:     {t_total:,}")
        print(f"  Score Médio Completude:   {t_avg:.2f}%")
        print(f"  Incompletas (< 100%):     {len(t_incompletas):,}")
        print(f"Embarcadores Totais:        {e_total:,}")
        print(f"  Score Médio Completude:   {e_avg:.2f}%")
        print(f"  Incompletas (< 100%):     {len(e_incompletas):,}")
        print(f"Matches Totais:             {m_total:,}")
        print(f"  Com Dados Mínimos (2 Lados): {m_counts['dados_minimos_completos']:,} ({m_complete_pct:.2f}%)")
        print(f"  Incompletos:               {len(m_incompletos):,}")
        print("=========================================")

if __name__ == "__main__":
    main()
