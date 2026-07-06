#!/usr/bin/env python3
"""
enriquecer_cidades_embarcadores.py
====================================
Enriquece o campo `cidade` da tabela embarcadores_provaveis onde o campo
esta vazio, usando a tabela de municipios do repositorio kelvins/municipios-brasileiros
(campo siafi_id = codigo de municipio da Receita Federal).

O CSV de origem (fornecedores_insumos.csv) usa o codigo siafi_id (4 digitos)
no campo `municipio`. A tabela de referencia mapeia siafi_id -> nome do municipio.

Fonte da tabela de referencia:
  https://raw.githubusercontent.com/kelvins/municipios-brasileiros/main/csv/municipios.csv

Colunas relevantes: codigo_ibge, nome, codigo_uf, siafi_id

Estrategia:
1. Baixar tabela de municipios (com cache local em scripts/tabela_municipios_rf.csv)
2. Construir dicionario {siafi_id: nome}
3. Reler CSV de origem para obter o mapa cnpj -> (cod_mun, uf)
4. Para cada embarcador com cidade vazia, resolver nome via siafi_id + uf
5. Atualizar banco com UPDATE ... WHERE cnpj=? AND corredor_alvo=? AND (cidade IS NULL OR cidade='')
6. Gerar relatorio
"""

import csv
import io
import os
import re
import sqlite3
import sys
import unicodedata
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# ─── Configuracoes ────────────────────────────────────────────────────────────

CSV_PATH      = Path("/home/william/docs/WiNS_Hub_Comercial/fornecedores_insumos.csv")
PROJECT_ROOT  = Path(__file__).resolve().parent.parent
DB_PATH       = PROJECT_ROOT / "instance" / "local.db"
if not DB_PATH.exists():
    DB_PATH = PROJECT_ROOT / "local.db"

# Cache local da tabela de municipios (nao comitado, listado no .gitignore)
TABELA_CACHE  = Path(__file__).resolve().parent / "tabela_municipios_rf.csv"
TABELA_URL    = "https://raw.githubusercontent.com/kelvins/municipios-brasileiros/main/csv/municipios.csv"

UF_CORREDOR = {
    "SC": "SC->SP",
    "MG": "MG->SP",
    "SP": "SP->DF",
    "MS": "MS->PR",
}


# ─── Utilitarios ──────────────────────────────────────────────────────────────

def normalizar_titulo(txt):
    """Remove acentos e converte para Title Case limpo."""
    nfd = unicodedata.normalize("NFD", txt)
    sem_acento = nfd.encode("ascii", "ignore").decode("ascii")
    return sem_acento.title().strip()


def normalizar_cidade(nome):
    """Normaliza nome de cidade para exibicao."""
    # Manter acentos mas garantir Title Case
    palavras_minusculas = {"de", "do", "da", "dos", "das", "e", "em"}
    partes = nome.strip().split()
    resultado = []
    for i, p in enumerate(partes):
        p_lower = p.lower()
        if i == 0 or p_lower not in palavras_minusculas:
            resultado.append(p.capitalize())
        else:
            resultado.append(p_lower)
    return " ".join(resultado)


