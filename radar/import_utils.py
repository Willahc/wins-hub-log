import os
import re
import io
import csv
import unicodedata
import openpyxl
from typing import List, Dict, Any, Tuple
from rapidfuzz import fuzz
from radar.import_validators import EmbarcadorImportSchema

def detectar_tipo_arquivo(path_or_filename: str) -> str:
    """
    Retorna 'xlsx' se terminar com .xlsx, senão 'csv'.
    Se a extensão não for nenhuma dessas, levanta ValueError.
    """
    ext = os.path.splitext(path_or_filename)[1].lower()
    if ext == ".xlsx":
        return "xlsx"
    elif ext == ".csv":
        return "csv"
    else:
        raise ValueError(f"Extensão de arquivo não suportada: {ext}. Envie .csv ou .xlsx.")

def normalizar_cabecalhos(headers: List[Any]) -> List[str]:
    """
    Normaliza os cabeçalhos das colunas (removendo acentos, convertendo para
    minúsculas, limpando espaços por sublinhados e caracteres especiais).
    Exemplo: "Razão Social" -> "razao_social"
    """
    normalized = []
    for h in headers:
        if h is None:
            normalized.append("")
            continue
        # Remove acentos
        s = unicodedata.normalize("NFKD", str(h)).encode("ASCII", "ignore").decode("utf-8").lower().strip()
        # Substitui espaços e hífens por sublinhados
        s = re.sub(r"[-\s]+", "_", s)
        # Remove qualquer caractere que não seja letra, número ou sublinhado
        s = re.sub(r"[^\w_]", "", s)
        normalized.append(s)
    return normalized

def mapear_colunas_linha(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Mapeia os cabeçalhos normalizados para os nomes exatos de campos esperados.
    Isso serve para lidar com sinônimos comuns em cabeçalhos de planilhas.
    """
    mapping = {
        "cnpj_da_empresa": "cnpj",
        "razao": "razao_social",
        "nome": "nome_fantasia",
        "cnae_principal": "cnae",
        "desc_cnae": "cnae_descricao",
        "desc_cnae_principal": "cnae_descricao",
        "cnae_desc": "cnae_descricao",
        "cnae_descricao": "cnae_descricao",
        "corredor": "corredor_alvo",
        "origem": "origem_provavel",
        "destino": "destino_provavel",
    }
    
    mapped_row = {}
    for k, v in row.items():
        mapped_key = mapping.get(k, k)
        mapped_row[mapped_key] = v
    return mapped_row

def ler_csv_com_encoding_e_sep(file) -> List[Dict[str, Any]]:
    """
    Lê o arquivo CSV de forma robusta, detectando delimitador e encoding.
    """
    if hasattr(file, "read"):
        content = file.read()
    else:
        content = file

    # Detecção de encoding
    decoded = None
    for enc in ["utf-8-sig", "latin1", "utf-8"]:
        try:
            decoded = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
            
    if decoded is None:
        raise ValueError("Não foi possível decodificar o arquivo CSV (tente salvar em UTF-8 ou Latin-1).")
        
    lines = decoded.splitlines()
    if not lines:
        return []
    
    # Detecção de delimitador com base nas primeiras linhas
    sample = "\n".join(lines[:5])
    delimiter = ";" if ";" in sample else ","
    
    stream = io.StringIO(decoded, newline=None)
    reader = csv.reader(stream, delimiter=delimiter)
    
    try:
        headers = next(reader)
    except StopIteration:
        return []
        
    normalized_headers = normalizar_cabecalhos(headers)
    
    data = []
    for r in reader:
        # Ignorar linhas vazias
        if not any(cell.strip() for cell in r if cell):
            continue
        row_dict = {}
        for idx, h in enumerate(normalized_headers):
            if h:
                val = r[idx].strip() if idx < len(r) else ""
                row_dict[h] = val
        data.append(mapear_colunas_linha(row_dict))
    return data

def ler_xlsx(file) -> List[Dict[str, Any]]:
    """
    Lê o arquivo XLSX usando openpyxl em modo read_only e data_only.
    """
    if hasattr(file, "read"):
        content = file.read()
    else:
        content = file

    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    sheet = wb.active
    
    rows_iter = sheet.iter_rows(values_only=True)
    try:
        headers = next(rows_iter)
    except StopIteration:
        return []
    
    if not headers:
        return []
        
    normalized_headers = normalizar_cabecalhos(headers)
    
    data = []
    for r in rows_iter:
        # Ignorar linhas totalmente vazias
        if not any(cell is not None for cell in r):
            continue
        row_dict = {}
        for idx, h in enumerate(normalized_headers):
            if h:
                val = r[idx] if idx < len(r) else None
                if val is not None:
                    # Tratar floats do Excel (como CNPJs ou telefones lidos como número)
                    if isinstance(val, float) and val.is_integer():
                        val = int(val)
                    row_dict[h] = str(val)
                else:
                    row_dict[h] = ""
        data.append(mapear_colunas_linha(row_dict))
    return data

def gerar_preview_importacao(rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Valida todas as linhas com Pydantic.
    Retorna uma tupla (linhas_validas, linhas_invalidas).
    - linhas_validas: lista de dicionários contendo os dados limpos e validados.
    - linhas_invalidas: lista de dicionários contendo o índice da linha, os dados originais e a lista de erros.
    """
    linhas_validas = []
    linhas_invalidas = []

    for idx, row in enumerate(rows):
        linha_num = idx + 2  # 1-indexed + 1 para o cabeçalho
        try:
            schema = EmbarcadorImportSchema(**row)
            # dump do pydantic v2
            linhas_validas.append(schema.model_dump())
        except Exception as e:
            # Captura erros detalhados de validação
            erros_msg = []
            if hasattr(e, "errors"):
                for err in e.errors():
                    loc = " -> ".join(str(x) for x in err.get("loc", []))
                    msg = err.get("msg", "Erro de validação")
                    erros_msg.append(f"{loc}: {msg}")
            else:
                erros_msg.append(str(e))
                
            linhas_invalidas.append({
                "linha": linha_num,
                "dados": row,
                "erros": erros_msg
            })

    return linhas_validas, linhas_invalidas

def limpar_nome_para_fuzzy(nome: str) -> str:
    """
    Normaliza o nome da empresa para melhorar a precisão do fuzzy matching.
    Remove acentos, pontuação, converte para minúsculo e elimina sufixos empresariais comuns.
    """
    if not nome:
        return ""
    # Remove acentos
    s = unicodedata.normalize("NFKD", str(nome)).encode("ASCII", "ignore").decode("utf-8").lower().strip()
    # Remove sufixos de enquadramento empresarial comuns
    s = re.sub(r"\b(ltda|sa|s/a|s\.a|eireli|me|mep|limitada|sociedade|anonima)\b", " ", s)
    # Remove pontuações
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.split())

