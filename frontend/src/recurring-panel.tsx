"use client";
import { useEffect, useState } from "react";
import type { components } from "./api-schema";
import { request } from "./api";
import { localDay, money, yuanToFen, fenToYuan } from "./money";
type Plan = components["schemas"]["PlanOutput"];
type Draft = components["schemas"]["DraftOutput"];
type Edit = {
  selected: boolean;
  decision: "confirm" | "skip";
  confirmation_date: string;
  nav_date: string;
  quantity: string;
  amount: string;
  costs: string;
};
export function RecurringPanel({
  accounts,
  instruments,
  valuations,
  changed,
}: {
  accounts: components["schemas"]["AccountOutput"][];
  instruments: components["schemas"]["InstrumentOutput"][];
  valuations: components["schemas"]["PriceOutput"][];
  changed: () => Promise<void>;
}) {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState("");
  const [showDeleted, setShowDeleted] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<Plan | null>(null);
  const [selected, setSelected] = useState("");
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [edits, setEdits] = useState<Record<string, Edit>>({});
  const [start, setStart] = useState(localDay().slice(0, 7) + "-01");
  const [end, setEnd] = useState(localDay());
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [review, setReview] = useState<
    components["schemas"]["ReviewInput"] | null
  >(null);
  const [allowDuplicate, setAllowDuplicate] = useState(false);
  const [form, setForm] = useState({
    name: "",
    account_id: "",
    cash_account_id: "",
    instrument_id: "",
    start_date: localDay(),
    frequency: "weekdays" as Plan["frequency"],
    weekday: 0,
    amount: "10.00",
    costs: "0.00",
  });
  useEffect(() => {
    let current = true;
    request<Plan[]>("/recurring?include_deleted=true")
      .then((p) => {
        if (current) setPlans(p);
      })
      .catch((e: Error) => {
        if (current) setMessage(e.message);
      });
    return () => {
      current = false;
    };
  }, []);
  const valid = !!start && !!end && start <= end && end <= localDay();
  const key = [selected, start, end].join(":");
  const [loaded, setLoaded] = useState("");
  async function load(id = selected) {
    if (!id || !valid) return;
    const rows = await request<Draft[]>(
      `/recurring/${id}/drafts?start=${start}&end=${end}`,
    );
    setDrafts(rows);
    setEdits({});
    setLoaded([id, start, end].join(":"));
  }
  async function act(run: () => Promise<string>) {
    setBusy(true);
    setMessage("");
    try {
      const result = await run();
      setPlans(await request<Plan[]>("/recurring?include_deleted=true"));
      await changed();
      setMessage(result);
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function edit(d: Draft): Edit {
    return (
      edits[d.id] ?? {
        selected: false,
        decision: "confirm",
        confirmation_date: "",
        nav_date: "",
        quantity: "",
        amount: fenToYuan(d.amount_fen),
        costs: fenToYuan(d.costs_fen),
      }
    );
  }
  function update(d: Draft, fields: Partial<Edit>) {
    setEdits({ ...edits, [d.id]: { ...edit(d), ...fields } });
    setReview(null);
  }
  function prepare() {
    try {
      const rows = drafts
        .filter(
          (d) => d.status === "pending" && !plan?.deleted && edit(d).selected,
        )
        .map((d) => {
          const e = edit(d);
          return {
            id: d.id,
            revision: d.revision,
            decision: e.decision,
            confirmation_date:
              e.decision === "confirm" ? e.confirmation_date : null,
            nav_date:
              e.decision === "confirm" && e.nav_date ? e.nav_date : null,
            quantity: e.decision === "confirm" ? e.quantity : "0",
            amount_fen: e.decision === "confirm" ? yuanToFen(e.amount) : "0",
            costs_fen: e.decision === "confirm" ? yuanToFen(e.costs) : "0",
          };
        });
      if (!rows.length || rows.length > 100)
        throw new Error("请选择 1～100 项待核对记录。");
      if (
        rows.some(
          (r) =>
            r.decision === "confirm" &&
            (!r.quantity || !r.confirmation_date || !r.nav_date),
        )
      )
        throw new Error(
          "请按回执填写实际确认日期、成交净值所属日和份额，不能用计划日期或最新净值代替。",
        );
      setReview({ rows, allow_possible_duplicate: allowDuplicate });
      setMessage("");
    } catch (e) {
      setMessage((e as Error).message);
    }
  }
  const plan = plans.find((p) => p.id === selected);
  const editingPlan = plans.find((p) => p.id === editing);
  const visiblePlans = plans.filter((p) => showDeleted || !p.deleted);
  function beginEdit(p: Plan) {
    setEditing(p.id);
    setFormOpen(true);
    setSelected(p.id);
    setLoaded("");
    setForm({
      name: p.name,
      account_id: p.account_id,
      cash_account_id: p.cash_account_id ?? "",
      instrument_id: p.instrument_id,
      start_date: p.start_date,
      frequency: p.frequency,
      weekday: p.weekday,
      amount: fenToYuan(p.amount_fen),
      costs: fenToYuan(p.costs_fen),
    });
    setMessage("");
  }
  function quoteFor(day: string) {
    return valuations.find(
      (v) =>
        v.instrument_id === plan?.instrument_id &&
        v.price_date === day &&
        v.status === "active",
    );
  }

  return (
    <section className="card panel" aria-label="定投计划与批量确认">
      <h2>定投计划与批量确认</h2>
      <p className="footnote">
        计划只生成待核对草稿，不代表扣款成功，不冻结资金或增加持仓。核对支付宝已确认交易后再入账；已手工记过的交易不要重复确认。节假日和扣款失败可跳过。
      </p>
      <section aria-label="定投计划管理">
        <h3>定投计划管理</h3>
        <label className="recurring-check-label">
          <input
            type="checkbox"
            className="recurring-check"
            checked={showDeleted}
            disabled={busy || !!review}
            onChange={(e) => {
              setShowDeleted(e.target.checked);
              if (!e.target.checked && plan?.deleted) {
                setSelected("");
                setLoaded("");
              }
            }}
          />
          显示已删除计划（只读历史）
        </label>
        {!visiblePlans.length ? (
          <p className="empty-state">还没有计划，请添加定投计划。</p>
        ) : (
          <div className="table-scroll">
            <table className="investment-table" aria-label="定投计划管理列表">
              <thead>
                <tr>
                  <th>计划／状态</th>
                  <th>账户／基金</th>
                  <th>金额／默认费用</th>
                  <th>规则／起始日</th>
                  <th>待核对／已确认</th>
                  <th>管理</th>
                </tr>
              </thead>
              <tbody>
                {visiblePlans.map((p) => (
                  <tr key={p.id}>
                    <td>
                      {p.name}
                      <small>
                        {p.deleted
                          ? "已删除（历史保留）"
                          : p.paused
                            ? "已暂停"
                            : "运行中"}
                      </small>
                    </td>
                    <td>
                      {accounts.find((a) => a.id === p.account_id)?.name ??
                        "未知账户"}
                      <small>
                        {instruments.find((i) => i.id === p.instrument_id)
                          ?.name ?? "未知基金"}
                      </small>
                    </td>
                    <td>
                      {money(p.amount_fen)}
                      <small>{money(p.costs_fen)}</small>
                    </td>
                    <td>
                      {p.frequency === "daily"
                        ? "每日"
                        : p.frequency === "weekdays"
                          ? "周一至周五"
                          : `每周${["一", "二", "三", "四", "五", "六", "日"][p.weekday]}`}
                      <small>{p.start_date}</small>
                    </td>
                    <td>
                      {p.pending_count} ／ {p.confirmed_count}
                    </td>
                    <td>
                      <button
                        className="secondary"
                        disabled={busy || !!review}
                        onClick={() => {
                          setSelected(p.id);
                          setLoaded("");
                        }}
                      >
                        选择查看
                      </button>
                      {!p.deleted && (
                        <>
                          <button
                            className="secondary"
                            disabled={busy || !!review}
                            onClick={() => beginEdit(p)}
                          >
                            修改计划
                          </button>
                          <button
                            className="secondary"
                            disabled={busy || !!review}
                            onClick={() =>
                              void act(async () => {
                                await request(
                                  `/recurring/${p.id}/pause`,
                                  "POST",
                                  { revision: p.revision, paused: !p.paused },
                                );
                                return p.paused
                                  ? "计划已恢复。"
                                  : "计划已暂停。";
                              })
                            }
                          >
                            {p.paused ? "恢复计划" : "暂停计划"}
                          </button>
                          {p.paused && (
                            <button
                              className="danger"
                              disabled={busy || !!review}
                              onClick={() => setPendingDelete(p)}
                            >
                              删除计划
                            </button>
                          )}
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {pendingDelete && (
        <div className="alert" role="dialog" aria-label="删除定投计划确认">
          <p>
            删除“{pendingDelete.name}
            ”后，将从常用列表移除，不能再生成或确认。已有{" "}
            {pendingDelete.confirmed_count} 项已确认交易及{" "}
            {pendingDelete.pending_count}{" "}
            项待核对记录均保留为只读历史，不删除账务。
          </p>
          <button
            className="danger"
            disabled={busy}
            onClick={() =>
              void act(async () => {
                await request(`/recurring/${pendingDelete.id}/delete`, "POST", {
                  revision: pendingDelete.revision,
                });
                if (selected === pendingDelete.id) {
                  setSelected("");
                  setLoaded("");
                }
                if (editing === pendingDelete.id) {
                  setEditing("");
                  setFormOpen(false);
                }
                setPendingDelete(null);
                return "计划已删除，历史记录与交易已保留。";
              })
            }
          >
            确认删除计划
          </button>
          <button
            className="secondary"
            disabled={busy}
            onClick={() => setPendingDelete(null)}
          >
            取消删除计划
          </button>
        </div>
      )}
      <details
        open={formOpen}
        onToggle={(e) => setFormOpen(e.currentTarget.open)}
      >
        <summary>{editing ? "修改定投计划" : "添加定投计划"}</summary>
        {editing && (
          <p className="footnote">
            金额和频率修改只影响新草稿；扣款账户用于之后确认的待核对项，已确认交易不变。已有核对记录后账户、基金及起始日不可更换。
          </p>
        )}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void act(async () => {
              const p = await request<Plan>(
                editing ? `/recurring/${editing}` : "/recurring",
                editing ? "PUT" : "POST",
                {
                  revision: editing ? editingPlan?.revision : undefined,
                  ...form,
                  cash_account_id: form.cash_account_id || null,
                  amount_fen: yuanToFen(form.amount),
                  costs_fen: yuanToFen(form.costs),
                  amount: undefined,
                  costs: undefined,
                },
              );
              setSelected(p.id);
              setLoaded("");
              setFormOpen(false);
              setEditing("");
              return editing
                ? "计划已修改，已有草稿与交易未改变。"
                : "计划已保存，请选择日期生成待核对项。";
            });
          }}
        >
          <fieldset
            disabled={busy || !!review}
            className="investment-report-controls"
          >
            <label>
              计划名称
              <input
                required
                maxLength={80}
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </label>
            <label>
              计划持仓账户
              <select
                required
                disabled={!!editingPlan?.has_drafts}
                value={form.account_id}
                onChange={(e) =>
                  setForm({ ...form, account_id: e.target.value })
                }
              >
                <option value="">请选择</option>
                {accounts
                  .filter(
                    (a) =>
                      (a.id === form.account_id || !a.archived) &&
                      !["liability", "receivable"].includes(a.kind),
                  )
                  .map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              计划扣款账户
              <select
                value={form.cash_account_id}
                onChange={(e) =>
                  setForm({ ...form, cash_account_id: e.target.value })
                }
              >
                <option value="">同持仓账户（含现金）</option>
                {accounts
                  .filter(
                    (a) =>
                      !a.archived &&
                      !["liability", "receivable"].includes(a.kind),
                  )
                  .map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              定投基金
              <select
                required
                disabled={!!editingPlan?.has_drafts}
                value={form.instrument_id}
                onChange={(e) =>
                  setForm({ ...form, instrument_id: e.target.value })
                }
              >
                <option value="">请选择</option>
                {instruments
                  .filter((i) => i.kind === "fund")
                  .map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.name} · {i.code}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              计划起始日
              <input
                type="date"
                required
                disabled={!!editingPlan?.has_drafts}
                value={form.start_date}
                onChange={(e) =>
                  setForm({ ...form, start_date: e.target.value })
                }
              />
            </label>
            <label>
              每次扣款（元，已含费用）
              <input
                required
                inputMode="decimal"
                value={form.amount}
                onChange={(e) => setForm({ ...form, amount: e.target.value })}
              />
            </label>
            <label>
              默认费用（元）
              <input
                required
                inputMode="decimal"
                value={form.costs}
                onChange={(e) => setForm({ ...form, costs: e.target.value })}
              />
            </label>
            <label>
              生成频率
              <select
                value={form.frequency}
                onChange={(e) =>
                  setForm({
                    ...form,
                    frequency: e.target.value as Plan["frequency"],
                  })
                }
              >
                <option value="daily">每日</option>
                <option value="weekdays">周一至周五（非交易日历）</option>
                <option value="weekly">每周指定星期</option>
              </select>
            </label>
            {form.frequency === "weekly" && (
              <label>
                每周星期
                <select
                  value={form.weekday}
                  onChange={(e) =>
                    setForm({ ...form, weekday: Number(e.target.value) })
                  }
                >
                  {["一", "二", "三", "四", "五", "六", "日"].map((d, i) => (
                    <option key={i} value={i}>
                      星期{d}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </fieldset>
          <button disabled={busy || !!review}>保存定投计划</button>
          {editing && (
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() => {
                setEditing("");
                setFormOpen(false);
              }}
            >
              取消修改计划
            </button>
          )}
        </form>
      </details>
      <fieldset
        disabled={busy || review !== null}
        className="investment-report-controls"
      >
        <label>
          选择定投计划
          <select
            value={selected}
            onChange={(e) => {
              setSelected(e.target.value);
              setLoaded("");
              setReview(null);
            }}
          >
            <option value="">请选择计划</option>
            {visiblePlans.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
                {p.deleted ? "（已删除）" : p.paused ? "（已暂停）" : ""}
              </option>
            ))}
          </select>
        </label>
        <label>
          核对开始日期
          <input
            type="date"
            value={start}
            max={localDay()}
            onChange={(e) => {
              setStart(e.target.value);
              setLoaded("");
            }}
          />
        </label>
        <label>
          核对结束日期
          <input
            type="date"
            value={end}
            max={localDay()}
            onChange={(e) => {
              setEnd(e.target.value);
              setLoaded("");
            }}
          />
        </label>
      </fieldset>
      {plan && (
        <>
          <p>
            {plan.name} · 每次 {money(plan.amount_fen)} · 默认费用{" "}
            {money(plan.costs_fen)} ·{" "}
            {plan.deleted
              ? "已删除，仅供查看"
              : plan.paused
                ? "已暂停，仅停止生成新草稿"
                : "运行中，无后台自动执行"}
          </p>
          <div className="recurring-actions">
            <button
              disabled={busy || !!review || !valid}
              onClick={() =>
                void act(async () => {
                  await load();
                  return "待核对项已刷新。";
                })
              }
            >
              查看待核对项
            </button>
            <button
              disabled={
                busy || !!review || !valid || plan.paused || plan.deleted
              }
              onClick={() =>
                void act(async () => {
                  const r = await request<{ count: number }>(
                    `/recurring/${plan.id}/generate`,
                    "POST",
                    { start, end },
                  );
                  await load();
                  return `新增 ${r.count} 项，已有日期不会重复生成。`;
                })
              }
            >
              生成待核对项
            </button>
            <button
              className="secondary"
              disabled={busy || !!review || plan.deleted}
              onClick={() =>
                void act(async () => {
                  await request(`/recurring/${plan.id}/pause`, "POST", {
                    revision: plan.revision,
                    paused: !plan.paused,
                  });
                  return plan.paused
                    ? "计划已恢复，不会自动补单。"
                    : "计划已暂停，已有草稿仍可核对。";
                })
              }
            >
              {plan.paused ? "恢复计划" : "暂停计划"}
            </button>
          </div>
        </>
      )}
      <p className="footnote">
        QDII
        的申请日、成交净值所属日、公布日和确认日可能不同。请按平台回执填写日期，不统一推算
        T+2；仅匹配所填净值日，不用确认日或最新净值代替。价格仅供核对，实际份额和费用以回执为准，缺价可通过联网净值补齐。
      </p>
      {loaded === key && (
        <>
          <p className="footnote">
            此范围共 {drafts.length} 项，一次最多选择 100
            项；填写实际份额与扣款。首版资金在确认日入账，不处理扣款后尚未确认的在途资金。计划参数可在上方管理栏修改，已有草稿金额保持生成时快照。
          </p>
          <div className="recurring-actions">
            <button
              className="secondary"
              disabled={busy || !!review || !!plan?.deleted}
              onClick={() => {
                const ids = new Set(
                  drafts
                    .filter((d) => d.status === "pending" && !plan?.deleted)
                    .slice(0, 100)
                    .map((d) => d.id),
                );
                setEdits(
                  Object.fromEntries(
                    drafts.map((d) => [
                      d.id,
                      { ...edit(d), selected: ids.has(d.id) },
                    ]),
                  ),
                );
              }}
            >
              选择待核对项（最多100条）
            </button>
            <button
              className="secondary"
              disabled={busy || !!review || !!plan?.deleted}
              onClick={() =>
                setEdits(
                  Object.fromEntries(
                    drafts.map((d) => [d.id, { ...edit(d), selected: false }]),
                  ),
                )
              }
            >
              取消所选定投项
            </button>
          </div>
          <div className="table-scroll">
            <table className="investment-table" aria-label="定投待核对列表">
              <thead>
                <tr>
                  <th>选择／计划日期</th>
                  <th>处理／状态</th>
                  <th>实际确认日期</th>
                  <th>实际份额</th>
                  <th>实际扣款（元）</th>
                  <th>费用（元）</th>
                  <th>成交净值所属日</th>
                  <th>该日已录净值（核对用）</th>
                </tr>
              </thead>
              <tbody>
                {drafts.map((d) => {
                  const e = edit(d);
                  return (
                    <tr key={d.id}>
                      <td>
                        {d.status === "pending" && !plan?.deleted && (
                          <input
                            className="recurring-check"
                            type="checkbox"
                            aria-label={`选择 ${d.scheduled_date}`}
                            checked={e.selected}
                            disabled={busy || !!review || !!plan?.deleted}
                            onChange={(v) =>
                              update(d, { selected: v.target.checked })
                            }
                          />
                        )}{" "}
                        {d.scheduled_date}
                      </td>
                      <td>
                        {d.status === "pending" && !plan?.deleted ? (
                          <select
                            aria-label={`${d.scheduled_date} 处理方式`}
                            disabled={busy || !!review || !!plan?.deleted}
                            value={e.decision}
                            onChange={(v) =>
                              update(d, {
                                decision: v.target.value as Edit["decision"],
                              })
                            }
                          >
                            <option value="confirm">确认买入</option>
                            <option value="skip">跳过</option>
                          </select>
                        ) : d.status === "pending" ? (
                          "待核对（计划已删除）"
                        ) : d.status === "skipped" ? (
                          "已跳过"
                        ) : d.event_status === "void" ? (
                          "交易已作废（保留关联）"
                        ) : (
                          "已确认"
                        )}
                      </td>
                      {d.status === "pending" && !plan?.deleted ? (
                        <>
                          <td>
                            <input
                              aria-label={`${d.scheduled_date} 确认日期`}
                              type="date"
                              max={localDay()}
                              min={d.scheduled_date}
                              disabled={
                                busy || !!review || e.decision === "skip"
                              }
                              value={e.confirmation_date}
                              onChange={(v) =>
                                update(d, { confirmation_date: v.target.value })
                              }
                            />
                          </td>
                          <td>
                            <input
                              aria-label={`${d.scheduled_date} 份额`}
                              inputMode="decimal"
                              disabled={
                                busy || !!review || e.decision === "skip"
                              }
                              value={e.quantity}
                              onChange={(v) =>
                                update(d, { quantity: v.target.value })
                              }
                            />
                          </td>
                          <td>
                            <input
                              aria-label={`${d.scheduled_date} 扣款`}
                              inputMode="decimal"
                              disabled={
                                busy || !!review || e.decision === "skip"
                              }
                              value={e.amount}
                              onChange={(v) =>
                                update(d, { amount: v.target.value })
                              }
                            />
                          </td>
                          <td>
                            <input
                              aria-label={`${d.scheduled_date} 费用`}
                              inputMode="decimal"
                              disabled={
                                busy || !!review || e.decision === "skip"
                              }
                              value={e.costs}
                              onChange={(v) =>
                                update(d, { costs: v.target.value })
                              }
                            />
                          </td>
                          <td>
                            <input
                              aria-label={`${d.scheduled_date} 净值所属日`}
                              type="date"
                              max={e.confirmation_date || localDay()}
                              disabled={
                                busy || !!review || e.decision === "skip"
                              }
                              value={e.nav_date}
                              onChange={(v) =>
                                update(d, { nav_date: v.target.value })
                              }
                            />
                          </td>
                        </>
                      ) : (
                        <>
                          <td>{d.effective_date ?? "—"}</td>
                          <td>{d.quantity ?? "—"}</td>
                          <td>{money(d.amount_fen)}</td>
                          <td>{money(d.costs_fen)}</td>
                          <td>{d.nav_date ?? "未记录"}</td>
                        </>
                      )}
                      <td>
                        {d.status === "pending" && !plan?.deleted
                          ? e.nav_date
                            ? (quoteFor(e.nav_date)?.price ??
                              "本地暂无该日净值")
                            : "请填写成交净值日"
                          : d.nav_date
                            ? (d.nav_price ?? "本地暂无该日净值")
                            : "未记录净值日"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <label className="recurring-check-label">
            <input
              type="checkbox"
              className="recurring-check"
              disabled={busy || !!review || !!plan?.deleted}
              checked={allowDuplicate}
              onChange={(e) => setAllowDuplicate(e.target.checked)}
            />
            我已核对，允许与已有完全相同的买入记录并存（通常无需勾选）
          </label>
          <button
            disabled={busy || !!review || !!plan?.deleted}
            onClick={prepare}
          >
            预览所选确认／跳过
          </button>
        </>
      )}
      {review && (
        <div className="alert" role="group" aria-label="定投批量确认预览">
          <p>
            所选 {review.rows.length} 项；确认买入{" "}
            {review.rows.filter((r) => r.decision === "confirm").length}{" "}
            项，总扣款{" "}
            {money(
              review.rows
                .filter((r) => r.decision === "confirm")
                .reduce((sum, r) => sum + BigInt(r.amount_fen ?? "0"), 0n)
                .toString(),
            )}
            （已含费用）；其余跳过。任一项失败将整批回滚。
          </p>
          <ul>
            {review.rows
              .filter((r) => r.decision === "confirm")
              .map((r) => (
                <li key={r.id}>
                  净值日 {r.nav_date} · 确认日 {r.confirmation_date} · 该日净值{" "}
                  {quoteFor(r.nav_date ?? "")?.price ??
                    "本地暂无该日净值（不替用其他日期）"}{" "}
                  · 实际份额 {r.quantity}
                </li>
              ))}
          </ul>
          <button
            disabled={busy}
            onClick={() =>
              void act(async () => {
                const r = await request<{ count: number }>(
                  "/recurring/review",
                  "POST",
                  review,
                );
                setReview(null);
                await load();
                return `已处理 ${r.count} 项。已确认交易可在投资记录中修改或作废。`;
              })
            }
          >
            确认处理所选记录
          </button>
          <button
            className="secondary"
            disabled={busy}
            onClick={() => setReview(null)}
          >
            返回修改定投记录
          </button>
        </div>
      )}
      {busy && <p role="status">正在处理定投…</p>}
      {message && <p role="status">{message}</p>}
    </section>
  );
}
