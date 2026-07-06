#!/usr/bin/env python3
"""
enriquecer_base_pre_match.py
=============================
Enriquece a base de dados de transportadoras e embarcadores de forma priorizada
e controlada antes de gerar novos matches, usando a BrasilAPI e cache local.
"""

import os
import sys
import json
import time
import argparse
import sqlite3
import unicodedata
import re
import requests
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# Adiciona a raiz do projeto ao path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

from config import Config
from radar.embarcadores import avaliar_embarcador

CACHE_PATH = PROJECT_ROOT / "instance" / "cache_brasilapi_cnpj.jsonl"
DB_PATH = PROJECT_ROOT / "instance" / "local.db"
if not DB_PATH.exists():
    DB_PATH = PROJECT_ROOT / "local.db"


# ─── Helpers de Schema e Rows ─────────────────────────────────────────────────

def get_table_columns(conn, table):
    """Retorna o schema das colunas em letras minúsculas."""
    try:
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info({table})")
        return {row[1].lower() for row in cur.fetchall()}
    except Exception as e:
        print(f"Erro ao ler schema da tabela {table}: {e}", file=sys.stderr)
        return set()


def row_get(row, key, default=""):
    """Acesso seguro a colunas do Row SQLite."""
    try:
        if not row:
            return default
        for k in row.keys():
            if k.lower() == key.lower():
                val = row[k]
                return val if val is not None else default
    except Exception:
        pass
    return default


def table_has_col(table_cols, col):
    return col.lower() in table_cols


# ─── Utilitários ──────────────────────────────────────────────────────────────

def limpar_cnpj(cnpj_raw):
    return "".join(x for x in str(cnpj_raw) if x.isdigit()).zfill(14)


def formatar_cnpj(cnpj_raw):
    c = limpar_cnpj(cnpj_raw)
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:14]}" if len(c) == 14 else c


def normalizar_texto(t):
    if not t:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(t).upper().strip())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def e_razao_social_ruim(razao):
    if not razao:
        return True
    m = re.match(r"^[\d\.\-\/]{6,}", razao.strip())
    if m:
        return True
    if razao.strip() in ["", "-", "—", "None"]:
        return True
    return False


def safe_str(val):
    if val is None:
        return ""
    return str(val).strip()


def classificar_perfil_forte(row_db):
    """Classifica se uma transportadora tem perfil logístico forte com base no nome."""
    razao = (row_get(row_db, "razao_social") or "").upper()
    fantasia = (row_get(row_db, "nome_fantasia") or "").upper()
    nome_rntrc = (row_get(row_db, "nome_rntrc") or "").upper()
    
    termos_forte = ["TRANSPORT", "TRANSPORTADORA", "TRANSPORTES", "LOGISTICA", "LOG", "CARGAS", "FRETES", "EXPRESSO", "RODOVIARIO"]
    termos_fraco = ["COMERCIO", "ALIMENTOS", "BEBIDAS", "MERCADO", "PADARIA", "RESTAURANTE", "DISTRIBUIDORA DE ALIMENTOS"]
    
    has_forte = any(t in razao or t in fantasia or t in nome_rntrc for t in termos_forte)
    has_fraco = any(t in razao or t in fantasia or t in nome_rntrc for t in termos_fraco)
    
    return has_forte and not has_fraco


class EmbarcadorMock:
    """Mock do model SQLAlchemy para a função avaliar_embarcador."""
    def __init__(self, row_dict):
        self.__dict__.update(row_dict)
        # Se algum campo não estiver definido, colocar default None
        for key in ["razao_social", "nome_fantasia", "cnae_descricao", "cidade", "uf", 
                    "origem_provavel", "destino_provavel", "corredor_alvo", "status_crm",
                    "telefone", "email", "site", "notas"]:
            if not hasattr(self, key):
                setattr(self, key, None)


# ─── Cache Local ──────────────────────────────────────────────────────────────

