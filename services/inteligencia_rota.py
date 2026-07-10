"""
Inteligência de Rota — acesso read-only a rota_core / rota_views
(banco PostgreSQL/PostGIS caminhao_vazio).

NÃO é o app FastAPI separado: módulo do WiNS Hub Log.
"""
from __future__ import annotations

import os
import time
import logging
from decimal import Decimal
from datetime import date, datetime
from typing import Any, Optional
import math

import psycopg


CONNECT_TIMEOUT_SECONDS = int(os.environ.get("ROTA_CONNECT_TIMEOUT_SECONDS", "2"))
STATEMENT_TIMEOUT_MS = int(os.environ.get("ROTA_STATEMENT_TIMEOUT_MS", "1500"))
STATS_STATEMENT_TIMEOUT_MS = int(os.environ.get("ROTA_STATS_STATEMENT_TIMEOUT_MS", "250"))
QUERY_CACHE_TTL_SECONDS = int(os.environ.get("ROTA_QUERY_CACHE_TTL_SECONDS", "600"))
_QUERY_CACHE: dict[tuple[str, tuple[Any, ...]], tuple[float, dict[str, Any]]] = {}

# Global max values for score normalization (cached 10 min)
_GLOBAL_MAX: Optional[dict[str, float]] = None
_GLOBAL_MAX_TS: float = 0.0
_GLOBAL_MAX_TTL = 600

_log = logging.getLogger("inteligencia_rota")

# Stale-if-error: ultimo resultado valido de get_inteligencia_stats()
_last_valid_stats: Optional[dict[str, Any]] = None
_last_valid_stats_ts: float = 0.0
_STALE_MAX_AGE = 3600  # 1 hora maximo para usar stale

# Campos obrigatorios para validar stats
_STATS_REQUIRED_FIELDS = [
    "total_postos",
    "total_pontos_apoio",
    "total_transportadores",
    "total_cnpj_logisticos",
    "total_municipios_score",
]

# Eventos de log
_LOG_CACHE_HIT = 0
_LOG_CACHE_MISS = 1
_LOG_REFRESH_OK = 2
_LOG_REFRESH_ERROR = 3
_LOG_STALE_USED = 4
_LOG_INVALID_SKIP = 5

_EVENT_LABELS = {
    _LOG_CACHE_HIT: "cache_hit",
    _LOG_CACHE_MISS: "cache_miss",
    _LOG_REFRESH_OK: "stats_refresh_success",
    _LOG_REFRESH_ERROR: "stats_refresh_error",
    _LOG_STALE_USED: "stale_value_used",
    _LOG_INVALID_SKIP: "invalid_payload_not_cached",
}


def _log_cache_event(event: int, extra: str = "") -> None:
    label = _EVENT_LABELS.get(event, "unknown")
    msg = f"[cache_stats] {label}"
    if extra:
        msg += f" | {extra}"
    _log.info(msg)


def _is_valid_inteligencia_stats(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("status") == "error":
        return False
    for field in _STATS_REQUIRED_FIELDS:
        val = payload.get(field)
        if val is None:
            return False
    return True


def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


def rota_configured() -> bool:
    return bool(_env("ROTA_DB_NAME") and _env("ROTA_DB_USER"))


def get_conn():
    """Conexão ao Postgres de inteligência (schemas rota*).

    Se ROTA_DB_PASSWORD estiver vazio, usa socket Unix (/var/run/postgresql)
    com peer auth local (padrão do Postgres da VPS para user william).
    """
    dbname = _env("ROTA_DB_NAME", "caminhao_vazio")
    user = _env("ROTA_DB_USER")
    password = _env("ROTA_DB_PASSWORD")
    host = _env("ROTA_DB_HOST", "127.0.0.1")
    port = int(_env("ROTA_DB_PORT", "5432") or "5432")
    if password:
        return psycopg.connect(
            host=host or "127.0.0.1",
            port=port,
            dbname=dbname,
            user=user,
            password=password,
            connect_timeout=CONNECT_TIMEOUT_SECONDS,
        )
    # peer auth local — sem senha
    return psycopg.connect(
        host="/var/run/postgresql",
        dbname=dbname,
        user=user,
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
    )


def _sanitize_limit(limit: Optional[int], default: int = 100, max_limit: int = 1000) -> int:
    try:
        n = int(limit) if limit is not None else default
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, max_limit))


