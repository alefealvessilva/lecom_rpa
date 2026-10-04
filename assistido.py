"""Automação RPA Lecom - Modo Assistido (Interface Visível).

Executa as rotinas cadastradas no banco de dados SQLite com interface visível
(headless=False) para acompanhamento e resolução de credenciais/MFA.
"""

import os
import re
import shutil
import ssl
import sys
import time
import urllib.parse
import urllib.request
from typing import List
from playwright.sync_api import sync_playwright

from i_rpa_tarefa import TarefaExportacao
from rpa_repositorio_sqlite import RpaRepositorioSqlite

repo = RpaRepositorioSqlite()
USER_DATA_DIR: str = repo.obter_configuracao("user_data_dir", r"C:\BI\Playwright_Profile")
URL_WORKSPACE: str = repo.obter_configuracao("url_workspace", "")
ROTINAS: List[TarefaExportacao] = repo.listar_tarefas()


def exportar_endpoint(p, tarefa: TarefaExportacao, index: int, total: int) -> None:
    os.makedirs(os.path.dirname(tarefa.caminho_destino), exist_ok=True)
    print(f"\n[{index}/{total}] Processando endpoint: '{tarefa.nome_pesquisa}'")

    browser = p.chromium.launch_persistent_context(
        user_data_dir=USER_DATA_DIR,
        channel="chrome",
        headless=False,
        args=["--start-maximized"],
        no_viewport=True,
        accept_downloads=True,
        slow_mo=1000,
    )

    try:
        page = browser.pages[0] if browser.pages else browser.new_page()

        # 1. Acesso à URL configurada
        page.goto(URL_WORKSPACE, wait_until="domcontentloaded")

        # 2. Login SAML / SSO genérico
        try:
            btn_saml = page.locator("div").filter(has_text=re.compile(r"^Entrar com (SAML|SSO)$", re.IGNORECASE)).first
            if btn_saml.is_visible(timeout=3000):
                btn_saml.click()
                print("Botão SAML/SSO acionado.")
                page.wait_for_timeout(1500)
        except Exception:
            pass

        campo_busca = page.locator("#field-search").or_(
            page.get_by_role("textbox", name=re.compile(r"Pesquise", re.IGNORECASE))
        ).first

        url_atual_lower = page.url.lower()
        em_tela_login = (
            "login" in url_atual_lower
            or "sso" in url_atual_lower
            or "microsoftonline" in url_atual_lower
            or "auth" in url_atual_lower
        )

        if em_tela_login:
            print("Aguardando preenchimento de login e aprovação de MFA no navegador (até 5 min)...")
            autenticado = False
            for _ in range(300):
                try:
                    btn_yes = page.get_by_role("button", name=re.compile(r"^(Sim|Yes)$", re.IGNORECASE))
                    if btn_yes.first.is_visible(timeout=500):
                        btn_yes.first.click()
                        print("Confirmação de SSO aceita.")
                except Exception:
                    pass

                try:
                    if campo_busca.is_visible():
                        autenticado = True
                        break
                except Exception:
                    pass
                page.wait_for_timeout(1000)

            if not autenticado:
                raise TimeoutError("Tempo limite para autenticação excedido (5 minutos).")

            print("Login e MFA confirmados com sucesso!")

        try:
            btn_yes = page.get_by_role("button", name=re.compile(r"^(Sim|Yes)$", re.IGNORECASE))
            if btn_yes.first.is_visible(timeout=2000):
                btn_yes.first.click()
                print("Confirmação de SSO aceita.")
        except Exception:
            pass

        caminho_url = urllib.parse.urlparse(URL_WORKSPACE).path
        if caminho_url and caminho_url not in page.url and "login" not in page.url.lower():
            page.goto(URL_WORKSPACE, wait_until="domcontentloaded")

        # 3. Localização do campo de busca
        campo_busca.wait_for(state="visible", timeout=30000)
        page.wait_for_timeout(1000)
        campo_busca.click()

        # 4. Seleção da pesquisa salva
        tablist = page.get_by_role("tablist")
        tablist.wait_for(state="visible")
        tablist.click()

        opcao = page.get_by_text(tarefa.nome_pesquisa)
        opcao.wait_for(state="visible", timeout=15000)
        opcao.click()

        # 5. Abertura do modal de exportação
        btn_export = page.locator('button:has(path[d*="M19 9h-4"])')
        btn_export.wait_for(state="visible", timeout=30000)
        btn_export.click()

        chk_form = page.get_by_role("checkbox", name="Informações do formulário")
        chk_form.wait_for(state="visible", timeout=15000)
        chk_form.check()

        # 6. Geração e captura do download
        print(f"Gerando relatório para '{tarefa.nome_pesquisa}'...")
        cookies_sessao = browser.cookies()

        with page.expect_download(timeout=180000) as download_info:
            page.get_by_role("button", name="Gerar").click()

        download = download_info.value
        print(f"Download detectado: {download.suggested_filename}")

        try:
            download.save_as(tarefa.caminho_destino)
            print(f"Relatório '{tarefa.nome_pesquisa}' salvo em: {tarefa.caminho_destino}")
        except Exception as e:
            print(f"Salvando via stream direto ({e})...")
            cookie_header = "; ".join([f"{c['name']}={c['value']}" for c in cookies_sessao])
            req = urllib.request.Request(
                download.url,
                headers={
                    "Cookie": cookie_header,
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Referer": URL_WORKSPACE
                }
            )
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            with urllib.request.urlopen(req, context=ctx, timeout=180) as resp, open(tarefa.caminho_destino, "wb") as f:
                shutil.copyfileobj(resp, f)
            print(f"Relatório '{tarefa.nome_pesquisa}' salvo via stream direto em: {tarefa.caminho_destino}")

    finally:
        try:
            browser.close()
        except Exception:
            pass


def main() -> None:
    if not URL_WORKSPACE:
        print("\n[ERRO] Nenhuma URL do Lecom Workspace configurada.")
        print("Abra a interface gráfica 'python app.py' e informe a URL do seu workspace Lecom.\n")
        sys.exit(1)

    tarefas_ativas: List[TarefaExportacao] = [t for t in ROTINAS if t.ativo]
    if not tarefas_ativas:
        print("\n[AVISO] Nenhuma rotina ativa encontrada no banco de dados SQLite (rpa_dados.db).")
        print("Execute 'python app.py' para cadastrar seus endpoints e arquivos de destino.\n")
        sys.exit(0)

    with sync_playwright() as p:
        total: int = len(tarefas_ativas)
        for idx, rotina in enumerate(tarefas_ativas, start=1):
            exportar_endpoint(p, rotina, idx, total)
            time.sleep(1)

        print("\nTodos os endpoints foram finalizados com sucesso.")


if __name__ == "__main__":
    main()