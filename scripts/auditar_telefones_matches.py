#!/usr/bin/env python3
import os
import sys
import csv

# Add root folder to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import Transportadora, EmbarcadorProvavel, MatchPreditivo

def has_phone(val):
    return bool(val and val.strip())

def main():
    print("============================================================")
    print("AUDITORIA ESPECÍFICA DE TELEFONES")
    print("============================================================")
    
    os.makedirs("exports/telefones", exist_ok=True)
    
    with app.app_context():
        # 1. Base Inteira
        print("  Auditando Base Inteira...")
        t_total = Transportadora.query.count()
        t_com_tel = Transportadora.query.filter(Transportadora.telefone != None, Transportadora.telefone != "").count()
        t_com_tel_norm = Transportadora.query.filter(Transportadora.telefone_normalizado != None, Transportadora.telefone_normalizado != "").count()
        t_com_wa = Transportadora.query.filter_by(whatsapp_possivel=True).count()
        t_sem_tel = t_total - t_com_tel
        
        e_total = EmbarcadorProvavel.query.count()
        e_com_tel = EmbarcadorProvavel.query.filter(EmbarcadorProvavel.telefone != None, EmbarcadorProvavel.telefone != "").count()
        e_com_tel_norm = EmbarcadorProvavel.query.filter(EmbarcadorProvavel.telefone_normalizado != None, EmbarcadorProvavel.telefone_normalizado != "").count()
        e_com_wa = EmbarcadorProvavel.query.filter_by(whatsapp_possivel=True).count()
        e_sem_tel = e_total - e_com_tel
        
        # 2. Empresas presentes em matches
        print("  Auditando Empresas nos Matches...")
        matches = MatchPreditivo.query.all()
        t_ids = set(m.transportadora_id for m in matches)
        e_ids = set(m.embarcador_id for m in matches)
        
        t_in_matches = Transportadora.query.filter(Transportadora.id.in_(t_ids)).all()
        e_in_matches = EmbarcadorProvavel.query.filter(EmbarcadorProvavel.id.in_(e_ids)).all()
        
        t_m_total = len(t_in_matches)
        t_m_tel = sum(1 for t in t_in_matches if has_phone(t.telefone))
        t_m_norm = sum(1 for t in t_in_matches if has_phone(t.telefone_normalizado))
        t_m_wa = sum(1 for t in t_in_matches if t.whatsapp_possivel)
        t_m_sem = t_m_total - t_m_tel
        
        e_m_total = len(e_in_matches)
        e_m_tel = sum(1 for e in e_in_matches if has_phone(e.telefone))
        e_m_norm = sum(1 for e in e_in_matches if has_phone(e.telefone_normalizado))
        e_m_wa = sum(1 for e in e_in_matches if e.whatsapp_possivel)
        e_m_sem = e_m_total - e_m_tel
        
        # 3. Matches
        print("  Auditando Matches...")
        m_total = len(matches)
        m_com_t_tel = 0
        m_sem_t_tel = 0
        m_com_e_tel = 0
        m_sem_e_tel = 0
        m_com_ambos = 0
        m_com_pelo_menos_um = 0
        m_sem_nenhum = 0
        m_com_t_wa = 0
        m_com_e_wa = 0
        m_com_pelo_menos_um_wa = 0
        
        # Listas para exportar
        t_matches_sem_tel = []
        e_matches_sem_tel = []
        
        m_sem_t_tel_rows = []
        m_sem_e_tel_rows = []
        m_sem_nenhum_rows = []
        
        for m in matches:
            t = m.transportadora
            e = m.embarcador
            
            t_tel = has_phone(t.telefone) or has_phone(t.telefone_normalizado) if t else False
            e_tel = has_phone(e.telefone) or has_phone(e.telefone_normalizado) if e else False
            
            t_wa = t.whatsapp_possivel if t else False
            e_wa = e.whatsapp_possivel if e else False
            
            if t_tel:
                m_com_t_tel += 1
            else:
                m_sem_t_tel += 1
                if t: t_matches_sem_tel.append(t)
                
            if e_tel:
                m_com_e_tel += 1
            else:
                m_sem_e_tel += 1
                if e: e_matches_sem_tel.append(e)
                
            if t_tel and e_tel:
                m_com_ambos += 1
            if t_tel or e_tel:
                m_com_pelo_menos_um += 1
            else:
                m_sem_nenhum += 1
                
            if t_wa:
                m_com_t_wa += 1
            if e_wa:
                m_com_e_wa += 1
            if t_wa or e_wa:
                m_com_pelo_menos_um_wa += 1
                
            # Detalhamento de matches sem telefone
            m_info = {
                "match_id": m.id,
                "corredor": m.corredor,
                "score_match": m.score_match,
                "transportadora_cnpj": t.cnpj if t else "",
                "transportadora_nome": (t.razao_social or t.nome_rntrc) if t else "",
                "embarcador_cnpj": e.cnpj if e else "",
                "embarcador_nome": (e.razao_social or e.nome_fantasia) if e else ""
            }
            
            if not t_tel:
                m_sem_t_tel_rows.append(m_info)
            if not e_tel:
                m_sem_e_tel_rows.append(m_info)
            if not t_tel and not e_tel:
                m_sem_nenhum_rows.append(m_info)
                
        # Dedup lists of companies sem telefone
        t_matches_sem_tel = list({x.id: x for x in t_matches_sem_tel}.values())
        e_matches_sem_tel = list({x.id: x for x in e_matches_sem_tel}.values())
        
        # 4. Por Corredor
        print("  Auditando por Corredor...")
        corredores = sorted(list(set(m.corredor for m in matches)))
        corredor_stats = []
        
        for c in corredores:
            c_matches = [m for m in matches if m.corredor == c]
            c_tot = len(c_matches)
            
            c_t_ids = set(m.transportadora_id for m in c_matches)
            c_e_ids = set(m.embarcador_id for m in c_matches)
            
            c_t_in = [t for t in t_in_matches if t.id in c_t_ids]
            c_e_in = [e for e in e_in_matches if e.id in c_e_ids]
            
            c_t_tel = sum(1 for t in c_t_in if has_phone(t.telefone) or has_phone(t.telefone_normalizado))
            c_e_tel = sum(1 for e in c_e_in if has_phone(e.telefone) or has_phone(e.telefone_normalizado))
            
            c_pct_t = (c_t_tel / len(c_t_in)) * 100 if c_t_in else 0.0
            c_pct_e = (c_e_tel / len(c_e_in)) * 100 if c_e_in else 0.0
            
            c_ambos = 0
            c_pelo_menos_um = 0
            c_nenhum = 0
            
            for m in c_matches:
                t_tel = has_phone(m.transportadora.telefone) or has_phone(m.transportadora.telefone_normalizado) if m.transportadora else False
                e_tel = has_phone(m.embarcador.telefone) or has_phone(m.embarcador.telefone_normalizado) if m.embarcador else False
                
                if t_tel and e_tel:
                    c_ambos += 1
                if t_tel or e_tel:
                    c_pelo_menos_um += 1
                else:
                    c_nenhum += 1
                    
            corredor_stats.append({
                "corredor": c,
                "total_matches": c_tot,
                "transportadoras_unicas": len(c_t_in),
                "embarcadores_unicos": len(c_e_in),
                "pct_t_com_telefone": round(c_pct_t, 2),
                "pct_e_com_telefone": round(c_pct_e, 2),
                "matches_telefone_dois_lados": c_ambos,
                "matches_telefone_pelo_menos_um_lado": c_pelo_menos_um,
                "matches_sem_telefone_nenhum": c_nenhum
            })
            
        # Escrever arquivos CSV
        # 1. Resumo
        resumo_fields = ["metrica", "valor"]
        resumo_rows = [
            {"metrica": "total_transportadoras", "valor": t_total},
            {"metrica": "transportadoras_com_telefone", "valor": t_com_tel},
            {"metrica": "transportadoras_com_telefone_normalizado", "valor": t_com_tel_norm},
            {"metrica": "transportadoras_com_whatsapp_possivel", "valor": t_com_wa},
            {"metrica": "transportadoras_sem_telefone", "valor": t_sem_tel},
            
            {"metrica": "total_embarcadores", "valor": e_total},
            {"metrica": "embarcadores_com_telefone", "valor": e_com_tel},
            {"metrica": "embarcadores_com_telefone_normalizado", "valor": e_com_tel_norm},
            {"metrica": "embarcadores_com_whatsapp_possivel", "valor": e_com_wa},
            {"metrica": "embarcadores_sem_telefone", "valor": e_sem_tel},
            
            {"metrica": "transportadoras_unicas_matches", "valor": t_m_total},
            {"metrica": "transportadoras_matches_com_telefone", "valor": t_m_tel},
            {"metrica": "transportadoras_matches_com_telefone_normalizado", "valor": t_m_norm},
            {"metrica": "transportadoras_matches_com_whatsapp_possivel", "valor": t_m_wa},
            {"metrica": "transportadoras_matches_sem_telefone", "valor": t_m_sem},
            
            {"metrica": "embarcadores_unicas_matches", "valor": e_m_total},
            {"metrica": "embarcadores_matches_com_telefone", "valor": e_m_tel},
            {"metrica": "embarcadores_matches_com_telefone_normalizado", "valor": e_m_norm},
            {"metrica": "embarcadores_matches_com_whatsapp_possivel", "valor": e_m_wa},
            {"metrica": "embarcadores_matches_sem_telefone", "valor": e_m_sem},
            
            {"metrica": "total_matches", "valor": m_total},
            {"metrica": "matches_com_telefone_transportadora", "valor": m_com_t_tel},
            {"metrica": "matches_sem_telefone_transportadora", "valor": m_sem_t_tel},
            {"metrica": "matches_com_telefone_embarcador", "valor": m_com_e_tel},
            {"metrica": "matches_sem_telefone_embarcador", "valor": m_sem_e_tel},
            {"metrica": "matches_telefone_dois_lados", "valor": m_com_ambos},
            {"metrica": "matches_telefone_pelo_menos_um_lado", "valor": m_com_pelo_menos_um},
            {"metrica": "matches_sem_telefone_nenhum", "valor": m_sem_nenhum},
            {"metrica": "matches_whatsapp_possivel_transportadora", "valor": m_com_t_wa},
            {"metrica": "matches_whatsapp_possivel_embarcador", "valor": m_com_e_wa},
            {"metrica": "matches_whatsapp_possivel_pelo_menos_um", "valor": m_com_pelo_menos_um_wa}
        ]
        
        with open("exports/telefones/auditoria_telefones_resumo.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=resumo_fields, delimiter=";")
            w.writeheader()
            w.writerows(resumo_rows)
            
        # 2. Por Corredor
        c_fields = [
            "corredor", "total_matches", "transportadoras_unicas", "embarcadores_unicos",
            "pct_t_com_telefone", "pct_e_com_telefone", "matches_telefone_dois_lados",
            "matches_telefone_pelo_menos_um_lado", "matches_sem_telefone_nenhum"
        ]
        with open("exports/telefones/auditoria_telefones_por_corredor.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=c_fields, delimiter=";")
            w.writeheader()
            w.writerows(corredor_stats)
            
        # 3. Transportadoras sem telefone
        t_fields = ["id", "cnpj", "razao_social", "municipio", "uf", "telefone"]
        t_rows = [{"id": x.id, "cnpj": x.cnpj, "razao_social": x.razao_social or x.nome_rntrc, "municipio": x.municipio, "uf": x.uf, "telefone": x.telefone or ""} for x in t_matches_sem_tel]
        with open("exports/telefones/transportadoras_matches_sem_telefone.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=t_fields, delimiter=";")
            w.writeheader()
            w.writerows(t_rows)
            
        # 4. Embarcadores sem telefone
        e_fields = ["id", "cnpj", "razao_social", "cidade", "uf", "telefone"]
        e_rows = [{"id": x.id, "cnpj": x.cnpj, "razao_social": x.razao_social or x.nome_fantasia, "cidade": x.cidade, "uf": x.uf, "telefone": x.telefone or ""} for x in e_matches_sem_tel]
        with open("exports/telefones/embarcadores_matches_sem_telefone.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=e_fields, delimiter=";")
            w.writeheader()
            w.writerows(e_rows)
            
        # 5. Matches sem telefone transportadora
        m_fields = ["match_id", "corredor", "score_match", "transportadora_cnpj", "transportadora_nome", "embarcador_cnpj", "embarcador_nome"]
        with open("exports/telefones/matches_sem_telefone_transportadora.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=m_fields, delimiter=";")
            w.writeheader()
            w.writerows(m_sem_t_tel_rows)
            
        # 6. Matches sem telefone embarcador
        with open("exports/telefones/matches_sem_telefone_embarcador.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=m_fields, delimiter=";")
            w.writeheader()
            w.writerows(m_sem_e_tel_rows)
            
        # 7. Matches sem telefone nenhum
        with open("exports/telefones/matches_sem_telefone_nenhum.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=m_fields, delimiter=";")
            w.writeheader()
            w.writerows(m_sem_nenhum_rows)
            
        # Gerar o Relatório MD
        c_md = ""
        for cs in corredor_stats:
            c_md += f"| {cs['corredor']} | {cs['total_matches']:,} | {cs['transportadoras_unicas']:,} | {cs['embarcadores_unicos']:,} | {cs['pct_t_com_telefone']}% | {cs['pct_e_com_telefone']}% | {cs['matches_telefone_dois_lados']:,} | {cs['matches_telefone_pelo_menos_um_lado']:,} | {cs['matches_sem_telefone_nenhum']:,} |\n"
            
        md_content = f"""# RELATÓRIO DE AUDITORIA DE COBERTURA DE TELEFONES nos MATCHES

Este relatório apresenta o diagnóstico detalhado da cobertura de telefones nos matches preditivos ativos no sistema.

---

## 📞 1. Estatísticas da Base Inteira

### Transportadoras (Total: {t_total:,})
* **Com telefone (bruto):** {t_com_tel:,} ({t_com_tel/t_total*100:.2f}%)
* **Com telefone normalizado:** {t_com_tel_norm:,} ({t_com_tel_norm/t_total*100:.2f}%)
* **Com WhatsApp possível:** {t_com_wa:,} ({t_com_wa/t_total*100:.2f}%)
* **Sem telefone:** {t_sem_tel:,} ({t_sem_tel/t_total*100:.2f}%)

### Embarcadores (Total: {e_total:,})
* **Com telefone (bruto):** {e_com_tel:,} ({e_com_tel/e_total*100:.2f}%)
* **Com telefone normalizado:** {e_com_tel_norm:,} ({e_com_tel_norm/e_total*100:.2f}%)
* **Com WhatsApp possível:** {e_com_wa:,} ({e_com_wa/e_total*100:.2f}%)
* **Sem telefone:** {e_sem_tel:,} ({e_sem_tel/e_total*100:.2f}%)

---

## 💼 2. Empresas Presentes em Matches

### Transportadoras Únicas nos Matches (Total: {t_m_total:,})
* **Com telefone (bruto):** {t_m_tel:,} ({t_m_tel/t_m_total*100:.2f}%)
* **Com telefone normalizado:** {t_m_norm:,} ({t_m_norm/t_m_total*100:.2f}%)
* **Com WhatsApp possível:** {t_m_wa:,} ({t_m_wa/t_m_total*100:.2f}%)
* **Sem telefone:** {t_m_sem:,} ({t_m_sem/t_m_total*100:.2f}%)

### Embarcadores Únicos nos Matches (Total: {e_m_total:,})
* **Com telefone (bruto):** {e_m_tel:,} ({e_m_tel/e_m_total*100:.2f}%)
* **Com telefone normalizado:** {e_m_norm:,} ({e_m_norm/e_m_total*100:.2f}%)
* **Com WhatsApp possível:** {e_m_wa:,} ({e_m_wa/e_m_total*100:.2f}%)
* **Sem telefone:** {e_m_sem:,} ({e_m_sem/e_m_total*100:.2f}%)

---

## 🔗 3. Qualidade da Cobertura de Telefones nos Matches (Total: {m_total:,})

* **Matches com telefone da Transportadora:** {m_com_t_tel:,} ({m_com_t_tel/m_total*100:.2f}%)
* **Matches com telefone do Embarcador:** {m_com_e_tel:,} ({m_com_e_tel/m_total*100:.2f}%)
* **Matches com telefone dos DOIS LADOS:** **{m_com_ambos:,}** ({m_com_ambos/m_total*100:.2f}%)
* **Matches com telefone em pelo menos um lado:** **{m_com_pelo_menos_um:,}** ({m_com_pelo_menos_um/m_total*100:.2f}%)
* **Matches sem telefone nenhum (Lacuna Crítica):** **{m_sem_nenhum:,}** ({m_sem_nenhum/m_total*100:.2f}%)

---

## 🛣️ 4. Cobertura de Telefones por Corredor

| Corredor | Matches | Transp. Únicas | Embarc. Únicos | % Transp. c/ Tel | % Embarc. c/ Tel | Tel Ambos Lados | Tel Pelo Menos Um | Sem Tel Nenhum |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
{c_md}

---

## 📢 Conclusão e Observações
* **Lacuna Crítica:** Temos {m_sem_nenhum:,} matches sem telefone de contato de nenhum dos dois lados.
* **Ação Recomendada:**
  1. Corrigir eventuais problemas de exibição de telefones normalizados nos templates do app.
  2. Executar normalização retroativa de telefones para popular os campos estruturados de DDD, celular/fixo e WhatsApp.
  3. Realizar enriquecimento de telefones ausentes via cache local do CNPJ.
"""
        with open("exports/telefones/RELATORIO_TELEFONES_MATCHES.md", "w", encoding="utf-8") as f:
            f.write(md_content.strip())
            
    print("Auditoria concluída com sucesso!")
    print("Relatório salvo em: exports/telefones/RELATORIO_TELEFONES_MATCHES.md")

if __name__ == "__main__":
    main()
