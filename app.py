import csv
import io
from datetime import datetime
from functools import wraps

from flask import (Flask, Response, flash, jsonify, redirect,
                   render_template, request, session, url_for)
from flask_sqlalchemy import SQLAlchemy

from config import Config
from models import ImportLog, Transportadora, EmbarcadorProvavel, MatchPreditivo, ProspeccaoLog, db
from jobs import iniciar_importacao
import sqlite3
from sqlalchemy.engine import Engine
from sqlalchemy import event

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=60000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

app = Flask(__name__)
app.config["SECRET_KEY"]        = Config.SECRET_KEY
app.config["SQLALCHEMY_DATABASE_URI"] = Config.DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "connect_args": {"timeout": 60}
}

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
    # Parâmetros de filtro
    corredor = request.args.get("corredor", "")
    status_match = request.args.get("status", "")
    prioridade = request.args.get("prioridade", "")
    temperatura = request.args.get("temperatura", "")
    periodo = request.args.get("periodo", "todos")  # hoje, 7d, 30d, todos
    min_score = request.args.get("min_score", "").strip()
    busca = request.args.get("q", "").strip()

    # Data de hoje para followups e período
    from datetime import datetime, timedelta
    hoje = datetime.utcnow()
    data_hoje_str = hoje.strftime("%Y-%m-%d")

    # Montar query de matches preditivos para calcular contagens filtradas
    query_matches = MatchPreditivo.query
    
    if corredor:
        query_matches = query_matches.filter_by(corredor=corredor)
    if status_match:
        query_matches = query_matches.filter_by(status=status_match)
    if prioridade:
        query_matches = query_matches.filter_by(prioridade=prioridade)
    if temperatura:
        query_matches = query_matches.filter_by(temperatura=temperatura)
    if min_score:
        try:
            query_matches = query_matches.filter(MatchPreditivo.score_match >= float(min_score))
        except ValueError:
            pass
    if busca:
        like = f"%{busca}%"
        # Bate em transportadora ou embarcador através de joins
        query_matches = query_matches.join(MatchPreditivo.transportadora).join(MatchPreditivo.embarcador).filter(
            db.or_(
                Transportadora.razao_social.ilike(like),
                Transportadora.cnpj.ilike(like),
                EmbarcadorProvavel.razao_social.ilike(like),
                EmbarcadorProvavel.cnpj.ilike(like)
            )
        )
        
    if periodo == "hoje":
        inicio_periodo = hoje.replace(hour=0, minute=0, second=0, microsecond=0)
        query_matches = query_matches.filter(MatchPreditivo.created_at >= inicio_periodo)
    elif periodo == "7d":
        inicio_periodo = hoje - timedelta(days=7)
        query_matches = query_matches.filter(MatchPreditivo.created_at >= inicio_periodo)
    elif periodo == "30d":
        inicio_periodo = hoje - timedelta(days=30)
        query_matches = query_matches.filter(MatchPreditivo.created_at >= inicio_periodo)

    # Contagens de Matches baseados nos filtros
    total_matches = query_matches.count()
    matches_alta = query_matches.filter_by(prioridade="Alta").count()
    matches_em_contato = query_matches.filter_by(status="Em contato").count()
    matches_negociando = query_matches.filter_by(status="Negociando").count()
    matches_fechados = query_matches.filter_by(status="Fechado").count()
    matches_perdidos = query_matches.filter_by(status="Perdido").count()

    # Contagens gerais do sistema (parcialmente afetadas pelo corredor se filtrado)
    query_transp = Transportadora.query
    query_emb = EmbarcadorProvavel.query
    if corredor:
        query_transp = query_transp.filter_by(corredor_alvo=corredor)
        query_emb = query_emb.filter_by(corredor_alvo=corredor)
        
    total_transportadoras = query_transp.count()
    total_embarcadores = query_emb.count()

    # Follow-ups (filtrados por corredor e temperatura se definidos nos matches)
    query_fu = MatchPreditivo.query.filter(MatchPreditivo.data_proxima_acao != "")
    if corredor:
        query_fu = query_fu.filter_by(corredor=corredor)
    if temperatura:
        query_fu = query_fu.filter_by(temperatura=temperatura)
        
    fu_vencidos = query_fu.filter(MatchPreditivo.data_proxima_acao < data_hoje_str).count()
    fu_hoje = query_fu.filter(MatchPreditivo.data_proxima_acao == data_hoje_str).count()

    # Taxas de conversão baseadas nos filtros dos matches
    taxa_fechamento = (matches_fechados / total_matches * 100) if total_matches > 0 else 0.0
    taxa_resposta = ((matches_em_contato + matches_negociando + matches_fechados) / total_matches * 100) if total_matches > 0 else 0.0

    # Listas rápidas do Dashboard
    # 1. Top 10 Matches por Score
    top_matches = query_matches.order_by(MatchPreditivo.score_match.desc()).limit(10).all()

    # 2. Próximos Follow-ups (hoje ou vencidos)
    lista_followups = query_fu.filter(MatchPreditivo.data_proxima_acao <= data_hoje_str).order_by(
        MatchPreditivo.data_proxima_acao.desc(),
        MatchPreditivo.score_match.desc()
    ).limit(5).all()

    # 3. Últimas Prospecções comerciais
    query_props = ProspeccaoLog.query
    if corredor:
        query_props = query_props.join(ProspeccaoLog.match).filter(MatchPreditivo.corredor == corredor)
    ultimas_prospeccoes = query_props.order_by(ProspeccaoLog.created_at.desc()).limit(5).all()

    # 4. Embarcadores recém-importados
    novos_embarcadores = query_emb.order_by(EmbarcadorProvavel.created_at.desc()).limit(5).all()

    # 5. Dados para Gráficos
    # A. Funil dos matches
    funil_dados = {
        "Sugerido": query_matches.filter_by(status="Sugerido").count(),
        "Validar": query_matches.filter_by(status="Validar").count(),
        "Abordar": query_matches.filter_by(status="Abordar").count(),
        "Em contato": matches_em_contato,
        "Negociando": matches_negociando,
        "Fechado": matches_fechados,
        "Perdido": matches_perdidos,
        "Descartado": query_matches.filter_by(status="Descartado").count()
    }
    
    # B. Matches por corredor
    matches_por_corredor = {}
    for nome in Config.CORREDORES:
        matches_por_corredor[nome] = query_matches.filter_by(corredor=nome).count()

    # C. Conversão por temperatura
    conversao_temp = {
        "Quente": query_matches.filter_by(temperatura="Quente").count(),
        "Morno": query_matches.filter_by(temperatura="Morno").count(),
        "Frio": query_matches.filter_by(temperatura="Frio").count()
    }

    # D. Prospecções por canal
    prospeccao_por_canal = {
        "WhatsApp": query_props.filter_by(canal="WhatsApp").count(),
        "Ligação": query_props.filter_by(canal="Ligação").count(),
        "E-mail": query_props.filter_by(canal="E-mail").count(),
        "Outro": query_props.filter_by(canal="Outro").count()
    }

    # Verificar se a base está 100% vazia
    base_vazia = (total_transportadoras == 0 and total_embarcadores == 0 and total_matches == 0)

    return render_template(
        "index.html",
        total_transportadoras=total_transportadoras,
        total_embarcadores=total_embarcadores,
        total_matches=total_matches,
        matches_alta=matches_alta,
        matches_em_contato=matches_em_contato,
        matches_negociando=matches_negociando,
        matches_fechados=matches_fechados,
        matches_perdidos=matches_perdidos,
        fu_vencidos=fu_vencidos,
        fu_hoje=fu_hoje,
        taxa_fechamento=taxa_fechamento,
        taxa_resposta=taxa_resposta,
        top_matches=top_matches,
        lista_followups=lista_followups,
        ultimas_prospeccoes=ultimas_prospeccoes,
        novos_embarcadores=novos_embarcadores,
        funil_dados=funil_dados,
        matches_por_corredor=matches_por_corredor,
        conversao_temp=conversao_temp,
        prospeccao_por_canal=prospeccao_por_canal,
        corredores=Config.CORREDORES,
        status_labels=Config.STATUS_LABELS,
        status_list=Config.STATUS_CRM,
        filtros=dict(
            corredor=corredor,
            status=status_match,
            prioridade=prioridade,
            temperatura=temperatura,
            periodo=periodo,
            min_score=min_score,
            q=busca
        ),
        base_vazia=base_vazia
    )