def carregar_cache_local():
    cache = {}
    if CACHE_PATH.exists():
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                    cnpj = item.get("cnpj")
                    if cnpj:
                        cache[limpar_cnpj(cnpj)] = item
                except Exception:
                    pass
    return cache


def salvar_no_cache(cnpj, status, dados):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    item = {
        "cnpj": limpar_cnpj(cnpj),
        "status": status,
        "dados": dados,
        "consultado_em": datetime.now(timezone.utc).isoformat()
    }
    with open(CACHE_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(item) + "\n")


# ─── Requisições à API ─────────────────────────────────────────────────────────

def consultar_brasilapi(cnpj, sleep_time=1.5):
    cnpj_limpo = limpar_cnpj(cnpj)
    url = f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}"
    headers = {"User-Agent": "WiNS-Hub-PreMatchEnricher/1.0"}
    
    time.sleep(sleep_time)
    
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            return r.status_code, r.json()
        elif r.status_code == 404:
            return r.status_code, None
        elif r.status_code == 429:
            return r.status_code, None
        else:
            return r.status_code, None
    except Exception as e:
        print(f"  Erro de conexão para CNPJ {cnpj_limpo}: {e}")
        return 500, None


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Enriquece a base de dados de transportadoras/embarcadores antes do match.")
    parser.add_argument("--corredor", required=True, help="Corredor alvo (ex: 'SC->SP')")
    parser.add_argument("--tipo", choices=["transportadoras", "embarcadores", "ambos"], default="ambos", help="Tipo de registros a enriquecer")
    parser.add_argument("--prioridade", choices=["Alta", "Media", "Baixa", "todas"], default="todas", help="Prioridade dos embarcadores (todas, Alta, Media, Baixa)")
    parser.add_argument("--limit", type=int, default=500, help="Limite máximo de consultas à API (default: 500)")
    parser.add_argument("--sleep", type=float, default=1.5, help="Sleep entre chamadas da API (default: 1.5)")
    parser.add_argument("--only-missing", action="store_true", help="Apenas registros sem CNAE ou com Razão Social ruim")
    parser.add_argument("--dry-run", action="store_true", help="Modo simulação (não grava no banco nem no cache)")
    parser.add_argument("--preferir-transportadoras-puras", action="store_true", help="Ordena transportadoras puras primeiro no processamento")

    args = parser.parse_args()

    print("=" * 60)
    print("PIPELINE DE ENRIQUECIMENTO PRÉ-MATCH BRASILAPI")
    print("=" * 60)
    print(f"Corredor:              {args.corredor}")
    print(f"Tipo selecionado:      {args.tipo}")
    print(f"Prioridade Emb:        {args.prioridade}")
    print(f"Limite consultas API:  {args.limit}")
    print(f"Intervalo (sleep):     {args.sleep}s")
    print(f"Apenas faltantes:      {args.only_missing}")
    print(f"Modo Simulação:        {args.dry_run}")
    print(f"Foco Transp Puras:     {args.preferir_transportadoras_puras}")
    print("-" * 60)

    if not DB_PATH.exists():
        print(f"ERRO: Banco de dados não encontrado em {DB_PATH}!", file=sys.stderr)
        sys.exit(1)

    # 1. Carregar cache local
    cache = carregar_cache_local()
    print(f"Cache local carregado: {len(cache):,} registros.")

    # 2. Conectar ao banco de dados e schemas
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    t_cols = get_table_columns(conn, "transportadoras")
    e_cols = get_table_columns(conn, "embarcadores_provaveis")

    # 3. Carregar registros candidatos do corredor
    t_rows = []
    e_rows = []

    if args.tipo in ["transportadoras", "ambos"]:
        # Buscar transportadoras do corredor
        cur.execute("""
            SELECT * FROM transportadoras 
            WHERE corredor_alvo = ? OR corredor = ?
        """, (args.corredor, args.corredor))
        t_rows = cur.fetchall()

    if args.tipo in ["embarcadores", "ambos"]:
        # Buscar embarcadores do corredor
        cur.execute("""
            SELECT * FROM embarcadores_provaveis 
            WHERE corredor_alvo = ?
        """, (args.corredor,))
        e_rows = cur.fetchall()

    print(f"Registros carregados do banco:")
    print(f"  {len(t_rows):,} transportadoras.")
    print(f"  {len(e_rows):,} embarcadores.")

    # 4. Filtrar candidatas
    candidatos_t = []
    candidatos_e = []

    for r in t_rows:
        if args.only_missing:
            cnae_db = row_get(r, "cnae_principal")
            razao_db = row_get(r, "razao_social")
            if not cnae_db or e_razao_social_ruim(razao_db):
                candidatos_t.append(r)
        else:
            candidatos_t.append(r)

    for r in e_rows:
        prio_db = row_get(r, "prioridade")
        
        # Filtro de prioridade do CLI
        if args.prioridade != "todas":
            prio_clean = prio_db.replace("é", "e").replace("É", "e").lower()
            cli_prio_clean = args.prioridade.lower().replace("é", "e")
            
            # Hierarquia ou igualdade simples
            if cli_prio_clean == "alta" and prio_clean != "alta":
                continue
            elif cli_prio_clean == "media" and prio_clean not in ["alta", "media"]:
                continue
            elif cli_prio_clean == "baixa" and prio_clean not in ["alta", "media", "baixa"]:
                continue

        if args.only_missing:
            cnae_db = row_get(r, "cnae")
            razao_db = row_get(r, "razao_social")
            if not cnae_db or e_razao_social_ruim(razao_db):
                candidatos_e.append(r)
        else:
            candidatos_e.append(r)

    print(f"Candidatos após filtros básicos:")
    print(f"  {len(candidatos_t):,} transportadoras elegíveis.")
    print(f"  {len(candidatos_e):,} embarcadores elegíveis.")

    # 5. Atribuir Ranks de Prioridade e Ordenar Fila Unificada
    # Ranks:
    # 1: Embarcador Alta
    # 2: Transportadora Perfil Logístico Forte
    # 3: Embarcador Média
    # 4: Transportadora Restante (neutra/fraca)
    # 5: Embarcador Baixa
    
    fila = []
    
    for r in candidatos_e:
        prio = row_get(r, "prioridade", "Baixa")
        prio_c = prio.replace("é", "e").replace("É", "e").lower()
        
        if prio_c == "alta":
            rank = 1
        elif prio_c == "media":
            rank = 3
        else:
            rank = 5
            
        fila.append((rank, "embarcador", r))

    for r in candidatos_t:
        forte = classificar_perfil_forte(r)
        if forte:
            rank = 2
        else:
            rank = 4
            
        # Se preferir-transportadoras-puras estiver ativo e for transportadora logistica forte, 
        # podemos favorecer ainda mais no desempate da fila
        fila.append((rank, "transportadora", r))

    # Ordenar fila por Rank (menor rank = prioridade maior)
    # Em caso de empate, mantemos a ordem de score de demanda/tamanho ou banco
    fila.sort(key=lambda x: x[0])

    total_fila = len(fila)
    print(f"Fila unificada priorizada construída com {total_fila:,} CNPJs.")
    print("-" * 60)

    # 6. Processamento
    consultados_api = 0
    lidos_cache = 0
    pulados_completos = 0
    atualizados_t = 0
    atualizados_e = 0
    erros = 0
    rate_limited = False

    campos_preenchidos = Counter()
    
    agora_iso = datetime.now(timezone.utc).isoformat()
    data_consulta = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")

    for rank, tipo, row_db in fila:
        if consultados_api >= args.limit:
            print(f"Limite máximo de consultas API atingido ({args.limit}). Finalizando.")
            break

        cnpj_raw = row_get(row_db, "cnpj")
        cnpj_limpo = limpar_cnpj(cnpj_raw)
        if not cnpj_limpo:
            continue

        dados_api = None
        status_code = None

        # 6.1 Verificar Cache
        if cnpj_limpo in cache:
            cache_item = cache[cnpj_limpo]
            status_code = cache_item.get("status")
            dados_api = cache_item.get("dados")
            lidos_cache += 1
        else:
            # 6.2 Consultar API
            print(f"  [Rank {rank}] Consultando API para {cnpj_limpo} ({tipo})...")
            status_code, dados_api = consultar_brasilapi(cnpj_limpo, sleep_time=args.sleep)
            consultados_api += 1

            if status_code == 429:
                print("=" * 60)
                print("AVISO: RATE LIMIT 429 DETECTADO! Parando pipeline com segurança.")
                print("=" * 60)
                rate_limited = True
                break

            if not args.dry_run:
                salvar_no_cache(cnpj_limpo, status_code, dados_api)

        # 6.3 Atualizar dados no banco
        if status_code == 200 and dados_api:
            # Extrair dados limpos da API
            razao_api = safe_str(dados_api.get("razao_social"))
            fantasia_api = safe_str(dados_api.get("nome_fantasia"))
            cnae_api = safe_str(dados_api.get("cnae_fiscal"))
            
            secundarios = [safe_str(c.get("codigo")) for c in dados_api.get("cnaes_secundarios", []) if c.get("codigo")]
            cnaes_secundarios_api = ",".join(secundarios)
            
            situacao_api = safe_str(dados_api.get("descricao_situacao_cadastral"))
            porte_api = safe_str(dados_api.get("porte"))
            natureza_api = safe_str(dados_api.get("natureza_juridica"))
            
            try:
                capital_api = float(dados_api.get("capital_social", 0.0) or 0.0)
            except Exception:
                capital_api = 0.0
                
            socios_api = ", ".join(safe_str(s.get("nome_socio")) for s in dados_api.get("qsa", []) if s.get("nome_socio"))
            cnae_desc_api = safe_str(dados_api.get("cnae_fiscal_descricao"))

            logradouro_api = safe_str(dados_api.get("logradouro"))
            bairro_api = safe_str(dados_api.get("bairro"))
            cep_api = safe_str(dados_api.get("cep"))
            cidade_api = safe_str(dados_api.get("municipio"))
            uf_api = safe_str(dados_api.get("uf")).upper()

            ddd_tel = safe_str(dados_api.get("ddd_telefone_1"))
            tel_api = safe_str(dados_api.get("telefone_1"))
            telefone_api = f"({ddd_tel}) {tel_api}" if ddd_tel and tel_api else ""
            email_api = safe_str(dados_api.get("email"))

            # Notas Cadastrais
            nota_enrich = (
                f"[BrasilAPI {data_consulta}]: Situação: {situacao_api} | "
                f"Porte: {porte_api} | Natureza Jurídica: {natureza_api} | "
                f"Capital Social: R$ {capital_api:,.2f} | Sócios: {socios_api}"
            )

            # --- ATUALIZAR TRANSPORTADORA ---
            if tipo == "transportadora":
                t_id = row_get(row_db, "id")
                notas_db = row_get(row_db, "notas")
                razao_db = row_get(row_db, "razao_social")
                fantasia_db = row_get(row_db, "nome_fantasia")
                cnae_db = row_get(row_db, "cnae_principal")
                tel_db = row_get(row_db, "telefone")
                email_db = row_get(row_db, "email")
                cidade_db = row_get(row_db, "municipio")
                uf_db = row_get(row_db, "uf")
                cep_db = row_get(row_db, "cep")
                fonte_db = row_get(row_db, "corredor") or "RNTRC"

                # 1. Razão Social
                razao_final = razao_db
                if e_razao_social_ruim(razao_db) and razao_api:
                    razao_final = razao_api
                    campos_preenchidos["t_razao_social"] += 1

                # 2. Nome Fantasia
                fantasia_final = fantasia_db
                if not fantasia_db and fantasia_api:
                    fantasia_final = fantasia_api
                    campos_preenchidos["t_nome_fantasia"] += 1

                # 3. CNAE
                cnae_final = cnae_db
                if not cnae_db and cnae_api:
                    cnae_final = cnae_api
                    campos_preenchidos["t_cnae"] += 1

                cnaes_secundarios_final = row_get(row_db, "cnaes_secundarios")
                if not cnaes_secundarios_final and cnaes_secundarios_api:
                    cnaes_secundarios_final = cnaes_secundarios_api

                # Recalcular tem_cnae_frete
                CNAES_FRETE = {"4930201", "4930202", "4930203", "4930204"}
                cnaes_completos = [cnae_final] + secundarios
                tem_cnae_frete_final = bool(CNAES_FRETE & set(cnaes_completos))

                # 4. Contatos (somente se vazio)
                tel_final = tel_db if tel_db else telefone_api
                if not tel_db and telefone_api:
                    campos_preenchidos["t_telefone"] += 1

                email_final = email_db if email_db else email_api
                if not email_db and email_api:
                    campos_preenchidos["t_email"] += 1

                # 5. Localização (somente se vazio)
                cidade_final = cidade_db if cidade_db else cidade_api
                if not cidade_db and cidade_api:
                    campos_preenchidos["t_cidade"] += 1

                uf_final = uf_db if uf_db else uf_api
                if not uf_db and uf_api:
                    campos_preenchidos["t_uf"] += 1

                cep_final = cep_db if cep_db else cep_api
                if not cep_db and cep_api:
                    campos_preenchidos["t_cep"] += 1

                # Divergências
                divergencias = []
                if cep_api and cep_db and cep_api.replace("-", "") != cep_db.replace("-", ""):
                    divergencias.append(f"CEP API ({cep_api}) != DB ({cep_db})")
                if uf_api and uf_db and uf_api.upper() != uf_db.upper():
                    divergencias.append(f"UF API ({uf_api}) != DB ({uf_db})")
                if cidade_api and cidade_db:
                    if normalizar_texto(cidade_api) != normalizar_texto(cidade_db):
                        divergencias.append(f"Cidade API ({cidade_api}) != DB ({cidade_db})")

                # Registrar qualidade logística nas notas
                forte = classificar_perfil_forte(row_db)
                nota_qualidade = "Qualidade Logística: Forte" if forte else "Qualidade Logística: Neutra"
                
                novas_notas = notas_db
                if nota_enrich not in novas_notas:
                    novas_notas = (novas_notas + "\n" + nota_enrich).strip()
                if nota_qualidade not in novas_notas:
                    novas_notas = (novas_notas + "\n" + nota_qualidade).strip()
                if divergencias:
                    nota_div = f"[Divergência BrasilAPI {data_consulta}]: " + " | ".join(divergencias)
                    if nota_div not in novas_notas:
                        novas_notas = (novas_notas + "\n" + nota_div).strip()

                # Fonte
                fontes = [f.strip() for f in (fonte_db or "RNTRC").split(",") if f.strip()]
                if "BrasilAPI" not in fontes:
                    fontes.append("BrasilAPI")
                fonte_final = ", ".join(fontes)

                # Montar UPDATE dinâmico
                fields = []
                vals = []

                if table_has_col(t_cols, "razao_social"):
                    fields.append("razao_social = ?")
                    vals.append(razao_final)
                if table_has_col(t_cols, "nome_fantasia"):
                    fields.append("nome_fantasia = ?")
                    vals.append(fantasia_final)
                if table_has_col(t_cols, "cnae_principal"):
                    fields.append("cnae_principal = ?")
                    vals.append(cnae_final)
                if table_has_col(t_cols, "cnaes_secundarios"):
                    fields.append("cnaes_secundarios = ?")
                    vals.append(cnaes_secundarios_final)
                if table_has_col(t_cols, "tem_cnae_frete"):
                    fields.append("tem_cnae_frete = ?")
                    vals.append(tem_cnae_frete_final)
                if table_has_col(t_cols, "telefone"):
                    fields.append("telefone = ?")
                    vals.append(tel_final)
                if table_has_col(t_cols, "email"):
                    fields.append("email = ?")
                    vals.append(email_final)
                if table_has_col(t_cols, "municipio"):
                    fields.append("municipio = ?")
                    vals.append(cidade_final)
                if table_has_col(t_cols, "uf"):
                    fields.append("uf = ?")
                    vals.append(uf_final)
                if table_has_col(t_cols, "cep"):
                    fields.append("cep = ?")
                    vals.append(cep_final)
                if table_has_col(t_cols, "corredor"):
                    fields.append("corredor = ?")
                    vals.append(fonte_final)
                if table_has_col(t_cols, "notas"):
                    fields.append("notas = ?")
                    vals.append(novas_notas)
                if table_has_col(t_cols, "atualizado_em"):
                    fields.append("atualizado_em = ?")
                    vals.append(agora_iso)

                if fields and not args.dry_run:
                    query = f"UPDATE transportadoras SET {', '.join(fields)} WHERE id = ?"
                    vals.append(t_id)
                    cur.execute(query, tuple(vals))
                
                atualizados_t += 1

            # --- ATUALIZAR EMBARCADOR ---
            elif tipo == "embarcador":
                e_id = row_get(row_db, "id")
                notas_db = row_get(row_db, "notas")
                razao_db = row_get(row_db, "razao_social")
                fantasia_db = row_get(row_db, "nome_fantasia")
                cnae_db = row_get(row_db, "cnae")
                cnae_desc_db = row_get(row_db, "cnae_descricao")
                tel_db = row_get(row_db, "telefone")
                email_db = row_get(row_db, "email")
                site_db = row_get(row_db, "site")
                cidade_db = row_get(row_db, "cidade")
                uf_db = row_get(row_db, "uf")
                cep_db = row_get(row_db, "cep")
                fonte_db = row_get(row_db, "fonte") or "Importação CSV"

                # 1. Razão Social
                razao_final = razao_db
                if e_razao_social_ruim(razao_db) and razao_api:
                    razao_final = razao_api
                    campos_preenchidos["e_razao_social"] += 1

                # 2. Nome Fantasia
                fantasia_final = fantasia_db
                if not fantasia_db and fantasia_api:
                    fantasia_final = fantasia_api
                    campos_preenchidos["e_nome_fantasia"] += 1

                # 3. CNAE
                cnae_final = cnae_db
                if not cnae_db and cnae_api:
                    cnae_final = cnae_api
                    campos_preenchidos["e_cnae"] += 1

                cnae_desc_final = cnae_desc_db
                if not cnae_desc_db and cnae_desc_api:
                    cnae_desc_final = cnae_desc_api
                    campos_preenchidos["e_cnae_desc"] += 1

                # 4. Contatos
                tel_final = tel_db if tel_db else telefone_api
                if not tel_db and telefone_api:
                    campos_preenchidos["e_telefone"] += 1

                email_final = email_db if email_db else email_api
                if not email_db and email_api:
                    campos_preenchidos["e_email"] += 1

                site_final = site_db if site_db else ""

                # 5. Localização
                cidade_final = cidade_db if cidade_db else cidade_api
                if not cidade_db and cidade_api:
                    campos_preenchidos["e_cidade"] += 1

                uf_final = uf_db if uf_db else uf_api
                if not uf_db and uf_api:
                    campos_preenchidos["e_uf"] += 1

                cep_final = cep_db if cep_db else cep_api
                if not cep_db and cep_api and table_has_col(e_cols, "cep"):
                    campos_preenchidos["e_cep"] += 1

                # Divergências
                divergencias = []
                if cep_api and cep_db and cep_api.replace("-", "") != cep_db.replace("-", ""):
                    divergencias.append(f"CEP API ({cep_api}) != DB ({cep_db})")
                if uf_api and uf_db and uf_api.upper() != uf_db.upper():
                    divergencias.append(f"UF API ({uf_api}) != DB ({uf_db})")
                if cidade_api and cidade_db:
                    if normalizar_texto(cidade_api) != normalizar_texto(cidade_db):
                        divergencias.append(f"Cidade API ({cidade_api}) != DB ({cidade_db})")

                novas_notas = notas_db
                if nota_enrich not in novas_notas:
                    novas_notas = (novas_notas + "\n" + nota_enrich).strip()
                if divergencias:
                    nota_div = f"[Divergência BrasilAPI {data_consulta}]: " + " | ".join(divergencias)
                    if nota_div not in novas_notas:
                        novas_notas = (novas_notas + "\n" + nota_div).strip()

                if not table_has_col(e_cols, "cep") and cep_api:
                    nota_cep = f"CEP BrasilAPI: {cep_api}"
                    if nota_cep not in novas_notas:
                        novas_notas = (novas_notas + "\n" + nota_cep).strip()

                # Fonte
                fontes = [f.strip() for f in (fonte_db or "Importação CSV").split(",") if f.strip()]
                if "BrasilAPI" not in fontes:
                    fontes.append("BrasilAPI")
                fonte_final = ", ".join(fontes)

                # 6. Reclassificar e Recalcular Score de Demanda
                mock_dict = {
                    "razao_social": razao_final,
                    "nome_fantasia": fantasia_final,
                    "cnae_descricao": cnae_desc_final,
                    "cidade": cidade_final,
                    "uf": uf_final,
                    "origem_provavel": row_get(row_db, "origem_provavel"),
                    "destino_provavel": row_get(row_db, "destino_provavel"),
                    "corredor_alvo": row_get(row_db, "corredor_alvo"),
                    "status_crm": row_get(row_db, "status_crm"),
                    "telefone": tel_final,
                    "email": email_final,
                    "site": site_final,
                    "notas": novas_notas
                }
                mock_emb = EmbarcadorMock(mock_dict)
                eval_res = avaliar_embarcador(mock_emb)

                # Extrair reclassificação
                setor_predito_final = eval_res["setor_predito"]
                tipo_carga_final = eval_res["tipo_carga_provavel"]
                score_demanda_final = eval_res["score_total"]
                prioridade_final = eval_res["prioridade"]
                carrocerias_final = eval_res["carrocerias_provaveis"]

                # Montar UPDATE dinâmico
                fields = []
                vals = []

                if table_has_col(e_cols, "razao_social"):
                    fields.append("razao_social = ?")
                    vals.append(razao_final)
                if table_has_col(e_cols, "nome_fantasia"):
                    fields.append("nome_fantasia = ?")
                    vals.append(fantasia_final)
                if table_has_col(e_cols, "cnae"):
                    fields.append("cnae = ?")
                    vals.append(cnae_final)
                if table_has_col(e_cols, "cnae_descricao"):
                    fields.append("cnae_descricao = ?")
                    vals.append(cnae_desc_final)
                if table_has_col(e_cols, "telefone"):
                    fields.append("telefone = ?")
                    vals.append(tel_final)
                if table_has_col(e_cols, "email"):
                    fields.append("email = ?")
                    vals.append(email_final)
                if table_has_col(e_cols, "site"):
                    fields.append("site = ?")
                    vals.append(site_final)
                if table_has_col(e_cols, "cidade"):
                    fields.append("cidade = ?")
                    vals.append(cidade_final)
                if table_has_col(e_cols, "uf"):
                    fields.append("uf = ?")
                    vals.append(uf_final)
                if table_has_col(e_cols, "cep"):
                    fields.append("cep = ?")
                    vals.append(cep_final)
                if table_has_col(e_cols, "fonte"):
                    fields.append("fonte = ?")
                    vals.append(fonte_final)
                if table_has_col(e_cols, "notas"):
                    fields.append("notas = ?")
                    vals.append(novas_notas)
                if table_has_col(e_cols, "setor_predito"):
                    fields.append("setor_predito = ?")
                    vals.append(setor_predito_final)
                if table_has_col(e_cols, "tipo_carga_provavel"):
                    fields.append("tipo_carga_provavel = ?")
                    vals.append(tipo_carga_final)
                if table_has_col(e_cols, "carrocerias_provaveis"):
                    fields.append("carrocerias_provaveis = ?")
                    vals.append(carrocerias_final)
                if table_has_col(e_cols, "score_demanda"):
                    fields.append("score_demanda = ?")
                    vals.append(score_demanda_final)
                if table_has_col(e_cols, "prioridade"):
                    fields.append("prioridade = ?")
                    vals.append(prioridade_final)
                if table_has_col(e_cols, "updated_at"):
                    fields.append("updated_at = ?")
                    vals.append(agora_iso)

                if fields and not args.dry_run:
                    query = f"UPDATE embarcadores_provaveis SET {', '.join(fields)} WHERE id = ?"
                    vals.append(e_id)
                    cur.execute(query, tuple(vals))

                atualizados_e += 1
        else:
            erros += 1

    if not args.dry_run:
        conn.commit()

    # 7. Relatório Final de Setores e Fontes
    # Estatísticas de setores pós-enriquecimento
    cur.execute("SELECT setor_predito, COUNT(*) FROM embarcadores_provaveis WHERE corredor_alvo = ? GROUP BY setor_predito ORDER BY COUNT(*) DESC", (args.corredor,))
    top_setores = cur.fetchall()

    # Total com BrasilAPI na fonte por corredor
    cur.execute("SELECT COUNT(*) FROM transportadoras WHERE (corredor_alvo = ? OR corredor = ?) AND corredor LIKE '%BrasilAPI%'", (args.corredor, args.corredor))
    transp_brasilapi = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM embarcadores_provaveis WHERE corredor_alvo = ? AND fonte LIKE '%BrasilAPI%'", (args.corredor,))
    emb_brasilapi = cur.fetchone()[0]

    conn.close()

    # Imprimir Relatório
    print()
    print("=" * 60)
    print("RELATÓRIO FINAL DE ENRIQUECIMENTO PRÉ-MATCH")
    print("=" * 60)
    print(f"Corredor processado:            {args.corredor}")
    print(f"Tipo processado:                {args.tipo}")
    print(f"Total candidatos na fila:       {total_fila:,}")
    print(f"Lidos do Cache Local:           {lidos_cache:,}")
    print(f"Consultados na API:             {consultados_api:,}")
    print(f"Transportadoras atualizadas:    {atualizados_t:,}")
    print(f"Embarcadores atualizados:       {atualizados_e:,}")
    print(f"Pulados por estarem completos:  {pulados_completos:,}")
    print(f"Falhas/Erros (ex: 404):         {erros:,}")
    print(f"Rate Limit 429 atingido:        {'Sim' if rate_limited else 'Não'}")
    print("-" * 60)
    print("Campos preenchidos/corrigidos:")
    for campo, count in sorted(campos_preenchidos.items()):
        print(f"  - {campo:<25}: {count:,}")
    print("-" * 60)
    print("Distribuição de Setores dos Embarcadores do Corredor:")
    for row in top_setores[:8]:
        print(f"  - {row[0] or 'indefinido':<25}: {row[1]:,} embarcadores")
    print("-" * 60)
    print("Total com tag 'BrasilAPI' no corredor:")
    print(f"  - Transportadoras: {transp_brasilapi:,}")
    print(f"  - Embarcadores:    {emb_brasilapi:,}")
    print("=" * 60)


if __name__ == "__main__":
    main()