def _get_global_max(cur) -> dict[str, float]:
    """Retorna os valores máximos de cada componente para normalização do score.
    Cache de 10 minutos para evitar consulta repetida.
    """
    global _GLOBAL_MAX, _GLOBAL_MAX_TS
    now = time.time()
    if _GLOBAL_MAX is not None and (now - _GLOBAL_MAX_TS) < _GLOBAL_MAX_TTL:
        return _GLOBAL_MAX
    try:
        cur.execute("""
            SELECT
                COALESCE(MAX(transportadores_qtd), 0),
                COALESCE(MAX(cnpjs_logisticos_qtd), 0),
                COALESCE(MAX(pontos_apoio_qtd), 0),
                COALESCE(MAX(comex_fluxos_qtd), 0),
                COALESCE(MAX(postos_qtd), 0),
                COALESCE(MAX(risco_prf_qtd), 0)
            FROM rota_views.vw_score_municipio_logistico
        """)
        row = cur.fetchone()
        if row:
            _GLOBAL_MAX = {
                "mx_t": float(row[0] or 0),
                "mx_c": float(row[1] or 0),
                "mx_pa": float(row[2] or 0),
                "mx_x": float(row[3] or 0),
                "mx_p": float(row[4] or 0),
                "mx_r": float(row[5] or 0),
            }
            _GLOBAL_MAX_TS = now
        return _GLOBAL_MAX or {}
    except Exception:
        return {}


def _calc_confianca(row: dict) -> int:
    """Nivel de confianca (0-100) medindo cobertura e completude dos dados."""
    score = 0
    uf = row.get("uf")
    municipio = row.get("municipio")
    if uf and municipio:
        score += 20
    elif uf:
        score += 10
    t = row.get("transportadores_qtd")
    if t is not None and t != '':
        score += 20
    c = row.get("cnpjs_logisticos_qtd")
    if c is not None and c != '':
        score += 20
    pa = row.get("pontos_apoio_qtd")
    if pa is not None and pa != '':
        score += 15
    po = row.get("postos_qtd")
    if po is not None and po != '':
        score += 10
    x = row.get("comex_fluxos_qtd")
    if x is not None and x != '':
        score += 10
    r = row.get("risco_prf_qtd")
    if r is not None and r != '':
        score += 5
    return min(score, 100)


def _nivel_correspondencia(uf, municipio) -> str:
    if uf and municipio:
        return "municipio_exato"
    if uf:
        return "uf_regional"
    return "nao_encontrado"


def _classificar_confianca(valor: int) -> str:
    if valor >= 80: return "alta"
    if valor >= 60: return "boa"
    if valor >= 40: return "parcial"
    if valor > 0: return "baixa"
    return "sem_dados"


def _classificar_risco(penalidade: float, max_penalidade: float) -> tuple[str, str]:
    if max_penalidade <= 0 or penalidade <= 0:
        return "baixo", "Baixo"
    ratio = penalidade / max_penalidade
    if ratio >= 0.7: return "elevado", "Elevado"
    if ratio >= 0.3: return "moderado", "Moderado"
    return "baixo", "Baixo"


def _gerar_fatores(row: dict) -> tuple[list[str], list[str]]:
    """Gera fatores positivos e alertas a partir dos dados brutos."""
    positivos = []
    atencao = []
    
    t = row.get("transportadores_qtd") or 0
    c = row.get("cnpjs_logisticos_qtd") or 0
    pa = row.get("pontos_apoio_qtd") or 0
    x = row.get("comex_fluxos_qtd") or 0
    r = row.get("risco_prf_qtd") or 0
    
    if t > 0:
        if t >= 100: positivos.append("Alta presença de transportadores registrados")
        elif t >= 10: positivos.append("Presenca moderada de transportadores")
    else:
        atencao.append("Sem dados de transportadores registrados")
    
    if c > 0:
        if c >= 50: positivos.append("Forte concentracao de empresas logisticas")
        elif c >= 5: positivos.append("Presenca de empresas logisticas")
    else:
        atencao.append("Sem dados de empresas logisticas")
    
    if pa > 0:
        if pa >= 20: positivos.append("Boa infraestrutura regional de apoio")
        elif pa >= 5: positivos.append("Infraestrutura de apoio presente")
    else:
        atencao.append("Baixa cobertura de pontos de apoio")
    
    if x > 0:
        if x >= 10: positivos.append("Sinal relevante de movimentacao economica")
        else: positivos.append("Sinal de movimentacao economica presente")
    
    score_rv = row.get("score_retorno_vazio")
    if score_rv is not None and score_rv != '' and (float(score_rv) or 0) >= 40:
        positivos.append("Destino com bom potencial de retorno")
    
    if r > 0:
        if r >= 10: atencao.append("Risco regional acima da media")
        else: atencao.append("Sinal de ocorrencias na regiao")
    
    return positivos[:3], atencao[:3]


