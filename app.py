"""Interface Gráfica e Ponto de Entrada para Executável asclabs RPA Suite • Automatizador de Relatórios."""

import ctypes
import os
import re
import shutil
import ssl
import sys
import threading
import time
import urllib.parse
import urllib.request
from typing import List, Optional, Protocol
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from playwright.sync_api import sync_playwright

from i_rpa_tarefa import TarefaExportacao
from rpa_repositorio_sqlite import RpaRepositorioSqlite

APP_ID_WINDOWS: str = "br.com.asclabs.lecom_rpa"
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID_WINDOWS)
except Exception:
    pass

USER_DATA_DIR_PADRAO: str = r"C:\BI\Playwright_Profile"
URL_WORKSPACE_PADRAO: str = ""
PLACEHOLDER_URL: str = "https://dominio-lecom/workspace/result-search"


def obter_caminho_recurso(caminho_relativo: str) -> str:
    """Retorna o caminho absoluto do recurso, compatível com PyInstaller e execução direta."""
    try:
        base_path = sys._MEIPASS  # type: ignore[attr-defined]
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, caminho_relativo)


class SessionExpiredError(Exception):
    """Exceção para sinalizar perda de sessão ou redirecionamento para login."""
    pass


class ExecutionCancelledError(Exception):
    """Exceção para sinalizar parada imediata solicitada pelo usuário."""
    pass


class i_rpa_observer(Protocol):
    """Contrato de observador para atualizações de estado e logs da automação."""

    def on_status_change(self, status: str) -> None:
        ...

    def on_log(self, message: str) -> None:
        ...

    def on_finish(
        self,
        success: bool,
        message: str,
        is_session_expired: bool = False,
        is_cancelled: bool = False,
    ) -> None:
        ...


