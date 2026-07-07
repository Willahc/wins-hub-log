#!/usr/bin/env python3
import os
import sys
import csv
import time
import json
import argparse
import requests
from datetime import datetime

# Add root folder to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import Transportadora, EmbarcadorProvavel, MatchPreditivo
from scripts.normalizar_telefones import normalize_phone_number

def has_phone(emp):
    if not emp:
        return False
    return bool((emp.telefone and emp.telefone.strip()) or (emp.telefone_normalizado and emp.telefone_normalizado.strip()))

def save_to_cache(data):
    cache_path = "instance/cache_brasilapi_cnpj.jsonl"
    try:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"  [Aviso] Falha ao gravar no cache: {e}")

def fetch_brasilapi(cnpj):
    url = f"https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
    try:
        response = requests.get(url, timeout=15)
        status_code = response.status_code
        if status_code == 200:
            return {"cnpj": cnpj, "status": 200, "dados": response.json(), "timestamp": datetime.now().isoformat()}
        elif status_code == 429:
            print("  [Erro] Rate limit (HTTP 429) atingido na BrasilAPI.")
            return {"cnpj": cnpj, "status": 429, "timestamp": datetime.now().isoformat()}
        else:
            return {"cnpj": cnpj, "status": status_code, "timestamp": datetime.now().isoformat()}
    except Exception as e:
        print(f"  [Erro] Falha na requisição para CNPJ {cnpj}: {e}")
        return {"cnpj": cnpj, "status": 500, "error": str(e), "timestamp": datetime.now().isoformat()}

