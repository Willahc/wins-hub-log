from models import MatchPreditivo, ProspeccaoLog, db
from sqlalchemy import func, case

def calcular_taxa_resposta(total_prosp, total_resp):
    if not total_prosp:
        return 0.0
    return round((total_resp / total_prosp) * 100, 2)

def calcular_taxa_negociacao(total_prosp, total_neg):
    if not total_prosp:
        return 0.0
    return round((total_neg / total_prosp) * 100, 2)

def calcular_taxa_fechamento(total_prosp, total_fechado):
    if not total_prosp:
        return 0.0
    return round((total_fechado / total_prosp) * 100, 2)

def calcular_metricas_funil():
    total_matches = MatchPreditivo.query.count()
    alta_prioridade = MatchPreditivo.query.filter_by(prioridade="Alta").count()
    
    # Ações de prospecção
    total_prosp = ProspeccaoLog.query.filter(ProspeccaoLog.canal != "Sistema").count()
    enviadas_manualmente = ProspeccaoLog.query.filter(
        ProspeccaoLog.status.in_(["Enviada manualmente", "Respondida", "Sem resposta"]),
        ProspeccaoLog.canal != "Sistema"
    ).count()
    
    # Respostas registradas
    respostas = ProspeccaoLog.query.filter(
        ProspeccaoLog.status == "Respondida",
        ProspeccaoLog.canal != "Sistema"
    ).count()
    
    # Negociações abertas (matches com status Negociando)
    negociacoes = MatchPreditivo.query.filter_by(status="Negociando").count()
    
    # Fechados (matches com status Fechado)
    fechados = MatchPreditivo.query.filter_by(status="Fechado").count()
    
    # Perdidos/Descartados
    perdidos = MatchPreditivo.query.filter_by(status="Descartado").count()
    
    taxa_resp = calcular_taxa_resposta(enviadas_manualmente, respostas)
    taxa_neg = calcular_taxa_negociacao(enviadas_manualmente, negociacoes)
    taxa_fech = calcular_taxa_fechamento(enviadas_manualmente, fechados)
    
    return {
        "total_matches": total_matches,
        "alta_prioridade": alta_prioridade,
        "total_prosp": total_prosp,
        "enviadas_manualmente": enviadas_manualmente,
        "respostas": respostas,
        "negociacoes": negociacoes,
        "fechados": fechados,
        "perdidos": perdidos,
        "taxa_resposta": taxa_resp,
        "taxa_negociacao": taxa_neg,
        "taxa_fechamento": taxa_fech
    }

def calcular_metricas_por_corredor():
    resultados = db.session.query(
        MatchPreditivo.corredor,
        func.count(MatchPreditivo.id).label("matches"),
        func.sum(case((MatchPreditivo.status == "Fechado", 1), else_=0)).label("fechados"),
        func.sum(case((MatchPreditivo.status == "Negociando", 1), else_=0)).label("negociacoes"),
    ).group_by(MatchPreditivo.corredor).all()
    
    prosp_corredor = db.session.query(
        MatchPreditivo.corredor,
        func.count(ProspeccaoLog.id).label("prospeccoes"),
        func.sum(case((ProspeccaoLog.status == "Respondida", 1), else_=0)).label("respostas")
    ).join(ProspeccaoLog).group_by(MatchPreditivo.corredor).all()
    
    p_map = {p[0]: {"prospeccoes": p[1], "respostas": p[2]} for p in prosp_corredor}
    
    metricas = []
    for r in resultados:
        cor = r[0]
        m = r[1]
        f = r[2] or 0
        n = r[3] or 0
        p = p_map.get(cor, {}).get("prospeccoes", 0)
        resp = p_map.get(cor, {}).get("respostas", 0)
        
        taxa_resp = calcular_taxa_resposta(p, resp)
        taxa_fech = calcular_taxa_fechamento(p, f)
        
        metricas.append({
            "corredor": cor,
            "matches": m,
            "prospeccoes": p,
            "respostas": resp,
            "negociacoes": n,
            "fechados": f,
            "taxa_resposta": taxa_resp,
            "taxa_fechamento": taxa_fech
        })
    return metricas

def calcular_metricas_por_setor():
    from models import EmbarcadorProvavel
    resultados = db.session.query(
        EmbarcadorProvavel.setor_predito,
        func.count(MatchPreditivo.id).label("matches"),
        func.sum(case((MatchPreditivo.status == "Fechado", 1), else_=0)).label("fechados"),
        func.sum(case((MatchPreditivo.status == "Negociando", 1), else_=0)).label("negociacoes"),
    ).join(MatchPreditivo, MatchPreditivo.embarcador_id == EmbarcadorProvavel.id).group_by(EmbarcadorProvavel.setor_predito).all()
    
    prosp_setor = db.session.query(
        EmbarcadorProvavel.setor_predito,
        func.count(ProspeccaoLog.id).label("prospeccoes"),
        func.sum(case((ProspeccaoLog.status == "Respondida", 1), else_=0)).label("respostas")
    ).join(MatchPreditivo, MatchPreditivo.embarcador_id == EmbarcadorProvavel.id).join(ProspeccaoLog, ProspeccaoLog.match_id == MatchPreditivo.id).group_by(EmbarcadorProvavel.setor_predito).all()
    
    p_map = {p[0]: {"prospeccoes": p[1], "respostas": p[2]} for p in prosp_setor}
    
    metricas = []
    for r in resultados:
        setor = r[0] or "indefinido"
        m = r[1]
        f = r[2] or 0
        n = r[3] or 0
        p = p_map.get(r[0], {}).get("prospeccoes", 0)
        resp = p_map.get(r[0], {}).get("respostas", 0)
        
        taxa_resp = calcular_taxa_resposta(p, resp)
        taxa_fech = calcular_taxa_fechamento(p, f)
        
        metricas.append({
            "setor": setor,
            "matches": m,
            "prospecções": p,
            "respostas": resp,
            "negociacoes": n,
            "fechados": f,
            "taxa_resposta": taxa_resp,
            "taxa_fechamento": taxa_fech
        })
    return metricas

def calcular_metricas_por_canal():
    resultados = db.session.query(
        ProspeccaoLog.canal,
        func.count(ProspeccaoLog.id).label("total"),
        func.sum(case((ProspeccaoLog.status == "Respondida", 1), else_=0)).label("respostas"),
    ).group_by(ProspeccaoLog.canal).all()
    
    metricas = []
    for r in resultados:
        canal = r[0]
        tot = r[1]
        resp = r[2] or 0
        taxa = calcular_taxa_resposta(tot, resp)
        metricas.append({
            "canal": canal,
            "total": tot,
            "respostas": resp,
            "taxa_resposta": taxa
        })
    return metricas

def calcular_metricas_por_status():
    resultados = db.session.query(
        MatchPreditivo.status,
        func.count(MatchPreditivo.id).label("total")
    ).group_by(MatchPreditivo.status).all()
    
    return {r[0]: r[1] for r in resultados}
