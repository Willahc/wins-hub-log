import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from app import app, db
from config import Config
from models import ImportLog, Transportadora
from jobs import rodar_importacao

def test_real_job_limit():
    print("=== EXECUTANDO JOB DE IMPORTACAO REAL COM LIMITE DE 50 REGISTROS ===")
    with app.app_context():
        # Limpar logs e transportadoras de teste anteriores para comecar limpo
        ImportLog.query.filter_by(corredor="SC->SP").delete()
        Transportadora.query.filter_by(corredor="SC->SP").delete()
        db.session.commit()
        
        # Criar log de importacao
        log = ImportLog(corredor="SC->SP", status="rodando", mensagem="Iniciando teste de 50 registros", progresso=0)
        db.session.add(log)
        db.session.commit()
        log_id = log.id
        print(f"Log de importacao criado. ID: {log_id}")
        
        try:
            print("Executando rodar_importacao (pode demorar alguns segundos por causa da BrasilAPI)...")
            # Rodando na thread principal para diagnóstico
            rodar_importacao(app, "SC->SP", log_id)
            
            # Verificar resultado
            log_resultado = ImportLog.query.get(log_id)
            print(f"Resultado do log: status={log_resultado.status}, progresso={log_resultado.progresso}%, total_inserido={log_resultado.total_inserido}, mensagem={log_resultado.mensagem}")
            if log_resultado.status == "erro":
                print(f"Erro capturado no log: {log_resultado.erro}")
                
            total_transp = Transportadora.query.filter_by(corredor="SC->SP").count()
            print(f"Total de transportadoras SC->SP no banco: {total_transp}")
            if total_transp > 0:
                print("Amostra da primeira transportadora gravada no banco:")
                t = Transportadora.query.filter_by(corredor="SC->SP").first()
                print(f"  CNPJ: {t.cnpj}")
                print(f"  Nome: {t.nome_rntrc}")
                print(f"  Razao Social: {t.razao_social}")
                print(f"  Porte: {t.porte}")
                print(f"  Telefone: {t.telefone}")
                
        except Exception as e:
            print(f"ERRO CRITICO NO JOB: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    test_real_job_limit()
