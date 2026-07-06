from radar.cnae_rules import CNAE_LOGISTICO_RULES


def normalizar_texto(valor):
    if not valor:
        return ""
    return str(valor).lower().strip()


def normalizar_corredor(corredor):
    if not corredor:
        return ""
    return str(corredor).replace("→", "->").strip()


def classificar_setor_por_texto(texto):
    texto_norm = normalizar_texto(texto)

    melhor = None

    for setor, regra in CNAE_LOGISTICO_RULES.items():
        for keyword in regra["keywords"]:
            if keyword.lower() in texto_norm:
                candidato = {
                    "setor": setor,
                    "tipo_carga": regra["tipo_carga"],
                    "carrocerias": regra["carrocerias"],
                    "score_cnae": regra["peso_score"],
                }

                if melhor is None or candidato["score_cnae"] > melhor["score_cnae"]:
                    melhor = candidato

    if melhor:
        return melhor

    return {
        "setor": "indefinido",
        "tipo_carga": "não identificado",
        "carrocerias": [],
        "score_cnae": 20,
    }


def calcular_score_retorno(
    percentual_retorno_vazio=0,
    score_cnae=0,
    score_cidade=50,
    score_carga=50,
    score_crm=10,
    tem_contato=False,
    tem_historico=False,
):
    score_contato = 100 if tem_contato else 0
    score_historico = 100 if tem_historico else 0

    total = (
        percentual_retorno_vazio * 0.30
        + score_cnae * 0.25
        + score_cidade * 0.15
        + score_carga * 0.10
        + score_crm * 0.10
        + score_contato * 0.05
        + score_historico * 0.05
    )

    return round(total, 2)


def avaliar_transportadora(transportadora):
    from config import Config
    from radar.demanda import gerar_justificativa

    # 1. Normalizar corredor e obter percentual de retorno
    corredor_norm = normalizar_corredor(transportadora.corredor)
    
    # Mapeamento de percentual por corredor
    MAPA_RETORNO = {
        "SC->SP": 84.3,
        "SP->DF": 79.2,
        "MS->PR": 77.7,
        "MG->SP": 70.0
    }
    pct_retorno = MAPA_RETORNO.get(corredor_norm, 50.0)

    # 2. CNAE / Setor
    texto_classificacao = f"{transportadora.razao_social or ''} {transportadora.nome_fantasia or ''} {transportadora.cnaes_secundarios or ''}"
    setor_info = classificar_setor_por_texto(texto_classificacao)
    
    score_cnae = setor_info["score_cnae"]
    if transportadora.tem_cnae_frete and score_cnae < 75:
        score_cnae = 75 # Garantia mínima para quem tem CNAE de frete
        
    setor_predito = setor_info["setor"]
    tipo_carga_provavel = setor_info["tipo_carga"]
    carrocerias = setor_info["carrocerias"]
    carrocerias_str = ", ".join(carrocerias) if carrocerias else "não identificada"

    # 3. Cidade / Polo logístico
    score_cidade = 40
    municipio_upper = (transportadora.municipio or "").upper().strip()
    if corredor_norm in Config.CORREDORES:
        corr_info = Config.CORREDORES[corredor_norm]
        if municipio_upper in [m.upper() for m in corr_info.get("municipios", [])]:
            score_cidade = 100
        elif transportadora.uf == corr_info.get("uf_origem"):
            score_cidade = 60

    # 4. Tipo de carga / Carroceria
    score_carga = 40
    if carrocerias:
        if any(c in ["bau", "sider"] for c in carrocerias):
            score_carga = 100
        elif any(c in ["refrigerado", "graneleiro", "carga seca"] for c in carrocerias):
            score_carga = 80

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
    status_crm = transportadora.status_crm or "nao_contatada"
    score_crm = CRM_SCORES.get(status_crm, 10)

    # 6. Contato
    tem_contato = bool(transportadora.telefone or transportadora.email)

    # 7. Histórico
    tem_historico = bool(transportadora.notas)

    # Calcular Score Retorno
    score_total = calcular_score_retorno(
        percentual_retorno_vazio=pct_retorno,
        score_cnae=score_cnae,
        score_cidade=score_cidade,
        score_carga=score_carga,
        score_crm=score_crm,
        tem_contato=tem_contato,
        tem_historico=tem_historico
    )

    # Prioridade
    if score_total >= 75:
        prioridade = "Alta"
    elif score_total >= 50:
        prioridade = "Média"
    else:
        prioridade = "Baixa"

    # Justificativa
    justificativa = gerar_justificativa(
        corredor=transportadora.corredor or "N/A",
        cidade=transportadora.municipio or "N/A",
        setor=setor_predito,
        tipo_carga=tipo_carga_provavel,
        score=score_total
    )

    return {
        "score_total": score_total,
        "setor_predito": setor_predito,
        "tipo_carga_provavel": tipo_carga_provavel,
        "carrocerias_provaveis": carrocerias_str,
        "prioridade": prioridade,
        "justificativa": justificativa
    }
