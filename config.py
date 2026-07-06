import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY     = os.environ.get("SECRET_KEY", "dev-key-insegura")
    _db_url        = os.environ.get("DATABASE_URL", "sqlite:///local.db")
    DATABASE_URL   = _db_url.replace("postgresql://", "postgresql+psycopg://").replace("postgres://", "postgresql+psycopg://")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
    FLASK_ENV      = os.environ.get("FLASK_ENV", "development")

    CORREDORES = {
        "SP->DF": {
            "uf_origem": "SP",
            "assimetria": "79,2%",
            "municipios": ["SANTA GERTRUDES","GUARULHOS","CAJAMAR","SAO PAULO","BARUERI","CORDEIROPOLIS","LIMEIRA","ARARAS","SUMARE","JUNDIAI","CRAVINHOS","IRACEMAPOLIS"],
        },
        "SC->SP": {
            "uf_origem": "SC",
            "assimetria": "84,3%",
            "municipios": ["JOINVILLE","BLUMENAU","ITAJAI","CHAPECO","CRICIUMA","FLORIANOPOLIS","LAGES","JARAGUA DO SUL","BRUSQUE","CONCORDIA","SAO JOSE"],
        },
        "MS->PR": {
            "uf_origem": "MS",
            "assimetria": "77,7%",
            "municipios": ["CAMPO GRANDE","DOURADOS","TRES LAGOAS","CORUMBA","PARANAIBA","SIDROLANDIA","NOVA ANDRADINA","NAVIRAI"],
        },
        "MG->SP": {
            "uf_origem": "MG",
            "assimetria": "?",
            "municipios": ["UBERLANDIA","UBERABA","ARAGUARI","BETIM","CONTAGEM","SETE LAGOAS","IPATINGA","TIMOTEO","VARGINHA","POUSO ALEGRE","EXTREMA"],
        },
    }

    RNTRC_RESOURCE_ID = "ac349216-d199-4fd5-a34d-ca56fc6bcf19"
    RNTRC_META_URL    = f"https://dados.antt.gov.br/api/3/action/resource_show?id=ac349216-d199-4fd5-a34d-ca56fc6bcf19"
    BRASILAPI_URL     = "https://brasilapi.com.br/api/cnpj/v1/{}"
    # Tempo entre chamadas de API externas (segundos) — usado para evitar bursts
    DELAY_API_S       = 0.4
    # Limite máximo de registros importados e enriquecidos em lote para evitar rate limit
    IMPORT_LIMIT      = int(os.environ.get("IMPORT_LIMIT", 50))
    # Configuráveis para chamadas à BrasilAPI
    BRASILAPI_TIMEOUT = float(os.environ.get("BRASILAPI_TIMEOUT", 10))
    BRASILAPI_MAX_RETRIES = int(os.environ.get("BRASILAPI_MAX_RETRIES", 3))
    BRASILAPI_BACKOFF_FACTOR = float(os.environ.get("BRASILAPI_BACKOFF_FACTOR", 0.5))

    STATUS_CRM = ["nao_contatada","tentativa","contatada","interessada","negociando","cliente","descartada"]
    STATUS_LABELS = {
        "nao_contatada": ("Nao contatada", "secondary"),
        "tentativa":     ("Tentativa",     "warning"),
        "contatada":     ("Contatada",     "info"),
        "interessada":   ("Interessada",   "primary"),
        "negociando":    ("Negociando",    "success"),
        "cliente":       ("Cliente",       "success"),
        "descartada":    ("Descartada",    "danger"),
    }
