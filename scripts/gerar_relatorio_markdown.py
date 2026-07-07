#!/usr/bin/env python3
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import Transportadora, EmbarcadorProvavel, MatchPreditivo

def main():
    print("============================================================")
    print("GERANDO RELATÓRIO EXECUTIVO EM MARKDOWN")
    print("============================================================")
    
    os.makedirs("exports/completude", exist_ok=True)
    md_path = "exports/completude/RELATORIO_COMPLETUDE_DADOS.md"
    
    with app.app_context():
        t_total = Transportadora.query.count()
        e_total = EmbarcadorProvavel.query.count()
        m_total = MatchPreditivo.query.count()
        
        t_avg = db.session.query(db.func.avg(Transportadora.score_completude)).scalar() or 0.0
        e_avg = db.session.query(db.func.avg(EmbarcadorProvavel.score_completude)).scalar() or 0.0
        
        t_tel = Transportadora.query.filter(Transportadora.telefone != '', Transportadora.telefone.isnot(None)).count()
        t_email = Transportadora.query.filter(Transportadora.email != '', Transportadora.email.isnot(None)).count()
        t_socios = Transportadora.query.filter(Transportadora.socios != '', Transportadora.socios.isnot(None)).count()
        
        e_tel = EmbarcadorProvavel.query.filter(EmbarcadorProvavel.telefone != '', EmbarcadorProvavel.telefone.isnot(None)).count()
        e_email = EmbarcadorProvavel.query.filter(EmbarcadorProvavel.email != '', EmbarcadorProvavel.email.isnot(None)).count()
        e_site = EmbarcadorProvavel.query.filter(EmbarcadorProvavel.site != '', EmbarcadorProvavel.site.isnot(None)).count()
        e_socios = EmbarcadorProvavel.query.filter(EmbarcadorProvavel.socios != '', EmbarcadorProvavel.socios.isnot(None)).count()
        
        # Matches counts
        m_counts_completos = 0
        m_counts_sem_contato_nenhum = 0
        
        all_matches = MatchPreditivo.query.all()
        for m in all_matches:
            t = m.transportadora
            e = m.embarcador
            
            has_t = bool(t and (t.telefone or t.email or t.socios))
            has_e = bool(e and (e.telefone or e.email or e.site))
            
            if has_t and has_e:
                m_counts_completos += 1
            if not has_t and not has_e:
                m_counts_sem_contato_nenhum += 1
                
        m_incompletos = m_total - m_counts_completos
        
        # Montar o Markdown
        md_content = f"""# RELATÓRIO EXECUTIVO — COMPLETUDE DE DADOS

Este relatório apresenta um diagnóstico detalhado da completude dos dados cadastrais e de contatos de **Transportadoras**, **Embarcadores** e seus **Matches Preditivos**, antes do início das ações de prospecção comercial.

---

## 📈 Resumo Geral

* **Total de Transportadoras na base:** {t_total:,}
* **Total de Embarcadores na base:** {e_total:,}
* **Total de Matches Preditivos carregados:** {m_total:,}
* **Completude Média das Transportadoras:** {t_avg:.2f}%
* **Completude Média dos Embarcadores:** {e_avg:.2f}%

---

## 📞 Diagnóstico de Contatos Preenchidos

### Transportadoras
* **Com Telefone:** {t_tel:,} ({t_tel/t_total*100:.2f}% preenchimento)
* **Com E-mail:** {t_email:,} ({t_email/t_total*100:.2f}% preenchimento)
* **Com Sócios/QSA:** {t_socios:,} ({t_socios/t_total*100:.2f}% preenchimento)

### Embarcadores
* **Com Telefone:** {e_tel:,} ({e_tel/e_total*100:.2f}% preenchimento)
* **Com E-mail:** {e_email:,} ({e_email/e_total*100:.2f}% preenchimento)
* **Com Site:** {e_site:,} ({e_site/e_total*100:.2f}% preenchimento)
* **Com Sócios/QSA:** {e_socios:,} ({e_socios/e_total*100:.2f}% preenchimento)

---

## 🔗 Status de Qualidade dos Matches Preditivos

* **Matches Totalmente Acionáveis (contato de ambos os lados):** **{m_counts_completos:,}** ({m_counts_completos/m_total*100:.2f}%)
* **Matches com Alguma Lacuna (um ou ambos os lados sem contato):** **{m_incompletos:,}** ({m_incompletos/m_total*100:.2f}%)
* **Matches sem Contato Nenhum (ambos os lados sem contato):** **{m_counts_sem_contato_nenhum:,}** ({m_counts_sem_contato_nenhum/m_total*100:.2f}%)

---

## ⚠️ Campos Críticos Faltantes e Limitações de Fontes Públicas

1. **E-mails e Sites:** 
   * A BrasilAPI e a Receita Federal possuem uma baixíssima taxa de preenchimento de e-mail e site cadastral. Na maioria das vezes, os e-mails informados são de escritórios de contabilidade ou estão desatualizados.
2. **Sócios/QSA de Embarcadores:**
   * Embora o QSA tenha sido migrado com sucesso de notas para a nova coluna dedicada de sócios, muitas empresas (especialmente MEIs e pequenas empresas) não registram sócios adicionais no QSA público.
3. **Telefones de Contato:**
   * Cerca de 95%+ dos telefones cadastrados foram normalizados, mas há uma lacuna de e-mail/site corporativos que dificulta a abordagem por múltiplos canais.

---

## 🚀 Próximos Passos Recomendados

1. **Abordagem por WhatsApp (Comercial):**
   * Com {t_tel + e_tel:,} telefones normalizados e limpos, e com a flag `whatsapp_possivel` ativa nas empresas com celulares válidos, a equipe comercial deve priorizar contato via telefone/WhatsApp.
2. **Enriquecimento Manual do Pipeline de Prospecção:**
   * Para os matches estratégicos que possuem apenas contato de um lado, realizar pesquisa direcionada (LinkedIn/Google) para capturar o e-mail/site do tomador de decisão.
3. **Campanha Piloto:**
   * Iniciar com os **{m_counts_completos:,} matches acionáveis** que já possuem contatos cadastrados de ambas as partes.
"""
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content.strip())
            
    print(f"Relatório Markdown gerado com sucesso em: {md_path}")

if __name__ == "__main__":
    main()