@app.route("/transportadoras")
@login_required
def transportadoras_lista():
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

    # Stats em UMA query agregada (usa corredor_alvo — fonte de verdade RNTRC)
    # enriquecidas = cnae preenchido e diferente de 'RNTRC' (enriquecidas via BrasilAPI)
    # pendentes    = total - enriquecidas (brutas RNTRC, cnae nulo ou vazio)
    stats = {nome: {"total": 0, "enriquecidas": 0, "pendentes": 0, "clientes": 0} for nome in Config.CORREDORES}
    agregados = db.session.query(
        Transportadora.corredor_alvo,
        db.func.count().label("total"),
        db.func.sum(db.case(
            (db.and_(
                Transportadora.cnae_principal.isnot(None),
                Transportadora.cnae_principal != "",
                Transportadora.cnae_principal != "RNTRC",
            ), 1), else_=0
        )).label("enriquecidas"),
        db.func.sum(db.case((Transportadora.status_crm == "cliente", 1), else_=0)).label("clientes"),
    ).group_by(Transportadora.corredor_alvo).all()
    for cor, total, enriquecidas, clientes in agregados:
        if cor in stats:
            enr = int(enriquecidas or 0)
            tot = int(total or 0)
            stats[cor] = {"total": tot,
                          "enriquecidas": enr,
                          "pendentes":    tot - enr,
                          "clientes":     int(clientes or 0)}

    ultimo_log = ImportLog.query.order_by(ImportLog.iniciado.desc()).first()
    ufs = [r[0] for r in db.session.query(Transportadora.uf).distinct().order_by(Transportadora.uf).all() if r[0]]

    # Sem filtro → não carrega lista (cards stats + prompt). Evita render de 7k linhas.
    if not tem_filtro:
        return render_template(
            "transportadoras.html",
            empresas=[], total_empresas=0, page=1, total_pages=1, page_size=PAGE_SIZE,
            stats=stats, corredores=Config.CORREDORES,
            status_labels=Config.STATUS_LABELS, status_list=Config.STATUS_CRM,
            ultimo_log=ultimo_log,
            filtros=dict(corredor="", uf="", status="", cnae_frete="", q=""),
            ufs=ufs, sem_filtro=True,
        )

    query = Transportadora.query
    if corredor: query = query.filter_by(corredor_alvo=corredor)
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
        "transportadoras.html",
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
    return redirect(url_for("transportadoras_lista"))


@app.route("/status-importacao/<int:log_id>")
@login_required
def status_importacao(log_id):
    log = ImportLog.query.get_or_404(log_id)
    is_ok = log.status != "erro"
    return jsonify({
        "ok": is_ok,
        "status": log.status,
        "progress": log.progresso,
        "message": log.mensagem,
        "total_processado": log.processado,
        "total_inserido": log.total_inserido or 0,
        "error": log.erro or "",
        "pct": log.progresso, # compatibilidade com frontend antigo
        "total": log.total,
        "processado": log.processado,
        "mensagem": log.mensagem
    })


# ─── Export CSV ──────────────────────────────────────────────────────────────

