#!/usr/bin/env python3
import os
import sys
import csv
import json
import time
import argparse
import urllib.request
import urllib.error
from datetime import datetime

# Add root folder to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import Transportadora, EmbarcadorProvavel, MatchPreditivo

def fetch_brasilapi(cnpj):
    url = f"https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                return {
                    "cnpj": cnpj,
                    "status": 200,
                    "dados": data,
                    "consultado_em": datetime.now().isoformat()
                }
    except urllib.error.HTTPError as e:
        return {"cnpj": cnpj, "status": e.code, "dados": None}
    except Exception as e:
        return {"cnpj": cnpj, "status": 500, "dados": None}

def save_to_cache(data):
    cache_path = "instance/cache_brasilapi_cnpj.jsonl"
    try:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")
    except Exception as e:
        print(f"  [Aviso] Falha ao gravar no cache: {e}")

def salvar_csv(output_path, fieldnames, rows):
    try:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
            writer.writeheader()
            writer.writerows(rows)
    except Exception as e:
        print(f"  [Erro] Falha ao salvar CSV em {output_path}: {e}")

def main():
    parser = argparse.ArgumentParser(description="Enriquecimento de endereços via CNPJ.")
    parser.add_argument("--tipo", choices=["transportadora", "embarcador", "ambos"], default="ambos", help="Tipo de empresa para filtrar")
    parser.add_argument("--only-matches", action="store_true", help="Apenas empresas presentes em matches")
    parser.add_argument("--corredor", default=None, help="Filtrar matches por corredor")
    parser.add_argument("--input", default=None, help="Caminho do CSV opcional contendo CNPJs")
    parser.add_argument("--dry-run", action="store_true", help="Simulação sem alteração no banco")
    parser.add_argument("--limit", type=int, default=100, help="Limite de consultas online/novas")
    parser.add_argument("--resume", action="store_true", help="Retoma o enriquecimento a partir do arquivo de saída")
    parser.add_argument("--sleep", type=float, default=1.0, help="Espera entre consultas online")
    parser.add_argument("--only-empty", action="store_true", help="Atualiza apenas campos de endereço que estiverem vazios")
    parser.add_argument("--output", required=True, help="Caminho do CSV de saída")
    
    args = parser.parse_args()
    
    print("============================================================")
    if args.dry_run:
        print("SIMULAÇÃO DE ENRIQUECIMENTO DE ENDEREÇOS (DRY-RUN)")
    else:
        print("ENRIQUECIMENTO GEOGRÁFICO DE ENDEREÇOS COMPLETO (CNPJ)")
    print("============================================================")
    
    # 1. Carregar cache local
    print("  Carregando cache local do CNPJ...")
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
            print(f"    Cache carregado ({len(cache_dict):,} registros).")
        except Exception as e:
            print(f"    [Aviso] Falha ao ler cache: {e}")
            
    # 2. Obter lista de alvos a processar
    targets = []
    
    with app.app_context():
        if args.input:
            print(f"  Lendo alvos do arquivo de entrada: {args.input}")
            try:
                with open(args.input, "r", encoding="utf-8-sig") as f:
                    sample = f.read(2048)
                    f.seek(0)
                    delimiter = ";"
                    if sample and "," in sample and (sample.count(",") > sample.count(";")):
                        delimiter = ","
                    reader = csv.DictReader(f, delimiter=delimiter)
                    for r in reader:
                        cnpj_raw = r.get("cnpj", "").strip()
                        if cnpj_raw:
                            targets.append({
                                "tipo_empresa": r.get("tipo_empresa", "").strip().lower() or "embarcador",
                                "id": r.get("id", "").strip(),
                                "cnpj": cnpj_raw,
                                "nome": r.get("nome", "").strip() or r.get("razao_social", "").strip() or ""
                            })
            except Exception as e:
                print(f"Erro ao ler CSV de entrada: {e}")
                sys.exit(1)
        else:
            print("  Buscando alvos no banco de dados...")
            # Determinar quais IDs de transportadoras/embarcadores estão em matches
            t_ids = set()
            e_ids = set()
            if args.only_matches:
                mq = MatchPreditivo.query
                if args.corredor:
                    mq = mq.filter_by(corredor=args.corredor)
                for m in mq.all():
                    t_ids.add(m.transportadora_id)
                    e_ids.add(m.embarcador_id)
                print(f"    Filtro matches ativo: {len(t_ids)} transportadoras e {len(e_ids)} embarcadores associados.")
                
            # Buscar Transportadoras
            if args.tipo in ("transportadora", "ambos"):
                t_query = Transportadora.query
                if args.only_matches:
                    t_query = t_query.filter(Transportadora.id.in_(t_ids))
                for t in t_query.all():
                    targets.append({
                        "tipo_empresa": "transportadora",
                        "id": str(t.id),
                        "cnpj": t.cnpj,
                        "nome": t.razao_social or t.nome_rntrc or t.nome_fantasia or ""
                    })
                    
            # Buscar Embarcadores
            if args.tipo in ("embarcador", "ambos"):
                e_query = EmbarcadorProvavel.query
                if args.only_matches:
                    e_query = e_query.filter(EmbarcadorProvavel.id.in_(e_ids))
                for e in e_query.all():
                    targets.append({
                        "tipo_empresa": "embarcador",
                        "id": str(e.id),
                        "cnpj": e.cnpj,
                        "nome": e.razao_social or e.nome_fantasia or ""
                    })
                    
        print(f"  Total de alvos identificados: {len(targets):,}")
        
        # 3. Configurar colunas de saída
        fieldnames = [
            "id", "tipo_empresa", "cnpj", "nome", "cep_encontrado", 
            "logradouro_encontrado", "bairro_encontrado", "municipio_encontrado", 
            "uf_encontrado", "status_enriquecimento", "observacao", "fonte"
        ]
        
        # Inicializar linhas de saída
        out_rows = []
        for t in targets:
            out_rows.append({col: "" for col in fieldnames})
            out_rows[-1]["id"] = t["id"]
            out_rows[-1]["tipo_empresa"] = t["tipo_empresa"]
            out_rows[-1]["cnpj"] = t["cnpj"]
            out_rows[-1]["nome"] = t["nome"]
            out_rows[-1]["status_enriquecimento"] = "Pendente"
            
        # Resume
        resume_dict = {}
        if args.resume and os.path.exists(args.output):
            print(f"  Modo Resume: Carregando progresso de {args.output}...")
            try:
                with open(args.output, "r", encoding="utf-8-sig") as f_res:
                    reader_res = csv.DictReader(f_res, delimiter=";")
                    for r_res in reader_res:
                        res_id = r_res.get("id", "").strip()
                        res_tipo = r_res.get("tipo_empresa", "").strip()
                        if res_id and res_tipo:
                            resume_dict[(res_id, res_tipo)] = r_res
                
                # Restaurar no out_rows
                for row in out_rows:
                    key = (row["id"], row["tipo_empresa"])
                    if key in resume_dict:
                        res_row = resume_dict[key]
                        status = res_row.get("status_enriquecimento", "").strip()
                        if status != "Pendente" and status != "":
                            for col in fieldnames:
                                row[col] = res_row.get(col, "")
                print(f"    Progresso de {len(resume_dict):,} registros carregado.")
            except Exception as e:
                print(f"    [Aviso] Falha no resume: {e}")
                
        # 4. Loop de Processamento
        cnpjs_queried = 0
        cnpjs_found = 0
        cnpjs_not_found = 0
        db_updates = 0
        
        for idx, r in enumerate(out_rows):
            # Pular se já processado em resume
            if args.resume and r.get("status_enriquecimento") != "Pendente" and r.get("status_enriquecimento") != "":
                if r.get("status_enriquecimento") == "Sucesso":
                    cnpjs_found += 1
                elif r.get("status_enriquecimento") == "Não Encontrado":
                    cnpjs_not_found += 1
                continue
                
            cnpj_raw = r["cnpj"]
            cnpj = "".join(filter(str.isdigit, cnpj_raw))
            tipo_emp = r["tipo_empresa"]
            emp_id = int(r["id"])
            
            # Verificar se já tem endereço completo no banco se --only-empty estiver ativo
            skip = False
            if args.only_empty:
                if tipo_emp == "transportadora":
                    t_db = Transportadora.query.get(emp_id)
                    if t_db and t_db.cep and t_db.logradouro and t_db.bairro:
                        skip = True
                        r["status_enriquecimento"] = "Pulado"
                        r["observacao"] = "Já possui dados de endereço completos no banco"
                elif tipo_emp == "embarcador":
                    e_db = EmbarcadorProvavel.query.get(emp_id)
                    if e_db and e_db.cep and e_db.logradouro and e_db.bairro:
                        skip = True
                        r["status_enriquecimento"] = "Pulado"
                        r["observacao"] = "Já possui dados de endereço completos no banco"
            if skip:
                continue
                
            # Limite
            if cnpjs_queried >= args.limit:
                r["status_enriquecimento"] = "Pendente"
                r["observacao"] = "Limite de consultas atingido"
                continue
                
            cnpjs_queried += 1
            
            # Salvar parciais
            if cnpjs_queried > 0 and cnpjs_queried % 50 == 0:
                salvar_csv(args.output, fieldnames, out_rows)
                
            cached_data = cache_dict.get(cnpj)
            data_api = None
            fonte = ""
            
            if cached_data and cached_data.get("status") == 200:
                data_api = cached_data.get("dados")
                fonte = "BrasilAPI Cache"
            else:
                if cnpjs_queried > 1 and args.sleep > 0:
                    time.sleep(args.sleep)
                    
                print(f"  Consultando CNPJ {cnpj_raw} ({tipo_emp}) online...")
                result = fetch_brasilapi(cnpj)
                save_to_cache(result)
                cache_dict[cnpj] = result
                
                if result.get("status") == 200:
                    data_api = result.get("dados")
                    fonte = "BrasilAPI"
                elif result.get("status") == 429:
                    print(f"\n[AVISO] HTTP 429 (Too Many Requests). Salvando parciais e parando seguro...")
                    r["status_enriquecimento"] = "Erro"
                    r["observacao"] = "Erro API: Status 429"
                    
                    # Marcar seguintes como pendentes/interrompidos
                    for rem_r in out_rows[idx + 1:]:
                        if rem_r.get("status_enriquecimento") == "Pendente":
                            rem_r["status_enriquecimento"] = "Pendente"
                            rem_r["observacao"] = "Interrompido por HTTP 429"
                    break
                else:
                    r["status_enriquecimento"] = "Não Encontrado"
                    r["observacao"] = f"Erro API: Status {result.get('status')}"
                    cnpjs_not_found += 1
                    
            if data_api:
                cnpjs_found += 1
                r["status_enriquecimento"] = "Sucesso"
                r["fonte"] = fonte
                
                # Extrair campos
                cep = (data_api.get("cep") or "").strip()
                logradouro = (data_api.get("logradouro") or "").strip()
                bairro = (data_api.get("bairro") or "").strip()
                numero = (data_api.get("numero") or "").strip()
                complemento = (data_api.get("complemento") or "").strip()
                municipio = (data_api.get("municipio") or "").strip()
                uf = (data_api.get("uf") or "").strip()
                
                situacao = (data_api.get("descricao_situacao_cadastral") or "").strip()
                data_abertura = (data_api.get("data_inicio_atividade") or "").strip()
                
                r["cep_encontrado"] = cep
                r["logradouro_encontrado"] = logradouro
                r["bairro_encontrado"] = bairro
                r["municipio_encontrado"] = municipio
                r["uf_encontrado"] = uf
                
                # Montar endereço normalizado
                addr_parts = []
                if logradouro:
                    if numero: addr_parts.append(f"{logradouro}, {numero}")
                    else: addr_parts.append(logradouro)
                if complemento: addr_parts.append(complemento)
                if bairro: addr_parts.append(bairro)
                if municipio and uf: addr_parts.append(f"{municipio}/{uf}")
                if cep: addr_parts.append(f"CEP {cep}")
                endereco_completo = " - ".join(addr_parts)
                
                # Escrever no banco de dados se não for dry-run
                if not args.dry_run:
                    timestamp_now = datetime.now().strftime("%Y-%m-%d %H:%M")
                    is_updated = False
                    
                    if tipo_emp == "transportadora":
                        t_db = Transportadora.query.get(emp_id)
                        if t_db:
                            def update_field(field_name, new_val):
                                nonlocal is_updated
                                if not new_val: return
                                curr = getattr(t_db, field_name, None)
                                if not curr or (not args.only_empty and curr != new_val):
                                    setattr(t_db, field_name, new_val)
                                    is_updated = True
                                    
                            update_field("cep", cep)
                            update_field("logradouro", logradouro)
                            update_field("bairro", bairro)
                            update_field("municipio", municipio)
                            update_field("uf", uf)
                            update_field("situacao_rf", situacao)
                            update_field("data_abertura", data_abertura)
                            
                            if is_updated:
                                t_db.endereco_completo = endereco_completo
                                t_db.data_enriquecimento_contato = timestamp_now
                                t_db.fonte_contato = fonte
                                t_db.notas = (t_db.notas or "") + f"\n[Endereço enriquecido em {timestamp_now}] fonte: {fonte}"
                                db.session.add(t_db)
                                db_updates += 1
                                
                    elif tipo_emp == "embarcador":
                        e_db = EmbarcadorProvavel.query.get(emp_id)
                        if e_db:
                            def update_field(field_name, new_val):
                                nonlocal is_updated
                                if not new_val: return
                                curr = getattr(e_db, field_name, None)
                                if not curr or (not args.only_empty and curr != new_val):
                                    setattr(e_db, field_name, new_val)
                                    is_updated = True
                                    
                            update_field("cep", cep)
                            update_field("logradouro", logradouro)
                            update_field("bairro", bairro)
                            update_field("cidade", municipio)
                            update_field("uf", uf)
                            update_field("situacao_rf", situacao)
                            
                            if is_updated:
                                e_db.endereco_completo = endereco_completo
                                e_db.data_enriquecimento_contato = timestamp_now
                                e_db.fonte_contato = fonte
                                e_db.notas = (e_db.notas or "") + f"\n[Endereço enriquecido em {timestamp_now}] fonte: {fonte}"
                                db.session.add(e_db)
                                db_updates += 1
                                
        # Salvar final
        salvar_csv(args.output, fieldnames, out_rows)
        
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
    print("RELATÓRIO DE ENRIQUECIMENTO DE ENDEREÇOS:")
    print(f"  Total consultados:                    {cnpjs_queried:,}")
    print(f"  Encontrados:                          {cnpjs_found:,}")
    print(f"  Não encontrados:                      {cnpjs_not_found:,}")
    print(f"  Registros atualizados no banco:       {db_updates:,}")
    print(f"CSV salvo em: {args.output}")
    print("=========================================")

if __name__ == "__main__":
    main()
