"""Contrato de Repositório para Persistência do RPA Lecom.

Define a interface abstrata para armazenamento de tarefas e configurações
locais, garantindo inversão de dependência e desacoplamento de storage.
"""

from typing import Dict, List, Protocol
from i_rpa_tarefa import TarefaExportacao


class i_rpa_repositorio(Protocol):
    """Contrato abstrato de persistência para rotinas e configurações do RPA."""

    def inicializar(self) -> None:
        """Inicializa as tabelas ou estruturas de persistência caso não existam."""
        ...

    def listar_tarefas(self) -> List[TarefaExportacao]:
        """Recupera todas as tarefas de exportação salvas."""
        ...

    def salvar_tarefas(self, tarefas: List[TarefaExportacao]) -> None:
        """Persiste a lista completa de tarefas de exportação."""
        ...

    def obter_configuracao(self, chave: str, padrao: str = "") -> str:
        """Retorna o valor de uma configuração por chave ou o valor padrão."""
        ...

    def salvar_configuracao(self, chave: str, valor: str) -> None:
        """Salva ou atualiza um par chave/valor de configuração."""
        ...

    def obter_todas_configuracoes(self) -> Dict[str, str]:
        """Retorna um dicionário com todas as configurações persistidas."""
        ...
