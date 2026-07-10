"""
Auditoria global da distribuicao do score de oportunidade.

Processa todos os matches elegiveis em batches, reutilizando 
build_match_opportunity() da producao. Apenas leitura.
"""
import os, sys, json, math, csv, time
from datetime import datetime, date as _date
from collections import Counter, defaultdict

# Add project to path
BASE = "/home/william/repos/wins-hub-log"
sys.path.insert(0, BASE)
os.chdir(BASE)

# Use the production app directly
from app import app, db, MatchPreditivo, build_match_opportunity, MATCH_SCORE_FORMULA_VERSION
from services import inteligencia_rota as ir

# ============================================================
# Config
# ============================================================
BATCH_SIZE = 500
OUT_DIR = "/opt/caminhao_vazio/logs/auditoria_score_global"
os.makedirs(OUT_DIR, exist_ok=True)

NOW = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

# ============================================================
# Stats accumulators
# ============================================================
scores = []
componentes_acum = defaultdict(list)
sem_score = 0
dados_insuficientes = 0
erros = 0
total_matches = 0
sem_intel_origem = 0
sem_intel_destino = 0

# Component names and max values from build_match_opportunity
COMPONENTES = ["match_original", "forca_logistica", "retorno_vazio", 
               "confianca", "momento_operacional", "penalidades"]
COMPONENTE_MAX = {"match_original": 20, "forca_logistica": 20, 
                  "retorno_vazio": 25, "confianca": 15,
                  "momento_operacional": 15, "penalidades": 15}

# ============================================================
# Helpers
# ============================================================
def _percentil(sorted_data, p):
    if not sorted_data:
        return None
    n = len(sorted_data)
    k = (p / 100.0) * (n - 1)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_data[int(k)]
    d0 = sorted_data[int(f)] * (c - k)
    d1 = sorted_data[int(c)] * (k - f)
    return round(d0 + d1, 2)

def _estatisticas(vals):
    n = len(vals)
    if n == 0:
        return {}
    s = sorted(vals)
    soma = sum(vals)
    media = soma / n
    
    # Variance
    var = sum((x - media) ** 2 for x in vals) / n
    std = math.sqrt(var)
    
    # Unique
    unicos = len(set(vals))
    
    # Mode
    counter = Counter(vals)
    moda_val, moda_cnt = counter.most_common(1)[0]
    
    # Quartiles
    q1 = _percentil(s, 25)
    q2 = _percentil(s, 50)
    q3 = _percentil(s, 75)
    iqr = q3 - q1 if q3 is not None and q1 is not None else None
    
    return {
        "n": n,
        "unicos": unicos,
        "min": min(vals),
        "max": max(vals),
        "media": round(media, 2),
        "mediana": q2,
        "moda": moda_val,
        "moda_freq": moda_cnt,
        "desvio_padrao": round(std, 2),
        "variancia": round(var, 2),
        "amplitude": max(vals) - min(vals),
        "q1": q1,
        "q3": q3,
        "iqr": iqr,
        "coef_variacao": round(std / media * 100, 2) if media > 0 else None,
        "p1": _percentil(s, 1),
        "p5": _percentil(s, 5),
        "p10": _percentil(s, 10),
        "p20": _percentil(s, 20),
        "p25": q1,
        "p50": q2,
        "p75": q3,
        "p80": _percentil(s, 80),
        "p90": _percentil(s, 90),
        "p95": _percentil(s, 95),
        "p99": _percentil(s, 99),
    }

