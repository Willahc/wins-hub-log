#!/usr/bin/env python3
"""
importar_embarcadores_fornecedores.py
=====================================
Lê /home/william/docs/WiNS_Hub_Comercial/fornecedores_insumos.csv e popula
a tabela embarcadores_provaveis com empresas que provavelmente demandam
transporte nos corredores alvo.

Colunas do CSV:
    cnpj, divisao_cnae, cnae_principal, uf, municipio, razao_social, capital_social

Mapeamento UF -> corredor:
    SC -> SC->SP
    MG -> MG->SP
    SP -> SP->DF
    MS -> MS->PR

Regras:
- Upsert por (cnpj, corredor_alvo) - nao sobrescreve dados manuais.
- Exclui empresas com razao social que indique transportadora/logistica.
- Classifica setor, tipo de carga, carrocerias e score_demanda.
"""

import csv
import re
import sqlite3
import sys
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path

# ─── Configuracoes ────────────────────────────────────────────────────────────

CSV_PATH = Path("/home/william/docs/WiNS_Hub_Comercial/fornecedores_insumos.csv")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "instance" / "local.db"
if not DB_PATH.exists():
    DB_PATH = PROJECT_ROOT / "local.db"

FONTE = "fornecedores_insumos_csv"

UF_CORREDOR = {
    "SC": "SC->SP",
    "MG": "MG->SP",
    "SP": "SP->DF",
    "MS": "MS->PR",
}

CORREDOR_ROTAS = {
    "SC->SP": ("SC", "SP"),
    "MG->SP": ("MG", "SP"),
    "SP->DF": ("SP", "DF"),
    "MS->PR": ("MS", "PR"),
}

# ─── Palavras-chave para exclusao (transportadoras/logistica) ─────────────────

EXCLUIR_PALAVRAS = [
    "transport", "transporte", "transportadora", "cargas", "carga rodoviaria",
    "rodoviario", "rodoviaria", "logistica", "armazenamento",
    "armazem", "correio", "courier", "entregas", "fretamento",
    "despacho", "despachante",
]

DIVISOES_EXCLUIR = {"49", "50", "51", "52", "53"}

# ─── Setores ──────────────────────────────────────────────────────────────────

SETORES = [
    ("Alimentos e Bebidas",       ["aliment", "bebida", "frigorifico", "laticinios", "lactic", "alimentar"]),
    ("Atacadista / Distribuicao", ["atacad", "distribuid"]),
    ("Metalmecanico / Autopecas", ["metal", "metalurg", "mecanica", "maquina", "equipamento", "autopeca",
                                   "siderurg", "fundic", "laminac", "fundacao", "ferro", "aco"]),
    ("Plasticos / Embalagens",    ["plastic", "borracha", "embalagem", "pvc", "poliuretano"]),
    ("Textil / Confeccao",        ["textil", "confec", "vestuario", "fio", "tecido", "malharia"]),
    ("Moveis / Madeira",          ["movel", "madeira", "marcenaria", "carpintaria"]),
    ("Quimico / Farma",           ["quimica", "farmac", "farmaceutic", "tintas", "tinta", "resina"]),
    ("Materiais de Construcao",   ["construcao", "construção", "cimento", "ceramic", "mineral", "argamassa",
                                   "telha", "tijolo", "cal ", "gesso", "pedra britada"]),
    ("Agro / Insumos",            ["agro", "grao", "cereal", "soja", "milho", "agricol", "insumo", "fertilizante"]),
    ("Vidro / Minerais",          ["vidro", "cristal"]),
]

SETOR_CARGA = {
    "Alimentos e Bebidas":        ("Carga seca / paletizada; possivel refrigerada",  "bau, sider, bau refrigerado"),
    "Atacadista / Distribuicao":  ("Carga seca fracionada/paletizada",              "bau, sider"),
    "Metalmecanico / Autopecas":  ("Carga industrial / autopecas",                  "sider, bau, prancha leve"),
    "Plasticos / Embalagens":     ("Carga leve volumosa",                           "sider, bau, grade baixa"),
    "Textil / Confeccao":         ("Carga seca leve",                               "bau, sider"),
    "Moveis / Madeira":           ("Carga volumosa",                                "sider, bau, grade baixa"),
    "Quimico / Farma":            ("Carga controlada / paletizada",                 "bau, sider, tanque"),
    "Materiais de Construcao":    ("Carga pesada / paletizada",                     "sider, carroceria aberta, graneleiro"),
    "Agro / Insumos":             ("Granel / ensacado / paletizado",                "graneleiro, sider, bau"),
    "Vidro / Minerais":           ("Carga especial / fragil",                       "bau, sider"),
    "Industrial / Comercial":     ("Carga seca",                                    "bau, sider"),
}

