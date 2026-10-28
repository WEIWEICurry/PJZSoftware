"""Investment period reports and bounded formula-safe CSV, each on one DB snapshot."""

from __future__ import annotations

import csv
import io
from datetime import date
from typing import Any

from sqlalchemy import Connection, text

from pjz.accounting import Accounting
from pjz.domain import RuleError
from pjz.investment_report_domain import (
    ACTION_LABELS,
    KIND_LABELS,
    current_allocation,
    investment_bounds,
    period_totals,
)
from pjz.investments import Investments

MAX_EXPORT_ROWS = 50000
METRIC_KEYS = (
    "buy_outflow_fen",
    "sell_inflow_fen",
    "realized_fen",
    "cash_dividends_fen",
    "reinvested_dividends_fen",
    "fees_fen",
    "cash_delta_fen",
    "realized_and_dividends_fen",
)
METRIC_LABELS = (
    "买入实际扣款",
    "卖出净到账",
    "已实现卖出盈亏",
    "现金净分红",
    "再投净分红",
    "已计入费用",
    "相关现金净变动",
    "已实现与分红合计（不含浮动）",
)


def safe_text(value: str) -> str:
    return (
        "'" + value
        if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n"))
        else value
    )


def yuan(value: str | int | None) -> str:
    if value is None:
        return ""
    integer = int(value)
    return (
        ("-" if integer < 0 else "")
        + str(abs(integer) // 100)
        + "."
        + str(abs(integer) % 100).zfill(2)
    )


class InvestmentReports:
    def __init__(self, accounting: Accounting) -> None:
        self.accounting = accounting
        self.investments = Investments(accounting)

    def load(self, connection: Connection, query: dict[str, Any]) -> dict[str, Any]:
        today = date.today()
        first, last, requested_end = investment_bounds(
            query["period"], query["anchor"], query.get("start"), query.get("end"), today
        )
        positions, _, effects = self.investments.replay_details(connection)
        snapshot = self.investments.snapshot(connection, positions)
        accounts = {a["id"]: a for a in self.accounting.account_rows(connection)}
        assets = {i["id"]: i for i in snapshot["instruments"]}
        account_id, instrument_id, kind = (
            query.get(k) for k in ("account_id", "instrument_id", "kind")
        )
        if account_id and (
            account_id not in accounts
            or accounts[account_id]["kind"] in ("liability", "receivable")
        ):
            raise RuleError("INVESTMENT_REPORT_INVALID_FILTER")
        if instrument_id and instrument_id not in assets:
            raise RuleError("INVESTMENT_REPORT_INVALID_FILTER")

        def matches(row: dict[str, Any]) -> bool:
            return (
                (not account_id or row["account_id"] == account_id)
                and (not instrument_id or row["instrument_id"] == instrument_id)
                and (not kind or assets[row["instrument_id"]]["kind"] == kind)
            )

        rows = []
        for raw in snapshot["trades"]:
            if (
                not matches(raw)
                or not first.isoformat() <= raw["effective_date"] <= last.isoformat()
            ):
                continue
            asset = assets[raw["instrument_id"]]
            effect = effects.get(raw["id"], {})
            cash_account = (
                effect.get("cash_account_id") or raw.get("cash_account_id") or raw["account_id"]
            )
            rows.append(
                {
                    **raw,
                    "account_name": accounts[raw["account_id"]]["name"],
                    "instrument_name": asset["name"],
                    "market": asset["market"],
                    "code": asset["code"],
                    "kind": asset["kind"],
                    "cash_account_id": cash_account,
                    "cash_account_name": accounts[cash_account]["name"],
                    "cash_delta_fen": effect.get("cash_delta_fen"),
                    "allocated_cost_fen": effect.get("allocated_cost_fen"),
                    "realized_fen": effect.get("realized_fen"),
                }
            )
        active = [r for r in rows if r["status"] == "active"]
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in active:
            groups.setdefault(row["instrument_id"], []).append(row)
        contributions = [
            {
                "instrument_id": identifier,
                "instrument_name": assets[identifier]["name"],
                "market": assets[identifier]["market"],
                "code": assets[identifier]["code"],
                "kind": assets[identifier]["kind"],
                **period_totals(items),
            }
            for identifier, items in groups.items()
        ]
        contributions.sort(
            key=lambda r: (-int(r["realized_and_dividends_fen"]), r["market"], r["code"])
        )
        current = [p for p in snapshot["positions"] if p["quantity"] != "0" and matches(p)]
        groups_now = current_allocation(
            current,
            accounts,
            assets,
            int(snapshot["known_value_fen"]),
            snapshot["missing_price_count"] == 0,
        )
        allowed = {
            t["instrument_id"]
            for t in snapshot["trades"]
            if not account_id or t["account_id"] == account_id
        }
        valuations = [
            v
            for v in snapshot["valuations"]
            if (not account_id or v["instrument_id"] in allowed)
            and (not instrument_id or v["instrument_id"] == instrument_id)
            and (not kind or assets[v["instrument_id"]]["kind"] == kind)
            and first.isoformat() <= v["price_date"] <= last.isoformat()
        ]
        return {
            "period": query["period"],
            "start": first.isoformat(),
            "end": last.isoformat(),
            "requested_end": requested_end.isoformat(),
            "ledger_revision": connection.execute(text("SELECT revision FROM ledger")).scalar_one(),
            "totals": period_totals(active),
            "contributions": contributions,
            "current_allocation": {
                "as_of_date": today.isoformat(),
                "total_value_fen": None
                if snapshot["missing_price_count"]
                else snapshot["known_value_fen"],
                "known_value_fen": snapshot["known_value_fen"],
                "missing_price_count": snapshot["missing_price_count"],
                "selected_position_count": len(current),
                "groups": groups_now,
            },
            "accounts": [
                a for a in accounts.values() if a["kind"] not in ("liability", "receivable")
            ],
            "instruments": list(assets.values()),
            "_rows": rows,
            "_positions": current,
            "_valuations": valuations,
            "_accounts": accounts,
            "_assets": assets,
        }

    def get(
        self, query: dict[str, Any], offset: int = 0, include_void: bool = False
    ) -> dict[str, Any]:
        with self.accounting.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN")
            result = self.load(connection, query)
            rows = (
                result["_rows"]
                if include_void
                else [r for r in result["_rows"] if r["status"] == "active"]
            )
            return {
                **{k: v for k, v in result.items() if not k.startswith("_")},
                "entries": {"items": rows[offset : offset + 20], "total": len(rows)},
            }

    def export(self, dataset: str, query: dict[str, Any], include_void: bool) -> bytes:
        with self.accounting.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN")
            result = self.load(connection, query)
        accounts, assets = result["_accounts"], result["_assets"]
        scope = [
            str(result["ledger_revision"]),
            result["start"],
            result["end"],
            query.get("account_id") or "",
            query.get("instrument_id") or "",
            query.get("kind") or "",
        ]
        headers = ["账本版本", "报表开始", "实际截止", "筛选持仓账户ID", "筛选标的ID", "筛选类型"]
        rows: list[list[Any]] = []
        if dataset == "report":
            headers += (
                ["行类型", "标的ID", "市场", "代码", "标的名称", "有效记录数"]
                + [name + "（元）" for name in METRIC_LABELS]
                + [name + "（分）" for name in METRIC_LABELS]
            )
            for item in [
                {
                    "instrument_id": "",
                    "market": "",
                    "code": "",
                    "instrument_name": "全部所选有效事件",
                    **result["totals"],
                },
                *result["contributions"],
            ]:
                rows.append(
                    [
                        *scope,
                        "期间汇总" if not item["instrument_id"] else "标的构成",
                        item["instrument_id"],
                        item["market"],
                        item["code"],
                        safe_text(item["instrument_name"]),
                        item["record_count"],
                        *[yuan(item[k]) for k in METRIC_KEYS],
                        *[item[k] for k in METRIC_KEYS],
                    ]
                )
        elif dataset == "trades":
            headers += [
                "记录ID",
                "修订",
                "状态",
                "日期",
                "同日顺序",
                "操作",
                "持仓账户ID",
                "持仓账户",
                "标的ID",
                "市场",
                "代码",
                "标的名称",
                "份额",
                "折算前份额",
                "成交或净分红（元）",
                "费用（元）",
                "期初成本（元）",
                "现金账户ID",
                "现金账户",
                "实际现金变动（元）",
                "分摊成本（元）",
                "已实现卖出盈亏（元）",
                "备注",
                "成交或净分红（分）",
                "费用（分）",
                "现金变动（分）",
                "分摊成本（分）",
                "已实现盈亏（分）",
                "期初成本（分）",
                "期初成本状态",
            ]
            for r in result["_rows"]:
                if not include_void and r["status"] == "void":
                    continue
                rows.append(
                    [
                        *scope,
                        r["id"],
                        r["revision"],
                        "有效" if r["status"] == "active" else "已作废（不计入）",
                        r["effective_date"],
                        r["sequence"],
                        ACTION_LABELS[r["action"]],
                        r["account_id"],
                        safe_text(r["account_name"]),
                        r["instrument_id"],
                        r["market"],
                        r["code"],
                        safe_text(r["instrument_name"]),
                        r["quantity"],
                        r["split_from_quantity"] or "",
                        yuan(r["gross_fen"]),
                        yuan(r["costs_fen"]),
                        yuan(r["cost_basis_fen"]),
                        r["cash_account_id"],
                        safe_text(r["cash_account_name"]),
                        yuan(r["cash_delta_fen"]),
                        yuan(r["allocated_cost_fen"]),
                        yuan(r["realized_fen"]),
                        safe_text(r["note"]),
                        r["gross_fen"],
                        r["costs_fen"],
                        r["cash_delta_fen"],
                        r["allocated_cost_fen"],
                        r["realized_fen"],
                        r["cost_basis_fen"],
                        ("成本待补" if r["cost_basis_fen"] is None else "已知")
                        if r["action"] == "opening"
                        else "不适用",
                    ]
                )
        elif dataset == "positions":
            headers += [
                "持仓日期（非历史快照）",
                "持仓账户ID",
                "持仓账户",
                "标的ID",
                "市场",
                "代码",
                "标的名称",
                "类型",
                "份额",
                "剩余成本（元）",
                "市值（元）",
                "累计已实现卖出盈亏（元）",
                "累计现金分红（元）",
                "累计再投分红（元）",
                "持仓盈亏（元）",
                "占比基点",
                "手动价格",
                "价格日期",
                "估值状态",
                "成本状态",
                "事件后价格门槛",
                "剩余成本（分）",
                "市值（分）",
                "累计已实现卖出盈亏（分）",
                "累计现金分红（分）",
                "累计再投分红（分）",
                "持仓盈亏（分）",
                "持仓占比（%）",
                "占比状态",
            ]
            for p in result["_positions"]:
                a = assets[p["instrument_id"]]
                rows.append(
                    [
                        *scope,
                        result["current_allocation"]["as_of_date"],
                        p["account_id"],
                        safe_text(accounts[p["account_id"]]["name"]),
                        a["id"],
                        a["market"],
                        a["code"],
                        safe_text(a["name"]),
                        KIND_LABELS[a["kind"]],
                        p["quantity"],
                        yuan(p["cost_fen"]),
                        yuan(p["value_fen"]),
                        yuan(p["realized_fen"]),
                        yuan(p["cash_dividends_fen"]),
                        yuan(p["reinvested_dividends_fen"]),
                        yuan(p["unrealized_fen"]),
                        p["share_bps"],
                        p["price"],
                        p["price_date"],
                        "待估值" if p["value_fen"] is None else "已估值",
                        "成本待补" if p["cost_fen"] is None else "已知",
                        p["valuation_required_from"],
                        p["cost_fen"],
                        p["value_fen"],
                        p["realized_fen"],
                        p["cash_dividends_fen"],
                        p["reinvested_dividends_fen"],
                        p["unrealized_fen"],
                        "" if p["share_bps"] is None else yuan(p["share_bps"]) + "%",
                        "总市值待估值"
                        if result["current_allocation"]["missing_price_count"]
                        else "总市值为零"
                        if result["current_allocation"]["total_value_fen"] == "0"
                        else "已知",
                    ]
                )
        elif dataset == "valuations":
            headers += [
                "估值ID",
                "修订",
                "状态",
                "标的ID",
                "市场",
                "代码",
                "标的名称",
                "类型",
                "价格日期",
                "价格（元／份或股）",
                "来源",
                "创建时间",
                "更新时间",
            ]
            for v in result["_valuations"]:
                a = assets[v["instrument_id"]]
                rows.append(
                    [
                        *scope,
                        v["id"],
                        v["revision"],
                        "有效" if v["status"] == "active" else "已作废",
                        a["id"],
                        a["market"],
                        a["code"],
                        safe_text(a["name"]),
                        KIND_LABELS[a["kind"]],
                        v["price_date"],
                        v["price"],
                        "手动",
                        v["created_at"],
                        v["updated_at"],
                    ]
                )
        else:
            raise RuleError("INVESTMENT_REPORT_INVALID_EXPORT")
        if len(rows) > MAX_EXPORT_ROWS:
            raise RuleError("REPORT_EXPORT_TOO_LARGE")
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(headers)
        writer.writerows(rows)
        return output.getvalue().encode("utf-8-sig")
