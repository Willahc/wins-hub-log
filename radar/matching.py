from radar.scoring import normalizar_corredor, avaliar_transportadora
from radar.embarcadores import avaliar_embarcador

def classificar_prioridade_match(score):
    if score >= 75:
        return "Alta"
    elif score >= 55:
        return "Média"
    else:
        return "Baixa"

def gerar_justificativa_match(transportadora, embarcador, score):
    eval_t = avaliar_transportadora(transportadora)
    eval_e = avaliar_embarcador(embarcador)
    return (
        f"Match preditivo de {score} pontos no corredor {transportadora.corredor}. "
        f"Transportadora em {transportadora.municipio}/{transportadora.uf} (Setor: {eval_t['setor_predito']}, Carga: {eval_t['tipo_carga_provavel']}) "
        f"combina com a demanda do Embarcador {embarcador.razao_social or embarcador.nome_fantasia} de {embarcador.cidade}/{embarcador.uf} "
        f"(Setor: {eval_e['setor_predito']}, Carga: {eval_e['tipo_carga_provavel']})."
    )

def calcular_match_transportadora_embarcador(transportadora, embarcador, preferir_transportadoras_puras=False):
    # 1. Compatibilidade de corredor (30%)
    corr_t = normalizar_corredor(transportadora.corredor_alvo or transportadora.corredor)
    corr_e = normalizar_corredor(embarcador.corredor_alvo)
    score_corredor = 100 if (corr_t == corr_e and corr_t != "") else 0

    # 2. Localização / Cidade / UF (20%)
    cidade_t = (transportadora.municipio or "").upper().strip()
    cidade_e = (embarcador.cidade or "").upper().strip()
    uf_t = (transportadora.uf or "").upper().strip()
    uf_e = (embarcador.uf or "").upper().strip()
    
    if cidade_t == cidade_e and cidade_t != "":
        score_localizacao = 100
    elif uf_t == uf_e and uf_t != "":
        score_localizacao = 70
    else:
        score_localizacao = 40

    # 3. Compatibilidade Setor / Tipo de Carga (20% - sendo 10% setor e 10% carga/carroceria)
    eval_t = avaliar_transportadora(transportadora)
    eval_e = avaliar_embarcador(embarcador)
    
    setor_t = eval_t["setor_predito"]
    setor_e = eval_e["setor_predito"]
    
    if setor_t == setor_e and setor_t != "indefinido":
        score_setor = 100
    else:
        score_setor = 45
        
    carg_t = eval_t["carrocerias_provaveis"].lower()
    carg_e = eval_e["carrocerias_provaveis"].lower()
    
    comum = False
    for item in ["bau", "sider", "refrigerado", "graneleiro", "carga seca"]:
        if item in carg_t and item in carg_e:
            comum = True
            break
            
    score_carga = 100 if comum else 50

    # 4. Compatibilidade CRM (10%)
    crm_t = transportadora.status_crm or "nao_contatada"
    crm_e = embarcador.status_crm or "nao_contatada"
    
    if crm_t == "descartada" or crm_e == "descartada":
        score_crm = 0
    elif crm_t in ["cliente", "negociando"] and crm_e in ["cliente", "negociando"]:
        score_crm = 100
    elif crm_t in ["cliente", "negociando", "interessada", "contatada"] or crm_e in ["cliente", "negociando", "interessada", "contatada"]:
        score_crm = 80
    else:
        score_crm = 60

    # 5. Scores Individuais (10% + 10%)
    radar_score = eval_t["score_total"]
    demanda_score = eval_e["score_total"]

    # Calcular Score Match total
    score_total = (
        score_corredor * 0.30
        + score_localizacao * 0.20
        + score_setor * 0.10
        + score_carga * 0.10
        + score_crm * 0.10
        + radar_score * 0.10
        + demanda_score * 0.10
    )
    score_total = round(score_total, 2)

    if preferir_transportadoras_puras:
        razao = (transportadora.razao_social or "").upper()
        fantasia = (transportadora.nome_fantasia or "").upper()
        nome_rntrc = (transportadora.nome_rntrc or "").upper()
        
        termos_bonus = ["TRANSPORT", "TRANSPORTADORA", "TRANSPORTES", "LOGISTICA", "LOG", "CARGAS", "FRETES", "EXPRESSO", "RODOVIARIO"]
        termos_penalizacao = ["DISTRIBUIDORA DE ALIMENTOS", "COMERCIO", "ALIMENTOS", "BEBIDAS", "MERCADO", "RESTAURANTE", "PADARIA"]
        
        has_bonus = any(t_bon in razao or t_bon in fantasia or t_bon in nome_rntrc for t_bon in termos_bonus)
        has_penalizacao = any(t_pen in razao or t_pen in fantasia or t_pen in nome_rntrc for t_pen in termos_penalizacao)
        
        if has_bonus:
            score_total += 15
        if has_penalizacao:
            score_total -= 25
            
        score_total = max(0.0, min(100.0, score_total))
        score_total = round(score_total, 2)

    prioridade = classificar_prioridade_match(score_total)
    justificativa = gerar_justificativa_match(transportadora, embarcador, score_total)

    return {
        "score_total": score_total,
        "prioridade": prioridade,
        "score_corredor": score_corredor,
        "score_localizacao": score_localizacao,
        "score_setor": score_setor,
        "score_carga": score_carga,
        "score_crm": score_crm,
        "justificativa": justificativa
    }

