"""Explicit opt-in public NAV preview and atomic non-overwriting import."""

import json
import secrets
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from pjz.accounting import Accounting, fetch_all, now
from pjz.daily_api import Key, StrictInput
from pjz.domain import RuleError
from pjz.investment_domain import decimal_text, decimal_value

SOURCE = "天天基金公开历史净值"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: Any, msg: Any, headers: Any, newurl: Any
    ) -> None:
        return None


def read_response(request: urllib.request.Request) -> bytes:
    for attempt in range(2):
        try:
            with urllib.request.build_opener(NoRedirect).open(request, timeout=10) as response:
                return bytes(response.read(1000001))
        except urllib.error.HTTPError as error:
            if attempt == 0 and (error.code in (403, 429) or error.code >= 500):
                continue
            raise RuleError("NAV_SOURCE_HTTP_ERROR") from error
        except (ssl.SSLError, urllib.error.URLError, OSError) as error:
            reason = getattr(error, "reason", error)
            if isinstance(reason, ssl.SSLError):
                raise RuleError("NAV_TLS_ERROR") from error
            if attempt == 0:
                continue
            code = "NAV_TIMEOUT" if isinstance(reason, TimeoutError) else "NAV_CONNECTION_ERROR"
            raise RuleError(code) from error
    raise RuleError("NAV_CONNECTION_ERROR")


def fetch_nav(code: str, start: date, end: date) -> list[dict[str, str]]:
    try:
        rows = []
        for page in range(1, 20):
            query = urllib.parse.urlencode(
                {
                    "fundCode": code,
                    "pageIndex": page,
                    "pageSize": 20,
                    "startDate": start.isoformat(),
                    "endDate": end.isoformat(),
                }
            )
            request = urllib.request.Request(
                "https://api.fund.eastmoney.com/f10/lsjz?" + query,
                headers={"Referer": "https://fundf10.eastmoney.com/", "User-Agent": "Mozilla/5.0"},
            )
            raw = read_response(request)
            if len(raw) > 1000000:
                raise ValueError("size")
            obj = json.loads(raw, parse_float=str)
            total = int(obj["TotalCount"])
            if obj["ErrCode"] != 0 or not 0 <= total <= 366:
                raise ValueError("shape")
            chunk = obj["Data"]["LSJZList"] if obj["Data"] is not None else []
            if not isinstance(chunk, list) or len(chunk) > 100:
                raise ValueError("shape")
            rows.extend(chunk)
            if len(rows) == total:
                break
            if not chunk or len(rows) > total:
                raise ValueError("truncated")
        if len(rows) != total:
            raise ValueError("truncated")
        result = []
        seen = set()
        for row in rows:
            day = date.fromisoformat(row["FSRQ"])
            if not start <= day <= end or day in seen:
                raise ValueError("date")
            seen.add(day)
            result.append(
                {
                    "price_date": day.isoformat(),
                    "price": decimal_text(decimal_value(str(row["DWJZ"]))),
                }
            )
        return sorted(result, key=lambda r: r["price_date"], reverse=True)
    except RuleError as error:
        if str(error).startswith("NAV_"):
            raise
        raise RuleError("NAV_SOURCE_UNAVAILABLE") from error
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise RuleError("NAV_SOURCE_UNAVAILABLE") from error


class NavQuery(StrictInput):
    instrument_id: uuid.UUID
    start: date
    end: date
    enabled: bool = False


class NavImport(StrictInput):
    token: str


class NavRow(BaseModel):
    price_date: str
    price: str
    exists: bool
    restore_void: bool = False


class NavPreview(BaseModel):
    token: str
    source: str
    fetched_at: str
    rows: list[NavRow]


class NavImported(BaseModel):
    imported: int
    skipped: int


