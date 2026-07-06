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
    if len(sys.argv) < 2:
        print("Uso: python scripts/importar_contatos_csv.py <caminho_do_csv>")
        sys.exit(1)
        
    csv_path = sys.argv[1]
    if not os.path.exists(csv_path):
        print(f"Erro: Arquivo CSV '{csv_path}' nao encontrado.")
        sys.exit(1)
        
    print("============================================================")
    print("IMPORTAÇÃO E ENRIQUECIMENTO DE CONTATOS COMERCIAIS")
    print("============================================================")
    
    # 1. Executar backup antes de alterar o banco
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
        
    lines_read = 0
    t_updated = 0
    e_updated = 0
    phones_filled = 0
    emails_filled = 0
    sites_filled = 0
    socios_filled = 0
    skipped_existing = 0
    
    with app.app_context():
        # Ler o arquivo CSV
        # Tenta detectar delimitador ';' ou ','
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            # Ler cabeçalho para ver delimitador
            sample = f.read(2048)
            f.seek(0)
            delimiter = ";"
            if sample:
                if "," in sample and (sample.count(",") > sample.count(";")):
                    delimiter = ","
            
            reader = csv.DictReader(f, delimiter=delimiter)
            
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
                
                emp_id = None
                if emp_id_str:
                    try:
                        emp_id = int(emp_id_str)
                    except ValueError:
                        pass
                
                if tipo == "transportadora":
                    # Buscar por ID ou CNPJ
                    t = None
                    if emp_id:
                        t = Transportadora.query.get(emp_id)
                    if not t and cnpj:
                        t = Transportadora.query.filter_by(cnpj=cnpj).first()
                        
                    if t:
                        is_modified = False
                        
                        # Telefone
                        if telefone_csv:
                            if not t.telefone:
                                t.telefone = telefone_csv
                                phones_filled += 1
                                is_modified = True
                            elif t.telefone != telefone_csv:
                                skipped_existing += 1
                                
                        # Email
                        if email_csv:
                            if not t.email:
                                t.email = email_csv
                                emails_filled += 1
                                is_modified = True
                            elif t.email != email_csv:
                                skipped_existing += 1
                                
                        # Socios
                        if socios_csv:
                            if not t.socios:
                                t.socios = socios_csv
                                socios_filled += 1
                                is_modified = True
                            elif t.socios != socios_csv:
                                skipped_existing += 1
                                
                        # Notas
                        info_notes = []
                        if fonte_contato:
                            info_notes.append(f"Fonte: {fonte_contato}")
                        if obs_contato:
                            info_notes.append(f"Obs: {obs_contato}")
                            
                        if info_notes:
                            timestamp = datetime.now().strftime("%d/%m/%Y %H:%M")
                            note_block = f"\n[Contato Enriquecido - {timestamp}]\n" + "\n".join(info_notes)
                            t.notas = (t.notas or "") + note_block
                            is_modified = True
                            
                        if is_modified:
                            t_updated += 1
                            db.session.add(t)
                            
                elif tipo == "embarcador":
                    # Buscar por ID ou CNPJ
                    e = None
                    if emp_id:
                        e = EmbarcadorProvavel.query.get(emp_id)
                    if not e and cnpj:
                        e = EmbarcadorProvavel.query.filter_by(cnpj=cnpj).first()
                        
                    if e:
                        is_modified = False
                        
                        # Telefone
                        if telefone_csv:
                            if not e.telefone:
                                e.telefone = telefone_csv
                                phones_filled += 1
                                is_modified = True
                            elif e.telefone != telefone_csv:
                                skipped_existing += 1
                                
                        # Email
                        if email_csv:
                            if not e.email:
                                e.email = email_csv
                                emails_filled += 1
                                is_modified = True
                            elif e.email != email_csv:
                                skipped_existing += 1
                                
                        # Site
                        if site_csv:
                            if not e.site:
                                e.site = site_csv
                                sites_filled += 1
                                is_modified = True
                            elif e.site != site_csv:
                                skipped_existing += 1
                                
                        # Notas
                        info_notes = []
                        if fonte_contato:
                            info_notes.append(f"Fonte: {fonte_contato}")
                        if obs_contato:
                            info_notes.append(f"Obs: {obs_contato}")
                            
                        if info_notes:
                            timestamp = datetime.now().strftime("%d/%m/%Y %H:%M")
                            note_block = f"\n[Contato Enriquecido - {timestamp}]\n" + "\n".join(info_notes)
                            e.notas = (e.notas or "") + note_block
                            is_modified = True
                            
                        if is_modified:
                            e_updated += 1
                            db.session.add(e)
                            
            db.session.commit()
            
        # Exibir relatório
        print(f"Linhas Lidas do CSV:        {lines_read:,}")
        print(f"Transportadoras Atualizadas: {t_updated:,}")
        print(f"Embarcadores Atualizados:   {e_updated:,}")
        print(f"Telefones Preenchidos:      {phones_filled:,}")
        print(f"E-mails Preenchidos:        {emails_filled:,}")
        print(f"Sites Preenchidos:          {sites_filled:,}")
        print(f"Sócios Preenchidos:         {socios_filled:,}")
        print(f"Pulados por Já Existirem:   {skipped_existing:,}")
        print("============================================================")

if __name__ == "__main__":
    main()
