import sqlite3
import os
import sys

sys.path.append(os.path.dirname(__file__))
from backup_db import get_db_path

def seed():
    db_path = get_db_path()
    if not os.path.exists(db_path):
        print(f"Erro: Banco de dados '{db_path}' nao encontrado.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 3 Transportadoras Fictícias para SC→SP correspondendo ao corredor de embarcadores fictícios
    # Colunas: corredor, cnpj, razao_social, municipio, uf, telefone, email, cnae_principal, tem_cnae_frete, porte, status_crm, notas
    transportadoras = [
        ("SC→SP", "00.000.000/0004-04", "Trans Alimentos Ltda", "Joinville", "SC", "47999991111", "contato@transalimentos.com.br", "1031700", True, "Pequeno", "Não contatada", "CD Alimentos - Frota ativa refrigerada e sider"),
        ("SC→SP", "00.000.000/0005-05", "Trans Metalurgica Ltda", "Joinville", "SC", "47999992222", "contato@transmetalurgica.com.br", "2539001", True, "Medio", "Não contatada", "CD Siderurgia - Frota de carretas abertas e sider"),
        ("SC→SP", "00.000.000/0006-06", "Trans Geral Ltda", "Joinville", "SC", "47999993333", "contato@transgeral.com.br", "4691500", True, "Grande", "Não contatada", "CD Geral - Frota de bau geral")
    ]
    
    for t in transportadoras:
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO transportadoras (
                    corredor, cnpj, razao_social, municipio, uf,
                    telefone, email, cnae_principal, tem_cnae_frete, porte, status_crm, notas
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, t)
            print(f"Transportadora semeada com sucesso: {t[2]}")
        except Exception as e:
            print(f"Erro ao semear {t[2]}: {e}")
            
    conn.commit()
    conn.close()
    print("Seed de transportadoras ficticias concluido.")

if __name__ == "__main__":
    seed()
