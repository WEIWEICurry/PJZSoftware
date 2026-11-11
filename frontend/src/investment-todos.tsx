"use client";
import { useEffect, useState } from "react";
import type { components } from "./api-schema";
import { request } from "./api";

type Page = components["schemas"]["InvestmentPage"];
export type InvestmentTodo = components["schemas"]["InvestmentTodo"];
type Report = components["schemas"]["InvestmentTodos"];
const categories = [
  { kind: "recurring", name: "定投待核对", unit: "条" },
  { kind: "missing_price", name: "缺少有效估值", unit: "个标的" },
  { kind: "stale_price", name: "估值超过 7 天", unit: "个标的" },
  { kind: "unknown_cost", name: "持仓成本待补齐", unit: "组持仓" },
] as const;
export function InvestmentTodos({
  page,
  disabled,
  open,
}: {
  page: Page;
  disabled: boolean;
  open: (todo: InvestmentTodo) => void;
}) {
  const [retry, setRetry] = useState(0);
  const [kind, setKind] = useState<InvestmentTodo["kind"] | null>(null);
  const [state, setState] = useState<{
    basis: Page;
    data: Report | null;
    error: string;
  } | null>(null);
  useEffect(() => {
    let current = true;
    request<Report>("/investments/todos")
      .then((data) => {
        if (current) setState({ basis: page, data, error: "" });
      })
      .catch((e: Error) => {
        if (current) setState({ basis: page, data: null, error: e.message });
      });
    return () => {
      current = false;
    };
  }, [page, retry]);
  const current = state?.basis === page ? state : null;
  const data = current?.data;
  const activeKind =
    kind ??
    categories.find((category) =>
      data?.items.some((item) => item.kind === category.kind),
    )?.kind;
  const tasks = data?.items.filter((item) => item.kind === activeKind) ?? [];
  return (
    <section className="card panel investment-todos" aria-label="投资待办">
      <div className="investment-todos-heading">
        <h2>投资待办</h2>
        <button
          type="button"
          className="secondary"
          disabled={disabled || !current}
          onClick={() => {
            setState(null);
            setRetry((n) => n + 1);
          }}
        >
          刷新待办
        </button>
      </div>
      {!current && <p aria-live="polite">正在读取投资待办…</p>}
      {current?.error && (
        <p className="alert error">
          待办读取失败，请点击刷新待办重试。{current.error}
        </p>
      )}
      {data && (
        <>
          <div className="investment-todo-counts">
            {categories.map((category) => {
              const count = data.items
                .filter((item) => item.kind === category.kind)
                .reduce((sum, item) => sum + item.count, 0);
              return (
                <button
                  type="button"
                  className="secondary"
                  key={category.kind}
                  disabled={disabled || !count}
                  aria-pressed={activeKind === category.kind}
                  onClick={() => setKind(category.kind)}
                >
                  <span>{category.name}</span>
                  <strong>{count}</strong>
                  <small>{category.unit}</small>
                </button>
              );
            })}
          </div>
          {!data.items.length ? (
            <p>当前没有待处理事项。</p>
          ) : (
            <details className="investment-todo-list" open>
              <summary>
                {categories.find((category) => category.kind === activeKind)
                  ?.name ?? "待办明细"}{" "}
                · {tasks.length} 项
              </summary>
              {tasks.length ? (
                tasks.map((item) => (
                  <div
                    key={item.kind + item.id}
                    className="investment-todo-row"
                  >
                    <div>
                      <strong>{item.title}</strong>
                      {item.kind === "recurring" && (
                        <span> · {item.count} 条待核对</span>
                      )}
                      <small>{item.detail}</small>
                    </div>
                    <button
                      type="button"
                      className="secondary"
                      disabled={disabled}
                      onClick={() => open(item)}
                    >
                      {item.kind === "recurring"
                        ? "查看待核对项"
                        : item.kind === "unknown_cost"
                          ? "查看持仓记录"
                          : "去更新估值"}
                    </button>
                  </div>
                ))
              ) : (
                <p>这类待办已处理完。</p>
              )}
            </details>
          )}
          <p className="footnote">
            全部账户 · 统计截至 {data.as_of} · 账本版本 {data.revision}
            。定投统计已生成草稿；估值按 7 个自然日提示，可按需要更新。
          </p>
        </>
      )}
    </section>
  );
}