def nav_router(accounting: Accounting) -> APIRouter:
    router = APIRouter(prefix="/api/v1/fund-nav")
    cache: dict[str, dict[str, Any]] = {}

    @router.post("/preview", response_model=NavPreview)
    def preview(payload: NavQuery) -> object:
        if not payload.enabled:
            raise RuleError("NAV_DISABLED")
        if (
            not payload.start <= payload.end <= date.today()
            or payload.end - payload.start > timedelta(days=365)
        ):
            raise RuleError("NAV_INVALID_RANGE")
        with accounting.engine.connect() as connection:
            assets = fetch_all(
                connection,
                "SELECT * FROM instruments WHERE id=:id",
                {"id": str(payload.instrument_id)},
            )
            if not assets or assets[0]["kind"] != "fund":
                raise RuleError("NAV_FUND_ONLY")
        rows = fetch_nav(assets[0]["code"], payload.start, payload.end)
        stamp = now()
        for token in list(cache):
            if cache[token]["expires"] < time.monotonic():
                del cache[token]
        if len(cache) >= 10:
            del cache[next(iter(cache))]
        token = secrets.token_urlsafe(32)
        with accounting.engine.connect() as connection:
            existing = {
                r["price_date"]: r
                for r in fetch_all(
                    connection,
                    "SELECT * FROM valuations WHERE instrument_id=:id",
                    {"id": str(payload.instrument_id)},
                )
            }
        cache[token] = {
            "rows": rows,
            "existing": existing,
            "instrument_id": str(payload.instrument_id),
            "fetched_at": stamp,
            "expires": time.monotonic() + 300,
        }
        return {
            "token": token,
            "source": SOURCE,
            "fetched_at": stamp,
            "rows": [
                {
                    **r,
                    "exists": existing.get(r["price_date"], {}).get("status") == "active",
                    "restore_void": existing.get(r["price_date"], {}).get("status") == "void",
                }
                for r in rows
            ],
        }

    @router.post("/import", response_model=NavImported)
    def import_nav(payload: NavImport, key: Key) -> object:
        def action(connection: Any) -> dict[str, Any]:
            item = cache.get(payload.token)
            if item is None or item["expires"] < time.monotonic():
                raise RuleError("NAV_PREVIEW_EXPIRED")
            imported = 0
            for row in item["rows"]:
                found = fetch_all(
                    connection,
                    "SELECT * FROM valuations WHERE instrument_id=:id AND price_date=:day",
                    {"id": item["instrument_id"], "day": row["price_date"]},
                )
                before = found[0] if found else None
                expected = item["existing"].get(row["price_date"])
                if before and before["status"] == "active":
                    continue
                if expected and expected["status"] == "active":
                    continue
                if (before is None) != (expected is None) or (
                    before
                    and expected
                    and (before["id"], before["revision"]) != (expected["id"], expected["revision"])
                ):
                    raise RuleError("NAV_PREVIEW_CHANGED")
                identifier = before["id"] if before else str(uuid.uuid4())
                revision = before["revision"] + 1 if before else 1
                values = {
                    "id": identifier,
                    "asset": item["instrument_id"],
                    "day": row["price_date"],
                    "price": row["price"],
                    "at": now(),
                    "revision": revision,
                }
                if before:
                    connection.execute(
                        text(
                            "UPDATE valuations SET price=:price,status='active',revision=:revision,"
                            "updated_at=:at WHERE id=:id"
                        ),
                        values,
                    )
                else:
                    connection.execute(
                        text(
                            "INSERT INTO valuations "
                            "(id,ledger_id,instrument_id,price_date,price,status,"
                            "created_at,updated_at) "
                            "VALUES (:id,(SELECT id FROM ledger),:asset,:day,:price,"
                            "'active',:at,:at)"
                        ),
                        values,
                    )
                accounting.audit(
                    connection,
                    identifier,
                    "import_public_nav",
                    before,
                    {
                        **row,
                        "source": SOURCE,
                        "fetched_at": item["fetched_at"],
                        "revision": revision,
                    },
                )
                imported += 1
            return {"imported": imported, "skipped": len(item["rows"]) - imported}

        return accounting.command(key, "import_public_nav", {"token": payload.token}, action)

    return router
