"""Create checkpoint file."""
CHECKPOINT = "/opt/caminhao_vazio/logs/CHECKPOINT_QUALIDADE_SCORE_20260710.txt"
with open(CHECKPOINT, "w", encoding="utf-8") as f:
    f.write("""CHECKPOINT QUALIDADE SCORE - 2026-07-10 19:27 UTC

### What was done
- FASE 1: Chromium screenshots (8 screenshots, 7 pages)
- FASE 2: Backup incremental em /opt/caminhao_vazio/backups/qualidade_score_oportunidade_20260710/
- FASE 3: Diagnostico snapshots via diagnostico_snapshots.py
- FASE 4-7: Taxonomia resultados, metricas, faixas, amostra minima
- FASE 8: Regra anti-vazamento temporal (verificar_vazamento_temporal)
- FASE 9: services/qualidade_score.py criado
- FASE 10: View /qualidade-score + template
- FASE 11: Link na sidebar do base.html
- FASE 12: GET /api/metricas/qualidade-score endpoint

### Files created/modified
- services/qualidade_score.py (novo)
- templates/qualidade_score.html (novo)
- app.py (import + 2 rotas adicionadas)
- templates/base.html (sidebar link adicionado)
- scripts/chromium_screenshot.py (atualizado)
- scripts/diagnostico_snapshots.py (novo)

### Resultados do Diagnostico
- 16 total logs, 8 com resultado, 8/8 com snapshot completo
- Score range muito estreito (22-23/100), todos baixa_prioridade
- Variabilidade baixa - amostra insuficiente para calibracao
- Vazamento temporal: OK (0 sem snapshot)
- Thresholds: 300 terminais / 50 resultados minimos

### Screenshots
/opt/caminhao_vazio/logs/screenshots_qualidade_score/01_fila_decisao_geral.png
/opt/caminhao_vazio/logs/screenshots_qualidade_score/02_ranking_oportunidades.png
/opt/caminhao_vazio/logs/screenshots_qualidade_score/03_filtros_oportunidade.png
/opt/caminhao_vazio/logs/screenshots_qualidade_score/04_offcanvas_inteligencia.png
/opt/caminhao_vazio/logs/screenshots_qualidade_score/05_formulario_resultado.png
/opt/caminhao_vazio/logs/screenshots_qualidade_score/06_qualidade_score.png
/opt/caminhao_vazio/logs/screenshots_qualidade_score/07_layout_1366x768.png
/opt/caminhao_vazio/logs/screenshots_qualidade_score/08_layout_1920x1080.png

### Validacao
- /health: 200
- /qualidade-score: 200 (autenticado)
- /api/metricas/qualidade-score: 200 JSON
- Comercial preservado
""")
print(f"Checkpoint written: {CHECKPOINT}")
