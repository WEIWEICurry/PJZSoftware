"""Pure integer accounting rules, independent from the database and web framework."""

from __future__ import annotations

from dataclasses import dataclass

MAX_FEN = 10**12


class RuleError(ValueError):
    pass


@dataclass(frozen=True)
class Entry:
    account_id: str
    delta_fen: int


def entries_for(
    kind: str,
    account: str,
    account_kind: str,
    amount: int,
    target: str | None = None,
    target_kind: str | None = None,
    fee: int = 0,
) -> list[Entry]:
    if kind == "opening":
        return [Entry(account, amount)]
    if kind == "adjustment":
        return [Entry(account, amount)]
    if account_kind == "receivable" and kind not in ("transfer", "adjustment"):
        raise RuleError("RECEIVABLE_EVENT_UNSUPPORTED")
    if kind == "income":
        if account_kind == "liability":
            raise RuleError("DEBT_INCOME_UNSUPPORTED")
        return [Entry(account, amount)]
    if kind == "expense":
        return [Entry(account, amount if account_kind == "liability" else -amount)]
    if kind == "refund":
        return [Entry(account, -amount if account_kind == "liability" else amount)]
    if kind == "transfer" and target:
        if target == account:
            raise RuleError("SAME_ACCOUNT")
        if account_kind in ("liability", "receivable") and target_kind in (
            "liability",
            "receivable",
        ):
            raise RuleError("DEBT_TRANSFER_UNSUPPORTED")
        if fee and "receivable" in (account_kind, target_kind):
            raise RuleError("INVALID_EVENT_FIELDS")
        if account_kind == "liability":
            if fee > amount:
                raise RuleError("FEE_EXCEEDS_AMOUNT")
            return [Entry(account, amount), Entry(target, amount - fee)]
        return [
            Entry(account, -(amount + fee)),
            Entry(target, -amount if target_kind == "liability" else amount),
        ]
    raise RuleError("INVALID_EVENT")


def check_balance(balance: int) -> None:
    if balance < 0:
        raise RuleError("INSUFFICIENT_BALANCE")
    if balance > MAX_FEN:
        raise RuleError("AMOUNT_OUT_OF_RANGE")
