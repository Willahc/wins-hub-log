
from models import ProspeccaoLog, db
from sqlalchemy import text

# Minimum sample thresholds for statistical confidence
MIN_TERMINAIS = 300
MIN_RESULTADOS = 50

TAXONOMIA_RESULTADO = {
    "positivos": ["interessado", "proposta_enviada", "negociacao", "fechado"],
    "neutros": ["contato_realizado", "sem_resposta"],
    "negativos": ["sem_interesse", "perdido", "dados_incorretos", "duplicado", "cancelado"],
}

CLASSIFICACAO_FAIXAS = {
    "agir_agora": (60, 100),
    "alta_prioridade": (40, 59),
    "acompanhar": (20, 39),
    "revisar_dados": (0, 19),
}


def diagnosticar_snapshots():
    out = {}

    result = db.session.execute(text("SELECT COUNT(*) as total FROM prospeccao_logs"))
    out["total_logs"] = result.fetchone()[0]

    result = db.session.execute(text("SELECT COUNT(*) as c FROM prospeccao_logs WHERE canal='Resultado'"))
    out["total_resultados"] = result.fetchone()[0]

    result = db.session.execute(text("""SELECT COUNT(*) as c FROM prospeccao_logs 
               WHERE canal='Resultado' AND score_oportunidade_no_momento IS NOT NULL"""))
    out["resultados_com_snapshot"] = result.fetchone()[0]

    result = db.session.execute(text("""SELECT COUNT(*) as c FROM prospeccao_logs 
               WHERE canal='Resultado' AND score_oportunidade_no_momento IS NULL"""))
    out["resultados_sem_snapshot"] = result.fetchone()[0]

    rows = db.session.execute(text("""SELECT resultado, COUNT(*) as cnt FROM prospeccao_logs 
               WHERE canal='Resultado' GROUP BY resultado ORDER BY cnt DESC""")).fetchall()
    out["distribuicao_resultados"] = {r[0]: r[1] for r in rows}

    rows = db.session.execute(text("""SELECT resultado, 
               ROUND(AVG(score_oportunidade_no_momento), 1) as avg_score,
               ROUND(MIN(score_oportunidade_no_momento), 1) as min_score,
               ROUND(MAX(score_oportunidade_no_momento), 1) as max_score,
               COUNT(*) as cnt
               FROM prospeccao_logs 
               WHERE canal='Resultado' AND score_oportunidade_no_momento IS NOT NULL
               GROUP BY resultado ORDER BY avg_score DESC""")).fetchall()
    out["score_por_resultado"] = {r[0]: {"avg": r[1], "min": r[2], "max": r[3], "n": r[4]} for r in rows}

    terminal_list = "','".join(TAXONOMIA_RESULTADO["negativos"] + ["fechado"])
    result = db.session.execute(text(f"""SELECT COUNT(*) as c FROM prospeccao_logs 
               WHERE canal='Resultado' AND resultado IN ('{terminal_list}')"""))
    out["terminais"] = result.fetchone()[0]

    pos_list = "','".join(TAXONOMIA_RESULTADO["positivos"])
    result = db.session.execute(text(f"""SELECT COUNT(*) as c FROM prospeccao_logs 
               WHERE canal='Resultado' AND resultado IN ('{pos_list}')"""))
    out["positivos"] = result.fetchone()[0]

    faixas = {}
    for nome, (lo, hi) in CLASSIFICACAO_FAIXAS.items():
        rows = db.session.execute(text("""SELECT resultado, COUNT(*) as cnt FROM prospeccao_logs 
                   WHERE canal='Resultado' AND score_oportunidade_no_momento >= :lo 
                   AND score_oportunidade_no_momento <= :hi
                   GROUP BY resultado ORDER BY cnt DESC"""), {"lo": lo, "hi": hi}).fetchall()
        faixas[nome] = {r[0]: r[1] for r in rows} if rows else {}
    out["faixas"] = faixas

    rows = db.session.execute(text("""SELECT classificacao_oportunidade_no_momento, COUNT(*) as cnt 
               FROM prospeccao_logs WHERE canal='Resultado' 
               AND classificacao_oportunidade_no_momento IS NOT NULL
               GROUP BY classificacao_oportunidade_no_momento""")).fetchall()
    out["classificacoes"] = {r[0]: r[1] for r in rows}

    out["diagnostico"] = {
        "terminais_suficientes": out["terminais"] >= MIN_TERMINAIS,
        "resultados_suficientes": out["total_resultados"] >= MIN_RESULTADOS,
        "min_terminal_needed": MIN_TERMINAIS,
        "min_resultados_needed": MIN_RESULTADOS,
        "score_variabilidade": _calcular_variabilidade(out["score_por_resultado"]),
    }

    return out


def _calcular_variabilidade(score_por_resultado):
    if len(score_por_resultado) < 2:
        return "insuficiente"
    avgs = [v["avg"] for v in score_por_resultado.values()]
    spread = max(avgs) - min(avgs)
    if spread >= 20:
        return "boa"
    elif spread >= 10:
        return "moderada"
    else:
        return "baixa"


def metricas_calibracao():
    return {"status": "indisponivel", "motivo": "Amostra insuficiente para calibracao"}


def verificar_vazamento_temporal():
    result = db.session.execute(text("""SELECT COUNT(*) as c FROM prospeccao_logs 
               WHERE canal='Resultado' AND score_oportunidade_no_momento IS NULL"""))
    sem_snapshot = result.fetchone()[0]
    result = db.session.execute(text("""SELECT COUNT(*) as c FROM prospeccao_logs 
               WHERE canal='Resultado' AND score_oportunidade_no_momento IS NOT NULL"""))
    com_snapshot = result.fetchone()[0]
    return {
        "com_snapshot": com_snapshot,
        "sem_snapshot": sem_snapshot,
        "ok": sem_snapshot == 0,
    }