@app.route("/exportar")
@login_required
def exportar():
    corredor = request.args.get("corredor", "")
    status   = request.args.get("status", "")

    query = Transportadora.query
    if corredor:
        query = query.filter_by(corredor_alvo=corredor)
    if status:
        query = query.filter_by(status_crm=status)

    empresas = query.order_by(Transportadora.corredor_alvo, Transportadora.razao_social).all()

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
            e.corredor_alvo or e.corredor or "", e.cnpj, e.razao_social or e.nome_rntrc,
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

    # Stats para os cards (usa corredor_alvo — fonte de verdade RNTRC)
    # enriquecidas = cnae preenchido e diferente de 'RNTRC' (enriquecidas via BrasilAPI)
    # pendentes    = total - enriquecidas (brutas RNTRC, cnae nulo ou vazio)
    stats = {nome: {"total": 0, "enriquecidas": 0, "pendentes": 0, "clientes": 0} for nome in Config.CORREDORES}
    agregados = db.session.query(
        Transportadora.corredor_alvo,
        db.func.count().label("total"),
        db.func.sum(db.case(
            (db.and_(
                Transportadora.cnae_principal.isnot(None),
                Transportadora.cnae_principal != "",
                Transportadora.cnae_principal != "RNTRC",
            ), 1), else_=0
        )).label("enriquecidas"),
        db.func.sum(db.case((Transportadora.status_crm == "cliente", 1), else_=0)).label("clientes"),
    ).group_by(Transportadora.corredor_alvo).all()
    for cor, total, enriquecidas, clientes in agregados:
        if cor in stats:
            enr = int(enriquecidas or 0)
            tot = int(total or 0)
            stats[cor] = {"total": tot,
                          "enriquecidas": enr,
                          "pendentes":    tot - enr,
                          "clientes":     int(clientes or 0)}

    ultimo_log = ImportLog.query.order_by(ImportLog.iniciado.desc()).first()
    ufs = [r[0] for r in db.session.query(Transportadora.uf).distinct().order_by(Transportadora.uf).all() if r[0]]

    query = Transportadora.query
    if corredor: query = query.filter_by(corredor_alvo=corredor)
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
    import_resumo = session.pop("import_resumo", None)

    return render_template(
        "embarcadores.html",
        empresas=embarcadores, total_empresas=total_empresas,
        page=page, total_pages=total_pages, page_size=PAGE_SIZE_EMB,
        stats=stats, corredores=Config.CORREDORES,
        status_labels=Config.STATUS_LABELS, status_list=Config.STATUS_CRM,
        ultimo_log=ultimo_log,
        import_resumo=import_resumo,
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
        from radar.import_utils import (
            detectar_tipo_arquivo,
            ler_csv_com_encoding_e_sep,
            ler_xlsx,
            gerar_preview_importacao,
            detectar_duplicidades
        )
        
        tipo = detectar_tipo_arquivo(file.filename)
        file_content = file.read()
        
        if tipo == "xlsx":
            rows_brutas = ler_xlsx(file_content)
        else:
            rows_brutas = ler_csv_com_encoding_e_sep(file_content)
            
    except Exception as e:
        flash(f"Erro ao ler arquivo: {str(e)}", "danger")
        return redirect(url_for("embarcadores_lista"))

    if not rows_brutas:
        flash("O arquivo enviado está vazio ou não possui cabeçalhos reconhecidos.", "warning")
        return redirect(url_for("embarcadores_lista"))

    # Pré-validação com Pydantic
    linhas_validas, linhas_invalidas = gerar_preview_importacao(rows_brutas)

    # Obter existentes para detecção de duplicidades
    existentes_db = EmbarcadorProvavel.query.all()
    existentes = [{
        "id": emp.id,
        "cnpj": emp.cnpj,
        "razao_social": emp.razao_social,
        "nome_fantasia": emp.nome_fantasia,
        "cidade": emp.cidade,
        "uf": emp.uf,
        "corredor_alvo": emp.corredor_alvo
    } for emp in existentes_db]

    duplicidades = detectar_duplicidades(linhas_validas, existentes)

    # Salvar registros válidos
    from radar.embarcadores import avaliar_embarcador
    
    sucessos = 0
    atualizados = 0
    ignorados = 0
    
    vistos_neste_lote = {}
    
    for row in linhas_validas:
        cnpj = row.get("cnpj")
        corredor_alvo = row.get("corredor_alvo")
        
        chave_unica = (cnpj, corredor_alvo) if cnpj else None
        
        if chave_unica and chave_unica in vistos_neste_lote:
            ignorados += 1
            continue
            
        try:
            embarcador = None
            if cnpj and corredor_alvo:
                embarcador = EmbarcadorProvavel.query.filter_by(cnpj=cnpj, corredor_alvo=corredor_alvo).first()
                
            is_new = False
            if not embarcador:
                embarcador = EmbarcadorProvavel(cnpj=cnpj, corredor_alvo=corredor_alvo)
                db.session.add(embarcador)
                is_new = True
                
            embarcador.razao_social = row.get("razao_social")
            embarcador.nome_fantasia = row.get("nome_fantasia")
            embarcador.cidade = row.get("cidade")
            embarcador.uf = row.get("uf")
            embarcador.cnae = row.get("cnae")
            embarcador.cnae_descricao = row.get("cnae_descricao")
            embarcador.telefone = row.get("telefone")
            embarcador.email = row.get("email")
            embarcador.site = row.get("site")
            embarcador.origem_provavel = row.get("origem_provavel")
            embarcador.destino_provavel = row.get("destino_provavel")
            embarcador.fonte = row.get("fonte")
            embarcador.notas = row.get("notas")
            
            # Reavaliar Score Radar
            res = avaliar_embarcador(embarcador)
            embarcador.score_demanda = res["score_total"]
            embarcador.prioridade = res["prioridade"]
            embarcador.setor_predito = res["setor_predito"]
            embarcador.tipo_carga_provavel = res["tipo_carga_provavel"]
            embarcador.carrocerias_provaveis = res["carrocerias_provaveis"]
            
            if chave_unica:
                vistos_neste_lote[chave_unica] = True
                
            if is_new:
                sucessos += 1
            else:
                atualizados += 1
                
        except Exception as ex:
            db.session.rollback()
            linhas_invalidas.append({
                "linha": "Banco",
                "dados": row,
                "erros": [f"Erro ao salvar registro: {str(ex)}"]
            })

    try:
        db.session.commit()
    except Exception as commit_ex:
        db.session.rollback()
        flash(f"Erro ao salvar lote de importação: {str(commit_ex)}", "danger")
        return redirect(url_for("embarcadores_lista"))

    # Salvar resumo detalhado na session
    session["import_resumo"] = {
        "total_linhas": len(rows_brutas),
        "importadas": sucessos,
        "atualizadas": atualizados,
        "ignoradas": ignorados,
        "erros": len(linhas_invalidas),
        "duplicidades_possiveis": len(duplicidades),
        "detalhes_erros": linhas_invalidas[:20],  # Limitar para não sobrecarregar cookie de session
        "detalhes_duplicidades": duplicidades[:20]
    }

    flash(f"Importação concluída. {sucessos} adicionados, {atualizados} atualizados. Erros: {len(linhas_invalidas)}. Duplicidades: {len(duplicidades)}.", "success" if len(linhas_invalidas) == 0 else "warning")
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
    temperatura = request.args.get("temperatura", "")
    uf_origem  = request.args.get("uf_origem", "")
    uf_destino = request.args.get("uf_destino", "")
    min_score  = request.args.get("min_score", "").strip()
    fu_vencido = request.args.get("fu_vencido", "")
    busca      = request.args.get("q", "").strip()

    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1

    query = MatchPreditivo.query
    
    if busca:
        like = f"%{busca}%"
        # Bate em transportadora ou embarcador através de joins
        query = query.join(MatchPreditivo.transportadora).join(MatchPreditivo.embarcador).filter(
            db.or_(
                Transportadora.razao_social.ilike(like),
                Transportadora.cnpj.ilike(like),
                EmbarcadorProvavel.razao_social.ilike(like),
                EmbarcadorProvavel.cnpj.ilike(like)
            )
        )

    if corredor:   query = query.filter(MatchPreditivo.corredor == corredor)
    if prioridade: query = query.filter(MatchPreditivo.prioridade == prioridade)
    if status:     query = query.filter(MatchPreditivo.status == status)
    if temperatura: query = query.filter(MatchPreditivo.temperatura == temperatura)
    if uf_origem:  query = query.filter(MatchPreditivo.uf_origem == uf_origem)
    if uf_destino: query = query.filter(MatchPreditivo.uf_destino == uf_destino)
    if min_score:
        try:
            query = query.filter(MatchPreditivo.score_match >= float(min_score))
        except ValueError:
            pass
            
    if fu_vencido == "1":
        from datetime import datetime
        data_hoje_str = datetime.utcnow().strftime("%Y-%m-%d")
        query = query.filter(MatchPreditivo.data_proxima_acao != "", MatchPreditivo.data_proxima_acao <= data_hoje_str)

    # Ordenar por maior score de match decrescente
    query = query.order_by(MatchPreditivo.score_match.desc())

    PAGE_SIZE_MATCH = 50
    total_matches = query.count()
    total_pages = max(1, (total_matches + PAGE_SIZE_MATCH - 1) // PAGE_SIZE_MATCH)
    page = min(page, total_pages)
    
    matches = query.limit(PAGE_SIZE_MATCH).offset((page - 1) * PAGE_SIZE_MATCH).all()

    # Preencher dados de prospecção em memória para a listagem
    for m in matches:
        m.prospeccao_total = len(m.prospeccoes)
        if m.prospeccoes:
            ordenados = sorted(m.prospeccoes, key=lambda x: x.created_at, reverse=True)
            m.prospeccao_ultimo_status = ordenados[0].status
            m.prospeccao_ultima_data = ordenados[0].created_at.strftime("%d/%m %H:%M")
        else:
            m.prospeccao_ultimo_status = "Pendente"
            m.prospeccao_ultima_data = "—"

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
    status_list = ["Sugerido", "Validar", "Abordar", "Em contato", "Negociando", "Fechado", "Perdido", "Descartado"]
    status_labels = {
        "Sugerido":   ("Sugerido",   "secondary"),
        "Validar":    ("Validar",    "info"),
        "Abordar":    ("Abordar",    "warning"),
        "Em contato": ("Em contato", "primary"),
        "Negociando": ("Negociando", "success"),
        "Fechado":    ("Fechado",    "success"),
        "Perdido":    ("Perdido",    "danger"),
        "Descartado": ("Descartado", "danger")
    }

    return render_template(
        "matches.html",
        matches=matches, total_empresas=total_matches,
        total_matches=total_matches,
        page=page, total_pages=total_pages, page_size=PAGE_SIZE_MATCH,
        stats=stats, corredores=Config.CORREDORES,
        status_labels=status_labels, status_list=status_list,
        filtros=dict(
            corredor=corredor,
            prioridade=prioridade,
            status=status,
            temperatura=temperatura,
            uf_origem=uf_origem,
            uf_destino=uf_destino,
            min_score=min_score,
            fu_vencido=fu_vencido,
            q=busca
        ),
        ufs_origem=ufs_origem, ufs_destino=ufs_destino
    )


@app.route("/matches/gerar", methods=["POST"])
@login_required
def gerar_matches():
    from radar.matching import gerar_matches_preditivos
    
    corredor = request.form.get("corredor") or request.args.get("corredor")
    prioridade = request.form.get("prioridade") or request.args.get("prioridade") or request.form.get("prioridade_minima") or request.args.get("prioridade_minima")
    
    if not corredor and request.referrer:
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(request.referrer)
        queries = parse_qs(parsed.query)
        if "corredor" in queries and queries["corredor"]:
            corredor = queries["corredor"][0]
        if "prioridade" in queries and queries["prioridade"]:
            prioridade = queries["prioridade"][0]

    if not corredor:
        flash("Por favor, selecione um corredor no filtro antes de gerar os matches preditivos.", "warning")
        return redirect(url_for("matches_lista"))
        
    try:
        limite = 5000
        res = gerar_matches_preditivos(
            db.session,
            corredor=corredor,
            prioridade_minima=prioridade,
            limite_matches=limite,
            preferir_transportadoras_puras=True
        )
        criados = res.get("total_matches", 0)
        flash(f"Geração de matches concluída com sucesso para o corredor {corredor}. {criados} matches processados.", "success")
    except Exception as ex:
        flash(f"Erro ao gerar matches: {ex}", "danger")
        print(f"Erro ao gerar matches preditivos: {ex}")
    return redirect(url_for("matches_lista", corredor=corredor, prioridade=prioridade))


@app.route("/matches/<int:match_id>/crm", methods=["POST"])
@login_required
def atualizar_match_crm(match_id):
    match = MatchPreditivo.query.get_or_404(match_id)
    status_antigo = match.status
    
    match.status = request.form.get("status", match.status)
    match.notas  = request.form.get("notes", request.form.get("notas", match.notas))
    
    # Atualizar campos de Cadência Comercial se fornecidos
    match.temperatura = request.form.get("temperatura", match.temperatura)
    match.proxima_acao = request.form.get("proxima_acao", match.proxima_acao)
    match.data_proxima_acao = request.form.get("data_proxima_acao", match.data_proxima_acao)
    
    db.session.commit()
    
    # Registrar auditoria se houver alteração de status
    if status_antigo != match.status:
        from radar.prospeccao import registrar_evento_sistema
        registrar_evento_sistema(db.session, match, status_antigo, match.status, "Alteracao de status via formulario CRM")
        
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
        "cidade_embarcador", "uf_embarcador", "setor", "tipo_carga", "status", "justificativa", "notas",
        "prospeccao_total", "prospeccao_ultimo_status", "prospeccao_ultima_data"
    ])
    
    for m in matches:
        total_p = len(m.prospeccoes)
        ultimo_status_p = "Pendente"
        ultima_data_p = "—"
        if m.prospeccoes:
            ordenados = sorted(m.prospeccoes, key=lambda x: x.created_at, reverse=True)
            ultimo_status_p = ordenados[0].status
            ultima_data_p = ordenados[0].created_at.strftime("%d/%m/%Y %H:%M")

        writer.writerow([
            m.score_match, m.prioridade, m.corredor,
            m.transportadora.razao_social or m.transportadora.nome_rntrc,
            m.cidade_origem, m.uf_origem,
            m.embarcador.razao_social or m.embarcador.nome_fantasia,
            m.cidade_destino, m.uf_destino,
            m.embarcador.setor_predito or "",
            m.embarcador.tipo_carga_provavel or "",
            m.status, m.justificativa or "", m.notas or "",
            total_p, ultimo_status_p, ultima_data_p
        ])

    output.seek(0)
    nome_arquivo = f"matches_{corredor.replace('→','-') or 'todos'}.csv"
    return Response(
        output.getvalue().encode("utf-8-sig"),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={nome_arquivo}"},
    )



