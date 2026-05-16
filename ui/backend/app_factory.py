from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from ui.backend.core.migrations import bootstrap_master_user, run_migrations
from ui.backend.core import config
from ui.backend.routes import ai_services, assets, auth, chats, datasources, files, secrets, templates, tenants, user_profiles, users


def create_app() -> FastAPI:
    app = FastAPI(title="Agent UI Backend", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_static_no_cache_headers(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return response

    @app.on_event("startup")
    def on_startup() -> None:
        run_migrations()
        bootstrap_master_user()

    app.include_router(auth.router)
    app.include_router(tenants.router)
    app.include_router(users.router)
    app.include_router(user_profiles.router)
    app.include_router(chats.router)
    app.include_router(templates.router)
    app.include_router(ai_services.router)
    app.include_router(datasources.router)
    app.include_router(files.router)
    app.include_router(secrets.router)
    app.include_router(assets.router)
    static_dir = config.FRONTEND_DIR / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")
    return app
