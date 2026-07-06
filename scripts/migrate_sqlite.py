import os
import sqlite3
from backup_db import get_db_path, run_backup

def migrate():
    # 1. Gerar backup automatico antes de comecar a migracao
    print("Iniciando processo de migracao segura...")
    db_path = get_db_path()
    if not os.path.exists(db_path):
        print(f"Aviso: Banco de dados '{db_path}' nao existe. O Flask ira cria-lo vazio automaticamente.")
        return
        
    print("Gerando backup preventivo antes de aplicar migracao...")
    backup_file = run_backup()
    if not backup_file:
        print("Abortando migracao: Falha ao gerar o backup de seguranca preventivo.")
        return

    schema_esperado = {
        "transportadoras": [
            ("corredor_alvo",    "TEXT"),
            ("origem_provavel",  "TEXT"),
            ("destino_provavel", "TEXT"),
        ],
        "matches_preditivos": [
            ("temperatura", "VARCHAR(20) DEFAULT 'Frio'"),
            ("proxima_acao", "VARCHAR(200)"),
            ("data_proxima_acao", "VARCHAR(10)"),
            ("resultado_ultimo", "VARCHAR(50)")
        ],
        "prospeccao_logs": [
            ("proxima_acao", "VARCHAR(200)"),
            ("data_proxima_acao", "VARCHAR(10)"),
            ("resultado", "VARCHAR(50)"),
            ("responsavel", "VARCHAR(100) DEFAULT 'Comercial'"),
            ("temperatura", "VARCHAR(20)")
        ],
        "import_logs": [
            ("progresso", "INTEGER DEFAULT 0"),
            ("total_inserido", "INTEGER DEFAULT 0"),
            ("erro", "TEXT")
        ]
    }

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Obter tabelas existentes
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tabelas_existentes = [t[0] for t in cursor.fetchall()]
        
        colunas_adicionadas = 0
        
        for tabela, colunas in schema_esperado.items():
            if tabela not in tabelas_existentes:
                print(f"Aviso: Tabela '{tabela}' nao existe no banco de dados. Sera criada pelo Flask.")
                continue
                
            # Ler colunas existentes na tabela
            cursor.execute(f"PRAGMA table_info({tabela});")
            colunas_reais = [col[1] for col in cursor.fetchall()]
            
            for col_nome, col_tipo in colunas:
                if col_nome not in colunas_reais:
                    print(f"Adicionando coluna '{col_nome}' ({col_tipo}) na tabela '{tabela}'...")
                    cursor.execute(f"ALTER TABLE {tabela} ADD COLUMN {col_nome} {col_tipo};")
                    colunas_adicionadas += 1
                    
        conn.commit()
        conn.close()
        
        if colunas_adicionadas > 0:
            print(f"Migracao concluida com sucesso. {colunas_adicionadas} colunas foram adicionadas.")
        else:
            print("Nenhuma alteracao de schema foi necessaria. O banco esta atualizado!")
            
    except Exception as e:
        print(f"Erro durante a migracao: {e}")

if __name__ == "__main__":
    migrate()