# ─── Prospecção Assistida ────────────────────────────────────────────────────

@app.route("/matches/<int:match_id>/prospeccao")
@login_required
def prospeccao_match(match_id):
    match = MatchPreditivo.query.get_or_404(match_id)
    from radar.prospeccao import (gerar_mensagem_embarcador, 
                                  gerar_mensagem_transportadora, 
                                  gerar_assunto_email, 
                                  montar_link_whatsapp)
    msg_emb = gerar_mensagem_embarcador(match)
    msg_transp = gerar_mensagem_transportadora(match)
    assunto = gerar_assunto_email(match)
    
    contato_emb = match.embarcador.telefone or ""
    email_emb = match.embarcador.email or ""
    contato_transp = match.transportadora.telefone or ""
    email_transp = match.transportadora.email or ""
    
    link_wa_emb = montar_link_whatsapp(contato_emb, msg_emb)
    link_wa_transp = montar_link_whatsapp(contato_transp, msg_transp)
    
    logs = [
        {
            "id": l.id,
            "canal": l.canal,
            "destinatario_tipo": l.destinatario_tipo,
            "destinatario_nome": l.destinatario_nome,
            "destinatario_contato": l.destinatario_contato,
            "status": l.status,
            "observacao": l.observacao,
            "data": l.created_at.strftime("%d/%m/%Y %H:%M")
        } for l in match.prospeccoes
    ]
    
    return jsonify({
        "ok": True,
        "msg_emb": msg_emb,
        "msg_transp": msg_transp,
        "assunto": assunto,
        "link_wa_emb": link_wa_emb,
        "link_wa_transp": link_wa_transp,
        "contato_emb": contato_emb,
        "email_emb": email_emb,
        "contato_transp": contato_transp,
        "email_transp": email_transp,
        "logs": logs,
        "temperatura": match.temperatura or "Frio",
        "proxima_acao": match.proxima_acao or "",
        "data_proxima_acao": match.data_proxima_acao or "",
        "resultado_ultimo": match.resultado_ultimo or ""
    })


