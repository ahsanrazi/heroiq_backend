import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


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

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        """Catch-all so an unexpected error returns a consistent JSON envelope
        with a 500 instead of FastAPI's default. HeroIQException (incl. the 503
        ServiceUnavailableError) is matched by the more specific handler above;
        FastAPI's HTTPException keeps its own handler. Sentry (if configured)
        captures via its ASGI integration; we also log the full traceback."""
        logger.exception(f"Unhandled error on {request.method} {request.url.path}: {exc}")
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."}},
        )