SETORES_PRIORITARIOS = {
    "Alimentos e Bebidas",
    "Metalmecanico / Autopecas",
    "Atacadista / Distribuicao",
    "Materiais de Construcao",
    "Agro / Insumos",
    "Plasticos / Embalagens",
}

DIVISOES_INDUSTRIA = {"22", "23", "24", "25", "26", "27", "28",
                       "10", "11", "12", "13", "14", "15", "16",
                       "17", "18", "19", "20", "21"}

# ─── Utilitarios ──────────────────────────────────────────────────────────────

def normalizar(txt):
    return unicodedata.normalize("NFD", txt).encode("ascii", "ignore").decode("ascii").upper().strip()

def formatar_cnpj(cnpj_raw):
    digits = re.sub(r"\D", "", cnpj_raw)
    if len(digits) != 14:
        return ""
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"

def eh_transportadora(razao, divisao):
    razao_lower = normalizar(razao).lower()
    if any(p in razao_lower for p in EXCLUIR_PALAVRAS):
        return True
    if divisao.strip() in DIVISOES_EXCLUIR:
        return True
    return False

def classificar_setor(razao, cnae, divisao):
    texto = normalizar(razao + " " + cnae).lower()
    for setor, palavras in SETORES:
        if any(p in texto for p in palavras):
            return setor
    div = divisao.strip()
    if div == "22":
        return "Plasticos / Embalagens"
    if div == "23":
        return "Materiais de Construcao"
    if div == "24":
        return "Metalmecanico / Autopecas"
    return "Industrial / Comercial"

def calcular_score(setor, uf, capital, razao, cnpj, divisao):
    score = 0.0
    if setor in SETORES_PRIORITARIOS:
        score += 30
    try:
        if capital >= 100_000:
            score += 20
        elif capital >= 20_000:
            score += 10
    except Exception:
        pass
    if divisao.strip() in DIVISOES_INDUSTRIA:
        score += 15
    if cnpj and razao and len(razao) > 3:
        score += 15
    return min(score, 100.0)

