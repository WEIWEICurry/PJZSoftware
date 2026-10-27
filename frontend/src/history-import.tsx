"use client";

import { useEffect, useState } from "react";
import { request } from "./api";
import type { components } from "./api-schema";
import { money } from "./money";

type Category = components["schemas"]["CategoryOutput"];
type Preview = components["schemas"]["HistoryPreview"];
type Batch = components["schemas"]["BatchOutput"];
type Detail = components["schemas"]["BatchDetail"];
type Row = components["schemas"]["HistoryRow"];
const states = {
  ready: "可导入",
  unmapped: "待映射",
  duplicate: "重复，已导入",
  conflict: "期间重叠，需核对",
};

export function HistoryImport({
  available,
  changed,
}: {
  available: boolean;
  changed: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<Preview | null>(null);
  const [dirty, setDirty] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const [batches, setBatches] = useState<Batch[]>([]);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const enabled = available && !busy;
  useEffect(() => {
    if (!available) return;
    let cancelled = false;
    Promise.all([
      request<Category[]>("/categories"),
      request<Batch[]>("/history/batches"),
    ])
      .then(([nextCategories, nextBatches]) => {
        if (!cancelled) {
          setCategories(nextCategories);
          setBatches(nextBatches);
        }
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [available]);
  async function act(operation: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await operation();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败，请重试。");
    } finally {
      setBusy(false);
    }
  }
  async function inspect(nextFile: File, nextMapping: Record<string, string>) {
    setPreview(null);
    setAcknowledged(false);
    await act(async () => {
      const form = new FormData();
      form.append("file", nextFile);
      form.append("mapping", JSON.stringify(nextMapping));
      const result = await request<Preview>("/history/preview", "POST", form);
      setPreview(result);
      setDirty(false);
      setMapping(
        Object.fromEntries(
          result.rows.map((row) => [row.mapping_key, row.category_id || ""]),
        ),
      );
    });
  }
  async function confirm() {
    if (!preview) return;
    await act(async () => {
      await request("/history/commit", "POST", {
        preview_token: preview.preview_token,
        acknowledge_coverage: true,
      });
      setBatches(await request<Batch[]>("/history/batches"));
      setNotice(
        preview.action === "import"
          ? "历史汇总已导入，账户余额未改变。"
          : "批次已撤销，原始来源保留，相关明细恢复参与统计。",
      );
      setPreview(null);
      setDetail(null);
      setAcknowledged(false);
      changed();
    });
  }
  function rowsTable(rows: Row[], editable: boolean, showImpact = false) {
    const totals = new Map<string, bigint>();
    for (const row of rows) {
      const label =
        row.period_start +
        " ～ " +
        row.period_end +
        " · " +
        (row.direction === "expense" ? "支出" : "收入");
      totals.set(label, (totals.get(label) ?? 0n) + BigInt(row.amount_fen));
    }
    return (
      <>
        <div className="history-period-totals">
          {Array.from(totals, ([label, total]) => (
            <p key={label}>
              {label}合计：<strong>{money(total.toString())}</strong>
            </p>
          ))}
        </div>
        <div className="table-scroll history-table">
          <table>
            <thead>
              <tr>
                <th>期间／方向</th>
                <th>原分类 → 账本分类</th>
                <th className="amount-column">汇总金额</th>
                <th>范围内有效明细</th>
                <th>来源／检查</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={row.mapping_key + row.period_start + index}>
                  <td>
                    {row.period_start} ～ {row.period_end}
                    <small>
                      {row.direction === "expense" ? "支出" : "收入"} ·
                      仅含所列日期，无逐日数据
                    </small>
                  </td>
                  <td>
                    {row.source_category}
                    {editable ? (
                      <select
                        aria-label={
                          "映射 " + row.source_category + " " + row.direction
                        }
                        value={
                          mapping[row.mapping_key] ?? row.category_id ?? ""
                        }
                        disabled={!enabled}
                        onChange={(e) => {
                          setMapping({
                            ...mapping,
                            [row.mapping_key]: e.target.value,
                          });
                          setDirty(true);
                          setAcknowledged(false);
                        }}
                      >
                        <option value="">请选择账本分类</option>
                        {categories
                          .filter((c) => c.direction === row.direction)
                          .map((c) => (
                            <option key={c.id} value={c.id}>
                              {c.name}
                            </option>
                          ))}
                      </select>
                    ) : (
                      <small>→ {row.category_name}</small>
                    )}
                  </td>
                  <td className="amount-column">{money(row.amount_fen)}</td>
                  <td>
                    {row.detail_count} 条 · 净额 {money(row.detail_fen)}
                    <small>资金流水保留，覆盖范围内不重复统计</small>
                    {showImpact && (
                      <small>
                        本项报表变化：
                        {BigInt(row.report_delta_fen) > 0n ? "+" : ""}
                        {money(row.report_delta_fen)}
                      </small>
                    )}
                  </td>
                  <td>
                    <span>{editable ? states[row.status] : "来源留存"}</span>
                    <small>
                      {row.source_refs.length
                        ? row.source_refs.join("、")
                        : "原始 JSON 文件"}
                    </small>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </>
    );
  }
  return (
    <section
      className="card panel full history-import"
      aria-label="历史汇总导入"
    >
      <div className="section-heading">
        <div>
          <span className="section-label">历史迁移</span>
          <h2>先核对，再导入旧账</h2>
        </div>
      </div>
      <p>
        导入已整理的分类汇总
        JSON，不需要选择支付账户，不改变账户余额。重复或重叠内容会阻止导入。
      </p>
      <label htmlFor="history-file">选择历史汇总 JSON（最多 512 KB）</label>
      <input
        id="history-file"
        type="file"
        accept=".json,application/json"
        disabled={!enabled}
        onChange={(e) => {
          const next = e.target.files?.[0];
          e.target.value = "";
          setDetail(null);
          setPreview(null);
          setMapping({});
          setFile(next ?? null);
          if (next) void inspect(next, {});
        }}
      />
      <p className="footnote">
        支持已整理的鲨鱼记账格式。截图原件继续保存在原目录；备份包含 JSON
        来源与汇总，不包含截图图片。当前不做自动 OCR。
      </p>
      {error && (
        <div role="alert" className="alert error">
          {error}
        </div>
      )}
      {notice && (
        <div role="status" className="alert success">
          {notice}
        </div>
      )}
      {preview && (
        <div className="history-preview" aria-label="历史导入预览">
          <h3>
            {preview.action === "withdraw" ? "撤销影响预览" : "导入预览"} ·{" "}
            {preview.filename}
          </h3>
          {rowsTable(preview.rows, preview.action === "import", true)}
          {preview.action === "import" && (
            <>
              <p className="footnote">
                待映射项请选择已有同方向分类。没有合适分类时，先在日常账本添加分类，再重新选择文件。
              </p>
              <button
                className="secondary"
                disabled={!enabled || !file}
                onClick={() => file && void inspect(file, mapping)}
              >
                按当前分类重新预览
              </button>
            </>
          )}
          <details className="source-hashes">
            <summary>查看来源校验信息</summary>
            <code>文件 SHA-256：{preview.file_hash}</code>
            <code>内容 SHA-256：{preview.canonical_hash}</code>
          </details>
          <p className="alert">
            {preview.action === "import"
              ? "确认后，以上期间和分类的报表使用汇总金额，范围内的逐笔收支（含退款、手续费）不再重复计入；账户余额仍按原流水计算。请核对截止日期，尤其是同一天后续补记的流水。"
              : "撤销后，以上汇总退出统计，范围内的有效明细按所列净额恢复统计。原始批次和来源仍保留，账户余额不变。"}
          </p>
          {(!preview.can_confirm || dirty) && (
            <p className="footnote">
              {dirty
                ? "分类已修改，请重新预览。"
                : "存在待映射、重复或重叠内容，请核对；不会自动覆盖已有汇总。"}
            </p>
          )}
          <label className="coverage-check">
            <input
              type="checkbox"
              checked={acknowledged}
              disabled={!enabled || dirty || !preview.can_confirm}
              onChange={(e) => setAcknowledged(e.target.checked)}
            />
            我已核对期间、金额及明细覆盖规则
          </label>
          <div className="row-actions">
            <button
              disabled={
                !enabled || !preview.can_confirm || dirty || !acknowledged
              }
              onClick={() => void confirm()}
            >
              {preview.action === "import"
                ? "确认导入历史汇总"
                : "确认撤销此批次"}
            </button>
            <button
              className="secondary"
              disabled={!enabled}
              onClick={() => {
                setPreview(null);
                setAcknowledged(false);
              }}
            >
              取消预览
            </button>
          </div>
        </div>
      )}
      <h3>导入批次</h3>
      {!batches.length && <p className="footnote">还没有导入历史汇总。</p>}
      <div className="history-batches">
        {batches.map((batch) => (
          <div key={batch.id} className="history-batch">
            <div>
              <strong>{batch.filename}</strong>
              <small>
                {batch.status === "active" ? "生效中" : "已撤销"} ·{" "}
                {batch.created_at.slice(0, 10)}
              </small>
            </div>
            <div className="row-actions">
              <button
                className="text-button"
                disabled={!enabled}
                onClick={() =>
                  void act(async () => {
                    setDetail(
                      await request<Detail>("/history/batches/" + batch.id),
                    );
                  })
                }
              >
                查看明细
              </button>
              {batch.status === "active" && (
                <button
                  className="text-button danger"
                  disabled={!enabled}
                  onClick={() =>
                    void act(async () => {
                      setPreview(
                        await request<Preview>(
                          "/history/batches/" + batch.id + "/withdraw-preview",
                          "POST",
                        ),
                      );
                      setDetail(null);
                      setAcknowledged(false);
                      setDirty(false);
                    })
                  }
                >
                  预览撤销
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
      {detail && (
        <div className="history-detail">
          <h3>
            批次明细 · {detail.filename} ·{" "}
            {detail.status === "active" ? "生效中" : "已撤销"}
          </h3>
          {rowsTable(detail.rows, false)}
          <code>文件 SHA-256：{detail.file_hash}</code>
          <code>内容 SHA-256：{detail.canonical_hash}</code>
          <p className="footnote">
            范围内明细为当前账本的有效记录；撤销批次不再覆盖统计。来源内容已随账本保存。
          </p>
        </div>
      )}
    </section>
  );
}
