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
from models import Transportadora, EmbarcadorProvavel

def format_phone(val):
    if not val:
        return ""
    val = "".join(filter(str.isdigit, val))
    if len(val) == 10:
        return f"({val[:2]}) {val[2:6]}-{val[6:]}"
    elif len(val) == 11:
        return f"({val[:2]}) {val[2:7]}-{val[7:]}"
    return val

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
    parser = argparse.ArgumentParser(description="Enriquecimento de dados cadastrais por CNPJ usando dados públicos.")
    parser.add_argument("--input", required=True, help="Caminho do CSV de entrada")
    parser.add_argument("--dry-run", action="store_true", help="Se ativado, não faz alterações no banco ou backups")
    parser.add_argument("--limit", type=int, default=100, help="Limite de CNPJs a consultar")
    parser.add_argument("--sleep", type=float, default=1.0, help="Tempo de espera entre requisições externas")
    parser.add_argument("--tipo", choices=["transportadora", "embarcador", "ambos"], default="ambos", help="Tipo de empresa para filtrar")
    parser.add_argument("--corredor", default=None, help="Filtrar por corredor do CSV de entrada")
    parser.add_argument("--only-empty", action="store_true", help="Atualizar apenas campos vazios no banco")
    parser.add_argument("--output", required=True, help="Caminho do CSV de saída com resultados")
    parser.add_argument("--resume", action="store_true", help="Retoma o enriquecimento a partir do arquivo de saída")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.input):
        print(f"Erro: Arquivo CSV de entrada '{args.input}' nao encontrado.")
        sys.exit(1)
        
    print("============================================================")
    if args.dry_run:
        print("SIMULAÇÃO DE ENRIQUECIMENTO CADASTRAL (DRY-RUN)")
    else:
        print("ENRIQUECIMENTO CADASTRAL COMPLETO (CNPJ/BRASILAPI)")
    print("============================================================")
    
    # 1. Carregar cache local da BrasilAPI
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
            print(f"    Cache carregado com sucesso ({len(cache_dict):,} registros).")
        except Exception as e:
            print(f"    [Aviso] Erro ao carregar cache local: {e}")
    else:
        print("    [Aviso] Nenhum cache local encontrado.")
        
    # 2. Ler todas as linhas do CSV de entrada
    print(f"  Lendo arquivo de entrada: {args.input}")
    all_rows = []
    orig_fields = []
    try:
        with open(args.input, "r", encoding="utf-8-sig") as f:
            sample = f.read(2048)
            f.seek(0)
            delimiter = ";"
            if sample:
                if "," in sample and (sample.count(",") > sample.count(";")):
                    delimiter = ","
            
            reader = csv.DictReader(f, delimiter=delimiter)
            orig_fields = reader.fieldnames or []
            for row in reader:
                all_rows.append(dict(row))
    except Exception as e:
        print(f"Erro ao ler arquivo de entrada: {e}")
        sys.exit(1)
        
    # Configurar colunas de saída
    fieldnames = list(orig_fields)
    new_cols = [
        "razao_social_encontrada", "nome_fantasia_encontrado", "telefone_encontrado",
        "email_encontrado", "socios_encontrados", "porte_encontrado", "capital_social_encontrado",
        "situacao_rf_encontrada", "status_enriquecimento", "observacao", "fonte_enriquecimento"
    ]
    for col in new_cols:
        if col not in fieldnames:
            fieldnames.append(col)
            
    # Inicializar novas colunas
    for r in all_rows:
        for col in new_cols:
            if col not in r:
                r[col] = ""
        if not r.get("status_enriquecimento"):
            r["status_enriquecimento"] = "Ignorado"
            
    # 3. Resume
    resume_count = 0
    if args.resume and os.path.exists(args.output):
        print(f"  Modo Resume: Restaurando progresso de {args.output}...")
        try:
            prev_rows = {}
            with open(args.output, "r", encoding="utf-8-sig") as f_res:
                sample = f_res.read(2048)
                f_res.seek(0)
                delimiter = ";"
                if sample and "," in sample and (sample.count(",") > sample.count(";")):
                    delimiter = ","
                reader_res = csv.DictReader(f_res, delimiter=delimiter)
                for row_res in reader_res:
                    emp_id = row_res.get("id", "").strip()
                    if emp_id:
                        prev_rows[emp_id] = row_res
            
            for r in all_rows:
                emp_id = r.get("id", "").strip()
                if emp_id in prev_rows:
                    prev_r = prev_rows[emp_id]
                    status_enr = prev_r.get("status_enriquecimento", "").strip()
                    if status_enr != "Ignorado" and status_enr != "":
                        for col in new_cols:
                            r[col] = prev_r.get(col, "")
                        resume_count += 1
            print(f"    {resume_count} registros restaurados.")
        except Exception as e:
            print(f"    [Aviso] Falha ao ler arquivo de resume: {e}")
            
    # Estatísticas
    lines_read = 0
    cnpjs_queried = 0
    cnpjs_found = 0
    cnpjs_not_found = 0
    t_updated = 0
    e_updated = 0
    
    with app.app_context():
        try:
            for r in all_rows:
                lines_read += 1
                
                # Se resume e processado, pula
                if args.resume and r.get("status_enriquecimento") != "Ignorado" and r.get("status_enriquecimento") != "":
                    if r.get("status_enriquecimento") == "Sucesso":
                        cnpjs_found += 1
                    elif r.get("status_enriquecimento") == "Não Encontrado":
                        cnpjs_not_found += 1
                    continue
                    
                emp_id_str = r.get("id", "").strip()
                cnpj_raw = r.get("cnpj", "").strip()
                cnpj = "".join(filter(str.isdigit, cnpj_raw))
                
                # Descobrir tipo_empresa se não estiver no CSV (por exemplo, buscando no banco pelo id ou cnpj)
                # Ou assumir que está no campo `tipo_empresa`
                tipo_emp = r.get("tipo_empresa", "").strip().lower()
                if not tipo_emp:
                    # Tentar deduzir do arquivo de entrada ou tentar carregar
                    # Vamos tentar identificar se é transportadora ou embarcador buscando pelo id/cnpj
                    t_exists = Transportadora.query.filter_by(cnpj=cnpj_raw).first() if cnpj_raw else None
                    if t_exists:
                        tipo_emp = "transportadora"
                    else:
                        e_exists = EmbarcadorProvavel.query.filter_by(cnpj=cnpj_raw).first() if cnpj_raw else None
                        if e_exists:
                            tipo_emp = "embarcador"
                            
                # Filtros
                tipo_match = False
                if args.tipo == "ambos":
                    tipo_match = True
                elif args.tipo == "transportadora" and tipo_emp == "transportadora":
                    tipo_match = True
                elif args.tipo == "embarcador" and tipo_emp == "embarcador":
                    tipo_match = True
                    
                corredor_match = True
                if args.corredor:
                    corr_row = r.get("corredor", "").strip()
                    if corr_row != args.corredor:
                        corredor_match = False
                        
                should_process = tipo_match and corredor_match
                if should_process and cnpjs_queried >= args.limit:
                    should_process = False
                    r["observacao"] = "Ignorado: Limite de requisições atingido"
                    
                if should_process and not cnpj:
                    should_process = False
                    r["observacao"] = "Erro: CNPJ inválido/ausente"
                    
                if should_process:
                    cnpjs_queried += 1
                    
                    if cnpjs_queried > 0 and cnpjs_queried % 50 == 0:
                        salvar_csv(args.output, fieldnames, all_rows)
                        
                    cached_data = cache_dict.get(cnpj)
                    data_api = None
                    fonte = ""
                    
                    if cached_data and cached_data.get("status") == 200:
                        data_api = cached_data.get("dados")
                        fonte = "BrasilAPI Cache"
                    else:
                        if cnpjs_queried > 1 and args.sleep > 0:
                            time.sleep(args.sleep)
                            
                        print(f"  Consultando CNPJ {cnpj_raw} online...")
                        result = fetch_brasilapi(cnpj)
                        save_to_cache(result)
                        cache_dict[cnpj] = result
                        
                        if result.get("status") == 200:
                            data_api = result.get("dados")
                            fonte = "BrasilAPI"
                        elif result.get("status") == 429:
                            print(f"\n[AVISO] HTTP 429 (Too Many Requests). Parando e salvando parciais...")
                            r["status_enriquecimento"] = "Erro"
                            r["observacao"] = "Erro API: Status 429"
                            
                            # Marcar seguintes
                            idx = all_rows.index(r)
                            for rem_r in all_rows[idx + 1:]:
                                if rem_r.get("status_enriquecimento") == "Ignorado":
                                    rem_r["status_enriquecimento"] = "Ignorado"
                                    rem_r["observacao"] = "Ignorado: Interrompido por HTTP 429"
                            break
                        else:
                            r["status_enriquecimento"] = "Não Encontrado"
                            r["observacao"] = f"Erro API: Status {result.get('status')}"
                            cnpjs_not_found += 1
                            
                    if data_api:
                        cnpjs_found += 1
                        r["status_enriquecimento"] = "Sucesso"
                        r["fonte_enriquecimento"] = fonte
                        
                        # Extrair dados cadastrais
                        razao = (data_api.get("razao_social") or "").strip()
                        fantasia = (data_api.get("nome_fantasia") or "").strip()
                        ddd_t1 = (data_api.get("ddd_telefone_1") or "").strip()
                        ddd_t2 = (data_api.get("ddd_telefone_2") or "").strip()
                        tel_val = format_phone(ddd_t1 if ddd_t1 else ddd_t2)
                        email_val = (data_api.get("email") or "").strip().lower()
                        porte = (data_api.get("porte") or "").strip()
                        cap_social = float(data_api.get("capital_social") or 0)
                        situacao = (data_api.get("descricao_situacao_cadastral") or "").strip()
                        
                        qsa = data_api.get("qsa") or []
                        socios_list = [(s.get("nome_socio") or "").strip() for s in qsa if s and s.get("nome_socio")]
                        socios = ", ".join(socios_list)
                        
                        logradouro = (data_api.get("logradouro") or "").strip()
                        numero = (data_api.get("numero") or "").strip()
                        complemento = (data_api.get("complemento") or "").strip()
                        bairro = (data_api.get("bairro") or "").strip()
                        cep = (data_api.get("cep") or "").strip()
                        municipio = (data_api.get("municipio") or "").strip()
                        uf = (data_api.get("uf") or "").strip()
                        data_abertura = (data_api.get("data_inicio_atividade") or "").strip()
                        
                        # CNPJ secundários formatados
                        cnaes_sec_list = [f"{c.get('codigo')}" for c in (data_api.get("cnaes_secundarios") or []) if c and c.get("codigo")]
                        cnaes_secundarios = ", ".join(cnaes_sec_list)
                        cnae_principal = str(data_api.get("cnae_fiscal") or "")
                        
                        r["razao_social_encontrada"] = razao
                        r["nome_fantasia_encontrado"] = fantasia
                        r["telefone_encontrado"] = tel_val
                        r["email_encontrado"] = email_val
                        r["socios_encontrados"] = socios
                        r["porte_encontrado"] = porte
                        r["capital_social_encontrado"] = cap_social
                        r["situacao_rf_encontrada"] = situacao
                        
                        addr_parts = []
                        if logradouro:
                            if numero: addr_parts.append(f"{logradouro}, {numero}")
                            else: addr_parts.append(logradouro)
                        if complemento: addr_parts.append(complemento)
                        if bairro: addr_parts.append(bairro)
                        if municipio and uf: addr_parts.append(f"{municipio}/{uf}")
                        if cep: addr_parts.append(f"CEP {cep}")
                        endereco_completo = " - ".join(addr_parts)
                        
                        # Atualizar banco
                        if not args.dry_run:
                            emp_id = None
                            if emp_id_str:
                                try: emp_id = int(emp_id_str)
                                except ValueError: pass
                                
                            is_updated = False
                            timestamp_now = datetime.now().strftime("%Y-%m-%d %H:%M")
                            
                            if tipo_emp == "transportadora":
                                t = None
                                if emp_id: t = db.session.get(Transportadora, emp_id)
                                if not t and cnpj: t = Transportadora.query.filter_by(cnpj=cnpj).first()
                                
                                if t:
                                    # Auxiliar para check only-empty
                                    def update_field(field_name, new_val):
                                        nonlocal is_updated
                                        if not new_val: return
                                        curr = getattr(t, field_name, None)
                                        if not curr or (not args.only_empty and curr != new_val):
                                            setattr(t, field_name, new_val)
                                            is_updated = True
                                            
                                    update_field("razao_social", razao)
                                    update_field("nome_fantasia", fantasia)
                                    update_field("telefone", tel_val)
                                    update_field("email", email_val)
                                    update_field("socios", socios)
                                    update_field("cnae_principal", cnae_principal)
                                    update_field("cnaes_secundarios", cnaes_secundarios)
                                    update_field("porte", porte)
                                    update_field("capital_social", cap_social)
                                    update_field("situacao_rf", situacao)
                                    update_field("logradouro", logradouro)
                                    update_field("bairro", bairro)
                                    update_field("cep", cep)
                                    update_field("municipio", municipio)
                                    update_field("uf", uf)
                                    update_field("data_abertura", data_abertura)
                                    
                                    if is_updated:
                                        t.data_enriquecimento_contato = timestamp_now
                                        t.fonte_contato = fonte
                                        t.endereco_completo = endereco_completo
                                        
                                        note = f"\n[Dados Cadastrais enriquecidos em {timestamp_now}] fonte: {fonte}"
                                        t.notas = (t.notas or "") + note
                                        
                                        db.session.add(t)
                                        t_updated += 1
                                        
                            elif tipo_emp == "embarcador":
                                e = None
                                if emp_id: e = db.session.get(EmbarcadorProvavel, emp_id)
                                if not e and cnpj: e = EmbarcadorProvavel.query.filter_by(cnpj=cnpj).first()
                                
                                if e:
                                    def update_field(field_name, new_val):
                                        nonlocal is_updated
                                        if not new_val: return
                                        curr = getattr(e, field_name, None)
                                        if not curr or (not args.only_empty and curr != new_val):
                                            setattr(e, field_name, new_val)
                                            is_updated = True
                                            
                                    update_field("razao_social", razao)
                                    update_field("nome_fantasia", fantasia)
                                    update_field("telefone", tel_val)
                                    update_field("email", email_val)
                                    update_field("socios", socios)
                                    update_field("cnae", cnae_principal)
                                    update_field("cnae_descricao", data_api.get("cnae_fiscal_descricao", ""))
                                    update_field("porte", porte)
                                    update_field("capital_social", cap_social)
                                    update_field("situacao_rf", situacao)
                                    
                                    if is_updated:
                                        e.data_enriquecimento_contato = timestamp_now
                                        e.fonte_contato = fonte
                                        e.endereco_completo = endereco_completo
                                        
                                        note = f"\n[Dados Cadastrais enriquecidos em {timestamp_now}] fonte: {fonte}"
                                        e.notas = (e.notas or "") + note
                                        
                                        db.session.add(e)
                                        e_updated += 1
                                        
            # Salvar tudo no fim
            salvar_csv(args.output, fieldnames, all_rows)
            
            # Commit & backup
            if not args.dry_run and (t_updated > 0 or e_updated > 0):
                print("  Criando backup do banco de dados...")
                try:
                    from scripts.backup_db import run_backup
                    backup_file = run_backup()
                    if backup_file:
                        print(f"  Backup criado com sucesso em: {backup_file}")
                except Exception as ex:
                    print(f"  [Aviso] Erro ao criar backup: {ex}")
                    
                db.session.commit()
                
        except Exception as err:
            db.session.rollback()
            print(f"\n[ERRO] Ocorreu um erro no enriquecimento: {err}")
            sys.exit(1)
            
    print("\n============================================================")
    print("RELATÓRIO DE ENRIQUECIMENTO CADASTRAL:")
    print(f"  linhas lidas:                             {lines_read:,}")
    print(f"  CNPJs consultados:                        {cnpjs_queried:,}")
    print(f"  encontrados:                              {cnpjs_found:,}")
    print(f"  não encontrados:                          {cnpjs_not_found:,}")
    print(f"  transportadoras atualizadas no banco:     {t_updated:,}")
    print(f"  embarcadores atualizadas no banco:       {e_updated:,}")
    print("============================================================")
    print(f"Resultados salvos em: {args.output}")

if __name__ == "__main__":
    main()
