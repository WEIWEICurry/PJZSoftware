"use client";

import { useEffect, useState, type FormEvent } from "react";
import type { components } from "./api-schema";
import { DateStepper } from "./date-stepper";
import { RecurringPanel } from "./recurring-panel";
import { FundNavPanel } from "./fund-nav-panel";
import { request } from "./api";
import { fenToYuan, localDay, money, yuanToFen } from "./money";
import {
  sortPositions,
  type PositionSort,
  type PositionSortKey,
} from "./position-sort";

type Page = components["schemas"]["InvestmentPage"];
type SellOption = components["schemas"]["SellOption"];
type Account = components["schemas"]["AccountOutput"];
type Trade = components["schemas"]["TradeOutput"];
type Instrument = components["schemas"]["InstrumentInput"];
const kinds = { stock: "股票", etf: "ETF", fund: "公募基金" };
const actions = {
  opening: "期初持仓",
  buy: "买入／申购",
  sell: "卖出／赎回",
  cash_dividend: "现金分红",
  reinvest: "基金分红再投",
  split: "份额折算（拆分／合并）",
};
const amount = (value: string | null | undefined, fallback = "待核算") =>
  value == null ? fallback : money(value);
const profitTone = (value: string | null | undefined) =>
  value == null || BigInt(value) === 0n
    ? undefined
    : BigInt(value) < 0n
      ? "return-negative"
      : "return-positive";
const blank = () => ({
  account_id: "",
  instrument_id: "",
  action: "buy" as Trade["action"],
  effective_date: localDay(),
  nav_date: localDay(),
  nav_date_manual: false,
  quantity: "",
  amount: "",
  costs: "",
  basis: "",
  amount_mode: "net" as "gross" | "net",
  note: "",
  cash_account_id: "",
  split_from_quantity: "",
});

