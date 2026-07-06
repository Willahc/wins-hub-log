#!/usr/bin/env python3
import os
import sys
import csv

# Add root folder to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from models import MatchPreditivo

def main():
    print("============================================================")
    print("AUDITORIA DE COBERTURA DE CONTATOS COMERCIAIS")
    print("============================================================")
    
    with app.app_context():
        # 1. Carregar todos os matches preditivos
        matches = MatchPreditivo.query.all()
        total_matches = len(matches)
        
        # Coletas de entidades únicas
        unique_t = {}
        unique_e = {}
        
        matches_with_t_contact = 0
        matches_with_e_contact = 0
        matches_no_contact = 0
        
        for m in matches:
            t = m.transportadora
            e = m.embarcador
            
            if t.id not in unique_t:
                unique_t[t.id] = t
            if e.id not in unique_e:
                unique_e[e.id] = e
                
            t_has = bool((t.telefone and t.telefone.strip()) or (t.email and t.email.strip()) or (t.socios and t.socios.strip()))
            e_has = bool((e.telefone and e.telefone.strip()) or (e.email and e.email.strip()) or (e.site and e.site.strip()))
            
            if t_has:
                matches_with_t_contact += 1
            if e_has:
                matches_with_e_contact += 1
            if not t_has and not e_has:
                matches_no_contact += 1
                
        # Estatísticas para Transportadoras únicas
        t_unicas_count = len(unique_t)
        t_com_telefone = sum(1 for t in unique_t.values() if t.telefone and t.telefone.strip())
        t_com_email = sum(1 for t in unique_t.values() if t.email and t.email.strip())
        t_com_socios = sum(1 for t in unique_t.values() if t.socios and t.socios.strip())
        t_com_algum = sum(1 for t in unique_t.values() if (t.telefone and t.telefone.strip()) or (t.email and t.email.strip()) or (t.socios and t.socios.strip()))
        
        # Estatísticas para Embarcadores únicos
        e_unicos_count = len(unique_e)
        e_com_telefone = sum(1 for e in unique_e.values() if e.telefone and e.telefone.strip())
        e_com_email = sum(1 for e in unique_e.values() if e.email and e.email.strip())
        e_com_site = sum(1 for e in unique_e.values() if e.site and e.site.strip())
        e_com_algum = sum(1 for e in unique_e.values() if (e.telefone and e.telefone.strip()) or (e.email and e.email.strip()) or (e.site and e.site.strip()))
        
        # Relatório no terminal
        print(f"Total de Matches:                      {total_matches:,}")
        print(f"Transportadoras Únicas:                {t_unicas_count:,}")
        print(f"Embarcadores Únicos:                   {e_unicos_count:,}")
        print(f"Transportadoras com Telefone:          {t_com_telefone:,}")
        print(f"Transportadoras com E-mail:            {t_com_email:,}")
        print(f"Transportadoras com Sócios:            {t_com_socios:,}")
        print(f"Transportadoras com Algum Contato:     {t_com_algum:,}")
        print(f"Embarcadores com Telefone:             {e_com_telefone:,}")
        print(f"Embarcadores com E-mail:               {e_com_email:,}")
        print(f"Embarcadores com Site:                 {e_com_site:,}")
        print(f"Embarcadores com Algum Contato:        {e_com_algum:,}")
        print(f"Matches com Contato da Transportadora: {matches_with_t_contact:,}")
        print(f"Matches com Contato do Embarcador:     {matches_with_e_contact:,}")
        print(f"Matches sem Contato Nenhum:            {matches_no_contact:,}")
        print("-" * 60)
        
        # 2. Ordenar os matches para a fila prioritária
        # Ordenação:
        # - score_match desc
        # - prioridade Alta primeiro
        # - corredor
        # - empresas sem contato primeiro (contact_count asc: 0, 1, 2)
        def get_sort_key(m):
            t = m.transportadora
            e = m.embarcador
            t_has = bool((t.telefone and t.telefone.strip()) or (t.email and t.email.strip()) or (t.socios and t.socios.strip()))
            e_has = bool((e.telefone and e.telefone.strip()) or (e.email and e.email.strip()) or (e.site and e.site.strip()))
            contact_count = (1 if t_has else 0) + (1 if e_has else 0)
            
            prio_val = 3 if m.prioridade == "Alta" else 2 if m.prioridade == "Média" else 1
            
            # Para score_match desc, usamos -score_match
            # Para prioridade desc, usamos -prio_val
            # Para corredor asc, usamos m.corredor
            # Para sem contato primeiro, usamos contact_count (asc)
            return (-m.score_match, -prio_val, m.corredor or "", contact_count)
            
        matches_sorted = sorted(matches, key=get_sort_key)
        
        # 3. Exportar fila de contatos para CSV
        os.makedirs("exports/contatos", exist_ok=True)
        csv_path = "exports/contatos/fila_contatos_prioritarios_matches.csv"
        
        written_entities = set() # Guarda (tipo_empresa, id) para evitar duplicatas na fila
        
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow([
                "tipo_empresa", "id", "cnpj", "nome", "telefone", "email", "site", "socios", 
                "score_match", "prioridade", "corredor", "fonte_contato", "observacao_contato"
            ])
            
            for m in matches_sorted:
                t = m.transportadora
                e = m.embarcador
                
                # Adicionar transportadora se não foi escrita ainda
                t_key = ("transportadora", t.id)
                if t_key not in written_entities:
                    writer.writerow([
                        "transportadora",
                        t.id,
                        t.cnpj,
                        t.razao_social or t.nome_rntrc or t.nome_fantasia or "",
                        t.telefone or "",
                        t.email or "",
                        "",  # site não existe para transportadora
                        t.socios or "",
                        m.score_match,
                        m.prioridade,
                        m.corredor,
                        "",  # fonte_contato
                        ""   # observacao_contato
                    ])
                    written_entities.add(t_key)
                    
                # Adicionar embarcador se não foi escrito ainda
                e_key = ("embarcador", e.id)
                if e_key not in written_entities:
                    writer.writerow([
                        "embarcador",
                        e.id,
                        e.cnpj,
                        e.razao_social or e.nome_fantasia or "",
                        e.telefone or "",
                        e.email or "",
                        e.site or "",
                        "",  # socios não existe para embarcador
                        m.score_match,
                        m.prioridade,
                        m.corredor,
                        "",  # fonte_contato
                        ""   # observacao_contato
                    ])
                    written_entities.add(e_key)
                    
        print(f"Fila exportada com sucesso em: {csv_path}")
        print(f"Total de registros de empresas na fila de contatos: {len(written_entities):,}")
        print("============================================================")

if __name__ == "__main__":
    main()
