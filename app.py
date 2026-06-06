import csv
import io
from datetime import datetime
from functools import wraps

from flask import (Flask, Response, flash, jsonify, redirect,
                   render_template, request, session, url_for)
from flask_sqlalchemy import SQLAlchemy

from config import Config
from models import ImportLog, Transportadora, db
from jobs import iniciar_importacao

app = Flask(__name__)
app.config["SECRET_KEY"]        = Config.SECRET_KEY
app.config["SQLALCHEMY_DATABASE_URI"] = Config.DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

with app.app_context():
    db.create_all()


# ─── Auth simples (sessão) ────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logado"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("senha") == Config.ADMIN_PASSWORD:
            session["logado"] = True
            return redirect(url_for("index"))
        flash("Senha incorreta.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ─── Dashboard principal ──────────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    corredor  = request.args.get("corredor", "")
    uf        = request.args.get("uf", "")
    status    = request.args.get("status", "")
    cnae_ok   = request.args.get("cnae_frete", "")
    busca     = request.args.get("q", "").strip()

    query = Transportadora.query

    if corredor:
        query = query.filter_by(corredor=corredor)
    if uf:
        query = query.filter_by(uf=uf)
    if status:
        query = query.filter_by(status_crm=status)
    if cnae_ok == "1":
        query = query.filter_by(tem_cnae_frete=True)
    if busca:
        like = f"%{busca}%"
        query = query.filter(
            db.or_(
                Transportadora.razao_social.ilike(like),
                Transportadora.nome_rntrc.ilike(like),
                Transportadora.cnpj.ilike(like),
                Transportadora.municipio.ilike(like),
                Transportadora.socios.ilike(like),
            )
        )

    empresas = query.order_by(
        Transportadora.tem_cnae_frete.desc(),
        Transportadora.status_crm,
        Transportadora.razao_social,
    ).all()

    # Estatísticas por corredor
    stats = {}
    for nome_corredor in Config.CORREDORES:
        total     = Transportadora.query.filter_by(corredor=nome_corredor).count()
        com_frete = Transportadora.query.filter_by(corredor=nome_corredor, tem_cnae_frete=True).count()
        clientes  = Transportadora.query.filter_by(corredor=nome_corredor, status_crm="cliente").count()
        stats[nome_corredor] = {
            "total":     total,
            "com_frete": com_frete,
            "clientes":  clientes,
        }

    # Último log de importação
    ultimo_log = ImportLog.query.order_by(ImportLog.iniciado.desc()).first()

    ufs = [r[0] for r in db.session.query(Transportadora.uf).distinct().order_by(Transportadora.uf).all() if r[0]]

    return render_template(
        "index.html",
        empresas      = empresas,
        stats         = stats,
        corredores    = Config.CORREDORES,
        status_labels = Config.STATUS_LABELS,
        status_list   = Config.STATUS_CRM,
        ultimo_log    = ultimo_log,
        filtros       = dict(corredor=corredor, uf=uf, status=status,
                             cnae_frete=cnae_ok, q=busca),
        ufs           = ufs,
    )


# ─── Detalhe / atualização CRM ───────────────────────────────────────────────

@app.route("/empresa/<int:empresa_id>", methods=["POST"])
@login_required
def atualizar_empresa(empresa_id):
    empresa = Transportadora.query.get_or_404(empresa_id)
    empresa.status_crm     = request.form.get("status_crm", empresa.status_crm)
    empresa.notas          = request.form.get("notas", empresa.notas)
    empresa.ultimo_contato = datetime.utcnow()
    empresa.atualizado_em  = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True, "status": empresa.status_crm})


# ─── Importação ──────────────────────────────────────────────────────────────

@app.route("/importar", methods=["POST"])
@login_required
def importar():
    corredor = request.form.get("corredor")
    if corredor not in Config.CORREDORES:
        return jsonify({"erro": "Corredor inválido"}), 400

    log_id, ja_rodava = iniciar_importacao(app, corredor)
    if log_id is None:
        flash(f"Não foi possível iniciar importação de {corredor}. Tente novamente.", "danger")
    elif ja_rodava:
        flash(f"Importação de {corredor} já está em andamento (log #{log_id}). Aguarde a anterior concluir.", "warning")
    else:
        flash(f"Importação do corredor {corredor} iniciada (log #{log_id}). Aguarde alguns minutos.", "info")
    return redirect(url_for("index"))


@app.route("/status-importacao/<int:log_id>")
@login_required
def status_importacao(log_id):
    log = ImportLog.query.get_or_404(log_id)
    return jsonify({
        "status":     log.status,
        "total":      log.total,
        "processado": log.processado,
        "mensagem":   log.mensagem,
        "pct":        round(log.processado / max(log.total, 1) * 100),
    })


# ─── Export CSV ──────────────────────────────────────────────────────────────

@app.route("/exportar")
@login_required
def exportar():
    corredor = request.args.get("corredor", "")
    status   = request.args.get("status", "")

    query = Transportadora.query
    if corredor:
        query = query.filter_by(corredor=corredor)
    if status:
        query = query.filter_by(status_crm=status)

    empresas = query.order_by(Transportadora.corredor, Transportadora.razao_social).all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow([
        "corredor", "cnpj", "razao_social", "municipio", "uf",
        "telefone", "email", "socios", "cnae_frete", "porte",
        "status_crm", "notas", "link",
    ])
    for e in empresas:
        writer.writerow([
            e.corredor, e.cnpj, e.razao_social or e.nome_rntrc,
            e.municipio, e.uf, e.telefone or "", e.email or "",
            e.socios or "", "Sim" if e.tem_cnae_frete else "Não",
            e.porte or "", e.status_crm, e.notas or "",
            f"https://www.cnpj.ws/{e.cnpj.replace('.','').replace('/','').replace('-','')}",
        ])

    output.seek(0)
    nome_arquivo = f"transportadoras_{corredor.replace('→','-') or 'todas'}.csv"
    return Response(
        output.getvalue().encode("utf-8-sig"),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={nome_arquivo}"},
    )


# ─── Health check ─────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({"status": "ok", "ts": datetime.utcnow().isoformat()})


if __name__ == "__main__":
    app.run(debug=True)