class RpaService:
    """Serviço responsável pela orquestração do RPA Lecom."""

    def __init__(self, observer: i_rpa_observer) -> None:
        self._observer: i_rpa_observer = observer
        self._parada_solicitada: bool = False
        self._browser_ativo = None
        self._lock: threading.Lock = threading.Lock()

    def solicitar_parada(self) -> None:
        with self._lock:
            self._parada_solicitada = True
            if self._browser_ativo is not None:
                try:
                    self._browser_ativo.close()
                except Exception:
                    pass

    def executar(
        self,
        headless: bool,
        tarefas: List[TarefaExportacao],
        user_data_dir: str,
        url_workspace: str,
    ) -> None:
        with self._lock:
            self._parada_solicitada = False
            self._browser_ativo = None

        tarefas_ativas: List[TarefaExportacao] = [t for t in tarefas if t.ativo]
        if not tarefas_ativas:
            self._observer.on_log("Nenhum endpoint ativo selecionado para exportação.")
            self._observer.on_finish(False, "Nenhum endpoint ativo selecionado.")
            return

        total: int = len(tarefas_ativas)

        try:
            self._observer.on_status_change("Iniciando navegador...")
            self._observer.on_log(f"Modo: {'Segundo Plano (Headless)' if headless else 'Visível (Assistido)'}")
            self._observer.on_log(f"Perfil: {user_data_dir}")
            self._observer.on_log(f"URL Alvo: {url_workspace}")
            self._observer.on_log(f"Total de endpoints a processar: {total}")

            with sync_playwright() as p:
                for index, tarefa in enumerate(tarefas_ativas):
                    with self._lock:
                        if self._parada_solicitada:
                            raise ExecutionCancelledError("Execução interrompida pelo usuário.")

                    self._processar_tarefa(p, tarefa, user_data_dir, url_workspace, headless, index + 1, total)

                    with self._lock:
                        if self._parada_solicitada:
                            raise ExecutionCancelledError("Execução interrompida pelo usuário.")

                    time.sleep(1)

            self._observer.on_status_change("Concluído com sucesso!")
            self._observer.on_finish(True, f"Processamento finalizado!\nTotal de relatórios gerados: {total}")

        except ExecutionCancelledError:
            self._observer.on_status_change("Execução Interrompida")
            self._observer.on_log("Processo cancelado pelo usuário.")
            self._observer.on_finish(False, "Execução cancelada pelo usuário.", is_cancelled=True)
        except SessionExpiredError as exc:
            self._observer.on_status_change("Sessão Expirada")
            self._observer.on_log(f"[ALERTA] {str(exc)}")
            self._observer.on_finish(False, str(exc), is_session_expired=True)
        except Exception as exc:
            with self._lock:
                if self._parada_solicitada:
                    self._observer.on_status_change("Execução Interrompida")
                    self._observer.on_log("Processo cancelado pelo usuário.")
                    self._observer.on_finish(False, "Execução cancelada pelo usuário.", is_cancelled=True)
                    return
            self._observer.on_status_change("Erro na execução")
            self._observer.on_log(f"ERRO: {str(exc)}")
            self._observer.on_finish(False, str(exc), is_session_expired=False)

    def _processar_tarefa(
        self,
        p,
        tarefa: TarefaExportacao,
        user_data_dir: str,
        url_workspace: str,
        headless: bool,
        index: int,
        total: int,
    ) -> None:
        os.makedirs(os.path.dirname(tarefa.caminho_destino), exist_ok=True)
        self._observer.on_status_change(f"[{index}/{total}] Exportando '{tarefa.nome_pesquisa}'...")
        self._observer.on_log(f"[{index}/{total}] Inicializando navegador para: {tarefa.nome_pesquisa}")

        args: List[str] = (
            [
                "--headless=new",
                "--window-size=1920,1080",
                "--disable-gpu",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
            if headless
            else ["--start-maximized"]
        )

        browser = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            channel="chrome",
            headless=headless,
            viewport=None if not headless else {"width": 1920, "height": 1080},
            no_viewport=not headless,
            accept_downloads=True,
            slow_mo=1000 if not headless else 500,
            args=args,
        )

        with self._lock:
            if self._parada_solicitada:
                try:
                    browser.close()
                except Exception:
                    pass
                raise ExecutionCancelledError("Execução interrompida pelo usuário.")
            self._browser_ativo = browser

        try:
            page = browser.pages[0] if browser.pages else browser.new_page()

            page.goto(url_workspace, wait_until="domcontentloaded")

            # Tratamento genérico de botões corporativos SSO / SAML
            try:
                btn_saml = page.locator("div").filter(has_text=re.compile(r"^Entrar com (SAML|SSO)$", re.IGNORECASE)).first
                if btn_saml.is_visible(timeout=3000):
                    btn_saml.click()
                    self._observer.on_log("Autenticação SSO/SAML acionada.")
                    page.wait_for_timeout(1500)
            except Exception:
                pass

            # Definição do seletor do campo de busca no Workspace
            campo_busca = page.locator("#field-search").or_(
                page.get_by_role("textbox", name=re.compile(r"Pesquise", re.IGNORECASE))
            ).first

            # Detecção de tela de autenticação / provedor de identidade
            url_atual_lower = page.url.lower()
            em_tela_login = (
                "login" in url_atual_lower
                or "sso" in url_atual_lower
                or "microsoftonline" in url_atual_lower
                or "auth" in url_atual_lower
            )

            if em_tela_login:
                if headless:
                    raise SessionExpiredError("Sessão expirada. Execute o modo 'Visível (Login/MFA)' para autenticar.")
                else:
                    self._observer.on_status_change("Aguardando Login e MFA...")
                    self._observer.on_log("Aguardando preenchimento de login e aprovação do MFA no navegador...")

                    autenticado = False
                    for _ in range(300):
                        with self._lock:
                            if self._parada_solicitada:
                                raise ExecutionCancelledError("Execução interrompida pelo usuário.")
                        try:
                            btn_yes = page.get_by_role("button", name=re.compile(r"^(Sim|Yes)$", re.IGNORECASE))
                            if btn_yes.first.is_visible(timeout=500):
                                btn_yes.first.click()
                                self._observer.on_log("Confirmação de SSO aceita.")
                        except Exception:
                            pass

                        try:
                            if campo_busca.is_visible():
                                autenticado = True
                                break
                        except Exception as ex_chk:
                            if "closed" in str(ex_chk).lower():
                                raise ExecutionCancelledError("Navegador fechado pelo usuário.")
                        page.wait_for_timeout(1000)

                    if not autenticado:
                        if any(k in page.url.lower() for k in ["login", "sso", "microsoftonline", "auth"]):
                            raise SessionExpiredError("Tempo limite para autenticação excedido (5 minutos).")

                    self._observer.on_log("Autenticação concluída com sucesso!")
                    self._observer.on_status_change("Autenticado!")

            # Caso ainda haja confirmação SSO pendente
            try:
                btn_yes = page.get_by_role("button", name=re.compile(r"^(Sim|Yes)$", re.IGNORECASE))
                if btn_yes.first.is_visible(timeout=2000):
                    btn_yes.first.click()
                    self._observer.on_log("Confirmação de SSO aceita.")
            except Exception:
                pass

            # Se necessário, navega até a URL do workspace
            caminho_url = urllib.parse.urlparse(url_workspace).path
            if caminho_url and caminho_url not in page.url and "login" not in page.url.lower():
                page.goto(url_workspace, wait_until="domcontentloaded")

            # Localização do campo de busca com hidratação
            campo_busca = page.locator("#field-search").or_(
                page.get_by_role("textbox", name=re.compile(r"Pesquise", re.IGNORECASE))
            ).first
            campo_busca.wait_for(state="visible", timeout=30000)
            page.wait_for_timeout(1000)
            campo_busca.click()

            # Seleção da pesquisa salva com retry defensivo
            tablist = page.get_by_role("tablist")
            try:
                tablist.wait_for(state="visible", timeout=5000)
            except Exception:
                campo_busca.click()
                tablist.wait_for(state="visible", timeout=15000)
            tablist.click()

            opcao = page.get_by_text(tarefa.nome_pesquisa)
            opcao.wait_for(state="visible", timeout=15000)
            opcao.click()

            # Modal de exportação
            self._observer.on_log(f"Solicitando exportação de '{tarefa.nome_pesquisa}'...")
            btn_export = page.locator('button:has(path[d*="M19 9h-4"])')
            btn_export.wait_for(state="visible", timeout=30000)
            btn_export.click()

            chk_form = page.get_by_role("checkbox", name="Informações do formulário")
            chk_form.wait_for(state="visible", timeout=15000)
            chk_form.check()

            # Captura do download
            cookies_sessao = browser.cookies()
            with page.expect_download(timeout=180000) as download_info:
                page.get_by_role("button", name="Gerar").click()

            download = download_info.value
            self._observer.on_log(f"Download detectado: {download.suggested_filename}")

            try:
                download.save_as(tarefa.caminho_destino)
                self._observer.on_log(f"Concluído: {tarefa.caminho_destino}")
            except Exception as ex_save:
                self._observer.on_log(f"Fallback stream direto ({ex_save})...")
                cookie_header: str = "; ".join([f"{c['name']}={c['value']}" for c in cookies_sessao])
                req = urllib.request.Request(
                    download.url,
                    headers={
                        "Cookie": cookie_header,
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "Referer": url_workspace,
                    },
                )
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE

                with urllib.request.urlopen(req, context=ctx, timeout=180) as resp, open(tarefa.caminho_destino, "wb") as f:
                    shutil.copyfileobj(resp, f)
                self._observer.on_log(f"Concluído via stream direto: {tarefa.caminho_destino}")

        finally:
            with self._lock:
                self._browser_ativo = None
            try:
                browser.close()
            except Exception:
                pass


