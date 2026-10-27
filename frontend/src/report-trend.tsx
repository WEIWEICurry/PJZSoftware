"use client";

import { useState, type CSSProperties } from "react";
import type { components } from "./api-schema";
import { money } from "./money";

type Point = components["schemas"]["TrendPoint"];
const valueLabel = (point: Point, value: string | null) =>
  point.status === "future"
    ? "未到日期"
    : value === null
      ? "缺少分日数据"
      : money(value);

export function ReportTrend({
  period,
  points,
}: {
  period: "week" | "month" | "year";
  points: Point[];
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [focused, setFocused] = useState<string | null>(null);
  const active =
    points.find((point) => point.start === (focused ?? selected)) ??
    points.findLast((point) => point.status !== "future") ??
    points[0];
  const maximum = points.reduce((result, point) => {
    for (const value of [point.income_fen, point.expense_fen]) {
      if (value !== null) {
        const n = BigInt(value) < 0n ? -BigInt(value) : BigInt(value);
        if (n > result) result = n;
      }
    }
    return result;
  }, 1n);
  const hasNegative = points.some((point) =>
    [point.income_fen, point.expense_fen].some(
      (value) => value !== null && BigInt(value) < 0n,
    ),
  );
  const height = (value: string) => {
    const n = BigInt(value) < 0n ? -BigInt(value) : BigInt(value);
    return Number((n * 10000n) / maximum) / (hasNegative ? 200 : 100);
  };
  return (
    <section className="card panel report-trend" aria-label="收支趋势">
      <div className="section-heading">
        <h2>{period === "year" ? "逐月" : "逐日"}收支趋势</h2>
        <span className="trend-key">
          <i className="income-key" />
          收入 <i className="expense-key" />
          净支出
        </span>
      </div>
      <p className="footnote">
        时间从左到右排列，正值向上、负值向下。悬停、点击或用键盘聚焦柱组可查看金额；缺少分日数据和未来日期不填零。较窄窗口可在图内左右滚动。
      </p>
      {active && (
        <div className="trend-detail" aria-live="polite">
          <strong>
            {active.start}
            {active.end !== active.start ? " ～ " + active.end : ""}
          </strong>
          <span>收入 {valueLabel(active, active.income_fen)}</span>
          <span>净支出 {valueLabel(active, active.expense_fen)}</span>
        </div>
      )}
      <div
        className="trend-chart"
        style={
          { "--zero-px": hasNegative ? "100px" : "200px" } as CSSProperties
        }
      >
        <span className="trend-zero" aria-hidden="true">
          0
        </span>
        <div
          className="trend-scroller"
          tabIndex={0}
          role="group"
          aria-label="横向收支趋势图"
        >
          <div
            className={"trend-plot " + period}
            style={{ "--trend-count": points.length } as CSSProperties}
          >
            {points.map((point) => (
              <button
                type="button"
                key={point.start}
                className={"trend-row " + point.status}
                aria-pressed={point.start === active?.start}
                aria-label={`${point.start}，收入 ${valueLabel(point, point.income_fen)}，净支出 ${valueLabel(point, point.expense_fen)}`}
                onPointerMove={(event) => {
                  if (event.movementX || event.movementY) {
                    setFocused(null);
                    setSelected(point.start);
                  }
                }}
                onFocus={() => setFocused(point.start)}
                onBlur={() => setFocused(null)}
                onClick={() => {
                  setFocused(null);
                  setSelected(point.start);
                }}
              >
                <span className="trend-bars">
                  {(["income_fen", "expense_fen"] as const).map(
                    (field, index) => (
                      <span className="trend-lane" key={field}>
                        {point[field] === null ? (
                          <span className="trend-gap" aria-hidden="true">
                            {point.status === "future" ? "—" : "?"}
                          </span>
                        ) : (
                          <span
                            aria-hidden="true"
                            className={
                              (index ? "expense-bar" : "income-bar") +
                              (BigInt(point[field]!) < 0n
                                ? " negative"
                                : " positive")
                            }
                            style={{ height: height(point[field]!) + "%" }}
                          />
                        )}
                      </span>
                    ),
                  )}
                </span>
                <span className="trend-label">
                  {period === "year"
                    ? Number(point.start.slice(5, 7)) + "月"
                    : point.start.slice(5)}
                </span>
                <span className="trend-state">
                  {point.status === "future"
                    ? "未到"
                    : point.status === "unallocated"
                      ? "缺失"
                      : ""}
                </span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