def _build_explicacao(row: dict, global_max: dict) -> dict:
    """Constroi estrutura de explicabilidade para uma linha da view."""
    if not row or row.get("sem_dados"):
        return {}
    
    # UF-only aggregate (AVG) - no component breakdown
    if "score_medio" in row:
        uf = row.get("uf")
        nivel = _nivel_correspondencia(uf, None)
        return {
            "score_logistico": row.get("score_medio"),
            "score_retorno_vazio": row.get("retorno_medio"),
            "classificacao": row.get("classificacao"),
            "confianca_dados": 40,
            "confianca_label": "parcial",
            "nivel_correspondencia": nivel,
            "componentes": {},
            "risco_regional": "sem_dados",
            "risco_regional_label": "Sem dados",
            "fatores_positivos": [],
            "fatores_atencao": ["Dados agregados por UF - sem detalhamento municipal"],
            "limitacoes": ["Media estadual - nao reflete condicoes municipais especificas"],
            "transportadores_qtd": 0, "cnpjs_logisticos_qtd": 0,
            "postos_qtd": 0, "pontos_apoio_qtd": 0,
            "comex_fluxos_qtd": 0, "risco_prf_qtd": 0,
        }
    
    uf = row.get("uf")
    municipio = row.get("municipio")
    
    t = float(row.get("transportadores_qtd") or 0)
    c = float(row.get("cnpjs_logisticos_qtd") or 0)
    pa = float(row.get("pontos_apoio_qtd") or 0)
    x = float(row.get("comex_fluxos_qtd") or 0)
    r = float(row.get("risco_prf_qtd") or 0)
    postos = float(row.get("postos_qtd") or 0)
    
    mx_t = max(float(global_max.get("mx_t", 1)), 1)
    mx_c = max(float(global_max.get("mx_c", 1)), 1)
    mx_pa = max(float(global_max.get("mx_pa", 1)), 1)
    mx_x = max(float(global_max.get("mx_x", 1)), 1)
    mx_r = max(float(global_max.get("mx_r", 1)), 1)
    
    pts_t = round((t / mx_t) * 25, 1) if mx_t > 0 else 0
    pts_c = round((c / mx_c) * 25, 1) if mx_c > 0 else 0
    pts_pa = round((pa / mx_pa) * 20, 1) if mx_pa > 0 else 0
    pts_x = round((x / mx_x) * 20, 1) if mx_x > 0 else 0
    pts_r_pen = round((r / mx_r) * 10, 1) if mx_r > 0 else 0
    
    conf = _calc_confianca(row)
    nivel = _nivel_correspondencia(uf, municipio)
    
    componentes = {
        "transportadores": {
            "quantidade": int(t), "pontos": min(pts_t, 25), "maximo": 25, "fonte": "RNTRC"
        },
        "cnpjs_logisticos": {
            "quantidade": int(c), "pontos": min(pts_c, 25), "maximo": 25, "fonte": "CNPJ (agregado UF)"
        },
        "pontos_apoio": {
            "quantidade": int(pa), "pontos": min(pts_pa, 20), "maximo": 20, "fonte": "Base propria"
        },
    }
    componentes["postos"] = {
        "quantidade": int(postos), "fonte": "ANP", "no_score": True
    }
    componentes["comex"] = {
        "quantidade": int(x), "pontos": min(pts_x, 20), "maximo": 20, "fonte": "Comex (agregado UF)"
    }
    risco_pen = min(pts_r_pen, 10)
    componentes["risco"] = {
        "quantidade": int(r), "penalidade": risco_pen, "maximo_penalidade": 10, "fonte": "PRF (agregado UF)"
    }
    
    risco_tag, risco_label = _classificar_risco(pts_r_pen, 10)
    fatores_pos, fatores_atencao = _gerar_fatores(row)
    
    limitacoes = []
    if nivel == "uf_regional":
        limitacoes.append("Correspondencia realizada apenas por UF - dados podem nao refletir o municipio exato")
    elif nivel == "nao_encontrado":
        limitacoes.append("Municipio nao identificado na base de inteligencia")
    if c > 0 and nivel == "municipio_exato":
        limitacoes.append("CNPJs logisticos sao agregados por UF, nao por municipio")
    if x > 0:
        limitacoes.append("Dados Comex sao agregados por UF, nao por municipio")
    if r > 0:
        limitacoes.append("Risco baseado em dados PRF agregados por UF - nao representa rota exata")
    limitacoes.append("Analise baseada em dados regionais - nao ha tracado geografico real do percurso")
    
    return {
        "score_logistico": row.get("score_logistico"),
        "score_retorno_vazio": row.get("score_retorno_vazio"),
        "classificacao": row.get("classificacao"),
        "confianca_dados": conf,
        "confianca_label": _classificar_confianca(conf),
        "nivel_correspondencia": nivel,
        "componentes": componentes,
        "risco_regional": risco_tag,
        "risco_regional_label": risco_label,
        "fatores_positivos": fatores_pos,
        "fatores_atencao": fatores_atencao,
        "limitacoes": limitacoes,
        "transportadores_qtd": int(t),
        "cnpjs_logisticos_qtd": int(c),
        "postos_qtd": int(postos),
        "pontos_apoio_qtd": int(pa),
        "comex_fluxos_qtd": int(x),
        "risco_prf_qtd": int(r),
    }