def baixar_tabela_municipios():
    """Baixa ou carrega do cache a tabela de municipios."""
    if TABELA_CACHE.exists():
        print(f"  Usando cache local: {TABELA_CACHE}")
        with open(TABELA_CACHE, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        print(f"  Baixando de: {TABELA_URL}")
        try:
            with urllib.request.urlopen(TABELA_URL, timeout=30) as r:
                content = r.read().decode("utf-8")
            # Salvar cache
            TABELA_CACHE.parent.mkdir(parents=True, exist_ok=True)
            with open(TABELA_CACHE, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"  Cache salvo em: {TABELA_CACHE}")
        except Exception as e:
            print(f"  ERRO ao baixar tabela: {e}")
            sys.exit(1)
    return content


def construir_mapa_siafi(content):
    """
    Retorna dicionario {siafi_id: nome_municipio} a partir do CSV de municipios.
    siafi_id corresponde ao codigo de municipio da Receita Federal (campo municipio no CSV de origem).
    """
    mapa = {}
    reader = csv.DictReader(io.StringIO(content))
    for row in reader:
        siafi = row.get("siafi_id", "").strip()
        nome  = row.get("nome", "").strip()
        if siafi and nome:
            # Guardar versao sem acento e com acento
            mapa[siafi] = nome
    return mapa


def ler_cnpj_municipio_csv():
    """
    Le o CSV de fornecedores e retorna:
      dict {cnpj_formatado: (cod_siafi, uf)}
    para todos os CNPJs das UFs alvo.
    """
    resultado = {}

    def fmt(raw):
        d = re.sub(r"\D", "", raw)
        if len(d) != 14:
            return ""
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"

    with open(CSV_PATH, "r", encoding="utf-8-sig", errors="ignore", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            uf   = row.get("uf", "").strip().upper()
            cnpj = row.get("cnpj", "").strip()
            mun  = row.get("municipio", "").strip()
            if uf in UF_CORREDOR and mun:
                cnpj_fmt = fmt(cnpj)
                if cnpj_fmt:
                    resultado[cnpj_fmt] = (mun, uf)

    return resultado


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("ENRIQUECEDOR DE CIDADES - EMBARCADORES")
    print("=" * 60)

    if not DB_PATH.exists():
        print(f"ERRO: Banco nao encontrado: {DB_PATH}")
        sys.exit(1)
    if not CSV_PATH.exists():
        print(f"ERRO: CSV nao encontrado: {CSV_PATH}")
        sys.exit(1)

    print(f"DB:  {DB_PATH}")
    print(f"CSV: {CSV_PATH}")
    print()

    # 1. Baixar/carregar tabela de municipios
    print("[1/5] Carregando tabela de municipios (SIAFI/RF)...")
    content = baixar_tabela_municipios()
    mapa_siafi = construir_mapa_siafi(content)
    print(f"  Municipios carregados: {len(mapa_siafi):,}")

    # 2. Ler mapa cnpj -> (cod_siafi, uf) do CSV de origem
    print("[2/5] Lendo CSV de origem para mapear cnpj -> codigo municipio...")
    cnpj_mun_map = ler_cnpj_municipio_csv()
    print(f"  CNPJs mapeados: {len(cnpj_mun_map):,}")

    # 3. Conectar ao banco
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur  = conn.cursor()

    # Contar cidades vazias antes
    cur.execute("SELECT COUNT(*) FROM embarcadores_provaveis")
    total_emb = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM embarcadores_provaveis WHERE cidade IS NULL OR cidade = ''")
    vazias_antes = cur.fetchone()[0]

    print(f"[3/5] Situacao antes da atualizacao:")
    print(f"  Total embarcadores:  {total_emb:,}")
    print(f"  Cidade vazia:        {vazias_antes:,}")
    print(f"  Cidade preenchida:   {total_emb - vazias_antes:,}")
    print()

    # 4. Atualizar cidades
    print("[4/5] Atualizando cidades...")

    # Buscar embarcadores com cidade vazia + seu cnpj
    cur.execute("""
        SELECT id, cnpj, uf, corredor_alvo
        FROM embarcadores_provaveis
        WHERE cidade IS NULL OR cidade = ''
    """)
    sem_cidade = cur.fetchall()

    agora = datetime.utcnow().isoformat()
    c_atualizado   = 0
    c_nao_encontrado = Counter()
    c_por_uf       = Counter()
    c_cidades      = Counter()
    amostra_por_uf = defaultdict(list)
    erros          = []

    for row in sem_cidade:
        emb_id  = row["id"]
        cnpj    = row["cnpj"]
        uf      = row["uf"]
        corredor = row["corredor_alvo"]

        # Buscar o codigo do municipio para esse CNPJ
        info = cnpj_mun_map.get(cnpj)
        if not info:
            erros.append(f"cnpj={cnpj} nao encontrado no CSV")
            c_nao_encontrado["sem_cnpj_no_csv"] += 1
            continue

        cod_siafi, uf_csv = info

        # Resolver nome
        nome_cidade = mapa_siafi.get(cod_siafi)
        if not nome_cidade:
            c_nao_encontrado[f"cod_{cod_siafi}_uf_{uf}"] += 1
            continue

        cidade_final = normalizar_cidade(nome_cidade)

        # Atualizar (preserva outros campos manuais)
        cur.execute("""
            UPDATE embarcadores_provaveis
            SET cidade = ?, updated_at = ?
            WHERE id = ? AND (cidade IS NULL OR cidade = '')
        """, (cidade_final, agora, emb_id))

        c_atualizado += 1
        c_por_uf[uf] += 1
        c_cidades[cidade_final] += 1
        if len(amostra_por_uf[uf]) < 5:
            amostra_por_uf[uf].append((cnpj, cidade_final))

    conn.commit()

    # 5. Verificar depois
    cur.execute("SELECT COUNT(*) FROM embarcadores_provaveis WHERE cidade IS NULL OR cidade = ''")
    vazias_depois = cur.fetchone()[0]
    conn.close()

    # ─── Relatorio ────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("RELATORIO")
    print("=" * 60)
    print(f"  Total embarcadores:           {total_emb:>8,}")
    print(f"  Cidade vazia ANTES:           {vazias_antes:>8,}")
    print(f"  Atualizadas com sucesso:      {c_atualizado:>8,}")
    print(f"  Nao encontradas (sem match):  {sum(c_nao_encontrado.values()):>8,}")
    print(f"  Cidade vazia DEPOIS:          {vazias_depois:>8,}")
    print()
    print("  Por UF:")
    for uf in sorted(c_por_uf.keys()):
        print(f"    {uf}: {c_por_uf[uf]:,}")
    print()
    print("  Top cidades por frequencia (10):")
    for cidade, cnt in c_cidades.most_common(10):
        print(f"    {cidade}: {cnt:,}")
    print()
    print("  Amostra por UF:")
    for uf in sorted(amostra_por_uf.keys()):
        print(f"    {uf}:")
        for cnpj, cidade in amostra_por_uf[uf]:
            print(f"      {cnpj} -> {cidade}")
    if c_nao_encontrado:
        print()
        total_nao_enc = sum(c_nao_encontrado.values())
        print(f"  Nao encontrados (primeiros 5 de {total_nao_enc}):")
        for k, v in list(c_nao_encontrado.most_common(5)):
            print(f"    {k}: {v}")
    print()
    print("Enriquecimento concluido.")


if __name__ == "__main__":
    main()
