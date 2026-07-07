#!/usr/bin/env python3
import os
import sys
import csv
from datetime import datetime

# Add root folder to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import Transportadora, EmbarcadorProvavel, MatchPreditivo

def check_col(model_class, col_name):
    return hasattr(model_class, col_name)

def get_count_safe(model_class, filter_expr):
    try:
        return model_class.query.filter(filter_expr).count()
    except Exception:
        return 0

def main():
    print("============================================================")
    print("AUDITORIA GEOGRÁFICA OFICIAL DE MATCHES")
    print("============================================================")
    
    os.makedirs("exports/geografia", exist_ok=True)
    
    with app.app_context():
        # ─── 1. TRANSPORTADORAS ───
        print("  Auditando Transportadoras...")
        t_total = Transportadora.query.count()
        
        # Presentes em matches
        t_in_matches = db.session.query(Transportadora.id).join(
            MatchPreditivo, MatchPreditivo.transportadora_id == Transportadora.id
        ).distinct().count()
        
        t_cep = get_count_safe(Transportadora, (Transportadora.cep != "") & (Transportadora.cep.isnot(None)))
        t_logradouro = get_count_safe(Transportadora, (Transportadora.logradouro != "") & (Transportadora.logradouro.isnot(None)))
        t_bairro = get_count_safe(Transportadora, (Transportadora.bairro != "") & (Transportadora.bairro.isnot(None)))
        t_municipio = get_count_safe(Transportadora, (Transportadora.municipio != "") & (Transportadora.municipio.isnot(None)))
        t_uf = get_count_safe(Transportadora, (Transportadora.uf != "") & (Transportadora.uf.isnot(None)))
        t_endereco_completo = get_count_safe(Transportadora, (Transportadora.endereco_completo != "") & (Transportadora.endereco_completo.isnot(None)))
        
        t_lat = 0
        t_lon = 0
        t_prec = {}
        if check_col(Transportadora, "latitude"):
            t_lat = get_count_safe(Transportadora, Transportadora.latitude.isnot(None))
        if check_col(Transportadora, "longitude"):
            t_lon = get_count_safe(Transportadora, Transportadora.longitude.isnot(None))
        if check_col(Transportadora, "precisao_geocodificacao"):
            # Obter contagens de precisão
            rows = db.session.query(
                Transportadora.precisao_geocodificacao, db.func.count(Transportadora.id)
            ).group_by(Transportadora.precisao_geocodificacao).all()
            t_prec = {r[0] or "Não geocodificado": r[1] for r in rows}
            
        t_metrics = [
            ("total_na_base", t_total),
            ("presentes_em_matches", t_in_matches),
            ("com_cep", t_cep),
            ("com_logradouro", t_logradouro),
            ("com_bairro", t_bairro),
            ("com_municipio", t_municipio),
            ("com_uf", t_uf),
            ("com_endereco_completo", t_endereco_completo),
            ("com_latitude", t_lat),
            ("com_longitude", t_lon)
        ]
        
        # Salvar auditoria_geografia_transportadoras.csv
        with open("exports/geografia/auditoria_geografia_transportadoras.csv", "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["metrica", "valor", "percentual_total", "percentual_matches"])
            for met, val in t_metrics:
                pct_tot = (val / t_total * 100) if t_total > 0 else 0
                pct_mat = (val / t_in_matches * 100) if t_in_matches > 0 else 0
                writer.writerow([met, val, f"{pct_tot:.2f}%", f"{pct_mat:.2f}%"])
                
        # ─── 2. EMBARCADORES ───
        print("  Auditando Embarcadores...")
        e_total = EmbarcadorProvavel.query.count()
        
        # Presentes em matches
        e_in_matches = db.session.query(EmbarcadorProvavel.id).join(
            MatchPreditivo, MatchPreditivo.embarcador_id == EmbarcadorProvavel.id
        ).distinct().count()
        
        e_cidade = get_count_safe(EmbarcadorProvavel, (EmbarcadorProvavel.cidade != "") & (EmbarcadorProvavel.cidade.isnot(None)))
        e_uf = get_count_safe(EmbarcadorProvavel, (EmbarcadorProvavel.uf != "") & (EmbarcadorProvavel.uf.isnot(None)))
        e_endereco_completo = get_count_safe(EmbarcadorProvavel, (EmbarcadorProvavel.endereco_completo != "") & (EmbarcadorProvavel.endereco_completo.isnot(None)))
        
        e_cep = 0
        e_logradouro = 0
        e_bairro = 0
        e_lat = 0
        e_lon = 0
        e_prec = {}
        
        if check_col(EmbarcadorProvavel, "cep"):
            e_cep = get_count_safe(EmbarcadorProvavel, (EmbarcadorProvavel.cep != "") & (EmbarcadorProvavel.cep.isnot(None)))
        if check_col(EmbarcadorProvavel, "logradouro"):
            e_logradouro = get_count_safe(EmbarcadorProvavel, (EmbarcadorProvavel.logradouro != "") & (EmbarcadorProvavel.logradouro.isnot(None)))
        if check_col(EmbarcadorProvavel, "bairro"):
            e_bairro = get_count_safe(EmbarcadorProvavel, (EmbarcadorProvavel.bairro != "") & (EmbarcadorProvavel.bairro.isnot(None)))
        if check_col(EmbarcadorProvavel, "latitude"):
            e_lat = get_count_safe(EmbarcadorProvavel, EmbarcadorProvavel.latitude.isnot(None))
        if check_col(EmbarcadorProvavel, "longitude"):
            e_lon = get_count_safe(EmbarcadorProvavel, EmbarcadorProvavel.longitude.isnot(None))
        if check_col(EmbarcadorProvavel, "precisao_geocodificacao"):
            rows = db.session.query(
                EmbarcadorProvavel.precisao_geocodificacao, db.func.count(EmbarcadorProvavel.id)
            ).group_by(EmbarcadorProvavel.precisao_geocodificacao).all()
            e_prec = {r[0] or "Não geocodificado": r[1] for r in rows}
            
        e_metrics = [
            ("total_na_base", e_total),
            ("presentes_em_matches", e_in_matches),
            ("com_cidade", e_cidade),
            ("com_uf", e_uf),
            ("com_cep", e_cep),
            ("com_logradouro", e_logradouro),
            ("com_bairro", e_bairro),
            ("com_endereco_completo", e_endereco_completo),
            ("com_latitude", e_lat),
            ("com_longitude", e_lon)
        ]
        
        # Salvar auditoria_geografia_embarcadores.csv
        with open("exports/geografia/auditoria_geografia_embarcadores.csv", "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["metrica", "valor", "percentual_total", "percentual_matches"])
            for met, val in e_metrics:
                pct_tot = (val / e_total * 100) if e_total > 0 else 0
                pct_mat = (val / e_in_matches * 100) if e_in_matches > 0 else 0
                writer.writerow([met, val, f"{pct_tot:.2f}%", f"{pct_mat:.2f}%"])
                
        # ─── 3. MATCHES ───
        print("  Auditando Matches...")
        m_total = MatchPreditivo.query.count()
        
        # Por corredor
        corr_rows = db.session.query(
            MatchPreditivo.corredor, db.func.count(MatchPreditivo.id)
        ).group_by(MatchPreditivo.corredor).all()
        
        # Filtros geográficos dos matches
        loc_minima = 0
        cep_t_cidade_e = 0
        cep_dois_lados = 0
        endereco_dois_lados = 0
        lat_lon_dois_lados = 0
        
        all_matches = MatchPreditivo.query.all()
        for m in all_matches:
            t = m.transportadora
            e = m.embarcador
            
            if not t or not e:
                continue
                
            # Mínimo: t.municipio e t.uf e e.cidade e e.uf
            t_min = bool(t.municipio and t.uf)
            e_min = bool(e.cidade and e.uf)
            if t_min and e_min:
                loc_minima += 1
                
            # CEP t + cidade/UF e
            t_has_cep = bool(t.cep and t.cep.strip())
            if t_has_cep and e_min:
                cep_t_cidade_e += 1
                
            # CEP dois lados
            e_has_cep = False
            if check_col(EmbarcadorProvavel, "cep") and e.cep and e.cep.strip():
                e_has_cep = True
            if t_has_cep and e_has_cep:
                cep_dois_lados += 1
                
            # Endereço completo dois lados
            t_has_addr = bool(t.endereco_completo and t.endereco_completo.strip())
            e_has_addr = bool(e.endereco_completo and e.endereco_completo.strip())
            if t_has_addr and e_has_addr:
                endereco_dois_lados += 1
                
            # Lat/Lon dois lados
            t_has_latlon = False
            e_has_latlon = False
            if check_col(Transportadora, "latitude") and t.latitude is not None and t.longitude is not None:
                t_has_latlon = True
            if check_col(EmbarcadorProvavel, "latitude") and e.latitude is not None and e.longitude is not None:
                e_has_latlon = True
            if t_has_latlon and e_has_latlon:
                lat_lon_dois_lados += 1
                
        # Por nível de precisão do match (se coluna existir)
        match_prec = {}
        if check_col(MatchPreditivo, "precisao_geografica_match"):
            rows = db.session.query(
                MatchPreditivo.precisao_geografica_match, db.func.count(MatchPreditivo.id)
            ).group_by(MatchPreditivo.precisao_geografica_match).all()
            match_prec = {r[0] or "Sem cálculo": r[1] for r in rows}
            
        m_metrics = [
            ("total_matches", m_total),
            ("com_localizacao_minima_dois_lados", loc_minima),
            ("com_cep_t_cidade_uf_e", cep_t_cidade_e),
            ("com_cep_dois_lados", cep_dois_lados),
            ("com_endereco_completo_dois_lados", endereco_dois_lados),
            ("com_lat_lon_dois_lados", lat_lon_dois_lados)
        ]
        
        # Salvar auditoria_geografia_matches.csv
        with open("exports/geografia/auditoria_geografia_matches.csv", "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["metrica", "valor", "percentual"])
            for met, val in m_metrics:
                pct = (val / m_total * 100) if m_total > 0 else 0
                writer.writerow([met, val, f"{pct:.2f}%"])
                
            writer.writerow([])
            writer.writerow(["corredor", "total_matches", "percentual"])
            for corr, tot in corr_rows:
                pct = (tot / m_total * 100) if m_total > 0 else 0
                writer.writerow([corr, tot, f"{pct:.2f}%"])
                
        # ─── 4. EMPRESAS SEM GEOGRAFIA SUFICIENTE ───
        # Listar empresas que não possuem CEP ou Cidade/UF
        print("  Identificando empresas sem geografia suficiente...")
        sem_geografia = []
        
        # Transportadoras sem CEP ou sem Cidade/UF
        for t in Transportadora.query.all():
            if not t.cep or not t.municipio or not t.uf:
                sem_geografia.append({
                    "tipo_empresa": "transportadora",
                    "id": t.id,
                    "cnpj": t.cnpj,
                    "nome": t.razao_social or t.nome_rntrc or t.nome_fantasia or "",
                    "cep": t.cep or "",
                    "cidade": t.municipio or "",
                    "uf": t.uf or "",
                    "motivo": "Falta CEP ou Cidade/UF"
                })
                
        # Embarcadores sem CEP (se coluna existir) ou sem Cidade/UF
        for e in EmbarcadorProvavel.query.all():
            cep_val = getattr(e, "cep", None) or ""
            if not cep_val or not e.cidade or not e.uf:
                sem_geografia.append({
                    "tipo_empresa": "embarcador",
                    "id": e.id,
                    "cnpj": e.cnpj,
                    "nome": e.razao_social or e.nome_fantasia or "",
                    "cep": cep_val,
                    "cidade": e.cidade or "",
                    "uf": e.uf or "",
                    "motivo": "Falta CEP ou Cidade/UF"
                })
                
        with open("exports/geografia/empresas_sem_geografia_suficiente.csv", "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["tipo_empresa", "id", "cnpj", "nome", "cep", "cidade", "uf", "motivo"], delimiter=";")
            writer.writeheader()
            writer.writerows(sem_geografia)
            
        # ─── 5. RELATÓRIO MARKDOWN ───
        print("  Gerando relatório Markdown...")
        
        # Agrupar corredores para exibir no md
        corredores_md = "\n".join([f"* **{c[0]}:** {c[1]:,} matches" for c in corr_rows])
        
        # Precisões do match
        precisoes_md = ""
        if match_prec:
            precisoes_md = "\n".join([f"* **{p}:** {count:,} matches" for p, count in match_prec.items()])
        else:
            precisoes_md = "* Nenhuma coordenada ou score geográfico computado ainda."
            
        md_content = f"""# RELATÓRIO DE AUDITORIA GEOGRÁFICA DE MATCHES

Este relatório apresenta o diagnóstico geográfico atual das **Transportadoras**, **Embarcadores** e **Matches Preditivos**, identificando as lacunas existentes para o match logístico de proximidade.

---

## 📉 Diagnóstico das Transportadoras (Base total: {t_total:,})
* **Presentes em Matches:** {t_in_matches:,}
* **Com CEP preenchido:** {t_cep:,} ({t_cep/t_in_matches*100:.2f}% das em matches)
* **Com Logradouro:** {t_logradouro:,} ({t_logradouro/t_in_matches*100:.2f}%)
* **Com Bairro:** {t_bairro:,} ({t_bairro/t_in_matches*100:.2f}%)
* **Com Município/UF:** {t_municipio:,}/{t_uf:,}
* **Com Latitude/Longitude:** {t_lat:,}/{t_lon:,}

## 🏢 Diagnóstico dos Embarcadores (Base total: {e_total:,})
* **Presentes em Matches:** {e_in_matches:,}
* **Com Cidade/UF preenchido:** {e_cidade:,}/{e_uf:,}
* **Com CEP preenchido:** {e_cep:,} ({e_cep/e_in_matches*100:.2f}% das em matches se coluna ativa)
* **Com Logradouro:** {e_logradouro:,}
* **Com Bairro:** {e_bairro:,}
* **Com Latitude/Longitude:** {e_lat:,}/{e_lon:,}

---

## 🔗 Qualidade Geográfica dos Matches (Total: {m_total:,})

### Por Corredor:
{corredores_md}

### Métricas de Proximidade e Coordenadas:
* **Com Localização Mínima dos Dois Lados (Cidade/UF):** **{loc_minima:,}** ({loc_minima/m_total*100:.2f}%)
* **Com CEP (Transportadora) + Cidade/UF (Embarcador):** **{cep_t_cidade_e:,}** ({cep_t_cidade_e/m_total*100:.2f}%)
* **Com CEP de Ambos os Lados:** **{cep_dois_lados:,}** ({cep_dois_lados/m_total*100:.2f}%)
* **Com Endereço Completo de Ambos os Lados:** **{endereco_dois_lados:,}** ({endereco_dois_lados/m_total*100:.2f}%)
* **Com Coordenadas (Lat/Lon) de Ambos os Lados:** **{lat_lon_dois_lados:,}** ({lat_lon_dois_lados/m_total*100:.2f}%)

### Distribuição por Precisão Geográfica do Match:
{precisoes_md}

---

## ⚠️ Lacunas Críticas Identificadas
1. **Embarcadores sem Endereço Detalhado:** A maior lacuna está nos embarcadores, que historicamente só possuem a Cidade/UF do match predito. Sem logradouro, CEP ou bairro, é impossível computar geocodificação de precisão (rua ou CEP).
2. **Coordenadas Inexistentes:** Não há nenhuma coordenada de latitude ou longitude registrada para as empresas, inviabilizando o cálculo de raio de distância real (distância em quilômetros).
3. **Empresas sem Geografia Suficiente:** Foram identificadas **{len(sem_geografia):,}** empresas com dados geográficos faltantes ou incompletos na base.

---

## 🚀 Próximos Passos
1. **Etapa 2 — Migração do Schema:** Adicionar colunas de latitude, longitude, CEP, e status de geocodificação nos modelos.
2. **Etapa 3 — Enriquecimento de Endereços por CNPJ:** Rodar o enriquecedor para popular os campos vazios de CEP, logradouro e bairro dos embarcadores a partir da base BrasilAPI/CNPJ.
3. **Etapa 4 — Geocodificação:** Executar geocodificação em camadas (CEP, Município, ou Logradouro) para salvar lat/lon.
4. **Etapa 5 — Cálculo do Score Geográfico:** Avaliar o raio real em quilômetros e computar o score_geografico experimental.
"""
        with open("exports/geografia/RELATORIO_GEOGRAFIA_MATCHES.md", "w", encoding="utf-8") as f:
            f.write(md_content.strip())
            
    print("Relatórios e arquivo Markdown gerados com sucesso!")

if __name__ == "__main__":
    main()
