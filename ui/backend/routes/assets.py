from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ui.backend.core import config

router = APIRouter()


def get_index_file() -> FileResponse:
    index_file = config.FRONTEND_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Frontend nao encontrado")
    return FileResponse(index_file, headers={"Cache-Control": "no-store, no-cache, must-revalidate"})


@router.get("/")
def serve_ui_root():
    return get_index_file()


@router.get("/styles.css")
def serve_ui_styles():
    return FileResponse(
        config.FRONTEND_DIR / "styles.css",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@router.get("/app.js")
def serve_ui_script():
    return FileResponse(
        config.FRONTEND_DIR / "app.js",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )
