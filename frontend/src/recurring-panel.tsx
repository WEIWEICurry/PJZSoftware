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
  changed,
}: {
  accounts: components["schemas"]["AccountOutput"][];
  instruments: components["schemas"]["InstrumentOutput"][];
  changed: () => Promise<void>;
}) {
  const [plans, setPlans] = useState<Plan[]>([]);
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
    instrument_id: "",
    start_date: localDay(),
    frequency: "weekdays" as Plan["frequency"],
    weekday: 0,
    amount: "10.00",
    costs: "0.00",
  });
  useEffect(() => {
    let current = true;
    request<Plan[]>("/recurring")
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
      setPlans(await request<Plan[]>("/recurring"));
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
        confirmation_date: d.scheduled_date,
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
        .filter((d) => d.status === "pending" && edit(d).selected)
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
            r.decision === "confirm" && (!r.quantity || !r.confirmation_date),
        )
      )
        throw new Error(
          "请填写实际确认日期和份额，不能用计划金额代替实际份额。",
        );
      setReview({ rows, allow_possible_duplicate: allowDuplicate });
      setMessage("");
    } catch (e) {
      setMessage((e as Error).message);
    }
  }
  const plan = plans.find((p) => p.id === selected);
  return (
    <section className="card panel" aria-label="定投计划与批量确认">
      <h2>定投计划与批量确认</h2>
      <p className="footnote">
        计划只生成待核对草稿，不代表扣款成功，不冻结资金或增加持仓。核对支付宝已确认交易后再入账；已手工记过的交易不要重复确认。节假日和扣款失败可跳过。
      </p>
      <details>
        <summary>添加定投计划</summary>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void act(async () => {
              const p = await request<Plan>("/recurring", "POST", {
                ...form,
                amount_fen: yuanToFen(form.amount),
                costs_fen: yuanToFen(form.costs),
                amount: undefined,
                costs: undefined,
              });
              setSelected(p.id);
              setLoaded("");
              return "计划已保存，请选择日期生成待核对项。";
            });
          }}
        >
          <fieldset disabled={busy} className="investment-report-controls">
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
              计划资金账户
              <select
                required
                value={form.account_id}
                onChange={(e) =>
                  setForm({ ...form, account_id: e.target.value })
                }
              >
                <option value="">请选择</option>
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
          <button disabled={busy}>保存定投计划</button>
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
            {plans.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
                {p.paused ? "（已暂停）" : ""}
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
            {plan.paused
              ? "已暂停，仅停止生成新草稿"
              : "运行中，无后台自动执行"}
          </p>
          <div className="investment-tabs">
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
              disabled={busy || !!review || !valid || plan.paused}
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
              disabled={busy || !!review}
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
      {loaded === key && (
        <>
          <p className="footnote">
            此范围共 {drafts.length} 项，一次最多选择 100
            项；填写实际份额与扣款。首版资金在确认日入账，不处理扣款后尚未确认的在途资金。变更计划金额请暂停原计划并新建。
          </p>
          <div className="investment-tabs">
            <button
              className="secondary"
              disabled={busy || !!review}
              onClick={() => {
                const ids = new Set(
                  drafts
                    .filter((d) => d.status === "pending")
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
              disabled={busy || !!review}
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
                  <th>净值所属日（选填）</th>
                </tr>
              </thead>
              <tbody>
                {drafts.map((d) => {
                  const e = edit(d);
                  return (
                    <tr key={d.id}>
                      <td>
                        {d.status === "pending" && (
                          <input
                            className="recurring-check"
                            type="checkbox"
                            aria-label={`选择 ${d.scheduled_date}`}
                            checked={e.selected}
                            disabled={busy || !!review}
                            onChange={(v) =>
                              update(d, { selected: v.target.checked })
                            }
                          />
                        )}{" "}
                        {d.scheduled_date}
                      </td>
                      <td>
                        {d.status === "pending" ? (
                          <select
                            aria-label={`${d.scheduled_date} 处理方式`}
                            disabled={busy || !!review}
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
                        ) : d.status === "skipped" ? (
                          "已跳过"
                        ) : d.event_status === "void" ? (
                          "交易已作废（保留关联）"
                        ) : (
                          "已确认"
                        )}
                      </td>
                      {d.status === "pending" ? (
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
                              max={e.confirmation_date}
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
                          <td>{d.nav_date ?? "—"}</td>
                        </>
                      )}
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
              disabled={busy || !!review}
              checked={allowDuplicate}
              onChange={(e) => setAllowDuplicate(e.target.checked)}
            />
            我已核对，允许与已有完全相同的买入记录并存（通常无需勾选）
          </label>
          <button disabled={busy || !!review} onClick={prepare}>
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