def _score_match_explicado(intel_origem: dict, intel_destino: dict) -> dict:
    """Calcula score combinado explicado do match."""
    if not intel_origem and not intel_destino:
        return {}
    
    score_lo = 0.0
    conf = 0
    count = 0
    
    if intel_origem:
        sl = float(intel_origem.get("score_logistico") or 0)
        score_lo += sl * 0.25
        conf += intel_origem.get("confianca_dados") or 0
        count += 1
    
    if intel_destino:
        sl = float(intel_destino.get("score_logistico") or 0)
        score_lo += sl * 0.35
        conf += intel_destino.get("confianca_dados") or 0
        count += 1
    
    score_rv = 0.0
    if intel_destino:
        rv = float(intel_destino.get("score_retorno_vazio") or 0)
        score_rv = rv * 0.30
    
    risco_pen = 0
    if intel_origem.get("risco_regional") == "elevado": risco_pen += 5
    if intel_destino.get("risco_regional") == "elevado": risco_pen += 5
    risco_pen = min(risco_pen, 10)
    
    pre_risco = score_lo + score_rv
    score_total = pre_risco * (1 - risco_pen / 100)
    score_total = max(0, min(100, round(score_total)))
    confianca = round(conf / count) if count > 0 else 0
    
    if score_total >= 80: classe = "muito_forte"
    elif score_total >= 60: classe = "forte"
    elif score_total >= 40: classe = "medio"
    elif score_total >= 20: classe = "fraco"
    else: classe = "baixo_sinal"
    
    fatores_pos = []
    fatores_atencao = []
    seen_pos = set()
    seen_aten = set()
    for src in [intel_origem, intel_destino]:
        if src:
            for f in (src.get("fatores_positivos") or []):
                if f not in seen_pos and len(fatores_pos) < 3:
                    fatores_pos.append(f); seen_pos.add(f)
            for f in (src.get("fatores_atencao") or []):
                if f not in seen_aten and len(fatores_atencao) < 3:
                    fatores_atencao.append(f); seen_aten.add(f)
    
    limitacoes = []
    seen_lim = set()
    for src in [intel_origem, intel_destino]:
        for lim in (src.get("limitacoes") or []):
            if lim not in seen_lim:
                seen_lim.add(lim); limitacoes.append(lim)
    
    return {
        "score_match_explicado": score_total,
        "score_retorno_vazio": round(score_rv, 1),
        "classificacao": classe,
        "confianca_geral": confianca,
        "confianca_label": _classificar_confianca(confianca),
        "forca_origem": intel_origem.get("score_logistico") if intel_origem else None,
        "forca_destino": intel_destino.get("score_logistico") if intel_destino else None,
        "risco_penalidade": risco_pen,
        "fatores_positivos": fatores_pos,
        "fatores_atencao": fatores_atencao,
        "limitacoes": limitacoes,
    }


def get_match_explicado(match, intel_origem: dict, intel_destino: dict) -> dict:
    """Retorna explicacao completa para um match individual."""
    base = _score_match_explicado(intel_origem, intel_destino)
    base["match_id"] = match.id
    base["origem"] = {
        "cidade": match.cidade_origem,
        "uf": match.uf_origem,
        "inteligencia": intel_origem,
    }
    base["destino"] = {
        "cidade": match.cidade_destino,
        "uf": match.uf_destino,
        "inteligencia": intel_destino,
    }
    return base


