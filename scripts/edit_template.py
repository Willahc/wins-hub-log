"""
Add global distribution section to qualidade_score.html template.
"""
TEMPLATE = "/home/william/repos/wins-hub-log/templates/qualidade_score.html"

with open(TEMPLATE, "r", encoding="utf-8") as f:
    content = f.read()

# Section to add
global_section = """  <!-- Distribuicao Atual dos Matches (Auditoria Global) -->
  {% if global_audit and global_audit.get('estatisticas') %}
  {% set e = global_audit['estatisticas'] %}
  {% set fa = global_audit['distribuicao_faixas'] %}
  {% set ca = global_audit['compressao'] %}
  {% set comp = global_audit['componentes'] %}
  <div class="qs-card mb-3" style="border-color:var(--wins-amber);">
    <div class="d-flex justify-content-between align-items-center mb-2">
      <h6 class="mb-0 text-warning"><i class="bi bi-globe me-1"></i>Distribui\u00e7\u00e3o atual dos matches</h6>
      <span class="badge bg-warning text-dark qs-badge">{{ global_audit.metadados.formula_versao }}</span>
    </div>
    <div class="alert alert-warning small py-1 px-2 mb-2" style="font-size:0.7rem;">
      <i class="bi bi-info-circle me-1"></i>
      A distribui\u00e7\u00e3o atual do score n\u00e3o representa probabilidade de fechamento.
      A avalia\u00e7\u00e3o de resultados utiliza snapshots hist\u00f3ricos.
    </div>

    <div class="row g-2 mb-2">
      <div class="col-md-2 col-4"><div class="small text-muted">Auditados</div><div class="fw-bold">{{ global_audit.processamento.total_processado }}</div></div>
      <div class="col-md-2 col-4"><div class="small text-muted">Score \u00fanicos</div><div class="fw-bold text-info">{{ e.unicos }}</div></div>
      <div class="col-md-2 col-4"><div class="small text-muted">M\u00ednimo</div><div class="fw-bold">{{ e.min }}</div></div>
      <div class="col-md-2 col-4"><div class="small text-muted">M\u00e1ximo</div><div class="fw-bold">{{ e.max }}</div></div>
      <div class="col-md-2 col-4"><div class="small text-muted">M\u00e9dia</div><div class="fw-bold">{{ e.media }}</div></div>
      <div class="col-md-2 col-4"><div class="small text-muted">Mediana</div><div class="fw-bold">{{ e.mediana }}</div></div>
    </div>

    <div class="row g-2 mb-2">
      <div class="col-md-3"><div class="small text-muted">Desvio padr\u00e3o: <strong>{{ e.desvio_padrao }}</strong></div></div>
      <div class="col-md-3"><div class="small text-muted">P10: <strong>{{ e.p10 }}</strong>  P25: <strong>{{ e.p25 }}</strong>  P50: <strong>{{ e.p50 }}</strong></div></div>
      <div class="col-md-3"><div class="small text-muted">P75: <strong>{{ e.p75 }}</strong>  P90: <strong>{{ e.p90 }}</strong>  P99: <strong>{{ e.p99 }}</strong></div></div>
      <div class="col-md-3"><div class="small text-muted">Amplitude: <strong>{{ e.amplitude }}</strong>/100</div></div>
    </div>

    <div class="table-responsive small mb-2">
      <table class="table table-dark table-sm mb-0" style="border-color:#334155;font-size:0.7rem;">
        <thead><tr><th>Classifica\u00e7\u00e3o</th><th>Faixa</th><th class="text-end">Qtd</th><th class="text-end">%</th><th class="text-end">Score m\u00e9dio</th></tr></thead>
        <tbody>
          {% for fname in ['revisar_dados','baixa_prioridade','acompanhar','alta_prioridade','agir_agora'] %}
          {% set f = fa.get(fname, {}) %}
          <tr>
            <td><span class="badge {% if fname == 'agir_agora' %}bg-warning text-dark{% elif fname == 'alta_prioridade' %}bg-info{% elif fname == 'acompanhar' %}bg-primary{% elif fname == 'baixa_prioridade' %}bg-secondary{% else %}bg-dark text-muted{% endif %} qs-badge">{{ fname.replace('_',' ') }}</span></td>
            <td>{% if fname == 'revisar_dados' %}0-19{% elif fname == 'baixa_prioridade' %}20-39{% elif fname == 'acompanhar' %}40-59{% elif fname == 'alta_prioridade' %}60-79{% else %}80-100{% endif %}</td>
            <td class="text-end">{{ f.get('quantidade', 0) }}</td>
            <td class="text-end">{{ f.get('percentual', 0) }}%</td>
            <td class="text-end">{{ f.get('score_medio', '-') or '-' }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>

    <div class="row g-2 small">
      <div class="col-md-6">
        <div class="text-muted">Componentes:</div>
        <ul class="list-unstyled mb-0" style="font-size:0.65rem;">
          {% for cname, cdata in comp.items() %}
          <li><span class="text-muted">{{ cname }}:</span> m\u00e9dia {{ cdata.get('media','?') }}/{{ cdata.get('maximo','?') }} ({{ cdata.get('unicos',0) }} valores \u00fanicos)</li>
          {% endfor %}
        </ul>
      </div>
      <div class="col-md-6">
        <div class="text-muted">Compress\u00e3o:</div>
        <ul class="list-unstyled mb-0" style="font-size:0.65rem;">
          <li>{{ ca.get('pct_modal_5',0) }}% no intervalo modal de 5 pts</li>
          <li>{{ ca.get('ratio_unicos_total',0) }} scores \u00fanicos / total</li>
          <li>Alertas: 
            {% for a in ca.get('alertas', []) %}
            <span class="badge bg-danger qs-badge">{{ a }}</span>
            {% else %}
            <span class="text-success">Nenhum</span>
            {% endfor %}
          </li>
        </ul>
      </div>
    </div>

    <div class="small text-muted mt-2">
      \u00daltima auditoria: {{ global_audit.metadados.data_auditoria[:10] }} ({{ global_audit.metadados.tempo_execucao_s }}s)
    </div>
  </div>
  {% endif %}

"""

# Insert before the Legenda section
old = "  <!-- Legenda -->"
content = content.replace(old, global_section + old, 1)

with open(TEMPLATE, "w", encoding="utf-8") as f:
    f.write(content)

print("Template updated with global distribution section.")
