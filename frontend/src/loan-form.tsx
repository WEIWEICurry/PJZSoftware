"use client";
import { useState, type FormEvent } from "react";
import { request } from "./api";
import type { components } from "./api-schema";
import { fenToYuan, localDay, money, yuanToFen } from "./money";

type Account = components["schemas"]["AccountOutput"];
export type LoanAction = "borrow" | "repay" | "lend" | "collect";
export const loanLabels: Record<LoanAction, string> = {
  borrow: "我借入",
  repay: "我还钱",
  lend: "我借出",
  collect: "收回借款",
};
export function isLoanAccount(account: Account) {
  return account.kind === "liability" || account.kind === "receivable";
}
export function LoanForm({
  accounts,
  existing,
  initialAction = "borrow",
  initialCounterparty = "",
  enabled,
  save,
  cancel,
}: {
  accounts: Account[];
  existing?: components["schemas"]["EventOutput"];
  initialAction?: LoanAction;
  initialCounterparty?: string;
  enabled: boolean;
  save: (operation: () => Promise<void>) => Promise<void>;
  cancel?: () => void;
}) {
  const [action, setAction] = useState<LoanAction>(initialAction);
  const [counterparty, setCounterparty] = useState(initialCounterparty);
  const [name, setName] = useState("");
  const [cash, setCash] = useState(
    existing
      ? initialAction === "borrow" || initialAction === "collect"
        ? (existing.target_account_id ?? "")
        : existing.account_id
      : "",
  );
  const [amount, setAmount] = useState(
    existing ? fenToYuan(existing.amount_fen) : "",
  );
  const [day, setDay] = useState(existing?.effective_date ?? localDay());
  const [note, setNote] = useState(existing?.note ?? "");
  const returning = action === "repay" || action === "collect";
  const receiving = action === "borrow" || action === "collect";
  const kind =
    action === "borrow" || action === "repay" ? "liability" : "receivable";
  const parties = accounts.filter(
    (a) =>
      a.kind === kind &&
      !a.archived &&
      (!returning || a.balance_fen !== "0" || a.id === initialCounterparty),
  );
  const cashAccounts = accounts.filter((a) => !isLoanAccount(a) && !a.archived);
  const party = parties.find((a) => a.id === counterparty);
  async function submit(event: FormEvent) {
    event.preventDefault();
    await save(async () => {
      const cashId = cash || cashAccounts[0]?.id;
      if (existing) {
        const [source, target] = receiving
          ? [counterparty, cashId]
          : [cashId, counterparty];
        await request("/events/" + existing.id, "PUT", {
          kind: "transfer",
          account_id: source,
          target_account_id: target,
          amount_fen: yuanToFen(amount),
          effective_date: day,
          note,
          fee_fen: "0",
          category_id: null,
          original_event_id: null,
          revision: existing.revision,
        });
      } else
        await request("/loans", "POST", {
          action,
          cash_account_id: cashId,
          counterparty_id: counterparty || null,
          counterparty_name: counterparty ? null : name.trim(),
          effective_date: day,
          amount_fen: yuanToFen(amount),
          note,
        });
      setAmount("");
      setNote("");
      setName("");
      setCounterparty("");
    });
  }
  return (
    <form className="form-grid loan-form" onSubmit={submit}>
      <div
        className="loan-actions wide-field"
        role="group"
        aria-label="借还款操作"
      >
        {(Object.entries(loanLabels) as [LoanAction, string][]).map(
          ([key, label]) => (
            <button
              type="button"
              className={action === key ? "" : "secondary"}
              aria-pressed={action === key}
              disabled={!enabled || Boolean(existing)}
              key={key}
              onClick={() => {
                setAction(key);
                setCounterparty("");
                setName("");
                setAmount("");
              }}
            >
              {label}
            </button>
          ),
        )}
      </div>
      <label>
        {returning ? "选择欠款" : action === "borrow" ? "向谁借" : "借给谁"}
        <select
          value={counterparty}
          onChange={(e) => setCounterparty(e.target.value)}
          required={returning || Boolean(existing)}
          disabled={Boolean(existing)}
        >
          <option value="">
            {returning ? "请选择未结清的欠款" : "填写新对象"}
          </option>
          {parties.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name} · {money(a.balance_fen)}
            </option>
          ))}
        </select>
      </label>
      {!existing && !returning && !counterparty && (
        <label>
          对方姓名
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={50}
            required
          />
        </label>
      )}
      <label>
        {receiving ? "收款账户" : "付款账户"}
        <select
          value={cash || cashAccounts[0]?.id || ""}
          onChange={(e) => setCash(e.target.value)}
          required
        >
          <option value="" disabled>
            请选择资金账户
          </option>
          {cashAccounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name} · {money(a.balance_fen)}
            </option>
          ))}
        </select>
      </label>
      <label>
        本金（元）
        <input
          inputMode="decimal"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          placeholder="0.00"
          required
        />
      </label>
      <label>
        发生日期
        <input
          type="date"
          value={day}
          max={localDay()}
          onChange={(e) => setDay(e.target.value)}
          required
        />
      </label>
      <label>
        备注（选填）
        <input
          value={note}
          maxLength={500}
          onChange={(e) => setNote(e.target.value)}
        />
      </label>
      {party && returning && (
        <p className="footnote wide-field">
          {action === "repay" ? "我还欠对方" : "对方还欠我"}{" "}
          {money(party.balance_fen)}，可以分次
          {action === "repay" ? "归还" : "收回"}。
        </p>
      )}
      {returning && !parties.length && (
        <p className="footnote wide-field">
          暂无这类未结清欠款。已有欠款可在账户页添加期初记录。
        </p>
      )}
      <div className="form-footer">
        <button
          disabled={!enabled || !cashAccounts.length || (returning && !party)}
        >
          {existing ? "保存修改" : "保存" + loanLabels[action]}
        </button>
        {cancel && (
          <button type="button" className="secondary" onClick={cancel}>
            关闭
          </button>
        )}
        <small>只记录本金，不计日常收支。利息请单独记录收入或支出。</small>
      </div>
    </form>
  );
}