# ============================================================
# Main audit
# ============================================================
def auditar():
    global total_matches, sem_score, dados_insuficientes, erros
    global sem_intel_origem, sem_intel_destino
    
    print(f"Iniciando auditoria global de distribuicao de score...")
    print(f"Formula: {MATCH_SCORE_FORMULA_VERSION}")
    print(f"Batch size: {BATCH_SIZE}")
    print(f"Output: {OUT_DIR}")
    print()
    
    t0 = time.time()
    
    with app.app_context():
        # Count total
        total = db.session.query(MatchPreditivo.id).count()
        total_matches = total
        print(f"Total de matches na base: {total}")
        
        # Get min/max IDs for pagination
        row = db.session.query(
            db.func.min(MatchPreditivo.id).label("min_id"),
            db.func.max(MatchPreditivo.id).label("max_id")
        ).first()
        min_id, max_id = row.min_id or 0, row.max_id or 0
        print(f"ID range: {min_id} - {max_id}")
        print()
        
        processed = 0
        batch_num = 0
        checkpoint_id = min_id
        
        while checkpoint_id <= max_id:
            batch_end = checkpoint_id + BATCH_SIZE - 1
            
            # Batch load matches
            matches = db.session.query(MatchPreditivo).filter(
                MatchPreditivo.id >= checkpoint_id,
                MatchPreditivo.id <= batch_end
            ).order_by(MatchPreditivo.id).all()
            
            if not matches:
                checkpoint_id = batch_end + 1
                continue
            
            batch_num += 1
            processed += len(matches)
            
            # Collect unique locations for intelligence
            locations = []
            seen_locs = set()
            for m in matches:
                if m.uf_origem:
                    loc = (m.uf_origem, (m.cidade_origem or "").upper())
                    if loc not in seen_locs:
                        seen_locs.add(loc)
                        locations.append({"uf": loc[0], "municipio": loc[1].title()})
                if m.uf_destino:
                    loc = (m.uf_destino, (m.cidade_destino or "").upper())
                    if loc not in seen_locs:
                        seen_locs.add(loc)
                        locations.append({"uf": loc[0], "municipio": loc[1].title()})
            
            # Get intelligence (batched)
            intel_result = {}
            try:
                if ir.rota_configured() and locations:
                    intel_result = ir.get_matches_inteligencia(locations)
                    if intel_result.get("status") == "ok":
                        intel_result = intel_result.get("results", {})
                    else:
                        intel_result = {}
            except Exception:
                intel_result = {}
            
            # Build key lookup
            intel_map = {}
            for m in matches:
                key_origem = (m.uf_origem + "::" + (m.cidade_origem or "").upper()) if (m.cidade_origem and m.uf_origem) else (m.uf_origem + "::") if m.uf_origem else None
                key_destino = (m.uf_destino + "::" + (m.cidade_destino or "").upper()) if (m.cidade_destino and m.uf_destino) else (m.uf_destino + "::") if m.uf_destino else None
                m.intel_origem = intel_map.get(key_origem) or intel_result.get(key_origem, {}) if key_origem else {}
                m.intel_destino = intel_map.get(key_destino) or intel_result.get(key_destino, {}) if key_destino else {}
                # Cache in map for reuse
                if key_origem:
                    intel_map[key_origem] = m.intel_origem
                if key_destino:
                    intel_map[key_destino] = m.intel_destino
            
            # Calculate explicacao + oportunidade for each match
            for m in matches:
                try:
                    m.explicacao = ir.get_match_explicado(m, m.intel_origem, m.intel_destino)
                    if not m.explicacao:
                        dados_insuficientes += 1
                        continue
                    
                    oport = build_match_opportunity(m, m.explicacao, m.intel_origem, m.intel_destino)
                    
                    score_val = oport.get("score_oportunidade")
                    if score_val is None:
                        sem_score += 1
                        continue
                    
                    scores.append(score_val)
                    
                    comps = oport.get("componentes", {})
                    for cname in COMPONENTES:
                        val = comps.get(cname, {}).get("pontos", 0)
                        if val is None:
                            val = 0
                        componentes_acum[cname].append(val)
                    
                    if not m.intel_origem:
                        sem_intel_origem += 1
                    if not m.intel_destino:
                        sem_intel_destino += 1
                        
                except Exception as e:
                    erros += 1
                    if erros <= 5:
                        print(f"  Erro match {m.id}: {e}")
            
            # Progress
            if batch_num % 5 == 0 or processed >= total:
                pct = processed / total * 100 if total > 0 else 0
                elapsed = time.time() - t0
                rate = processed / elapsed if elapsed > 0 else 0
                print(f"  Batch {batch_num}: {processed}/{total} ({pct:.1f}%) - {rate:.0f} matches/s - scores acum: {len(scores)}")
            
            checkpoint_id = batch_end + 1
        
        # ============================================================
        # Compute statistics
        # ============================================================
        print(f"\nProcessamento concluido em {time.time()-t0:.1f}s")
        print(f"Total processado: {processed}")
        print(f"Total com score: {len(scores)}")
        
        if not scores:
            print("ERRO: Nenhum score coletado!")
            return None
        
        est = _estatisticas(scores)
        
        # Classificacao distribution
        faixas = {"revisar_dados": [], "baixa_prioridade": [], "acompanhar": [],
                  "alta_prioridade": [], "agir_agora": []}
        for s in scores:
            if s >= 80: faixas["agir_agora"].append(s)
            elif s >= 60: faixas["alta_prioridade"].append(s)
            elif s >= 40: faixas["acompanhar"].append(s)
            elif s >= 20: faixas["baixa_prioridade"].append(s)
            else: faixas["revisar_dados"].append(s)
        
        faixa_stats = {}
        for nome, vals in faixas.items():
            n = len(vals)
            faixa_stats[nome] = {
                "quantidade": n,
                "percentual": round(n / len(scores) * 100, 2) if scores else 0,
                "score_medio": round(sum(vals) / n, 2) if n > 0 else None,
            }
        
        # Histograms
        hist_10 = defaultdict(int)
        hist_5 = defaultdict(int)
        hist_1 = Counter(scores)
        for s in scores:
            hist_10[(s // 10) * 10] += 1
            hist_5[(s // 5) * 5] += 1
        
        # Compression metrics
        sorted_scores = sorted(scores)
        n_scores = len(scores)
        
        # Modal concentration
        modal_5_range = (est["moda"] // 5) * 5
        modal_5_count = hist_5.get(modal_5_range, 0)
        pct_modal_5 = modal_5_count / n_scores * 100
        
        around_median_2 = sum(1 for s in scores if abs(s - est["mediana"]) <= 2)
        around_median_5 = sum(1 for s in scores if abs(s - est["mediana"]) <= 5)
        
        p90_minus_p10 = (est["p90"] or 0) - (est["p10"] or 0)
        
        sat_piso = sum(1 for s in scores if s == est["min"])
        sat_teto = sum(1 for s in scores if s == est["max"])
        
        # Alerts
        alertas = []
        if max(v["percentual"] for v in faixa_stats.values()) > 70:
            alertas.append("MAIS_70_MESMA_CLASSIFICACAO")
        if pct_modal_5 > 50:
            alertas.append("MAIS_50_INTERVALO_5")
        if est["unicos"] < 15:
            alertas.append("MENOS_15_SCORES_UNICOS")
        if est["desvio_padrao"] < 5:
            alertas.append("DESVIO_PADRAO_INFERIOR_5")
        if p90_minus_p10 < 10:
            alertas.append("P90_P10_INFERIOR_10")
        if est["moda_freq"] / n_scores > 0.30:
            alertas.append("MAIS_30_MESMO_SCORE")
        
        compressao = {
            "pct_modal_5": round(pct_modal_5, 2),
            "pct_around_median_2": round(around_median_2 / n_scores * 100, 2),
            "pct_around_median_5": round(around_median_5 / n_scores * 100, 2),
            "p90_minus_p10": p90_minus_p10,
            "ratio_unicos_total": round(est["unicos"] / n_scores, 4),
            "sat_piso_pct": round(sat_piso / n_scores * 100, 2),
            "sat_teto_pct": round(sat_teto / n_scores * 100, 2),
            "pct_modal": round(est["moda_freq"] / n_scores * 100, 2),
            "alertas": alertas,
        }
        
        # Component stats
        comp_stats = {}
        for cname in COMPONENTES:
            vals = componentes_acum.get(cname, [])
            if not vals:
                comp_stats[cname] = {"n": 0, "status": "sem_dados"}
                continue
            total = len(vals)
            ausentes = total - sum(1 for v in vals if v != 0)  # not exactly right for "ausente"
            # Proper ausente = when componente not present in dict
            # We stored 0 for missing components, so we need to know
            c_est = _estatisticas(vals)
            c_est["maximo"] = COMPONENTE_MAX.get(cname, 0)
            c_est["contrib_media"] = round(c_est["media"], 2)
            if COMPONENTE_MAX.get(cname, 0) > 0 and est.get("media", 0) > 0:
                c_est["contrib_pct"] = round(c_est["media"] / est["media"] * 100, 1) if est["media"] > 0 else 0
            else:
                c_est["contrib_pct"] = 0
            comp_stats[cname] = c_est
        
        # Build complete result
        result = {
            "metadados": {
                "data_auditoria": datetime.utcnow().isoformat(),
                "formula_versao": MATCH_SCORE_FORMULA_VERSION,
                "batch_size": BATCH_SIZE,
                "tempo_execucao_s": round(time.time() - t0, 1),
            },
            "processamento": {
                "total_base": total_matches,
                "total_processado": processed,
                "total_com_score": len(scores),
                "sem_score": sem_score,
                "dados_insuficientes": dados_insuficientes,
                "erros": erros,
                "sem_intel_origem": sem_intel_origem,
                "sem_intel_destino": sem_intel_destino,
            },
            "estatisticas": est,
            "distribuicao_faixas": faixa_stats,
            "compressao": compressao,
            "histograma_10": {str(k): v for k, v in sorted(hist_10.items())},
            "histograma_5": {str(k): v for k, v in sorted(hist_5.items())},
            "histograma_1": {str(k): v for k, v in sorted(hist_1.items())},
            "componentes": comp_stats,
        }
        
        # Write JSON
        json_path = os.path.join(OUT_DIR, "resumo_global.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"\nJSON escrito: {json_path}")
        
        # Write CSVs
        _write_csv_faixas(result)
        _write_csv_scores(result)
        _write_csv_componentes(result)
        _write_csv_percentis(result)
        
        return result


def _write_csv_faixas(result):
    path = os.path.join(OUT_DIR, "distribuicao_faixas.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["faixa", "quantidade", "percentual", "score_medio"])
        for faixa, st in result["distribuicao_faixas"].items():
            w.writerow([faixa, st["quantidade"], st["percentual"], st["score_medio"]])
    print(f"CSV faixas: {path}")


def _write_csv_scores(result):
    path = os.path.join(OUT_DIR, "distribuicao_scores.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["score", "frequencia"])
        for score, freq in sorted(result["histograma_1"].items(), key=lambda x: int(x[0])):
            w.writerow([score, freq])
    print(f"CSV scores: {path}")


def _write_csv_componentes(result):
    path = os.path.join(OUT_DIR, "componentes.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["componente", "n", "min", "max", "media", "mediana", "desvio_padrao",
                     "p10", "p25", "p50", "p75", "p90", "p95", "unicos",
                     "contrib_media", "maximo_teorico"])
        for cname, st in result["componentes"].items():
            w.writerow([
                cname, st.get("n", 0), st.get("min", ""), st.get("max", ""),
                st.get("media", ""), st.get("mediana", ""), st.get("desvio_padrao", ""),
                st.get("p10", ""), st.get("p25", ""), st.get("p50", ""),
                st.get("p75", ""), st.get("p90", ""), st.get("p95", ""),
                st.get("unicos", ""), st.get("contrib_media", ""),
                st.get("maximo", "")
            ])
    print(f"CSV componentes: {path}")


def _write_csv_percentis(result):
    path = os.path.join(OUT_DIR, "amostra_percentis.csv")
    est = result["estatisticas"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["metrica", "valor"])
        for key in ["p1", "p5", "p10", "p20", "p25", "p50", "p75", "p80", "p90", "p95", "p99"]:
            w.writerow([f"percentil_{key}", est.get(key)])
    print(f"CSV percentis: {path}")


if __name__ == "__main__":
    result = auditar()
    
    if result:
        print("\n=== RESUMO FINAL ===")
        print(f"Total auditado: {result['processamento']['total_processado']}")
        print(f"Com score valido: {result['processamento']['total_com_score']}")
        print(f"Scores unicos: {result['estatisticas']['unicos']}")
        print(f"Min: {result['estatisticas']['min']}")
        print(f"Max: {result['estatisticas']['max']}")
        print(f"Media: {result['estatisticas']['media']}")
        print(f"Mediana: {result['estatisticas']['mediana']}")
        print(f"Desvio padrao: {result['estatisticas']['desvio_padrao']}")
        print(f"P10: {result['estatisticas']['p10']}  P25: {result['estatisticas']['p25']}  P50: {result['estatisticas']['p50']}  P75: {result['estatisticas']['p75']}  P90: {result['estatisticas']['p90']}  P99: {result['estatisticas']['p99']}")
        print(f"Distribuicao:")
        for faixa, st in result["distribuicao_faixas"].items():
            print(f"  {faixa}: {st['quantidade']} ({st['percentual']}%) media={st['score_medio']}")
        print(f"Alertas: {result['compressao']['alertas']}")
        print(f"Tempo: {result['metadados']['tempo_execucao_s']}s")