export function InvestmentAssets({ connected }: { connected: boolean }) {
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!connected) return;
    let current = true;
    request<Page>("/investments")
      .then((value) => {
        if (current) setPage(value);
      })
      .catch((e: Error) => {
        if (current) setError(e.message);
      });
    return () => {
      current = false;
    };
  }, [connected]);
  return (
    <section className="card panel investment-assets">
      <span className="section-label">资产总览 · 本地估值</span>
      <h2>
        {page?.missing_price_count ? "已知净资产小计" : "净资产"}{" "}
        {amount(page?.known_net_fen, "—")}
      </h2>
      <p>资金账户净额包含应收与负债，持仓另加市值，证券现金只统计一次。</p>
      {page && (
        <p>
          持仓已估值合计 {money(page.known_value_fen)} ·{" "}
          {page.missing_price_count
            ? `${page.missing_price_count} 项持仓待估值，总净资产未知。`
            : "全部持仓已有估值；各价格日期见投资页。"}
        </p>
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}

export function InvestmentsPage({
  available,
  changed,
}: {
  available: boolean;
  changed: () => void;
}) {
  const [page, setPage] = useState<Page | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [section, setSection] = useState<
    "positions" | "trades" | "prices" | "recurring"
  >("positions");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [form, setForm] = useState(blank);
  const [editing, setEditing] = useState<Trade | null>(null);
  const [pendingVoid, setPendingVoid] = useState<Trade | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [showClosed, setShowClosed] = useState(false);
  const [positionSort, setPositionSort] = useState<PositionSort | null>(null);
  const [filterAccount, setFilterAccount] = useState("");
  const [filterKind, setFilterKind] = useState("");
  const [detail, setDetail] = useState<{
    account_id: string;
    instrument_id: string;
  } | null>(null);
  const [offset, setOffset] = useState(0);
  const [instrument, setInstrument] = useState<Instrument>({
    market: "SH",
    kind: "stock",
    code: "",
    name: "",
  });
  const [priceDate, setPriceDate] = useState(localDay());
  const [prices, setPrices] = useState<Record<string, string>>({});

  const [historicalSell, setHistoricalSell] = useState<{
    key: string;
    snapshot: Page | null;
    rows: SellOption[];
    error: string;
  } | null>(null);
  const [sellRetry, setSellRetry] = useState(0);
  const historicalSellKey =
    form.action === "sell" &&
    !editing &&
    form.account_id &&
    form.effective_date &&
    form.effective_date < localDay()
      ? `${form.account_id}|${form.effective_date}`
      : "";
  useEffect(() => {
    if (!available || !historicalSellKey) return;
    let current = true;
    const [account, day] = historicalSellKey.split("|");
    request<SellOption[]>(
      `/investments/sell-options?account_id=${account}&effective_date=${day}`,
    )
      .then((rows) => {
        if (!current) return;
        setHistoricalSell({
          key: historicalSellKey,
          snapshot: page,
          rows,
          error: "",
        });
        setForm((previous) =>
          rows.some((r) => r.instrument_id === previous.instrument_id)
            ? previous
            : { ...previous, instrument_id: "", quantity: "" },
        );
      })
      .catch((e: Error) => {
        if (current)
          setHistoricalSell({
            key: historicalSellKey,
            snapshot: page,
            rows: [],
            error: e.message,
          });
      });
    return () => {
      current = false;
    };
  }, [available, historicalSellKey, page, sellRetry]);
  useEffect(() => {
    if (!available) return;
    let current = true;
    Promise.all([
      request<Page>("/investments"),
      request<Account[]>("/accounts"),
    ])
      .then(([value, rows]) => {
        if (current) {
          setPage(value);
          setAccounts(rows);
          setForm((previous) =>
            previous.account_id
              ? previous
              : {
                  ...previous,
                  account_id:
                    rows.find(
                      (a) =>
                        a.name === "支付宝" &&
                        !a.archived &&
                        !["liability", "receivable"].includes(a.kind),
                    )?.id ?? "",
                },
          );
        }
      })
      .catch((e: Error) => {
        if (current) setError(e.message);
      });
    return () => {
      current = false;
    };
  }, [available]);
  async function act(operation: () => Promise<string>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const message = await operation();
      const [value, rows] = await Promise.all([
        request<Page>("/investments"),
        request<Account[]>("/accounts"),
      ]);
      setPage(value);
      setAccounts(rows);
      setNotice(message);
      changed();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败，请重试。");
    } finally {
      setBusy(false);
    }
  }
  const enabled = available && !busy && page !== null;
  const instrumentName = (id: string) => {
    const item = page?.instruments.find((i) => i.id === id);
    return item ? `${item.name} · ${item.market} ${item.code}` : "未知标的";
  };
  const accountName = (id: string) =>
    accounts.find((a) => a.id === id)?.name ?? "未知账户";
  const matching = (item: { account_id: string; instrument_id: string }) =>
    (!filterAccount || item.account_id === filterAccount) &&
    (!filterKind ||
      page?.instruments.find((i) => i.id === item.instrument_id)?.kind ===
        filterKind);
  const positions = sortPositions(
    page?.positions.filter(
      (p) => matching(p) && (showClosed || p.quantity !== "0"),
    ) ?? [],
    positionSort,
  );
  function toggleSort(key: PositionSortKey) {
    setPositionSort((previous) => ({
      key,
      direction:
        previous?.key === key && previous.direction === "descending"
          ? "ascending"
          : "descending",
    }));
  }
  const trades =
    page?.trades.filter(
      (t) =>
        matching(t) &&
        (!detail ||
          (t.account_id === detail.account_id &&
            t.instrument_id === detail.instrument_id)),
    ) ?? [];
  const position =
    detail &&
    page?.positions.find(
      (p) =>
        p.account_id === detail.account_id &&
        p.instrument_id === detail.instrument_id,
    );
  function edit(trade: Trade) {
    setEditing(trade);
    setShowForm(true);
    setError("");
    setPendingVoid(null);
    setForm({
      account_id: trade.account_id,
      instrument_id: trade.instrument_id,
      action: trade.action,
      effective_date: trade.effective_date,
      nav_date: trade.nav_date ?? trade.effective_date,
      nav_date_manual: true,
      quantity: trade.quantity,
      amount: fenToYuan(trade.gross_fen),
      costs: fenToYuan(trade.costs_fen),
      basis:
        trade.cost_basis_fen === null ? "" : fenToYuan(trade.cost_basis_fen),
      amount_mode: "gross",
      note: trade.note,
      cash_account_id: trade.cash_account_id ?? "",
      split_from_quantity: trade.split_from_quantity ?? "",
    });
  }
  async function saveTrade(event: FormEvent) {
    event.preventDefault();
    await act(async () => {
      await request(
        "/investments/trades" + (editing ? "/" + editing.id : ""),
        editing ? "PUT" : "POST",
        {
          account_id: form.account_id,
          instrument_id: form.instrument_id,
          action: form.action,
          effective_date: form.effective_date,
          nav_date: ["buy", "sell"].includes(form.action)
            ? form.nav_date
            : null,
          quantity:
            form.action === "cash_dividend" ? "0" : form.quantity.trim(),
          amount_fen: ["opening", "split"].includes(form.action)
            ? "0"
            : yuanToFen(form.amount),
          costs_fen: ["opening", "split", "cash_dividend"].includes(form.action)
            ? "0"
            : yuanToFen(form.costs.trim() || "0"),
          cost_basis_fen:
            form.action === "opening" && form.basis.trim()
              ? yuanToFen(form.basis)
              : null,
          amount_mode: ["buy", "sell"].includes(form.action)
            ? form.amount_mode
            : "gross",
          cash_account_id:
            ["buy", "sell", "cash_dividend", "reinvest"].includes(
              form.action,
            ) && form.cash_account_id
              ? form.cash_account_id
              : null,
          split_from_quantity:
            form.action === "split" ? form.split_from_quantity.trim() : null,
          note: form.note,
          ...(editing ? { revision: editing.revision } : {}),
        },
      );
      setShowForm(false);
      setEditing(null);
      setForm({
        ...blank(),
        account_id: cashAccounts.find((a) => a.name === "支付宝")?.id ?? "",
      });
      return (
        "投资记录已保存，现金、持仓和后续成本已重新核算。" +
        (["cash_dividend", "reinvest", "split"].includes(form.action)
          ? "请补录事件当日或之后的除息／折算后价格。"
          : "")
      );
    });
  }
  const cashAccounts = accounts.filter(
    (a) => !a.archived && a.kind !== "liability" && a.kind !== "receivable",
  );
  const heldQuantity = (account: string, asset: string) =>
    page?.positions.find(
      (p) => p.account_id === account && p.instrument_id === asset,
    )?.quantity ?? "";
  const sellRows: SellOption[] = historicalSellKey
    ? historicalSell?.key === historicalSellKey &&
      historicalSell.snapshot === page
      ? historicalSell.rows
      : []
    : (page?.positions ?? []).filter(
        (p) => p.account_id === form.account_id && /[1-9]/.test(p.quantity),
      );
  const sellPending =
    !!historicalSellKey &&
    (historicalSell?.key !== historicalSellKey ||
      historicalSell.snapshot !== page);
  const sellError =
    historicalSellKey &&
    historicalSell?.key === historicalSellKey &&
    historicalSell.snapshot === page
      ? historicalSell.error
      : "";
  const sellRestricted = form.action === "sell" && !editing;
  const entryInstruments = (page?.instruments ?? []).filter(
    (i) => !sellRestricted || sellRows.some((p) => p.instrument_id === i.id),
  );
  const saleQuantity = sellRows.find(
    (p) => p.instrument_id === form.instrument_id,
  )?.quantity;
  const sellBlocked =
    sellRestricted &&
    (!form.account_id ||
      sellPending ||
      !!sellError ||
      !entryInstruments.length);
  function changeAction(action: Trade["action"]) {
    setForm({
      ...form,
      action,
      instrument_id: action === "sell" ? "" : form.instrument_id,
      quantity: action === "cash_dividend" ? "0" : "",
      amount: "",
      costs: "",
      basis: "",
      amount_mode: "net",
      cash_account_id: "",
      split_from_quantity:
        action === "split"
          ? heldQuantity(form.account_id, form.instrument_id)
          : "",
    });
  }
  function cashPreview() {
    if (form.action === "opening")
      return "期初只建立持仓，不扣现金，不计收入。";
    if (form.action === "split")
      return `确认份额 ${form.split_from_quantity || "—"} → ${form.quantity || "—"}，总成本不变，现金不变；保存后需更新折算后价格。`;
    try {
      const input = BigInt(yuanToFen(form.amount));
      const fee = BigInt(yuanToFen(form.costs.trim() || "0"));
      if (form.action === "cash_dividend")
        return `实际净到账 ${money(input.toString())}，份额与总成本不变，只计投资分红。`;
      if (form.action === "reinvest")
        return `净分红 ${money(input.toString())} 再投，新增 ${form.quantity || "—"} 份；另扣现金费用 ${money(fee.toString())}，分红收益与成本同步记录。`;
      const net =
        form.amount_mode === "net"
          ? input
          : input + (form.action === "buy" ? fee : -fee);
      return `本次${form.action === "buy" ? "扣款" : "到账"} ${money(net.toString())}，持仓${form.action === "buy" ? "增加" : "减少"} ${form.quantity || "—"} 份／股。`;
    } catch {
      return "填写金额和份额后可查看本次资金变化。";
    }
  }
  return (
    <div className="investment-workspace">
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <div className="alert success" role="status">
          {notice}
        </div>
      )}
      <div className="stat-grid">
        {[
          ["已估值持仓市值", amount(page?.known_value_fen, "—")],
          ["持仓盈亏", amount(page?.unrealized_fen), page?.holding_return_bps],
          [
            "累计投资盈亏",
            amount(page?.total_profit_fen),
            page?.total_return_bps,
          ],
        ].map(([label, value, rate]) => (
          <div
            className={`card metric ${label === "已估值持仓市值" ? "metric-primary" : ""}`}
            key={label}
          >
            <span>{label}</span>
            <strong
              className={profitTone(
                label === "持仓盈亏"
                  ? page?.unrealized_fen
                  : label === "累计投资盈亏"
                    ? page?.total_profit_fen
                    : null,
              )}
            >
              {value}
            </strong>
            {label !== "已估值持仓市值" && (
              <span>
                收益率{" "}
                {rate == null
                  ? "—"
                  : `${BigInt(rate) > 0n ? "+" : ""}${fenToYuan(rate)}%`}
              </span>
            )}
          </div>
        ))}
      </div>
      <p className="footnote">
        已实现卖出盈亏 {amount(page?.realized_fen, "—")}
        ；现金分红 {amount(page?.cash_dividends_fen, "—")} · 再投分红{" "}
        {amount(page?.reinvested_dividends_fen, "—")}
        。已实现与分红从录入期初之后计算，持仓盈亏按带入成本核算，费用不重复扣除。估值价格可能来自不同日期。持仓收益率以剩余成本为分母；累计收益率以期初成本及后续累计投入（含费用、不减卖出回款、不重复计再投分红）为分母，均非年化。
        {!!page?.missing_price_count &&
          ` ${page.missing_price_count} 项待估值，市值仅为已知小计。`}
        {!!page?.unknown_cost_count &&
          ` ${page.unknown_cost_count} 项成本待补，相关盈亏未知。`}
      </p>
      <div className="investment-toolbar">
        <div className="investment-tabs" role="group" aria-label="投资视图">
          {(
            [
              ["positions", "我的持仓"],
              ["trades", "投资记录"],
              ["prices", "标的与估值"],
              ["recurring", "定投计划"],
            ] as const
          ).map(([id, label]) => (
            <button
              className={section === id ? "" : "secondary"}
              aria-pressed={section === id}
              key={id}
              onClick={() => {
                setSection(id);
                setDetail(null);
                setOffset(0);
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <div>
          <button
            className="secondary"
            disabled={!available || busy}
            onClick={() => void act(async () => "投资数据已刷新。")}
          >
            刷新投资
          </button>{" "}
          <button
            disabled={!enabled}
            aria-expanded={showForm}
            aria-controls="investment-entry-form"
            onClick={() => setShowForm(!showForm)}
          >
            记一笔投资
          </button>
        </div>
      </div>
      {showForm && (
        <section
          id="investment-entry-form"
          className="card panel"
          aria-label="投资记录表单"
        >
          <h2>{editing ? "修改投资记录" : "记一笔投资"}</h2>
          <form onSubmit={saveTrade}>
            <fieldset disabled={!enabled} className="investment-fields">
              <label>
                操作
                <select
                  value={form.action}
                  disabled={!!editing}
                  onChange={(e) =>
                    changeAction(e.target.value as Trade["action"])
                  }
                >
                  <optgroup label="买卖与期初">
                    {(["opening", "buy", "sell"] as const).map((id) => (
                      <option key={id} value={id}>
                        {actions[id]}
                      </option>
                    ))}
                  </optgroup>
                  <optgroup label="分红">
                    {(["cash_dividend", "reinvest"] as const).map((id) => (
                      <option key={id} value={id}>
                        {actions[id]}
                      </option>
                    ))}
                  </optgroup>
                  <optgroup label="更多：份额事件">
                    <option value="split">{actions.split}</option>
                  </optgroup>
                </select>
              </label>
              <label>
                持仓账户
                <select
                  required
                  aria-label="持仓账户"
                  value={form.account_id}
                  disabled={!!editing}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      account_id: e.target.value,
                      ...(form.action === "sell"
                        ? { instrument_id: "", quantity: "" }
                        : {}),
                      split_from_quantity:
                        form.action === "split"
                          ? heldQuantity(e.target.value, form.instrument_id)
                          : form.split_from_quantity,
                    })
                  }
                >
                  <option value="">请选择账户</option>
                  {cashAccounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name} · {money(a.balance_fen)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                投资标的
                <select
                  aria-label="投资标的"
                  required
                  disabled={!!editing || !!sellBlocked}
                  value={form.instrument_id}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      instrument_id: e.target.value,
                      ...(form.action === "sell" ? { quantity: "" } : {}),
                      split_from_quantity:
                        form.action === "split"
                          ? heldQuantity(form.account_id, e.target.value)
                          : form.split_from_quantity,
                    })
                  }
                >
                  <option value="">请选择标的</option>
                  {entryInstruments.map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.name} · {i.code}
                    </option>
                  ))}
                </select>
                {sellRestricted && (
                  <small role="status">
                    {!form.account_id
                      ? "请先选择持仓账户。"
                      : sellPending
                        ? "正在读取该日期的持仓…"
                        : sellError
                          ? "持仓查询失败，请重试。"
                          : !entryInstruments.length
                            ? historicalSellKey
                              ? "该账户在所选日期暂无可卖出的持仓。"
                              : "该账户暂无可卖出的持仓。"
                            : "仅显示该持仓账户有剩余份额的标的。"}
                  </small>
                )}
                {!!sellError && (
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => {
                      setHistoricalSell(null);
                      setSellRetry((n) => n + 1);
                    }}
                  >
                    重试持仓查询
                  </button>
                )}
              </label>
              <label>
                {form.action === "opening"
                  ? "期初日期"
                  : form.action === "cash_dividend"
                    ? "实际到账日期"
                    : ["reinvest", "split"].includes(form.action)
                      ? "确认日期"
                      : "成交／确认日期"}
                <DateStepper
                  stepLabel={
                    form.action === "opening"
                      ? "期初日期"
                      : form.action === "cash_dividend"
                        ? "实际到账日期"
                        : ["reinvest", "split"].includes(form.action)
                          ? "确认日期"
                          : "成交／确认日期"
                  }
                  required
                  max={localDay()}
                  value={form.effective_date}
                  onValueChange={(value) =>
                    setForm({
                      ...form,
                      effective_date: value,
                      ...(form.action === "sell" && !editing
                        ? { instrument_id: "", quantity: "" }
                        : {}),
                      nav_date: form.nav_date_manual ? form.nav_date : value,
                    })
                  }
                />
              </label>
              {["buy", "sell"].includes(form.action) && (
                <label>
                  成交净值所属日
                  <DateStepper
                    stepLabel="成交净值所属日"
                    required
                    max={form.effective_date || localDay()}
                    value={form.nav_date}
                    onValueChange={(value) =>
                      setForm({
                        ...form,
                        nav_date: value,
                        nav_date_manual: true,
                      })
                    }
                  />
                </label>
              )}
              {form.action === "split" && (
                <label>
                  折算前份额（份／股）
                  <input
                    required
                    inputMode="decimal"
                    value={form.split_from_quantity}
                    onChange={(e) =>
                      setForm({ ...form, split_from_quantity: e.target.value })
                    }
                  />
                  <small>
                    必须与事件发生前的实际持仓一致，历史事件修改后会重新核对。
                  </small>
                </label>
              )}
              {form.action !== "cash_dividend" && (
                <label>
                  {form.action === "split"
                    ? "折算后份额（份／股）"
                    : form.action === "reinvest"
                      ? "新增份额（份）"
                      : "数量（份／股）"}
                  <input
                    required
                    inputMode="decimal"
                    placeholder="最多八位小数"
                    aria-label={
                      form.action === "split"
                        ? "折算后份额（份／股）"
                        : form.action === "reinvest"
                          ? "新增份额（份）"
                          : "数量（份／股）"
                    }
                    value={form.quantity}
                    onChange={(e) =>
                      setForm({ ...form, quantity: e.target.value })
                    }
                  />
                  {form.action === "sell" && form.instrument_id && (
                    <small>
                      {editing
                        ? `当前剩余 ${heldQuantity(form.account_id, form.instrument_id) || "0"} 份／股；历史修改以保存时重算校验为准。`
                        : historicalSellKey
                          ? `所选日期剩余 ${saleQuantity ?? "—"} 份／股；保存时还会校验后续交易。`
                          : `当前持有 ${saleQuantity ?? "0"} 份／股。`}
                    </small>
                  )}
                </label>
              )}
              {["buy", "sell", "cash_dividend", "reinvest"].includes(
                form.action,
              ) && (
                <label>
                  {form.action === "buy" || form.action === "reinvest"
                    ? "扣款账户"
                    : "到账账户"}
                  <select
                    aria-label={
                      form.action === "buy" || form.action === "reinvest"
                        ? "扣款账户"
                        : "到账账户"
                    }
                    value={form.cash_account_id}
                    onChange={(e) =>
                      setForm({ ...form, cash_account_id: e.target.value })
                    }
                  >
                    <option value="">同持仓账户（含现金）</option>
                    {cashAccounts.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {form.action === "opening" && (
                <label>
                  剩余总成本（元，选填）
                  <input
                    inputMode="decimal"
                    placeholder="未知请留空，不能填写买入单价"
                    aria-describedby="opening-cost-help"
                    value={form.basis}
                    onChange={(e) =>
                      setForm({ ...form, basis: e.target.value })
                    }
                  />
                  <small id="opening-cost-help">
                    当前持有份额对应的成本合计，不是每份成本价，也不是当前市值。未知可留空。
                  </small>
                </label>
              )}
              {["buy", "sell"].includes(form.action) && (
                <label>
                  金额口径
                  <select
                    aria-label="金额口径"
                    value={form.amount_mode}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        amount_mode: e.target.value as "gross" | "net",
                      })
                    }
                  >
                    <option value="gross">成交金额（不含费用）</option>
                    <option value="net">实际扣款／到账（已含费用）</option>
                  </select>
                </label>
              )}
              {!["opening", "split"].includes(form.action) && (
                <label>
                  {form.action === "cash_dividend"
                    ? "实际净到账（元）"
                    : form.action === "reinvest"
                      ? "再投分红金额（元）"
                      : form.amount_mode === "gross"
                        ? "成交金额（元）"
                        : form.action === "buy"
                          ? "实际扣款（元）"
                          : "实际到账（元）"}
                  <input
                    required
                    inputMode="decimal"
                    value={form.amount}
                    onChange={(e) =>
                      setForm({ ...form, amount: e.target.value })
                    }
                  />
                </label>
              )}
              {["buy", "sell", "reinvest"].includes(form.action) && (
                <div className="investment-fees">
                  <label>
                    {form.action === "reinvest"
                      ? "另付费用（元）"
                      : "费用合计（元）"}
                    <input
                      inputMode="decimal"
                      placeholder="留空按 0 处理"
                      value={form.costs}
                      onChange={(e) =>
                        setForm({ ...form, costs: e.target.value })
                      }
                    />
                    <small>
                      {form.action === "reinvest"
                        ? "仅填另外从持仓资金账户扣除的费用；已在净分红中扣除的费用不要重复填写。"
                        : form.amount_mode === "net"
                          ? "已含在实际金额中，此处只拆解，不再加扣。"
                          : "手续费、税费等合计，计入投资成本／净到账。"}
                    </small>
                  </label>
                </div>
              )}
              <label className="investment-note">
                {form.action === "split" ? "折算依据（必填）" : "备注"}
                <input
                  required={form.action === "split"}
                  maxLength={500}
                  placeholder={
                    form.action === "split"
                      ? "例如：平台确认的份额拆分记录"
                      : ""
                  }
                  value={form.note}
                  onChange={(e) => setForm({ ...form, note: e.target.value })}
                />
              </label>
            </fieldset>
            <p className="alert" aria-live="polite">
              {cashPreview()}
            </p>
            <p className="footnote">
              基金填写实际确认份额和确认日。期初为该账户标的第一笔记录；成本未知时先补齐成本再卖出。更换账户、标的或操作请作废后重新录入。
            </p>
            <button disabled={!enabled || !!sellBlocked}>保存投资记录</button>{" "}
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() => {
                setShowForm(false);
                setEditing(null);
                setForm({
                  ...blank(),
                  account_id:
                    cashAccounts.find((a) => a.name === "支付宝")?.id ?? "",
                });
              }}
            >
              取消编辑
            </button>
          </form>
        </section>
      )}
      {section !== "prices" && section !== "recurring" && (
        <div className="investment-filters">
          <label>
            账户筛选
            <select
              value={filterAccount}
              onChange={(e) => {
                setFilterAccount(e.target.value);
                setDetail(null);
                setOffset(0);
              }}
            >
              <option value="">全部账户</option>
              {accounts
                .filter(
                  (a) => a.kind !== "liability" && a.kind !== "receivable",
                )
                .map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
            </select>
          </label>
          <label>
            投资类型
            <select
              value={filterKind}
              onChange={(e) => {
                setFilterKind(e.target.value);
                setDetail(null);
                setOffset(0);
              }}
            >
              <option value="">全部类型</option>
              {Object.entries(kinds).map(([id, label]) => (
                <option key={id} value={id}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          {section === "positions" && (
            <label className="investment-checkbox">
              <input
                type="checkbox"
                checked={showClosed}
                onChange={(e) => setShowClosed(e.target.checked)}
              />
              显示已清仓
            </label>
          )}
        </div>
      )}
      {section === "positions" && (
        <section className="card panel">
          <h2>我的持仓</h2>
          <p className="footnote">
            持仓占比按全部账户持仓市值计算，不含现金，筛选不改变分母；显示到小数点后两位。
            收益率均非年化；持仓收益率按剩余成本，累计收益率按期初及后续累计投入计算。
            {!!page?.missing_price_count &&
              " 存在未估值持仓，总市值未知，占比暂不计算。"}
          </p>
          {!positions.length && (
            <p className="empty-state">
              暂无匹配持仓。先在“标的与估值”添加标的，再录入期初或买入。
            </p>
          )}
          {!!positions.length && (
            <div className="table-scroll">
              <table className="investment-table holdings-table">
                <thead>
                  <tr>
                    <th>标的／账户</th>
                    <th className="amount-column">份额／股数</th>
                    {(
                      [
                        ["cost_fen", "剩余成本"],
                        ["value_fen", "市值"],
                        ["unrealized_fen", "持仓盈亏"],
                        ["holding_return_bps", "持仓收益率"],
                        ["total_profit_fen", "累计盈亏"],
                        ["total_return_bps", "累计收益率"],
                        ["share_bps", "持仓占比"],
                      ] as const
                    ).map(([key, label]) => (
                      <th
                        className="amount-column"
                        key={key}
                        scope="col"
                        aria-sort={
                          positionSort?.key === key
                            ? positionSort.direction
                            : "none"
                        }
                      >
                        <button
                          type="button"
                          className="investment-sort"
                          aria-label={label}
                          title={`按${label}${positionSort?.key === key && positionSort.direction === "descending" ? "从小到大" : "从大到小"}排序`}
                          onClick={() => toggleSort(key)}
                        >
                          {label}
                          <span aria-hidden="true">
                            {positionSort?.key === key
                              ? positionSort.direction === "descending"
                                ? "↓"
                                : "↑"
                              : "↕"}
                          </span>
                        </button>
                      </th>
                    ))}
                    <th>估值价格</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p) => (
                    <tr key={p.account_id + p.instrument_id}>
                      <td>
                        {instrumentName(p.instrument_id)}
                        <small>
                          {accountName(p.account_id)}
                          {p.quantity === "0" ? " · 已清仓" : ""}
                        </small>
                      </td>
                      <td className="amount-column">{p.quantity}</td>
                      <td className="amount-column">
                        {amount(p.cost_fen, "成本待补")}
                      </td>
                      <td className="amount-column">
                        {amount(p.value_fen, "待估值")}
                      </td>
                      <td
                        className={`amount-column ${profitTone(p.unrealized_fen) ?? ""}`}
                      >
                        {amount(p.unrealized_fen)}
                      </td>
                      <td
                        className={`amount-column ${profitTone(p.holding_return_bps) ?? ""}`}
                      >
                        {p.holding_return_bps == null
                          ? "—"
                          : fenToYuan(p.holding_return_bps) + "%"}
                      </td>
                      <td
                        className={`amount-column ${profitTone(p.total_profit_fen) ?? ""}`}
                      >
                        {amount(p.total_profit_fen, "—")}
                      </td>
                      <td
                        className={`amount-column ${profitTone(p.total_return_bps) ?? ""}`}
                      >
                        {p.total_return_bps == null
                          ? "—"
                          : fenToYuan(p.total_return_bps) + "%"}
                      </td>
                      <td className="amount-column">
                        {p.share_bps == null
                          ? page?.missing_price_count
                            ? "待估值"
                            : "—"
                          : fenToYuan(p.share_bps) + "%"}
                      </td>
                      <td>
                        {p.price ?? "—"}
                        <small>
                          {p.valuation_required_from && p.value_fen === null
                            ? `事件后待更新（${p.valuation_required_from} 起）`
                            : p.price_date
                              ? `${p.price_date}${p.price_date < localDay() ? " · 非今日价格" : ""}`
                              : "尚未录入价格"}
                        </small>
                      </td>
                      <td>
                        <button
                          className="secondary"
                          onClick={() => {
                            setDetail(p);
                            setSection("trades");
                            setOffset(0);
                          }}
                        >
                          查看明细
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
      {section === "trades" && (
        <section className="card panel">
          <h2>{detail ? instrumentName(detail.instrument_id) : "投资记录"}</h2>
          {position && (
            <p>
              {accountName(position.account_id)} · {position.quantity} 份／股 ·
              剩余成本 {amount(position.cost_fen, "待补")} · 已实现{" "}
              {money(position.realized_fen)} · 持仓盈亏{" "}
              {amount(position.unrealized_fen)} · 现金分红{" "}
              {amount(position.cash_dividends_fen)} · 再投分红{" "}
              {amount(position.reinvested_dividends_fen)}
            </p>
          )}
          {detail && (
            <button
              className="secondary"
              onClick={() => {
                setDetail(null);
                setOffset(0);
              }}
            >
              返回全部记录
            </button>
          )}
          {pendingVoid && (
            <div className="alert" role="group" aria-label="确认作废投资">
              <p>
                确认作废 {pendingVoid.effective_date} 的
                {actions[pendingVoid.action]}
                ？会重算后续现金与持仓，原记录仍保留。
              </p>
              <button
                disabled={!enabled}
                onClick={() =>
                  void act(async () => {
                    await request(
                      `/investments/trades/${pendingVoid.id}/void`,
                      "POST",
                      { revision: pendingVoid.revision },
                    );
                    setPendingVoid(null);
                    return "投资记录已作废，后续数据已重算。";
                  })
                }
              >
                确认作废投资
              </button>{" "}
              <button
                className="secondary"
                onClick={() => setPendingVoid(null)}
              >
                取消作废
              </button>
            </div>
          )}
          {!trades.length ? (
            <p className="empty-state">暂无匹配记录。</p>
          ) : (
            <div className="table-scroll">
              <table className="investment-table">
                <thead>
                  <tr>
                    <th>日期／操作</th>
                    <th>净值所属日</th>
                    <th>标的／账户</th>
                    <th>数量</th>
                    <th>金额／期初成本</th>
                    <th>费用</th>
                    <th>备注／状态</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.slice(offset, offset + 20).map((t) => (
                    <tr key={t.id}>
                      <td>
                        {t.effective_date}
                        <small
                          className={
                            t.is_recurring
                              ? "trade-recurring"
                              : t.action === "sell"
                                ? "trade-red"
                                : t.action === "buy"
                                  ? "trade-blue"
                                  : undefined
                          }
                        >
                          {t.is_recurring ? "定投买入" : actions[t.action]}
                        </small>
                      </td>
                      <td>
                        {t.nav_date ?? "—"}
                        {t.nav_date_source === "default_backfill" && (
                          <small>按确认日补齐</small>
                        )}
                      </td>
                      <td>
                        {instrumentName(t.instrument_id)}
                        <small>
                          {accountName(t.account_id)}
                          {[
                            "buy",
                            "sell",
                            "cash_dividend",
                            "reinvest",
                          ].includes(t.action)
                            ? ` · ${t.action === "buy" || t.action === "reinvest" ? "扣款" : "到账"}：${accountName(t.cash_account_id || t.account_id)}`
                            : ""}
                        </small>
                      </td>
                      <td>
                        {t.action === "cash_dividend"
                          ? "—"
                          : t.action === "split"
                            ? `${t.split_from_quantity} → ${t.quantity}`
                            : t.quantity}
                      </td>
                      <td>
                        {t.action === "split"
                          ? "—"
                          : amount(
                              t.action === "opening"
                                ? t.cost_basis_fen
                                : t.gross_fen,
                              "成本待补",
                            )}
                      </td>
                      <td>{money(t.costs_fen)}</td>
                      <td>
                        {t.note || "—"}
                        <small>{t.status === "void" ? "已作废" : "有效"}</small>
                      </td>
                      <td>
                        {t.status === "active" && (
                          <>
                            <button
                              className="secondary"
                              disabled={!enabled}
                              onClick={() => edit(t)}
                            >
                              修改
                            </button>{" "}
                            <button
                              className="secondary"
                              disabled={!enabled}
                              onClick={() => setPendingVoid(t)}
                            >
                              作废
                            </button>
                          </>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="investment-pagination">
            <span>共 {trades.length} 条</span>
            <button
              className="secondary"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - 20))}
            >
              上一页
            </button>
            <button
              className="secondary"
              disabled={offset + 20 >= trades.length}
              onClick={() => setOffset(offset + 20)}
            >
              下一页
            </button>
          </div>
        </section>
      )}
      {section === "recurring" && (
        <RecurringPanel
          accounts={accounts}
          instruments={page?.instruments ?? []}
          valuations={page?.valuations ?? []}
          changed={async () => {
            setPage(await request<Page>("/investments"));
            changed();
          }}
        />
      )}
      {section === "prices" && (
        <>
          <FundNavPanel
            instruments={page?.instruments ?? []}
            saved={async () => {
              setPage(await request<Page>("/investments"));
              changed();
            }}
          />
          <section className="card panel">
            <h2>手动估值</h2>
            <label className="investment-price-date">
              价格／净值日期
              <DateStepper
                stepLabel="价格／净值日期"
                max={localDay()}
                required
                value={priceDate}
                onValueChange={(value) => {
                  setPriceDate(value);
                  setPrices({});
                }}
              />
            </label>
            <p className="footnote">
              价格为元／股或元／份，最多八位小数。每个标的单独保存；所选日期已有价格时修改原记录并保留修订。同一标的各账户共用价格。
            </p>
            {!page?.instruments.length && <p>先添加投资标的。</p>}
            {page?.instruments.map((i) => {
              const existing = page.valuations.find(
                (v) => v.instrument_id === i.id && v.price_date === priceDate,
              );
              const latest = page.valuations.find(
                (v) => v.instrument_id === i.id && v.status === "active",
              );
              return (
                <form
                  className="investment-price-row"
                  key={i.id}
                  onSubmit={(e) => {
                    e.preventDefault();
                    void act(async () => {
                      await request("/investments/valuations", "PUT", {
                        instrument_id: i.id,
                        price_date: priceDate,
                        price: prices[i.id] ?? existing?.price ?? "",
                        revision: existing?.revision ?? 0,
                        status: "active",
                      });
                      return `${i.name} 的手动价格已保存。`;
                    });
                  }}
                >
                  <div>
                    <strong>
                      {i.name} · {i.code}
                    </strong>
                    <small>
                      {kinds[i.kind]} · 最新有效{" "}
                      {latest
                        ? `${latest.price} 元 · ${latest.price_date}`
                        : "待估值"}
                    </small>
                  </div>
                  <input
                    aria-label={`${i.name}价格`}
                    required
                    inputMode="decimal"
                    placeholder="价格／净值"
                    value={prices[i.id] ?? existing?.price ?? ""}
                    onChange={(e) =>
                      setPrices({ ...prices, [i.id]: e.target.value })
                    }
                  />
                  <button disabled={!enabled || !priceDate}>保存价格</button>
                  {existing?.status === "active" && (
                    <button
                      type="button"
                      className="secondary"
                      disabled={!enabled}
                      onClick={() =>
                        void act(async () => {
                          await request("/investments/valuations", "PUT", {
                            instrument_id: i.id,
                            price_date: priceDate,
                            price: existing.price,
                            revision: existing.revision,
                            status: "void",
                          });
                          return "该日价格已作废，估值回退到最近有效价格。";
                        })
                      }
                    >
                      作废该日价格
                    </button>
                  )}
                </form>
              );
            })}
            <details>
              <summary>查看估值记录（含作废）</summary>
              <ul>
                {page?.valuations.map((v) => (
                  <li key={v.id}>
                    {instrumentName(v.instrument_id)} · {v.price_date} ·{" "}
                    {v.price} 元 · {v.source_label} ·{" "}
                    {v.status === "void" ? "已作废" : "有效"} · 修订{" "}
                    {v.revision}
                    {v.fetched_at && <> · 联网获取时间 {v.fetched_at}</>}
                  </li>
                ))}
              </ul>
            </details>
          </section>
          <section className="card panel">
            <h2>添加投资标的</h2>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void act(async () => {
                  await request("/investments/instruments", "POST", instrument);
                  setInstrument({ ...instrument, code: "", name: "" });
                  return "投资标的已添加，可以录入期初或买入。";
                });
              }}
            >
              <fieldset className="investment-fields" disabled={!enabled}>
                <label>
                  标的类型
                  <select
                    value={instrument.kind}
                    onChange={(e) => {
                      const kind = e.target.value as Instrument["kind"];
                      setInstrument({
                        ...instrument,
                        kind,
                        market:
                          kind === "fund"
                            ? "FUND"
                            : instrument.market === "FUND"
                              ? "SH"
                              : instrument.market,
                      });
                    }}
                  >
                    {Object.entries(kinds).map(([id, label]) => (
                      <option key={id} value={id}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  市场
                  <select
                    value={instrument.market}
                    disabled={instrument.kind === "fund"}
                    onChange={(e) =>
                      setInstrument({
                        ...instrument,
                        market: e.target.value as Instrument["market"],
                      })
                    }
                  >
                    {instrument.kind === "fund" ? (
                      <option value="FUND">公募基金</option>
                    ) : (
                      <>
                        <option value="SH">上海</option>
                        <option value="SZ">深圳</option>
                        <option value="BJ">北京</option>
                      </>
                    )}
                  </select>
                </label>
                <label>
                  六位代码
                  <input
                    required
                    pattern="[0-9]{6}"
                    maxLength={6}
                    value={instrument.code}
                    onChange={(e) =>
                      setInstrument({ ...instrument, code: e.target.value })
                    }
                  />
                </label>
                <label>
                  标的名称
                  <input
                    required
                    maxLength={60}
                    value={instrument.name}
                    onChange={(e) =>
                      setInstrument({ ...instrument, name: e.target.value })
                    }
                  />
                </label>
              </fieldset>
              <button disabled={!enabled}>添加标的</button>
            </form>
          </section>
        </>
      )}
      <p className="footnote">
        支持期初、买卖／申赎、现金分红、公募基金分红再投及份额拆分／合并。分红和折算后请更新事件日或之后的除息／折算后价格，同日已有价格也需重新保存确认。不支持现金补差、送红股或自动税费计算。
      </p>
    </div>
  );
}
