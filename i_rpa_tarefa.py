"""Definição de modelo e entidade para tarefas de exportação do Lecom."""

from dataclasses import dataclass
from typing import Dict, Union

DictTarefa = Dict[str, Union[str, bool]]


@dataclass
class TarefaExportacao:
    """Entidade que representa um endpoint de pesquisa salva e seu arquivo de destino."""

    nome_pesquisa: str
    caminho_destino: str
    ativo: bool = True

    def to_dict(self) -> DictTarefa:
        return {
            "nome_pesquisa": self.nome_pesquisa,
            "caminho_destino": self.caminho_destino,
            "ativo": self.ativo,
        }

    @classmethod
    def from_dict(cls, data: DictTarefa) -> "TarefaExportacao":
        return cls(
            nome_pesquisa=str(data.get("nome_pesquisa", "")),
            caminho_destino=str(data.get("caminho_destino", "")),
            ativo=bool(data.get("ativo", True)),
        )
