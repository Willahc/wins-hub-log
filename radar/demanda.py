def gerar_justificativa(corredor, cidade, setor, tipo_carga, score):
    return (
        f"Corredor {corredor} com alta assimetria de retorno vazio. "
        f"Empresa localizada em {cidade}, setor provável {setor}, "
        f"tipo de carga provável: {tipo_carga}. "
        f"Score preditivo inicial: {score}."
    )