def _jsonable(row: dict) -> dict:
    out = {}
    for k, v in row.items():
        if isinstance(v, Decimal):
            out[k] = float(v)
        elif isinstance(v, (datetime, date)):
            out[k] = v.isoformat()
        elif isinstance(v, memoryview):
            out[k] = None
        else:
            try:
                # geometry/bytes etc.
                if hasattr(v, "isoformat"):
                    out[k] = v.isoformat()
                else:
                    out[k] = v
            except Exception:
                out[k] = str(v) if v is not None else None
    return out


def _fetch_dicts(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [_jsonable(dict(zip(cols, r))) for r in cur.fetchall()]


def _set_statement_timeout(cur, timeout_ms: Optional[int] = None) -> None:
    timeout = max(1, int(timeout_ms if timeout_ms is not None else STATEMENT_TIMEOUT_MS))
    cur.execute(f"SET statement_timeout = {timeout}")
    cur.execute("SET lock_timeout = 500")


def _cache_key(sql: str, params: list[Any]) -> tuple[str, tuple[Any, ...]]:
    return (sql, tuple(params or []))


def _cache_get(key: tuple[str, tuple[Any, ...]]) -> Optional[dict[str, Any]]:
    if QUERY_CACHE_TTL_SECONDS <= 0:
        return None
    cached = _QUERY_CACHE.get(key)
    if not cached:
        return None
    ts, value = cached
    if time.time() - ts > QUERY_CACHE_TTL_SECONDS:
        _QUERY_CACHE.pop(key, None)
        return None
    return value


def _cache_set(key: tuple[str, tuple[Any, ...]], value: dict[str, Any]) -> None:
    if QUERY_CACHE_TTL_SECONDS <= 0:
        return
    if len(_QUERY_CACHE) > 256:
        oldest = sorted(_QUERY_CACHE.items(), key=lambda item: item[1][0])[:64]
        for old_key, _ in oldest:
            _QUERY_CACHE.pop(old_key, None)
    _QUERY_CACHE[key] = (time.time(), value)


def health() -> dict[str, Any]:
    if not rota_configured():
        return {"status": "unconfigured", "detail": "ROTA_DB_* ausente no .env"}
    conn = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT current_database(), NOW()")
        db, now = cur.fetchone()
        cur.execute(
            """
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name IN ('rota','rota_core','rota_views')
            ORDER BY schema_name
            """
        )
        schemas = [r[0] for r in cur.fetchall()]
        cur.close()
        return {
            "status": "ok",
            "database": db,
            "schemas": schemas,
            "server_time": now.isoformat() if hasattr(now, "isoformat") else str(now),
            "service": "wins-hub-log",
            "module": "inteligencia_rota",
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)[:200]}
    finally:
        if conn:
            conn.close()


