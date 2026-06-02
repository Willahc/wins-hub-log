from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

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
