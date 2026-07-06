#!/usr/bin/env python3
import os
import sys
import csv
import json

# Add root folder to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import MatchPreditivo, Transportadora, EmbarcadorProvavel

def transp_has_contact(t):
    return bool((t.telefone and t.telefone.strip()) or 
                (t.email and t.email.strip()) or 
                (t.socios and t.socios.strip()))

def emb_has_contact(e):
    return bool((e.telefone and e.telefone.strip()) or 
                (e.email and e.email.strip()) or 
                (e.site and e.site.strip()))

def main():
    print("============================================================")
    print("GERANDO RELATÓRIO DE PENDENTES IRREDUTÍVEIS")
    print("============================================================")
    
    cache_dict = {}
    cache_path = "instance/cache_brasilapi_cnpj.jsonl"
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        cnpj_clean = "".join(filter(str.isdigit, data.get("cnpj", "")))
                        if cnpj_clean:
                            cache_dict[cnpj_clean] = data
                    except Exception:
                        pass
        except Exception as e:
            print(f"Erro ao ler cache: {e}")
            
    with app.app_context():
        all_matches = MatchPreditivo.query.all()
        total_matches = len(all_matches)
        
        # Matches ainda sem contato nenhum
        matches_sem_contato = []
        for m in all_matches:
            if not transp_has_contact(m.transportadora) and not emb_has_contact(m.embarcador):
                matches_sem_contato.append(m)
                
        total_sem_contato = len(matches_sem_contato)
        
        # Transportadoras sem contato
        transp_dict = {}
        # Embarcadores sem contato
        emb_dict = {}
        
        for m in matches_sem_contato:
            t = m.transportadora
            if t.id not in transp_dict:
                transp_dict[t.id] = {
                    "t": t,
                    "matches": [],
                    "max_score": 0.0,
                    "best_match": None
                }
            transp_dict[t.id]["matches"].append(m)
            if m.score_match > transp_dict[t.id]["max_score"]:
                transp_dict[t.id]["max_score"] = m.score_match
                transp_dict[t.id]["best_match"] = m
                
            e = m.embarcador
            if e.id not in emb_dict:
                emb_dict[e.id] = {
                    "e": e,
                    "matches": [],
                    "max_score": 0.0,
                    "best_match": None
                }
            emb_dict[e.id]["matches"].append(m)
            if m.score_match > emb_dict[e.id]["max_score"]:
                emb_dict[e.id]["max_score"] = m.score_match
                emb_dict[e.id]["best_match"] = m
                
        # Construir registros de pendentes irredutíveis
        pend_rows = []
        
        # Processar transportadoras
        for t_id, data in transp_dict.items():
            t = data["t"]
            bm = data["best_match"]
            cnpj = "".join(filter(str.isdigit, t.cnpj or ""))
            
            cached = cache_dict.get(cnpj)
            tentativa = "Sim" if cached else "Não"
            status_rec = ""
            motivo = "Não consultado (limite/rate limit)"
            obs = ""
            
            if cached:
                status_rec = str(cached.get("status", ""))
                if cached.get("status") == 200:
                    motivo = "API de CNPJ retornou campos de contatos vazios"
                    obs = "CNPJ ativo na Receita Federal mas sem telefone/email"
                else:
                    motivo = f"Erro na consulta do CNPJ: Status {cached.get('status')}"
                    obs = cached.get("observacao", "Sem observações adicionais")
                    
            pend_rows.append({
                "tipo_empresa": "transportadora",
                "id": str(t.id),
                "cnpj": t.cnpj,
                "nome": t.razao_social or t.nome_rntrc or "—",
                "corredor": bm.corredor if bm else "",
                "qtd_matches_afetados": int(len(data["matches"])),
                "score_match_max": float(data["max_score"]),
                "motivo_pendente": motivo,
                "tentativa_receita": tentativa,
                "status_receita": status_rec,
                "observacao": obs
            })
            
        # Processar embarcadores
        for e_id, data in emb_dict.items():
            e = data["e"]
            bm = data["best_match"]
            cnpj = "".join(filter(str.isdigit, e.cnpj or ""))
            
            cached = cache_dict.get(cnpj)
            tentativa = "Sim" if cached else "Não"
            status_rec = ""
            motivo = "Não consultado (limite/rate limit)"
            obs = ""
            
            if cached:
                status_rec = str(cached.get("status", ""))
                if cached.get("status") == 200:
                    motivo = "API de CNPJ retornou campos de contatos vazios"
                    obs = "CNPJ ativo na Receita Federal mas sem telefone/email"
                else:
                    motivo = f"Erro na consulta do CNPJ: Status {cached.get('status')}"
                    obs = cached.get("observacao", "Sem observações adicionais")
                    
            pend_rows.append({
                "tipo_empresa": "embarcador",
                "id": str(e.id),
                "cnpj": e.cnpj,
                "nome": e.razao_social or e.nome_fantasia or "—",
                "corredor": bm.corredor if bm else "",
                "qtd_matches_afetados": int(len(data["matches"])),
                "score_match_max": float(data["max_score"]),
                "motivo_pendente": motivo,
                "tentativa_receita": tentativa,
                "status_receita": status_rec,
                "observacao": obs
            })
            
        # Ordenar por matches afetados desc, score max desc
        pend_rows.sort(key=lambda x: (
            -x["qtd_matches_afetados"],
            -x["score_match_max"],
            x["tipo_empresa"]
        ))
        
        # Salvar CSV
        out_path = "exports/contatos/pendentes_sem_contato_apos_receita.csv"
        cols = [
            "tipo_empresa", "id", "cnpj", "nome", "corredor", 
            "qtd_matches_afetados", "score_match_max", 
            "motivo_pendente", "tentativa_receita", "status_receita", "observacao"
        ]
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=cols, delimiter=";")
            writer.writeheader()
            writer.writerows(pend_rows)
            
        # Calcular taxas finais
        # Matches com contato acionável (pelo menos um contato na transportadora ou no embarcador)
        matches_acionaveis = total_matches - total_sem_contato
        pct_cobertura = (matches_acionaveis / total_matches) * 100 if total_matches > 0 else 0.0
        
        # Relatório Final
        print(f"Matches ainda sem contato:                   {total_sem_contato:,}")
        print(f"Transportadoras ainda sem contato nos matches:{len(transp_dict):,}")
        print(f"Embarcadores ainda sem contato nos matches:   {len(emb_dict):,}")
        print(f"Percentual de Cobertura Final de Matches:    {pct_cobertura:.2f}%")
        print(f"Percentual de Matches Acionáveis:            {pct_cobertura:.2f}%")
        print("============================================================")
        print(f"Relatório salvo em: {out_path}")

if __name__ == "__main__":
    main()
