import os
import sqlite3
from backup_db import get_db_path

def run_check():
    db_path = get_db_path()
    if not os.path.exists(db_path):
        print(f"Erro: Banco de dados '{db_path}' nao encontrado localmente.")
        return

    print(f"=== Relatorio de Checagem do Banco SQLite: {db_path} ===")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Listar tabelas
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [t[0] for t in cursor.fetchall()]
        print(f"\nTabelas encontradas ({len(tables)}):")
        for t in sorted(tables):
            # Obter quantidade de colunas
            cursor.execute(f"PRAGMA table_info({t});")
            cols = len(cursor.fetchall())
            print(f"  - {t} ({cols} colunas)")
            
        print("\nContagem de Registros Principais:")
        
        # Dicionario de tabelas esperadas
        tabelas_esperadas = {
            "transportadoras": "transportadoras",
            "import_logs": "import_logs",
            "embarcadores_provaveis": "embarcadores_provaveis",
            "matches_preditivos": "matches_preditivos",
            "prospeccao_logs": "prospeccao_logs"
        }
        
        for rotulo, tabela in tabelas_esperadas.items():
            if tabela in tables:
                cursor.execute(f"SELECT COUNT(*) FROM {tabela};")
                count = cursor.fetchone()[0]
                print(f"  * {rotulo}: {count} registros")
            else:
                print(f"  * {rotulo}: TABELA NAO ENCONTRADA")
                
        conn.close()
        print("\n=======================================================")
    except Exception as e:
        print(f"Erro ao conectar ou ler banco de dados: {e}")

if __name__ == "__main__":
    run_check()
