#!/usr/bin/env python3
import os
import sys
import csv
import math
from datetime import datetime

# Add root folder to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import Transportadora, EmbarcadorProvavel, MatchPreditivo

def haversine(lat1, lon1, lat2, lon2):
    # Radius of the earth in km
    R = 6371.0
    
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance = R * c
    return distance

def normalize_str(s):
    import unicodedata
    if not s:
        return ""
    s = s.strip().lower()
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Calcula o score geográfico dos matches.")
    parser.add_argument("--dry-run", action="store_true", help="Simulação sem gravar no banco de dados")
    args = parser.parse_args()
    
    print("============================================================")
    if args.dry_run:
        print("SIMULAÇÃO DE CÁLCULO DE SCORE GEOGRÁFICO (DRY-RUN)")
    else:
        print("CÁLCULO DE SCORE GEOGRÁFICO DE MATCHES COMPLETO")
    print("============================================================")
    
    os.makedirs("exports/geografia", exist_ok=True)
    output_path = "exports/geografia/score_geografico_matches.csv"
    
    rows = []
    
    calc_count = 0
    insuficiente_count = 0
    total_distance = 0.0
    corredor_distances = {}
    corredor_counts = {}
    
    db_updates = 0
    
    with app.app_context():
        all_matches = MatchPreditivo.query.all()
        print(f"  Processando {len(all_matches):,} matches...")
        
        for m in all_matches:
            t = m.transportadora
            e = m.embarcador
            
            if not t or not e:
                insuficiente_count += 1
                continue
                
            t_lat, t_lon = t.latitude, t.longitude
            e_lat, e_lon = e.latitude, e.longitude
            
            # Verificar se temos coordenadas dos dois lados
            if t_lat is None or t_lon is None or e_lat is None or e_lon is None:
                insuficiente_count += 1
                
                # Preencher com NULL se gravação ativa
                if not args.dry_run:
                    m.distancia_km = None
                    m.score_geografico = None
                    m.precisao_geografica_match = "insuficiente"
                    m.score_match_v2 = m.score_match
                    db.session.add(m)
                    db_updates += 1
                continue
                
            # Calcular distância real via Haversine
            dist = haversine(t_lat, t_lon, e_lat, e_lon)
            
            # Determinar a precisão geográfica do match
            t_prec = t.precisao_geocodificacao or "cidade"
            e_prec = e.precisao_geocodificacao or "cidade"
            
            if t_prec == "endereco" and e_prec == "endereco":
                prec_match = "endereco"
            elif t_prec in ("endereco", "cep") and e_prec in ("endereco", "cep"):
                prec_match = "cep"
            else:
                prec_match = "cidade"
                
            # Calcular score geográfico inicial baseado em distância
            if dist <= 10.0:
                score_geo = 100.0
            elif dist <= 30.0:
                score_geo = 90.0
            elif dist <= 75.0:
                score_geo = 75.0
            elif dist <= 150.0:
                score_geo = 55.0
            elif dist <= 300.0:
                score_geo = 30.0
            else:
                score_geo = 10.0
                
            # Bônus por mesmo município
            is_same_city = False
            if t.municipio and e.cidade and normalize_str(t.municipio) == normalize_str(e.cidade) and t.uf == e.uf:
                is_same_city = True
                score_geo = min(100.0, score_geo + 10.0)
                
            # Restrições de precisão (Capping)
            # Se a geocodificação for de nível cidade (centroid), o score máximo é limitado a 70
            if prec_match == "cidade":
                score_geo = min(70.0, score_geo)
                
            # Calcular score_match_v2
            # Fórmula: 70% score_match + 25% score_geografico + 5% score_completude (média)
            t_comp = t.score_completude or 0
            e_comp = e.score_completude or 0
            avg_comp = (t_comp + e_comp) / 2.0
            
            score_v2 = 0.70 * m.score_match + 0.25 * score_geo + 0.05 * avg_comp
            
            # Acumular estatísticas
            calc_count += 1
            total_distance += dist
            
            corr = m.corredor or "Indefinido"
            corredor_distances[corr] = corredor_distances.get(corr, 0.0) + dist
            corredor_counts[corr] = corredor_counts.get(corr, 0) + 1
            
            # Adicionar na lista de saída do CSV
            rows.append({
                "match_id": m.id,
                "corredor": m.corredor or "",
                "transportadora_nome": t.razao_social or t.nome_rntrc or t.nome_fantasia or "",
                "embarcador_nome": e.razao_social or e.nome_fantasia or "",
                "score_match_atual": m.score_match,
                "score_geografico": round(score_geo, 2),
                "score_match_v2": round(score_v2, 2),
                "distancia_km": round(dist, 2),
                "precisao_geografica_match": prec_match
            })
            
            # Gravar no banco de dados se não for dry-run
            if not args.dry_run:
                m.distancia_km = dist
                m.score_geografico = score_geo
                m.precisao_geografica_match = prec_match
                m.score_match_v2 = score_v2
                db.session.add(m)
                db_updates += 1
                
        # Commit e backup se modificado
        if not args.dry_run and db_updates > 0:
            print("  Criando backup do banco de dados...")
            try:
                from scripts.backup_db import run_backup
                run_backup()
            except Exception as ex:
                print(f"  [Aviso] Falha ao criar backup: {ex}")
                
            db.session.commit()
            
    # Salvar CSV
    fields = [
        "match_id", "corredor", "transportadora_nome", "embarcador_nome", 
        "score_match_atual", "score_geografico", "score_match_v2", 
        "distancia_km", "precisao_geografica_match"
    ]
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
        
    # Análise de impacto e console
    avg_dist = (total_distance / calc_count) if calc_count > 0 else 0.0
    
    # Ordenar por score_v2 desc para ver os top 100
    sorted_v2 = sorted(rows, key=lambda x: x["score_match_v2"], reverse=True)
    
    # matches onde score atual é alto (ex: >= 80) mas score geográfico é ruim (ex: <= 30)
    conflitos = [r for r in rows if r["score_match_atual"] >= 80.0 and r["score_geografico"] <= 30.0]
    
    print("\n=========================================")
    print("ESTATÍSTICAS DO SCORE GEOGRÁFICO:")
    print(f"  Matches com score calculado:          {calc_count:,}")
    print(f"  Matches sem coordenadas suficientes:  {insuficiente_count:,}")
    print(f"  Distância média geral:                {avg_dist:.2f} km")
    
    print("\nDistância média por corredor:")
    for corr in corredor_distances:
        c_count = corredor_counts[corr]
        c_avg = corredor_distances[corr] / c_count if c_count > 0 else 0.0
        print(f"  * {corr}: {c_avg:.2f} km (base: {c_count:,} matches)")
        
    print(f"\nMatches com score atual alto (>=80) mas geografia ruim (<=30): {len(conflitos):,}")
    print(f"Resultados detalhados salvos em: {output_path}")
    print("=========================================")

if __name__ == "__main__":
    main()