def gerar_matches_preditivos(
    db_session,
    corredor=None,
    prioridade_minima=None,
    limite_matches=None,
    limite_transportadoras=None,
    limite_embarcadores=None,
    max_matches_por_embarcador=10,
    max_matches_por_transportadora=30,
    preferir_transportadoras_puras=False,
    replace=False
):
    from models import Transportadora, EmbarcadorProvavel, MatchPreditivo
    from collections import Counter
    from sqlalchemy import func
    
    if not corredor:
        raise ValueError("O parâmetro 'corredor' é obrigatório para evitar cruzamentos globais ineficientes.")
        
    corredor_alvo_normalizado = normalizar_corredor(corredor)
    
    # 1. Se replace=True ou por padrão, apagar matches com status "Sugerido" apenas do corredor especificado
    # (Se o usuário quer gerar matches novos, os sugeridos antigos do corredor são limpos)
    db_session.query(MatchPreditivo).filter(
        MatchPreditivo.status == "Sugerido",
        MatchPreditivo.corredor == corredor_alvo_normalizado
    ).delete(synchronize_session=False)
    db_session.commit()
    
    # 2. Obter embarcadores filtrados por corredor e prioridade
    query_emb = db_session.query(EmbarcadorProvavel).filter(
        EmbarcadorProvavel.corredor_alvo == corredor_alvo_normalizado
    )
    
    if prioridade_minima:
        if prioridade_minima == "Alta":
            query_emb = query_emb.filter(EmbarcadorProvavel.prioridade == "Alta")
        elif prioridade_minima == "Média":
            query_emb = query_emb.filter(EmbarcadorProvavel.prioridade.in_(["Alta", "Média"]))
        elif prioridade_minima == "Baixa":
            query_emb = query_emb.filter(EmbarcadorProvavel.prioridade.in_(["Alta", "Média", "Baixa"]))
            
    # Ordenar por maior score de demanda primeiro
    query_emb = query_emb.order_by(EmbarcadorProvavel.score_demanda.desc(), EmbarcadorProvavel.razao_social)
    
    if limite_embarcadores:
        query_emb = query_emb.limit(limite_embarcadores)
        
    embarcadores = query_emb.all()
    
    # 3. Obter transportadoras do mesmo corredor
    query_transp = db_session.query(Transportadora).filter(
        (Transportadora.corredor_alvo == corredor_alvo_normalizado) |
        (Transportadora.corredor == corredor_alvo_normalizado)
    )
    
    if limite_transportadoras:
        query_transp = query_transp.limit(limite_transportadoras)
        
    transportadoras = query_transp.all()
    
    print(f"Buscando matches no corredor {corredor_alvo_normalizado}:")
    print(f"  Embarcadores carregados: {len(embarcadores)}")
    print(f"  Transportadoras carregadas: {len(transportadoras)}")
    
    # Inicializar contador de matches por transportadora usando os matches já existentes no banco que NÃO são "Sugerido"
    existentes_crm = db_session.query(MatchPreditivo.transportadora_id, func.count(MatchPreditivo.id))\
        .filter(MatchPreditivo.corredor == corredor_alvo_normalizado)\
        .filter(MatchPreditivo.status != "Sugerido")\
        .group_by(MatchPreditivo.transportadora_id).all()
        
    matches_por_transportadora = Counter({t_id: count for t_id, count in existentes_crm})
    
    matches_gravados = 0
    embarcadores_com_match = set()
    transportadoras_com_match = set()
    
    # Rastrear repetições para o relatório final
    rep_embarcadores = Counter()
    rep_transportadoras = Counter()
    
    mapa_nomes_emb = {}
    mapa_nomes_transp = {}
    
    for e in embarcadores:
        if limite_matches and matches_gravados >= limite_matches:
            print(f"  Limite de matches atingido ({limite_matches}). Parando.")
            break
            
        candidatos = []
        for t in transportadoras:
            res = calcular_match_transportadora_embarcador(
                t, e, preferir_transportadoras_puras=preferir_transportadoras_puras
            )
            if res["score_total"] >= 50:
                candidatos.append((t, res))
                
        # Ordenar candidatos do melhor score para o pior
        candidatos.sort(key=lambda x: x[1]["score_total"], reverse=True)
        
        # Selecionar candidatos respeitando max_matches_por_embarcador e max_matches_por_transportadora
        candidatos_selecionados = []
        for t, res in candidatos:
            if len(candidatos_selecionados) >= max_matches_por_embarcador:
                break
                
            # Verificar limite por transportadora
            if matches_por_transportadora[t.id] >= max_matches_por_transportadora:
                continue
                
            candidatos_selecionados.append((t, res))
            matches_por_transportadora[t.id] += 1
            
        # Gravar os matches selecionados
        for t, res in candidatos_selecionados:
            if limite_matches and matches_gravados >= limite_matches:
                break
                
            # Evitar duplicidade antes de inserir, ou atualizar caso exista
            existente = db_session.query(MatchPreditivo).filter_by(
                transportadora_id=t.id,
                embarcador_id=e.id,
                corredor=corredor_alvo_normalizado
            ).first()
            
            if existente:
                existente.score_match = res["score_total"]
                existente.prioridade = res["prioridade"]
                existente.score_corredor = res["score_corredor"]
                existente.score_localizacao = res["score_localizacao"]
                existente.score_setor = res["score_setor"]
                existente.score_carga = res["score_carga"]
                existente.score_crm = res["score_crm"]
                existente.justificativa = res["justificativa"]
                existente.cidade_origem = t.municipio
                existente.uf_origem = t.uf
                existente.cidade_destino = e.cidade
                existente.uf_destino = e.uf
            else:
                match = MatchPreditivo(
                    transportadora_id=t.id,
                    embarcador_id=e.id,
                    corredor=corredor_alvo_normalizado,
                    cidade_origem=t.municipio,
                    uf_origem=t.uf,
                    cidade_destino=e.cidade,
                    uf_destino=e.uf,
                    score_match=res["score_total"],
                    prioridade=res["prioridade"],
                    score_corredor=res["score_corredor"],
                    score_localizacao=res["score_localizacao"],
                    score_setor=res["score_setor"],
                    score_carga=res["score_carga"],
                    score_crm=res["score_crm"],
                    justificativa=res["justificativa"],
                    status="Sugerido"
                )
                db_session.add(match)
                
            matches_gravados += 1
            embarcadores_com_match.add(e.id)
            transportadoras_com_match.add(t.id)
            
            # Registrar nomes para o relatorio
            nome_emb = e.razao_social or e.nome_fantasia or "Embarcador Desconhecido"
            nome_transp = t.razao_social or t.nome_rntrc or t.nome_fantasia or "Transportadora Desconhecida"
            mapa_nomes_emb[e.id] = nome_emb
            mapa_nomes_transp[t.id] = nome_transp
            
            rep_embarcadores[e.id] += 1
            rep_transportadoras[t.id] += 1
            
            # Commit por lote
            if matches_gravados % 200 == 0:
                db_session.commit()
                
    db_session.commit()
    
    # Calcular estatisticas para o relatorio
    total_emb = len(embarcadores_com_match)
    media_por_emb = round(matches_gravados / total_emb, 2) if total_emb > 0 else 0.0
    
    top_10_emb = [(mapa_nomes_emb.get(eid, f"ID {eid}"), count) for eid, count in rep_embarcadores.most_common(10)]
    top_10_transp = [(mapa_nomes_transp.get(tid, f"ID {tid}"), count) for tid, count in rep_transportadoras.most_common(10)]
    
    return {
        "total_matches": matches_gravados,
        "embarcadores_unicos": total_emb,
        "transportadoras_unicas": len(transportadoras_com_match),
        "media_por_embarcador": media_por_emb,
        "top_embarcadores": top_10_emb,
        "top_transportadoras": top_10_transp
    }
