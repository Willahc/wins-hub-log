#!/usr/bin/env python3
import os
import sys
import csv
import argparse
from datetime import datetime

# Add root folder to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import Transportadora, EmbarcadorProvavel, MatchPreditivo

def normalize_phone_number(phone_str):
    if not phone_str:
        return None, None, None, False
        
    # Limpar caracteres não numéricos
    digits = "".join(filter(str.isdigit, phone_str))
    
    # Tratar DDI de DDI brasileiro (55)
    if digits.startswith("55") and len(digits) in (12, 13):
        digits = digits[2:]
        
    if len(digits) == 11:
        # Formato Celular: DDD + 9 dígitos
        ddd = digits[:2]
        local = digits[2:]
        tipo = "celular"
        whatsapp = True
        formatted = f"({ddd}) {local[:5]}-{local[5:]}"
        return formatted, ddd, tipo, whatsapp
    elif len(digits) == 10:
        # Formato Fixo ou Celular antigo: DDD + 8 dígitos
        ddd = digits[:2]
        local = digits[2:]
        first_digit = local[0]
        # Se começar com 9 ou 8 (celulares antigos)
        if first_digit in ("9", "8", "7"):
            tipo = "celular"
            whatsapp = True
        else:
            tipo = "fixo"
            whatsapp = False
        formatted = f"({ddd}) {local[:4]}-{local[4:]}"
        return formatted, ddd, tipo, whatsapp
    
    return phone_str, None, "desconhecido", False

def main():
    parser = argparse.ArgumentParser(description="Normalizador de telefones.")
    parser.add_argument("--dry-run", action="store_true", help="Simulação sem gravar no banco de dados")
    parser.add_argument("--only-matches", action="store_true", help="Normalizar apenas empresas presentes em matches")
    args = parser.parse_args()
    
    print("============================================================")
    if args.dry_run:
        print("SIMULAÇÃO DE NORMALIZAÇÃO DE TELEFONES (DRY-RUN)")
    else:
        print("NORMALIZAÇÃO DE TELEFONES COMPLETA")
    print("============================================================")
    
    os.makedirs("exports/telefones", exist_ok=True)
    output_path = "exports/telefones/telefones_normalizados_matches.csv"
    
    fields = [
        "tipo_empresa", "id", "cnpj", "nome", "telefone_original", 
        "telefone_normalizado", "ddd", "tipo_telefone", "whatsapp_possivel"
    ]
    rows = []
    
    t_updated = 0
    e_updated = 0
    t_total_proc = 0
    e_total_proc = 0
    
    with app.app_context():
        # Obter IDs de empresas em matches se only-matches estiver ativo
        t_ids = None
        e_ids = None
        if args.only_matches:
            print("  Carregando empresas presentes em matches...")
            matches = MatchPreditivo.query.all()
            t_ids = set(m.transportadora_id for m in matches)
            e_ids = set(m.embarcador_id for m in matches)
            print(f"    Filtro ativo: {len(t_ids)} transportadoras e {len(e_ids)} embarcadores.")

        # 1. Transportadoras
        print("  Processando Transportadoras...")
        query_t = Transportadora.query
        if t_ids is not None:
            query_t = query_t.filter(Transportadora.id.in_(t_ids))
        
        all_trans = query_t.all()
        for t in all_trans:
            if not t.telefone:
                continue
                
            t_total_proc += 1
            orig = t.telefone
            norm, ddd, tipo, whatsapp = normalize_phone_number(orig)
            
            rows.append({
                "tipo_empresa": "transportadora",
                "id": t.id,
                "cnpj": t.cnpj,
                "nome": t.razao_social or t.nome_rntrc or t.nome_fantasia or "",
                "telefone_original": orig,
                "telefone_normalizado": norm or "",
                "ddd": ddd or "",
                "tipo_telefone": tipo or "desconhecido",
                "whatsapp_possivel": "Sim" if whatsapp else "Não"
            })
            
            is_modified = False
            # Gravar nas novas colunas se não for dry-run
            if not args.dry_run:
                if t.telefone_normalizado != norm:
                    t.telefone_normalizado = norm
                    is_modified = True
                if t.ddd != ddd:
                    t.ddd = ddd
                    is_modified = True
                if t.tipo_telefone != tipo:
                    t.tipo_telefone = tipo
                    is_modified = True
                if t.whatsapp_possivel != whatsapp:
                    t.whatsapp_possivel = whatsapp
                    is_modified = True
                    
                if is_modified:
                    db.session.add(t)
                    t_updated += 1
                    
        # 2. Embarcadores
        print("  Processando Embarcadores...")
        query_e = EmbarcadorProvavel.query
        if e_ids is not None:
            query_e = query_e.filter(EmbarcadorProvavel.id.in_(e_ids))
            
        all_embs = query_e.all()
        for e in all_embs:
            if not e.telefone:
                continue
                
            e_total_proc += 1
            orig = e.telefone
            norm, ddd, tipo, whatsapp = normalize_phone_number(orig)
            
            rows.append({
                "tipo_empresa": "embarcador",
                "id": e.id,
                "cnpj": e.cnpj,
                "nome": e.razao_social or e.nome_fantasia or "",
                "telefone_original": orig,
                "telefone_normalizado": norm or "",
                "ddd": ddd or "",
                "tipo_telefone": tipo or "desconhecido",
                "whatsapp_possivel": "Sim" if whatsapp else "Não"
            })
            
            is_modified = False
            if not args.dry_run:
                if e.telefone_normalizado != norm:
                    e.telefone_normalizado = norm
                    is_modified = True
                if e.ddd != ddd:
                    e.ddd = ddd
                    is_modified = True
                if e.tipo_telefone != tipo:
                    e.tipo_telefone = tipo
                    is_modified = True
                if e.whatsapp_possivel != whatsapp:
                    e.whatsapp_possivel = whatsapp
                    is_modified = True
                    
                if is_modified:
                    db.session.add(e)
                    e_updated += 1
                    
        # Commit e backup se modificado
        if not args.dry_run and (t_updated > 0 or e_updated > 0):
            print("  Criando backup do banco de dados...")
            try:
                from scripts.backup_db import run_backup
                run_backup()
            except Exception as ex:
                print(f"  [Aviso] Falha ao criar backup: {ex}")
                
            db.session.commit()
            
    # Salvar CSV
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
        
    # Relatório resumido
    celulares = sum(1 for r in rows if r["tipo_telefone"] == "celular")
    fixos = sum(1 for r in rows if r["tipo_telefone"] == "fixo")
    desconhecidos = sum(1 for r in rows if r["tipo_telefone"] == "desconhecido")
    
    print("\n=========================================")
    print("RELATÓRIO DE NORMALIZAÇÃO DE TELEFONES:")
    print(f"  Total analisados com telefone: {t_total_proc + e_total_proc:,}")
    print(f"    Fixo:                        {fixos:,}")
    print(f"    Celular / WhatsApp possível: {celulares:,}")
    print(f"    Desconhecido / Inválido:     {desconhecidos:,}")
    print(f"  Atualizados no banco:          {t_updated + e_updated:,}")
    print(f"    Transportadoras:             {t_updated:,}")
    print(f"    Embarcadores:                {e_updated:,}")
    print(f"CSV salvo em: {output_path}")
    print("=========================================")

if __name__ == "__main__":
    main()
