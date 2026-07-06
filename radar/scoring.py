from radar.cnae_rules import CNAE_LOGISTICO_RULES


def normalizar_texto(valor):
    if not valor:
        return ""
    return str(valor).lower().strip()


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
