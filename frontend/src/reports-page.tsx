"use client";

import { useEffect, useState } from "react";
import { raw, request } from "./api";
import type { components } from "./api-schema";
import { BudgetPanel } from "./budget-panel";
import { fenToYuan, localDay, money } from "./money";

type Report = components["schemas"]["ReportOutput"];
type Entries = components["schemas"]["ReportEntryPage"];
type Period = Report["period"];
const labels: Record<Period, string> = {
  day: "日",
  week: "周",
  month: "月",
  year: "年",
};
const amount = (value: string | null) =>
  value === null ? "待核对" : money(value);
const signed = (value: string) =>
  BigInt(value) > 0n ? "+" + money(value) : money(value);
function isoDay(value: Date) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}

export function ReportsPage({
  available,
  changed,
}: {
  available: boolean;
  changed: () => void;
}) {
  const [period, setPeriod] = useState<Period>("month");
  const [anchor, setAnchor] = useState(localDay());
  const [loadedReport, setLoadedReport] = useState<{
    key: string;
    data: Report;
  } | null>(null);
  const [loadedEntries, setLoadedEntries] = useState<{
    key: string;
    data: Entries;
  } | null>(null);
  const [direction, setDirection] = useState<"income" | "expense">("expense");
  const [entryCategory, setEntryCategory] = useState("");
  const [entryDirection, setEntryDirection] = useState("");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [exporting, setExporting] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const reportKey = JSON.stringify([period, anchor, refresh]);
  const entriesKey = JSON.stringify([
    period,
    anchor,
    entryCategory,
    entryDirection,
    offset,
    refresh,
  ]);
  const data = loadedReport?.key === reportKey ? loadedReport.data : null;
  const entries =
    loadedEntries?.key === entriesKey
      ? loadedEntries.data
      : { items: [], total: 0 };
  useEffect(() => {
    if (!available) return;
    let cancelled = false;
    request<Report>("/reports?" + new URLSearchParams({ period, anchor }))
      .then((result) => {
        if (!cancelled) setLoadedReport({ key: reportKey, data: result });
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [available, period, anchor, refresh, reportKey]);
  useEffect(() => {
    if (!available) return;
    let cancelled = false;
    const params = new URLSearchParams({
      period,
      anchor,
      offset: String(offset),
      limit: "20",
    });
    if (entryCategory) params.set("category_id", entryCategory);
    if (entryDirection) params.set("direction", entryDirection);
    request<Entries>("/reports/entries?" + params)
      .then((result) => {
        if (!cancelled) setLoadedEntries({ key: entriesKey, data: result });
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [
    available,
    period,
    anchor,
    entryCategory,
    entryDirection,
    offset,
    refresh,
    entriesKey,
  ]);
  function choosePeriod(next: Period) {
    setError("");
    setPeriod(next);
    setEntryCategory("");
    setOffset(0);
  }
  function chooseAnchor(next: string) {
    setError("");
    if (next) {
      setAnchor(next);
      setEntryCategory("");
      setOffset(0);
    }
  }
  function navigate(step: number) {
    if (!data) return;
    const date = new Date(data.current.start + "T12:00:00");
    if (period === "year") date.setFullYear(date.getFullYear() + step);
    else if (period === "month") date.setMonth(date.getMonth() + step);
    else date.setDate(date.getDate() + step * (period === "week" ? 7 : 1));
    chooseAnchor(isoDay(date));
  }
  async function download() {
    setExporting(true);
    setError("");
    try {
      const params = new URLSearchParams({ period, anchor });
      if (entryCategory) params.set("category_id", entryCategory);
      if (entryDirection) params.set("direction", entryDirection);
      const blob = await (await raw("/reports/export?" + params)).blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `PJZ-${period}-${anchor}.csv`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "导出失败，请重试。");
    } finally {
      setExporting(false);
    }
  }
  const categories =
    data?.current.categories.filter((row) => row.direction === direction) ?? [];
  const maximum = (data?.trend ?? []).reduce((largest, row) => {
    for (const value of [row.income_fen, row.expense_fen]) {
      if (value !== null) {
        const n = BigInt(value) < 0n ? -BigInt(value) : BigInt(value);
        if (n > largest) largest = n;
      }
    }
    return largest;
  }, 1n);
  const width = (value: string) => {
    const n = BigInt(value) < 0n ? -BigInt(value) : BigInt(value);
    return Number((n * 10000n) / maximum) / 100;
  };
  return (
    <div className="reports-workspace">
      <section className="card panel report-controls" aria-label="报表期间选择">
        <div className="period-buttons" role="group" aria-label="报表周期">
          {(Object.entries(labels) as [Period, string][]).map(
            ([value, label]) => (
              <button
                key={value}
                aria-pressed={period === value}
                className={period === value ? "" : "secondary"}
                disabled={!available}
                onClick={() => choosePeriod(value)}
              >
                {label}报表
              </button>
            ),
          )}
        </div>
        <div className="report-date-controls">
          <button
            className="secondary"
            disabled={!available || !data}
            onClick={() => navigate(-1)}
          >
            上一{labels[period]}
          </button>
          <label>
            选择日期
            <input
              type="date"
              max={localDay()}
              value={anchor}
              disabled={!available}
              onChange={(e) => chooseAnchor(e.target.value)}
            />
          </label>
          <button
            className="secondary"
            disabled={!available || !data || data.calendar_end >= localDay()}
            onClick={() => navigate(1)}
          >
            下一{labels[period]}
          </button>
          <button
            className="text-button"
            disabled={!available}
            onClick={() => chooseAnchor(localDay())}
          >
            返回当前{labels[period]}
          </button>
          <button
            className="text-button"
            disabled={!available}
            onClick={() => {
              setError("");
              setRefresh((v) => v + 1);
            }}
          >
            刷新报表
          </button>
          <button
            className="text-button"
            onClick={() =>
              document
                .getElementById("category-budgets")
                ?.scrollIntoView({ behavior: "smooth" })
            }
          >
            分类预算（选填）
          </button>
        </div>
        <p className="footnote">
          周一至周日；当前期间截至今天。只统计已记录资料，空白日期不代表实际没有收支。转账、借还本金、期初和余额校正不计收支。
        </p>
      </section>
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
      {!data && !error && <p role="status">正在计算报表…</p>}
      {data && (
        <>
          <div className="report-range">
            <h2>
              {data.current.start} ～ {data.current.end}
            </h2>
            <span>
              {data.current.day_count} 天 · {data.current.detail_count}{" "}
              条计入明细 · {data.current.historical_count} 项历史汇总
            </span>
          </div>
          {(data.current.income_fen === null ||
            data.current.expense_fen === null) && (
            <p className="alert report-incomplete">
              所选期间截取了历史汇总，缺少分日数据。未知方向显示待核对；可定位小计为收入{" "}
              {money(data.current.known_income_fen)}、支出{" "}
              {money(data.current.known_expense_fen)}，不能当作完整期间总额。
            </p>
          )}
          <div className="report-metrics">
            {(
              [
                ["收入", data.current.income_fen],
                ["净支出", data.current.expense_fen],
                ["结余", data.current.surplus_fen],
                ["日均净支出", data.current.daily_expense_fen],
              ] as const
            ).map(([label, value]) => (
              <div className="card metric" key={label}>
                <span>{label}</span>
                <strong>{amount(value)}</strong>
                {value === null && <small>历史汇总无法分配到所选期间</small>}
              </div>
            ))}
          </div>
          <section
            className="card panel report-comparison"
            aria-label="上期对比"
          >
            <h2>上期对比</h2>
            <p className="footnote">
              {data.previous
                ? `${data.previous.start} ～ ${data.previous.end}；未结束期间按相同经过天数比较，最长至上期末。`
                : "没有可比较的更早期间。"}
            </p>
            {data.previous &&
              (data.previous.income_fen === null ||
                data.previous.expense_fen === null) && (
                <p className="footnote">
                  上期截取了历史汇总，无法对齐分日金额的方向不计算变化。
                </p>
              )}
            <div className="comparison-grid">
              {data.changes.map((change) => (
                <div key={change.metric}>
                  <span>
                    {change.metric === "income"
                      ? "收入"
                      : change.metric === "expense"
                        ? "净支出"
                        : "结余"}
                    变化
                  </span>
                  <strong>
                    {change.delta_fen === null
                      ? "不可比较"
                      : signed(change.delta_fen)}
                  </strong>
                  <small>
                    {change.change_bps === null
                      ? "上期为零或资料不足，不计算比例"
                      : (BigInt(change.change_bps) > 0n ? "+" : "") +
                        fenToYuan(change.change_bps) +
                        "%"}
                  </small>
                </div>
              ))}
            </div>
          </section>
          <section className="card panel" aria-label="收支趋势">
            <div className="section-heading">
              <h2>{period === "year" ? "逐月" : "逐日"}收支趋势</h2>
              <span className="trend-key">
                <i className="income-key" />
                收入 <i className="expense-key" />
                净支出
              </span>
            </div>
            <p className="footnote">
              柱长按金额绝对值展示，负净支出代表退款净额；精确数值见表格。历史汇总无逐日数据时不拆分、不填零。
            </p>
            <div className="trend-list">
              {data.trend.map((point) => (
                <div className={"trend-row " + point.status} key={point.start}>
                  <span>
                    {period === "year"
                      ? point.start.slice(0, 7)
                      : point.start.slice(5)}
                  </span>
                  <div className="trend-bars">
                    {(["income_fen", "expense_fen"] as const).map(
                      (field, index) => (
                        <div key={field} className="trend-track">
                          {point[field] !== null ? (
                            <span
                              className={index ? "expense-bar" : "income-bar"}
                              style={{ width: width(point[field]!) + "%" }}
                              title={money(point[field]!)}
                            />
                          ) : (
                            <small>
                              {point.status === "future"
                                ? "未到日期"
                                : "缺少分日数据"}
                            </small>
                          )}
                        </div>
                      ),
                    )}
                  </div>
                  <div className="trend-values">
                    {point.status === "future" ? (
                      "—"
                    ) : (
                      <>
                        <span>{amount(point.income_fen)}</span>
                        <span>{amount(point.expense_fen)}</span>
                      </>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>
          {data.history_ranges.length > 0 && (
            <details className="card panel report-sources">
              <summary>
                历史汇总来源与覆盖范围（{data.history_ranges.length} 项）
              </summary>
              <p className="footnote">
                范围外仅统计已有明细，不代表无收支。被覆盖的{" "}
                {data.current.covered_count}{" "}
                条明细保留资金作用，但不重复加入报表。
              </p>
              <ul>
                {data.history_ranges.map((range, index) => (
                  <li key={index}>
                    {range.start} ～ {range.end} · {range.category_name} ·{" "}
                    {range.direction === "income" ? "收入" : "支出"}原汇总{" "}
                    {money(range.amount_fen)} ·{" "}
                    {range.allocated ? "期间内计入" : "无法分配到所选期间"} ·{" "}
                    {range.source}
                  </li>
                ))}
              </ul>
            </details>
          )}
          <section className="card panel" aria-label="分类收支排行">
            <div className="section-heading">
              <h2>分类排行</h2>
              <div className="period-buttons">
                <button
                  className={direction === "expense" ? "" : "secondary"}
                  aria-pressed={direction === "expense"}
                  onClick={() => setDirection("expense")}
                >
                  支出分类
                </button>
                <button
                  className={direction === "income" ? "" : "secondary"}
                  aria-pressed={direction === "income"}
                  onClick={() => setDirection("income")}
                >
                  收入分类
                </button>
              </div>
            </div>
            <p className="footnote">
              按净额排行，占比以同方向正金额为分母；净退款不作为正消费。资料不足时不计算该方向占比。
            </p>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>分类</th>
                    <th className="amount-column">净额</th>
                    <th>正金额占比</th>
                    <th>构成</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {categories.map((row) => (
                    <tr key={row.category_id}>
                      <td>{row.category_name}</td>
                      <td className="amount-column">
                        {amount(row.amount_fen)}
                        {row.amount_fen === null && (
                          <small>可定位小计 {money(row.known_fen)}</small>
                        )}
                      </td>
                      <td>
                        {row.share_bps === null
                          ? "不可计算"
                          : fenToYuan(String(row.share_bps)) + "%"}
                        <div className="category-track">
                          <span
                            style={{ width: (row.share_bps ?? 0) / 100 + "%" }}
                          />
                        </div>
                      </td>
                      <td>
                        明细 {money(row.detail_fen)}
                        <small>可计入汇总 {money(row.historical_fen)}</small>
                      </td>
                      <td>
                        <button
                          className="text-button"
                          onClick={() => {
                            setEntryCategory(row.category_id);
                            setEntryDirection(row.direction);
                            setOffset(0);
                            document
                              .getElementById("report-records")
                              ?.scrollIntoView({ behavior: "smooth" });
                          }}
                        >
                          查看构成
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!categories.length && (
              <p className="empty-state">所选期间没有这类收支记录。</p>
            )}
          </section>
          <section
            id="report-records"
            className="card panel"
            aria-label="报表构成明细"
          >
            <div className="section-heading">
              <div>
                <h2>收支构成明细</h2>
                <span>共 {entries.total} 条来源记录（含覆盖凭证）</span>
              </div>
              <button
                disabled={!available || exporting}
                onClick={() => void download()}
              >
                {exporting ? "正在导出…" : "导出当前构成 CSV"}
              </button>
            </div>
            <div className="report-entry-filters">
              <label>
                构成方向
                <select
                  value={entryDirection}
                  onChange={(e) => {
                    setEntryDirection(e.target.value);
                    setEntryCategory("");
                    setOffset(0);
                  }}
                >
                  <option value="">全部收支</option>
                  <option value="expense">支出</option>
                  <option value="income">收入</option>
                </select>
              </label>
              <label>
                构成分类
                <select
                  value={entryCategory}
                  onChange={(e) => {
                    setEntryCategory(e.target.value);
                    setOffset(0);
                  }}
                >
                  <option value="">全部分类</option>
                  {data.current.categories
                    .filter(
                      (c) => !entryDirection || c.direction === entryDirection,
                    )
                    .map((c) => (
                      <option key={c.category_id} value={c.category_id}>
                        {c.category_name}
                      </option>
                    ))}
                </select>
              </label>
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>原记录期间</th>
                    <th>分类／账户</th>
                    <th>来源／备注</th>
                    <th className="amount-column">原金额</th>
                    <th className="amount-column">计入金额</th>
                    <th>状态</th>
                  </tr>
                </thead>
                <tbody>
                  {entries.items.map((row) => (
                    <tr key={row.id}>
                      <td>
                        {row.start}
                        {row.start !== row.end ? " ～ " + row.end : ""}
                      </td>
                      <td>
                        {row.category_name}
                        <small>{row.account_name || "无账户归属"}</small>
                      </td>
                      <td className="note-cell">
                        {row.source}
                        <small>{row.note}</small>
                      </td>
                      <td className="amount-column">{money(row.amount_fen)}</td>
                      <td className="amount-column">
                        {amount(row.counted_fen)}
                      </td>
                      <td>
                        {row.status === "included"
                          ? "计入"
                          : row.status === "covered"
                            ? "已被历史汇总覆盖"
                            : "原汇总无法分配"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!entries.items.length && (
              <p className="empty-state">当前筛选没有构成记录。</p>
            )}
            <div className="pagination">
              <button
                className="secondary"
                disabled={!offset}
                onClick={() => setOffset((v) => Math.max(0, v - 20))}
              >
                明细上一页
              </button>
              <span>第 {Math.floor(offset / 20) + 1} 页</span>
              <button
                className="secondary"
                disabled={offset + 20 >= entries.total}
                onClick={() => setOffset((v) => v + 20)}
              >
                明细下一页
              </button>
            </div>
          </section>
        </>
      )}
      <BudgetPanel available={available} changed={changed} />
    </div>
  );
}
