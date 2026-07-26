"""Utilitários de paginação para endpoints de listagem."""

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")

_DEFAULT_PAGE_SIZE = 20
_MAX_PAGE_SIZE = 100


class PaginationParams(BaseModel):
    """Parâmetros de paginação recebidos via query string."""

    page: int = Field(default=1, ge=1, description="Número da página (inicia em 1)")
    page_size: int = Field(
        default=_DEFAULT_PAGE_SIZE,
        ge=1,
        le=_MAX_PAGE_SIZE,
        description="Itens por página",
    )

    @property
    def offset(self) -> int:
        """Calcula o offset SQL a partir da página e tamanho."""
        return (self.page - 1) * self.page_size


class Page(BaseModel, Generic[T]):
    """Resposta paginada genérica."""

    items: list[T]
    total: int = Field(description="Total de itens (sem paginação)")
    page: int
    page_size: int
    pages: int = Field(description="Total de páginas")

    @classmethod
    def create(cls, items: list[T], total: int, params: PaginationParams) -> "Page[T]":
        """Cria resposta paginada a partir de itens e parâmetros."""
        pages = max(1, (total + params.page_size - 1) // params.page_size)
        return cls(
            items=items,
            total=total,
            page=params.page,
            page_size=params.page_size,
            pages=pages,
        )
