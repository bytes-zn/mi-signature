"""Application-wide exception hierarchy.

Business logic raises subclasses of :class:`AppError`; the API layer maps
them to structured JSON error responses via a central exception handler.
"""


class AppError(Exception):
    """Base class for all expected application errors."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str | None = None, *, code: str | None = None) -> None:
        self.message = message or "An unexpected error occurred."
        if code is not None:
            self.code = code
        super().__init__(self.message)


class NotFoundError(AppError):
    """A requested resource does not exist."""

    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    """The request conflicts with existing state."""

    status_code = 409
    code = "conflict"


class ValidationError(AppError):
    """Domain-level validation failed (beyond schema validation)."""

    status_code = 422
    code = "validation_error"


class UnauthorizedError(AppError):
    """Authentication failed or credentials are missing."""

    status_code = 401
    code = "unauthorized"


class ForbiddenError(AppError):
    """The authenticated caller lacks permission for this action."""

    status_code = 403
    code = "forbidden"
