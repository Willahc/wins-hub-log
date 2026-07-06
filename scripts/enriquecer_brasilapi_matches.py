#!/usr/bin/env python3
"""
enriquecer_brasilapi_matches.py
================================
Enriquece dados cadastrais das transportadoras e dos embarcadores
presentes nos matches preditivos de um corredor específico via BrasilAPI.

Uso:
python scripts/enriquecer_brasilapi_matches.py --corredor "MS->PR" --limit 100 --sleep 1.0 --only-missing
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
from datetime import datetime
from pathlib import Path

# Adiciona a raiz do projeto ao path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

from config import Config

CACHE_PATH = PROJECT_ROOT / "instance" / "cache_brasilapi_cnpj.jsonl"
DB_PATH = PROJECT_ROOT / "instance" / "local.db"
if not DB_PATH.exists():
    DB_PATH = PROJECT_ROOT / "local.db"


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
    # Se contiver CPF ou CNPJ formatado no início, comum nos dados do RNTRC
    m = re.match(r"^[\d\.\-\/]{6,}", razao.strip())
    if m:
        return True
    # Se for igual a string vazia ou traços
    if razao.strip() in ["", "-", "—", "None"]:
        return True
    return False


def safe_str(val):
    if val is None:
        return ""
    return str(val).strip()


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
                        # Indexa pelo CNPJ limpo para correspondência rápida
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
        "consultado_em": datetime.utcnow().isoformat()
    }
    with open(CACHE_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(item) + "\n")


# ─── Requisições à API ─────────────────────────────────────────────────────────

def consultar_brasilapi(cnpj, sleep_time=1.0):
    cnpj_limpo = limpar_cnpj(cnpj)
    url = f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}"
    headers = {"User-Agent": "WiNS-Hub-Enricher/1.0"}
    
    # Respeitar sleep
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
    parser = argparse.ArgumentParser(description="Enriquece seletivamente CNPJs dos matches preditivos via BrasilAPI.")
    parser.add_argument("--corredor", required=True, help="Corredor alvo (ex: 'MS->PR')")
    parser.add_argument("--limit", type=int, default=100, help="Limite máximo de consultas à API (default: 100)")
    parser.add_argument("--sleep", type=type(1.0), default=1.0, help="Sleep entre chamadas da API (default: 1.0)")
    parser.add_argument("--only-missing", action="store_true", help="Apenas CNPJs com dados faltantes (sem CNAE ou Razão Social ruim)")
    parser.add_argument("--dry-run", action="store_true", help="Modo simulação (não grava alterações no banco nem no cache)")

    args = parser.parse_args()

    print("=" * 60)
    print("ENRIQUECIMENTO SELETIVO BRASILAPI - MATCHES")
    print("=" * 60)
    print(f"Corredor:              {args.corredor}")
    print(f"Limite consultas API:  {args.limit}")
    print(f"Intervalo (sleep):     {args.sleep}s")
    print(f"Apenas faltantes:      {args.only_missing}")
    print(f"Modo Simulação:        {args.dry_run}")
    print("-" * 60)

    if not DB_PATH.exists():
        print(f"ERRO: Banco de dados não encontrado em {DB_PATH}!", file=sys.stderr)
        sys.exit(1)

    # 1. Carregar cache local
    cache = carregar_cache_local()
    print(f"Cache local carregado: {len(cache):,} registros.")

    # 2. Conectar ao banco de dados e carregar CNPJs candidatos dos matches
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Buscar matches preditivos do corredor
    cur.execute("""
        SELECT transportadora_id, embarcador_id 
        FROM matches_preditivos 
        WHERE corredor = ?
    """, (args.corredor,))
    matches = cur.fetchall()

    if not matches:
        print(f"Nenhum match encontrado para o corredor {args.corredor}.")
        conn.close()
        sys.exit(0)

    t_ids = list(set(m["transportadora_id"] for m in matches if m["transportadora_id"]))
    e_ids = list(set(m["embarcador_id"] for m in matches if m["embarcador_id"]))

    print(f"Encontrados nos matches {args.corredor}:")
    print(f"  {len(t_ids)} transportadoras únicas.")
    print(f"  {len(e_ids)} embarcadores únicos.")

    # Carregar transportadoras
    t_rows = []
    if t_ids:
        placeholders = ",".join("?" for _ in t_ids)
        t_rows = cur.execute(f"""
            SELECT * FROM transportadoras WHERE id IN ({placeholders})
        """, t_ids).fetchall()

    # Carregar embarcadores
    e_rows = []
    if e_ids:
        placeholders = ",".join("?" for _ in e_ids)
        e_rows = cur.execute(f"""
            SELECT * FROM embarcadores_provaveis WHERE id IN ({placeholders})
        """, e_ids).fetchall()

    # Filtrar candidatos
    candidatos_t = []
    candidatos_e = []

    for r in t_rows:
        cnpj_l = limpar_cnpj(r["cnpj"])
        if args.only_missing:
            # Considerado faltando se CNAE principal estiver vazio ou a razão social for ruim (padrão RNTRC)
            if not r["cnae_principal"] or e_razao_social_ruim(r["razao_social"]):
                candidatos_t.append(r)
        else:
            candidatos_t.append(r)

    for r in e_rows:
        cnpj_l = limpar_cnpj(r["cnpj"])
        if args.only_missing:
            if not r["cnae"] or e_razao_social_ruim(r["razao_social"]):
                candidatos_e.append(r)
        else:
            candidatos_e.append(r)

    print(f"Candidatos após filtros:")
    print(f"  {len(candidatos_t)} transportadoras candidatas.")
    print(f"  {len(candidatos_e)} embarcadores candidatos.")
    
    # Unificar CNPJs candidatos
    cnpjs_candidatos = {}
    for r in candidatos_t:
        cnpjs_candidatos[limpar_cnpj(r["cnpj"])] = ("transportadora", r)
    for r in candidatos_e:
        # Se coincidir (raro), o tipo do embarcador sobressai ou processa ambos
        cnpjs_candidatos[limpar_cnpj(r["cnpj"])] = ("embarcador", r)

    print(f"Total de CNPJs únicos a processar: {len(cnpjs_candidatos):,}")
    print("-" * 60)

    # 3. Processar CNPJs
    consultados_api = 0
    lidos_cache = 0
    atualizados_t = 0
    atualizados_e = 0
    erros = 0
    rate_limited = False

    # Contagem de campos preenchidos
    campos_preenchidos = Counter()
    
    agora_iso = datetime.utcnow().isoformat()
    data_consulta = datetime.utcnow().strftime("%d/%m/%Y %H:%M")

    for cnpj_limpo, (tipo, row_db) in cnpjs_candidatos.items():
        if consultados_api >= args.limit:
            print(f"Limite de consultas à API atingido ({args.limit}). Interrompendo.")
            break

        dados_api = None
        status_code = None

        # Verificar cache
        if cnpj_limpo in cache:
            cache_item = cache[cnpj_limpo]
            status_code = cache_item.get("status")
            dados_api = cache_item.get("dados")
            lidos_cache += 1
        else:
            # Consultar API
            print(f"  Consultando API para CNPJ: {formatar_cnpj(cnpj_limpo)} ({tipo})...")
            status_code, dados_api = consultar_brasilapi(cnpj_limpo, sleep_time=args.sleep)
            consultados_api += 1

            if status_code == 429:
                print("=" * 60)
                print("AVISO: RECEBIDO HTTP 429 (RATE LIMIT) DA BRASILAPI!")
                print("Parando execução para evitar novos bloqueios temporários.")
                print("=" * 60)
                rate_limited = True
                break

            if not args.dry_run:
                # Salvar no cache local
                salvar_no_cache(cnpj_limpo, status_code, dados_api)

        # Se dados válidos, aplicar atualização no banco
        if status_code == 200 and dados_api:
            # Extrair campos da API
            razao_api = safe_str(dados_api.get("razao_social"))
            fantasia_api = safe_str(dados_api.get("nome_fantasia"))
            cnae_api = safe_str(dados_api.get("cnae_fiscal"))
            
            # CNPJ Secundários
            secundarios = [safe_str(c.get("codigo")) for c in dados_api.get("cnaes_secundarios", []) if c.get("codigo")]
            cnaes_secundarios_api = ",".join(secundarios)
            
            # Detalhes Cadastrais
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

            # --- PROCESSAR ATUALIZAÇÃO ---
            if tipo == "transportadora":
                # Resgatar banco original
                t_id = row_db["id"]
                notas_db = row_db["notas"] or ""
                razao_db = row_db["razao_social"] or ""
                fantasia_db = row_db["nome_fantasia"] or ""
                cnae_db = row_db["cnae_principal"] or ""
                tel_db = row_db["telefone"] or ""
                email_db = row_db["email"] or ""
                cidade_db = row_db["municipio"]
                uf_db = row_db["uf"]
                cep_db = row_db["cep"]
                fonte_db = row_db["corredor"] or "RNTRC" # campo corredor no DB e usado como fonte/tag as vezes

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

                cnaes_secundarios_final = row_db["cnaes_secundarios"] or ""
                if not row_db["cnaes_secundarios"] and cnaes_secundarios_api:
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

                novas_notas = notas_db
                if nota_enrich not in novas_notas:
                    novas_notas = (novas_notas + "\n" + nota_enrich).strip()
                if divergencias:
                    nota_div = f"[Divergência BrasilAPI {data_consulta}]: " + " | ".join(divergencias)
                    if nota_div not in novas_notas:
                        novas_notas = (novas_notas + "\n" + nota_div).strip()

                # Fonte
                # Adicionar BrasilAPI sem duplicar
                fontes = [f.strip() for f in (fonte_db or "RNTRC").split(",") if f.strip()]
                if "BrasilAPI" not in fontes:
                    fontes.append("BrasilAPI")
                fonte_final = ", ".join(fontes)

                if not args.dry_run:
                    cur.execute("""
                        UPDATE transportadoras
                        SET razao_social = ?, nome_fantasia = ?, cnae_principal = ?, 
                            cnaes_secundarios = ?, tem_cnae_frete = ?,
                            telefone = ?, email = ?, municipio = ?, uf = ?, cep = ?, 
                            corredor = ?, notas = ?, atualizado_em = ?
                        WHERE id = ?
                    """, (razao_final, fantasia_final, cnae_final, cnaes_secundarios_final,
                          tem_cnae_frete_final, tel_final, email_final, cidade_final,
                          uf_final, cep_final, fonte_final, novas_notas, agora_iso, t_id))
                
                atualizados_t += 1

            elif tipo == "embarcador":
                # Resgatar banco original
                e_id = row_db["id"]
                notas_db = row_db["notas"] or ""
                razao_db = row_db["razao_social"] or ""
                fantasia_db = row_db["nome_fantasia"] or ""
                cnae_db = row_db["cnae"] or ""
                cnae_desc_db = row_db["cnae_descricao"] or ""
                tel_db = row_db["telefone"] or ""
                email_db = row_db["email"] or ""
                site_db = row_db["site"] or ""
                cidade_db = row_db["cidade"]
                uf_db = row_db["uf"]
                cep_db = row_db["cep"]
                fonte_db = row_db["fonte"] or "Importação CSV"

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

                site_final = site_db if site_db else "" # api não retorna site explicitamente no CNPJ v1 geralmente, mas manter

                # 5. Localização
                cidade_final = cidade_db if cidade_db else cidade_api
                if not cidade_db and cidade_api:
                    campos_preenchidos["e_cidade"] += 1

                uf_final = uf_db if uf_db else uf_api
                if not uf_db and uf_api:
                    campos_preenchidos["e_uf"] += 1

                cep_final = cep_db if cep_db else cep_api
                if not cep_db and cep_api:
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

                novas_notas = os.linesep.join([notas_db, nota_enrich]).strip()
                if nota_enrich not in novas_notas:
                    novas_notas = (novas_notas + "\n" + nota_enrich).strip()
                if divergencias:
                    nota_div = f"[Divergência BrasilAPI {data_consulta}]: " + " | ".join(divergencias)
                    if nota_div not in novas_notas:
                        novas_notas = (novas_notas + "\n" + nota_div).strip()

                # Fonte
                fontes = [f.strip() for f in (fonte_db or "Importação CSV").split(",") if f.strip()]
                if "BrasilAPI" not in fontes:
                    fontes.append("BrasilAPI")
                fonte_final = ", ".join(fontes)

                if not args.dry_run:
                    cur.execute("""
                        UPDATE embarcadores_provaveis
                        SET razao_social = ?, nome_fantasia = ?, cnae = ?, cnae_descricao = ?,
                            telefone = ?, email = ?, cidade = ?, uf = ?, cep = ?, 
                            fonte = ?, notas = ?, updated_at = ?
                        WHERE id = ?
                    """, (razao_final, fantasia_final, cnae_final, cnae_desc_final,
                          tel_final, email_final, cidade_final, uf_final, cep_final,
                          fonte_final, novas_notas, agora_iso, e_id))
                
                atualizados_e += 1

        else:
            erros += 1

    if not args.dry_run:
        conn.commit()

    conn.close()

    # Relatório Final
    print()
    print("=" * 60)
    print("RELATÓRIO DE ENRIQUECIMENTO BRASILAPI")
    print("=" * 60)
    print(f"Total de CNPJs Candidatos:       {len(cnpjs_candidatos):>6,}")
    print(f"Lidos do Cache Local:             {lidos_cache:>6,}")
    print(f"Consultados na API:               {consultados_api:>6,}")
    print(f"Transportadoras Atualizadas:      {atualizados_t:>6,}")
    print(f"Embarcadores Atualizados:         {atualizados_e:>6,}")
    print(f"Falhas/Erros Cadastrais (ex: 404):{erros:>6,}")
    print(f"Bloqueado por Rate Limit (429):   {'Sim' if rate_limited else 'Não'}")
    print("-" * 60)
    print("Campos Preenchidos / Corrigidos:")
    for campo, count in sorted(campos_preenchidos.items()):
        print(f"  - {campo:<25}: {count:,}")
    print("=" * 60)


if __name__ == "__main__":
    main()
