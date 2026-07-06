import csv
import io
from datetime import datetime
from functools import wraps

from flask import (Flask, Response, flash, jsonify, redirect,
                   render_template, request, session, url_for)
from flask_sqlalchemy import SQLAlchemy

from config import Config
from models import ImportLog, Transportadora, EmbarcadorProvavel, MatchPreditivo, db
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

    # Injetar dados do radar preditivo em memória
    from radar.scoring import avaliar_transportadora
    for e in empresas:
        res = avaliar_transportadora(e)
        e.radar_score = res["score_total"]
        e.radar_prioridade = res["prioridade"]
        e.radar_setor = res["setor_predito"]
        e.radar_tipo_carga = res["tipo_carga_provavel"]
        e.radar_carrocerias = res["carrocerias_provaveis"]
        e.radar_justificativa = res["justificativa"]

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
        "radar_score", "radar_prioridade", "radar_setor", "radar_tipo_carga", "radar_carrocerias", "radar_justificativa"
    ])
    from radar.scoring import avaliar_transportadora
    for e in empresas:
        res = avaliar_transportadora(e)
        writer.writerow([
            e.corredor, e.cnpj, e.razao_social or e.nome_rntrc,
            e.municipio, e.uf, e.telefone or "", e.email or "",
            e.socios or "", "Sim" if e.tem_cnae_frete else "Não",
            e.porte or "", e.status_crm, e.notas or "",
            f"https://www.cnpj.ws/{e.cnpj.replace('.','').replace('/','').replace('-','')}",
            res["score_total"], res["prioridade"], res["setor_predito"], res["tipo_carga_provavel"], res["carrocerias_provaveis"], res["justificativa"]
        ])

    output.seek(0)
    nome_arquivo = f"transportadoras_{corredor.replace('→','-') or 'todas'}.csv"
    return Response(
        output.getvalue().encode("utf-8-sig"),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={nome_arquivo}"},
    )



# ─── Radar de Carga de Retorno ───────────────────────────────────────────────

