import urllib.parse
import re

def limpar_telefone_para_whatsapp(telefone):
    if not telefone:
        return ""
    # Manter somente números
    nums = re.sub(r"\D", "", str(telefone))
    # Se for celular do Brasil sem DDI (ex: 47999999999 ou 4799999999)
    if len(nums) in [10, 11] and not nums.startswith("55"):
        nums = "55" + nums
    return nums

def montar_link_whatsapp(telefone, mensagem):
    nums = limpar_telefone_para_whatsapp(telefone)
    if not nums:
        return ""
    texto_enc = urllib.parse.quote(mensagem)
    return f"https://api.whatsapp.com/send?phone={nums}&text={texto_enc}"

def gerar_mensagem_embarcador(match):
    corredor = match.corredor or "N/A"
    cidade_embarcador = match.cidade_destino or "N/A"
    uf_embarcador = match.uf_destino or "N/A"
    tipo_carga = match.embarcador.tipo_carga_provavel or "carga seca / geral"
    destino_provavel = match.embarcador.destino_provavel or "o destino alvo"
    
    msg = (
        "Olá, tudo bem?\n\n"
        f"Tenho uma oportunidade de aproveitamento de rota no corredor {corredor}.\n\n"
        "Identificamos disponibilidade de transportadora com perfil compatível para carga de retorno, "
        "podendo ajudar a reduzir custo de frete e evitar deslocamento vazio.\n\n"
        f"Pelo perfil da sua empresa em {cidade_embarcador}/{uf_embarcador}, "
        f"acredito que pode haver aderência para cargas do tipo {tipo_carga}.\n\n"
        f"Vocês têm alguma demanda de embarque para {destino_provavel} ou região nos próximos dias?\n\n"
        "Posso te passar mais detalhes e avaliar uma cotação."
    )
    return msg

def gerar_mensagem_transportadora(match):
    corredor = match.corredor or "N/A"
    tipo_carga = match.embarcador.tipo_carga_provavel or "carga compatível"
    cidade_embarcador = match.cidade_destino or "N/A"
    uf_embarcador = match.uf_destino or "N/A"
    destino_provavel = match.embarcador.destino_provavel or "o destino alvo"
    
    msg = (
        "Olá, tudo bem?\n\n"
        f"Identificamos um possível embarcador compatível com o corredor {corredor}, "
        f"com perfil de carga provável: {tipo_carga}.\n\n"
        "Esse match pode ajudar a reduzir retorno vazio e gerar receita adicional na rota.\n\n"
        f"Você teria disponibilidade operacional para avaliar uma carga saindo de {cidade_embarcador}/{uf_embarcador} "
        f"com destino provável para {destino_provavel}?"
    )
    return msg

def gerar_assunto_email(match):
    return f"Oportunidade de Carga de Retorno - Corredor {match.corredor} - WiNS Hub Log"
