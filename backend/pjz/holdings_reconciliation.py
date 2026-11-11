"""Read-only holdings reconciliation against a consistent ledger snapshot."""

from typing import Any

from pjz.accounting import fetch_all
from pjz.domain import RuleError
from pjz.investments import Investments
from pjz.reconciliation_domain import compare_quantity, reference_value


def reconcile(service: Investments, payload: dict[str, Any]) -> dict[str, Any]:
    account, day = payload["account_id"], payload["as_of"]
    identifiers = [row["instrument_id"] for row in payload["rows"]]
    if len(set(identifiers)) != len(identifiers):
        raise RuleError("HOLDING_DUPLICATE_FUND")
    with service.accounting.engine.connect() as connection:
        connection.exec_driver_sql("BEGIN")
        accounts = fetch_all(connection, "SELECT kind FROM accounts WHERE id=:id", {"id": account})
        if not accounts or accounts[0]["kind"] in ("liability", "receivable"):
            raise RuleError("CASH_ACCOUNT_REQUIRED")
        snapshot = service.snapshot(connection, as_of=day)
        assets = {i["id"]: i for i in snapshot["instruments"]}
        positions = {
            p["instrument_id"]: p for p in snapshot["positions"] if p["account_id"] == account
        }
        output = []
        for row in payload["rows"]:
            asset = assets.get(row["instrument_id"])
            if not asset or asset["kind"] != "fund":
                raise RuleError("RECEIPT_FUND_REQUIRED")
            position = positions.get(asset["id"])
            local = position["quantity"] if position else "0"
            status, delta = compare_quantity(local, row["quantity"])
            reference = reference_value(local, row["unit_nav"]) if row["nav_date"] else None
            platform = row["amount_fen"]
            value_delta = (
                str(int(reference) - int(platform))
                if reference is not None and platform is not None
                else None
            )
            output.append(
                {
                    "instrument_id": asset["id"],
                    "name": asset["name"],
                    "code": asset["code"],
                    "platform_quantity": row["quantity"],
                    "local_quantity": local,
                    "quantity_status": status,
                    "quantity_delta": delta,
                    "platform_value_fen": platform,
                    "pending_fen": row["pending_fen"],
                    "unit_nav": row["unit_nav"],
                    "nav_date": row["nav_date"],
                    "reference_value_fen": reference,
                    "value_delta_fen": value_delta,
                    "local_value_fen": position["value_fen"] if position else "0",
                    "local_price": position["price"] if position else None,
                    "local_price_date": position["price_date"] if position else None,
                    "local_cost_fen": position["cost_fen"] if position else "0",
                    "same_price_date": bool(
                        position and row["nav_date"] and position["price_date"] == row["nav_date"]
                    ),
                }
            )
        return {
            "revision": connection.exec_driver_sql("SELECT revision FROM ledger").scalar_one(),
            "as_of": day,
            "account_id": account,
            "rows": output,
            "unprovided": [
                {"instrument_id": asset, "name": assets[asset]["name"], "quantity": pos["quantity"]}
                for asset, pos in positions.items()
                if asset not in identifiers and pos["quantity"] != "0"
            ],
        }
