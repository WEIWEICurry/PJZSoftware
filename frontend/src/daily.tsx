"use client";
import { useEffect, useState, type FormEvent } from "react";
import { request } from "./api";
import type { components } from "./api-schema";
import { fenToYuan, localDay, money, yuanToFen } from "./money";

type Account = components["schemas"]["AccountOutput"];
type Category = components["schemas"]["CategoryOutput"];
type LedgerEvent = components["schemas"]["EventOutput"];
type EventPage = components["schemas"]["EventPage"];
type Summary = components["schemas"]["SummaryOutput"];
type EventInput = components["schemas"]["EventInput"];
const accountKinds = {
  cash: "现金",
  bank: "银行卡",
  payment: "支付账户",
  securities: "证券现金",
  liability: "负债",
};
const eventKinds: Record<string, string> = {
  opening: "期初",
  income: "收入",
  expense: "支出",
  transfer: "转账／借还本金",
  refund: "退款",
  adjustment: "余额校正",
};
const blankEvent = (): EventInput => ({
  kind: "expense",
  account_id: "",
  amount_fen: "0",
  effective_date: localDay(),
  fee_fen: "0",
  note: "",
  category_id: null,
  target_account_id: null,
  original_event_id: null,
});

export function DailyOverview({
  connected,
  open,
}: {
  connected: boolean;
  open: (tab: "accounts" | "journal") => void;
}) {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (connected)
      request<Summary>("/summary?month=" + localDay().slice(0, 7))
        .then(setSummary)
        .catch((e: Error) => setError(e.message));
  }, [connected]);
  return (
    <section className="daily-overview">
      <div className="section-heading">
        <div>
          <span className="section-label">
            本月收支 · {localDay().slice(0, 7)}
          </span>
          <h2>每一笔，都有清晰的去向。</h2>
        </div>
        <button disabled={!connected} onClick={() => open("journal")}>
          记一笔 +
        </button>
      </div>
      {error && (
        <div role="alert" className="alert error">
          {error}
        </div>
      )}
      <div className="stat-grid">
        {[
          ["本月收入", summary?.income_fen],
          ["本月支出（扣除退款）", summary?.expense_fen],
          ["本月结余", summary?.surplus_fen],
        ].map(([label, value]) => (
          <div className="card metric" key={label}>
            <span>{label}</span>
            <strong>{value === undefined ? "—" : money(value)}</strong>
          </div>
        ))}
      </div>
      <div className="card asset-strip">
        <div>
          <span>账户净额</span>
          <strong>{summary ? money(summary.net_fen) : "—"}</strong>
        </div>
        <p>
          现金资产 {summary ? money(summary.assets_fen) : "—"} · 未偿负债{" "}
          {summary ? money(summary.debt_fen) : "—"}
          <br />
          <small>只统计账户资金，尚未包含投资持仓价值。</small>
        </p>
        <button
          className="secondary"
          disabled={!connected}
          onClick={() => open("accounts")}
        >
          管理账户
        </button>
      </div>
    </section>
  );
}

