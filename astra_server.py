"""ASTRA API entry point.

Run with: uvicorn astra_server:app --reload
"""

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config import STATIC_DIR, logger
from routes.chat import router as chat_router
from routes.space_data import router as space_data_router

app = FastAPI(
    title="ASTRA Space Situational Intelligence API",
    version="0.1.0",
    description="Receives natural-language space queries for later watsonx processing.",
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Guarantee JSON responses even for bugs we didn't anticipate.

    Without this, an uncaught exception falls through to Starlette's default
    handler, which returns a *plain text* 500 response — that breaks any
    frontend doing `await response.json()`.
    """
    logger.exception("Unhandled error while processing %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected internal error occurred in the ASTRA server."},
    )


app.include_router(chat_router)
app.include_router(space_data_router)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("static/favicon.svg", media_type="image/svg+xml")


# Keep this last: API routes must be evaluated before the catch-all static mount.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
