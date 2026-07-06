#!/usr/bin/env python3
import os
import sys
import csv

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
    print("GERANDO FILA DE EMPRESAS SEM CONTATO NOS MATCHES")
    print("============================================================")
    
    with app.app_context():
        all_matches = MatchPreditivo.query.all()
        total_matches = len(all_matches)
        
        # Filtrar matches sem contato nenhum
        matches_sem_contato = []
        for m in all_matches:
            if not transp_has_contact(m.transportadora) and not emb_has_contact(m.embarcador):
                matches_sem_contato.append(m)
                
        total_sem_contato = len(matches_sem_contato)
        
        # Agrupar transportadoras
        transp_dict = {}
        # Agrupar embarcadores
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
                
        # Construir linhas das transportadoras
        t_rows = []
        for t_id, data in transp_dict.items():
            t = data["t"]
            bm = data["best_match"]
            t_rows.append({
                "tipo_empresa": "transportadora",
                "id": str(t.id),
                "cnpj": t.cnpj,
                "nome": t.razao_social or t.nome_rntrc or "—",
                "telefone": "",
                "email": "",
                "site": "",
                "socios": "",
                "score_match_max": float(data["max_score"]),
                "qtd_matches_afetados": int(len(data["matches"])),
                "prioridade": bm.prioridade if bm else "",
                "corredor": bm.corredor if bm else "",
                "fonte_contato": "",
                "observacao_contato": ""
            })
            
        # Ordenar transportadoras
        t_rows.sort(key=lambda x: (
            -x["qtd_matches_afetados"],
            -x["score_match_max"],
            x["corredor"]
        ))
        
        # Construir linhas dos embarcadores
        e_rows = []
        for e_id, data in emb_dict.items():
            e = data["e"]
            bm = data["best_match"]
            e_rows.append({
                "tipo_empresa": "embarcador",
                "id": str(e.id),
                "cnpj": e.cnpj,
                "nome": e.razao_social or e.nome_fantasia or "—",
                "telefone": "",
                "email": "",
                "site": "",
                "socios": "",
                "score_match_max": float(data["max_score"]),
                "qtd_matches_afetados": int(len(data["matches"])),
                "prioridade": bm.prioridade if bm else "",
                "corredor": bm.corredor if bm else "",
                "fonte_contato": "",
                "observacao_contato": ""
            })
            
        # Ordenar embarcadores
        e_rows.sort(key=lambda x: (
            -x["qtd_matches_afetados"],
            -x["score_match_max"],
            0 if x["prioridade"] == "Alta" else 1,
            x["corredor"]
        ))
        
        # União das duas filas
        # transportadoras primeiro, depois embarcadores
        all_rows = t_rows + e_rows
        
        # Salvar arquivos CSV
        out_dir = "exports/contatos"
        os.makedirs(out_dir, exist_ok=True)
        
        cols = [
            "tipo_empresa", "id", "cnpj", "nome", "telefone", "email", "site",
            "socios", "score_match_max", "qtd_matches_afetados", "prioridade",
            "corredor", "fonte_contato", "observacao_contato"
        ]
        
        t_path = os.path.join(out_dir, "fila_transportadoras_sem_contato_matches.csv")
        with open(t_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=cols, delimiter=";")
            writer.writeheader()
            writer.writerows(t_rows)
            
        e_path = os.path.join(out_dir, "fila_embarcadores_sem_contato_matches.csv")
        with open(e_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=cols, delimiter=";")
            writer.writeheader()
            writer.writerows(e_rows)
            
        all_path = os.path.join(out_dir, "fila_empresas_sem_contato_matches.csv")
        with open(all_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=cols, delimiter=";")
            writer.writeheader()
            writer.writerows(all_rows)
            
        # Relatório Terminal
        print(f"Matches Sem Contato Nenhum:                 {total_sem_contato:,} (de {total_matches:,} total)")
        print(f"Transportadoras Únicas Sem Contato na Fila: {len(t_rows):,}")
        print(f"Embarcadores Únicos Sem Contato na Fila:    {len(e_rows):,}")
        
        print("\n=== TOP 20 EMPRESAS QUE MAIS DESTRAVAM MATCHES ===")
        # Unir as duas filas e ordenar de forma unificada por matches afetados
        top_destrava = sorted(all_rows, key=lambda x: -x["qtd_matches_afetados"])
        for idx, row in enumerate(top_destrava[:20], 1):
            print(f"{idx:2d}. [{row['tipo_empresa'].upper()}] ID {row['id']} - CNPJ: {row['cnpj']} - {row['nome'][:40]:40} | Destrava {row['qtd_matches_afetados']:3d} matches (Max Score: {row['score_match_max']})")
        print("============================================================")

if __name__ == "__main__":
    main()
