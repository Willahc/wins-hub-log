from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Index, text

db = SQLAlchemy()

class Transportadora(db.Model):
    __tablename__ = "transportadoras"

    id             = db.Column(db.Integer, primary_key=True)
    cnpj           = db.Column(db.String(18), unique=True, nullable=False, index=True)
    nome_rntrc     = db.Column(db.Text)
    razao_social   = db.Column(db.Text)
    nome_fantasia  = db.Column(db.Text)
    municipio      = db.Column(db.String(100), index=True)
    uf             = db.Column(db.String(2), index=True)
    corredor       = db.Column(db.String(20), index=True)
    telefone       = db.Column(db.String(50))
    email          = db.Column(db.String(150))
    socios         = db.Column(db.Text)
    cnae_principal = db.Column(db.String(10))
    tem_cnae_frete = db.Column(db.Boolean, default=False)
    cnaes_secundarios = db.Column(db.Text)
    porte          = db.Column(db.String(50))
    capital_social = db.Column(db.Float)
    situacao_rf    = db.Column(db.String(50))
    numero_rntrc   = db.Column(db.String(20))
    logradouro     = db.Column(db.Text)
    bairro         = db.Column(db.String(100))
    cep            = db.Column(db.String(10))
    data_abertura  = db.Column(db.String(10))

    # CRM
    status_crm     = db.Column(db.String(20), default="nao_contatada", index=True)
    notas          = db.Column(db.Text)
    ultimo_contato = db.Column(db.DateTime)

    criado_em      = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_em  = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id":             self.id,
            "cnpj":           self.cnpj,
            "nome":           self.razao_social or self.nome_rntrc,
            "municipio":      self.municipio,
            "uf":             self.uf,
            "corredor":       self.corredor,
            "telefone":       self.telefone or "",
            "email":          self.email or "",
            "socios":         self.socios or "",
            "cnae":           self.cnae_principal or "",
            "tem_cnae_frete": self.tem_cnae_frete,
            "porte":          self.porte or "",
            "status_crm":     self.status_crm,
            "notas":          self.notas or "",
            "link_cnpjws":    f"https://www.cnpj.ws/{self.cnpj.replace('.','').replace('/','').replace('-','')}",
        }


class ImportLog(db.Model):
    __tablename__ = "import_logs"

    id         = db.Column(db.Integer, primary_key=True)
    corredor   = db.Column(db.String(20))
    status     = db.Column(db.String(20))   # rodando, concluido, erro
    total      = db.Column(db.Integer, default=0)
    processado = db.Column(db.Integer, default=0)
    mensagem   = db.Column(db.Text)
    iniciado   = db.Column(db.DateTime, default=datetime.utcnow)
    finalizado = db.Column(db.DateTime)

    __table_args__ = (
        Index(
            "import_logs_rodando_uniq",
            "corredor",
            unique=True,
            postgresql_where=text("status = 'rodando'"),
        ),
    )


class EmbarcadorProvavel(db.Model):
    __tablename__ = "embarcadores_provaveis"

    id                    = db.Column(db.Integer, primary_key=True)
    cnpj                  = db.Column(db.String(18), nullable=False, index=True)
    razao_social          = db.Column(db.Text)
    nome_fantasia         = db.Column(db.Text)
    cidade                = db.Column(db.String(100), index=True)
    uf                    = db.Column(db.String(2), index=True)
    cnae                  = db.Column(db.String(10))
    cnae_descricao        = db.Column(db.Text)
    setor_predito         = db.Column(db.String(100))
    tipo_carga_provavel   = db.Column(db.String(100))
    carrocerias_provaveis = db.Column(db.Text)
    corredor_alvo         = db.Column(db.String(20), index=True)
    origem_provavel       = db.Column(db.String(100))
    destino_provavel      = db.Column(db.String(100))
    score_demanda         = db.Column(db.Float)
    prioridade            = db.Column(db.String(20))
    fonte                 = db.Column(db.String(100))
    telefone              = db.Column(db.String(50))
    email                 = db.Column(db.String(150))
    site                  = db.Column(db.String(200))
    status_crm            = db.Column(db.String(20), default="nao_contatada", index=True)
    notas                 = db.Column(db.Text)
    created_at            = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at            = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_cnpj_corredor_alvo", "cnpj", "corredor_alvo", unique=True),
    )


class MatchPreditivo(db.Model):
    __tablename__ = "matches_preditivos"

    id                = db.Column(db.Integer, primary_key=True)
    transportadora_id = db.Column(db.Integer, db.ForeignKey("transportadoras.id", ondelete="CASCADE"), nullable=False)
    embarcador_id     = db.Column(db.Integer, db.ForeignKey("embarcadores_provaveis.id", ondelete="CASCADE"), nullable=False)
    corredor          = db.Column(db.String(20), index=True)
    cidade_origem     = db.Column(db.String(100))
    uf_origem         = db.Column(db.String(2))
    cidade_destino    = db.Column(db.String(100))
    uf_destino        = db.Column(db.String(2))
    score_match       = db.Column(db.Float, index=True)
    prioridade        = db.Column(db.String(20))
    score_corredor    = db.Column(db.Float)
    score_localizacao = db.Column(db.Float)
    score_setor       = db.Column(db.Float)
    score_carga       = db.Column(db.Float)
    score_crm         = db.Column(db.Float)
    justificativa     = db.Column(db.Text)
    status            = db.Column(db.String(20), default="Sugerido", index=True)
    notas             = db.Column(db.Text)
    
    # Campos de Cadência Comercial
    temperatura       = db.Column(db.String(20), default="Frio", index=True)
    proxima_acao      = db.Column(db.String(200))
    data_proxima_acao = db.Column(db.String(10), index=True)
    resultado_ultimo  = db.Column(db.String(50))
    
    created_at        = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at        = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relacionamentos
    transportadora    = db.relationship("Transportadora", backref=db.backref("matches_rel", cascade="all, delete-orphan"))
    embarcador        = db.relationship("EmbarcadorProvavel", backref=db.backref("matches_rel", cascade="all, delete-orphan"))

    __table_args__ = (
        Index("idx_match_transp_emb_corr", "transportadora_id", "embarcador_id", "corredor", unique=True),
    )


class ProspeccaoLog(db.Model):
    __tablename__ = "prospeccao_logs"

    id                   = db.Column(db.Integer, primary_key=True)
    match_id             = db.Column(db.Integer, db.ForeignKey("matches_preditivos.id", ondelete="CASCADE"), nullable=False)
    canal                = db.Column(db.String(20), nullable=False)
    destinatario_tipo    = db.Column(db.String(20), nullable=False)
    destinatario_nome    = db.Column(db.String(150))
    destinatario_contato = db.Column(db.String(150))
    mensagem             = db.Column(db.Text)
    status               = db.Column(db.String(20), nullable=False)
    observacao           = db.Column(db.Text)
    
    # Campos de Cadência Comercial
    proxima_acao         = db.Column(db.String(200))
    data_proxima_acao    = db.Column(db.String(10))
    resultado            = db.Column(db.String(50))
    responsavel          = db.Column(db.String(100))
    temperatura          = db.Column(db.String(20))
    
    created_at           = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at           = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relacionamento
    match = db.relationship("MatchPreditivo", backref=db.backref("prospeccoes", cascade="all, delete-orphan"))



