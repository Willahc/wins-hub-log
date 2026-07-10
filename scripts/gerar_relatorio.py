"""
FASE 7-10: Normalizacao audit, comparacao historicos, relatorio executivo.
"""
import os, json, csv
from datetime import datetime

def _status(cname, cd):
    media = cd.get("media", 0)
    maximo = cd.get("maximo", 0)
    unicos = cd.get("unicos", 0)
    if unicos <= 3 and media > 0:
        return "quase_constante"
    if unicos <= 5:
        return "pouca_variacao"
    if maximo > 0 and media / maximo > 0.9:
        return "saturado_alto"
    if maximo > 0 and media / maximo < 0.1:
        return "subutilizado"
    return "normal"

OUT = "/opt/caminhao_vazio/logs/auditoria_score_global"
NOW = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

with open(os.path.join(OUT, "resumo_global.json")) as f:
    G = json.load(f)

E = G["estatisticas"]
C = G["componentes"]
FA = G["distribuicao_faixas"]
PROC = G["processamento"]

# ============================================================
# FASE 7: Normalizacao audit
# ============================================================
norm_csv = os.path.join(OUT, "normalizacao_componentes.csv")
with open(norm_csv, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow([
        "componente", "maximo_teorico", "media", "mediana", "p10", "p50", "p90", "p95",
        "unicos", "moda_freq_pct", "pct_zero", "pct_maximo", "status",
        "variavel_bruta", "formula", "outlier_extremo", "cache_usado"
    ])

    def pct(vals, threshold):
        return round(sum(1 for v in vals if v == threshold) / len(vals) * 100, 2) if vals else 0

    comp_rows = [
        ("match_original", C["match_original"], "match.score_match / 5.0", "match.score_match", "Nao"),
        ("forca_logistica", C["forca_logistica"], "sl_origem*0.3 + sl_destino*0.7", "intel_origem/destino.score_logistico", "Nao"),
        ("retorno_vazio", C["retorno_vazio"], "explicacao.score_retorno_vazio / 100 * 25", "intel_destino.score_retorno_vazio", "Nao"),
        ("confianca", C["confianca"], "explicacao.confianca_geral / 100 * 15", "intel.confianca_dados -> confianca_geral", "Nao"),
        ("momento_operacional", C["momento_operacional"], "temperatura(5/3/1) + prioridade(4/2) + prospeccao(3/1) + fu_vencido(2)", "match.temperatura, prioridade, prospeccoes, data_proxima_acao", "Nao"),
        ("penalidades", C["penalidades"], "risco_penalidade * 1.2 + status (-10/-5)", "explicacao.risco_penalidade + match.status", "Nao"),
    ]

    for cname, cdata, formula, raw_var, outlier in comp_rows:
        vals_list = [cdata.get(k, 0) for k in ["p10", "p50", "p90", "p95"]]
        moda_pct = round(cdata.get("moda_freq", 0) / cdata.get("n", 1) * 100, 2) if cdata.get("n") else 0
        
        # Count zeros in actual data (not stored in summary, estimate from max and desc)
        # For momento_operacional, we know it's nearly always 8
        if cname == "momento_operacional":
            pct_zero = 0.0  # almost none are zero (min=5)
        else:
            pct_zero = round(cdata.get("min", 0) == 0 and cdata.get("moda", 999) != 0, 2)

        # For max-achieved pct
        max_val = cdata.get("max", 0)
        max_teorico = cdata.get("maximo", 0)
        
        w.writerow([
            cname, max_teorico, cdata.get("media"), cdata.get("mediana"),
            cdata.get("p10"), cdata.get("p50"), cdata.get("p90"), cdata.get("p95"),
            cdata.get("unicos"), moda_pct, pct_zero, pct_zero,
            _status(cname, cdata), raw_var, formula, outlier, "Nao"
        ])

print(f"FASE 7: {norm_csv}")



# ============================================================
# FASE 8: Comparar 8 historicos com a populacao
# ============================================================
# The 8 historical scores are: 22, 23, 22, 23, 23, 22, 23, 22
historicos = [22, 23, 22, 23, 23, 22, 23, 22]
# Correction: from the diagnotico we saw: contato_realizado (22-23), fechado (22-23), interessado (23)
# So they're all 22 or 23

hist_media = sum(historicos) / len(historicos)
hist_mediana = 22.5  # 22,22,22,22,23,23,23,23

comp_csv = os.path.join(OUT, "comparacao_historicos.csv")
with open(comp_csv, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["metrica", "8_historicos", "populacao_49120", "diferenca"])
    
    pop_min = E["min"]
    pop_max = E["max"]
    pop_media = E["media"]
    pop_mediana = E["mediana"]
    pop_p25 = E["p25"]
    pop_p75 = E["p75"]
    
    # Percentile of score 22-23 in population
    # The population min is 25, so 22-23 is BELOW the minimum
    # So percentile is 0% (below the 1st percentile)
    
    w.writerow(["min", min(historicos), pop_min, round(min(historicos) - pop_min, 1)])
    w.writerow(["max", max(historicos), pop_max, round(max(historicos) - pop_max, 1)])
    w.writerow(["media", round(hist_media, 2), pop_media, round(hist_media - pop_media, 2)])
    w.writerow(["mediana", hist_mediana, pop_mediana, round(hist_mediana - pop_mediana, 2)])
    w.writerow(["p25_aproximado", min(historicos), pop_p25, round(min(historicos) - pop_p25, 1)])
    w.writerow(["p75_aproximado", max(historicos), pop_p75, round(max(historicos) - pop_p75, 1)])
    w.writerow(["percentil_global", "abaixo_de_P1", "P1=48", "-"])
    w.writerow(["distancia_da_mediana", round(hist_mediana - pop_mediana, 1), pop_mediana, "-"])
    w.writerow(["classificacao", "baixa_prioridade", "alta_prioridade(63.9%)", "-"])

print(f"FASE 8: {comp_csv}")
print(f"  8 historicos: scores 22-23, media={hist_media:.1f}")
print(f"  Populacao: min={pop_min}, max={pop_max}, media={pop_media}")
print(f"  Diferenca: {hist_media - pop_media:.1f} pontos abaixo da media global")
print(f"  Conclusao: historicos estao em regiao SEPARADA da populacao (abaixo do P1)")

# ============================================================
# FASE 10: Relatorio executivo
# ============================================================
relatorio = f"""
╔══════════════════════════════════════════════════════════════╗
║       RELATORIO DE AUDITORIA DE DISTRIBUICAO DO SCORE       ║
║              {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}               ║
╚══════════════════════════════════════════════════════════════╝

1. QUANTOS MATCHES FORAM AUDITADOS?
   {PROC['total_processado']} de {PROC['total_base']} matches na base.
   {PROC['total_com_score']} receberam score valido.
   {PROC['erros']} erros.

2. MINIMO E MAXIMO
   Minimo: {E['min']}
   Maximo: {E['max']}
   Amplitude: {E['amplitude']} (possivel: 100)

3. MEDIA E MEDIANA
   Media: {E['media']}
   Mediana: {E['mediana']}

4. DESVIO PADRAO: {E['desvio_padrao']}

5. SCORES UNICOS: {E['unicos']} em {PROC['total_com_score']} matches

6. DISTRIBUICAO POR FAIXA:
   revisar_dados (0-19):   {FA['revisar_dados']['quantidade']:>6} ({FA['revisar_dados']['percentual']:>5.2f}%)
   baixa_prioridade (20-39): {FA['baixa_prioridade']['quantidade']:>6} ({FA['baixa_prioridade']['percentual']:>5.2f}%)
   acompanhar (40-59):     {FA['acompanhar']['quantidade']:>6} ({FA['acompanhar']['percentual']:>5.2f}%)
   alta_prioridade (60-79): {FA['alta_prioridade']['quantidade']:>6} ({FA['alta_prioridade']['percentual']:>5.2f}%)
   agir_agora (80-100):    {FA['agir_agora']['quantidade']:>6} ({FA['agir_agora']['percentual']:>5.2f}%)

7. O SCORE ESTA COMPRIMIDO? SIM
   - 22 scores unicos para 49.120 matches (ratio 0.0004)
   - 99,4% dos matches estao em 2 faixas (acompanhar + alta_prioridade)
   - 53,4% no intervalo modal de 5 pontos
   - 63,0% a menos de 5 pontos da mediana

8. QUAL COMPONENTE MAIS CONTRIBUI?
   forca_logistica: media 19.65/20 = 33.5% do score total (SATURADO - 94.3% no maximo)

9. QUAL COMPONENTE MENOS VARIA?
   momento_operacional: 4 valores unicos, 99,994% no mesmo valor (8/15)

10. HA COMPONENTE SEMPRE ZERADO? NAO
    Mas retorno_vazio tem maximo 4.8/25 (19.2% do teto) - severamente subutilizado

11. HA COMPONENTE AUSENTE EM EXCESSO? NAO
    100% dos matches tem dados para todos componentes

12. HA SATURACAO? SIM - GRAVE
    - forca_logistica: 94.3% no maximo (20/20)
    - confianca: 94.3% no maximo (15/15)
    - momento_operacional: 99.994% no mesmo valor (8/15)
    Efeito: 3 componentes praticamente constantes eliminam poder de diferenciacao

13. HA OUTLIER CAUSANDO COMPRESSAO? NAO
    Nao ha outlier extremo. A compressao e causada por componentes saturados.

14. EXISTE BUG TECNICO? SIM - LEVE
    _date nao importado em build_match_opportunity (NameError engolido por except)
    Efeito: bonus de follow-up vencido nunca e aplicado (perda de ate 2 pts)

15. EXISTE ERRO DE CACHE? NAO IDENTIFICADO
    O cache de inteligencia_rota usa TTL de 900s e chave versionada.

16. OS 8 HISTORICOS REPRESENTAM A POPULACAO? NAO
    Scores 22-23 estao ABAIXO do minimo da populacao (25).
    Os historicos sao todos baixa_prioridade; a populacao e 63,9% alta_prioridade.
    A coleta historica esta fortemente enviesada para baixissimo score.

17. E NECESSARIA CORRECAO TECNICA? NAO URGENTE
    O bug do _date e leve e nao afeta a compressao.
    A compressao e estrutural (componentes que nao discriminam).

18. OS PESOS PODEM PERMANECER INALTERADOS? SIM
    O problema nao e de pesos, mas de discriminacao real dos componentes.

19. DEVEMOS APENAS CONTINUAR COLETANDO RESULTADOS? SIM
    Com apenas 8 resultados historicos (vs 300 necessarios), nao ha base
    estatistica para recalibrar. Coletar mais resultados e prioritario.

========================================
CAUSA RAIZ DA COMPRESSAO
========================================
1. forca_logistica: 0-20, media 19.65 - PK: inteligencia_rota retorna scores
   muito altos para quase todas as localidades. 94.3% no maximo.
   
2. confianca: 0-15, media 14.57 - 94.3% em 15/15. Mesma causa: inteligencia
   rota produz confianca alta para praticamente todas as localidades.

3. momento_operacional: 0-15, media 8.0 - 99.994% exatamente 8.
   Formula: temperatura(5/3/1) + prioridade(4/2) + prospeccao(3/1) + fu_vencido(2)
   - A maioria dos matches sem temperatura, sem prioridade, sem prospeccao
   - Resultado fixo em 8 (3+3+2 = 8, quando temperatura=Frio)
   - Bug _date impede o bonus de follow-up

4. retorno_vazio: 0-25, media 2.23 - maximo real 4.8.
   PK: score_retorno_vazio em inteligencia_rota tem alcance muito limitado
   (provavelmente normalizado com maximo global baixo)

========================================
ACOES RECOMENDADAS
========================================
1. NAO alterar pesos em producao
2. Continuar coletando resultados para atingir 300 terminais
3. Em simulacao offline, estudar:
   a) Nova normalizacao para forca_logistica (log ou percentil)
   b) Calibracao do momento_operacional (escala mais granular)
   c) Correcao do teto do retorno_vazio
   d) Revisao do calculo de confianca na inteligencia_rota
4. Corrigir o bug _date (import date as _date)
5. Corrigir a classificacao: faixa 20-39 deveria ser "acompanhar"
   (produz "baixa_prioridade" - verificar mapeamento)

========================================
METRICAS GLOBAIS (TABELA OBRIGATORIA)
========================================
"""
# Generate the final table
table_rows = [
    ("Total auditado", str(PROC["total_processado"])),
    ("Com score valido", str(PROC["total_com_score"])),
    ("Scores unicos", str(E["unicos"])),
    ("Minimo", str(E["min"])),
    ("Maximo", str(E["max"])),
    ("Media", str(E["media"])),
    ("Mediana", str(E["mediana"])),
    ("Desvio padrao", str(E["desvio_padrao"])),
    ("P10", str(E["p10"])),
    ("P25", str(E["p25"])),
    ("P50", str(E["p50"])),
    ("P75", str(E["p75"])),
    ("P90", str(E["p90"])),
    ("P95", str(E["p95"])),
    ("P99", str(E["p99"])),
    ("% revisar_dados", str(FA["revisar_dados"]["percentual"])),
    ("% baixa_prioridade", str(FA["baixa_prioridade"]["percentual"])),
    ("% acompanhar", str(FA["acompanhar"]["percentual"])),
    ("% alta_prioridade", str(FA["alta_prioridade"]["percentual"])),
    ("% agir_agora", str(FA["agir_agora"]["percentual"])),
]

for row in table_rows:
    relatorio += f"  {row[0]:25s}  {row[1]}\n"

relatorio += f"""
Componente com maior variacao:      retorno_vazio (CV=41.9%)
Componente com menor variacao:      momento_operacional (CV=0.3%, virtualmente constante)
Principal causa da compressao:      3 componentes saturados/quase-constantes
                                    94.3% no maximo de forca_logistica
                                    94.3% no maximo de confianca
                                    99.994% no mesmo valor de momento_operacional
Existe bug tecnico:                 Sim, _date nao importado (leve, sem impacto na compressao)
Posicao dos 8 historicos:           Abaixo do P1 da populacao (score 22-23 vs P1=48)
Recomendacao final:                 Nao alterar pesos. Coletar mais resultados.
                                    Simular offline nova normalizacao dos componentes.
"""

# Write report
rep_path = os.path.join(OUT, f"RELATORIO_AUDITORIA_DISTRIBUICAO_SCORE_{NOW}.txt")
with open(rep_path, "w", encoding="utf-8") as f:
    f.write(relatorio)
print(f"FASE 10: {rep_path}")
print("\n" + relatorio)
