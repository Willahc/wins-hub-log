import os
import shutil
import glob
from datetime import datetime

def get_db_path():
    db_url = "sqlite:///local.db"
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                if line.strip().startswith("DATABASE_URL="):
                    db_url = line.split("=", 1)[1].strip()
                    break
    db_url = db_url.strip('"').strip("'")
    if db_url.startswith("sqlite:///"):
        rel_path = db_url.replace("sqlite:///", "")
        # Se nao existe na raiz mas existe dentro do diretorio instance/
        if not os.path.exists(rel_path) and os.path.exists(os.path.join("instance", rel_path)):
            return os.path.join("instance", rel_path)
        if not os.path.exists(rel_path) and os.path.exists("instance"):
            return os.path.join("instance", rel_path)
        return rel_path
    return "local.db"

def clean_old_backups(backup_dir, limit=20):
    files = glob.glob(os.path.join(backup_dir, "local_*.db"))
    # Ordenar por data de modificação (mais antigo primeiro)
    files.sort(key=os.path.getmtime)
    if len(files) > limit:
        to_delete = files[:-limit]
        for f in to_delete:
            try:
                os.remove(f)
            except Exception as e:
                print(f"Erro ao deletar backup antigo {f}: {e}")

def run_backup():
    db_path = get_db_path()
    if not os.path.exists(db_path):
        print(f"Banco de dados '{db_path}' nao encontrado. Nada para salvar.")
        return None

    backup_dir = "backups"
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"local_{timestamp}.db"
    backup_path = os.path.join(backup_dir, backup_filename)

    try:
        shutil.copy2(db_path, backup_path)
        print(f"Backup criado com sucesso: {backup_path}")
        clean_old_backups(backup_dir, limit=20)
        return backup_path
    except Exception as e:
        print(f"Erro ao criar backup: {e}")
        return None

if __name__ == "__main__":
    run_backup()
