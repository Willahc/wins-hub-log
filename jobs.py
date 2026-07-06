import io, time, threading, unicodedata, urllib.request, csv
from datetime import datetime, timedelta
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from sqlalchemy.exc import IntegrityError
from config import Config
from models import db, Transportadora, ImportLog

# logger
logger = logging.getLogger(__name__)
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO)

# requests session with retries configured from Config
session = requests.Session()
retries = Retry(
    total=Config.BRASILAPI_MAX_RETRIES,
    backoff_factor=Config.BRASILAPI_BACKOFF_FACTOR,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=frozenset(['GET','POST','PUT','DELETE','HEAD','OPTIONS'])
)
adapter = HTTPAdapter(max_retries=retries)
session.mount("https://", adapter)
session.mount("http://", adapter)

# simple in-memory metrics
stats = {"brasilapi_errors":0, "brasilapi_rate_limited":0, "brasilapi_success":0}

def normalizar(t):
    if not t: return ""
    nfkd = unicodedata.normalize("NFKD", t.upper().strip())
    return "".join(c for c in nfkd if not unicodedata.combining(c))

def limpar_cnpj(c): return "".join(x for x in str(c) if x.isdigit()).zfill(14)

def formatar_cnpj(c):
    c = limpar_cnpj(c)
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:14]}" if len(c)==14 else c

CNAES_FRETE = {"4930201","4930202","4930203","4930204"}

def enriquecer_cnpj(cnpj):
    """Enriquece dados de um CNPJ via BrasilAPI com retries, backoff e logging.
    Retorna dict com campos ou {} em caso de falha (não lança).
    """
    url = Config.BRASILAPI_URL.format(cnpj)
    try:
        r = session.get(url, timeout=Config.BRASILAPI_TIMEOUT)
        if r.status_code == 200:
            d = r.json()
            tel = f"({d.get('ddd_telefone_1')}) {d.get('telefone_1','')}" if d.get('ddd_telefone_1') else ""
            cnae = str(d.get("cnae_fiscal",""))
            secundarios = [str(c.get("codigo","")) for c in d.get("cnaes_secundarios",[])]
            cnaes = [cnae] + secundarios
            socios = ", ".join(s.get("nome_socio","") for s in d.get("qsa",[]) if s.get("nome_socio"))
            capital = None
            try:
                capital = float(d.get("capital_social",0) or 0)
            except Exception:
                capital = None
            stats["brasilapi_success"] += 1
            return {
                "razao_social": d.get("razao_social",""),
                "nome_fantasia": d.get("nome_fantasia",""),
                "situacao_rf": d.get("descricao_situacao_cadastral",""),
                "data_abertura": d.get("data_inicio_atividade",""),
                "cnae_principal": cnae,
                "tem_cnae_frete": bool(CNAES_FRETE & set(cnaes)),
                "cnaes_secundarios": ",".join(secundarios),
                "logradouro": d.get("logradouro",""),
                "bairro": d.get("bairro",""),
                "cep": d.get("cep",""),
                "telefone": tel,
                "email": d.get("email",""),
                "porte": d.get("porte",""),
                "capital_social": capital,
                "socios": socios,
            }
        elif r.status_code == 429:
            stats["brasilapi_rate_limited"] += 1
            logger.warning("BrasilAPI rate limited (429) for %s", cnpj)
            return {}
        else:
            stats["brasilapi_errors"] += 1
            logger.warning("BrasilAPI returned status %s for %s", r.status_code, cnpj)
            return {}
    except requests.RequestException as ex:
        stats["brasilapi_errors"] += 1
        logger.exception("Error fetching BrasilAPI for %s: %s", cnpj, ex)
        return {}

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
        if not log:
            return
        
        try:
            logger.info("Import started: corredor=%s log_id=%s", corredor, log_id)
            
            # Etapa 1: Iniciado (5%)
            log.progresso = 5
            log.mensagem = "Iniciando importação..."
            db.session.commit()
            
            # Etapa 2: Baixando dados ANTT (10%)
            log.progresso = 10
            log.mensagem = "Baixando dados oficiais RNTRC/ANTT (pode demorar alguns segundos)..."
            db.session.commit()
            
            try:
                registros = baixar_rntrc()
                logger.info("RNTRC downloaded (%s records).", len(registros))
            except Exception as e_down:
                raise Exception(f"Falha ao baixar dados ANTT/RNTRC: {str(e_down)}")
            
            # Etapa 3: Arquivo carregado (25%)
            log.progresso = 25
            log.mensagem = f"Arquivo carregado ({len(registros)} registros brutos)."
            db.session.commit()
            
            # Etapa 4: Filtrando corredor (40%)
            log.progresso = 40
            log.mensagem = f"Filtrando transportadoras do corredor {corredor}..."
            db.session.commit()
            
            filtrados = filtrar_corredor(registros, corredor)
            log.total = len(filtrados)
            db.session.commit()
            logger.info("Filtered %s records for %s", log.total, corredor)
            
            # Aplicando limite configurável para evitar rate-limit
            limite = Config.IMPORT_LIMIT
            if limite and limite > 0:
                logger.info("Applying IMPORT_LIMIT=%s on filtered list", limite)
                processar_lote = filtrados[:limite]
                log.mensagem = f"Filtrado corredor (limitado a {limite} de {log.total} para segurança da API)."
            else:
                processar_lote = filtrados
                log.mensagem = f"Filtrado corredor ({log.total} registros encontrados)."
                
            db.session.commit()
            
            # Etapa 5: Enriquecendo empresas (60% até 85%)
            total_lote = len(processar_lote)
            log.progresso = 60
            db.session.commit()
            
            inseridos = 0
            for idx, row in enumerate(processar_lote, 1):
                # Calcular progresso granular na etapa de enriquecimento
                log.progresso = 60 + int((idx / max(total_lote, 1)) * 25) # Vai de 60 a 85
                log.mensagem = f"Enriquecendo e validando {idx}/{total_lote}..."
                
                cnpj_limpo = limpar_cnpj(row["cpfcnpjtransportador"])
                cnpj_fmt   = formatar_cnpj(cnpj_limpo)
                
                # Enriquecimento via BrasilAPI
                dados = enriquecer_cnpj(cnpj_limpo)
                time.sleep(Config.DELAY_API_S)
                
                e = Transportadora.query.filter_by(cnpj=cnpj_fmt).first()
                if not e:
                    e = Transportadora(cnpj=cnpj_fmt)
                    db.session.add(e)
                    inseridos += 1
                
                # Atualizando dados
                e.nome_rntrc = row.get("nome_transportador", "")
                e.numero_rntrc = row.get("numero_rntrc", "")
                e.municipio = row.get("municipio", "")
                e.uf = row.get("uf", "")
                e.corredor = corredor
                e.razao_social = dados.get("razao_social", e.razao_social or "")
                e.nome_fantasia = dados.get("nome_fantasia", e.nome_fantasia or "")
                e.situacao_rf = dados.get("situacao_rf", e.situacao_rf or "")
                e.data_abertura = dados.get("data_abertura", e.data_abertura or "")
                e.cnae_principal = dados.get("cnae_principal", e.cnae_principal or "")
                e.tem_cnae_frete = dados.get("tem_cnae_frete", e.tem_cnae_frete or False)
                e.cnaes_secundarios = dados.get("cnaes_secundarios", e.cnaes_secundarios or "")
                e.logradouro = dados.get("logradouro", e.logradouro or "")
                e.bairro = dados.get("bairro", e.bairro or "")
                e.cep = dados.get("cep", e.cep or "")
                e.telefone = dados.get("telefone", e.telefone or "")
                e.email = dados.get("email", e.email or "")
                e.porte = dados.get("porte", e.porte or "")
                e.capital_social = dados.get("capital_social", e.capital_social)
                e.socios = dados.get("socios", e.socios or "")
                e.atualizado_em = datetime.utcnow()
                
                log.processado += 1
                log.total_inserido = inseridos
                db.session.commit()
                
            # Etapa 6: Gravando banco e finalizando (85% até 100%)
            log.progresso = 85
            log.mensagem = "Gravando registros finais..."
            db.session.commit()
            
            # Commit final redundante para segurança
            db.session.commit()
            
            log.status = "concluido"
            log.progresso = 100
            log.mensagem = f"Concluído: {total_lote} processados ({inseridos} novos inseridos)."
            log.finalizado = datetime.utcnow()
            db.session.commit()
            logger.info("Import concluded: corredor=%s processed=%s", corredor, log.processado)
            
        except Exception as ex:
            logger.exception("Import failed for corredor=%s: %s", corredor, ex)
            log.status = "erro"
            log.erro = str(ex)
            log.mensagem = f"Erro na importação: {str(ex)}"
            log.finalizado = datetime.utcnow()
            db.session.commit()