@app.route("/radar")
@login_required
def radar():
    corredor  = request.args.get("corredor", "")
    uf        = request.args.get("uf", "")
    status    = request.args.get("status", "")
    cnae_ok   = request.args.get("cnae_frete", "")
    busca     = request.args.get("q", "").strip()
    min_score = request.args.get("min_score", "").strip()
    prioridade = request.args.get("prioridade", "").strip()

    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1

    # Stats para os cards
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

    candidatas = query.limit(2000).all()

    from radar.scoring import avaliar_transportadora
    empresas_radar = []
    for e in candidatas:
        res = avaliar_transportadora(e)
        e.radar_score = res["score_total"]
        e.radar_prioridade = res["prioridade"]
        e.radar_setor = res["setor_predito"]
        e.radar_tipo_carga = res["tipo_carga_provavel"]
        e.radar_carrocerias = res["carrocerias_provaveis"]
        e.radar_justificativa = res["justificativa"]

        # Filtros do radar
        if min_score:
            try:
                if e.radar_score < float(min_score):
                    continue
            except ValueError:
                pass
        if prioridade and e.radar_prioridade.lower() != prioridade.lower():
            continue

        empresas_radar.append(e)

    # Ordenar por score descrescente
    empresas_radar.sort(key=lambda x: x.radar_score, reverse=True)

    total_empresas = len(empresas_radar)
    PAGE_SIZE_RADAR = 50
    total_pages = max(1, (total_empresas + PAGE_SIZE_RADAR - 1) // PAGE_SIZE_RADAR)
    page = min(page, total_pages)
    empresas_paginadas = empresas_radar[(page - 1) * PAGE_SIZE_RADAR : page * PAGE_SIZE_RADAR]

    return render_template(
        "radar.html",
        empresas=empresas_paginadas, total_empresas=total_empresas,
        page=page, total_pages=total_pages, page_size=PAGE_SIZE_RADAR,
        stats=stats, corredores=Config.CORREDORES,
        status_labels=Config.STATUS_LABELS, status_list=Config.STATUS_CRM,
        ultimo_log=ultimo_log,
        filtros=dict(corredor=corredor, uf=uf, status=status, cnae_frete=cnae_ok, q=busca, min_score=min_score, prioridade=prioridade),
        ufs=ufs
    )



# ─── Radar de Embarcadores Prováveis ─────────────────────────────────────────

@app.route("/embarcadores")
@login_required
def embarcadores_lista():
    corredor   = request.args.get("corredor", "")
    uf         = request.args.get("uf", "")
    cidade     = request.args.get("cidade", "").strip()
    prioridade = request.args.get("prioridade", "")
    status     = request.args.get("status", "")
    busca      = request.args.get("q", "").strip()
    min_score  = request.args.get("min_score", "").strip()

    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1

    query = EmbarcadorProvavel.query
    if corredor:   query = query.filter_by(corredor_alvo=corredor)
    if uf:         query = query.filter_by(uf=uf)
    if cidade:     query = query.filter(EmbarcadorProvavel.cidade.ilike(f"%{cidade}%"))
    if prioridade: query = query.filter_by(prioridade=prioridade)
    if status:     query = query.filter_by(status_crm=status)
    if busca:
        like = f"%{busca}%"
        query = query.filter(db.or_(
            EmbarcadorProvavel.razao_social.ilike(like),
            EmbarcadorProvavel.nome_fantasia.ilike(like),
            EmbarcadorProvavel.cnpj.ilike(like),
            EmbarcadorProvavel.cnae_descricao.ilike(like),
        ))
    if min_score:
        try:
            query = query.filter(EmbarcadorProvavel.score_demanda >= float(min_score))
        except ValueError:
            pass

    # Ordenar por maior score de demanda primeiro
    query = query.order_by(EmbarcadorProvavel.score_demanda.desc(), EmbarcadorProvavel.razao_social)

    PAGE_SIZE_EMB = 50
    total_empresas = query.count()
    total_pages = max(1, (total_empresas + PAGE_SIZE_EMB - 1) // PAGE_SIZE_EMB)
    page = min(page, total_pages)
    
    embarcadores = query.limit(PAGE_SIZE_EMB).offset((page - 1) * PAGE_SIZE_EMB).all()

    ufs = [r[0] for r in db.session.query(EmbarcadorProvavel.uf).distinct().order_by(EmbarcadorProvavel.uf).all() if r[0]]
    
    # Stats para os cards
    stats = {nome: {"total": 0, "prioritarios": 0, "clientes": 0} for nome in Config.CORREDORES}
    agregados = db.session.query(
        EmbarcadorProvavel.corredor_alvo,
        db.func.count().label("total"),
        db.func.sum(db.case((EmbarcadorProvavel.prioridade == "Alta", 1), else_=0)).label("prioritarios"),
        db.func.sum(db.case((EmbarcadorProvavel.status_crm == "cliente", 1), else_=0)).label("clientes"),
    ).group_by(EmbarcadorProvavel.corredor_alvo).all()
    
    for cor, total, prioritarios, clientes in agregados:
        if cor in stats:
            stats[cor] = {"total": int(total or 0),
                          "prioritarios": int(prioritarios or 0),
                          "clientes": int(clientes or 0)}

    ultimo_log = ImportLog.query.order_by(ImportLog.iniciado.desc()).first()

    return render_template(
        "embarcadores.html",
        empresas=embarcadores, total_empresas=total_empresas,
        page=page, total_pages=total_pages, page_size=PAGE_SIZE_EMB,
        stats=stats, corredores=Config.CORREDORES,
        status_labels=Config.STATUS_LABELS, status_list=Config.STATUS_CRM,
        ultimo_log=ultimo_log,
        filtros=dict(corredor=corredor, uf=uf, cidade=cidade, prioridade=prioridade, status=status, q=busca, min_score=min_score),
        ufs=ufs
    )


@app.route("/embarcadores/importar", methods=["POST"])
@login_required
def importar_embarcadores():
    if "arquivo" not in request.files:
        flash("Nenhum arquivo enviado.", "danger")
        return redirect(url_for("embarcadores_lista"))
        
    file = request.files["arquivo"]
    if file.filename == "":
        flash("Nenhum arquivo selecionado.", "danger")
        return redirect(url_for("embarcadores_lista"))

    try:
        stream = io.StringIO(file.stream.read().decode("utf-8-sig"), newline=None)
    except UnicodeDecodeError:
        try:
            file.stream.seek(0)
            stream = io.StringIO(file.stream.read().decode("latin1"), newline=None)
        except Exception as e:
            flash(f"Erro ao decodificar arquivo: {e}", "danger")
            return redirect(url_for("embarcadores_lista"))

    sample = stream.read(2048)
    stream.seek(0)
    delimiter = ";" if ";" in sample else ","
    
    reader = csv.DictReader(stream, delimiter=delimiter)
    
    from radar.embarcadores import avaliar_embarcador
    
    sucessos = 0
    erros = 0
    
    for row in reader:
        cnpj = row.get("cnpj", "").strip()
        corredor_alvo = row.get("corredor_alvo", "").strip()
        if not cnpj or not corredor_alvo:
            erros += 1
            continue
            
        try:
            embarcador = EmbarcadorProvavel.query.filter_by(cnpj=cnpj, corredor_alvo=corredor_alvo).first()
            if not embarcador:
                embarcador = EmbarcadorProvavel(cnpj=cnpj, corredor_alvo=corredor_alvo)
                db.session.add(embarcador)
                
            embarcador.razao_social = row.get("razao_social", "").strip()
            embarcador.nome_fantasia = row.get("nome_fantasia", "").strip()
            embarcador.cidade = row.get("cidade", "").strip()
            embarcador.uf = row.get("uf", "").strip()
            embarcador.cnae = row.get("cnae", "").strip()
            embarcador.cnae_descricao = row.get("cnae_descricao", "").strip()
            embarcador.telefone = row.get("telefone", "").strip()
            embarcador.email = row.get("email", "").strip()
            embarcador.site = row.get("site", "").strip()
            embarcador.origem_provavel = row.get("origem_provavel", "").strip()
            embarcador.destino_provavel = row.get("destino_provavel", "").strip()
            embarcador.fonte = row.get("fonte", "").strip()
            
            # Avaliar Radar
            res = avaliar_embarcador(embarcador)
            embarcador.score_demanda = res["score_total"]
            embarcador.prioridade = res["prioridade"]
            embarcador.setor_predito = res["setor_predito"]
            embarcador.tipo_carga_provavel = res["tipo_carga_provavel"]
            embarcador.carrocerias_provaveis = res["carrocerias_provaveis"]
            embarcador.notas = row.get("notas", "").strip() or embarcador.notas

            db.session.commit()
            sucessos += 1
        except Exception as ex:
            db.session.rollback()
            erros += 1
            print(f"Erro ao importar linha {row}: {ex}")

    flash(f"Importação concluída. {sucessos} embarcadores importados/atualizados. {erros} erros.", "success" if erros == 0 else "warning")
    return redirect(url_for("embarcadores_lista"))


@app.route("/embarcadores/exportar")
@login_required
def exportar_embarcadores():
    corredor = request.args.get("corredor", "")
    status   = request.args.get("status", "")

    query = EmbarcadorProvavel.query
    if corredor:
        query = query.filter_by(corredor_alvo=corredor)
    if status:
        query = query.filter_by(status_crm=status)

    embarcadores = query.order_by(EmbarcadorProvavel.score_demanda.desc(), EmbarcadorProvavel.razao_social).all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow([
        "cnpj", "razao_social", "cidade", "uf", "cnae", "cnae_descricao",
        "setor_predito", "tipo_carga_provavel", "carrocerias_provaveis",
        "corredor_alvo", "origem_provavel", "destino_provavel",
        "score_demanda", "prioridade", "status_crm", "telefone", "email", "site", "notas"
    ])
    
    for e in embarcadores:
        writer.writerow([
            e.cnpj, e.razao_social or e.nome_fantasia,
            e.cidade, e.uf, e.cnae or "", e.cnae_descricao or "",
            e.setor_predito or "", e.tipo_carga_provavel or "", e.carrocerias_provaveis or "",
            e.corredor_alvo or "", e.origem_provavel or "", e.destino_provavel or "",
            e.score_demanda, e.prioridade, e.status_crm,
            e.telefone or "", e.email or "", e.site or "", e.notas or ""
        ])

    output.seek(0)
    nome_arquivo = f"embarcadores_{corredor.replace('→','-') or 'todos'}.csv"
    return Response(
        output.getvalue().encode("utf-8-sig"),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={nome_arquivo}"},
    )


@app.route("/embarcadores/<int:embarcador_id>/crm", methods=["POST"])
@login_required
def atualizar_embarcador_crm(embarcador_id):
    emb = EmbarcadorProvavel.query.get_or_404(embarcador_id)
    
    emb.status_crm      = request.form.get("status_crm", emb.status_crm)
    emb.notas           = request.form.get("notas", emb.notas)
    emb.telefone        = request.form.get("telefone", emb.telefone)
    emb.email           = request.form.get("email", emb.email)
    emb.site            = request.form.get("site", emb.site)
    emb.origem_provavel = request.form.get("origem_provavel", emb.origem_provavel)
    emb.destino_provavel= request.form.get("destino_provavel", emb.destino_provavel)
    emb.tipo_carga_provavel = request.form.get("tipo_carga_provavel", emb.tipo_carga_provavel)
    
    from radar.embarcadores import avaliar_embarcador
    res = avaliar_embarcador(emb)
    emb.score_demanda = res["score_total"]
    emb.prioridade = res["prioridade"]
    emb.setor_predito = res["setor_predito"]
    emb.carrocerias_provaveis = res["carrocerias_provaveis"]

    db.session.commit()
    return jsonify({
        "ok": True, 
        "status": emb.status_crm, 
        "score": emb.score_demanda, 
        "prioridade": emb.prioridade
    })



# ─── Match Preditivo (Cargas de Retorno) ──────────────────────────────────────

@app.route("/matches")
@login_required
def matches_lista():
    corredor   = request.args.get("corredor", "")
    prioridade = request.args.get("prioridade", "")
    status     = request.args.get("status", "")
    uf_origem  = request.args.get("uf_origem", "")
    uf_destino = request.args.get("uf_destino", "")
    min_score  = request.args.get("min_score", "").strip()

    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1

    query = MatchPreditivo.query
    if corredor:   query = query.filter_by(corredor=corredor)
    if prioridade: query = query.filter_by(prioridade=prioridade)
    if status:     query = query.filter_by(status=status)
    if uf_origem:  query = query.filter_by(uf_origem=uf_origem)
    if uf_destino: query = query.filter_by(uf_destino=uf_destino)
    if min_score:
        try:
            query = query.filter(MatchPreditivo.score_match >= float(min_score))
        except ValueError:
            pass

    # Ordenar por maior score de match decrescente
    query = query.order_by(MatchPreditivo.score_match.desc())

    PAGE_SIZE_MATCH = 50
    total_matches = query.count()
    total_pages = max(1, (total_matches + PAGE_SIZE_MATCH - 1) // PAGE_SIZE_MATCH)
    page = min(page, total_pages)
    
    matches = query.limit(PAGE_SIZE_MATCH).offset((page - 1) * PAGE_SIZE_MATCH).all()

    # Filtros dinâmicos no template
    ufs_origem = [r[0] for r in db.session.query(MatchPreditivo.uf_origem).distinct().order_by(MatchPreditivo.uf_origem).all() if r[0]]
    ufs_destino = [r[0] for r in db.session.query(MatchPreditivo.uf_destino).distinct().order_by(MatchPreditivo.uf_destino).all() if r[0]]
    
    # Stats resumidos
    stats = {
        "total": total_matches,
        "alta": MatchPreditivo.query.filter_by(prioridade="Alta").count(),
        "negociando": MatchPreditivo.query.filter_by(status="Negociando").count(),
        "fechados": MatchPreditivo.query.filter_by(status="Fechado").count()
    }

    # Opções de status e labels
    status_list = ["Sugerido", "Validar", "Abordar", "Em contato", "Negociando", "Fechado", "Descartado"]
    status_labels = {
        "Sugerido":   ("Sugerido",   "secondary"),
        "Validar":    ("Validar",    "info"),
        "Abordar":    ("Abordar",    "warning"),
        "Em contato": ("Em contato", "primary"),
        "Negociando": ("Negociando", "success"),
        "Fechado":    ("Fechado",    "success"),
        "Descartado": ("Descartado", "danger")
    }

    return render_template(
        "matches.html",
        matches=matches, total_empresas=total_matches,
        total_matches=total_matches,
        page=page, total_pages=total_pages, page_size=PAGE_SIZE_MATCH,
        stats=stats, corredores=Config.CORREDORES,
        status_labels=status_labels, status_list=status_list,
        filtros=dict(corredor=corredor, prioridade=prioridade, status=status, uf_origem=uf_origem, uf_destino=uf_destino, min_score=min_score),
        ufs_origem=ufs_origem, ufs_destino=ufs_destino
    )


@app.route("/matches/gerar", methods=["POST"])
@login_required
def gerar_matches():
    from radar.matching import gerar_matches_preditivos
    try:
        criados = gerar_matches_preditivos(db.session)
        flash(f"Processamento de Match concluído com sucesso. {criados} novos matches sugeridos gerados.", "success")
    except Exception as ex:
        flash(f"Erro ao gerar matches: {ex}", "danger")
        print(f"Erro ao gerar matches preditivos: {ex}")
    return redirect(url_for("matches_lista"))


@app.route("/matches/<int:match_id>/crm", methods=["POST"])
@login_required
def atualizar_match_crm(match_id):
    match = MatchPreditivo.query.get_or_404(match_id)
    match.status = request.form.get("status", match.status)
    match.notas  = request.form.get("notas", match.notas)
    db.session.commit()
    return jsonify({"ok": True, "status": match.status})


@app.route("/matches/exportar")
@login_required
def exportar_matches():
    corredor   = request.args.get("corredor", "")
    status     = request.args.get("status", "")
    prioridade = request.args.get("prioridade", "")

    query = MatchPreditivo.query
    if corredor:   query = query.filter_by(corredor=corredor)
    if status:     query = query.filter_by(status=status)
    if prioridade: query = query.filter_by(prioridade=prioridade)

    matches = query.order_by(MatchPreditivo.score_match.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow([
        "score_match", "prioridade", "corredor", "transportadora",
        "cidade_transportadora", "uf_transportadora", "embarcador",
        "cidade_embarcador", "uf_embarcador", "setor", "tipo_carga", "status", "justificativa", "notas"
    ])
    
    for m in matches:
        writer.writerow([
            m.score_match, m.prioridade, m.corredor,
            m.transportadora.razao_social or m.transportadora.nome_rntrc,
            m.cidade_origem, m.uf_origem,
            m.embarcador.razao_social or m.embarcador.nome_fantasia,
            m.cidade_destino, m.uf_destino,
            m.embarcador.setor_predito or "",
            m.embarcador.tipo_carga_provavel or "",
            m.status, m.justificativa or "", m.notas or ""
        ])

    output.seek(0)
    nome_arquivo = f"matches_{corredor.replace('→','-') or 'todos'}.csv"
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