def main():
    parser = argparse.ArgumentParser(description="Enriquece telefones faltantes em matches.")
    parser.add_argument("--tipo", choices=["transportadora", "embarcador", "ambos"], default="ambos")
    parser.add_argument("--corredor", help="Filtrar por corredor específico")
    parser.add_argument("--only-matches", action="store_true", default=True, help="Apenas empresas em matches")
    parser.add_argument("--prioridade-sem-telefone-nenhum", action="store_true", help="Priorizar matches sem nenhum telefone dos dois lados")
    parser.add_argument("--min-score", type=float, help="Filtrar por score_match mínimo")
    parser.add_argument("--dry-run", action="store_true", help="Simulação sem gravar no banco de dados")
    parser.add_argument("--limit", type=int, default=500, help="Limite máximo de consultas externas")
    parser.add_argument("--sleep", type=float, default=0.5, help="Tempo de espera entre consultas online")
    parser.add_argument("--resume", action="store_true", help="Continuar de onde parou")
    parser.add_argument("--only-empty", action="store_true", default=True, help="Apenas empresas sem telefone")
    parser.add_argument("--output", default="exports/telefones/resultado_enriquecimento_telefones.csv")
    args = parser.parse_args()
    
    print("============================================================")
    if args.dry_run:
        print("SIMULAÇÃO DE ENRIQUECIMENTO DE TELEFONES (DRY-RUN)")
    else:
        print("ENRIQUECIMENTO DE TELEFONES REAL")
    print("============================================================")
    
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    
    # 1. Carregar cache local
    print("  Carregando cache local do CNPJ...")
    cache_dict = {}
    cache_path = "instance/cache_brasilapi_cnpj.jsonl"
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        cnpj = data.get("cnpj", "").replace(".", "").replace("/", "").replace("-", "").strip()
                        if cnpj:
                            cache_dict[cnpj] = data
            print(f"    Cache carregado ({len(cache_dict):,} registros).")
        except Exception as e:
            print(f"    [Aviso] Falha ao ler cache: {e}")
            
    # 2. Obter e filtrar matches
    with app.app_context():
        print("  Buscando matches no banco de dados...")
        query = MatchPreditivo.query
        if args.corredor:
            query = query.filter_by(corredor=args.corredor)
        if args.min_score:
            query = query.filter(MatchPreditivo.score_match >= args.min_score)
            
        matches = query.all()
        print(f"    Total de matches elegíveis: {len(matches):,}")
        
        # 3. Classificar prioridade de matches
        matches_priorizados = []
        for m in matches:
            t = m.transportadora
            e = m.embarcador
            
            t_tel = has_phone(t)
            e_tel = has_phone(e)
            
            # Determinar prioridade
            prio = 3 # Padrão: um lado tem, outro não
            
            if not t_tel and not e_tel:
                prio = 1 # Sem telefone nenhum
            elif (not t_tel or not e_tel) and m.score_match >= 90.0:
                prio = 2 # Score alto e sem telefone em um lado
                
            matches_priorizados.append((prio, m))
            
        if args.prioridade_sem_telefone_nenhum or True: # Se true ou padrão
            # Ordenar por prioridade (1, depois 2, depois 3) e depois por score_match desc
            matches_priorizados.sort(key=lambda x: (x[0], -x[1].score_match))
            
        # 4. Coletar CNPJs únicos das empresas que precisam de telefone
        cnpjs_para_enriquecer = [] # list of tuples: (cnpj_clean, tipo_emp, emp_id, prioridade)
        seen_cnpjs = set()
        
        for prio, m in matches_priorizados:
            t = m.transportadora
            e = m.embarcador
            
            # Transportadora
            if t and (args.tipo in ("transportadora", "ambos")):
                t_cnpj_clean = t.cnpj.replace(".", "").replace("/", "").replace("-", "").strip()
                if not has_phone(t) and t_cnpj_clean not in seen_cnpjs:
                    seen_cnpjs.add(t_cnpj_clean)
                    cnpjs_para_enriquecer.append((t_cnpj_clean, "transportadora", t.id, prio))
                    
            # Embarcador
            if e and (args.tipo in ("embarcador", "ambos")):
                e_cnpj_clean = e.cnpj.replace(".", "").replace("/", "").replace("-", "").strip()
                if not has_phone(e) and e_cnpj_clean not in seen_cnpjs:
                    seen_cnpjs.add(e_cnpj_clean)
                    cnpjs_para_enriquecer.append((e_cnpj_clean, "embarcador", e.id, prio))
                    
        print(f"  Empresas únicas sem telefone identificadas: {len(cnpjs_para_enriquecer):,}")
        
        # 5. Processamento das empresas
        out_rows = []
        cnpjs_queried = 0
        cnpjs_found = 0
        cnpjs_not_found = 0
        db_updates = 0
        
        limit = args.limit
        
        for idx, (cnpj, tipo_emp, emp_id, prio) in enumerate(cnpjs_para_enriquecer):
            if cnpjs_queried >= limit:
                print(f"  [Info] Limite de {limit} consultas atingido. Interrompendo lote.")
                break
                
            # Verificar se já tem cadastro populado por outra thread (segurança)
            if tipo_emp == "transportadora":
                emp_db = Transportadora.query.get(emp_id)
            else:
                emp_db = EmbarcadorProvavel.query.get(emp_id)
                
            if emp_db and has_phone(emp_db):
                # Pulando se já populado
                continue
                
            # Buscar no cache ou API online
            cached_data = cache_dict.get(cnpj)
            data_api = None
            fonte = ""
            
            if cached_data and cached_data.get("status") == 200:
                data_api = cached_data.get("dados")
                fonte = "Cache local (BrasilAPI)"
            else:
                # Consultar online
                print(f"  [{idx+1}/{len(cnpjs_para_enriquecer)}] Consultando CNPJ {cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]} ({tipo_emp}) online...")
                result = fetch_brasilapi(cnpj)
                cnpjs_queried += 1
                
                # Salvar no cache
                save_to_cache(result)
                cache_dict[cnpj] = result
                
                if result.get("status") == 200:
                    data_api = result.get("dados")
                    fonte = "BrasilAPI Online"
                    cnpjs_found += 1
                elif result.get("status") == 429:
                    print("  [Aviso] Interrompendo lote devido a Rate Limit 429.")
                    break
                else:
                    cnpjs_not_found += 1
                    
                time.sleep(args.sleep)
                
            # Extrair telefone do resultado
            tel_enc = ""
            if data_api:
                ddd_t1 = data_api.get("ddd_telefone_1", "").strip()
                ddd_t2 = data_api.get("ddd_telefone_2", "").strip()
                raw_phone = ddd_t1 if ddd_t1 else ddd_t2
                # Limpar caracteres
                tel_enc = "".join(filter(str.isdigit, raw_phone))
                
            # Se encontrou telefone
            if tel_enc:
                # Normalizar
                norm, ddd, tipo, whatsapp = normalize_phone_number(tel_enc)
                
                out_rows.append({
                    "cnpj": cnpj,
                    "tipo_empresa": tipo_emp,
                    "nome": emp_db.razao_social if emp_db else "",
                    "telefone_original": tel_enc,
                    "telefone_normalizado": norm or "",
                    "ddd": ddd or "",
                    "tipo_telefone": tipo,
                    "whatsapp_possivel": "Sim" if whatsapp else "Não",
                    "fonte": fonte,
                    "status": "Encontrado"
                })
                
                # Gravar no banco de dados se não for dry-run
                if not args.dry_run and emp_db:
                    timestamp_now = datetime.now().strftime("%Y-%m-%d %H:%M")
                    
                    emp_db.telefone = tel_enc
                    emp_db.telefone_normalizado = norm
                    emp_db.ddd = ddd
                    emp_db.tipo_telefone = tipo
                    emp_db.whatsapp_possivel = whatsapp
                    
                    emp_db.data_enriquecimento_contato = timestamp_now
                    emp_db.fonte_contato = fonte
                    emp_db.notas = (emp_db.notas or "") + f"\n[Telefone enriquecido em {timestamp_now}] fonte: {fonte}"
                    
                    db.session.add(emp_db)
                    db_updates += 1
            else:
                out_rows.append({
                    "cnpj": cnpj,
                    "tipo_empresa": tipo_emp,
                    "nome": emp_db.razao_social if emp_db else "",
                    "telefone_original": "",
                    "telefone_normalizado": "",
                    "ddd": "",
                    "tipo_telefone": "",
                    "whatsapp_possivel": "Não",
                    "fonte": fonte or "Não Encontrado no Cache/API",
                    "status": "Não Encontrado"
                })
                
        # Salvar CSV final
        csv_fields = ["cnpj", "tipo_empresa", "nome", "telefone_original", "telefone_normalizado", "ddd", "tipo_telefone", "whatsapp_possivel", "fonte", "status"]
        with open(args.output, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=csv_fields, delimiter=";")
            w.writeheader()
            w.writerows(out_rows)
            
        # Commit e backup se modificado
        if not args.dry_run and db_updates > 0:
            print("  Criando backup do banco de dados...")
            try:
                from scripts.backup_db import run_backup
                run_backup()
            except Exception as ex:
                print(f"  [Aviso] Falha ao criar backup: {ex}")
                
            db.session.commit()
            
    print("\n=========================================")
    print("RELATÓRIO DE ENRIQUECIMENTO DE TELEFONES:")
    print(f"  Total consultados online:        {cnpjs_queried:,}")
    print(f"  Encontrados novos:               {cnpjs_found:,}")
    print(f"  Não encontrados:                 {cnpjs_not_found:,}")
    print(f"  Registros atualizados no banco:  {db_updates:,}")
    print(f"CSV salvo em: {args.output}")
    print("=========================================")

if __name__ == "__main__":
    main()
