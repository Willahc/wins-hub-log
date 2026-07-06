import os
import sys
import shutil
import glob
from backup_db import get_db_path, run_backup

def list_backups(backup_dir="backups"):
    if not os.path.exists(backup_dir):
        print("Diretorio de backups nao encontrado.")
        return []
    files = glob.glob(os.path.join(backup_dir, "local_*.db"))
    files.sort(key=os.path.getmtime, reverse=True)
    return files

def restore(backup_file):
    if not os.path.exists(backup_file):
        print(f"Erro: Arquivo de backup '{backup_file}' nao encontrado.")
        return False

    db_path = get_db_path()
    
    # 1. Fazer backup de seguranca do banco atual se ele existir
    if os.path.exists(db_path):
        print("Realizando backup de seguranca do banco de dados atual...")
        safety_backup = run_backup()
        if not safety_backup:
            print("Abortando restauracao: falha ao gerar backup de seguranca atual.")
            return False
            
    # 2. Copiar backup selecionado para o local original
    try:
        shutil.copy2(backup_file, db_path)
        print(f"Banco de dados restaurado com sucesso para: {db_path}")
        return True
    except Exception as e:
        print(f"Erro ao restaurar banco de dados: {e}")
        return False

if __name__ == "__main__":
    backups = list_backups()
    
    if len(sys.argv) < 2:
        print("Uso: python scripts/restore_db.py <caminho_do_backup>")
        print("\nBackups disponiveis (mais recente primeiro):")
        if not backups:
            print("  Nenhum backup encontrado em backups/")
        for b in backups:
            print(f"  {b}")
        sys.exit(1)

    target_backup = sys.argv[1]
    success = restore(target_backup)
    if not success:
        sys.exit(1)
