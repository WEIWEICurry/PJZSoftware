import type { components } from "./api-schema";
import { money } from "./money";

type JournalEvent = components["schemas"]["JournalEventOutput"];
function signedMoney(value: string) {
  const delta = BigInt(value);
  return (
    (delta > 0n ? "+" : delta < 0n ? "-" : "") +
    money((delta < 0n ? -delta : delta).toString())
  );
}
export function JournalAmount({ row }: { row: JournalEvent }) {
  if (row.status === "void")
    return (
      <>
        <span>
          {row.kind === "investment" ? "—" : "原金额：" + money(row.amount_fen)}
        </span>
        <small>已作废，未影响余额</small>
      </>
    );
  const effects = row.cash_effects ?? [];
  return (
    <>
      {effects.length ? (
        effects.map((effect) => {
          const delta = BigInt(effect.delta_fen);
          const balanceLabel =
            effect.account_kind === "liability"
              ? "欠款"
              : effect.account_kind === "receivable"
                ? "待收回本金"
                : "余额";
          return (
            <div className="journal-cash-effect" key={effect.account_id}>
              <span
                className={`journal-cash-value ${delta > 0n ? "journal-cash-in" : delta < 0n ? "journal-cash-out" : ""}`}
              >
                {signedMoney(effect.delta_fen)}
              </span>
              <small className="journal-running-balance">
                {effects.length > 1 ? effect.account_name + " · " : ""}
                {balanceLabel}：{money(effect.balance_fen)}
              </small>
            </div>
          );
        })
      ) : (
        <>
          {row.kind === "investment" && row.cash_delta_fen != null
            ? signedMoney(row.cash_delta_fen)
            : money(row.amount_fen)}
          <small>余额待读取</small>
        </>
      )}
      {row.fee_fen !== "0" && <small>含手续费 {money(row.fee_fen)}</small>}
      {row.kind === "investment" && <small>实际资金变化（已含费用）</small>}
    </>
  );
}
