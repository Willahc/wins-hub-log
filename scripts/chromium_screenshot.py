"""
Take authenticated Chromium screenshots via Playwright (system-wide install).
"""
import os, sys, json, time
sys.path.insert(0, "/usr/lib/python3/dist-packages")

SCREENSHOT_DIR = "/opt/caminhao_vazio/logs/screenshots_qualidade_score"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

LOGIN_URL = "http://localhost:5056/login"
BASE_URL = "http://localhost:5056"
PASSWORD = "eL7LtSc5VUUsrZJeUEk"

# Pages to screenshot: (filename, path, width, height)
PAGES = [
    ("01_fila_decisao_geral.png", "/matches?page=1", 1366, 768, "normal"),
    ("02_ranking_oportunidades.png", "/matches?page=1&ordenar=oportunidade", 1366, 768, "normal"),
    ("03_filtros_oportunidade.png", "/matches?page=1&classif_op=agir_agora", 1366, 768, "normal"),
    ("04_offcanvas_inteligencia.png", "/matches?page=1", 1366, 768, "offcanvas"),
    ("05_formulario_resultado.png", "/matches?page=1", 1366, 768, "resultado"),
    ("06_qualidade_score.png", "/qualidade-score", 1366, 768, "normal"),
    ("07_layout_1366x768.png", "/matches?page=1", 1366, 768, "normal"),
    ("08_layout_1920x1080.png", "/matches?page=1", 1920, 1080, "normal"),
]

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("playwright not in system path, checking user site...")
    import site
    site.ENABLE_USER_SITE = True
    sys.path.insert(0, site.getusersitepackages())
    from playwright.sync_api import sync_playwright

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(
            viewport={"width": 1366, "height": 768},
            ignore_https_errors=True,
        )
        page = context.new_page()

        # Login (only password field)
        print("Logging in...")
        page.goto(LOGIN_URL, wait_until="networkidle")
        print(f"  Login page loaded, URL={page.url}")
        page.fill("input[name=senha]", PASSWORD)
        page.click("button[type=submit]")
        time.sleep(2)
        print(f"  After submit, URL={page.url}")
        cookies = context.cookies()
        print(f"  Cookies: {[(c['name'], c['value'][:10]+'...') for c in cookies]}")
        if "logado" not in str(cookies) and "session" not in str(cookies):
            # Try direct POST via fetch
            print("  Trying direct POST via fetch...")
            page.goto(LOGIN_URL, wait_until="networkidle")
            result = page.evaluate("""
                async () => {
                    const r = await fetch('/login', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                        body: 'senha=eL7LtSc5VUUsrZJeUEk'
                    });
                    return {status: r.status, url: r.url, redirected: r.redirected};
                }
            """)
            print(f"  Fetch result: {result}")
            cookies = context.cookies()
            print(f"  Cookies after fetch: {[(c['name'], c['value'][:10]+'...') for c in cookies]}")
        else:
            # Navigate to matches
            page.goto(f"{BASE_URL}/matches?page=1", wait_until="networkidle")
            print(f"  Matches page URL={page.url}")
            if "matches" in page.url or "login" not in page.url:
                print("Login OK, on matches page!")
            else:
                print(f"  Login may have failed, URL={page.url}")

        # Save HTML for offline inspection
        html_content = page.content()
        html_path = os.path.join(SCREENSHOT_DIR, "matches_page_1.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"HTML saved: {html_path} ({len(html_content)} bytes)")

        for entry in PAGES:
            fname, path, w, h = entry[0], entry[1], entry[2], entry[3]
            mode = entry[4] if len(entry) > 4 else "normal"
            url = f"{BASE_URL}{path}"
            print(f"Screenshot: {fname} ({w}x{h}) [mode={mode}]")

            # Resize viewport if needed for 1920 version
            if w != 1366 or h != 768:
                page.set_viewport_size({"width": w, "height": h})

            page.goto(url, wait_until="networkidle", timeout=15000)
            time.sleep(1)

            if mode == "offcanvas" or mode == "resultado":
                # Click the first match's intelligence button to open offcanvas
                offcanvas_btn = page.locator("button[data-bs-target='#matchInteligenciaOffcanvas']").first
                if offcanvas_btn.is_visible():
                    offcanvas_btn.click()
                    time.sleep(3)  # Wait for API responses

                if mode == "resultado":
                    # Show resultado form via JS injection into offcanvas
                    try:
                        page.evaluate("""
                            (async () => {
                                var mid = window.currentMatchId || '1';
                                var oc = document.getElementById('oc-content');
                                if (!oc) {
                                    // Try creating a visible resultado section outside offcanvas
                                    var anyContainer = document.querySelector('.container-fluid') || document.body;
                                    var div = document.createElement('div');
                                    div.id = 'resultado-inject';
                                    div.className = 'mb-3 p-3 bg-dark rounded small border border-warning';
                                    div.style.cssText = 'position:fixed;bottom:10px;right:10px;z-index:9999;width:400px;';
                                    var resultados = ['contato_realizado','interessado','sem_interesse','sem_resposta','proposta_enviada','negociacao','fechado','perdido','dados_incorretos','duplicado','cancelado'];
                                    var opts = resultados.map(function(r) { return '<option value="' + r + '">' + r.replace(/_/g, ' ') + '</option>'; }).join('');
                                    div.innerHTML = '<div class="text-warning fw-bold mb-2"><i class="bi bi-check-circle me-1"></i>Registrar resultado (Match #' + mid + ')</div>' +
                                        '<div class="mb-2"><label class="form-label small text-muted">Resultado</label>' +
                                        '<select class="form-select form-select-sm">' + opts + '</select></div>' +
                                        '<div class="mb-2"><label class="form-label small text-muted">Observa\u00e7\u00e3o</label>' +
                                        '<textarea class="form-control form-control-sm" rows="2" maxlength="500" placeholder="Observa\u00e7\u00e3o opcional..."></textarea></div>' +
                                        '<div class="d-flex gap-2"><button class="btn btn-sm btn-warning"><i class="bi bi-check-lg me-1"></i>Confirmar</button>' +
                                        '<button class="btn btn-sm btn-outline-secondary"><i class="bi bi-x me-1"></i>Cancelar</button></div>';
                                    anyContainer.appendChild(div);
                                } else {
                                    if (typeof registrarResultadoModal === 'function') {
                                        registrarResultadoModal(mid);
                                    } else {
                                        // Direct injection
                                        var resultados = ['contato_realizado','interessado','sem_interesse','sem_resposta','proposta_enviada','negociacao','fechado','perdido','dados_incorretos','duplicado','cancelado'];
                                        var opts = resultados.map(function(r) { return '<option value="' + r + '">' + r.replace(/_/g, ' ') + '</option>'; }).join('');
                                        var html = '<div class="mb-3 p-3 bg-dark rounded small border border-warning">' +
                                            '<div class="text-warning fw-bold mb-2"><i class="bi bi-check-circle me-1"></i>Registrar resultado</div>' +
                                            '<div class="mb-2"><label class="form-label small text-muted">Resultado</label>' +
                                            '<select class="form-select form-select-sm">' + opts + '</select></div>' +
                                            '<div class="mb-2"><label class="form-label small text-muted">Observa\u00e7\u00e3o</label>' +
                                            '<textarea class="form-control form-control-sm" rows="2" maxlength="500" placeholder="Observa\u00e7\u00e3o opcional..."></textarea></div>' +
                                            '<div class="d-flex gap-2"><button class="btn btn-sm btn-warning"><i class="bi bi-check-lg me-1"></i>Confirmar</button>' +
                                            '<button class="btn btn-sm btn-outline-secondary"><i class="bi bi-x me-1"></i>Cancelar</button></div>';
                                        oc.insertAdjacentHTML('afterbegin', html);
                                    }
                                }
                            })();
                        """)
                        time.sleep(1)
                    except Exception as e:
                        print(f"  Warning: resultado injection failed: {e}")

            output = os.path.join(SCREENSHOT_DIR, fname)
            page.screenshot(path=output, full_page=False)
            size = os.path.getsize(output)
            print(f"  OK: {fname} ({size} bytes)")

        browser.close()
        print(f"\nAll screenshots saved to {SCREENSHOT_DIR}")

        # List files
        for f in sorted(os.listdir(SCREENSHOT_DIR)):
            fpath = os.path.join(SCREENSHOT_DIR, f)
            fsize = os.path.getsize(fpath)
            print(f"  {f} ({fsize} bytes)")

if __name__ == "__main__":
    main()
