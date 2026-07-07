#!/usr/bin/env python3
import os
import sys
import csv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import Transportadora, EmbarcadorProvavel

def main():
    print("============================================================")
    print("GERANDO RELATÓRIO DE LACUNAS DE E-MAIL E SITE")
    print("============================================================")
    
    os.makedirs("exports/completude", exist_ok=True)
    output_path = "exports/completude/empresas_sem_email_site.csv"
    
    fields = ["tipo_empresa", "id", "cnpj", "nome", "telefone", "email", "site", "socios", "categoria_lacuna"]
    rows = []
    
    t_sem_email_site = 0
    e_sem_email_site = 0
    com_tel_sem_email = 0
    com_tel_socio_sem_site = 0
    
    with app.app_context():
        # 1. Transportadoras
        print("  Processando Transportadoras...")
        all_trans = Transportadora.query.all()
        for t in all_trans:
            tel = (t.telefone or "").strip()
            email = (t.email or "").strip()
            # Transportadora no schema não tem coluna 'site' física, então consideramos vazio
            site = ""
            socios = (t.socios or "").strip()
            nome = t.razao_social or t.nome_rntrc or t.nome_fantasia or ""
            
            # Categorias
            is_sem_email_site = not email and not site
            is_com_tel_sem_email = bool(tel and not email)
            is_com_tel_socio_sem_site = bool(tel and socios and not site)
            
            if is_sem_email_site or is_com_tel_sem_email or is_com_tel_socio_sem_site:
                cats = []
                if is_sem_email_site:
                    cats.append("sem_email_e_site")
                    t_sem_email_site += 1
                if is_com_tel_sem_email:
                    cats.append("com_telefone_sem_email")
                    com_tel_sem_email += 1
                if is_com_tel_socio_sem_site:
                    cats.append("com_telefone_socio_sem_site")
                    com_tel_socio_sem_site += 1
                    
                rows.append({
                    "tipo_empresa": "transportadora",
                    "id": t.id,
                    "cnpj": t.cnpj,
                    "nome": nome,
                    "telefone": tel,
                    "email": email,
                    "site": site,
                    "socios": socios,
                    "categoria_lacuna": ", ".join(cats)
                })
                
        # 2. Embarcadores
        print("  Processando Embarcadores...")
        all_embs = EmbarcadorProvavel.query.all()
        for e in all_embs:
            tel = (e.telefone or "").strip()
            email = (e.email or "").strip()
            site = (e.site or "").strip()
            socios = (e.socios or "").strip()
            nome = e.razao_social or e.nome_fantasia or ""
            
            # Categorias
            is_sem_email_site = not email and not site
            is_com_tel_sem_email = bool(tel and not email)
            is_com_tel_socio_sem_site = bool(tel and socios and not site)
            
            if is_sem_email_site or is_com_tel_sem_email or is_com_tel_socio_sem_site:
                cats = []
                if is_sem_email_site:
                    cats.append("sem_email_e_site")
                    e_sem_email_site += 1
                if is_com_tel_sem_email:
                    cats.append("com_telefone_sem_email")
                    com_tel_sem_email += 1
                if is_com_tel_socio_sem_site:
                    cats.append("com_telefone_socio_sem_site")
                    com_tel_socio_sem_site += 1
                    
                rows.append({
                    "tipo_empresa": "embarcador",
                    "id": e.id,
                    "cnpj": e.cnpj,
                    "nome": nome,
                    "telefone": tel,
                    "email": email,
                    "site": site,
                    "socios": socios,
                    "categoria_lacuna": ", ".join(cats)
                })
                
    # Gravar CSV
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
        
    print("\n=========================================")
    print("RELATÓRIO DE LACUNAS GERADO:")
    print(f"Total de registros com lacunas: {len(rows):,}")
    print(f"  Transportadoras sem e-mail/site: {t_sem_email_site:,}")
    print(f"  Embarcadores sem e-mail/site:    {e_sem_email_site:,}")
    print(f"  Empresas com tel mas sem e-mail: {com_tel_sem_email:,}")
    print(f"  Empresas com tel e sócio sem site:{com_tel_socio_sem_site:,}")
    print(f"CSV salvo em: {output_path}")
    print("=========================================")

if __name__ == "__main__":
    main()