def definir_prioridade(score):
    if score >= 75:
        return "Alta"
    if score >= 50:
        return "Media"
    return "Baixa"

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("IMPORTADOR DE EMBARCADORES - FORNECEDORES DE INSUMOS")
    print("=" * 60)

    if not CSV_PATH.exists():
        print(f"ERRO: Arquivo nao encontrado: {CSV_PATH}")
        sys.exit(1)

    if not DB_PATH.exists():
        print(f"ERRO: Banco de dados nao encontrado: {DB_PATH}")
        sys.exit(1)

    print(f"CSV:  {CSV_PATH}")
    print(f"DB:   {DB_PATH}")
    print()

    c_lido       = 0
    c_cnpj_ok    = 0
    c_excluido   = 0
    c_sem_uf     = 0
    c_inserido   = Counter()
    c_atualizado = Counter()
    c_prioridade = Counter()
    c_setor      = Counter()

    agora = datetime.utcnow().isoformat()

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur  = conn.cursor()

    # Garante indice unico
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_cnpj_corredor_alvo
        ON embarcadores_provaveis(cnpj, corredor_alvo)
    """)
    conn.commit()

    batch = []

    with open(CSV_PATH, "r", encoding="utf-8-sig", errors="ignore", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            c_lido += 1

            cnpj_raw = row.get("cnpj", "").strip()
            uf       = row.get("uf", "").strip().upper()
            razao    = row.get("razao_social", "").strip()
            cnae     = row.get("cnae_principal", "").strip()
            divisao  = row.get("divisao_cnae", "").strip()
            cap_str  = row.get("capital_social", "").strip()

            digits = re.sub(r"\D", "", cnpj_raw)
            if len(digits) != 14:
                continue
            c_cnpj_ok += 1

            if not razao or len(razao) < 3:
                continue

            if uf not in UF_CORREDOR:
                c_sem_uf += 1
                continue

            if eh_transportadora(razao, divisao):
                c_excluido += 1
                continue

            cnpj_fmt = formatar_cnpj(cnpj_raw)
            corredor = UF_CORREDOR[uf]
            orig, dest = CORREDOR_ROTAS[corredor]

            try:
                capital = float(cap_str.replace(",", ".")) if cap_str else 0.0
            except ValueError:
                capital = 0.0

            setor = classificar_setor(razao, cnae, divisao)
            tipo_carga, carrocerias = SETOR_CARGA.get(setor, ("Carga seca", "bau, sider"))
            score      = calcular_score(setor, uf, capital, razao, cnpj_fmt, divisao)
            prioridade = definir_prioridade(score)

            batch.append({
                "cnpj":           cnpj_fmt,
                "razao_social":   razao,
                "uf":             uf,
                "cnae":           cnae,
                "divisao":        divisao,
                "setor":          setor,
                "tipo_carga":     tipo_carga,
                "carrocerias":    carrocerias,
                "corredor":       corredor,
                "orig":           orig,
                "dest":           dest,
                "score":          round(score, 2),
                "prioridade":     prioridade,
                "agora":          agora,
            })

    print(f"Lidas:              {c_lido:>8,}")
    print(f"CNPJ valido 14d:    {c_cnpj_ok:>8,}")
    print(f"Fora das UFs alvo:  {c_sem_uf:>8,}")
    print(f"Excluidas (transp): {c_excluido:>8,}")
    print(f"Candidatas:         {len(batch):>8,}")
    print()
    print("Importando para o banco...")

    for rec in batch:
        cnpj     = rec["cnpj"]
        corredor = rec["corredor"]

        cur.execute(
            "SELECT id, status_crm, notas, telefone, email, site "
            "FROM embarcadores_provaveis WHERE cnpj=? AND corredor_alvo=?",
            (cnpj, corredor)
        )
        existente = cur.fetchone()

        if existente:
            cur.execute("""
                UPDATE embarcadores_provaveis SET
                    razao_social          = ?,
                    uf                    = ?,
                    cnae                  = ?,
                    cnae_descricao        = ?,
                    setor_predito         = ?,
                    tipo_carga_provavel   = ?,
                    carrocerias_provaveis = ?,
                    origem_provavel       = ?,
                    destino_provavel      = ?,
                    score_demanda         = ?,
                    prioridade            = ?,
                    fonte                 = ?,
                    updated_at            = ?
                WHERE cnpj=? AND corredor_alvo=?
            """, (
                rec["razao_social"], rec["uf"],
                rec["cnae"], f"Divisao CNAE {rec['divisao']}",
                rec["setor"], rec["tipo_carga"], rec["carrocerias"],
                rec["orig"], rec["dest"],
                rec["score"], rec["prioridade"], FONTE, rec["agora"],
                cnpj, corredor,
            ))
            c_atualizado[corredor] += 1
        else:
            cur.execute("""
                INSERT INTO embarcadores_provaveis
                    (cnpj, razao_social, nome_fantasia, cidade, uf,
                     cnae, cnae_descricao, setor_predito,
                     tipo_carga_provavel, carrocerias_provaveis,
                     corredor_alvo, origem_provavel, destino_provavel,
                     score_demanda, prioridade, fonte,
                     telefone, email, site, status_crm, notas,
                     created_at, updated_at)
                VALUES (?,?,?,?,?, ?,?,?, ?,?, ?,?,?, ?,?,?, ?,?,?,?,?, ?,?)
            """, (
                cnpj, rec["razao_social"], "", "", rec["uf"],
                rec["cnae"], f"Divisao CNAE {rec['divisao']}", rec["setor"],
                rec["tipo_carga"], rec["carrocerias"],
                corredor, rec["orig"], rec["dest"],
                rec["score"], rec["prioridade"], FONTE,
                "", "", "", "nao_contatada", "",
                rec["agora"], rec["agora"],
            ))
            c_inserido[corredor] += 1

        c_prioridade[rec["prioridade"]] += 1
        c_setor[rec["setor"]] += 1

    conn.commit()
    conn.close()

    print()
    print("=" * 60)
    print("RELATORIO DE IMPORTACAO")
    print("=" * 60)
    print(f"  Total lido no CSV:           {c_lido:>8,}")
    print(f"  Com CNPJ valido (14d):       {c_cnpj_ok:>8,}")
    print(f"  Fora das UFs alvo:           {c_sem_uf:>8,}")
    print(f"  Excluidas (transp/logist):   {c_excluido:>8,}")
    print(f"  Candidatas processadas:      {len(batch):>8,}")
    print()

    total_ins = sum(c_inserido.values())
    total_upd = sum(c_atualizado.values())
    print(f"  Inseridas (novas):           {total_ins:>8,}")
    print(f"  Atualizadas (existentes):    {total_upd:>8,}")
    print()
    print("  Por corredor:")
    for cor in ["SC->SP", "MG->SP", "SP->DF", "MS->PR"]:
        ins = c_inserido.get(cor, 0)
        upd = c_atualizado.get(cor, 0)
        print(f"    {cor}: +{ins:,} inseridas | {upd:,} atualizadas")

    print()
    print("  Por prioridade:")
    for pri in ["Alta", "Media", "Baixa"]:
        print(f"    {pri}: {c_prioridade.get(pri, 0):,}")

    print()
    print("  Por setor (top 10):")
    for setor, cnt in c_setor.most_common(10):
        print(f"    {setor}: {cnt:,}")

    conn2 = sqlite3.connect(str(DB_PATH))
    cur2  = conn2.cursor()
    cur2.execute("SELECT COUNT(*) FROM embarcadores_provaveis")
    total_final = cur2.fetchone()[0]
    conn2.close()
    print()
    print(f"  Total final em embarcadores_provaveis: {total_final:,}")
    print()
    print("Importacao concluida.")

if __name__ == "__main__":
    main()
