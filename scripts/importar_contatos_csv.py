#!/usr/bin/env python3
import os
import sys
import csv
from datetime import datetime

# Add root folder to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import Transportadora, EmbarcadorProvavel

def main():
    dry_run = False
    args = sys.argv[1:]
    if "--dry-run" in args:
        dry_run = True
        args.remove("--dry-run")
        
    if len(args) < 1:
        print("Uso: python scripts/importar_contatos_csv.py [--dry-run] <caminho_do_csv>")
        sys.exit(1)
        
    csv_path = args[0]
    if not os.path.exists(csv_path):
        print(f"Erro: Arquivo CSV '{csv_path}' nao encontrado.")
        sys.exit(1)
        
    # 1. Pré-validar se o CSV possui pelo menos um contato preenchido no arquivo inteiro
    has_any_contact_in_file = False
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            sample = f.read(2048)
            f.seek(0)
            delimiter = ";"
            if sample:
                if "," in sample and (sample.count(",") > sample.count(";")):
                    delimiter = ","
            
            reader = csv.DictReader(f, delimiter=delimiter)
            for row in reader:
                telefone_csv = row.get("telefone", "").strip()
                email_csv = row.get("email", "").strip()
                site_csv = row.get("site", "").strip()
                socios_csv = row.get("socios", "").strip()
                if telefone_csv or email_csv or site_csv or socios_csv:
                    has_any_contact_in_file = True
                    break
    except Exception as e:
        print(f"Erro ao ler arquivo CSV para validação: {e}")
        sys.exit(1)
        
    if not has_any_contact_in_file and not dry_run:
        print("Nenhum contato preenchido encontrado. Importação cancelada antes do backup.")
        sys.exit(0)
        
    print("============================================================")
    if dry_run:
        print("SIMULAÇÃO DE IMPORTAÇÃO DE CONTATOS (DRY-RUN)")
    else:
        print("IMPORTAÇÃO E ENRIQUECIMENTO DE CONTATOS COMERCIAIS")
    print("============================================================")
    
    # 2. Executar backup se não for dry-run
    if not dry_run:
        print("  Criando backup do banco de dados...")
        try:
            from scripts.backup_db import run_backup
            backup_file = run_backup()
            if backup_file:
                print(f"  Backup criado com sucesso em: {backup_file}")
            else:
                print("  [Aviso] Falha ao criar backup quente. Prosseguindo...")
        except Exception as e:
            print(f"  [Aviso] Erro ao carregar script de backup: {e}. Prosseguindo...")
    else:
        print("  Modo Dry-Run: Nenhuma alteração será feita no banco ou backups.")
        
    # Variáveis de estatísticas
    lines_read = 0
    lines_with_contact = 0
    lines_without_contact = 0
    records_found = 0
    records_updated = 0
    
    phones_filled = 0
    emails_filled = 0
    sites_filled = 0
    socios_filled = 0
    lines_ignored_existing = 0
    lines_not_found = 0
    
    with app.app_context():
        try:
            # Ler o arquivo CSV
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                sample = f.read(2048)
                f.seek(0)
                delimiter = ";"
                if sample:
                    if "," in sample and (sample.count(",") > sample.count(";")):
                        delimiter = ","
                
                reader = csv.DictReader(f, delimiter=delimiter)
                
                # Validar colunas obrigatórias
                cols = reader.fieldnames or []
                required_cols = {"tipo_empresa", "id", "cnpj"}
                missing_cols = required_cols - set(cols)
                if missing_cols:
                    print(f"Erro: Colunas obrigatórias ausentes no CSV: {list(missing_cols)}")
                    sys.exit(1)
                
                for row in reader:
                    lines_read += 1
                    
                    tipo = row.get("tipo_empresa", "").strip().lower()
                    emp_id_str = row.get("id", "").strip()
                    cnpj = row.get("cnpj", "").strip()
                    
                    telefone_csv = row.get("telefone", "").strip()
                    email_csv = row.get("email", "").strip()
                    site_csv = row.get("site", "").strip()
                    socios_csv = row.get("socios", "").strip()
                    fonte_contato = row.get("fonte_contato", "").strip()
                    obs_contato = row.get("observacao_contato", "").strip()
                    
                    # 1. Verificar se esta linha possui contatos
                    has_contact_in_row = bool(telefone_csv or email_csv or site_csv or socios_csv)
                    if has_contact_in_row:
                        lines_with_contact += 1
                    else:
                        lines_without_contact += 1
                        continue
                        
                    emp_id = None
                    if emp_id_str:
                        try:
                            emp_id = int(emp_id_str)
                        except ValueError:
                            pass
                    
                    if tipo == "transportadora":
                        t = None
                        if emp_id:
                            t = db.session.get(Transportadora, emp_id)
                        if not t and cnpj:
                            t = Transportadora.query.filter_by(cnpj=cnpj).first()
                            
                        if t:
                            records_found += 1
                            is_modified = False
                            phones_filled_row = False
                            emails_filled_row = False
                            socios_filled_row = False
                            skipped_existing_row = False
                            
                            # Telefone
                            if telefone_csv:
                                if not t.telefone:
                                    phones_filled_row = True
                                    if not dry_run:
                                        t.telefone = telefone_csv
                                        is_modified = True
                                else:
                                    skipped_existing_row = True
                                    
                            # Email
                            if email_csv:
                                if not t.email:
                                    emails_filled_row = True
                                    if not dry_run:
                                        t.email = email_csv
                                        is_modified = True
                                else:
                                    skipped_existing_row = True
                                    
                            # Socios
                            if socios_csv:
                                if not t.socios:
                                    socios_filled_row = True
                                    if not dry_run:
                                        t.socios = socios_csv
                                        is_modified = True
                                else:
                                    skipped_existing_row = True
                                    
                            # Notas (Fonte/Obs)
                            info_notes = []
                            if fonte_contato:
                                info_notes.append(f"fonte_contato: {fonte_contato}")
                            if obs_contato:
                                info_notes.append(f"observacao: {obs_contato}")
                                
                            if info_notes and not dry_run:
                                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                                note_block = f"\n[Contato importado em {timestamp}] " + " | ".join(info_notes)
                                t.notas = (t.notas or "") + note_block
                                is_modified = True
                                
                            # Atualizar contadores
                            if phones_filled_row: phones_filled += 1
                            if emails_filled_row: emails_filled += 1
                            if socios_filled_row: socios_filled += 1
                            
                            if phones_filled_row or emails_filled_row or socios_filled_row:
                                records_updated += 1
                                if not dry_run:
                                    db.session.add(t)
                            elif info_notes and not dry_run:
                                records_updated += 1
                                db.session.add(t)
                            elif skipped_existing_row:
                                lines_ignored_existing += 1
                        else:
                            lines_not_found += 1
                            
                    elif tipo == "embarcador":
                        e = None
                        if emp_id:
                            e = db.session.get(EmbarcadorProvavel, emp_id)
                        if not e and cnpj:
                            e = EmbarcadorProvavel.query.filter_by(cnpj=cnpj).first()
                            
                        if e:
                            records_found += 1
                            is_modified = False
                            phones_filled_row = False
                            emails_filled_row = False
                            sites_filled_row = False
                            skipped_existing_row = False
                            
                            # Telefone
                            if telefone_csv:
                                if not e.telefone:
                                    phones_filled_row = True
                                    if not dry_run:
                                        e.telefone = telefone_csv
                                        is_modified = True
                                else:
                                    skipped_existing_row = True
                                    
                            # Email
                            if email_csv:
                                if not e.email:
                                    emails_filled_row = True
                                    if not dry_run:
                                        e.email = email_csv
                                        is_modified = True
                                else:
                                    skipped_existing_row = True
                                    
                            # Site
                            if site_csv:
                                if not e.site:
                                    sites_filled_row = True
                                    if not dry_run:
                                        e.site = site_csv
                                        is_modified = True
                                else:
                                    skipped_existing_row = True
                                    
                            # Notas (Fonte/Obs)
                            info_notes = []
                            if fonte_contato:
                                info_notes.append(f"fonte_contato: {fonte_contato}")
                            if obs_contato:
                                info_notes.append(f"observacao: {obs_contato}")
                                
                            if info_notes and not dry_run:
                                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                                note_block = f"\n[Contato importado em {timestamp}] " + " | ".join(info_notes)
                                e.notas = (e.notas or "") + note_block
                                is_modified = True
                                
                            # Atualizar contadores
                            if phones_filled_row: phones_filled += 1
                            if emails_filled_row: emails_filled += 1
                            if sites_filled_row: sites_filled += 1
                            
                            if phones_filled_row or emails_filled_row or sites_filled_row:
                                records_updated += 1
                                if not dry_run:
                                    db.session.add(e)
                            elif info_notes and not dry_run:
                                records_updated += 1
                                db.session.add(e)
                            elif skipped_existing_row:
                                lines_ignored_existing += 1
                        else:
                            lines_not_found += 1
                    else:
                        lines_not_found += 1
                
                # Executar commit se não for dry run
                if not dry_run:
                    db.session.commit()
                    
        except Exception as err:
            db.session.rollback()
            print(f"\n[ERRO] Ocorreu um erro durante a importação. A transação foi revertida (rollback): {err}")
            sys.exit(1)
            
        # Exibir relatório final
        if dry_run:
            print("RELATÓRIO DE SIMULAÇÃO (DRY-RUN):")
            print(f"  Linhas Lidas:                             {lines_read:,}")
            print(f"  Linhas com Algum Contato Preenchido:      {lines_with_contact:,}")
            print(f"  Linhas Sem Contato Preenchido:            {lines_without_contact:,}")
            print(f"  Registros Encontrados no Banco:           {records_found:,}")
            print(f"  Registros que Seriam Atualizados:         {records_updated:,}")
            print(f"  Telefones que seriam preenchidos:         {phones_filled:,}")
            print(f"  E-mails que seriam preenchidos:           {emails_filled:,}")
            print(f"  Sites que seriam preenchidos:             {sites_filled:,}")
            print(f"  Sócios que seriam preenchidos:            {socios_filled:,}")
            print(f"  Linhas ignoradas por contato já existente: {lines_ignored_existing:,}")
            print(f"  Linhas com CNPJ/ID não encontrado:        {lines_not_found:,}")
        else:
            print("IMPORTAÇÃO CONCLUÍDA COM SUCESSO!")
            print(f"  Linhas Lidas:                             {lines_read:,}")
            print(f"  Linhas com Algum Contato Preenchido:      {lines_with_contact:,}")
            print(f"  Linhas Sem Contato Preenchido:            {lines_without_contact:,}")
            print(f"  Registros Encontrados no Banco:           {records_found:,}")
            print(f"  Registros Atualizados:                    {records_updated:,}")
            print(f"  Telefones Preenchidos:                    {phones_filled:,}")
            print(f"  E-mails Preenchidos:                      {emails_filled:,}")
            print(f"  Sites Preenchidos:                        {sites_filled:,}")
            print(f"  Sócios Preenchidos:                       {socios_filled:,}")
            print(f"  Linhas ignoradas por contato já existente: {lines_ignored_existing:,}")
            print(f"  Linhas com CNPJ/ID não encontrado:        {lines_not_found:,}")
        print("============================================================")

if __name__ == "__main__":
    main()
