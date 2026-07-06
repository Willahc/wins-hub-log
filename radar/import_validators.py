import re
from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator

class EmbarcadorImportSchema(BaseModel):
    cnpj: Optional[str] = None
    razao_social: Optional[str] = None
    nome_fantasia: Optional[str] = None
    cidade: str
    uf: Optional[str] = None
    cnae: Optional[str] = None
    cnae_descricao: Optional[str] = None
    telefone: Optional[str] = None
    email: Optional[str] = None
    site: Optional[str] = None
    corredor_alvo: str
    origem_provavel: Optional[str] = None
    destino_provavel: Optional[str] = None
    fonte: Optional[str] = None
    notas: Optional[str] = None

    # Validador executado 'before' (antes da coerção) para limpar strings e converter "" em None
    @field_validator(
        "cnpj", "razao_social", "nome_fantasia", "cidade", "uf", "cnae", 
        "cnae_descricao", "telefone", "email", "site", "corredor_alvo", 
        "origem_provavel", "destino_provavel", "fonte", "notas", 
        mode="before"
    )
    @classmethod
    def trim_and_nullify_strings(cls, v):
        if isinstance(v, str):
            v_stripped = v.strip()
            return v_stripped if v_stripped != "" else None
        return v

    @field_validator("cidade", "corredor_alvo")
    @classmethod
    def check_not_empty(cls, v):
        if v is None:
            raise ValueError("Este campo é obrigatório e não pode ser vazio.")
        return v

    @field_validator("uf")
    @classmethod
    def validate_uf(cls, v):
        if v:
            if len(v) != 2 or not v.isalpha():
                raise ValueError("UF deve conter exatamente 2 letras.")
            return v.upper()
        return v

    @field_validator("cnpj")
    @classmethod
    def normalize_cnpj(cls, v):
        if v:
            # Remove formatação, mantendo apenas números
            digits = re.sub(r"\D", "", v)
            if digits:
                return digits
        return None

    @field_validator("telefone")
    @classmethod
    def normalize_telefone(cls, v):
        if v:
            # Mantém números e o sinal de '+' se houver
            cleaned = re.sub(r"[^\d+]", "", v)
            return cleaned if cleaned else None
        return None

    @field_validator("email")
    @classmethod
    def validate_email_simple(cls, v):
        if v:
            pattern = r"^[\w\.-]+@[\w\.-]+\.\w+$"
            if not re.match(pattern, v):
                raise ValueError("Formato de e-mail inválido.")
            return v.lower()
        return None

    @model_validator(mode="after")
    def check_names_exist(self) -> "EmbarcadorImportSchema":
        if not self.razao_social and not self.nome_fantasia:
            raise ValueError("Razão Social ou Nome Fantasia deve ser preenchido.")
        return self
