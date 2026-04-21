from typing import Generic, TypeVar, List
from pydantic import BaseModel

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    page_size: int
    pages: int


def paginate(query_result: List[T], total: int, page: int, page_size: int) -> PaginatedResponse[T]:
    pages = (total + page_size - 1) // page_size if page_size else 1
    return PaginatedResponse(items=query_result, total=total, page=page, page_size=page_size, pages=pages)
