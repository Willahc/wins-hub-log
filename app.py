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

PAGE_SIZE = 100

@app.route("/")
@login_required
def index():
    corredor  = request.args.get("corredor", "")
    uf        = request.args.get("uf", "")
    status    = request.args.get("status", "")
    cnae_ok   = request.args.get("cnae_frete", "")
    busca     = request.args.get("q", "").strip()
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1

    tem_filtro = bool(corredor or uf or status or cnae_ok == "1" or busca)

    # Stats em UMA query agregada (era N×3 queries antes)
    stats = {nome: {"total": 0, "com_frete": 0, "clientes": 0} for nome in Config.CORREDORES}
    agregados = db.session.query(
        Transportadora.corredor,
        db.func.count().label("total"),
        db.func.sum(db.case((Transportadora.tem_cnae_frete.is_(True), 1), else_=0)).label("com_frete"),
        db.func.sum(db.case((Transportadora.status_crm == "cliente", 1), else_=0)).label("clientes"),
    ).group_by(Transportadora.corredor).all()
    for cor, total, com_frete, clientes in agregados:
        if cor in stats:
            stats[cor] = {"total": int(total or 0),
                          "com_frete": int(com_frete or 0),
                          "clientes":  int(clientes or 0)}

    ultimo_log = ImportLog.query.order_by(ImportLog.iniciado.desc()).first()
    ufs = [r[0] for r in db.session.query(Transportadora.uf).distinct().order_by(Transportadora.uf).all() if r[0]]

    # Sem filtro → não carrega lista (cards stats + prompt). Evita render de 7k linhas.
    if not tem_filtro:
        return render_template(
            "index.html",
            empresas=[], total_empresas=0, page=1, total_pages=1, page_size=PAGE_SIZE,
            stats=stats, corredores=Config.CORREDORES,
            status_labels=Config.STATUS_LABELS, status_list=Config.STATUS_CRM,
            ultimo_log=ultimo_log,
            filtros=dict(corredor="", uf="", status="", cnae_frete="", q=""),
            ufs=ufs, sem_filtro=True,
        )

    query = Transportadora.query
    if corredor: query = query.filter_by(corredor=corredor)
    if uf:       query = query.filter_by(uf=uf)
    if status:   query = query.filter_by(status_crm=status)
    if cnae_ok == "1":
        query = query.filter_by(tem_cnae_frete=True)
    if busca:
        like = f"%{busca}%"
        query = query.filter(db.or_(
            Transportadora.razao_social.ilike(like),
            Transportadora.nome_rntrc.ilike(like),
            Transportadora.cnpj.ilike(like),
            Transportadora.municipio.ilike(like),
            Transportadora.socios.ilike(like),
        ))

    query = query.order_by(
        Transportadora.tem_cnae_frete.desc(),
        Transportadora.status_crm,
        Transportadora.razao_social,
    )

    total_empresas = query.count()
    total_pages = max(1, (total_empresas + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, total_pages)
    empresas = query.limit(PAGE_SIZE).offset((page - 1) * PAGE_SIZE).all()

    return render_template(
        "index.html",
        empresas=empresas, total_empresas=total_empresas,
        page=page, total_pages=total_pages, page_size=PAGE_SIZE,
        stats=stats, corredores=Config.CORREDORES,
        status_labels=Config.STATUS_LABELS, status_list=Config.STATUS_CRM,
        ultimo_log=ultimo_log,
        filtros=dict(corredor=corredor, uf=uf, status=status, cnae_frete=cnae_ok, q=busca),
        ufs=ufs, sem_filtro=False,
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
