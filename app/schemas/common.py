from pydantic import BaseModel, model_validator
from typing import Generic, TypeVar, List

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    page_size: int
    pages: int
    total_pages: int = 0  # alias populated by validator

    @model_validator(mode='after')
    def _set_total_pages(self) -> 'PaginatedResponse':
        self.total_pages = self.pages
        return self


class ErrorResponse(BaseModel):
    code: str
    message: str
    detail: str | None = None