def detectar_duplicidades(rows: List[Dict[str, Any]], existentes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Detecta possíveis duplicidades usando RapidFuzz e CNPJ idêntico.
    Retorna uma lista de dicionários com alertas de duplicidade.
    """
    duplicidades = []
    
    # Indexar existentes por CNPJ para busca rápida
    existentes_por_cnpj = {}
    for ext in existentes:
        cnpj_val = ext.get("cnpj")
        if cnpj_val:
            cnpj_clean = re.sub(r"\D", "", cnpj_val)
            if cnpj_clean:
                existentes_por_cnpj[cnpj_clean] = ext

    for idx, row in enumerate(rows):
        linha_num = idx + 2
        cnpj_import = row.get("cnpj")
        
        # 1. CNPJ idêntico (duplicidade forte)
        if cnpj_import:
            cnpj_import_clean = re.sub(r"\D", "", cnpj_import)
            if cnpj_import_clean in existentes_por_cnpj:
                ext = existentes_por_cnpj[cnpj_import_clean]
                duplicidades.append({
                    "linha": linha_num,
                    "tipo": "CNPJ_DUPLICADO",
                    "importado": f"{row.get('razao_social') or row.get('nome_fantasia')} (CNPJ: {cnpj_import})",
                    "existente": f"{ext.get('razao_social') or ext.get('nome_fantasia')} (ID: {ext['id']} - Corredor: {ext.get('corredor_alvo')})",
                    "grau": "Forte (CNPJ idêntico)",
                    "bloquear": True,
                    "cnpj": cnpj_import_clean,
                    "corredor_alvo": ext.get("corredor_alvo")
                })
                continue

        # 2. Fuzzy Matching
        import_name = (row.get("razao_social") or row.get("nome_fantasia") or "")
        import_name_clean = limpar_nome_para_fuzzy(import_name)
        import_cidade = (row.get("cidade") or "").strip().lower()
        import_uf = (row.get("uf") or "").strip().upper()

        if not import_name_clean:
            continue

        for ext in existentes:
            ext_name_razao = (ext.get("razao_social") or "")
            ext_name_fantasia = (ext.get("nome_fantasia") or "")
            
            ext_name_razao_clean = limpar_nome_para_fuzzy(ext_name_razao)
            ext_name_fantasia_clean = limpar_nome_para_fuzzy(ext_name_fantasia)
            
            ext_cidade = (ext.get("cidade") or "").strip().lower()
            ext_uf = (ext.get("uf") or "").strip().upper()

            # Calcula similaridade com os nomes normalizados
            sim_razao = fuzz.token_set_ratio(import_name_clean, ext_name_razao_clean) if ext_name_razao_clean else 0
            sim_fantasia = fuzz.token_set_ratio(import_name_clean, ext_name_fantasia_clean) if ext_name_fantasia_clean else 0
            max_sim = max(sim_razao, sim_fantasia)

            mesma_localidade = (import_cidade == ext_cidade) and (import_uf == ext_uf)

            # Regra: similaridade >= 97 e mesma cidade/UF -> Duplicidade muito provável
            if max_sim >= 97 and mesma_localidade:
                duplicidades.append({
                    "linha": linha_num,
                    "tipo": "FUZZY_LOCALIDADE",
                    "importado": f"{row.get('razao_social') or row.get('nome_fantasia')} ({row.get('cidade')}/{row.get('uf')})",
                    "existente": f"{ext.get('razao_social') or ext.get('nome_fantasia')} (ID: {ext['id']} - {ext.get('cidade')}/{ext.get('uf')} - Corredor: {ext.get('corredor_alvo')})",
                    "grau": f"Muito Provável (Fuzzy: {max_sim:.1f}% + Localidade)",
                    "bloquear": False,
                    "cnpj": cnpj_import,
                    "corredor_alvo": ext.get("corredor_alvo")
                })
                break
                
            # Regra: similaridade >= 92 -> Possível duplicidade
            elif max_sim >= 92:
                duplicidades.append({
                    "linha": linha_num,
                    "tipo": "FUZZY_SIMILAR",
                    "importado": f"{row.get('razao_social') or row.get('nome_fantasia')}",
                    "existente": f"{ext.get('razao_social') or ext.get('nome_fantasia')} (ID: {ext['id']} - Corredor: {ext.get('corredor_alvo')})",
                    "grau": f"Possível (Fuzzy: {max_sim:.1f}%)",
                    "bloquear": False,
                    "cnpj": cnpj_import,
                    "corredor_alvo": ext.get("corredor_alvo")
                })
                break

    return duplicidades

