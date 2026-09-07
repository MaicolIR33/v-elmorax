from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import get_settings
from app.core.database import init_db, seed_db
from app.core.observability import RequestObservabilityMiddleware, configure_logging, logger
from app.routers.web import router as web_router


settings = get_settings()
settings.validate_production()
configure_logging(settings.log_level)

app = FastAPI(
    title=settings.app_name,
    description=settings.app_description,
    version=settings.app_version,
)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    max_age=settings.session_max_age_seconds,
    same_site="lax",
    https_only=settings.session_https_only,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
app.add_middleware(RequestObservabilityMiddleware)


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, error: Exception) -> HTMLResponse:
    logger.error(
        "Unhandled request error",
        exc_info=(type(error), error, error.__traceback__),
        extra={
            "event": "request_error",
            "request_id": getattr(request.state, "request_id", "unknown"),
            "method": request.method,
            "path": request.url.path,
        },
    )
    return HTMLResponse(
        "<h1>No pudimos completar la operación</h1>"
        "<p>Inténtalo nuevamente. Si continúa, informa a soporte.</p>",
        status_code=500,
        headers={"Cache-Control": "no-store"},
    )


@app.on_event("startup")
def startup() -> None:
    if settings.initialize_database:
        init_db()
        if settings.seed_demo_data:
            seed_db()
    logger.info("Application ready", extra={"event": "application_ready"})


app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(web_router)