def get_inteligencia_stats(include_tops: bool = True) -> dict[str, Any]:
    """Cards + tops para dashboard/métricas.
    
    Cache com stale-if-error: nunca armazena null/erro no cache.
    Em caso de falha, retorna o ultimo resultado valido se disponivel.
    """
    global _last_valid_stats, _last_valid_stats_ts
    cache_key = _cache_key("__inteligencia_stats__", [bool(include_tops)])
    cached = _cache_get(cache_key)
    if cached is not None:
        if _is_valid_inteligencia_stats(cached):
            _log_cache_event(_LOG_CACHE_HIT)
            return cached
        # Cache contem dados invalidos — limpar
        _QUERY_CACHE.pop(cache_key, None)
        _log_cache_event(_LOG_INVALID_SKIP, "cache hit but payload invalid, evicted")

    queries = {
        "total_postos": "SELECT COUNT(*) FROM rota_core.anp_postos",
        "total_pontos_apoio": "SELECT COUNT(*) FROM rota_views.vw_pontos_apoio_rota",
        "total_transportadores": (
            "SELECT COALESCE(SUM(quantidade_transportadores),0) "
            "FROM rota_core.rntrc_agregado_municipio"
        ),
        "total_cnpj_logisticos": (
            "SELECT COUNT(*) FROM rota_core.cnpj_logisticos_agregado"
        ),
        "total_comex": "SELECT COUNT(*) FROM rota_views.vw_comex_fluxo_uf",
        "total_risco_prf": "SELECT COUNT(*) FROM rota_views.vw_risco_rota_prf",
        "total_dnit_pavimento": "SELECT COUNT(*) FROM rota_core.dnit_pavimento",
        "total_dnit_obras": "SELECT COUNT(*) FROM rota_core.dnit_obras",
        "total_municipios_score": "SELECT COUNT(*) FROM rota_views.vw_score_municipio_logistico",
    }
    top_queries = {
        "top_uf_pontos_apoio": (
            "SELECT uf, COUNT(*) AS total FROM rota_views.vw_pontos_apoio_rota "
            "WHERE uf IS NOT NULL GROUP BY uf ORDER BY total DESC LIMIT 10"
        ),
        "top_uf_transportadores": (
            "SELECT uf, COALESCE(SUM(quantidade_transportadores),0) AS total "
            "FROM rota_core.rntrc_agregado_municipio GROUP BY uf ORDER BY total DESC LIMIT 10"
        ),
        "top_uf_postos": (
            "SELECT uf, COUNT(*) AS total FROM rota_core.anp_postos "
            "GROUP BY uf ORDER BY total DESC LIMIT 10"
        ),
        "top_uf_comex": (
            "SELECT uf, COALESCE(SUM(total_valor_fob),0) AS total "
            "FROM rota_views.vw_comex_fluxo_uf GROUP BY uf ORDER BY total DESC LIMIT 10"
        ),
        "top_br_risco": (
            "SELECT br, uf, total_acidentes FROM rota_views.vw_risco_rota_prf "
            "ORDER BY total_acidentes DESC NULLS LAST LIMIT 10"
        ),
        "top_municipios_score": (
            "SELECT uf, municipio, score_logistico, score_retorno_vazio, classificacao "
            "FROM rota_views.vw_score_municipio_logistico "
            "WHERE score_logistico IS NOT NULL "
            "ORDER BY score_logistico DESC LIMIT 10"
        ),
    }
    had_any_error = False
    data: dict[str, Any] = {"status": "ok"}
    conn = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        _set_statement_timeout(cur, STATS_STATEMENT_TIMEOUT_MS)
        for key, sql in queries.items():
            try:
                cur.execute(sql)
                row = cur.fetchone()
                v = row[0] if row else 0
                data[key] = float(v) if isinstance(v, Decimal) else (v or 0)
            except Exception:
                had_any_error = True
                conn.rollback()
                _set_statement_timeout(cur, STATS_STATEMENT_TIMEOUT_MS)
                data[key] = None
        if include_tops:
            for key, sql in top_queries.items():
                try:
                    cur.execute(sql)
                    cols = [d[0] for d in cur.description]
                    data[key] = [_jsonable(dict(zip(cols, r))) for r in cur.fetchall()]
                except Exception:
                    had_any_error = True
                    conn.rollback()
                    _set_statement_timeout(cur, STATS_STATEMENT_TIMEOUT_MS)
                    data[key] = []
        else:
            for key in top_queries:
                data[key] = []
        cur.close()

        if had_any_error:
            _log_cache_event(_LOG_REFRESH_ERROR, "partial query failure")
        else:
            _log_cache_event(_LOG_REFRESH_OK)

        if _is_valid_inteligencia_stats(data):
            _cache_set(cache_key, data)
            _last_valid_stats = dict(data)
            _last_valid_stats_ts = time.time()
            return data

        # Dados invalidos — nao armazenar no cache
        _log_cache_event(_LOG_INVALID_SKIP, "new payload invalid, not cached")
    except Exception as e:
        _log_cache_event(_LOG_REFRESH_ERROR, str(e)[:100])
        had_any_error = True
    finally:
        if conn:
            conn.close()

    # Stale-if-error: retornar ultimo resultado valido se existir
    if _last_valid_stats is not None and (time.time() - _last_valid_stats_ts) < _STALE_MAX_AGE:
        stale = dict(_last_valid_stats)
        stale["_stale_ts"] = _last_valid_stats_ts
        stale["_fresh"] = False
        _log_cache_event(_LOG_STALE_USED, f"age={int(time.time()-_last_valid_stats_ts)}s")
        return stale

    # Nunca houve resultado valido — retornar estrutura segura
    _log_cache_event(_LOG_CACHE_MISS, "no valid stats ever, returning safe fallback")
    safe = {"status": "ok", "_unavailable": True}
    for key in queries:
        safe[key] = 0
    for key in top_queries:
        safe[key] = []
    return safe


