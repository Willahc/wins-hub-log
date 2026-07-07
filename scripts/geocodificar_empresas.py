#!/usr/bin/env python3
import os
import sys
import csv
import unicodedata
from datetime import datetime

# Add root folder to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import Transportadora, EmbarcadorProvavel, MatchPreditivo

IBGE_UF_MAP = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
    "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
    "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR",
    "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF"
}

def normalize_str(s):
    if not s:
        return ""
    s = s.strip().lower()
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )

def main():
    print("============================================================")
    print("GEOCODIFICAÇÃO DE EMPRESAS")
    print("============================================================")
    
    os.makedirs("exports/geografia", exist_ok=True)
    
    # 1. Carregar base local de municípios
    municipios_csv = "scripts/tabela_municipios_rf.csv"
    municipios_dict = {}
    
    if os.path.exists(municipios_csv):
        print(f"  Lendo base local de municípios: {municipios_csv}")
        try:
            with open(municipios_csv, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    ibge = r.get("codigo_ibge", "").strip()
                    nome = r.get("nome", "").strip()
                    lat = r.get("latitude", "").strip()
                    lon = r.get("longitude", "").strip()
                    if ibge and nome and lat and lon:
                        uf_code = ibge[:2]
                        uf = IBGE_UF_MAP.get(uf_code)
                        if uf:
                            key = (normalize_str(nome), uf)
                            municipios_dict[key] = (float(lat), float(lon))
            print(f"    Municípios carregados: {len(municipios_dict):,}")
        except Exception as e:
            print(f"    [Erro] Falha ao carregar municípios: {e}")
            sys.exit(1)
    else:
        print(f"    [Erro] Base de municípios não encontrada em {municipios_csv}")
        sys.exit(1)
        
    # 2. Obter empresas dos matches
    t_ids = set()
    e_ids = set()
    
    # Vamos sempre geocodificar as empresas envolvidas nos matches primeiro
    with app.app_context():
        print("  Buscando empresas participantes de matches...")
        all_matches = MatchPreditivo.query.all()
        for m in all_matches:
            t_ids.add(m.transportadora_id)
            e_ids.add(m.embarcador_id)
            
        print(f"    Fila: {len(t_ids)} transportadoras e {len(e_ids)} embarcadores.")
        
        # 3. Filas de geocodificação externa
        fila_endereco = []
        fila_cep = []
        fila_cidade = []
        
        t_sucessos = 0
        e_sucessos = 0
        
        timestamp_now = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # Geocodificar Transportadoras
        print("  Processando Transportadoras...")
        for t in Transportadora.query.all():
            # Apenas se estiver em matches
            if t.id not in t_ids:
                continue
                
            city = t.municipio
            uf = t.uf
            cep = t.cep
            logradouro = t.logradouro
            bairro = t.bairro
            
            # Verificar se já tem geocodificação de precisão alta
            if t.latitude is not None and t.longitude is not None and t.precisao_geocodificacao == "endereco":
                continue
                
            # Classificar camadas
            has_full_address = bool(logradouro and bairro and city and uf)
            has_cep = bool(cep and len("".join(filter(str.isdigit, cep))) == 8)
            has_city = bool(city and uf)
            
            # Buscar coordenadas do centroide como fallback
            coord = None
            if has_city:
                key = (normalize_str(city), uf)
                coord = municipios_dict.get(key)
                
            # Atualizar registro no banco
            t.geocodificacao_status = "Sucesso" if coord else "Erro"
            t.precisao_geocodificacao = "cidade" if coord else "uf_insuficiente"
            t.fonte_geocodificacao = "tabela_municipios_rf.csv" if coord else ""
            t.data_geocodificacao = timestamp_now
            
            if coord:
                t.latitude = coord[0]
                t.longitude = coord[1]
                t_sucessos += 1
                
            db.session.add(t)
            
            # Adicionar nas filas de refinamento externo
            info = {
                "id": t.id,
                "tipo_empresa": "transportadora",
                "cnpj": t.cnpj,
                "nome": t.razao_social or t.nome_rntrc or t.nome_fantasia or "",
                "cep": cep or "",
                "endereco_completo": t.endereco_completo or "",
                "cidade": city or "",
                "uf": uf or ""
            }
            
            if has_full_address:
                fila_endereco.append(info)
            elif has_cep:
                fila_cep.append(info)
            else:
                fila_cidade.append(info)
                
        # Geocodificar Embarcadores
        print("  Processando Embarcadores...")
        for e in EmbarcadorProvavel.query.all():
            if e.id not in e_ids:
                continue
                
            city = e.cidade
            uf = e.uf
            cep = e.cep
            logradouro = e.logradouro
            bairro = e.bairro
            
            if e.latitude is not None and e.longitude is not None and e.precisao_geocodificacao == "endereco":
                continue
                
            has_full_address = bool(logradouro and bairro and city and uf)
            has_cep = bool(cep and len("".join(filter(str.isdigit, cep))) == 8)
            has_city = bool(city and uf)
            
            coord = None
            if has_city:
                key = (normalize_str(city), uf)
                coord = municipios_dict.get(key)
                
            e.geocodificacao_status = "Sucesso" if coord else "Erro"
            e.precisao_geocodificacao = "cidade" if coord else "uf_insuficiente"
            e.fonte_geocodificacao = "tabela_municipios_rf.csv" if coord else ""
            e.data_geocodificacao = timestamp_now
            
            if coord:
                e.latitude = coord[0]
                e.longitude = coord[1]
                e_sucessos += 1
                
            db.session.add(e)
            
            info = {
                "id": e.id,
                "tipo_empresa": "embarcador",
                "cnpj": e.cnpj,
                "nome": e.razao_social or e.nome_fantasia or "",
                "cep": cep or "",
                "endereco_completo": e.endereco_completo or "",
                "cidade": city or "",
                "uf": uf or ""
            }
            
            if has_full_address:
                fila_endereco.append(info)
            elif has_cep:
                fila_cep.append(info)
            else:
                fila_cidade.append(info)
                
        # Commit das alterações de centroide
        print("  Gravando coordenadas municipais no banco de dados...")
        try:
            from scripts.backup_db import run_backup
            run_backup()
        except Exception as ex:
            print(f"  [Aviso] Falha ao criar backup: {ex}")
            
        db.session.commit()
        
        # 4. Escrever as filas de geocodificação externa em CSV
        print("  Gerando arquivos de fila geográfica...")
        
        fields = ["id", "tipo_empresa", "cnpj", "nome", "cep", "endereco_completo", "cidade", "uf"]
        
        with open("exports/geografia/fila_geocodificacao_endereco.csv", "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields, delimiter=";")
            writer.writeheader()
            writer.writerows(fila_endereco)
            
        with open("exports/geografia/fila_geocodificacao_cep.csv", "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields, delimiter=";")
            writer.writeheader()
            writer.writerows(fila_cep)
            
        with open("exports/geografia/fila_geocodificacao_cidade.csv", "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields, delimiter=";")
            writer.writeheader()
            writer.writerows(fila_cidade)
            
    print("\n=========================================")
    print("GEOCODIFICAÇÃO CONCLUÍDA COM SUCESSO:")
    print(f"  Transportadoras geocodificadas (cidade): {t_sucessos:,}")
    print(f"  Embarcadores geocodificados (cidade):   {e_sucessos:,}")
    print(f"  Fila de Geocodificação de Endereço:      {len(fila_endereco):,} empresas")
    print(f"  Fila de Geocodificação de CEP:           {len(fila_cep):,} empresas")
    print(f"  Fila de Geocodificação de Cidade/Centro: {len(fila_cidade):,} empresas")
    print("=========================================")

if __name__ == "__main__":
    main()
