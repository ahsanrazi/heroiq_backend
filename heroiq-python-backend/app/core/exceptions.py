from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class HeroIQException(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code


class ServiceUnavailableError(HeroIQException):
    def __init__(self, service: str):
        super().__init__(
            code="SERVICE_UNAVAILABLE",
            message=f"{service} is temporarily unavailable.",
            status_code=503,
        )


def register_exception_handlers(app: FastAPI):
    @app.exception_handler(HeroIQException)
    async def heroiq_exception_handler(request: Request, exc: HeroIQException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )
