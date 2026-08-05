from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import get_settings
from app.core.database import init_db, seed_db
from app.routers.web import router as web_router


settings = get_settings()

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


@app.on_event("startup")
def startup() -> None:
    init_db()
    seed_db()


app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(web_router)
