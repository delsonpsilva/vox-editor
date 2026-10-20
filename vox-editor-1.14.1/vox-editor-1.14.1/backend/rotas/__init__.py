"""Rotas da API do VOX Editor, separadas por área (v1.8). A ordem de ROTEADORES é a ordem de registro."""
from . import edicao, exportacao, historia, legal, marca, montagem, projetos, publicacao, resumo, sistema

ROTEADORES = [sistema.router, projetos.router, edicao.router, marca.router, publicacao.router,
              exportacao.router, montagem.router, historia.router, resumo.router, legal.router]
