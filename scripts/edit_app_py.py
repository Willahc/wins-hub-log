"""
Apply edits to app.py: add global audit data to qualidade-score + API endpoint.
"""
import os, json

APP_PATH = "/home/william/repos/wins-hub-log/app.py"
AUDIT_PATH = "/opt/caminhao_vazio/logs/auditoria_score_global/resumo_global.json"

with open(APP_PATH, "r", encoding="utf-8") as f:
    content = f.read()

# Load audit data
audit_data = json.load(open(AUDIT_PATH))

# Update qualidade_score_page to include global audit data
old_page = '''@app.route("/qualidade-score")
@login_required
def qualidade_score_page():
    data = qualidade_score.diagnosticar_snapshots()
    vazamento = qualidade_score.verificar_vazamento_temporal()
    calibracao = qualidade_score.metricas_calibracao()
    return render_template("qualidade_score.html",
        data=data,
        vazamento=vazamento,
        calibracao=calibracao,
        now=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        MIN_TERMINAIS=qualidade_score.MIN_TERMINAIS,
        MIN_RESULTADOS=qualidade_score.MIN_RESULTADOS,
        logado=session.get("logado", False),
    )'''

new_page = '''@app.route("/qualidade-score")
@login_required
def qualidade_score_page():
    data = qualidade_score.diagnosticar_snapshots()
    vazamento = qualidade_score.verificar_vazamento_temporal()
    calibracao = qualidade_score.metricas_calibracao()
    # Carregar auditoria global do arquivo
    global_audit = {}
    audit_path = "/opt/caminhao_vazio/logs/auditoria_score_global/resumo_global.json"
    try:
        with open(audit_path) as f:
            global_audit = json.load(f)
    except Exception:
        global_audit = {"erro": "Auditoria global ainda nao executada"}
    return render_template("qualidade_score.html",
        data=data,
        vazamento=vazamento,
        calibracao=calibracao,
        global_audit=global_audit,
        now=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        MIN_TERMINAIS=qualidade_score.MIN_TERMINAIS,
        MIN_RESULTADOS=qualidade_score.MIN_RESULTADOS,
        logado=session.get("logado", False),
    )'''

content = content.replace(old_page, new_page, 1)

# Update api_qualidade_score to include global audit
old_api = '''@app.route("/api/metricas/qualidade-score")
@login_required
def api_qualidade_score():
    try:
        data = qualidade_score.diagnosticar_snapshots()
        vazamento = qualidade_score.verificar_vazamento_temporal()
        return jsonify({"ok": True, "data": data, "vazamento": vazamento})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500'''

new_api = '''@app.route("/api/metricas/qualidade-score")
@login_required
def api_qualidade_score():
    try:
        data = qualidade_score.diagnosticar_snapshots()
        vazamento = qualidade_score.verificar_vazamento_temporal()
        global_audit = {}
        try:
            with open("/opt/caminhao_vazio/logs/auditoria_score_global/resumo_global.json") as f:
                global_audit = json.load(f)
        except Exception:
            pass
        return jsonify({"ok": True, "data": data, "vazamento": vazamento, "global_audit": global_audit})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


@app.route("/api/metricas/distribuicao-score")
@login_required
def api_distribuicao_score():
    resp = {}
    try:
        with open("/opt/caminhao_vazio/logs/auditoria_score_global/resumo_global.json") as f:
            resp = json.load(f)
        resp["ok"] = True
    except Exception as e:
        resp = {"ok": False, "erro": str(e)}
    response = jsonify(resp)
    response.headers["Cache-Control"] = "private, no-store"
    return response'''

content = content.replace(old_api, new_api, 1)

# Add json import at the top if not present
if "import json" not in content.splitlines()[0:20]:
    content = content.replace("import csv\nimport io", "import csv\nimport io\nimport json", 1)

with open(APP_PATH, "w", encoding="utf-8") as f:
    f.write(content)

print("app.py updated with global audit data.")
print(f"Total lines: {len(content.splitlines())}")

