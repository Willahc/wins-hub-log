#!/usr/bin/env python3
import os
import sys
import csv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import Transportadora, EmbarcadorProvavel

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
        # Se começar com 9 ou 8 (muitos celulares antigos começavam com 8 ou 9)
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
    print("============================================================")
    print("NORMALIZADOR DE TELEFONES")
    print("============================================================")
    
    os.makedirs("exports/completude", exist_ok=True)
    output_path = "exports/completude/telefones_normalizados.csv"
    
    fields = [
        "tipo_empresa", "id", "cnpj", "nome", "telefone_original", 
        "telefone_normalizado", "ddd", "tipo_telefone", "whatsapp_possivel"
    ]
    rows = []
    
    t_updated = 0
    e_updated = 0
    
    with app.app_context():
        # 1. Transportadoras
        print("  Normalizando Transportadoras...")
        all_trans = Transportadora.query.all()
        for t in all_trans:
            if not t.telefone:
                continue
                
            orig = t.telefone
            norm, ddd, tipo, whatsapp = normalize_phone_number(orig)
            
            rows.append({
                "tipo_empresa": "transportadora",
                "id": t.id,
                "cnpj": t.cnpj,
                "nome": t.razao_social or t.nome_rntrc or t.nome_fantasia or "",
                "telefone_original": orig,
                "telefone_normalizado": norm,
                "ddd": ddd or "",
                "tipo_telefone": tipo,
                "whatsapp_possivel": "Sim" if whatsapp else "Não"
            })
            
            # Se for modificado e não estiver em dry-run (estamos rodando direto no banco)
            is_modified = False
            if norm and t.telefone != norm:
                note = f"\n[Telefone normalizado] Original: {orig}"
                t.notas = (t.notas or "") + note
                t.telefone = norm
                is_modified = True
                
            if t.whatsapp_possivel != whatsapp:
                t.whatsapp_possivel = whatsapp
                is_modified = True
                
            if is_modified:
                db.session.add(t)
                t_updated += 1
                
        # 2. Embarcadores
        print("  Normalizando Embarcadores...")
        all_embs = EmbarcadorProvavel.query.all()
        for e in all_embs:
            if not e.telefone:
                continue
                
            orig = e.telefone
            norm, ddd, tipo, whatsapp = normalize_phone_number(orig)
            
            rows.append({
                "tipo_empresa": "embarcador",
                "id": e.id,
                "cnpj": e.cnpj,
                "nome": e.razao_social or e.nome_fantasia or "",
                "telefone_original": orig,
                "telefone_normalizado": norm,
                "ddd": ddd or "",
                "tipo_telefone": tipo,
                "whatsapp_possivel": "Sim" if whatsapp else "Não"
            })
            
            is_modified = False
            if norm and e.telefone != norm:
                note = f"\n[Telefone normalizado] Original: {orig}"
                e.notas = (e.notas or "") + note
                e.telefone = norm
                is_modified = True
                
            if e.whatsapp_possivel != whatsapp:
                e.whatsapp_possivel = whatsapp
                is_modified = True
                
            if is_modified:
                db.session.add(e)
                e_updated += 1
                
        if t_updated > 0 or e_updated > 0:
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
        
    print("\n=========================================")
    print("NORMALIZAÇÃO DE TELEFONES CONCLUÍDA:")
    print(f"Total de telefones normalizados: {len(rows):,}")
    print(f"  Transportadoras atualizadas:   {t_updated:,}")
    print(f"  Embarcadores atualizados:      {e_updated:,}")
    print(f"CSV salvo em: {output_path}")
    print("=========================================")

if __name__ == "__main__":
    main()
