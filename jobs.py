import io, time, threading, unicodedata, urllib.request, csv
from datetime import datetime
import requests
from config import Config
from models import db, Transportadora, ImportLog

def normalizar(t):
    if not t: return ""
    nfkd = unicodedata.normalize("NFKD", t.upper().strip())
    return "".join(c for c in nfkd if not unicodedata.combining(c))

def limpar_cnpj(c): return "".join(x for x in str(c) if x.isdigit()).zfill(14)

def formatar_cnpj(c):
    c = limpar_cnpj(c)
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:14]}" if len(c)==14 else c

def enriquecer_cnpj(cnpj):
    try:
        r = requests.get(Config.BRASILAPI_URL.format(cnpj), timeout=10)
        if r.status_code != 200: return {}
        d = r.json()
        tel = f"({d['ddd_telefone_1']}) {d.get('telefone_1','')}" if d.get("ddd_telefone_1") else ""
        cnae = str(d.get("cnae_fiscal",""))
        cnaes = [cnae] + [str(c.get("codigo","")) for c in d.get("cnaes_secundarios",[])]
        socios = ", ".join(s.get("nome_socio","") for s in d.get("qsa",[])[:3])
        capital = None
        try: capital = float(d.get("capital_social",0) or 0)
        except: pass
        return {"razao_social":d.get("razao_social",""),"nome_fantasia":d.get("nome_fantasia",""),
                "situacao_rf":d.get("descricao_situacao_cadastral",""),"data_abertura":d.get("data_inicio_atividade",""),
                "cnae_principal":cnae,"tem_cnae_frete":"4930202" in cnaes,
                "logradouro":d.get("logradouro",""),"bairro":d.get("bairro",""),"cep":d.get("cep",""),
                "telefone":tel,"email":d.get("email",""),"porte":d.get("porte",""),
                "capital_social":capital,"socios":socios}
    except: return {}

def baixar_rntrc():
    meta = requests.get(Config.RNTRC_META_URL, timeout=60).json()
    raw  = urllib.request.urlopen(meta["result"]["url"], timeout=120).read()
    lines = raw.decode("latin-1").splitlines()
    reader = csv.DictReader(lines, delimiter=";")
    return list(reader)

def filtrar_corredor(registros, nome_corredor):
    cfg  = Config.CORREDORES[nome_corredor]
    uf   = cfg["uf_origem"]
    muns = cfg["municipios"]
    out  = []
    for r in registros:
        cnpj = r.get("cpfcnpjtransportador","")
        mun  = normalizar(r.get("municipio",""))
        if (r.get("situacao_rntrc")=="ATIVO" and r.get("uf")==uf
            and r.get("categoria_transportador")=="ETC"
            and mun in muns and "*" not in cnpj and len(cnpj)>=14):
            out.append(r)
    return out

def rodar_importacao(app, corredor, log_id):
    with app.app_context():
        log = ImportLog.query.get(log_id)
        try:
            log.mensagem = "Baixando RNTRC..."; db.session.commit()
            registros = baixar_rntrc()
            log.mensagem = f"Filtrando {corredor}..."; db.session.commit()
            filtrados = filtrar_corredor(registros, corredor)
            log.total = len(filtrados); db.session.commit()
            for row in filtrados:
                cnpj_limpo = limpar_cnpj(row["cpfcnpjtransportador"])
                cnpj_fmt   = formatar_cnpj(cnpj_limpo)
                dados = enriquecer_cnpj(cnpj_limpo)
                time.sleep(Config.DELAY_API_S)
                e = Transportadora.query.filter_by(cnpj=cnpj_fmt).first()
                if not e:
                    e = Transportadora(cnpj=cnpj_fmt); db.session.add(e)
                e.nome_rntrc=row.get("nome_transportador",""); e.numero_rntrc=row.get("numero_rntrc","")
                e.municipio=row.get("municipio",""); e.uf=row.get("uf",""); e.corredor=corredor
                e.razao_social=dados.get("razao_social",""); e.nome_fantasia=dados.get("nome_fantasia","")
                e.situacao_rf=dados.get("situacao_rf",""); e.data_abertura=dados.get("data_abertura","")
                e.cnae_principal=dados.get("cnae_principal",""); e.tem_cnae_frete=dados.get("tem_cnae_frete",False)
                e.logradouro=dados.get("logradouro",""); e.bairro=dados.get("bairro",""); e.cep=dados.get("cep","")
                e.telefone=dados.get("telefone",""); e.email=dados.get("email","")
                e.porte=dados.get("porte",""); e.capital_social=dados.get("capital_social")
                e.socios=dados.get("socios",""); e.atualizado_em=datetime.utcnow()
                log.processado += 1; log.mensagem=f"Processando {log.processado}/{log.total}..."; db.session.commit()
            log.status="concluido"; log.mensagem=f"Concluido: {log.total} empresas."; log.finalizado=datetime.utcnow(); db.session.commit()
        except Exception as ex:
            log.status="erro"; log.mensagem=str(ex); db.session.commit()

def iniciar_importacao(app, corredor):
    with app.app_context():
        log = ImportLog(corredor=corredor, status="rodando", mensagem="Iniciando...")
        db.session.add(log); db.session.commit(); log_id = log.id
    t = threading.Thread(target=rodar_importacao, args=(app, corredor, log_id), daemon=True)
    t.start()
    return log_id
