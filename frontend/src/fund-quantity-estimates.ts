"use client";
import { useEffect, useState } from "react";
import type { components } from "./api-schema";
import { request } from "./api";
import { localDay, yuanToFen } from "./money";

type Input = components["schemas"]["QuantityEstimateRow"];
type Output = components["schemas"]["QuantityEstimateOutput"];
export function quantityEstimateInput(
  id: string,
  instrument: string,
  day: string,
  amount: string,
  fee: string,
  mode: "net" | "gross",
): Input | null {
  if (!instrument || !day || day > localDay() || !amount.trim()) return null;
  try {
    const amountFen = yuanToFen(amount),
      costsFen = yuanToFen(fee.trim() || "0");
    if (BigInt(amountFen) <= 0n || BigInt(costsFen) < 0n) return null;
    return {
      id,
      instrument_id: instrument,
      nav_date: day,
      amount_fen: amountFen,
      costs_fen: costsFen,
      amount_mode: mode,
    };
  } catch {
    return null;
  }
}
export function useFundQuantityEstimates(rows: Input[], prices: unknown) {
  const signature = JSON.stringify(rows);
  const [state, setState] = useState<{
    signature: string;
    prices: unknown;
    rows: Output[];
    error: string;
  } | null>(null);
  useEffect(() => {
    const inputs: Input[] = JSON.parse(signature);
    if (!inputs.length) return;
    let current = true;
    const timer = setTimeout(() => {
      (async () => {
        const output: Output[] = [];
        for (let offset = 0; offset < inputs.length; offset += 100) {
          if (!current) return output;
          output.push(
            ...(await request<Output[]>(
              "/investments/quantity-estimates",
              "POST",
              { rows: inputs.slice(offset, offset + 100) },
            )),
          );
        }
        return output;
      })()
        .then((result) => {
          if (current) setState({ signature, prices, rows: result, error: "" });
        })
        .catch((e: Error) => {
          if (current)
            setState({ signature, prices, rows: [], error: e.message });
        });
    }, 180);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [signature, prices]);
  const current =
    state?.signature === signature && state.prices === prices ? state : null;
  const results = Object.fromEntries(
    (current?.rows ?? []).map((row) => [row.id, row]),
  );
  return {
    results,
    message: !rows.length
      ? "填写金额和净值日后自动计算。"
      : !current
        ? "正在按该日净值计算…"
        : current.error,
  };
}
export function estimateNote(result: Output | undefined, fallback: string) {
  if (!result) return fallback;
  if (result.quantity)
    return "按该日净值 " + result.price + " 预填，两位小数四舍五入，请核对。";
  return result.code === "ESTIMATE_NAV_MISSING"
    ? "本地暂无该日有效净值，请补价或手填份额。"
    : result.code === "ESTIMATE_TOO_SMALL"
      ? "计算不足 0.01 份，请手工核对。"
      : "请检查扣款和费用，或手工填写份额。";
}