def get_pontos_apoio(
    uf: Optional[str] = None,
    municipio: Optional[str] = None,
    tipo: Optional[str] = None,
    limit: Optional[int] = 100,
) -> dict[str, Any]:
    lim = _sanitize_limit(limit)
    sql = "SELECT * FROM rota_views.vw_pontos_apoio_rota WHERE 1=1"
    params: list[Any] = []
    if uf:
        sql += " AND uf = %s"
        params.append(uf.upper())
    if municipio:
        sql += " AND municipio ILIKE %s"
        params.append(f"%{municipio}%")
    if tipo:
        sql += " AND tipo_ponto ILIKE %s"
        params.append(f"%{tipo}%")
    sql += " LIMIT %s"
    params.append(lim)
    return _query_list(sql, params)


def get_postos(
    uf: Optional[str] = None,
    municipio: Optional[str] = None,
    bandeira: Optional[str] = None,
    limit: Optional[int] = 100,
) -> dict[str, Any]:
    lim = _sanitize_limit(limit)
    sql = "SELECT * FROM rota_core.anp_postos WHERE 1=1"
    params: list[Any] = []
    if uf:
        sql += " AND uf = %s"
        params.append(uf.upper())
    if municipio:
        sql += " AND municipio ILIKE %s"
        params.append(f"%{municipio}%")
    if bandeira:
        sql += " AND bandeira ILIKE %s"
        params.append(f"%{bandeira}%")
    sql += " LIMIT %s"
    params.append(lim)
    return _query_list(sql, params)


def get_risco_rota(
    uf: Optional[str] = None,
    br: Optional[str] = None,
    limit: Optional[int] = 100,
) -> dict[str, Any]:
    lim = _sanitize_limit(limit)
    sql = "SELECT * FROM rota_views.vw_risco_rota_prf WHERE 1=1"
    params: list[Any] = []
    if uf:
        sql += " AND uf = %s"
        params.append(uf.upper())
    if br:
        sql += " AND br = %s"
        params.append(br)
    sql += " ORDER BY total_acidentes DESC NULLS LAST LIMIT %s"
    params.append(lim)
    return _query_list(sql, params)


def get_transportadores_agregado(
    uf: Optional[str] = None,
    municipio: Optional[str] = None,
    limit: Optional[int] = 100,
) -> dict[str, Any]:
    lim = _sanitize_limit(limit)
    sql = "SELECT * FROM rota_core.rntrc_agregado_municipio WHERE 1=1"
    params: list[Any] = []
    if uf:
        sql += " AND uf = %s"
        params.append(uf.upper())
    if municipio:
        sql += " AND municipio ILIKE %s"
        params.append(f"%{municipio}%")
    sql += " ORDER BY quantidade_transportadores DESC NULLS LAST LIMIT %s"
    params.append(lim)
    return _query_list(sql, params)


def get_cnpj_logisticos_agregado(
    uf: Optional[str] = None,
    municipio: Optional[str] = None,
    limit: Optional[int] = 100,
) -> dict[str, Any]:
    lim = _sanitize_limit(limit)
    # prefer view if available
    sql = "SELECT * FROM rota_views.vw_cnpj_logisticos_por_municipio WHERE 1=1"
    params: list[Any] = []
    if uf:
        sql += " AND uf = %s"
        params.append(uf.upper())
    if municipio:
        sql += " AND municipio ILIKE %s"
        params.append(f"%{municipio}%")
    sql += " LIMIT %s"
    params.append(lim)
    out = _query_list(sql, params)
    if out.get("status") == "error":
        sql2 = "SELECT * FROM rota_core.cnpj_logisticos_agregado WHERE 1=1"
        params2: list[Any] = []
        if uf:
            sql2 += " AND uf = %s"
            params2.append(uf.upper())
        if municipio:
            sql2 += " AND municipio ILIKE %s"
            params2.append(f"%{municipio}%")
        sql2 += " LIMIT %s"
        params2.append(lim)
        return _query_list(sql2, params2)
    return out


def get_comex_fluxo_uf(
    uf: Optional[str] = None,
    ano: Optional[int] = None,
    limit: Optional[int] = 100,
) -> dict[str, Any]:
    lim = _sanitize_limit(limit)
    sql = "SELECT * FROM rota_views.vw_comex_fluxo_uf WHERE 1=1"
    params: list[Any] = []
    if uf:
        sql += " AND uf = %s"
        params.append(uf.upper())
    if ano is not None:
        try:
            sql += " AND ano = %s"
            params.append(int(ano))
        except (TypeError, ValueError):
            pass
    sql += " LIMIT %s"
    params.append(lim)
    return _query_list(sql, params)


