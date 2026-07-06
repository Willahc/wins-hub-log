#!/usr/bin/env python3
"""
enriquecer_cidades_transportadoras.py
======================================
Enriquece a coluna `municipio` (cidade) da tabela transportadoras
onde está vazia, utilizando os CSVs da RNTRC correspondentes
aos 4 corredores mapeados e normalizando os nomes das cidades
usando a tabela do IBGE (tabela_municipios_rf.csv).

Também atualiza `matches_preditivos.cidade_origem` e `uf_origem`
onde estiverem vazios com base na transportadora correspondente.
"""

import os
import sys
import csv
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# Configurações
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "instance" / "local.db"
if not DB_PATH.exists():
    DB_PATH = PROJECT_ROOT / "local.db"

TABELA_MUNICIPIOS = PROJECT_ROOT / "scripts" / "tabela_municipios_rf.csv"

CSV_FILES = [
    "exports/corredores/transportadoras_SP_DF_rntrc_05_2026.csv",
    "exports/corredores/transportadoras_MG_SP_rntrc_05_2026.csv",
    "exports/corredores/transportadoras_SC_SP_rntrc_05_2026.csv",
    "exports/corredores/transportadoras_MS_PR_rntrc_05_2026.csv"
]

DE_PARA_MANUAL = {
    ("AMAMBI", "MS"): "Amambai",
    ("BOCANA DO SUL", "SC"): "Bocaina do Sul",
    ("FLORNEA", "SP"): "Florínea",
    ("FRANCISCO S", "MG"): "Francisco Sá",
    ("JUT", "MS"): "Juti",
    ("LAURO MLLER", "SC"): "Lauro Müller",
    ("MARACAJ", "MS"): "Maracaju",
    ("SO CRISTVO DO SUL", "SC"): "São Cristóvão do Sul",
    ("VTOR MEIRELES", "SC"): "Vitor Meireles",
}


# Utilitários de Normalização
def normalizar_cnpj(cnpj_raw):
    d = re.sub(r"\D", "", str(cnpj_raw))
    if len(d) != 14:
        return ""
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def normalizar_deformado(txt):
    if not txt:
        return ""
    txt = txt.upper().strip()
    
    # Substituir abreviações comuns (mantendo correspondência com a deformação)
    txt = re.sub(r"\bS\b", "SAO", txt)
    txt = re.sub(r"\bSTA\b", "SANTA", txt)
    txt = re.sub(r"\bSTO\b", "SANTO", txt)
    
    txt = txt.replace(".", "").replace("-", " ")
    
    # Deletar completamente qualquer letra que tenha acento ou cedilha
    caracteres_deletar = "[ÁÀÂÃÉÊÍÓÔÕÚÇáàâãéêíóôõúç]"
    txt = re.sub(caracteres_deletar, "", txt)
    
    txt = re.sub(r"\s+", " ", txt)
    return txt.strip()


