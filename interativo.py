"""Utilitário de Inspeção e Mapeamento de Seletores.

Abre o navegador conectado ao perfil persistente e pausa na tela de busca
para permitir o uso do Playwright Inspector ('Pick locator' / 'Record').
"""

from playwright.sync_api import sync_playwright
from rpa_repositorio_sqlite import RpaRepositorioSqlite

repo = RpaRepositorioSqlite()
USER_DATA_DIR: str = repo.obter_configuracao("user_data_dir", r"C:\BI\Playwright_Profile")
URL_WORKSPACE: str = repo.obter_configuracao("url_workspace", "")

if not URL_WORKSPACE:
    print("[ERRO] Nenhuma URL do Lecom configurada. Abra o app.py e salve a URL.")
    exit(1)

with sync_playwright() as p:
    browser = p.chromium.launch_persistent_context(
        user_data_dir=USER_DATA_DIR,
        channel="chrome",
        headless=False,
        args=["--start-maximized"],
        no_viewport=True,
    )

    page = browser.pages[0] if browser.pages else browser.new_page()
    page.goto(URL_WORKSPACE)

    # Congela a execução e abre o painel de inspeção
    page.pause()