def get_score_municipio_logistico(
    uf: Optional[str] = None,
    municipio: Optional[str] = None,
    limit: Optional[int] = 100,
) -> dict[str, Any]:
    lim = _sanitize_limit(limit)
    sql = "SELECT * FROM rota_views.vw_score_municipio_logistico WHERE 1=1"
    params: list[Any] = []
    if uf:
        sql += " AND uf = %s"
        params.append(uf.upper())
    if municipio:
        sql += " AND municipio ILIKE %s"
        params.append(f"%{municipio}%")
    sql += " ORDER BY score_logistico DESC NULLS LAST LIMIT %s"
    params.append(lim)
    return _query_list(sql, params)

def _locations_cache_key(locations):
    parts = []
    for loc in locations:
        uf = (loc.get("uf") or "").strip().upper()
        mun = (loc.get("municipio") or "").strip().upper()
        parts.append(f"{uf}::{mun}")
    parts.sort()
    return "__matches_intel__" + "|".join(parts)


def get_matches_inteligencia(
    locations,
):
    if not locations:
        return {"status": "ok", "results": {}}
    cache_key = (_locations_cache_key(locations), tuple())
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    seen = set()
    unique = []
    for loc in locations:
        uf = (loc.get("uf") or "").strip().upper() or None
        mun = (loc.get("municipio") or "").strip().upper() or None
        key = f"{uf}::{mun}" if mun else f"{uf}::"
        if key not in seen:
            seen.add(key)
            unique.append((uf, mun))
    results = {}
    conn = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        _set_statement_timeout(cur, 5000)
        
        # Get global max values for normalization (one query, cached 10 min)
        global_max = _get_global_max(cur)
        
        mun_params = []
        mun_clauses = []
        for uf, mun in unique:
            if uf and mun:
                mun_clauses.append("(uf = %s AND municipio = %s)")
                mun_params.append(uf)
                mun_params.append(mun)
        if mun_clauses:
            sql = "SELECT * FROM rota_views.vw_score_municipio_logistico WHERE " + " OR ".join(mun_clauses)
            cur.execute(sql, mun_params)
            cols = [d[0] for d in cur.description]
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                key = f"{d['uf']}::{d['municipio'].upper()}" if d.get('municipio') else f"{d['uf']}::"
                results[key] = _jsonable(d)
                # Add explicacao
                results[key].update(_build_explicacao(results[key], global_max))
        uf_only = [(uf, mun) for uf, mun in unique if uf and not mun]
        if uf_only:
            uf_list = list(set(u for u, _ in uf_only))
            placeholders = ", ".join("%s" for _ in uf_list)
            sql = f"SELECT uf, COUNT(*) AS total_municipios, AVG(score_logistico) AS score_medio, AVG(score_retorno_vazio) AS retorno_medio FROM rota_views.vw_score_municipio_logistico WHERE uf IN ({placeholders}) GROUP BY uf"
            cur.execute(sql, uf_list)
            for row in cur.fetchall():
                d = dict(zip([desc[0] for desc in cur.description], row))
                key = f"{d['uf']}::"
                if key not in results:
                    results[key] = _jsonable(d)
                    results[key].update(_build_explicacao(results[key], global_max))
        for uf, mun in unique:
            key = f"{uf}::{mun.upper()}" if mun else f"{uf}::"
            if key not in results:
                results[key] = {
                    "uf": uf, "municipio": mun or None, "sem_dados": True,
                    "score_logistico": None, "confianca_dados": 0,
                    "confianca_label": "sem_dados",
                    "nivel_correspondencia": _nivel_correspondencia(uf, mun),
                }
        cur.close()
        result = {"status": "ok", "results": results}
        _cache_set(cache_key, result)
        return result
    except Exception as e:
        return {"status": "error", "detail": str(e)[:200], "results": {}}
    finally:
        if conn:
            conn.close()



def _query_list(sql: str, params: list[Any]) -> dict[str, Any]:
    key = _cache_key(sql, params)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    conn = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        _set_statement_timeout(cur)
        cur.execute(sql, params)
        rows = _fetch_dicts(cur)
        cur.close()
        result = {"status": "ok", "total": len(rows), "results": rows}
        _cache_set(key, result)
        return result
    except Exception as e:
        # Nao armazenar erro no cache para evitar poluicao
        return {"status": "error", "detail": str(e)[:200], "total": 0, "results": []}
    finally:
        if conn:
            conn.close()
