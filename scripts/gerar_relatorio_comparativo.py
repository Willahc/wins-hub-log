#!/usr/bin/env python3
import os
import sys
import csv

def main():
    print("============================================================")
    print("GERANDO RELATÓRIO COMPARATIVO DE SCORES")
    print("============================================================")
    
    csv_path = "exports/geografia/score_geografico_matches.csv"
    md_path = "exports/geografia/RELATORIO_SCORE_GEOGRAFICO.md"
    
    if not os.path.exists(csv_path):
        print(f"Erro: Arquivo CSV {csv_path} não encontrado. Execute o cálculo do score primeiro.")
        sys.exit(1)
        
    rows = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        for r in reader:
            rows.append({
                "match_id": int(r["match_id"]),
                "corredor": r["corredor"],
                "transportadora_nome": r["transportadora_nome"],
                "embarcador_nome": r["embarcador_nome"],
                "score_match_atual": float(r["score_match_atual"]),
                "score_geografico": float(r["score_geografico"]) if r["score_geografico"] else 0.0,
                "score_match_v2": float(r["score_match_v2"]) if r["score_match_v2"] else 0.0,
                "distancia_km": float(r["distancia_km"]) if r["distancia_km"] else 9999.0,
                "precisao": r["precisao_geografica_match"]
            })
            
    # 1. Médias por Corredor
    corredores = sorted(list(set(r["corredor"] for r in rows)))
    medias = {}
    for c in corredores:
        c_rows = [r for r in rows if r["corredor"] == c]
        tot = len(c_rows)
        avg_atual = sum(r["score_match_atual"] for r in c_rows) / tot
        avg_geo = sum(r["score_geografico"] for r in c_rows) / tot
        avg_v2 = sum(r["score_match_v2"] for r in c_rows) / tot
        medias[c] = (avg_atual, avg_geo, avg_v2, tot)
        
    # 2. Ranking Comparativo
    # Rank A: Ordenado por score_match_atual desc, depois por match_id asc
    rank_a_sorted = sorted(rows, key=lambda x: (-x["score_match_atual"], x["match_id"]))
    rank_a_pos = {r["match_id"]: idx for idx, r in enumerate(rank_a_sorted)}
    
    # Rank B: Ordenado por score_match_v2 desc, depois por match_id asc
    rank_b_sorted = sorted(rows, key=lambda x: (-x["score_match_v2"], x["match_id"]))
    rank_b_pos = {r["match_id"]: idx for idx, r in enumerate(rank_b_sorted)}
    
    subiram = 0
    cairam = 0
    iguais = 0
    
    for r in rows:
        m_id = r["match_id"]
        pos_a = rank_a_pos[m_id]
        pos_b = rank_b_pos[m_id]
        
        if pos_b < pos_a:
            subiram += 1
        elif pos_b > pos_a:
            cairam += 1
        else:
            iguais += 1
            
    # 3. Exemplos: Bons de score mas ruins geograficamente (distantes)
    conflitos = [r for r in rows if r["score_match_atual"] >= 80.0 and r["score_geografico"] <= 30.0]
    conflitos_sorted = sorted(conflitos, key=lambda x: -x["score_match_atual"])
    
    # Exemplos: Excelentes em ambos
    excelentes = [r for r in rows if r["score_match_atual"] >= 80.0 and r["score_geografico"] >= 70.0]
    excelentes_sorted = sorted(excelentes, key=lambda x: -x["score_match_v2"])
    
    # Gerar o MD
    corredores_md = ""
    for c in corredores:
        avg_at, avg_g, avg_v2, tot = medias[c]
        corredores_md += f"""| {c} | {tot:,} | {avg_at:.2f} | {avg_g:.2f} | {avg_v2:.2f} |
"""

    conflitos_md = ""
    for r in conflitos_sorted[:5]:
        conflitos_md += f"""* **Match #{r['match_id']} ({r['corredor']}):** {r['transportadora_nome']} ➔ {r['embarcador_nome']}
  * *Score Atual:* {r['score_match_atual']} | *Score Geo:* {r['score_geografico']} (Capped: {r['precisao']}) | *Distância:* {r['distancia_km']:.1f} km
"""

    excelentes_md = ""
    for r in excelentes_sorted[:5]:
        excelentes_md += f"""* **Match #{r['match_id']} ({r['corredor']}):** {r['transportadora_nome']} ➔ {r['embarcador_nome']}
  * *Score Atual:* {r['score_match_atual']} | *Score Geo:* {r['score_geografico']} (Capped: {r['precisao']}) | *Distância:* {r['distancia_km']:.1f} km
"""

    md_content = f"""# RELATÓRIO COMPARATIVO — SCORE ATUAL VS. SCORE GEOGRÁFICO

Este documento apresenta uma análise comparativa do algoritmo de match preditivo atual contra a versão experimental **V2**, que incorpora distâncias geográficas e completude cadastral.

---

## 📊 Estatísticas Médias por Corredor

| Corredor | Total Matches | Score Atual Médio | Score Geográfico Médio | Score V2 Médio |
| :--- | :--- | :--- | :--- | :--- |
{corredores_md}

---

## 📈 Impacto no Ranking de Prospecção

Ao substituir a ordenação atual pelo **Score Match V2** (`0.70 * score_match + 0.25 * score_geografico + 0.05 * score_completude`):
* **Matches que subiriam no ranking (proximidade alta):** **{subiram:,}** ({subiram/len(rows)*100:.2f}%)
* **Matches que cairiam no ranking (distância excessiva):** **{cairam:,}** ({cairam/len(rows)*100:.2f}%)
* **Matches que manteriam a posição exata:** **{iguais:,}** ({iguais/len(rows)*100:.2f}%)

---

## ⚠️ Exemplos de Matches Altamente Ineficientes (Geografia Ruim)
Estes matches possuem notas altas pelo score logístico/comercial tradicional, mas estão excessivamente distantes, o que resultará em custos logísticos elevados ou caminhões rodando vazios:

{conflitos_md}

---

## 💎 Exemplos de Matches Ideais (Excelência Comercial e Logística)
Estes matches atendem a todos os critérios operacionais e comerciais e estão localizados na mesma cidade ou região:

{excelentes_md}

---

## 📢 Recomendação e Próximos Passos

1. **Ativação Recomendada:**
   * A ativação do **Score Match V2** é fortemente recomendada para o pipeline comercial. Ela reduzirá o desperdício operacional ao rebaixar matches com distância excessiva (ex: transportadora e embarcador em cidades opostas com scores antigos artificialmente elevados).
2. **Capping de Precisão:**
   * O teto máximo de **70 pontos** no score geográfico para geocodificação em nível **cidade** (centroide municipal) protege o sistema contra falsos positivos, estimulando a equipe a enriquecer endereços exatos (rua e CEP).
3. **Próximo Passo:**
   * Adicionar ordenação por `score_match_v2` na interface `/matches` de forma opcional (chave de filtro) antes de torná-la o padrão definitivo do sistema.
"""
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content.strip())
        
    print(f"Relatório comparativo gerado com sucesso em: {md_path}")

if __name__ == "__main__":
    main()
