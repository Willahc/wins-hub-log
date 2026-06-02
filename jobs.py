import io
import time
import threading
import unicodedata
import urllib.request
from datetime import datetime

import pandas as pd
import requests

from config import Config
from models import db, Transportadora, ImportLog


def normalizar(texto: str) -> str:
    if not texto:
        return ""
    nfkd = unicodedata.normalize("NFKD", texto.upper().strip())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def limpar_cnpj(cnpj: str) -> str:
    return "".join(c for c in str(cnpj) if c.isdigit()).zfill(14)


def formatar_cnpj(cnpj: str) -> str:
    c = limpar_cnpj(cnpj)
    if len(c) != 14:
        return cnpj
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:14]}"


def enriquecer_cnpj(cnpj: str) -> dict:
    try:
        url  = Config.BRASILAPI_URL.format(cnpj)
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return {}
        d = resp.json()

        telefone = ""
        if d.get("ddd_telefone_1") and d.get("telefone_1"):
            telefone = f"({d['ddd_telefone_1']}) {d['telefone_1']}"

        cnae_principal = str(d.get("cnae_fiscal", ""))
        cnaes_todos    = [cnae_principal] + [
            str(c.get("codigo", "")) for c in d.get("cnaes_secundarios", [])
        ]

        socios = ", ".join(
            s.get("nome_socio", "") for s in d.get("qsa", [])[:3]
        )

        capital = None
        try:
            capital = float(d.get("capital_social", 0) or 0)
        except Exception:
            pass

        return {
            "razao_social":   d.get("razao_social", ""),
            "nome_fantasia":  d.get("nome_fantasia", ""),
            "situacao_rf":    d.get("descricao_situacao_cadastral", ""),
            "data_abertura":  d.get("data_inicio_atividade", ""),
            "cnae_principal": cnae_principal,
            "tem_cnae_frete": "4930202" in cnaes_todos,
            "logradouro":     d.get("logradouro", ""),
            "bairro":         d.get("bairro", ""),
            "cep":            d.get("cep", ""),
            "telefone":       telefone,
            "email":          d.get("email", ""),
            "porte":          d.get("porte", ""),
            "capital_social": capital,
            "socios":         socios,
        }
    except Exception:
        return {}


def baixar_rntrc() -> pd.DataFrame:
    meta     = requests.get(Config.RNTRC_META_URL, timeout=30).json()
    url_csv  = meta["result"]["url"]
    raw      = urllib.request.urlopen(url_csv).read()
    df       = pd.read_csv(
        io.StringIO(raw.decode("latin-1")),
        sep=";",
        on_bad_lines="skip",
        dtype=str,
    )
    return df


def filtrar_corredor(df: pd.DataFrame, nome_corredor: str) -> pd.DataFrame:
    cfg  = Config.CORREDORES[nome_corredor]
    uf   = cfg["uf_origem"]
    muns = cfg["municipios"]

    df = df[df["situacao_rntrc"] == "ATIVO"].copy()
    df["mun_norm"] = df["municipio"].fillna("").apply(normalizar)

    mask = (
        (df["uf"] == uf)
        & (df["mun_norm"].isin(muns))
        & (df["categoria_transportador"] == "ETC")
        & (~df["cpfcnpjtransportador"].str.contains(r"\*", na=False))
        & (df["cpfcnpjtransportador"].str.len() >= 14)
    )
    return df[mask].copy()


def rodar_importacao(app, corredor: str, log_id: int):
    """Roda em thread separada — baixa RNTRC, filtra e enriquece."""
    with app.app_context():
        log = ImportLog.query.get(log_id)

        try:
            # 1. Baixar RNTRC
            log.mensagem = "Baixando RNTRC..."
            db.session.commit()

            df_rntrc = baixar_rntrc()

            # 2. Filtrar corredor
            log.mensagem = f"Filtrando corredor {corredor}..."
            db.session.commit()

            df = filtrar_corredor(df_rntrc, corredor)
            log.total = len(df)
            db.session.commit()

            # 3. Enriquecer e salvar
            for idx, row in df.iterrows():
                cnpj_raw  = row["cpfcnpjtransportador"]
                cnpj_limpo = limpar_cnpj(cnpj_raw)
                cnpj_fmt   = formatar_cnpj(cnpj_limpo)

                dados = enriquecer_cnpj(cnpj_limpo)
                time.sleep(Config.DELAY_API_S)

                # Upsert
                empresa = Transportadora.query.filter_by(cnpj=cnpj_fmt).first()
                if not empresa:
                    empresa = Transportadora(cnpj=cnpj_fmt)
                    db.session.add(empresa)

                empresa.nome_rntrc     = row.get("nome_transportador", "")
                empresa.numero_rntrc   = row.get("numero_rntrc", "")
                empresa.municipio      = row.get("municipio", "")
                empresa.uf             = row.get("uf", "")
                empresa.corredor       = corredor
                empresa.razao_social   = dados.get("razao_social", "")
                empresa.nome_fantasia  = dados.get("nome_fantasia", "")
                empresa.situacao_rf    = dados.get("situacao_rf", "")
                empresa.data_abertura  = dados.get("data_abertura", "")
                empresa.cnae_principal = dados.get("cnae_principal", "")
                empresa.tem_cnae_frete = dados.get("tem_cnae_frete", False)
                empresa.logradouro     = dados.get("logradouro", "")
                empresa.bairro         = dados.get("bairro", "")
                empresa.cep            = dados.get("cep", "")
                empresa.telefone       = dados.get("telefone", "")
                empresa.email          = dados.get("email", "")
                empresa.porte          = dados.get("porte", "")
                empresa.capital_social = dados.get("capital_social")
                empresa.socios         = dados.get("socios", "")
                empresa.atualizado_em  = datetime.utcnow()

                log.processado += 1
                log.mensagem    = f"Processando {log.processado}/{log.total}..."
                db.session.commit()

            log.status     = "concluido"
            log.mensagem   = f"Importação concluída: {log.total} empresas."
            log.finalizado = datetime.utcnow()
            db.session.commit()

        except Exception as e:
            log.status   = "erro"
            log.mensagem = str(e)
            db.session.commit()


def iniciar_importacao(app, corredor: str) -> int:
    with app.app_context():
        log = ImportLog(corredor=corredor, status="rodando", mensagem="Iniciando...")
        db.session.add(log)
        db.session.commit()
        log_id = log.id

    t = threading.Thread(
        target=rodar_importacao,
        args=(app, corredor, log_id),
        daemon=True,
    )
    t.start()
    return log_id