@app.route("/matches/<int:match_id>/prospeccao/log", methods=["POST"])
@login_required
def criar_prospeccao_log(match_id):
    match = MatchPreditivo.query.get_or_404(match_id)
    
    log = ProspeccaoLog(
        match_id=match.id,
        canal=request.form.get("canal", "WhatsApp").strip(),
        destinatario_tipo=request.form.get("destinatario_tipo", "Embarcador").strip(),
        destinatario_nome=request.form.get("destinatario_nome", "").strip(),
        destinatario_contato=request.form.get("destinatario_contato", "").strip(),
        mensagem=request.form.get("mensagem", "").strip(),
        status=request.form.get("status", "Gerada").strip(),
        observacao=request.form.get("observacao", "").strip(),
        
        # Campos de Cadência
        resultado=request.form.get("resultado", "").strip(),
        temperatura=request.form.get("temperatura", "Frio").strip(),
        proxima_acao=request.form.get("proxima_acao", "").strip(),
        data_proxima_acao=request.form.get("data_proxima_acao", "").strip(),
        responsavel=request.form.get("responsavel", "Comercial").strip()
    )
    db.session.add(log)
    
    # Sincronizar dados mais recentes no Match Comercial Preditivo
    if log.temperatura:
        match.temperatura = log.temperatura
    if log.proxima_acao:
        match.proxima_acao = log.proxima_acao
    if log.data_proxima_acao:
        match.data_proxima_acao = log.data_proxima_acao
    if log.resultado:
        match.resultado_ultimo = log.resultado
        
    db.session.commit()
    return jsonify({"ok": True, "log_id": log.id})


@app.route("/prospeccao")
@login_required
def prospeccao_historico():
    canal = request.args.get("canal", "")
    status = request.args.get("status", "")
    corredor = request.args.get("corredor", "")
    dest_tipo = request.args.get("dest_tipo", "")
    
    query = ProspeccaoLog.query.join(MatchPreditivo)
    
    if canal: query = query.filter(ProspeccaoLog.canal == canal)
    if status: query = query.filter(ProspeccaoLog.status == status)
    if dest_tipo: query = query.filter(ProspeccaoLog.destinatario_tipo == dest_tipo)
    if corredor: query = query.filter(MatchPreditivo.corredor == corredor)
    
    query = query.order_by(ProspeccaoLog.created_at.desc())
    logs = query.limit(100).all()
    
    status_list = ["Gerada", "Copiada", "Enviada manualmente", "Respondida", "Sem resposta", "Descartada"]
    canal_list = ["WhatsApp", "E-mail", "Ligação", "Outro"]
    
    return render_template(
        "prospeccao.html",
        logs=logs,
        status_list=status_list,
        canal_list=canal_list,
        corredores=Config.CORREDORES,
        filtros=dict(canal=canal, status=status, corredor=corredor, dest_tipo=dest_tipo)
    )



# ─── Cadência Comercial e Métricas ───────────────────────────────────────────

