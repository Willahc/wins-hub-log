"""Create checkpoint for auditoria distribuicao score."""
path = "/opt/caminhao_vazio/logs/CHECKPOINT_AUDITORIA_DISTRIBUICAO_SCORE_20260710.txt"
with open(path, "w") as f:
    f.write("""CHECKPOINT AUDITORIA DISTRIBUICAO SCORE - 2026-07-10 19:55 UTC

### RESULTADOS
Total de matches: 49.120
Total processado: 49.120
Total com score: 49.120
Scores unicos: 22
Minimo: 25
Maximo: 68
Media: 58.58
Mediana: 62.0
Desvio padrao: 6.28
P10: 50.0
P25: 51.0
P50: 62.0
P75: 63.0
P90: 65.0
P95: 66.0
P99: 67.0

### DISTRIBUICAO POR FAIXA
revisar_dados (0-19): 0 (0.0%)
baixa_prioridade (20-39): 70 (0.14%)
acompanhar (40-59): 17.673 (35.98%)
alta_prioridade (60-79): 31.377 (63.88%)
agir_agora (80-100): 0 (0.0%)

### COMPRESSAO
53.44% no intervalo modal de 5 pontos
62.96% a menos de 5 pontos da mediana
22 scores unicos / 49.120 total (ratio 0.0004)
Alertas: MAIS_50_INTERVALO_5

### COMPONENTES
match_original: media 17.79/20 (89.0%), 20 valores unicos
forca_logistica: media 19.65/20 (98.3%), SATURADO (94.3% no maximo)
retorno_vazio: media 2.23/25 (8.9%), max real 4.8/25
confianca: media 14.57/15 (97.1%), SATURADO (94.3% no maximo)
momento_operacional: media 8.0/15 (53.3%), VIRTUALMENTE CONSTANTE
penalidades: media -3.66/15, 69.5% em 0

### COMPARACAO 8 HISTORICOS
Scores historicos: 22-23, media 22.5
Populacao: 25-68, media 58.58
Diferenca: -36.1 pontos (historicos abaixo do P1 da populacao)
Conclusao: Historicos NAO representam a populacao

### BUG TECNICO
Nome: _date nao importado em build_match_opportunity()
Impacto: Bonus de follow-up vencido (2 pts) nunca aplicado
Correcao: Nao aplicada (fora do escopo)

### RECOMENDACAO
Nao alterar pesos
Continuar coletando resultados
Simular offline nova normalizacao dos componentes

### ARQUIVOS GERADOS
/opt/caminhao_vazio/logs/auditoria_score_global/resumo_global.json
/opt/caminhao_vazio/logs/auditoria_score_global/distribuicao_faixas.csv
/opt/caminhao_vazio/logs/auditoria_score_global/distribuicao_scores.csv
/opt/caminhao_vazio/logs/auditoria_score_global/componentes.csv
/opt/caminhao_vazio/logs/auditoria_score_global/normalizacao_componentes.csv
/opt/caminhao_vazio/logs/auditoria_score_global/comparacao_historicos.csv
/opt/caminhao_vazio/logs/auditoria_score_global/amostra_percentis.csv
/opt/caminhao_vazio/logs/auditoria_score_global/RELATORIO_AUDITORIA_DISTRIBUICAO_SCORE_20260710_195202.txt

### PERFORMANCE
Tempo de auditoria: 317s (5.3 min)
Taxa: 155 matches/s
Zero queries individuais por match (batch processing + bicada inteligencia rota)
Memoria: processamento batch de 500 matches

### COMERCIAL
HTTPS winshubcomercial.com.br: 200
Nenhum arquivo do Comercial alterado

### VERSAO FORMULA
MATCH_SCORE_FORMULA_VERSION = v1 (inalterada)
Pesos nao alterados
""")
print(f"Checkpoint: {path}")
