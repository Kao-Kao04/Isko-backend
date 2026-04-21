from fastapi import HTTPException, status


class AppException(HTTPException):
    def __init__(self, status_code: int, code: str, message: str, detail: str | None = None):
        super().__init__(status_code=status_code, detail={"code": code, "message": message, "detail": detail})


class NotFoundError(AppException):
    def __init__(self, resource: str, id: int | str | None = None):
        msg = f"{resource} not found" if id is None else f"{resource} with id {id} not found"
        super().__init__(404, "NOT_FOUND", msg)


class ForbiddenError(AppException):
    def __init__(self, message: str = "Access denied"):
        super().__init__(403, "FORBIDDEN", message)


class ConflictError(AppException):
    def __init__(self, message: str):
        super().__init__(409, "CONFLICT", message)


class ValidationError(AppException):
    def __init__(self, message: str, detail: str | None = None):
        super().__init__(422, "VALIDATION_ERROR", message, detail)


class UnauthorizedError(AppException):
    def __init__(self, message: str = "Not authenticated"):
        super().__init__(401, "UNAUTHORIZED", message)
