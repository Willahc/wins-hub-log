"""
Teste de paridade: comparar scores do auditor com scores da pagina /matches.
"""
import os, sys, json
sys.path.insert(0, "/home/william/repos/wins-hub-log")
os.chdir("/home/william/repos/wins-hub-log")

from app import app, db, MatchPreditivo, build_match_opportunity, MATCH_SCORE_FORMULA_VERSION
from services import inteligencia_rota as ir

with app.app_context():
    # Get 20 matches across different IDs
    ids = range(1, 10000, 500)  # 20 matches spread across the range
    matches = db.session.query(MatchPreditivo).filter(MatchPreditivo.id.in_(ids)).all()
    
    # Get intelligence for all locations
    locations = []
    for m in matches:
        if m.uf_origem:
            locations.append({"uf": m.uf_origem, "municipio": (m.cidade_origem or "").title()})
        if m.uf_destino:
            locations.append({"uf": m.uf_destino, "municipio": (m.cidade_destino or "").title()})
    
    intel_result = ir.get_matches_inteligencia(locations) if ir.rota_configured() else {}
    if intel_result.get("status") == "ok":
        intel_result = intel_result.get("results", {})
    else:
        intel_result = {}
    
    differences = []
    print(f"Teste de paridade - {MATCH_SCORE_FORMULA_VERSION}")
    print(f"{'ID':>6} {'Auditor':>8} {'Detalhes'}")
    print("-" * 60)
    
    for m in matches:
        key_origem = (m.uf_origem + "::" + (m.cidade_origem or "").upper()) if (m.cidade_origem and m.uf_origem) else (m.uf_origem + "::") if m.uf_origem else None
        key_destino = (m.uf_destino + "::" + (m.cidade_destino or "").upper()) if (m.cidade_destino and m.uf_destino) else (m.uf_destino + "::") if m.uf_destino else None
        
        intel_o = intel_result.get(key_origem, {}) if key_origem else {}
        intel_d = intel_result.get(key_destino, {}) if key_destino else {}
        
        explicacao = ir.get_match_explicado(m, intel_o, intel_d)
        oport = build_match_opportunity(m, explicacao, intel_o, intel_d)
        
        score_auditor = oport.get("score_oportunidade", 0)
        classificacao = oport.get("classificacao_oportunidade", "")
        componentes = oport.get("componentes", {})
        
        comp_str = " ".join([f"{k}={v.get('pontos',0)}" for k,v in componentes.items()])
        print(f"{m.id:>6} {score_auditor:>8}  {classificacao:20s}  {comp_str[:60]}")
    
    print(f"\nDiferencas encontradas: {len(differences)}")
