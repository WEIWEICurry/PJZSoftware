"""Same-origin loopback API; bootstrap is not a user password."""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from pjz.account_deletion import AccountDeletion
from pjz.accounting import Accounting
from pjz.budgets import Budgets
from pjz.daily_api import router
from pjz.domain import RuleError
from pjz.history import HistoryImports
from pjz.history_api import history_router
from pjz.report_api import report_router
from pjz.reports import Reports
from pjz.storage import MAX_PACKAGE, SCHEMA_VERSION, DataError, LedgerStore


class BodyLimit:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD"):
            await self.app(scope, receive, send)
            return
        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > MAX_PACKAGE:
                response = JSONResponse(
                    {"error": {"code": "REQUEST_TOO_LARGE", "message": "REQUEST_TOO_LARGE"}},
                    status_code=413,
                )
                await response(scope, receive, send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


class LedgerOutput(BaseModel):
    id: str
    name: str
    revision: int
    created_at: str
    directory: str
    schema_version: int
    encrypted: bool
    stage: str


class BootstrapInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=20, max_length=128)


class RenameInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=60, pattern=r"\S")
    revision: int = Field(ge=1, strict=True)


class RestoreInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_token: str = Field(min_length=20, max_length=128)


class Session:
    def __init__(self) -> None:
        self.bootstrap = secrets.token_urlsafe(32)
        self.expires = time.monotonic() + 120
        self.cookie = secrets.token_urlsafe(32)
        self.csrf = secrets.token_urlsafe(32)
        self.lock = threading.Lock()

    def issue_bootstrap(self) -> str:
        with self.lock:
            self.bootstrap = secrets.token_urlsafe(32)
            self.expires = time.monotonic() + 120
            return self.bootstrap

    def exchange(self, token: str) -> bool:
        with self.lock:
            if not self.bootstrap or time.monotonic() > self.expires:
                return False
            if not secrets.compare_digest(token, self.bootstrap):
                return False
            self.bootstrap = ""
            return True