@app.route("/metricas")
@login_required
def metricas_comerciais():
    from radar.metricas import (
        calcular_metricas_funil,
        calcular_metricas_por_corredor,
        calcular_metricas_por_setor,
        calcular_metricas_por_canal
    )
    
    stats_funil = calcular_metricas_funil()
    por_corredor = calcular_metricas_por_corredor()
    por_setor = calcular_metricas_por_setor()
    por_canal = calcular_metricas_por_canal()
    
    from datetime import date
    hoje = date.today().isoformat()
    
    # Trazer follow-ups não resolvidos (onde data_proxima_acao é preenchida e status do match não é Fechado ou Descartado)
    followups = MatchPreditivo.query.filter(
        MatchPreditivo.data_proxima_acao.isnot(None),
        MatchPreditivo.data_proxima_acao != "",
        ~MatchPreditivo.status.in_(["Fechado", "Descartado"])
    ).order_by(MatchPreditivo.data_proxima_acao.asc()).limit(30).all()
    
    # Cobertura de Contatos
    total_matches = MatchPreditivo.query.count()
    if total_matches > 0:
        matches_t_contato = MatchPreditivo.query.join(MatchPreditivo.transportadora).filter(
            db.or_(
                db.and_(Transportadora.telefone != None, Transportadora.telefone != ""),
                db.and_(Transportadora.email != None, Transportadora.email != ""),
                db.and_(Transportadora.socios != None, Transportadora.socios != "")
            )
        ).count()
        
        matches_e_contato = MatchPreditivo.query.join(MatchPreditivo.embarcador).filter(
            db.or_(
                db.and_(EmbarcadorProvavel.telefone != None, EmbarcadorProvavel.telefone != ""),
                db.and_(EmbarcadorProvavel.email != None, EmbarcadorProvavel.email != ""),
                db.and_(EmbarcadorProvavel.site != None, EmbarcadorProvavel.site != "")
            )
        ).count()
        
        matches_completo = MatchPreditivo.query.join(MatchPreditivo.transportadora).join(MatchPreditivo.embarcador).filter(
            db.or_(
                db.and_(Transportadora.telefone != None, Transportadora.telefone != ""),
                db.and_(Transportadora.email != None, Transportadora.email != ""),
                db.and_(Transportadora.socios != None, Transportadora.socios != "")
            ),
            db.or_(
                db.and_(EmbarcadorProvavel.telefone != None, EmbarcadorProvavel.telefone != ""),
                db.and_(EmbarcadorProvavel.email != None, EmbarcadorProvavel.email != ""),
                db.and_(EmbarcadorProvavel.site != None, EmbarcadorProvavel.site != "")
            )
        ).count()
        
        matches_sem_contato = total_matches - (matches_t_contato + matches_e_contato - matches_completo)
        
        pct_t = round((matches_t_contato / total_matches) * 100, 1)
        pct_e = round((matches_e_contato / total_matches) * 100, 1)
        pct_c = round((matches_completo / total_matches) * 100, 1)
        pct_s = round((matches_sem_contato / total_matches) * 100, 1)
    else:
        matches_t_contato = matches_e_contato = matches_completo = matches_sem_contato = 0
        pct_t = pct_e = pct_c = pct_s = 0.0
        
    cobertura_contatos = {
        "total": total_matches,
        "t_contato": matches_t_contato,
        "e_contato": matches_e_contato,
        "completo": matches_completo,
        "sem_contato": matches_sem_contato,
        "pct_t": pct_t,
        "pct_e": pct_e,
        "pct_c": pct_c,
        "pct_s": pct_s
    }

    # Completude de Dados (Eficiente)
    t_avg_score = db.session.query(db.func.avg(Transportadora.score_completude)).scalar() or 0.0
    e_avg_score = db.session.query(db.func.avg(EmbarcadorProvavel.score_completude)).scalar() or 0.0
    
    t_sem_email = Transportadora.query.filter(db.or_(Transportadora.email == None, Transportadora.email == "")).count()
    e_sem_email = EmbarcadorProvavel.query.filter(db.or_(EmbarcadorProvavel.email == None, EmbarcadorProvavel.email == "")).count()
    total_sem_email = t_sem_email + e_sem_email
    
    total_sem_site = EmbarcadorProvavel.query.filter(db.or_(EmbarcadorProvavel.site == None, EmbarcadorProvavel.site == "")).count()
    
    t_com_tel = Transportadora.query.filter(Transportadora.telefone != None, Transportadora.telefone != "").count()
    e_com_tel = EmbarcadorProvavel.query.filter(EmbarcadorProvavel.telefone != None, EmbarcadorProvavel.telefone != "").count()
    total_com_tel = t_com_tel + e_com_tel
    
    t_com_soc = Transportadora.query.filter(Transportadora.socios != None, Transportadora.socios != "").count()
    e_com_soc = EmbarcadorProvavel.query.filter(EmbarcadorProvavel.socios != None, EmbarcadorProvavel.socios != "").count()
    total_com_soc = t_com_soc + e_com_soc
    
    matches_100 = MatchPreditivo.query.join(MatchPreditivo.transportadora).join(MatchPreditivo.embarcador).filter(
        Transportadora.score_completude == 100,
        EmbarcadorProvavel.score_completude == 100
    ).count()
    
    completude_dados = {
        "t_avg": round(t_avg_score, 1),
        "e_avg": round(e_avg_score, 1),
        "acionaveis": matches_completo,
        "dados_completos": matches_100,
        "sem_email": total_sem_email,
        "sem_site": total_sem_site,
        "com_telefone": total_com_tel,
        "com_socios": total_com_soc
    }

    # Calcular métricas geográficas (Validação Geográfica)
    matches_geo = MatchPreditivo.query.all()
    total_geo = len(matches_geo)
    
    com_score = 0
    sem_score = 0
    
    faixas = {
        "mesmo_municipio": 0,
        "ate_30": 0,
        "ate_150": 0,
        "acima_150": 0,
        "insuficiente": 0
    }
    
    confiabilidade = {
        "alta": 0,
        "media": 0,
        "baixa": 0,
        "insuficiente": 0
    }
    
    corredor_dists = {}
    
    for m in matches_geo:
        t = m.transportadora
        e = m.embarcador
        
        if m.score_geografico is not None:
            com_score += 1
            
            # Faixas
            if m.distancia_km == 0 and m.precisao_geografica_match == 'cidade':
                faixas["mesmo_municipio"] += 1
            elif m.distancia_km <= 30:
                faixas["ate_30"] += 1
            elif m.distancia_km <= 150:
                faixas["ate_150"] += 1
            else:
                faixas["acima_150"] += 1
                
            # Confiabilidade
            t_prec = t.precisao_geocodificacao or "cidade" if t else "cidade"
            e_prec = e.precisao_geocodificacao or "cidade" if e else "cidade"
            
            if t_prec in ("endereco", "cep") and e_prec in ("endereco", "cep"):
                confiabilidade["alta"] += 1
            elif (t_prec in ("endereco", "cep") and e_prec == "cidade") or (e_prec in ("endereco", "cep") and t_prec == "cidade"):
                confiabilidade["media"] += 1
            else:
                confiabilidade["baixa"] += 1
                
            # Corredor
            corr = m.corredor or "Indefinido"
            if corr not in corredor_dists:
                corredor_dists[corr] = []
            corredor_dists[corr].append(m.distancia_km)
        else:
            sem_score += 1
            faixas["insuficiente"] += 1
            confiabilidade["insuficiente"] += 1
            
    # Distância média por corredor
    dist_media_corredor = {}
    for corr, dists in corredor_dists.items():
        if dists:
            dist_media_corredor[corr] = round(sum(dists)/len(dists), 1)
        else:
            dist_media_corredor[corr] = 0.0
            
    geografia = {
        "com_score": com_score,
        "sem_score": sem_score,
        "pct_com_score": round((com_score / total_geo) * 100, 1) if total_geo > 0 else 0.0,
        "pct_sem_score": round((sem_score / total_geo) * 100, 1) if total_geo > 0 else 0.0,
        "faixas": faixas,
        "pct_faixas": {k: round((v / total_geo) * 100, 1) if total_geo > 0 else 0.0 for k, v in faixas.items()},
        "confiabilidade": confiabilidade,
        "pct_confiabilidade": {k: round((v / total_geo) * 100, 1) if total_geo > 0 else 0.0 for k, v in confiabilidade.items()},
        "dist_media_corredor": dist_media_corredor
    }

    return render_template(
        "metricas.html",
        stats=stats_funil,
        por_corredor=por_corredor,
        por_setor=por_setor,
        por_canal=por_canal,
        followups=followups,
        hoje=hoje,
        corredores=Config.CORREDORES,
        cobertura_contatos=cobertura_contatos,
        completude_dados=completude_dados,
        geografia=geografia
    )


