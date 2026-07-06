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

def calcular_match_transportadora_embarcador(transportadora, embarcador):
    # 1. Compatibilidade de corredor (30%)
    corr_t = normalizar_corredor(transportadora.corredor)
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

def gerar_matches_preditivos(db_session):
    from models import Transportadora, EmbarcadorProvavel, MatchPreditivo
    
    # 1. Apagar matches com status "Sugerido"
    db_session.query(MatchPreditivo).filter(MatchPreditivo.status == "Sugerido").delete()
    db_session.commit()
    
    # 2. Obter todos
    transportadoras = Transportadora.query.all()
    embarcadores = EmbarcadorProvavel.query.all()
    
    # Organizar transportadoras por corredor
    transp_por_corredor = {}
    for t in transportadoras:
        corr = normalizar_corredor(t.corredor)
        if corr:
            if corr not in transp_por_corredor:
                transp_por_corredor[corr] = []
            transp_por_corredor[corr].append(t)
            
    matches_criados = 0
    
    for e in embarcadores:
        corr_e = normalizar_corredor(e.corredor_alvo)
        if not corr_e or corr_e not in transp_por_corredor:
            continue
            
        candidatos = []
        for t in transp_por_corredor[corr_e]:
            res = calcular_match_transportadora_embarcador(t, e)
            if res["score_total"] >= 50:
                candidatos.append((t, res))
                
        # Ordenar e limitar a 20 matches por embarcador
        candidatos.sort(key=lambda x: x[1]["score_total"], reverse=True)
        candidatos = candidatos[:20]
        
        for t, res in candidatos:
            # Evitar duplicidade antes de inserir
            existente = MatchPreditivo.query.filter_by(
                transportadora_id=t.id,
                embarcador_id=e.id,
                corredor=corr_e
            ).first()
            
            if existente:
                continue
                
            match = MatchPreditivo(
                transportadora_id=t.id,
                embarcador_id=e.id,
                corredor=corr_e,
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
            matches_criados += 1
            
    db_session.commit()
    return matches_criados
