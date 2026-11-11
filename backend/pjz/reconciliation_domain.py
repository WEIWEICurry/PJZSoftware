"""Pure Decimal comparisons for user-confirmed platform holdings."""

from decimal import ROUND_HALF_UP, Decimal, localcontext

from pjz.investment_domain import decimal_text, rounded


def compare_quantity(local: str, platform: str) -> tuple[str, str]:
    with localcontext() as context:
        context.prec = 64
        actual, displayed = Decimal(local), Decimal(platform)
        delta = actual - displayed
        status = (
            "exact"
            if not delta
            else (
                "display"
                if actual.quantize(
                    Decimal(1).scaleb(-len(platform.partition(".")[2])), rounding=ROUND_HALF_UP
                )
                == displayed
                else "different"
            )
        )
        return status, decimal_text(delta)


def reference_value(quantity: str, nav: str | None) -> str | None:
    if nav is None:
        return None
    with localcontext() as context:
        context.prec = 64
        return str(rounded(Decimal(quantity) * Decimal(nav) * 100))
