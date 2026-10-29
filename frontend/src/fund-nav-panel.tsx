"use client";
import { useState } from "react";
import type { components } from "./api-schema";
import { request } from "./api";
import { localDay } from "./money";
type Preview = components["schemas"]["NavPreview"];
export function FundNavPanel({
  instruments,
  saved,
}: {
  instruments: components["schemas"]["InstrumentOutput"][];
  saved: () => Promise<void>;
}) {
  const [enabled, setEnabled] = useState(false);
  const [asset, setAsset] = useState("");
  const [start, setStart] = useState(localDay().slice(0, 7) + "-01");
  const [end, setEnd] = useState(localDay());
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function load() {
    setBusy(true);
    setMessage("");
    setPreview(null);
    try {
      setPreview(
        await request<Preview>("/fund-nav/preview", "POST", {
          instrument_id: asset,
          start,
          end,
          enabled,
        }),
      );
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function save() {
    if (!preview) return;
    setBusy(true);
    setMessage("");
    try {
      const result = await request<components["schemas"]["NavImported"]>(
        "/fund-nav/import",
        "POST",
        { token: preview.token },
      );
      setPreview(null);
      await saved();
      setMessage(
        `已导入 ${result.imported} 条，跳过已有 ${result.skipped} 条。`,
      );
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="card panel" aria-label="联网基金净值">
      <h2>联网基金净值（可选）</h2>
      <p className="footnote">
        获取最新已公布单位净值及历史净值，非盘中实时估值。仅向天天基金发送基金代码与日期范围，数据源可见
        IP；不发送账户、余额或份额。无后台自动请求，离开此页后默认关闭。
      </p>
      <label>
        <input
          type="checkbox"
          checked={enabled}
          disabled={busy}
          onChange={(e) => {
            setEnabled(e.target.checked);
            setPreview(null);
            setMessage("");
          }}
        />
        启用本次联网查询
      </label>
      {enabled && (
        <>
          <fieldset disabled={busy} className="investment-report-controls">
            <label>
              查询基金
              <select
                value={asset}
                onChange={(e) => {
                  setAsset(e.target.value);
                  setPreview(null);
                }}
              >
                <option value="">请选择基金</option>
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
              净值开始日期
              <input
                type="date"
                value={start}
                max={localDay()}
                onChange={(e) => {
                  setStart(e.target.value);
                  setPreview(null);
                }}
              />
            </label>
            <label>
              净值结束日期
              <input
                type="date"
                value={end}
                max={localDay()}
                onChange={(e) => {
                  setEnd(e.target.value);
                  setPreview(null);
                }}
              />
            </label>
          </fieldset>
          <button
            disabled={busy || !asset || !start || !end || start > end}
            onClick={() => void load()}
          >
            获取净值预览
          </button>
          <p className="footnote">
            一次最多 366
            天。已有日期（含手动和作废价格）全部跳过，不覆盖。来源与抓取时间保留在本地审计中；成功后仍可在手动估值中修正。
          </p>
          {preview && (
            <>
              <p>
                来源：{preview.source} · 获取时间：{preview.fetched_at} ·{" "}
                {preview.rows.length} 条 · 预览 5 分钟内有效
              </p>
              <div className="table-scroll">
                <table aria-label="净值导入预览">
                  <thead>
                    <tr>
                      <th>净值日期</th>
                      <th>单位净值</th>
                      <th>导入状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.rows.map((r) => (
                      <tr key={r.price_date}>
                        <td>{r.price_date}</td>
                        <td>{r.price}</td>
                        <td>{r.exists ? "已有，将跳过" : "可导入"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <button
                disabled={busy || !preview.rows.some((r) => !r.exists)}
                onClick={() => void save()}
              >
                确认导入净值
              </button>
              <button
                className="secondary"
                disabled={busy}
                onClick={() => setPreview(null)}
              >
                取消净值预览
              </button>
            </>
          )}
        </>
      )}
      {busy && <p role="status">正在处理净值…</p>}
      {message && <p role="status">{message}</p>}
    </section>
  );
}