def carregar_municipios_ibge():
    """Carrega a tabela de municípios e constrói de-para normalizado -> acentuado."""
    mapa = {}
    if not TABELA_MUNICIPIOS.exists():
        print(f"ERRO: Tabela de municípios {TABELA_MUNICIPIOS} não encontrada!")
        return mapa

    uf_map = {
        "35": "SP", "31": "MG", "42": "SC", "50": "MS", "11": "RO", "12": "AC", "13": "AM", "14": "RR",
        "15": "PA", "16": "AP", "17": "TO", "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB",
        "26": "PE", "27": "AL", "28": "SE", "29": "BA", "41": "PR", "43": "RS", "51": "MT", "52": "GO",
        "53": "DF", "32": "ES", "33": "RJ"
    }

    with open(TABELA_MUNICIPIOS, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            nome = row.get("nome", "")
            uf_num = row.get("codigo_uf", "")
            uf_sigla = uf_map.get(uf_num, "")
            if uf_sigla and nome:
                key = (normalizar_deformado(nome), uf_sigla)
                mapa[key] = nome.strip()
    return mapa


def ler_csvs_rntrc(mapa_cidades_ibge):
    """Lê os CSVs e retorna dict {cnpj_formatado: (cidade_enriquecida, uf, cep)}."""
    mapa_transportadoras = {}
    total_linhas_csv = 0
    cnpjs_unicos_csv = set()

    for file_rel in CSV_FILES:
        path = PROJECT_ROOT / file_rel
        if not path.exists():
            print(f"Aviso: CSV {path} não encontrado, pulando...")
            continue

        print(f"  Lendo: {path.name}...")
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                total_linhas_csv += 1
                cnpj_raw = row.get("cpfcnpjtransportador", "")
                cnpj_fmt = normalizar_cnpj(cnpj_raw)
                if not cnpj_fmt:
                    continue

                cnpjs_unicos_csv.add(cnpj_fmt)
                
                mun_csv = row.get("municipio", "").strip()
                uf_csv = row.get("uf", "").strip().upper()
                cep_csv = row.get("cep", "").strip()

                if mun_csv and uf_csv:
                    # Tentar resolver cidade acentuada
                    key_deformado = (normalizar_deformado(mun_csv), uf_csv)
                    
                    if key_deformado in DE_PARA_MANUAL:
                        cidade_resolvida = DE_PARA_MANUAL[key_deformado]
                    elif key_deformado in mapa_cidades_ibge:
                        cidade_resolvida = mapa_cidades_ibge[key_deformado]
                    else:
                        # Se não encontrar, converter para Title Case amigável como fallback
                        cidade_resolvida = mun_csv.title()

                    mapa_transportadoras[cnpj_fmt] = (cidade_resolvida, uf_csv, cep_csv)

    print(f"  Total linhas processadas nos CSVs: {total_linhas_csv:,}")
    print(f"  Total CNPJs únicos mapeados:      {len(cnpjs_unicos_csv):,}")
    return mapa_transportadoras


def main():
    print("=" * 60)
    print("ENRIQUECEDOR DE CIDADES - TRANSPORTADORAS")
    print("=" * 60)

    if not DB_PATH.exists():
        print(f"ERRO: Banco de dados não encontrado em {DB_PATH}!")
        sys.exit(1)

    # 1. Carregar municípios do IBGE
    print("[1/5] Carregando municípios do IBGE...")
    mapa_cidades_ibge = carregar_municipios_ibge()
    print(f"  Municípios carregados: {len(mapa_cidades_ibge):,}")

    # 2. Carregar dados das transportadoras dos CSVs
    print("[2/5] Carregando transportadoras dos CSVs RNTRC...")
    mapa_transp_csv = ler_csvs_rntrc(mapa_cidades_ibge)

    # 3. Conectar ao banco e iniciar enriquecimento
    print("[3/5] Conectando ao banco de dados e preparando enriquecimento...")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Contagens antes
    cur.execute("SELECT COUNT(*) FROM transportadoras")
    total_transportadoras = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM transportadoras WHERE municipio IS NULL OR TRIM(municipio) = ''")
    vazias_antes = cur.fetchone()[0]

    print(f"  Total transportadoras no banco:      {total_transportadoras:,}")
    print(f"  Transportadoras sem cidade (antes):  {vazias_antes:,}")
    print()

    # Buscar transportadoras com cidade vazia
    cur.execute("""
        SELECT id, cnpj, municipio, uf, cep, notas, corredor_alvo 
        FROM transportadoras 
        WHERE municipio IS NULL OR TRIM(municipio) = ''
    """)
    rows_vazias = cur.fetchall()

    print("[4/5] Atualizando transportadoras no banco...")
    c_atualizados = 0
    c_nao_encontrados = 0
    c_por_corredor = Counter()
    amostras_por_corredor = defaultdict(list)
    agora = datetime.utcnow().isoformat()

    for row in rows_vazias:
        t_id = row["id"]
        cnpj = row["cnpj"]
        corredor = row["corredor_alvo"] or "Desconhecido"
        cep_db = row["cep"]
        notas_db = row["notas"] or ""

        cnpj_fmt = normalizar_cnpj(cnpj)
        if cnpj_fmt in mapa_transp_csv:
            cidade_csv, uf_csv, cep_csv = mapa_transp_csv[cnpj_fmt]

            # CEP
            cep_final = cep_db
            novas_notas = notas_db
            if cep_csv:
                if not cep_db:
                    cep_final = cep_csv
                elif cep_db.replace("-", "") != cep_csv.replace("-", ""):
                    nota_cep = f"CEP do RNTRC: {cep_csv}"
                    if nota_cep not in novas_notas:
                        novas_notas = (novas_notas + "\n" + nota_cep).strip()

            # Update
            cur.execute("""
                UPDATE transportadoras 
                SET municipio = ?, cep = ?, notas = ?, atualizado_em = ?
                WHERE id = ? AND (municipio IS NULL OR TRIM(municipio) = '')
            """, (cidade_csv, cep_final, novas_notas, agora, t_id))

            c_atualizados += 1
            c_por_corredor[corredor] += 1
            
            if len(amostras_por_corredor[corredor]) < 5:
                amostras_por_corredor[corredor].append((cnpj_fmt, cidade_csv, uf_csv))
        else:
            c_nao_encontrados += 1

    conn.commit()

    # Contagens depois
    cur.execute("SELECT COUNT(*) FROM transportadoras WHERE municipio IS NULL OR TRIM(municipio) = ''")
    vazias_depois = cur.fetchone()[0]

    # 4. Atualizar matches preditivos correspondentes
    print("[5/5] Atualizando matches preditivos (cidade_origem e uf_origem)...")
    cur.execute("""
        SELECT m.id, t.municipio, t.uf
        FROM matches_preditivos m
        JOIN transportadoras t ON t.id = m.transportadora_id
        WHERE (m.cidade_origem IS NULL OR m.cidade_origem = '' OR m.cidade_origem = 'None')
          AND (t.municipio IS NOT NULL AND t.municipio != '')
    """)
    matches_vazios = cur.fetchall()
    
    matches_atualizados = 0
    for match_row in matches_vazios:
        cur.execute("""
            UPDATE matches_preditivos
            SET cidade_origem = ?, uf_origem = ?
            WHERE id = ?
        """, (match_row["municipio"], match_row["uf"], match_row["id"]))
        matches_atualizados += 1

    conn.commit()
    conn.close()

    # Relatório Final
    print()
    print("=" * 60)
    print("RELATÓRIO DE ENRIQUECIMENTO")
    print("=" * 60)
    print(f"Total transportadoras no banco:       {total_transportadoras:>8,}")
    print(f"Cidades vazias ANTES:                 {vazias_antes:>8,}")
    print(f"CNPJs pesquisados (vazios antes):     {len(rows_vazias):>8,}")
    print(f"Cidades atualizadas com sucesso:      {c_atualizados:>8,}")
    print(f"CNPJs não encontrados nos CSVs:       {c_nao_encontrados:>8,}")
    print(f"Cidades vazias DEPOIS:                {vazias_depois:>8,}")
    print(f"Matches preditivos atualizados:       {matches_atualizados:>8,}")
    print()
    print("Atualizações por Corredor:")
    for corr in sorted(c_por_corredor.keys()):
        print(f"  {corr:<15}: {c_por_corredor[corr]:,}")
    print()
    print("Amostra por Corredor (primeiros 5):")
    for corr in sorted(amostras_por_corredor.keys()):
        print(f"  Corredor {corr}:")
        for cnpj_f, cidade, uf in amostras_por_corredor[corr]:
            print(f"    - {cnpj_f} -> {cidade}/{uf}")
    print("=" * 60)
    print("Enriquecimento concluído com sucesso!")


if __name__ == "__main__":
    main()
