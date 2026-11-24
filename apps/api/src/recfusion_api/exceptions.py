from recfusion_api.schemas.errors import ErrorCode


class ApplicationError(Exception):
    def __init__(self, *, code: ErrorCode, message: str, status_code: int) -> None:
        super().__init__(message)
        if not 400 <= status_code <= 599:
            raise ValueError("Application errors must use an HTTP error status.")
        self.code = code
        self.message = message
        self.status_code = status_code
