"""Páginas públicas exigidas pelas redes (Termos, Privacidade, Exclusão de dados)."""
from __future__ import annotations

from fastapi import APIRouter

from .comum import *  # noqa: F401,F403

router = APIRouter()


@router.get("/termos")
@router.get("/termos-de-uso")
@router.get("/terms")
def pagina_termos(request: Request):
    return _pagina_legal("termos", request)


@router.get("/privacidade")
@router.get("/politica-de-privacidade")
@router.get("/privacy")
def pagina_privacidade(request: Request):
    return _pagina_legal("privacidade", request)


@router.get("/exclusao-de-dados")
@router.get("/data-deletion")
def pagina_exclusao(request: Request):
    return _pagina_legal("exclusao-de-dados", request)