@app.route("/followups")
@login_required
def followups_lista():
    tempo      = request.args.get("tempo", "") # vencidos, hoje, 7dias, todos
    corredor   = request.args.get("corredor", "")
    temperatura = request.args.get("temperatura", "")
    
    from datetime import date, timedelta
    hoje = date.today().isoformat()
    sete_dias = (date.today() + timedelta(days=7)).isoformat()
    
    query = MatchPreditivo.query.filter(
        MatchPreditivo.data_proxima_acao.isnot(None),
        MatchPreditivo.data_proxima_acao != ""
    )
    
    if tempo == "vencidos":
        query = query.filter(MatchPreditivo.data_proxima_acao < hoje, ~MatchPreditivo.status.in_(["Fechado", "Descartado"]))
    elif tempo == "hoje":
        query = query.filter(MatchPreditivo.data_proxima_acao == hoje)
    elif tempo == "7dias":
        query = query.filter(MatchPreditivo.data_proxima_acao >= hoje, MatchPreditivo.data_proxima_acao <= sete_dias)
    
    if corredor:
        query = query.filter(MatchPreditivo.corredor == corredor)
    if temperatura:
        query = query.filter(MatchPreditivo.temperatura == temperatura)
        
    followups = query.order_by(MatchPreditivo.data_proxima_acao.asc()).all()
    
    return render_template(
        "followups.html",
        followups=followups,
        hoje=hoje,
        corredores=Config.CORREDORES,
        filtros=dict(tempo=tempo, corredor=corredor, temperatura=temperatura)
    )


@app.route("/metricas/exportar")
@login_required
def exportar_metricas():
    from radar.metricas import calcular_metricas_por_corredor
    corredores_met = calcular_metricas_por_corredor()
    
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow([
        "corredor", "matches", "prospeccoes", "respostas", "negociacoes", "fechados", "taxa_resposta", "taxa_fechamento"
    ])
    
    for c in corredores_met:
        writer.writerow([
            c["corredor"], c["matches"], c["prospeccoes"], c["respostas"],
            c["negociacoes"], c["fechados"], c["taxa_resposta"], c["taxa_fechamento"]
        ])
        
    output.seek(0)
    return Response(
        output.getvalue().encode("utf-8-sig"),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=metricas_conversao.csv"},
    )


@app.route("/followups/exportar")
@login_required
def exportar_followups():
    query = MatchPreditivo.query.filter(
        MatchPreditivo.data_proxima_acao.isnot(None),
        MatchPreditivo.data_proxima_acao != ""
    )
    followups = query.order_by(MatchPreditivo.data_proxima_acao.asc()).all()
    
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow([
        "data_proxima_acao", "corredor", "embarcador", "transportadora", "canal", "status", "resultado", "temperatura", "observacao"
    ])
    
    for f in followups:
        canal = "WhatsApp"
        ultimo_log = ProspeccaoLog.query.filter_by(match_id=f.id).order_by(ProspeccaoLog.created_at.desc()).first()
        if ultimo_log:
            canal = ultimo_log.canal
            
        writer.writerow([
            f.data_proxima_acao, f.corredor,
            f.embarcador.razao_social or f.embarcador.nome_fantasia,
            f.transportadora.razao_social or f.transportadora.nome_rntrc,
            canal, f.status, f.resultado_ultimo or "", f.temperatura, f.notas or ""
        ])
        
    output.seek(0)
    return Response(
        output.getvalue().encode("utf-8-sig"),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=followups.csv"},
    )



# ─── Kanban Comercial de Matches ─────────────────────────────────────────────

@app.route("/kanban")
@login_required
def kanban_quadro():
    corredor      = request.args.get("corredor", "")
    prioridade    = request.args.get("prioridade", "")
    temperatura   = request.args.get("temperatura", "")
    status_filtro = request.args.get("status", "")
    min_score     = request.args.get("min_score", "").strip()
    busca         = request.args.get("q", "").strip()
    vencido_filtro = request.args.get("vencido", "")
    
    from datetime import date
    hoje = date.today().isoformat()
    
    query = MatchPreditivo.query
    
    if corredor:   query = query.filter_by(corredor=corredor)
    if prioridade: query = query.filter_by(prioridade=prioridade)
    if temperatura: query = query.filter_by(temperatura=temperatura)
    if status_filtro: query = query.filter_by(status=status_filtro)
    if min_score:
        try:
            query = query.filter(MatchPreditivo.score_match >= float(min_score))
        except ValueError:
            pass
            
    if vencido_filtro == "1":
        query = query.filter(
            MatchPreditivo.data_proxima_acao < hoje,
            MatchPreditivo.data_proxima_acao.isnot(None),
            MatchPreditivo.data_proxima_acao != "",
            ~MatchPreditivo.status.in_(["Fechado", "Descartado", "Perdido"])
        )
        
    if busca:
        like = f"%{busca}%"
        from models import Transportadora, EmbarcadorProvavel
        query = query.join(Transportadora).join(EmbarcadorProvavel).filter(
            db.or_(
                Transportadora.razao_social.ilike(like),
                Transportadora.nome_rntrc.ilike(like),
                EmbarcadorProvavel.razao_social.ilike(like),
                EmbarcadorProvavel.nome_fantasia.ilike(like)
            )
        )
        
    matches_all = query.order_by(MatchPreditivo.score_match.desc()).all()
    
    colunas_nomes = ["Sugerido", "Validar", "Abordar", "Em contato", "Negociando", "Fechado", "Perdido", "Descartado"]
    quadro = {c: [] for c in colunas_nomes}
    
    total_sugeridos = 0
    for m in matches_all:
        status_c = m.status if m.status in quadro else "Sugerido"
        if status_c == "Sugerido":
            total_sugeridos += 1
            if len(quadro["Sugerido"]) < 100:
                quadro["Sugerido"].append(m)
        else:
            quadro[status_c].append(m)
            
    from radar.prospeccao import (gerar_mensagem_embarcador, 
                                  gerar_mensagem_transportadora, 
                                  gerar_assunto_email, 
                                  montar_link_whatsapp)
    
    for status_c, cards in quadro.items():
        for m in cards:
            m.prospeccao_total = len(m.prospeccoes)
            if m.prospeccoes:
                ordenados = sorted(m.prospeccoes, key=lambda x: x.created_at, reverse=True)
                m.prospeccao_ultimo_status = ordenados[0].status
                m.prospeccao_ultima_data = ordenados[0].created_at.strftime("%d/%m %H:%M")
            else:
                m.prospeccao_ultimo_status = "Pendente"
                m.prospeccao_ultima_data = "—"
                
            # Links e mensagens rápidas
            msg_emb = gerar_mensagem_embarcador(m)
            msg_transp = gerar_mensagem_transportadora(m)
            
            m.link_wa_emb = montar_link_whatsapp(m.embarcador.telefone, msg_emb)
            m.link_wa_transp = montar_link_whatsapp(m.transportadora.telefone, msg_transp)
            
            m.assunto_email = gerar_assunto_email(m)
            m.corpo_email_emb = msg_emb
            m.corpo_email_transp = msg_transp
            
    matches_exist = any(len(cards) > 0 for cards in quadro.values())
        
    stats = {
        "total": MatchPreditivo.query.count(),
        "alta": MatchPreditivo.query.filter_by(prioridade="Alta").count(),
        "em_contato": MatchPreditivo.query.filter_by(status="Em contato").count(),
        "negociando": MatchPreditivo.query.filter_by(status="Negociando").count(),
        "fechados": MatchPreditivo.query.filter_by(status="Fechado").count(),
        "perdidos": MatchPreditivo.query.filter_by(status="Perdido").count(),
        "vencidos": MatchPreditivo.query.filter(
            MatchPreditivo.data_proxima_acao < hoje,
            MatchPreditivo.data_proxima_acao.isnot(None),
            MatchPreditivo.data_proxima_acao != "",
            ~MatchPreditivo.status.in_(["Fechado", "Descartado", "Perdido"])
        ).count(),
        "hoje": MatchPreditivo.query.filter_by(data_proxima_acao=hoje).count()
    }
    
    status_labels = {
        "Sugerido":   ("Sugerido",   "secondary"),
        "Validar":    ("Validar",    "info"),
        "Abordar":    ("Abordar",    "warning"),
        "Em contato": ("Em contato", "primary"),
        "Negociando": ("Negociando", "success"),
        "Fechado":    ("Fechado",    "success"),
        "Perdido":    ("Perdido",    "danger"),
        "Descartado": ("Descartado", "danger")
    }
    
    return render_template(
        "kanban.html",
        quadro=quadro,
        stats=stats,
        corredores=Config.CORREDORES,
        status_labels=status_labels,
        filtros=dict(corredor=corredor, prioridade=prioridade, temperatura=temperatura, status=status_filtro, min_score=min_score, q=busca, vencido=vencido_filtro),
        hoje=hoje,
        matches_exist=matches_exist,
        total_sugeridos=total_sugeridos
    )