class RpaApp(i_rpa_observer):
    """Interface Gráfica da aplicação em Tkinter com suporte a múltiplos endpoints, SQLite e triggers."""

    def __init__(self, root: tk.Tk) -> None:
        self._root: tk.Tk = root
        self._service: RpaService = RpaService(self)
        self._repo: RpaRepositorioSqlite = RpaRepositorioSqlite()

        self._executando: bool = False
        self._agendamento_ativo: bool = False
        self._modo_execucao_atual: Optional[str] = None  # "desassistido", "assistido", "trigger", ou None
        self._segundos_restantes: int = 0
        self._timer_id: Optional[str] = None
        self._sessao_expirada: bool = False
        self._acionado_por_trigger: bool = False

        # Variáveis carregadas do banco de dados SQLite (sem URLs chumbadas)
        self._url_workspace_var: tk.StringVar = tk.StringVar(
            value=self._repo.obter_configuracao("url_workspace", URL_WORKSPACE_PADRAO)
        )
        self._user_data_dir_var: tk.StringVar = tk.StringVar(
            value=self._repo.obter_configuracao("user_data_dir", USER_DATA_DIR_PADRAO)
        )
        self._intervalo_minutos_var: tk.IntVar = tk.IntVar(
            value=int(self._repo.obter_configuracao("intervalo_minutos", "30"))
        )

        self._img_app_logo: Optional[tk.PhotoImage] = None
        self._img_asclabs: Optional[tk.PhotoImage] = None
        self._img_icon: Optional[tk.PhotoImage] = None

        # Referências aos widgets de controle para gerenciamento de travas
        self._btn_salvar_cfg: Optional[tk.Button] = None
        self._entry_sessao: Optional[ttk.Entry] = None
        self._btn_sel_sessao: Optional[tk.Button] = None
        self._btn_add: Optional[tk.Button] = None
        self._btn_edit: Optional[tk.Button] = None
        self._btn_toggle: Optional[tk.Button] = None
        self._btn_del: Optional[tk.Button] = None
        self._btn_trigger: Optional[tk.Button] = None
        self._btn_desassistido: Optional[tk.Button] = None
        self._btn_assistido: Optional[tk.Button] = None
        self._btn_abrir_pasta: Optional[tk.Button] = None

        self._carregar_imagens_institucionais()
        self._rotinas: List[TarefaExportacao] = self._repo.listar_tarefas()

        self._configurar_janela()
        self._criar_componentes()
        self._atualizar_tabela_rotinas()

    def _carregar_imagens_institucionais(self) -> None:
        try:
            caminho_app_logo = obter_caminho_recurso(os.path.join("assets", "app_squircle_header.png"))
            if os.path.exists(caminho_app_logo):
                self._img_app_logo = tk.PhotoImage(file=caminho_app_logo)
        except Exception:
            pass

        try:
            caminho_marca = obter_caminho_recurso(os.path.join("assets", "asclabs_white_header.png"))
            if os.path.exists(caminho_marca):
                self._img_asclabs = tk.PhotoImage(file=caminho_marca)
        except Exception:
            pass

        try:
            caminho_ico = obter_caminho_recurso(os.path.join("assets", "appLogo.ico"))
            if os.path.exists(caminho_ico):
                self._root.iconbitmap(default=caminho_ico)
        except Exception:
            pass

        try:
            caminho_icon = obter_caminho_recurso(os.path.join("assets", "asclabs_icon.png"))
            if os.path.exists(caminho_icon):
                self._img_icon = tk.PhotoImage(file=caminho_icon)
                self._root.iconphoto(True, self._img_icon)
        except Exception:
            pass

    def _salvar_rotinas(self) -> None:
        try:
            self._repo.salvar_tarefas(self._rotinas)
        except Exception as exc:
            self.on_log(f"Erro ao salvar rotinas no banco SQLite: {exc}")

    def _obter_url_digitada(self) -> str:
        """Retorna o valor digitado no campo de URL, ignorando o placeholder."""
        valor = self._entry_url.get().strip()
        if valor == PLACEHOLDER_URL:
            return ""
        return valor

    def _salvar_configuracoes(self) -> None:
        if self._agendamento_ativo or self._executando:
            messagebox.showwarning(
                "Operação Bloqueada",
                "Pare o agendamento ou a execução em andamento antes de alterar configurações.",
            )
            return

        try:
            url_salvar: str = self._obter_url_digitada()
            self._url_workspace_var.set(url_salvar)
            self._repo.salvar_configuracao("url_workspace", url_salvar)
            self._repo.salvar_configuracao("user_data_dir", self._user_data_dir_var.get().strip())
            self._repo.salvar_configuracao("intervalo_minutos", str(self._intervalo_minutos_var.get()))
            self.on_log("Configurações salvas no banco de dados SQLite.")
            messagebox.showinfo("Configurações", "Parâmetros salvos com sucesso!")
        except Exception as exc:
            self.on_log(f"Erro ao salvar configurações no banco SQLite: {exc}")
            messagebox.showerror("Erro", f"Falha ao salvar configurações: {exc}")

    def _configurar_janela(self) -> None:
        self._root.title("asclabs RPA Suite • Automatizador de Relatórios")
        self._root.geometry("880x760")
        self._root.minsize(820, 620)
        self._root.configure(bg="#F8FAFC")

    def _criar_componentes(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")

        # Cabeçalho Institucional asclabs (Dark Slate)
        frame_header = tk.Frame(self._root, bg="#0F172A", padx=16, pady=12)
        frame_header.pack(fill=tk.X)

        if self._img_app_logo:
            lbl_app_logo = tk.Label(frame_header, image=self._img_app_logo, bg="#0F172A")
            lbl_app_logo.pack(side=tk.LEFT, padx=(0, 14))

        frame_titulos = tk.Frame(frame_header, bg="#0F172A")
        frame_titulos.pack(side=tk.LEFT, fill=tk.Y)

        lbl_titulo = tk.Label(
            frame_titulos,
            text="asclabs RPA Suite • Automatizador de Relatórios",
            font=("Segoe UI", 13, "bold"),
            fg="#FFFFFF",
            bg="#0F172A",
        )
        lbl_titulo.pack(anchor=tk.W)

        lbl_subtitulo = tk.Label(
            frame_titulos,
            text="Extração e Exportação Automatizada de Relatórios Lecom",
            font=("Segoe UI", 9),
            fg="#94A3B8",
            bg="#0F172A",
        )
        lbl_subtitulo.pack(anchor=tk.W)

        self._lbl_status = tk.Label(
            frame_titulos,
            text="Status: Pronto para iniciar",
            font=("Segoe UI", 8, "italic"),
            fg="#38BDF8",
            bg="#0F172A",
        )
        self._lbl_status.pack(anchor=tk.W, pady=(2, 0))

        if self._img_asclabs:
            lbl_marca = tk.Label(frame_header, image=self._img_asclabs, bg="#0F172A")
            lbl_marca.pack(side=tk.RIGHT, padx=(16, 0))

        # Painel de Configurações Globais (Totalmente Desacoplado)
        frame_configs = tk.LabelFrame(
            self._root,
            text=" Configurações Globais da Aplicação ",
            font=("Segoe UI", 9, "bold"),
            bg="#F8FAFC",
            fg="#334155",
            padx=12,
            pady=8,
        )
        frame_configs.pack(fill=tk.X, padx=16, pady=6)

        # Linha 1: URL do Lecom / Workspace com Placeholder Apagadinho
        frame_url = tk.Frame(frame_configs, bg="#F8FAFC")
        frame_url.pack(fill=tk.X, pady=(0, 6))

        lbl_url = tk.Label(
            frame_url,
            text="URL do Lecom Workspace:",
            font=("Segoe UI", 9, "bold"),
            bg="#F8FAFC",
            fg="#334155",
            width=26,
            anchor=tk.W,
        )
        lbl_url.pack(side=tk.LEFT)

        self._entry_url = tk.Entry(
            frame_url,
            font=("Segoe UI", 9),
            relief=tk.SOLID,
            bd=1,
            highlightthickness=0,
        )
        self._entry_url.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self._configurar_placeholder_url()

        self._btn_salvar_cfg = tk.Button(
            frame_url,
            text="💾 Salvar Configurações",
            font=("Segoe UI", 8, "bold"),
            bg="#0284C7",
            fg="#FFFFFF",
            activebackground="#0369A1",
            activeforeground="#FFFFFF",
            padx=10,
            pady=2,
            relief=tk.FLAT,
            cursor="hand2",
            command=self._salvar_configuracoes,
        )
        self._btn_salvar_cfg.pack(side=tk.RIGHT)

        # Linha 2: Pasta da Sessão
        frame_sessao = tk.Frame(frame_configs, bg="#F8FAFC")
        frame_sessao.pack(fill=tk.X)

        lbl_sessao = tk.Label(
            frame_sessao,
            text="Perfil do Chrome (Sessão):",
            font=("Segoe UI", 9, "bold"),
            bg="#F8FAFC",
            fg="#334155",
            width=26,
            anchor=tk.W,
        )
        lbl_sessao.pack(side=tk.LEFT)

        self._entry_sessao = ttk.Entry(frame_sessao, textvariable=self._user_data_dir_var, font=("Segoe UI", 9))
        self._entry_sessao.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        self._btn_sel_sessao = tk.Button(
            frame_sessao,
            text="📁 Procurar Perfil",
            font=("Segoe UI", 8),
            bg="#E2E8F0",
            fg="#1E293B",
            padx=10,
            pady=2,
            relief=tk.FLAT,
            cursor="hand2",
            command=self._selecionar_pasta_sessao,
        )
        self._btn_sel_sessao.pack(side=tk.RIGHT)

        # Painel de Endpoints / Rotinas (Tabela)
        frame_rotinas = tk.LabelFrame(
            self._root,
            text=" Fila de Endpoints / Pesquisas Salvas ",
            font=("Segoe UI", 9, "bold"),
            bg="#F8FAFC",
            fg="#334155",
            padx=12,
            pady=8,
        )
        frame_rotinas.pack(fill=tk.BOTH, expand=False, padx=16, pady=4)

        # Treeview de Tarefas
        colunas = ("pesquisa", "destino", "ativo")
        self._tree = ttk.Treeview(frame_rotinas, columns=colunas, show="headings", height=5, selectmode="browse")
        self._tree.heading("pesquisa", text="Pesquisa Salva (Endpoint)")
        self._tree.heading("destino", text="Arquivo de Destino (.xlsx)")
        self._tree.heading("ativo", text="Ativo?")

        self._tree.column("pesquisa", width=220, anchor=tk.W)
        self._tree.column("destino", width=460, anchor=tk.W)
        self._tree.column("ativo", width=70, anchor=tk.CENTER)

        scroll_tree = ttk.Scrollbar(frame_rotinas, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=scroll_tree.set)
        scroll_tree.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.pack(side=tk.TOP, fill=tk.X, expand=True)

        self._tree.bind("<Double-1>", lambda event: self._ao_clicar_duplo_tabela())

        # Barra de Ações da Tabela (Adicionar, Editar, Alternar, Excluir)
        frame_acoes_tabela = tk.Frame(frame_rotinas, bg="#F8FAFC", pady=6)
        frame_acoes_tabela.pack(fill=tk.X)

        self._btn_add = tk.Button(
            frame_acoes_tabela,
            text="➕ Adicionar Endpoint",
            font=("Segoe UI", 8, "bold"),
            bg="#0284C7",
            fg="#FFFFFF",
            activebackground="#0369A1",
            activeforeground="#FFFFFF",
            padx=10,
            pady=3,
            relief=tk.FLAT,
            cursor="hand2",
            command=self._abrir_modal_adicionar_endpoint,
        )
        self._btn_add.pack(side=tk.LEFT, padx=(0, 6))

        self._btn_edit = tk.Button(
            frame_acoes_tabela,
            text="✏️ Editar Endpoint",
            font=("Segoe UI", 8, "bold"),
            bg="#E2E8F0",
            fg="#0F172A",
            activebackground="#CBD5E1",
            activeforeground="#0F172A",
            padx=10,
            pady=3,
            relief=tk.FLAT,
            cursor="hand2",
            command=self._abrir_modal_editar_endpoint,
        )
        self._btn_edit.pack(side=tk.LEFT, padx=(0, 6))

        self._btn_toggle = tk.Button(
            frame_acoes_tabela,
            text="🔄 Alternar Ativo/Inativo",
            font=("Segoe UI", 8),
            bg="#E2E8F0",
            fg="#1E293B",
            padx=10,
            pady=3,
            relief=tk.FLAT,
            cursor="hand2",
            command=self._alternar_ativo_selecionado,
        )
        self._btn_toggle.pack(side=tk.LEFT, padx=(0, 6))

        self._btn_del = tk.Button(
            frame_acoes_tabela,
            text="🗑️ Excluir Selecionado",
            font=("Segoe UI", 8),
            bg="#FEE2E2",
            fg="#DC2626",
            padx=10,
            pady=3,
            relief=tk.FLAT,
            cursor="hand2",
            command=self._remover_endpoint_selecionado,
        )
        self._btn_del.pack(side=tk.LEFT)

        # Painel Trigger / Agendamento Automático
        frame_trigger = tk.LabelFrame(
            self._root,
            text=" Agendamento Automático (Trigger Cíclico) ",
            font=("Segoe UI", 9, "bold"),
            bg="#F8FAFC",
            fg="#334155",
            padx=14,
            pady=8,
        )
        frame_trigger.pack(fill=tk.X, padx=16, pady=4)

        lbl_intervalo = tk.Label(frame_trigger, text="Executar fila a cada:", font=("Segoe UI", 9), bg="#F8FAFC", fg="#475569")
        lbl_intervalo.pack(side=tk.LEFT, padx=(0, 6))

        self._spin_intervalo = ttk.Spinbox(
            frame_trigger,
            from_=1,
            to=1440,
            textvariable=self._intervalo_minutos_var,
            width=5,
            font=("Segoe UI", 9),
        )
        self._spin_intervalo.pack(side=tk.LEFT, padx=(0, 6))

        lbl_minutos = tk.Label(frame_trigger, text="minutos", font=("Segoe UI", 9), bg="#F8FAFC", fg="#475569")
        lbl_minutos.pack(side=tk.LEFT, padx=(0, 16))

        self._btn_trigger = tk.Button(
            frame_trigger,
            text="▶ Ativar Trigger",
            font=("Segoe UI", 9, "bold"),
            bg="#059669",
            fg="#FFFFFF",
            activebackground="#047857",
            activeforeground="#FFFFFF",
            padx=12,
            pady=4,
            relief=tk.FLAT,
            cursor="hand2",
            command=self._alternar_agendamento,
        )
        self._btn_trigger.pack(side=tk.LEFT, padx=(0, 14))

        self._lbl_timer_status = tk.Label(
            frame_trigger,
            text="Trigger: Desativada",
            font=("Segoe UI", 9, "bold"),
            bg="#F8FAFC",
            fg="#64748B",
        )
        self._lbl_timer_status.pack(side=tk.LEFT)

        # Painel de Botões de Ação
        frame_botoes = tk.Frame(self._root, bg="#F8FAFC", padx=16, pady=6)
        frame_botoes.pack(fill=tk.X)

        self._btn_desassistido = tk.Button(
            frame_botoes,
            text="▶ Executar Fila (Segundo Plano)",
            font=("Segoe UI", 9, "bold"),
            bg="#0284C7",
            fg="#FFFFFF",
            activebackground="#0369A1",
            activeforeground="#FFFFFF",
            padx=12,
            pady=6,
            relief=tk.FLAT,
            cursor="hand2",
            command=lambda: self._iniciar_execucao(headless=True, acionado_por_trigger=False),
        )
        self._btn_desassistido.pack(side=tk.LEFT, padx=(0, 8))

        self._btn_assistido = tk.Button(
            frame_botoes,
            text="👁 Executar Visível (Login/MFA)",
            font=("Segoe UI", 9),
            bg="#475569",
            fg="#FFFFFF",
            activebackground="#334155",
            activeforeground="#FFFFFF",
            padx=12,
            pady=6,
            relief=tk.FLAT,
            cursor="hand2",
            command=lambda: self._iniciar_execucao(headless=False, acionado_por_trigger=False),
        )
        self._btn_assistido.pack(side=tk.LEFT, padx=(0, 8))

        self._btn_abrir_pasta = tk.Button(
            frame_botoes,
            text="📂 Abrir Pasta Destino",
            font=("Segoe UI", 9),
            bg="#E2E8F0",
            fg="#1E293B",
            activebackground="#CBD5E1",
            activeforeground="#1E293B",
            padx=12,
            pady=6,
            relief=tk.FLAT,
            cursor="hand2",
            command=self._abrir_pasta_destino,
        )
        self._btn_abrir_pasta.pack(side=tk.RIGHT)

        # Barra de Progresso
        self._progresso = ttk.Progressbar(self._root, mode="indeterminate")
        self._progresso.pack(fill=tk.X, padx=16, pady=(2, 6))

        # Rodapé Institucional asclabs
        frame_rodape = tk.Frame(self._root, bg="#0B132B", padx=16, pady=6)
        frame_rodape.pack(side=tk.BOTTOM, fill=tk.X)

        lbl_creditos = tk.Label(
            frame_rodape,
            text="asclabs • Desenvolvido por Álefe Alves",
            font=("Segoe UI", 8),
            fg="#94A3B8",
            bg="#0B132B",
        )
        lbl_creditos.pack(side=tk.LEFT)

        lbl_versao = tk.Label(
            frame_rodape,
            text="v2.0 • asclabs engine",
            font=("Segoe UI", 8, "bold"),
            fg="#38BDF8",
            bg="#0B132B",
        )
        lbl_versao.pack(side=tk.RIGHT)

        # Área de Logs
        frame_log = tk.Frame(self._root, bg="#F8FAFC", padx=16, pady=2)
        frame_log.pack(fill=tk.BOTH, expand=True)

        lbl_log = tk.Label(frame_log, text="Logs da Operação:", font=("Segoe UI", 9, "bold"), bg="#F8FAFC", fg="#475569")
        lbl_log.pack(anchor=tk.W, pady=(0, 4))

        self._txt_log = tk.Text(
            frame_log,
            wrap=tk.WORD,
            font=("Consolas", 9),
            bg="#0F172A",
            fg="#E2E8F0",
            insertbackground="#FFFFFF",
            relief=tk.FLAT,
            padx=8,
            pady=8,
        )
        scroll_log = ttk.Scrollbar(frame_log, orient=tk.VERTICAL, command=self._txt_log.yview)
        self._txt_log.configure(yscrollcommand=scroll_log.set)
        scroll_log.pack(side=tk.RIGHT, fill=tk.Y)
        self._txt_log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._atualizar_estado_interface()

    def _atualizar_estado_interface(self) -> None:
        """Centraliza o bloqueio de botões: enquanto trigger ou execução estiver rodando,
        trava tudo exceto o botão de parada correspondente."""
        bloqueado: bool = self._agendamento_ativo or self._executando

        # Controles de Configuração
        estado_configs = tk.DISABLED if bloqueado else tk.NORMAL
        if self._entry_url:
            self._entry_url.config(state=estado_configs)
        if self._btn_salvar_cfg:
            self._btn_salvar_cfg.config(state=estado_configs)
        if self._entry_sessao:
            self._entry_sessao.config(state=estado_configs)
        if self._btn_sel_sessao:
            self._btn_sel_sessao.config(state=estado_configs)

        # Controles da Tabela de Endpoints
        if self._btn_add:
            self._btn_add.config(state=estado_configs)
        if self._btn_edit:
            self._btn_edit.config(state=estado_configs)
        if self._btn_toggle:
            self._btn_toggle.config(state=estado_configs)
        if self._btn_del:
            self._btn_del.config(state=estado_configs)

        # Spinbox de Intervalo
        if self._spin_intervalo:
            self._spin_intervalo.config(state=estado_configs)

        # Botão Abrir Pasta
        if self._btn_abrir_pasta:
            self._btn_abrir_pasta.config(state=estado_configs)

        # Botão Trigger
        if self._btn_trigger:
            if self._agendamento_ativo:
                self._btn_trigger.config(
                    text="⏹ Parar Trigger",
                    bg="#DC2626",
                    activebackground="#B91C1C",
                    state=tk.NORMAL,
                    command=self._parar_agendamento,
                )
            elif self._executando:
                self._btn_trigger.config(
                    text="▶ Ativar Trigger",
                    bg="#94A3B8",
                    activebackground="#94A3B8",
                    state=tk.DISABLED,
                )
            else:
                self._btn_trigger.config(
                    text="▶ Ativar Trigger",
                    bg="#059669",
                    activebackground="#047857",
                    state=tk.NORMAL,
                    command=self._iniciar_agendamento,
                )

        # Botão Executar Fila (Segundo Plano)
        if self._btn_desassistido:
            if self._executando and self._modo_execucao_atual == "desassistido":
                self._btn_desassistido.config(
                    text="⏹ Parar Execução",
                    bg="#DC2626",
                    activebackground="#B91C1C",
                    state=tk.NORMAL,
                    command=self._solicitar_parada_execucao,
                )
            elif bloqueado:
                self._btn_desassistido.config(
                    text="▶ Executar Fila (Segundo Plano)",
                    bg="#94A3B8",
                    activebackground="#94A3B8",
                    state=tk.DISABLED,
                )
            else:
                self._btn_desassistido.config(
                    text="▶ Executar Fila (Segundo Plano)",
                    bg="#0284C7",
                    activebackground="#0369A1",
                    state=tk.NORMAL,
                    command=lambda: self._iniciar_execucao(headless=True, acionado_por_trigger=False),
                )

        # Botão Executar Visível (Login/MFA)
        if self._btn_assistido:
            if self._executando and self._modo_execucao_atual == "assistido":
                self._btn_assistido.config(
                    text="⏹ Parar Execução",
                    bg="#DC2626",
                    activebackground="#B91C1C",
                    state=tk.NORMAL,
                    command=self._solicitar_parada_execucao,
                )
            elif bloqueado:
                self._btn_assistido.config(
                    text="👁 Executar Visível (Login/MFA)",
                    bg="#94A3B8",
                    activebackground="#94A3B8",
                    state=tk.DISABLED,
                )
            else:
                cor_bg = "#DC2626" if self._sessao_expirada else "#475569"
                txt_btn = "⚠️ Login Expirado: Executar Visível!" if self._sessao_expirada else "👁 Executar Visível (Login/MFA)"
                self._btn_assistido.config(
                    text=txt_btn,
                    bg=cor_bg,
                    activebackground="#334155",
                    state=tk.NORMAL,
                    command=lambda: self._iniciar_execucao(headless=False, acionado_por_trigger=False),
                )

    def _ao_clicar_duplo_tabela(self) -> None:
        if self._agendamento_ativo or self._executando:
            return
        self._abrir_modal_editar_endpoint()

    def _solicitar_parada_execucao(self) -> None:
        self.on_log("Solicitação de cancelamento enviada. Encerrando execução...")
        self.on_status_change("Interrompendo...")
        self._service.solicitar_parada()

    def _configurar_placeholder_url(self) -> None:
        valor_inicial: str = self._url_workspace_var.get().strip()

        def _on_focus_in(event: tk.Event) -> None:
            if self._entry_url.get() == PLACEHOLDER_URL:
                self._entry_url.delete(0, tk.END)
                self._entry_url.config(fg="#1E293B")

        def _on_focus_out(event: tk.Event) -> None:
            if not self._entry_url.get().strip():
                self._entry_url.delete(0, tk.END)
                self._entry_url.insert(0, PLACEHOLDER_URL)
                self._entry_url.config(fg="#94A3B8")
            else:
                self._url_workspace_var.set(self._entry_url.get().strip())

        self._entry_url.bind("<FocusIn>", _on_focus_in)
        self._entry_url.bind("<FocusOut>", _on_focus_out)

        if not valor_inicial or valor_inicial == PLACEHOLDER_URL:
            self._entry_url.delete(0, tk.END)
            self._entry_url.insert(0, PLACEHOLDER_URL)
            self._entry_url.config(fg="#94A3B8")
        else:
            self._entry_url.delete(0, tk.END)
            self._entry_url.insert(0, valor_inicial)
            self._entry_url.config(fg="#1E293B")

    def _atualizar_tabela_rotinas(self) -> None:
        for item in self._tree.get_children():
            self._tree.delete(item)

        for idx, rotina in enumerate(self._rotinas):
            status_txt = "Sim" if rotina.ativo else "Não"
            self._tree.insert("", tk.END, iid=str(idx), values=(rotina.nome_pesquisa, rotina.caminho_destino, status_txt))

    def _abrir_modal_adicionar_endpoint(self) -> None:
        if self._agendamento_ativo or self._executando:
            messagebox.showwarning(
                "Operação Bloqueada",
                "Pare o agendamento ou a execução em andamento antes de adicionar novos endpoints.",
            )
            return

        modal = tk.Toplevel(self._root)
        modal.title("Adicionar Endpoint / Pesquisa Salva")
        modal.geometry("560x240")
        modal.minsize(520, 220)
        modal.transient(self._root)
        modal.grab_set()

        var_pesquisa = tk.StringVar()
        var_destino = tk.StringVar()

        frame_conteudo = tk.Frame(modal, padx=16, pady=16)
        frame_conteudo.pack(fill=tk.BOTH, expand=True)

        tk.Label(frame_conteudo, text="Nome da Pesquisa Salva no Lecom:", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        entry_pesquisa = ttk.Entry(frame_conteudo, textvariable=var_pesquisa, font=("Segoe UI", 9))
        entry_pesquisa.pack(fill=tk.X, pady=(2, 10))
        entry_pesquisa.focus_set()

        tk.Label(frame_conteudo, text="Arquivo de Destino (.xlsx):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        frame_dest = tk.Frame(frame_conteudo)
        frame_dest.pack(fill=tk.X, pady=(2, 16))

        entry_dest = ttk.Entry(frame_dest, textvariable=var_destino, font=("Segoe UI", 9))
        entry_dest.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

        def _selecionar_destino_modal() -> None:
            caminho_inicial = os.path.dirname(var_destino.get().strip()) if var_destino.get().strip() else "C:\\"
            arquivo = filedialog.asksaveasfilename(
                title="Selecione o Destino do Relatório",
                initialdir=caminho_inicial if os.path.exists(caminho_inicial) else "C:\\",
                defaultextension=".xlsx",
                filetypes=[("Planilha Excel", "*.xlsx"), ("Todos os Arquivos", "*.*")],
            )
            if arquivo:
                var_destino.set(os.path.normpath(arquivo))

        btn_procurar = tk.Button(frame_dest, text="📁 Procurar", command=_selecionar_destino_modal)
        btn_procurar.pack(side=tk.RIGHT)

        def _salvar_novo_endpoint() -> None:
            pesquisa: str = var_pesquisa.get().strip()
            destino: str = var_destino.get().strip()
            if not pesquisa or not destino:
                messagebox.showwarning("Campos Obrigatórios", "Informe o nome da pesquisa salva e o arquivo de destino (.xlsx).", parent=modal)
                return

            self._rotinas.append(TarefaExportacao(nome_pesquisa=pesquisa, caminho_destino=destino, ativo=True))
            self._salvar_rotinas()
            self._atualizar_tabela_rotinas()
            self.on_log(f"Novo endpoint cadastrado: '{pesquisa}' -> '{destino}'")
            modal.destroy()

        btn_confirmar = tk.Button(
            frame_conteudo,
            text="✔ Salvar Endpoint",
            font=("Segoe UI", 9, "bold"),
            bg="#0284C7",
            fg="#FFFFFF",
            padx=14,
            pady=4,
            relief=tk.FLAT,
            command=_salvar_novo_endpoint,
        )
        btn_confirmar.pack(side=tk.RIGHT)

    def _abrir_modal_editar_endpoint(self) -> None:
        if self._agendamento_ativo or self._executando:
            messagebox.showwarning(
                "Operação Bloqueada",
                "Pare o agendamento ou a execução em andamento antes de editar endpoints.",
            )
            return

        selecionado = self._tree.selection()
        if not selecionado:
            messagebox.showinfo("Editar Endpoint", "Selecione um endpoint na tabela para editar.")
            return

        idx = int(selecionado[0])
        rotina_atual = self._rotinas[idx]

        modal = tk.Toplevel(self._root)
        modal.title(f"Editar Endpoint: {rotina_atual.nome_pesquisa}")
        modal.geometry("560x240")
        modal.minsize(520, 220)
        modal.transient(self._root)
        modal.grab_set()

        var_pesquisa = tk.StringVar(value=rotina_atual.nome_pesquisa)
        var_destino = tk.StringVar(value=rotina_atual.caminho_destino)

        frame_conteudo = tk.Frame(modal, padx=16, pady=16)
        frame_conteudo.pack(fill=tk.BOTH, expand=True)

        tk.Label(frame_conteudo, text="Nome da Pesquisa Salva no Lecom:", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        entry_pesquisa = ttk.Entry(frame_conteudo, textvariable=var_pesquisa, font=("Segoe UI", 9))
        entry_pesquisa.pack(fill=tk.X, pady=(2, 10))
        entry_pesquisa.focus_set()

        tk.Label(frame_conteudo, text="Arquivo de Destino (.xlsx):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        frame_dest = tk.Frame(frame_conteudo)
        frame_dest.pack(fill=tk.X, pady=(2, 16))

        entry_dest = ttk.Entry(frame_dest, textvariable=var_destino, font=("Segoe UI", 9))
        entry_dest.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

        def _selecionar_destino_modal() -> None:
            caminho_inicial = os.path.dirname(var_destino.get().strip()) if var_destino.get().strip() else "C:\\"
            arquivo = filedialog.asksaveasfilename(
                title="Selecione o Destino do Relatório",
                initialdir=caminho_inicial if os.path.exists(caminho_inicial) else "C:\\",
                defaultextension=".xlsx",
                filetypes=[("Planilha Excel", "*.xlsx"), ("Todos os Arquivos", "*.*")],
            )
            if arquivo:
                var_destino.set(os.path.normpath(arquivo))

        btn_procurar = tk.Button(frame_dest, text="📁 Procurar", command=_selecionar_destino_modal)
        btn_procurar.pack(side=tk.RIGHT)

        def _salvar_edicao_endpoint() -> None:
            pesquisa: str = var_pesquisa.get().strip()
            destino: str = var_destino.get().strip()
            if not pesquisa or not destino:
                messagebox.showwarning("Campos Obrigatórios", "Informe o nome da pesquisa salva e o arquivo de destino (.xlsx).", parent=modal)
                return

            antigo = self._rotinas[idx].nome_pesquisa
            self._rotinas[idx].nome_pesquisa = pesquisa
            self._rotinas[idx].caminho_destino = destino
            self._salvar_rotinas()
            self._atualizar_tabela_rotinas()
            self.on_log(f"Endpoint editado: '{antigo}' alterado para '{pesquisa}' -> '{destino}'")
            modal.destroy()

        btn_confirmar = tk.Button(
            frame_conteudo,
            text="✔ Salvar Alterações",
            font=("Segoe UI", 9, "bold"),
            bg="#0284C7",
            fg="#FFFFFF",
            padx=14,
            pady=4,
            relief=tk.FLAT,
            command=_salvar_edicao_endpoint,
        )
        btn_confirmar.pack(side=tk.RIGHT)

    def _alternar_ativo_selecionado(self) -> None:
        if self._agendamento_ativo or self._executando:
            return
        selecionado = self._tree.selection()
        if not selecionado:
            return
        idx = int(selecionado[0])
        self._rotinas[idx].ativo = not self._rotinas[idx].ativo
        self._salvar_rotinas()
        self._atualizar_tabela_rotinas()

    def _remover_endpoint_selecionado(self) -> None:
        if self._agendamento_ativo or self._executando:
            return
        selecionado = self._tree.selection()
        if not selecionado:
            return
        idx = int(selecionado[0])
        removido = self._rotinas.pop(idx)
        self._salvar_rotinas()
        self._atualizar_tabela_rotinas()
        self.on_log(f"Endpoint removido: {removido.nome_pesquisa}")

    def _alternar_agendamento(self) -> None:
        if self._agendamento_ativo:
            self._parar_agendamento(motivo="Interrompido pelo usuário")
        else:
            self._iniciar_agendamento()

    def _iniciar_agendamento(self) -> None:
        if self._executando:
            return
        if self._sessao_expirada:
            messagebox.showwarning(
                "Sessão Expirada",
                "A sessão está expirada ou inválida.\nExecute primeiro o modo 'Visível (Login/MFA)' para validar as credenciais antes de ativar a trigger.",
            )
            return

        url_workspace: str = self._obter_url_digitada()
        if not url_workspace:
            messagebox.showerror(
                "Configuração Obrigatória",
                "Informe a URL do Lecom Workspace antes de ativar a trigger.\nExemplo: https://dominio/workspace/result-search",
            )
            return

        tarefas_ativas = [t for t in self._rotinas if t.ativo]
        if not tarefas_ativas:
            messagebox.showwarning("Nenhum Endpoint Ativo", "Cadastre e ative pelo menos um endpoint antes de iniciar a trigger.")
            return

        intervalo: int = max(1, self._intervalo_minutos_var.get())
        self._agendamento_ativo = True
        self._segundos_restantes = intervalo * 60
        self.on_log(f"Trigger ativada: executando {len(tarefas_ativas)} endpoints a cada {intervalo} minuto(s).")
        self._atualizar_estado_interface()
        self._tick_timer()

    def _parar_agendamento(self, motivo: str = "") -> None:
        self._agendamento_ativo = False
        if self._timer_id:
            self._root.after_cancel(self._timer_id)
            self._timer_id = None

        if self._executando and self._acionado_por_trigger:
            self.on_log("Interrompendo execução acionada pela trigger...")
            self._service.solicitar_parada()

        texto_status: str = f"Trigger: Pausada ({motivo})" if motivo else "Trigger: Desativada"
        cor_status: str = "#DC2626" if motivo else "#64748B"
        self._lbl_timer_status.config(text=texto_status, fg=cor_status)

        if motivo:
            self.on_log(f"Trigger parada: {motivo}")

        self._atualizar_estado_interface()

    def _tick_timer(self) -> None:
        if not self._agendamento_ativo:
            return

        if self._segundos_restantes <= 0:
            if not self._executando:
                intervalo: int = max(1, self._intervalo_minutos_var.get())
                self._segundos_restantes = intervalo * 60
                self.on_log("Disparo programado: iniciando processamento sequencial da fila...")
                self._iniciar_execucao(headless=True, acionado_por_trigger=True)
            else:
                self.on_log("Trigger postergada: execução anterior ainda em andamento.")
                self._segundos_restantes = 15

        minutos: int = self._segundos_restantes // 60
        segundos: int = self._segundos_restantes % 60
        self._lbl_timer_status.config(text=f"Próxima execução: {minutos:02d}:{segundos:02d}", fg="#059669")
        self._segundos_restantes -= 1
        self._timer_id = self._root.after(1000, self._tick_timer)

    def _selecionar_pasta_sessao(self) -> None:
        if self._agendamento_ativo or self._executando:
            return
        caminho_atual: str = self._user_data_dir_var.get().strip()
        pasta = filedialog.askdirectory(
            title="Selecione a Pasta do Perfil do Navegador (Sessão)",
            initialdir=caminho_atual if os.path.exists(caminho_atual) else "C:\\",
        )
        if pasta:
            self._user_data_dir_var.set(os.path.normpath(pasta))
            self._salvar_configuracoes()

    def _iniciar_execucao(self, headless: bool, acionado_por_trigger: bool = False) -> None:
        if self._executando:
            return

        url_workspace: str = self._obter_url_digitada()
        if not url_workspace:
            messagebox.showerror(
                "Configuração Obrigatória",
                "Informe a URL do Lecom Workspace antes de executar.\nExemplo: https://dominio/workspace/result-search",
            )
            return

        tarefas_ativas: List[TarefaExportacao] = [t for t in self._rotinas if t.ativo]
        if not tarefas_ativas:
            messagebox.showwarning("Nenhum Endpoint Ativo", "Não há endpoints cadastrados ou ativos para processar.\nClique em '➕ Adicionar Endpoint' para cadastrar.")
            return

        user_data_dir: str = self._user_data_dir_var.get().strip()
        if not user_data_dir:
            messagebox.showerror("Configuração Inválida", "Preencha a pasta da sessão do perfil Chrome.")
            return

        self._executando = True
        self._acionado_por_trigger = acionado_por_trigger
        if acionado_por_trigger:
            self._modo_execucao_atual = "trigger"
        else:
            self._modo_execucao_atual = "desassistido" if headless else "assistido"

        self._atualizar_estado_interface()
        self._progresso.start(12)

        thread = threading.Thread(
            target=self._service.executar,
            args=(headless, self._rotinas, user_data_dir, url_workspace),
            daemon=True,
        )
        thread.start()

    def _abrir_pasta_destino(self) -> None:
        if self._agendamento_ativo or self._executando:
            return
        selecionado = self._tree.selection()
        caminho_arquivo: str = ""
        if selecionado:
            idx = int(selecionado[0])
            caminho_arquivo = self._rotinas[idx].caminho_destino
        elif self._rotinas:
            caminho_arquivo = self._rotinas[0].caminho_destino

        pasta: str = os.path.dirname(caminho_arquivo) if caminho_arquivo else r"C:\BI\Relatorios"
        os.makedirs(pasta, exist_ok=True)
        os.startfile(pasta)

    # Implementação do i_rpa_observer
    def on_status_change(self, status: str) -> None:
        self._root.after(0, lambda: self._lbl_status.config(text=f"Status: {status}"))

    def on_log(self, message: str) -> None:
        def _append() -> None:
            self._txt_log.insert(tk.END, f"{message}\n")
            self._txt_log.see(tk.END)

        self._root.after(0, _append)

    def on_finish(
        self,
        success: bool,
        message: str,
        is_session_expired: bool = False,
        is_cancelled: bool = False,
    ) -> None:
        def _finalizar() -> None:
            self._executando = False
            self._modo_execucao_atual = None
            self._progresso.stop()
            self._atualizar_estado_interface()

            if is_session_expired:
                self._sessao_expirada = True
                self._parar_agendamento(motivo="Sessão Expirada")
                self._atualizar_estado_interface()
                messagebox.showwarning(
                    "Sessão Expirada",
                    "A sessão do Lecom expirou ou foi redirecionada para SSO/Login.\n\n"
                    "A trigger automática foi pausada.\n"
                    "Clique no botão destacado 'Executar Visível' para logar e renovar o perfil.",
                )
            elif is_cancelled:
                self.on_log("Execução interrompida com sucesso.")
                if not self._acionado_por_trigger:
                    messagebox.showinfo("Interrompido", "A execução foi cancelada com sucesso.")
            elif success:
                if self._sessao_expirada:
                    self._sessao_expirada = False
                    self._atualizar_estado_interface()
                    self.on_log("Sessão revalidada com sucesso! Você pode reativar a trigger agora.")

                if not self._acionado_por_trigger:
                    messagebox.showinfo("Sucesso", message)
            else:
                if not self._acionado_por_trigger:
                    messagebox.showerror("Erro na Execução", message)

        self._root.after(0, _finalizar)


def main() -> None:
    root = tk.Tk()
    app = RpaApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