STALE_RODANDO_MIN = 30  # job iniciado há > 30 min sem heartbeat = job morto

def iniciar_importacao(app, corredor):
    """Retorna (log_id, ja_rodava). ja_rodava=True quando reaproveitou job em andamento."""
    with app.app_context():
        # Marca como erro jobs zumbis (worker reciclado / Render dormiu durante import)
        cutoff = datetime.utcnow() - timedelta(minutes=STALE_RODANDO_MIN)
        zumbis = ImportLog.query.filter(ImportLog.status == "rodando",
                                        ImportLog.iniciado < cutoff).all()
        for z in zumbis:
            z.status = "erro"
            z.mensagem = (z.mensagem or "") + " [marcado como zumbi automaticamente]"
            z.finalizado = datetime.utcnow()
        if zumbis:
            db.session.commit()

        # Camada 1: check rápido antes de tentar criar
        existing = ImportLog.query.filter_by(corredor=corredor, status="rodando").first()
        if existing:
            return existing.id, True

        # Camada 2: tenta criar; índice unique parcial impede 2º worker no mesmo corredor
        log = ImportLog(corredor=corredor, status="rodando", mensagem="Iniciando...")
        try:
            db.session.add(log)
            db.session.commit()
            log_id = log.id
        except IntegrityError:
            db.session.rollback()
            existing = ImportLog.query.filter_by(corredor=corredor, status="rodando").first()
            return (existing.id, True) if existing else (None, False)

    t = threading.Thread(target=rodar_importacao, args=(app, corredor, log_id), daemon=True)
    t.start()
    return log_id, False