@app.route("/kanban/match/<int:match_id>/status", methods=["POST"])
@login_required
def atualizar_kanban_status(match_id):
    match = MatchPreditivo.query.get_or_404(match_id)
    status_antigo = match.status
    
    if request.is_json:
        data = request.json
    else:
        data = request.form
        
    novo_status = data.get("status")
    if not novo_status:
        return jsonify({"ok": False, "error": "Status nao informado"}), 400
        
    valid_status = ["Sugerido", "Validar", "Abordar", "Em contato", "Negociando", "Fechado", "Perdido", "Descartado"]
    if novo_status not in valid_status:
        return jsonify({"ok": False, "error": f"Status '{novo_status}' invalido"}), 400
        
    try:
        match.status = novo_status
        
        if "temperatura" in data:
            match.temperatura = data["temperatura"]
        if "resultado_ultimo" in data:
            match.resultado_ultimo = data["resultado_ultimo"]
        if "proxima_acao" in data:
            match.proxima_acao = data["proxima_acao"]
        if "data_proxima_acao" in data:
            match.data_proxima_acao = data["data_proxima_acao"]
            
        db.session.commit()
        
        # Registrar auditoria se houver alteração de status
        if status_antigo != novo_status:
            from radar.prospeccao import registrar_evento_sistema
            registrar_evento_sistema(db.session, match, status_antigo, novo_status)
            
        return jsonify({"ok": True, "match_id": match.id, "status": match.status})
    except Exception as ex:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(ex)}), 500


@app.route("/kanban/exportar")
@login_required
def exportar_kanban():
    corredor      = request.args.get("corredor", "")
    prioridade    = request.args.get("prioridade", "")
    temperatura   = request.args.get("temperatura", "")
    status_filtro = request.args.get("status", "")
    
    query = MatchPreditivo.query
    if corredor:   query = query.filter_by(corredor=corredor)
    if prioridade: query = query.filter_by(prioridade=prioridade)
    if temperatura: query = query.filter_by(temperatura=temperatura)
    if status_filtro: query = query.filter_by(status=status_filtro)
    
    matches = query.order_by(MatchPreditivo.score_match.desc()).all()
    
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow([
        "status", "score_match", "prioridade", "corredor", "transportadora", "embarcador",
        "cidade_embarcador", "uf_embarcador", "tipo_carga", "temperatura", "proxima_acao",
        "data_proxima_acao", "resultado_ultimo", "notas",
        "prospeccao_total", "prospeccao_ultima_acao", "prospeccao_ultimo_status", "prospeccao_ultima_data"
    ])
    
    for m in matches:
        total_p = len(m.prospeccoes)
        ultima_acao_p = "—"
        ultimo_status_p = "Pendente"
        ultima_data_p = "—"
        if m.prospeccoes:
            ordenados = sorted(m.prospeccoes, key=lambda x: x.created_at, reverse=True)
            ultima_acao_p = ordenados[0].mensagem or "—"
            ultimo_status_p = ordenados[0].status or "Pendente"
            ultima_data_p = ordenados[0].created_at.strftime("%d/%m/%Y %H:%M")

        writer.writerow([
            m.status, m.score_match, m.prioridade, m.corredor,
            m.transportadora.razao_social or m.transportadora.nome_rntrc,
            m.embarcador.razao_social or m.embarcador.nome_fantasia,
            m.cidade_destino, m.uf_destino,
            m.embarcador.tipo_carga_provavel or "",
            m.temperatura, m.proxima_acao or "", m.data_proxima_acao or "",
            m.resultado_ultimo or "", m.notas or "",
            total_p, ultima_acao_p, ultimo_status_p, ultima_data_p
        ])
        
    output.seek(0)
    return Response(
        output.getvalue().encode("utf-8-sig"),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=kanban_matches.csv"},
    )


@app.route("/kanban/match/<int:match_id>/contato-rapido", methods=["POST"])
@login_required
def kanban_contato_rapido(match_id):
    match = MatchPreditivo.query.get_or_404(match_id)
    
    canal = request.form.get("canal", "WhatsApp").strip()
    dest_tipo = request.form.get("destinatario_tipo", "Embarcador").strip()
    contato = request.form.get("contato", "").strip()
    mensagem = request.form.get("mensagem", "").strip()
    
    emb_nome = match.embarcador.razao_social or match.embarcador.nome_fantasia or "Embarcador"
    transp_nome = match.transportadora.razao_social or match.transportadora.nome_rntrc or "Transportadora"
    dest_nome = emb_nome if dest_tipo == "Embarcador" else transp_nome
    
    log = ProspeccaoLog(
        match_id=match.id,
        canal=canal,
        destinatario_tipo=dest_tipo,
        destinatario_nome=dest_nome[:150],
        destinatario_contato=contato,
        mensagem=mensagem,
        status="Copiada",
        observacao="Contato rapido iniciado pelo Kanban",
        resultado="Respondeu" if match.status == "Em contato" else match.resultado_ultimo,
        temperatura=match.temperatura,
        proxima_acao=match.proxima_acao,
        data_proxima_acao=match.data_proxima_acao,
        responsavel="Comercial"
    )
    
    db.session.add(log)
    db.session.commit()
    return jsonify({"ok": True, "log_id": log.id})


# ─── Health check ─────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({"status": "ok", "ts": datetime.utcnow().isoformat()})


if __name__ == "__main__":
    app.run(debug=True)
