"use client";

import { useEffect, useState } from "react";
import type { components } from "./api-schema";
import { request } from "./api";

/* The response contains only the fields used during review. */
export type ReceiptPreview = components["schemas"]["ReceiptPreview"];

export function ReceiptImport({
  disabled,
  apply,
}: {
  disabled: boolean;
  apply: (receipt: ReceiptPreview) => void;
}) {
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [image, setImage] = useState("");
  const [result, setResult] = useState<ReceiptPreview | null>(null);
  const [applied, setApplied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") setImage(reader.result);
    };
    reader.readAsDataURL(file);
    return () => {
      if (reader.readyState === FileReader.LOADING) reader.abort();
    };
  }, [file]);
  function clear() {
    setApplied(false);
    setFile(null);
    setImage("");
    setResult(null);
    setError("");
  }
  function choose(selected: File) {
    clear();
    if (
      !["image/png", "image/jpeg"].includes(selected.type) ||
      selected.size === 0 ||
      selected.size > 5 * 1024 * 1024
    ) {
      setError("请选择不超过 5 MB 的 PNG 或 JPG 截图。");
      return;
    }
    setFile(selected);
  }
  async function recognize() {
    if (!file || busy || disabled) return;
    setApplied(false);
    setBusy(true);
    setResult(null);
    setError("");
    const body = new FormData();
    body.append("file", file, "receipt");
    try {
      setResult(
        await request<ReceiptPreview>(
          "/investments/receipt-preview",
          "POST",
          body,
        ),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "识别失败，请重试。");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="receipt-import">
      <button
        type="button"
        className="secondary"
        disabled={disabled || busy}
        aria-expanded={open}
        onClick={() => {
          if (open) clear();
          setOpen(!open);
        }}
      >
        {open ? "关闭截图识别" : "从截图填入"}
      </button>
      {open && (
        <section aria-label="截图识别核对" className="receipt-review">
          <div
            className="receipt-paste"
            tabIndex={0}
            aria-label="截图粘贴区"
            onPaste={(event) => {
              const pasted = event.clipboardData.files[0];
              if (pasted && !busy && !disabled) {
                event.preventDefault();
                choose(pasted);
              }
            }}
          >
            点击此处后按 Ctrl+V
            粘贴截图，或选择文件。支持已确认的支付宝基金买入回执。
          </div>
          <label>
            选择截图
            <input
              type="file"
              accept="image/png,image/jpeg"
              disabled={disabled || busy}
              onChange={(event) => {
                const selected = event.currentTarget.files?.[0];
                if (selected) choose(selected);
                event.currentTarget.value = "";
              }}
            />
          </label>
          <button
            type="button"
            className="secondary"
            disabled={!file || disabled || busy}
            onClick={() => void recognize()}
          >
            识别截图
          </button>
          {busy && <p role="status">正在识别截图，首次使用需要加载本地模型…</p>}
          {error && (
            <p className="alert error" role="alert">
              {error}
            </p>
          )}
          {image && (
            <div className="receipt-comparison">
              {/* Local data URL for the selected file, with no image optimizer or network call. */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={image} alt="待核对的基金买入回执" />
              {result && (
                <div>
                  <dl>
                    {[
                      ["基金", result.product],
                      ["基金代码", result.code],
                      ["付款方式", result.payment_hint],
                      ["实际扣款（元）", result.amount],
                      ["手续费（元）", result.fee],
                      ["确认金额（元）", result.confirmed_amount],
                      ["确认份额", result.quantity],
                      ["确认净值", result.unit_nav],
                      [
                        "买入时间",
                        result.purchase_date &&
                          [result.purchase_date, result.purchase_time]
                            .filter(Boolean)
                            .join(" "),
                      ],
                      ["确认日期", result.confirmation_date],
                      [
                        "净值所属日",
                        result.nav_date_estimated
                          ? result.nav_date + "（推算）"
                          : result.nav_date,
                      ],
                    ].map(([label, value]) => (
                      <div key={label}>
                        <dt>{label}</dt>
                        <dd>{value ?? "待核对"}</dd>
                      </div>
                    ))}
                  </dl>
                  {result.warnings.map((warning) => (
                    <p className="alert" key={warning}>
                      {warning}
                    </p>
                  ))}
                  <button
                    type="button"
                    disabled={disabled || applied}
                    onClick={() => {
                      apply(result);
                      setApplied(true);
                    }}
                  >
                    {applied ? "已填入草稿" : "填入并替换当前草稿"}
                  </button>
                </div>
              )}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