def create_app(
    store: LedgerStore,
    origin: str,
    assets: Path | None = None,
    shutdown: Callable[[], None] | None = None,
) -> FastAPI:
    app = FastAPI(
        title="PJZSoftware",
        version="0.6.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        telemetry={
            "tracing": False,
            "metrics": False,
            "logs": False,
            "operation_spans": False,
            "auto_configure": False,
        },
    )
    inline_hashes: set[str] = set()
    if assets:
        for html in assets.rglob("*.html"):
            for script in re.findall(
                r"<script[^>]*>(.*?)</script>", html.read_text(encoding="utf-8"), re.S
            ):
                if script:
                    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
                    inline_hashes.add("'sha256-" + digest + "'")
    script_policy = "script-src 'self' " + " ".join(sorted(inline_hashes)) + "; "
    session = Session()
    app.state.session = session
    previews: dict[str, tuple[bytes, int, float]] = {}
    mutation_lock = threading.Lock()

    def failure(code: str, status: int) -> JSONResponse:
        return JSONResponse({"error": {"code": code, "message": code}}, status_code=status)

    @app.middleware("http")
    async def security(request: Request, call_next: Any) -> Response:
        if request.headers.get("host") != origin.removeprefix("http://"):
            return failure("INVALID_HOST", 403)
        if request.headers.get("origin") not in (None, origin):
            return failure("INVALID_ORIGIN", 403)
        path = request.url.path
        write = request.method not in ("GET", "HEAD")
        if write:
            if request.headers.get("origin") != origin:
                return failure("INVALID_ORIGIN", 403)
            content_type = request.headers.get("content-type", "").split(";")[0]
            if content_type not in ("application/json", "multipart/form-data"):
                return failure("INVALID_CONTENT_TYPE", 415)
            try:
                if int(request.headers.get("content-length", "0")) > MAX_PACKAGE:
                    return failure("REQUEST_TOO_LARGE", 413)
            except ValueError:
                return failure("INVALID_LENGTH", 400)
        if path.startswith("/api/") and path != "/api/v1/session/bootstrap":
            if not secrets.compare_digest(request.cookies.get("pjz_session", ""), session.cookie):
                return failure("UNAUTHENTICATED", 401)
            if write and not secrets.compare_digest(
                request.headers.get("x-csrf-token", ""), session.csrf
            ):
                return failure("INVALID_CSRF", 403)
        response: Response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            + script_policy
            + "style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; "
            "font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
        return failure(str(error.detail), error.status_code)

    @app.exception_handler(RequestValidationError)
    async def input_error(request: Request, error: RequestValidationError) -> JSONResponse:
        return failure("INVALID_INPUT", 422)

    @app.exception_handler(DataError)
    async def data_error(request: Request, error: DataError) -> JSONResponse:
        code = str(error)
        return failure(code, 409 if code == "REVISION_CONFLICT" else 400)

    @app.exception_handler(RuleError)
    async def rule_error(request: Request, error: RuleError) -> JSONResponse:
        code = str(error)
        status = (
            409
            if code
            in ("REVISION_CONFLICT", "IDEMPOTENCY_CONFLICT", "RESOURCE_DELETED", "PREVIEW_EXPIRED")
            else 422
        )
        return failure(code, status)

    app.include_router(router(Accounting(store.engine), AccountDeletion(store)))
    app.include_router(history_router(HistoryImports(Accounting(store.engine))))
    app.include_router(
        report_router(Reports(Accounting(store.engine)), Budgets(Accounting(store.engine)))
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ready"}

    @app.post("/api/v1/session/bootstrap")
    def bootstrap(body: BootstrapInput, response: Response) -> dict[str, str]:
        if not session.exchange(body.token):
            raise HTTPException(401, "INVALID_BOOTSTRAP")
        response.set_cookie("pjz_session", session.cookie, httponly=True, samesite="strict")
        return {"csrf_token": session.csrf}

    @app.get("/api/v1/session")
    def current_session() -> dict[str, str]:
        return {"csrf_token": session.csrf}

    @app.get("/api/v1/ledger", response_model=LedgerOutput)
    def ledger() -> dict[str, Any]:
        return {
            **store.metadata(),
            "directory": str(store.directory),
            "schema_version": SCHEMA_VERSION,
            "encrypted": False,
            "stage": "M2",
        }

    @app.put("/api/v1/ledger")
    def rename(body: RenameInput) -> dict[str, Any]:
        with mutation_lock:
            return store.rename(body.name.strip(), body.revision)

    @app.post("/api/v1/backups")
    def backup() -> Response:
        with mutation_lock:
            payload = store.backup()
        return Response(
            payload,
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="ledger.pjzbackup"'},
        )

    @app.post("/api/v1/restores/preview")
    async def preview(file: Annotated[UploadFile, File()]) -> dict[str, Any]:
        from pjz.storage import inspect_backup

        payload = await file.read(MAX_PACKAGE + 1)
        await file.close()
        inspect_backup(payload)
        token = secrets.token_urlsafe(32)
        with mutation_lock:
            previews.clear()
            previews[token] = (payload, store.metadata()["revision"], time.monotonic() + 120)
        return {
            "preview_token": token,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "message": "将在新目录恢复，当前账本保持不变；确认后先备份当前账本。",
        }

    @app.post("/api/v1/restores/commit")
    def restore(body: RestoreInput) -> dict[str, str]:
        with mutation_lock:
            item = previews.pop(body.preview_token, None)
            if item is None or item[2] < time.monotonic():
                raise HTTPException(409, "PREVIEW_EXPIRED")
            if item[1] != store.metadata()["revision"]:
                raise HTTPException(409, "REVISION_CONFLICT")
            destination = store.restore(item[0])
        return {"directory": str(destination), "message": "已验证并恢复至新目录；未切换当前账本。"}

    @app.post("/api/v1/shutdown")
    def stop() -> dict[str, bool]:
        if shutdown:
            shutdown()
        return {"stopping": True}

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception) -> JSONResponse:
        return failure("INTERNAL_ERROR", 500)

    app.add_middleware(BodyLimit)
    if assets is not None:
        app.mount("/", StaticFiles(directory=assets, html=True), name="frontend")
    return app