export function DailyWorkspace({
  mode,
  available,
  changed,
}: {
  mode: "accounts" | "journal";
  available: boolean;
  changed: () => void;
}) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [page, setPage] = useState<EventPage>({ items: [], total: 0 });
  const [month, setMonth] = useState(localDay().slice(0, 7));
  const [filterAccount, setFilterAccount] = useState("");
  const [filterKind, setFilterKind] = useState("");
  const [filterCategory, setFilterCategory] = useState("");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [accountName, setAccountName] = useState("");
  const [accountKind, setAccountKind] = useState<Account["kind"]>("bank");
  const [openingDate, setOpeningDate] = useState(localDay());
  const [opening, setOpening] = useState("0.00");
  const [editingAccount, setEditingAccount] = useState<Account | null>(null);
  const [draft, setDraft] = useState<EventInput>(blankEvent);
  const [amount, setAmount] = useState("");
  const [fee, setFee] = useState("0.00");
  const [editing, setEditing] = useState<LedgerEvent | null>(null);
  const [pendingVoid, setPendingVoid] = useState<LedgerEvent | null>(null);
  const [categoryName, setCategoryName] = useState("");
  const [categoryDirection, setCategoryDirection] = useState<
    "expense" | "income"
  >("expense");
  const enabled = available && !busy;

  async function refreshBase() {
    const [nextAccounts, nextCategories] = await Promise.all([
      request<Account[]>("/accounts"),
      request<Category[]>("/categories"),
    ]);
    setAccounts(nextAccounts);
    setCategories(nextCategories);
  }
  async function refreshEvents() {
    const [year, number] = month.split("-").map(Number);
    if (!year || !number) return;
    const last = new Date(year, number, 0).getDate();
    const query = new URLSearchParams({
      start: month + "-01",
      end: month + "-" + last,
      limit: "20",
      offset: String(offset),
    });
    if (filterAccount) query.set("account_id", filterAccount);
    if (filterKind) query.set("kind", filterKind);
    if (filterCategory) query.set("category_id", filterCategory);
    setPage(await request<EventPage>("/events?" + query));
  }
  useEffect(() => {
    if (!available) return;
    Promise.all([
      request<Account[]>("/accounts"),
      request<Category[]>("/categories"),
    ])
      .then(([a, c]) => {
        setAccounts(a);
        setCategories(c);
      })
      .catch((e: Error) => setError(e.message));
  }, [available]);
  useEffect(() => {
    if (!available) return;
    const [year, number] = month.split("-").map(Number);
    if (!year || !number) return;
    const query = new URLSearchParams({
      start: month + "-01",
      end: month + "-" + new Date(year, number, 0).getDate(),
      limit: "20",
      offset: String(offset),
    });
    if (filterAccount) query.set("account_id", filterAccount);
    if (filterKind) query.set("kind", filterKind);
    if (filterCategory) query.set("category_id", filterCategory);
    request<EventPage>("/events?" + query)
      .then(setPage)
      .catch((e: Error) => setError(e.message));
  }, [available, month, filterAccount, filterKind, filterCategory, offset]);
  async function act(operation: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await operation();
      await refreshBase();
      await refreshEvents();
      changed();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败，请重试。");
    } finally {
      setBusy(false);
    }
  }
  async function saveAccount(event: FormEvent) {
    event.preventDefault();
    await act(async () => {
      if (editingAccount)
        await request("/accounts/" + editingAccount.id, "PATCH", {
          name: accountName,
          revision: editingAccount.revision,
          archived: editingAccount.archived,
        });
      else
        await request("/accounts", "POST", {
          name: accountName,
          kind: accountKind,
          opening_date: openingDate,
          opening_fen: yuanToFen(opening),
        });
      setAccountName("");
      setEditingAccount(null);
      setNotice("账户已保存。");
    });
  }
  function setKind(kind: EventInput["kind"]) {
    setDraft({
      ...draft,
      kind,
      category_id: null,
      target_account_id: null,
      original_event_id: null,
    });
    setFee("0.00");
  }
  function edit(row: LedgerEvent) {
    setDraft({
      kind: row.kind as EventInput["kind"],
      account_id: row.account_id,
      effective_date: row.effective_date,
      category_id: row.category_id,
      target_account_id: row.target_account_id,
      original_event_id: row.original_event_id,
      note: row.note,
      amount_fen: row.amount_fen,
      fee_fen: row.fee_fen,
    });
    setAmount(fenToYuan(row.amount_fen));
    setFee(fenToYuan(row.fee_fen));
    setEditing(row);
    setPendingVoid(null);
    document
      .getElementById("entry-form")
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  function startRefund(row: LedgerEvent) {
    setDraft({
      ...blankEvent(),
      kind: "refund",
      account_id: row.account_id,
      category_id: row.category_id,
      original_event_id: row.id,
    });
    setAmount(fenToYuan(row.amount_fen));
    setFee("0.00");
    setEditing(null);
    document
      .getElementById("entry-form")
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  const direction = draft.kind === "income" ? "income" : "expense";
  const choices = categories.filter((item) => item.direction === direction);
  const defaultCategory =
    choices.find(
      (item) =>
        item.name ===
        (draft.kind === "transfer"
          ? "手续费"
          : draft.kind === "income"
            ? "工资"
            : "餐饮"),
    )?.id ?? choices[0]?.id;
  async function saveEvent(event: FormEvent) {
    event.preventDefault();
    await act(async () => {
      const feeFen = draft.kind === "transfer" ? yuanToFen(fee) : "0";
      const needsCategory =
        ["income", "expense", "refund"].includes(draft.kind) || feeFen !== "0";
      const body = {
        ...draft,
        account_id:
          draft.account_id || accounts.find((item) => !item.archived)?.id,
        amount_fen: yuanToFen(amount),
        fee_fen: feeFen,
        category_id: needsCategory
          ? draft.category_id || defaultCategory
          : null,
        target_account_id:
          draft.kind === "transfer" ? draft.target_account_id : null,
        original_event_id:
          draft.kind === "refund" ? draft.original_event_id : null,
      };
      if (editing)
        await request("/events/" + editing.id, "PUT", {
          ...body,
          revision: editing.revision,
        });
      else await request("/events", "POST", body);
      setDraft(blankEvent());
      setAmount("");
      setFee("0.00");
      setEditing(null);
      setNotice("流水已保存，账户余额已更新。");
    });
  }
  const accountLabel = (id: string | null) =>
    accounts.find((item) => item.id === id)?.name ?? "—";
  const categoryLabel = (id: string | null) =>
    categories.find((item) => item.id === id)?.name ?? "—";
  return (
    <div className="daily-workspace">
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
      {mode === "accounts" ? (
        <>
          <div className="account-grid">
            {accounts.map((item) => (
              <section
                className={
                  "card account-card" + (item.archived ? " archived" : "")
                }
                key={item.id}
              >
                <span className="section-label">
                  {accountKinds[item.kind]} {item.archived ? "· 已归档" : ""}
                </span>
                <h2>{item.name}</h2>
                <strong>{money(item.balance_fen)}</strong>
                <p>
                  {item.kind === "liability" ? "当前欠款" : "当前余额"} · 期初{" "}
                  {item.opening_date}
                </p>
                <div className="row-actions">
                  <button
                    className="text-button"
                    disabled={!enabled}
                    onClick={() => {
                      setEditingAccount(item);
                      setAccountName(item.name);
                    }}
                  >
                    编辑名称
                  </button>
                  <button
                    className="text-button"
                    disabled={!enabled}
                    onClick={() =>
                      void act(async () => {
                        await request("/accounts/" + item.id, "PATCH", {
                          name: item.name,
                          archived: !item.archived,
                          revision: item.revision,
                        });
                        setNotice(
                          item.archived ? "账户已恢复。" : "账户已归档。",
                        );
                      })
                    }
                  >
                    {item.archived ? "恢复账户" : "归档账户"}
                  </button>
                </div>
              </section>
            ))}
          </div>
          {!accounts.length && (
            <div className="card empty-state">
              <h2>先添加一个账户</h2>
              <p>录入今天的实际余额作为期初，之后的收支都会有据可查。</p>
            </div>
          )}
          <section className="card panel">
            <span className="section-label">账户设置</span>
            <h2>{editingAccount ? "修改账户名称" : "添加账户"}</h2>
            <form onSubmit={saveAccount} className="form-grid">
              <label>
                账户名称
                <input
                  value={accountName}
                  maxLength={60}
                  onChange={(e) => setAccountName(e.target.value)}
                  required
                />
              </label>
              {!editingAccount && (
                <>
                  <label>
                    账户类型
                    <select
                      value={accountKind}
                      onChange={(e) =>
                        setAccountKind(e.target.value as Account["kind"])
                      }
                    >
                      {Object.entries(accountKinds).map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    期初日期
                    <input
                      type="date"
                      value={openingDate}
                      max={localDay()}
                      onChange={(e) => setOpeningDate(e.target.value)}
                      required
                    />
                  </label>
                  <label>
                    {accountKind === "liability"
                      ? "期初欠款（元）"
                      : "期初余额（元）"}
                    <input
                      inputMode="decimal"
                      value={opening}
                      onChange={(e) => setOpening(e.target.value)}
                      required
                    />
                  </label>
                </>
              )}
              <div className="form-footer">
                <button disabled={!enabled}>
                  {editingAccount ? "保存账户" : "添加账户"}
                </button>
                {editingAccount && (
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => {
                      setEditingAccount(null);
                      setAccountName("");
                    }}
                  >
                    取消编辑
                  </button>
                )}
                <small>期初余额不计入收入；归档要求余额为零。</small>
              </div>
            </form>
          </section>
        </>
      ) : (
        <>
          <section id="entry-form" className="card panel">
            <div className="section-heading">
              <div>
                <span className="section-label">日常账本</span>
                <h2>
                  {editing
                    ? "修改流水"
                    : draft.kind === "refund"
                      ? "记录退款"
                      : "记一笔"}
                </h2>
              </div>
              {editing && (
                <button
                  className="secondary"
                  onClick={() => {
                    setEditing(null);
                    setDraft(blankEvent());
                    setAmount("");
                  }}
                >
                  取消修改
                </button>
              )}
            </div>
            <form onSubmit={saveEvent} className="form-grid">
              <label>
                类型
                <select
                  value={draft.kind}
                  onChange={(e) =>
                    setKind(e.target.value as EventInput["kind"])
                  }
                >
                  {Object.entries(eventKinds)
                    .filter(([id]) => id !== "opening")
                    .map(([id, name]) => (
                      <option key={id} value={id}>
                        {name}
                      </option>
                    ))}
                </select>
              </label>
              <label>
                发生日期
                <input
                  type="date"
                  value={draft.effective_date}
                  max={localDay()}
                  onChange={(e) =>
                    setDraft({ ...draft, effective_date: e.target.value })
                  }
                  required
                />
              </label>
              <label>
                {draft.kind === "transfer" ? "转出／借款账户" : "记账账户"}
                <select
                  value={
                    draft.account_id ||
                    accounts.find((item) => !item.archived)?.id ||
                    ""
                  }
                  onChange={(e) =>
                    setDraft({ ...draft, account_id: e.target.value })
                  }
                  required
                >
                  <option value="" disabled>
                    请选择账户
                  </option>
                  {accounts
                    .filter((item) => !item.archived)
                    .map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name} · {money(item.balance_fen)}
                      </option>
                    ))}
                </select>
              </label>
              <label>
                {draft.kind === "transfer" ? "转账本金（元）" : "金额（元）"}
                <input
                  inputMode="decimal"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  placeholder={
                    draft.kind === "adjustment" ? "增额填正，减额填负" : "0.00"
                  }
                  required
                />
              </label>
              {draft.kind === "transfer" && (
                <>
                  <label>
                    转入／还款账户
                    <select
                      value={draft.target_account_id ?? ""}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          target_account_id: e.target.value,
                        })
                      }
                      required
                    >
                      <option value="" disabled>
                        请选择账户
                      </option>
                      {accounts
                        .filter((item) => !item.archived)
                        .map((item) => (
                          <option key={item.id} value={item.id}>
                            {item.name}
                          </option>
                        ))}
                    </select>
                  </label>
                  <label>
                    手续费（元）
                    <input
                      inputMode="decimal"
                      value={fee}
                      onChange={(e) => setFee(e.target.value)}
                      required
                    />
                  </label>
                </>
              )}
              {draft.kind !== "adjustment" && (
                <label>
                  {draft.kind === "transfer" ? "手续费分类" : "分类"}
                  <select
                    value={draft.category_id || defaultCategory || ""}
                    disabled={draft.kind === "refund"}
                    onChange={(e) =>
                      setDraft({ ...draft, category_id: e.target.value })
                    }
                  >
                    {choices.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label className="wide-field">
                {draft.kind === "adjustment" ? "校正原因（必填）" : "备注"}
                <input
                  value={draft.note ?? ""}
                  onChange={(e) => setDraft({ ...draft, note: e.target.value })}
                  maxLength={500}
                  required={draft.kind === "adjustment"}
                />
              </label>
              {draft.kind === "refund" && (
                <p className="footnote wide-field">
                  {draft.original_event_id
                    ? "已关联原支出，累计退款不能超过原支出金额。"
                    : "请先在下方找到原支出，点击该行的“退款”。"}
                </p>
              )}
              <div className="form-footer">
                <button
                  disabled={
                    !enabled ||
                    !accounts.some((item) => !item.archived) ||
                    (draft.kind === "refund" && !draft.original_event_id)
                  }
                >
                  {editing ? "保存修改" : "保存流水"}
                </button>
                <small>
                  {draft.kind === "transfer"
                    ? "借还本金与普通转账均不计收支，只有费用计入支出。"
                    : draft.kind === "adjustment"
                      ? "余额校正不计收支，并保留校正原因。"
                      : "金额按整数分保存，未来日期不作为已发生流水。"}
                </small>
              </div>
            </form>
          </section>
          <section className="card journal-panel">
            <div className="section-heading">
              <div>
                <span className="section-label">流水记录</span>
                <h2>每一笔，清楚留存</h2>
              </div>
              <span className="muted-label">共 {page.total} 条</span>
            </div>
            <div className="filters">
              <label>
                月份
                <input
                  type="month"
                  value={month}
                  onChange={(e) => {
                    setMonth(e.target.value);
                    setOffset(0);
                  }}
                />
              </label>
              <label>
                账户筛选
                <select
                  value={filterAccount}
                  onChange={(e) => {
                    setFilterAccount(e.target.value);
                    setOffset(0);
                  }}
                >
                  <option value="">全部账户</option>
                  {accounts.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                类型筛选
                <select
                  value={filterKind}
                  onChange={(e) => {
                    setFilterKind(e.target.value);
                    setOffset(0);
                  }}
                >
                  <option value="">全部类型</option>
                  {Object.entries(eventKinds).map(([id, label]) => (
                    <option value={id} key={id}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                分类筛选
                <select
                  value={filterCategory}
                  onChange={(e) => {
                    setFilterCategory(e.target.value);
                    setOffset(0);
                  }}
                >
                  <option value="">全部分类</option>
                  {categories.map((item) => (
                    <option value={item.id} key={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {pendingVoid && (
              <div className="alert">
                <strong>确认作废这条{eventKinds[pendingVoid.kind]}？</strong>
                <p>
                  {pendingVoid.effective_date} · {money(pendingVoid.amount_fen)}
                  。原记录会保留，余额将重新核算。
                </p>
                <button
                  disabled={!enabled}
                  onClick={() =>
                    void act(async () => {
                      await request(
                        "/events/" + pendingVoid.id + "/void",
                        "POST",
                        { revision: pendingVoid.revision },
                      );
                      setPendingVoid(null);
                      setNotice("流水已作废，余额已重新核算。");
                    })
                  }
                >
                  确认作废
                </button>
                <button
                  className="text-button"
                  onClick={() => setPendingVoid(null)}
                >
                  取消
                </button>
              </div>
            )}
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>日期／类型</th>
                    <th>账户／分类</th>
                    <th>备注</th>
                    <th className="amount-column">金额</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {page.items.map((row) => (
                    <tr
                      key={row.id}
                      className={row.status === "void" ? "void-row" : ""}
                    >
                      <td>
                        {row.effective_date}
                        <small>
                          {eventKinds[row.kind]}{" "}
                          {row.status === "void" ? "· 已作废" : ""}
                        </small>
                      </td>
                      <td>
                        {accountLabel(row.account_id)}
                        {row.target_account_id
                          ? " → " + accountLabel(row.target_account_id)
                          : ""}
                        <small>{categoryLabel(row.category_id)}</small>
                      </td>
                      <td className="note-cell">{row.note || "—"}</td>
                      <td className="amount-column">
                        {money(row.amount_fen)}
                        {row.fee_fen !== "0" && (
                          <small>手续费 {money(row.fee_fen)}</small>
                        )}
                      </td>
                      <td>
                        {row.kind !== "opening" && row.status === "active" && (
                          <div className="row-actions">
                            <button
                              className="text-button"
                              disabled={!enabled}
                              onClick={() => edit(row)}
                            >
                              修改
                            </button>
                            {row.kind === "expense" && (
                              <button
                                className="text-button"
                                disabled={!enabled}
                                onClick={() => startRefund(row)}
                              >
                                退款
                              </button>
                            )}
                            <button
                              className="text-button danger"
                              disabled={!enabled}
                              onClick={() => setPendingVoid(row)}
                            >
                              作废
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!page.items.length && (
              <div className="empty-state">这个筛选范围还没有流水。</div>
            )}
            <div className="pagination">
              <button
                className="secondary"
                disabled={!offset || !enabled}
                onClick={() => setOffset(Math.max(0, offset - 20))}
              >
                上一页
              </button>
              <span>第 {Math.floor(offset / 20) + 1} 页</span>
              <button
                className="secondary"
                disabled={offset + 20 >= page.total || !enabled}
                onClick={() => setOffset(offset + 20)}
              >
                下一页
              </button>
            </div>
          </section>
          <details className="card panel">
            <summary>添加自定义分类</summary>
            <form
              className="form-grid"
              onSubmit={(e) => {
                e.preventDefault();
                void act(async () => {
                  await request("/categories", "POST", {
                    name: categoryName,
                    direction: categoryDirection,
                  });
                  setCategoryName("");
                  setNotice("分类已添加。");
                });
              }}
            >
              <label>
                分类名称
                <input
                  value={categoryName}
                  maxLength={60}
                  onChange={(e) => setCategoryName(e.target.value)}
                  required
                />
              </label>
              <label>
                分类方向
                <select
                  value={categoryDirection}
                  onChange={(e) =>
                    setCategoryDirection(e.target.value as "income" | "expense")
                  }
                >
                  <option value="expense">支出</option>
                  <option value="income">收入</option>
                </select>
              </label>
              <div className="form-footer">
                <button disabled={!enabled}>添加分类</button>
              </div>
            </form>
          </details>
        </>
      )}
    </div>
  );
}
