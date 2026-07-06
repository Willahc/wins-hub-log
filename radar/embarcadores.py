from config import Config
from radar.scoring import classificar_setor_por_texto, normalizar_corredor

def classificar_prioridade(score):
    if score >= 75:
        return "Alta"
    elif score >= 50:
        return "Média"
    else:
        return "Baixa"

def gerar_justificativa_embarcador(embarcador, score, setor, tipo_carga):
    return (
        f"Embarcador com demanda provável no corredor {embarcador.corredor_alvo or 'N/A'}. "
        f"Origem provável: {embarcador.origem_provavel or 'N/A'} -> Destino provável: {embarcador.destino_provavel or 'N/A'}. "
        f"Setor predito: {setor}, Carga provável: {tipo_carga}. "
        f"Score preditivo de demanda: {score}."
    )

def avaliar_embarcador(embarcador):
    # 1. Normalizar corredor e obter percentual de retorno
    corredor_norm = normalizar_corredor(embarcador.corredor_alvo)
    MAPA_RETORNO = {
        "SC->SP": 84.3,
        "SP->DF": 79.2,
        "MS->PR": 77.7,
        "MG->SP": 70.0
    }
    pct_retorno = MAPA_RETORNO.get(corredor_norm, 50.0)

    # 2. CNAE / Setor
    texto_classificacao = f"{embarcador.razao_social or ''} {embarcador.nome_fantasia or ''} {embarcador.cnae_descricao or ''}"
    setor_info = classificar_setor_por_texto(texto_classificacao)
    score_cnae = setor_info["score_cnae"]
    setor_predito = setor_info["setor"]
    tipo_carga_provavel = setor_info["tipo_carga"]
    carrocerias = setor_info["carrocerias"]
    carrocerias_str = ", ".join(carrocerias) if carrocerias else "não identificada"

    # 3. Cidade / Polo logístico
    score_cidade = 40
    cidade_upper = (embarcador.cidade or "").upper().strip()
    if corredor_norm in Config.CORREDORES:
        corr_info = Config.CORREDORES[corredor_norm]
        if cidade_upper in [m.upper() for m in corr_info.get("municipios", [])]:
            score_cidade = 100
        elif embarcador.uf == corr_info.get("uf_origem"):
            score_cidade = 60

    # 4. Compatibilidade Rota Origem/Destino
    score_rota = 50
    if corredor_norm in Config.CORREDORES:
        corr_info = Config.CORREDORES[corredor_norm]
        uf_origem = corr_info.get("uf_origem")
        # Para corredores tipo "SP->DF", o destino é a UF final
        partes = corredor_norm.split("->")
        uf_destino = partes[1] if len(partes) > 1 else ""
        
        origem_ok = False
        destino_ok = False
        
        if embarcador.origem_provavel and uf_origem in embarcador.origem_provavel.upper():
            origem_ok = True
        if embarcador.destino_provavel and uf_destino in embarcador.destino_provavel.upper():
            destino_ok = True
            
        if origem_ok and destino_ok:
            score_rota = 100
        elif origem_ok or destino_ok:
            score_rota = 75

    # 5. Status CRM
    CRM_SCORES = {
        "cliente": 100,
        "negociando": 85,
        "interessada": 75,
        "contatada": 55,
        "tentativa": 35,
        "nao_contatada": 10,
        "descartada": 0
    }
    status_crm = embarcador.status_crm or "nao_contatada"
    score_crm = CRM_SCORES.get(status_crm, 10)

    # 6. Presença de Contato
    tem_contato = bool(embarcador.telefone or embarcador.email or embarcador.site)
    score_contato = 100 if tem_contato else 0

    # 7. Histórico / Notas
    tem_historico = bool(embarcador.notas)
    score_historico = 100 if tem_historico else 0

    # Calcular Score
    score_total = (
        pct_retorno * 0.30
        + score_cnae * 0.25
        + score_cidade * 0.15
        + score_rota * 0.10
        + score_crm * 0.10
        + score_contato * 0.05
        + score_historico * 0.05
    )
    score_total = round(score_total, 2)

    prioridade = classificar_prioridade(score_total)
    justificativa = gerar_justificativa_embarcador(embarcador, score_total, setor_predito, tipo_carga_provavel)

    return {
        "score_total": score_total,
        "setor_predito": setor_predito,
        "tipo_carga_provavel": tipo_carga_provavel,
        "carrocerias_provaveis": carrocerias_str,
        "prioridade": prioridade,
        "justificativa": justificativa
    }
