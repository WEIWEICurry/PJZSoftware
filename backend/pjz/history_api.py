"""Versioned local-only historical import API; uploaded JSON never selects filesystem paths."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel, Field, field_validator

from pjz.daily_api import Key, StrictInput
from pjz.domain import RuleError
from pjz.history import HistoryImports
from pjz.history_domain import MAX_SOURCE, unique_object


class HistoryRow(BaseModel):
    mapping_key: str
    source_category: str
    category_id: str | None
    category_name: str
    period_start: str
    period_end: str
    direction: Literal["income", "expense"]
    amount_fen: str
    source_refs: list[str]
    status: Literal["ready", "unmapped", "duplicate", "conflict"]
    detail_count: int
    detail_fen: str
    report_delta_fen: str


class HistoryPreview(BaseModel):
    preview_token: str
    action: Literal["import", "withdraw"]
    filename: str
    file_hash: str
    canonical_hash: str
    can_confirm: bool
    rows: list[HistoryRow]


class BatchOutput(BaseModel):
    id: str
    filename: str
    file_hash: str
    canonical_hash: str
    status: Literal["active", "withdrawn"]
    revision: int
    created_at: str


class BatchDetail(BatchOutput):
    rows: list[HistoryRow]


class ImportCommit(StrictInput):
    preview_token: str = Field(min_length=20, max_length=128)
    acknowledge_coverage: bool = Field(strict=True)

    @field_validator("acknowledge_coverage")
    @classmethod
    def acknowledged(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Coverage confirmation required")
        return value


class ImportResult(BaseModel):
    id: str
    status: Literal["active", "withdrawn"]


def history_router(service: HistoryImports) -> APIRouter:
    router = APIRouter(prefix="/api/v1/history")

    @router.post("/preview", response_model=HistoryPreview)
    async def preview(
        file: Annotated[UploadFile, File()], mapping: Annotated[str, Form()] = "{}"
    ) -> dict[str, Any]:
        try:
            payload = await file.read(MAX_SOURCE + 1)
            filename = file.filename or "summary.json"
        finally:
            await file.close()
        try:
            parsed = json.loads(mapping, object_pairs_hook=unique_object)
            if (
                not isinstance(parsed, dict)
                or len(parsed) > 500
                or any(
                    not isinstance(k, str) or not isinstance(v, str) or len(k) > 100 or len(v) > 100
                    for k, v in parsed.items()
                )
            ):
                raise ValueError("Invalid mapping")
        except (ValueError, TypeError, RecursionError) as error:
            raise RuleError("HISTORY_INVALID_MAPPING") from error
        return service.preview(payload, filename, parsed)

    @router.post("/commit", response_model=ImportResult)
    def commit(body: ImportCommit, key: Key) -> dict[str, Any]:
        return service.commit(body.preview_token, key)

    @router.get("/batches", response_model=list[BatchOutput])
    def batches() -> list[dict[str, Any]]:
        return service.batches()

    @router.get("/batches/{identifier}", response_model=BatchDetail)
    def detail(identifier: UUID) -> dict[str, Any]:
        return service.detail(str(identifier))

    @router.post("/batches/{identifier}/withdraw-preview", response_model=HistoryPreview)
    def withdrawal_preview(identifier: UUID) -> dict[str, Any]:
        return service.withdrawal_preview(str(identifier))

    return router
