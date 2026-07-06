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
    from sqlalchemy import func, text
    from sqlalchemy.exc import OperationalError
    import time
    import radar.matching as matching_mod
    
    if not corredor:
        raise ValueError("O parâmetro 'corredor' é obrigatório para evitar cruzamentos globais ineficientes.")
        
    corredor_alvo_normalizado = normalizar_corredor(corredor)
    
    # Executar PRAGMAs antes de operações pesadas
    try:
        db_session.execute(text("PRAGMA busy_timeout=60000"))
        db_session.execute(text("PRAGMA journal_mode=WAL"))
        db_session.execute(text("PRAGMA synchronous=NORMAL"))
    except Exception as e:
        print(f"  [Aviso] Falha ao configurar PRAGMAs no SQLite: {e}")

    retries_lock = 0
    deleted_count = 0

    # Guardar funções originais para caching
    orig_avaliar_transp = matching_mod.avaliar_transportadora
    orig_avaliar_emb = matching_mod.avaliar_embarcador
    
    cache_t = {}
    cache_e = {}
    
    def cached_avaliar_transp(t):
        if t.id not in cache_t:
            cache_t[t.id] = orig_avaliar_transp(t)
        return cache_t[t.id]
        
    def cached_avaliar_emb(e):
        if e.id not in cache_e:
            cache_e[e.id] = orig_avaliar_emb(e)
        return cache_e[e.id]
        
    # Aplicar monkey-patch temporário
    matching_mod.avaliar_transportadora = cached_avaliar_transp
    matching_mod.avaliar_embarcador = cached_avaliar_emb

    try:
        # 1. Se replace=True, apagar matches com status "Sugerido" apenas do corredor especificado
        if replace:
            max_retries = 5
            retry_delay = 1.0
            for attempt in range(max_retries):
                try:
                    # Contar quantos serão deletados para logar claramente
                    deleted_count = db_session.query(MatchPreditivo).filter(
                        MatchPreditivo.status == "Sugerido",
                        MatchPreditivo.corredor == corredor_alvo_normalizado
                    ).count()
                    
                    db_session.query(MatchPreditivo).filter(
                        MatchPreditivo.status == "Sugerido",
                        MatchPreditivo.corredor == corredor_alvo_normalizado
                    ).delete(synchronize_session=False)
                    db_session.commit()
                    print(f"  [Deletado] Apagados {deleted_count} matches antigos com status 'Sugerido' do corredor {corredor_alvo_normalizado}.")
                    break
                except OperationalError as e:
                    db_session.rollback()
                    if "locked" in str(e).lower() and attempt < max_retries - 1:
                        retries_lock += 1
                        print(f"  [Aviso] Banco travado ao deletar (tentativa {attempt + 1}/{max_retries}). Retentando em {retry_delay}s...")
                        time.sleep(retry_delay)
                        retry_delay *= 2
                    else:
                        raise e
        else:
            print("  [Deletado] Replace desativado. Nenhum match antigo foi apagado.")
        
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
        
        # Pré-processar transportadoras (evita fazer milhões de chamadas string, parsing e normalização no loop interno)
        print("  Pré-processando dados das transportadoras...")
        t_infos = {}
        carr_validas = {"bau", "sider", "refrigerado", "graneleiro", "carga seca"}
        for t in transportadoras:
            corr_t = normalizar_corredor(t.corredor_alvo or t.corredor)
            cidade_t = (t.municipio or "").upper().strip()
            uf_t = (t.uf or "").upper().strip()
            eval_t = cached_avaliar_transp(t)
            
            bonus_puras = 0.0
            if preferir_transportadoras_puras:
                razao = (t.razao_social or "").upper()
                fantasia = (t.nome_fantasia or "").upper()
                nome_rntrc = (t.nome_rntrc or "").upper()
                
                termos_bonus = ["TRANSPORT", "TRANSPORTADORA", "TRANSPORTES", "LOGISTICA", "LOG", "CARGAS", "FRETES", "EXPRESSO", "RODOVIARIO"]
                termos_penalizacao = ["DISTRIBUIDORA DE ALIMENTOS", "COMERCIO", "ALIMENTOS", "BEBIDAS", "MERCADO", "RESTAURANTE", "PADARIA"]
                
                has_bonus = any(t_bon in razao or t_bon in fantasia or t_bon in nome_rntrc for t_bon in termos_bonus)
                has_penalizacao = any(t_pen in razao or t_pen in fantasia or t_pen in nome_rntrc for t_pen in termos_penalizacao)
                
                if has_bonus:
                    bonus_puras += 15
                if has_penalizacao:
                    bonus_puras -= 25

            t_carr_str = eval_t["carrocerias_provaveis"].lower()
            t_carr_set = {item for item in carr_validas if item in t_carr_str}

            t_infos[t.id] = {
                "corr": corr_t,
                "cidade": cidade_t,
                "uf": uf_t,
                "setor": eval_t["setor_predito"],
                "carrocerias_set": t_carr_set,
                "status_crm": t.status_crm or "nao_contatada",
                "radar_contrib": eval_t["score_total"] * 0.10,
                "bonus_puras": bonus_puras
            }
            
        # Pré-processar embarcadores
        print("  Pré-processando dados dos embarcadores...")
        e_infos = {}
        for e in embarcadores:
            corr_e = normalizar_corredor(e.corredor_alvo)
            cidade_e = (e.cidade or "").upper().strip()
            uf_e = (e.uf or "").upper().strip()
            eval_e = cached_avaliar_emb(e)
            
            e_carr_str = eval_e["carrocerias_provaveis"].lower()
            e_carr_set = {item for item in carr_validas if item in e_carr_str}

            e_infos[e.id] = {
                "corr": corr_e,
                "cidade": cidade_e,
                "uf": uf_e,
                "setor": eval_e["setor_predito"],
                "carrocerias_set": e_carr_set,
                "status_crm": e.status_crm or "nao_contatada",
                "demanda_contrib": eval_e["score_total"] * 0.10
            }

        # Tabela de compatibilidade CRM com cache lazy
        crm_lookup = {}
        def get_crm_contrib(crm_t, crm_e):
            key = (crm_t, crm_e)
            if key not in crm_lookup:
                if crm_t == "descartada" or crm_e == "descartada":
                    crm_lookup[key] = 0.0
                elif crm_t in ["cliente", "negociando"] and crm_e in ["cliente", "negociando"]:
                    crm_lookup[key] = 10.0
                elif crm_t in ["cliente", "negociando", "interessada", "contatada"] or crm_e in ["cliente", "negociando", "interessada", "contatada"]:
                    crm_lookup[key] = 8.0
                else:
                    crm_lookup[key] = 6.0
            return crm_lookup[key]

        # Inicializar contador de matches por transportadora usando os matches já existentes no banco que NÃO são "Sugerido"
        existentes_crm = db_session.query(MatchPreditivo.transportadora_id, func.count(MatchPreditivo.id))\
            .filter(MatchPreditivo.corredor == corredor_alvo_normalizado)\
            .filter(MatchPreditivo.status != "Sugerido")\
            .group_by(MatchPreditivo.transportadora_id).all()
            
        matches_por_transportadora = Counter({t_id: count for t_id, count in existentes_crm})
        
        # Carregar todos os matches existentes no corredor para cache em memória
        print("  Carregando matches existentes no corredor para cache em memória...")
        existentes_dict = {}
        for m in db_session.query(MatchPreditivo).filter_by(corredor=corredor_alvo_normalizado).all():
            existentes_dict[(m.transportadora_id, m.embarcador_id)] = m
        
        matches_gravados = 0
        embarcadores_com_match = set()
        transportadoras_com_match = set()
        
        # Rastrear repetições para o relatório final
        rep_embarcadores = Counter()
        rep_transportadoras = Counter()
        
        mapa_nomes_emb = {}
        mapa_nomes_transp = {}
        
        # Processar em lotes menores para evitar travamentos longos do banco
        batch_size = 50
        num_embarcadores = len(embarcadores)
        
        for start_idx in range(0, num_embarcadores, batch_size):
            if limite_matches and matches_gravados >= limite_matches:
                print(f"  Limite de matches atingido ({limite_matches}). Parando.")
                break
                
            lote_emb = embarcadores[start_idx : start_idx + batch_size]
            
            max_retries = 5
            retry_delay = 1.0
            for attempt in range(max_retries):
                # Backup do contador de matches por transportadora
                matches_por_transportadora_backup = matches_por_transportadora.copy()
                try:
                    lote_matches_gravados = 0
                    lote_embarcadores_com_match = set()
                    lote_transportadoras_com_match = set()
                    lote_rep_embarcadores = Counter()
                    lote_rep_transportadoras = Counter()
                    lote_mapa_nomes_emb = {}
                    lote_mapa_nomes_transp = {}
    
                    for e in lote_emb:
                        if limite_matches and (matches_gravados + lote_matches_gravados) >= limite_matches:
                            break
                            
                        e_info = e_infos[e.id]
                        candidatos = []
                        for t in transportadoras:
                            t_info = t_infos[t.id]
                            
                            # 1. Compatibilidade de corredor (30%)
                            # Como ambos foram carregados filtrados pelo mesmo corredor_alvo_normalizado, score_corredor é sempre 100.
                            score_corredor = 100.0
                            
                            # 2. Localização / Cidade / UF (20%)
                            if t_info["cidade"] == e_info["cidade"] and t_info["cidade"] != "":
                                score_localizacao_contrib = 20.0
                                score_localizacao = 100.0
                            elif t_info["uf"] == e_info["uf"] and t_info["uf"] != "":
                                score_localizacao_contrib = 14.0
                                score_localizacao = 70.0
                            else:
                                score_localizacao_contrib = 8.0
                                score_localizacao = 40.0

                            # 3. Compatibilidade Setor / Tipo de Carga (20% - sendo 10% setor e 10% carga/carroceria)
                            if t_info["setor"] == e_info["setor"] and t_info["setor"] != "indefinido":
                                score_setor_contrib = 10.0
                                score_setor = 100.0
                            else:
                                score_setor_contrib = 4.5
                                score_setor = 45.0
                            
                            comum = bool(t_info["carrocerias_set"] & e_info["carrocerias_set"])
                            if comum:
                                score_carga_contrib = 10.0
                                score_carga = 100.0
                            else:
                                score_carga_contrib = 5.0
                                score_carga = 50.0

                            # 4. Compatibilidade CRM (10%)
                            crm_t = t_info["status_crm"]
                            crm_e = e_info["status_crm"]
                            score_crm_contrib = get_crm_contrib(crm_t, crm_e)
                            score_crm = score_crm_contrib * 10.0

                            # 5. Scores Individuais (10% + 10%)
                            score_total = (
                                30.0 # score_corredor * 0.30
                                + score_localizacao_contrib
                                + score_setor_contrib
                                + score_carga_contrib
                                + score_crm_contrib
                                + t_info["radar_contrib"]
                                + e_info["demanda_contrib"]
                            )
                            score_total = round(score_total, 2)

                            if preferir_transportadoras_puras:
                                score_total += t_info["bonus_puras"]
                                score_total = max(0.0, min(100.0, score_total))
                                score_total = round(score_total, 2)

                            if score_total >= 50:
                                candidatos.append((t, score_total, score_corredor, score_localizacao, score_setor, score_carga, score_crm))
                                
                        # Ordenar candidatos do melhor score para o pior
                        candidatos.sort(key=lambda x: x[1], reverse=True)
                        
                        # Selecionar candidatos respeitando max_matches_por_embarcador e max_matches_por_transportadora
                        candidatos_selecionados = []
                        for t, score_total, score_corredor, score_localizacao, score_setor, score_carga, score_crm in candidatos:
                            if len(candidatos_selecionados) >= max_matches_por_embarcador:
                                break
                                
                            # Verificar limite por transportadora
                            if matches_por_transportadora[t.id] >= max_matches_por_transportadora:
                                continue
                                
                            candidatos_selecionados.append((t, score_total, score_corredor, score_localizacao, score_setor, score_carga, score_crm))
                            matches_por_transportadora[t.id] += 1
                            
                        # Gravar os matches selecionados
                        for t, score_total, score_corredor, score_localizacao, score_setor, score_carga, score_crm in candidatos_selecionados:
                            if limite_matches and (matches_gravados + lote_matches_gravados) >= limite_matches:
                                break
                                
                            # Gerar justificativa e prioridade completas apenas para quem foi de fato selecionado
                            prioridade = classificar_prioridade_match(score_total)
                            justificativa = gerar_justificativa_match(t, e, score_total)
                            
                            # Evitar duplicidade antes de inserir, ou atualizar caso exista
                            existente = existentes_dict.get((t.id, e.id))
                            
                            if existente:
                                existente.score_match = score_total
                                existente.prioridade = prioridade
                                existente.score_corredor = score_corredor
                                existente.score_localizacao = score_localizacao
                                existente.score_setor = score_setor
                                existente.score_carga = score_carga
                                existente.score_crm = score_crm
                                existente.justificativa = justificativa
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
                                    score_match=score_total,
                                    prioridade=prioridade,
                                    score_corredor=score_corredor,
                                    score_localizacao=score_localizacao,
                                    score_setor=score_setor,
                                    score_carga=score_carga,
                                    score_crm=score_crm,
                                    justificativa=justificativa,
                                    status="Sugerido"
                                )
                                db_session.add(match)
                                existentes_dict[(t.id, e.id)] = match
                                
                            lote_matches_gravados += 1
                            lote_embarcadores_com_match.add(e.id)
                            lote_transportadoras_com_match.add(t.id)
                            
                            # Registrar nomes para o relatorio
                            nome_emb = e.razao_social or e.nome_fantasia or "Embarcador Desconhecido"
                            nome_transp = t.razao_social or t.nome_rntrc or t.nome_fantasia or "Transportadora Desconhecida"
                            lote_mapa_nomes_emb[e.id] = nome_emb
                            lote_mapa_nomes_transp[t.id] = nome_transp
                            
                            lote_rep_embarcadores[e.id] += 1
                            lote_rep_transportadoras[t.id] += 1
    
                    # Commit do lote
                    db_session.commit()
                    
                    # Integrar dados do lote com os totais de sucesso
                    matches_gravados += lote_matches_gravados
                    embarcadores_com_match.update(lote_embarcadores_com_match)
                    transportadoras_com_match.update(lote_transportadoras_com_match)
                    rep_embarcadores.update(lote_rep_embarcadores)
                    rep_transportadoras.update(lote_rep_transportadoras)
                    mapa_nomes_emb.update(lote_mapa_nomes_emb)
                    mapa_nomes_transp.update(lote_mapa_nomes_transp)
                    
                    print(f"  [Lote] Gravou {lote_matches_gravados} matches (Total: {matches_gravados}/{limite_matches or 'Sem Limite'})")
                    break
                    
                except OperationalError as e:
                    db_session.rollback()
                    matches_por_transportadora = matches_por_transportadora_backup
                    if "locked" in str(e).lower() and attempt < max_retries - 1:
                        retries_lock += 1
                        print(f"  [Aviso] Banco travado ao commitar lote (tentativa {attempt + 1}/{max_retries}). Retentando em {retry_delay}s...")
                        time.sleep(retry_delay)
                        retry_delay *= 2
                    else:
                        raise e
    finally:
        # Restaurar monkey-patch temporário
        matching_mod.avaliar_transportadora = orig_avaliar_transp
        matching_mod.avaliar_embarcador = orig_avaliar_emb
                    
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
        "top_transportadoras": top_10_transp,
        "deleted_count": deleted_count,
        "retries_lock": retries_lock
    }
