"""
Diagnostic queries on prospeccao_logs snapshots for quality evaluation.
"""
import sqlite3, os

DB = os.path.join(os.path.dirname(__file__), "..", "instance", "local.db")
DB = os.path.normpath(DB)

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 1. Total de logs
cur.execute("SELECT COUNT(*) as total, COUNT(score_oportunidade_no_momento) as c_snap FROM prospeccao_logs")
r = cur.fetchone()
print("=== 1. Visao Geral dos Logs ===")
print(f"Total de logs: {r['total']}")
print(f"Com snapshot score_oportunidade: {r['c_snap']}")

# 2. Logs com resultado
cur.execute("SELECT COUNT(*) as total, COUNT(score_oportunidade_no_momento) as c_snap FROM prospeccao_logs WHERE canal='Resultado'")
r = cur.fetchone()
print("\n=== 2. Logs com Resultado (canal=Resultado) ===")
print(f"Total: {r['total']}")
print(f"Com snapshot score_oportunidade: {r['c_snap']}")

# 3. Distribuicao de resultados
cur.execute("""SELECT resultado, COUNT(*) as cnt 
FROM prospeccao_logs WHERE canal='Resultado' 
GROUP BY resultado ORDER BY cnt DESC""")
print("\n=== 3. Distribuicao de Resultados ===")
for row in cur.fetchall():
    print(f"  {row['resultado']:25s}: {row['cnt']}")

# 4. Score statistics por resultado
cur.execute("""SELECT resultado, 
ROUND(AVG(score_oportunidade_no_momento),1) as avg_score,
ROUND(MIN(score_oportunidade_no_momento),1) as min_score,
ROUND(MAX(score_oportunidade_no_momento),1) as max_score,
COUNT(*) as cnt
FROM prospeccao_logs 
WHERE canal='Resultado' AND score_oportunidade_no_momento IS NOT NULL
GROUP BY resultado 
ORDER BY avg_score DESC""")
print("\n=== 4. Score Oportunidade por Resultado ===")
for row in cur.fetchall():
    print(f"  {row['resultado']:25s} avg={row['avg_score']:>5.1f}  min={row['min_score']:>5.1f}  max={row['max_score']:>5.1f}  n={row['cnt']}")

# 5. Logs sem snapshot
cur.execute("""SELECT COUNT(*) as sem_snapshot FROM prospeccao_logs 
WHERE canal='Resultado' AND score_oportunidade_no_momento IS NULL""")
r = cur.fetchone()
print(f"\n=== 5. Resultados sem Snapshot de Score ===")
print(f"Logs com resultado mas sem snapshot: {r['sem_snapshot']}")

# 6. Componentes disponiveis
cur.execute("""SELECT COUNT(score_logistico_origem_momento) as c_lo,
COUNT(score_logistico_destino_momento) as c_ld,
COUNT(score_retorno_no_momento) as c_rv,
COUNT(confianca_no_momento) as c_cg
FROM prospeccao_logs WHERE canal='Resultado'""")
r = cur.fetchone()
print("\n=== 6. Componentes de Snapshot Disponiveis ===")
print(f"score_logistico_origem: {r['c_lo']}")
print(f"score_logistico_destino: {r['c_ld']}")
print(f"score_retorno_no_momento: {r['c_rv']}")
print(f"confianca_no_momento: {r['c_cg']}")

# 7. Resultados terminais
cur.execute("""SELECT COUNT(*) as terminais FROM prospeccao_logs 
WHERE canal='Resultado' AND resultado IN ('fechado','perdido','cancelado','duplicado','dados_incorretos')""")
r = cur.fetchone()
print(f"\n=== 7. Resultados Terminais ===")
print(f"Total de resultados terminais: {r['terminais']}")

# 8. Transicoes de status
cur.execute("""SELECT status_anterior, status_novo, COUNT(*) as cnt 
FROM prospeccao_logs WHERE canal='Resultado' AND status_anterior IS NOT NULL
GROUP BY status_anterior, status_novo 
ORDER BY cnt DESC LIMIT 15""")
print("\n=== 8. Top 15 Transicoes de Status ===")
for row in cur.fetchall():
    print(f"  {row['status_anterior']:30s} -> {row['status_novo']:30s} : {row['cnt']}")

# 9. Faixas de score vs resultado
cur.execute("""SELECT 
CASE 
  WHEN score_oportunidade_no_momento >= 80 THEN '80-100'
  WHEN score_oportunidade_no_momento >= 60 THEN '60-79'
  WHEN score_oportunidade_no_momento >= 40 THEN '40-59'
  WHEN score_oportunidade_no_momento >= 20 THEN '20-39'
  ELSE '0-19'
END as faixa,
resultado,
COUNT(*) as cnt
FROM prospeccao_logs 
WHERE canal='Resultado' AND score_oportunidade_no_momento IS NOT NULL
GROUP BY faixa, resultado
ORDER BY faixa, cnt DESC""")
print("\n=== 9. Faixas de Score vs Resultado ===")
for row in cur.fetchall():
    print(f"  faixa={row['faixa']:6s}  {row['resultado']:25s}: {row['cnt']}")

# 10. Distribuicao da classificacao_oportunidade
cur.execute("""SELECT classificacao_oportunidade_no_momento, COUNT(*) as cnt 
FROM prospeccao_logs WHERE canal='Resultado' AND classificacao_oportunidade_no_momento IS NOT NULL
GROUP BY classificacao_oportunidade_no_momento ORDER BY cnt DESC""")
print("\n=== 10. Classificacao Oportunidade nos Snapshots ===")
for row in cur.fetchall():
    print(f"  {row['classificacao_oportunidade_no_momento']:25s}: {row['cnt']}")

# 11. Classificacao vs resultado
cur.execute("""SELECT classificacao_oportunidade_no_momento, resultado, COUNT(*) as cnt
FROM prospeccao_logs 
WHERE canal='Resultado' AND classificacao_oportunidade_no_momento IS NOT NULL
GROUP BY classificacao_oportunidade_no_momento, resultado
ORDER BY classificacao_oportunidade_no_momento, cnt DESC""")
print("\n=== 11. Classificacao vs Resultado ===")
for row in cur.fetchall():
    print(f"  {row['classificacao_oportunidade_no_momento']:20s} -> {row['resultado']:25s}: {row['cnt']}")

conn.close()
