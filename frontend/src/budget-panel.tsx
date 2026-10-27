"use client";

import { useEffect, useState, type FormEvent } from "react";
import { request } from "./api";
import type { components } from "./api-schema";
import { fenToYuan, localDay, money, yuanToFen } from "./money";

type BudgetPage = components["schemas"]["BudgetPage"];
type Category = components["schemas"]["CategoryOutput"];

export function BudgetPanel({
  available,
  changed,
}: {
  available: boolean;
  changed: () => void;
}) {
  const [month, setMonth] = useState(localDay().slice(0, 7));
  const [loaded, setLoaded] = useState<BudgetPage | null>(null);
  const data = loaded?.month === month ? loaded : null;
  const [categories, setCategories] = useState<Category[]>([]);
  const [editing, setEditing] = useState(false);
  const [category, setCategory] = useState("");
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => {
    if (!available) return;
    let cancelled = false;
    Promise.all([
      request<BudgetPage>("/budgets/" + month),
      request<Category[]>("/categories"),
    ])
      .then(([page, choices]) => {
        if (!cancelled) {
          setLoaded(page);
          setCategories(choices.filter((c) => c.direction === "expense"));
        }
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [month, available]);
  const enabled = available && !busy && !!data;
  const selected =
    category ||
    categories.find((c) => c.name === "餐饮")?.id ||
    categories[0]?.id ||
    "";
  const row = data?.items.find((b) => b.category_id === selected);
  const configured = data?.items.filter((b) => b.limit_fen !== null) ?? [];
  async function act(operation: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await operation();
      setLoaded(await request<BudgetPage>("/budgets/" + month));
      changed();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败，请重试。");
    } finally {
      setBusy(false);
    }
  }
  function openEditor(id = selected) {
    setEditing(true);
    setCategory(id);
    const existing = data?.items.find((b) => b.category_id === id);
    setAmount(existing?.limit_fen ? fenToYuan(existing.limit_fen) : "");
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    await act(async () => {
      await request("/budgets/" + month + "/" + selected, "PUT", {
        limit_fen: yuanToFen(amount),
        revision: row?.revision ?? 0,
      });
      setNotice("分类预算已保存，不影响记账。");
    });
  }
  return (
    <section
      id="category-budgets"
      className="card panel budget-panel"
      aria-label="可选分类预算"
    >
      <div className="section-heading">
        <div>
          <span className="section-label">按月规划 · 自愿设置</span>
          <h2>分类预算</h2>
        </div>
        <button
          className="secondary"
          disabled={!enabled}
          onClick={() => (editing ? setEditing(false) : openEditor())}
        >
          {editing
            ? "收起设置"
            : configured.length
              ? "管理分类预算"
              : "设置分类预算"}
        </button>
      </div>
      <div className="report-date-controls">
        <label className="budget-month">
          预算月份
          <input
            type="month"
            value={month}
            disabled={busy || !available}
            onChange={(e) => {
              if (e.target.value) {
                setMonth(e.target.value);
                setNotice("");
                setError("");
                setCategory("");
                setAmount("");
              }
            }}
          />
        </label>
        <button
          className="text-button"
          disabled={!available || busy}
          onClick={() => void act(async () => {})}
        >
          刷新预算
        </button>
      </div>
      <p className="footnote">
        预算月份独立于上方报表。只对已设置的支出分类显示额度，不限制记账，不自动续期或结转。
      </p>
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
      {data && !configured.length && (
        <p className="budget-empty">
          尚未设置分类预算。可以直接使用记账和报表，需要时再设置。
        </p>
      )}
      {configured.length > 0 && (
        <div className="budget-grid">
          {configured.map((budget) => (
            <article className={"budget-card " + budget.status} key={budget.id}>
              <div className="section-heading">
                <h3>{budget.category_name}</h3>
                <span>
                  {budget.status === "over"
                    ? "已超支"
                    : budget.status === "exhausted"
                      ? "额度用尽"
                      : budget.status === "near"
                        ? "接近额度"
                        : budget.status === "future"
                          ? "计划中"
                          : "月度预算"}
                </span>
              </div>
              <p>
                预算额度 <strong>{money(budget.limit_fen!)}</strong>
              </p>
              {budget.used_fen !== null && budget.remaining_fen !== null ? (
                <>
                  <div className="budget-numbers">
                    <span>
                      已用 <strong>{money(budget.used_fen)}</strong>
                    </span>
                    <span>
                      {BigInt(budget.remaining_fen) < 0n ? "超支" : "剩余"}{" "}
                      <strong>
                        {money(
                          BigInt(budget.remaining_fen) < 0n
                            ? budget.over_fen!
                            : budget.remaining_fen,
                        )}
                      </strong>
                    </span>
                  </div>
                  <div
                    className="budget-track"
                    role="progressbar"
                    aria-label={budget.category_name + "预算使用比例"}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={
                      Number(
                        BigInt(budget.used_bps ?? "0") > 10000n
                          ? 10000n
                          : BigInt(budget.used_bps ?? "0"),
                      ) / 100
                    }
                    aria-valuetext={fenToYuan(budget.used_bps ?? "0") + "%"}
                  >
                    <span
                      style={{
                        width:
                          Number(
                            BigInt(budget.used_bps ?? "0") > 10000n
                              ? 10000n
                              : BigInt(budget.used_bps ?? "0"),
                          ) /
                            100 +
                          "%",
                      }}
                    />
                  </div>
                  <small>
                    已用 {fenToYuan(budget.used_bps ?? "0")}% · 截至{" "}
                    {data?.as_of}
                  </small>
                  {budget.net_expense_fen &&
                    BigInt(budget.net_expense_fen) < 0n && (
                      <small>当月净退款，已用按零计算，不增加额度。</small>
                    )}
                </>
              ) : (
                <p>
                  {budget.status === "future"
                    ? "未到预算月份，尚未开始计算。"
                    : "存在无法分配的历史汇总，额度使用情况暂不可计算。"}
                </p>
              )}
              <div className="row-actions">
                <button
                  className="text-button"
                  disabled={!enabled}
                  onClick={() => openEditor(budget.category_id)}
                >
                  调整额度
                </button>
                <button
                  className="text-button danger"
                  disabled={!enabled}
                  onClick={() =>
                    void act(async () => {
                      await request(
                        "/budgets/" + month + "/" + budget.category_id,
                        "PUT",
                        { limit_fen: null, revision: budget.revision },
                      );
                      setNotice("该分类预算已移除，额度信息已隐藏。");
                    })
                  }
                >
                  移除{budget.category_name}预算
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
      {editing && (
        <div className="budget-editor">
          <form className="form-grid" onSubmit={save}>
            <label>
              预算分类
              <select
                value={selected}
                disabled={!enabled}
                onChange={(e) => openEditor(e.target.value)}
              >
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              月预算（元）
              <input
                inputMode="decimal"
                required
                value={amount}
                disabled={!enabled}
                placeholder="填写正金额"
                onChange={(e) => setAmount(e.target.value)}
              />
            </label>
            <div className="form-footer">
              <button disabled={!enabled || !selected}>保存分类预算</button>
              <small>
                退款抵减当月支出，已用最低为零；超支后仍可正常记账。
              </small>
            </div>
          </form>
          <div className="budget-copy">
            <button
              className="secondary"
              disabled={!enabled}
              onClick={() =>
                void act(async () => {
                  const result = await request<{ copied: number }>(
                    "/budgets/" + month + "/copy-previous",
                    "POST",
                    { ledger_revision: data!.ledger_revision },
                  );
                  setNotice(
                    "已沿用上月 " +
                      result.copied +
                      " 个分类预算，已有额度保持不变。",
                  );
                })
              }
            >
              沿用上月预算
            </button>
            <small>仅补充本月未设置的分类，不覆盖已有额度。</small>
          </div>
        </div>
      )}
    </section>
  );
}
