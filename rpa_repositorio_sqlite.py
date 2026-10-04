"""Implementação concreta de persistência local em SQLite para o RPA Lecom.

Gerencia o armazenamento transacional de rotinas de exportação e configurações
da aplicação através do banco embutido SQLite3.
"""

import sqlite3
from typing import Dict, List
from i_rpa_tarefa import TarefaExportacao


class RpaRepositorioSqlite:
    """Repositório transacional SQLite para tarefas e configurações."""

    def __init__(self, caminho_banco: str = "rpa_dados.db") -> None:
        self._caminho_banco: str = caminho_banco
        self.inicializar()

    def _obter_conexao(self) -> sqlite3.Connection:
        """Cria e retorna conexão com o banco SQLite."""
        return sqlite3.connect(self._caminho_banco)

    def inicializar(self) -> None:
        """Cria as tabelas caso ainda não existam no arquivo SQLite."""
        conn = self._obter_conexao()
        try:
            with conn:
                cursor: sqlite3.Cursor = conn.cursor()
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tarefas (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        nome_pesquisa TEXT NOT NULL,
                        caminho_destino TEXT NOT NULL,
                        ativo INTEGER NOT NULL DEFAULT 1
                    );
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS configuracoes (
                        chave TEXT PRIMARY KEY,
                        valor TEXT NOT NULL
                    );
                    """
                )
        finally:
            conn.close()

    def listar_tarefas(self) -> List[TarefaExportacao]:
        """Lê e retorna todas as rotinas salvas no banco de dados."""
        conn = self._obter_conexao()
        try:
            cursor: sqlite3.Cursor = conn.cursor()
            cursor.execute("SELECT nome_pesquisa, caminho_destino, ativo FROM tarefas ORDER BY id ASC")
            linhas = cursor.fetchall()
            return [
                TarefaExportacao(
                    nome_pesquisa=str(linha[0]),
                    caminho_destino=str(linha[1]),
                    ativo=bool(linha[2]),
                )
                for linha in linhas
            ]
        finally:
            conn.close()

    def salvar_tarefas(self, tarefas: List[TarefaExportacao]) -> None:
        """Substitui o conjunto de tarefas persistido pelo novo estado."""
        conn = self._obter_conexao()
        try:
            with conn:
                cursor: sqlite3.Cursor = conn.cursor()
                cursor.execute("DELETE FROM tarefas")
                for tarefa in tarefas:
                    cursor.execute(
                        "INSERT INTO tarefas (nome_pesquisa, caminho_destino, ativo) VALUES (?, ?, ?)",
                        (tarefa.nome_pesquisa, tarefa.caminho_destino, 1 if tarefa.ativo else 0),
                    )
        finally:
            conn.close()

    def obter_configuracao(self, chave: str, padrao: str = "") -> str:
        """Recupera valor de configuração associado à chave ou retorna o padrão."""
        conn = self._obter_conexao()
        try:
            cursor: sqlite3.Cursor = conn.cursor()
            cursor.execute("SELECT valor FROM configuracoes WHERE chave = ?", (chave,))
            resultado = cursor.fetchone()
            if resultado is not None:
                return str(resultado[0])
            return padrao
        finally:
            conn.close()

    def salvar_configuracao(self, chave: str, valor: str) -> None:
        """Insere ou atualiza um parâmetro de configuração."""
        conn = self._obter_conexao()
        try:
            with conn:
                cursor: sqlite3.Cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO configuracoes (chave, valor) VALUES (?, ?) ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
                    (chave, valor),
                )
        finally:
            conn.close()

    def obter_todas_configuracoes(self) -> Dict[str, str]:
        """Retorna todas as configurações como um dicionário chave/valor."""
        conn = self._obter_conexao()
        try:
            cursor: sqlite3.Cursor = conn.cursor()
            cursor.execute("SELECT chave, valor FROM configuracoes")
            linhas = cursor.fetchall()
            return {str(linha[0]): str(linha[1]) for linha in linhas}
        finally:
            conn.close()
