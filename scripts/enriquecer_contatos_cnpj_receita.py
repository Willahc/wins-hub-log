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
    parser = argparse.ArgumentParser(description="Enriquecimento de contatos por CNPJ usando dados públicos.")
    parser.add_argument("--input", required=True, help="Caminho do CSV de entrada")
    parser.add_argument("--dry-run", action="store_true", help="Se ativado, não faz alterações no banco ou backups")
    parser.add_argument("--limit", type=int, default=20, help="Limite de CNPJs a consultar")
    parser.add_argument("--sleep", type=float, default=1.0, help="Tempo de espera entre requisições externas")
    parser.add_argument("--tipo", choices=["transportadora", "embarcador", "ambos"], default="ambos", help="Tipo de empresa para filtrar")
    parser.add_argument("--only-empty", action="store_true", help="Enriquecer apenas empresas sem contatos")
    parser.add_argument("--output", required=True, help="Caminho do CSV de saída com resultados")
    parser.add_argument("--resume", action="store_true", help="Retoma o enriquecimento a partir do arquivo de saída")
    
    args = parser.parse_args()
    
    csv_path = args.input
    dry_run = args.dry_run
    limit = args.limit
    sleep_time = args.sleep
    tipo = args.tipo
    only_empty = args.only_empty
    output_path = args.output
    resume = args.resume
    
    if not os.path.exists(csv_path):
        print(f"Erro: Arquivo CSV de entrada '{csv_path}' nao encontrado.")
        sys.exit(1)
        
    print("============================================================")
    if dry_run:
        print("SIMULAÇÃO DE ENRIQUECIMENTO DE CONTATOS POR CNPJ (DRY-RUN)")
    else:
        print("ENRIQUECIMENTO DE CONTATOS POR CNPJ (RECEITA/DADOS PÚBLICOS)")
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
            print(f"    [Aviso] Erro ao carregar cache local: {e}. Prosseguindo sem cache...")
    else:
        print("    [Aviso] Nenhum cache local encontrado. Criando novo cache...")
        
    # 2. Ler todas as linhas do CSV de entrada
    print(f"  Lendo arquivo de entrada: {csv_path}")
    all_rows = []
    orig_fields = []
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
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
    for col in ["telefone_encontrado", "email_encontrado", "socios_encontrados", "endereco_encontrado", "fonte_enriquecimento", "status_enriquecimento", "observacao"]:
        if col not in fieldnames:
            fieldnames.append(col)
            
    # Inicializar novas colunas em todas as linhas
    for r in all_rows:
        for col in ["telefone_encontrado", "email_encontrado", "socios_encontrados", "endereco_encontrado", "fonte_enriquecimento", "status_enriquecimento", "observacao"]:
            if col not in r:
                r[col] = ""
        if not r.get("status_enriquecimento"):
            r["status_enriquecimento"] = "Ignorado"
            
    # 3. Carregar progresso anterior se resume for ativo
    resume_count = 0
    if resume and os.path.exists(output_path):
        print(f"  Modo Resume: Restaurando progresso de {output_path}...")
        try:
            prev_rows = {}
            with open(output_path, "r", encoding="utf-8-sig") as f_res:
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
            
            # Atualizar all_rows com os dados preenchidos anteriormente
            for r in all_rows:
                emp_id = r.get("id", "").strip()
                if emp_id in prev_rows:
                    prev_r = prev_rows[emp_id]
                    status_enr = prev_r.get("status_enriquecimento", "").strip()
                    if status_enr != "Ignorado" and status_enr != "":
                        for col in ["telefone_encontrado", "email_encontrado", "socios_encontrados", "endereco_encontrado", "fonte_enriquecimento", "status_enriquecimento", "observacao"]:
                            r[col] = prev_r.get(col, "")
                        resume_count += 1
            print(f"    {resume_count} registros restaurados. Serão pulados nesta execução.")
        except Exception as e:
            print(f"    [Aviso] Falha ao ler arquivo de resume: {e}. Prosseguindo sem resume...")
            
    # Estatísticas
    lines_read = 0
    cnpjs_queried = 0
    cnpjs_found = 0
    cnpjs_not_found = 0
    phones_found = 0
    emails_found = 0
    socios_found = 0
    t_updated = 0
    e_updated = 0
    fields_skipped_existing = 0
    
    with app.app_context():
        try:
            for r in all_rows:
                lines_read += 1
                
                if lines_read % 100 == 0:
                    print(f"  Progresso: {lines_read} linhas processadas, {cnpjs_queried} CNPJs consultados...")
                    
                # Se resume ativado e esta linha já foi processada com sucesso/erro, pula!
                if resume and r.get("status_enriquecimento") != "Ignorado" and r.get("status_enriquecimento") != "":
                    # Manter contadores de sucessos restaurados para o relatório final
                    st = r.get("status_enriquecimento")
                    if st == "Sucesso":
                        cnpjs_found += 1
                        if r.get("telefone_encontrado"): phones_found += 1
                        if r.get("email_encontrado"): emails_found += 1
                        if r.get("socios_encontrados"): socios_found += 1
                    elif st == "Não Encontrado":
                        cnpjs_not_found += 1
                    continue
                    
                tipo_emp = r.get("tipo_empresa", "").strip().lower()
                emp_id_str = r.get("id", "").strip()
                cnpj_raw = r.get("cnpj", "").strip()
                cnpj = "".join(filter(str.isdigit, cnpj_raw))
                
                # Filtros de Processamento
                tipo_match = False
                if tipo == "ambos":
                    tipo_match = True
                elif tipo == "transportadora" and tipo_emp == "transportadora":
                    tipo_match = True
                elif tipo == "embarcador" and tipo_emp == "embarcador":
                    tipo_match = True
                    
                has_contact = bool(r.get("telefone", "").strip() or 
                                   r.get("email", "").strip() or 
                                   r.get("site", "").strip() or 
                                   r.get("socios", "").strip())
                
                should_process = tipo_match
                if only_empty and has_contact:
                    should_process = False
                    r["observacao"] = "Ignorado: Empresa ja possui contatos no CSV"
                    
                if should_process and cnpjs_queried >= limit:
                    should_process = False
                    r["observacao"] = "Ignorado: Limite atingido"
                    
                if should_process and not cnpj:
                    should_process = False
                    r["observacao"] = "Erro: CNPJ invalido/ausente"
                    
                if should_process:
                    cnpjs_queried += 1
                    
                    # Salvar CSV a cada 50 consultas
                    if cnpjs_queried > 0 and cnpjs_queried % 50 == 0:
                        salvar_csv(output_path, fieldnames, all_rows)
                        
                    # 1. Buscar no cache
                    cached_data = cache_dict.get(cnpj)
                    data_api = None
                    fonte = ""
                    
                    if cached_data and cached_data.get("status") == 200:
                        data_api = cached_data.get("dados")
                        fonte = "BrasilAPI Cache"
                    else:
                        # Buscar na API
                        if cnpjs_queried > 1 and sleep_time > 0:
                            time.sleep(sleep_time)
                            
                        print(f"  Consultando CNPJ {cnpj_raw} online...")
                        result = fetch_brasilapi(cnpj)
                        save_to_cache(result)
                        cache_dict[cnpj] = result
                        
                        if result.get("status") == 200:
                            data_api = result.get("dados")
                            fonte = "BrasilAPI"
                        elif result.get("status") == 429:
                            print(f"\n[AVISO] Limite de requisições atingido (HTTP 429). Parando enriquecimento e salvando resultados parciais...")
                            r["status_enriquecimento"] = "Erro"
                            r["observacao"] = "Erro API: Status 429 (Too Many Requests)"
                            
                            # Marcar todas as linhas seguintes como interrompidas por 429
                            idx_current = all_rows.index(r)
                            for rem_r in all_rows[idx_current + 1:]:
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
                        r["fonte_enriquecimento"] = fonte
                        r["status_enriquecimento"] = "Sucesso"
                        
                        # Extrair e formatar dados
                        ddd_t1 = data_api.get("ddd_telefone_1", "").strip()
                        ddd_t2 = data_api.get("ddd_telefone_2", "").strip()
                        raw_phone = ddd_t1 if ddd_t1 else ddd_t2
                        tel_enc = format_phone(raw_phone)
                        r["telefone_encontrado"] = tel_enc
                        if tel_enc:
                            phones_found += 1
                            
                        email_enc = data_api.get("email", "").strip().lower() if data_api.get("email") else ""
                        r["email_encontrado"] = email_enc
                        if email_enc:
                            emails_found += 1
                            
                        qsa = data_api.get("qsa", [])
                        socios_list = [s.get("nome_socio", "").strip() for s in qsa if s.get("nome_socio")]
                        soc_enc = ", ".join(socios_list)
                        r["socios_encontrados"] = soc_enc
                        if soc_enc:
                            socios_found += 1
                            
                        logradouro = data_api.get("logradouro", "").strip()
                        numero = data_api.get("numero", "").strip()
                        complemento = data_api.get("complemento", "").strip()
                        bairro = data_api.get("bairro", "").strip()
                        cep = data_api.get("cep", "").strip()
                        municipio = data_api.get("municipio", "").strip()
                        uf = data_api.get("uf", "").strip()
                        
                        addr_parts = []
                        if logradouro:
                            if numero:
                                addr_parts.append(f"{logradouro}, {numero}")
                            else:
                                addr_parts.append(logradouro)
                        if complemento:
                            addr_parts.append(complemento)
                        if bairro:
                            addr_parts.append(bairro)
                        if municipio and uf:
                            addr_parts.append(f"{municipio}/{uf}")
                        if cep:
                            addr_parts.append(f"CEP {cep}")
                        r["endereco_encontrado"] = " - ".join(addr_parts)
                        
                        # Atualizar banco de dados se não for dry-run
                        if not dry_run:
                            emp_id = None
                            if emp_id_str:
                                try:
                                    emp_id = int(emp_id_str)
                                except ValueError:
                                    pass
                                    
                            is_updated = False
                            
                            if tipo_emp == "transportadora":
                                t = None
                                if emp_id:
                                    t = db.session.get(Transportadora, emp_id)
                                if not t and cnpj:
                                    t = Transportadora.query.filter_by(cnpj=cnpj).first()
                                    
                                if t:
                                    if tel_enc:
                                        if not t.telefone:
                                            t.telefone = tel_enc
                                            is_updated = True
                                        elif t.telefone != tel_enc:
                                            fields_skipped_existing += 1
                                    if email_enc:
                                        if not t.email:
                                            t.email = email_enc
                                            is_updated = True
                                        elif t.email != email_enc:
                                            fields_skipped_existing += 1
                                    if soc_enc:
                                        if not t.socios:
                                            t.socios = soc_enc
                                            is_updated = True
                                        elif t.socios != soc_enc:
                                            fields_skipped_existing += 1
                                            
                                    if is_updated:
                                        t_updated += 1
                                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                                        note_block = f"\n[Contato Receita/CNPJ importado em {timestamp}] fonte: {fonte} | observacao: Enriquecimento automatico de contatos"
                                        t.notas = (t.notas or "") + note_block
                                        db.session.add(t)
                                        
                            elif tipo_emp == "embarcador":
                                e = None
                                if emp_id:
                                    e = db.session.get(EmbarcadorProvavel, emp_id)
                                if not e and cnpj:
                                    e = EmbarcadorProvavel.query.filter_by(cnpj=cnpj).first()
                                    
                                if e:
                                    if tel_enc:
                                        if not e.telefone:
                                            e.telefone = tel_enc
                                            is_updated = True
                                        elif e.telefone != tel_enc:
                                            fields_skipped_existing += 1
                                    if email_enc:
                                        if not e.email:
                                            e.email = email_enc
                                            is_updated = True
                                        elif e.email != email_enc:
                                            fields_skipped_existing += 1
                                            
                                    if is_updated:
                                        e_updated += 1
                                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                                        note_block = f"\n[Contato Receita/CNPJ importado em {timestamp}] fonte: {fonte} | observacao: Enriquecimento automatico de contatos"
                                        e.notas = (e.notas or "") + note_block
                                        db.session.add(e)
                                        
            # 4. Salvar no arquivo de saída final
            salvar_csv(output_path, fieldnames, all_rows)
            
            # 5. Backup e Commit no banco
            if not dry_run and (t_updated > 0 or e_updated > 0):
                print("  Criando backup do banco de dados...")
                try:
                    from scripts.backup_db import run_backup
                    backup_file = run_backup()
                    if backup_file:
                        print(f"  Backup criado com sucesso em: {backup_file}")
                except Exception as ex:
                    print(f"  [Aviso] Erro ao criar backup: {ex}. Prosseguindo...")
                    
                db.session.commit()
                
        except Exception as err:
            db.session.rollback()
            print(f"\n[ERRO] Ocorreu um erro durante o processamento. Transação revertida: {err}")
            sys.exit(1)
            
    # Relatório final
    print("\n============================================================")
    print("RELATÓRIO DE ENRIQUECIMENTO:")
    print(f"  linhas lidas:                             {lines_read:,}")
    print(f"  CNPJs consultados:                        {cnpjs_queried:,}")
    print(f"  encontrados:                              {cnpjs_found:,}")
    print(f"  não encontrados:                          {cnpjs_not_found:,}")
    print(f"  telefones encontrados:                    {phones_found:,}")
    print(f"  emails encontrados:                      {emails_found:,}")
    print(f"  sócios encontrados:                       {socios_found:,}")
    print(f"  transportadoras atualizadas no banco:     {t_updated:,}")
    print(f"  embarcadores atualizadas no banco:       {e_updated:,}")
    print(f"  campos pulados por já existirem:          {fields_skipped_existing:,}")
    print("============================================================")
    print(f"Arquivo de saída gerado em: {output_path}")

if __name__ == "__main__":
    main()
