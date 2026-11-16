"use client";
import { useEffect, useRef, useState } from "react";
import type { components } from "./api-schema";
import { request } from "./api";
import { localDay } from "./money";
type Preview = components["schemas"]["NavPreview"];
type Imported = components["schemas"]["NavImported"];
type Result = {
  id: string;
  preview?: Preview;
  error?: string;
  imported?: Imported;
};
export function FundNavPanel({
  instruments,
  saved,
  initialInstrumentId,
}: {
  instruments: components["schemas"]["InstrumentOutput"][];
  saved: () => Promise<void>;
  initialInstrumentId?: string;
}) {
  const [enabled, setEnabled] = useState(false);
  const [selected, setSelected] = useState<string[]>(
    initialInstrumentId ? [initialInstrumentId] : [],
  );
  const [start, setStart] = useState(localDay().slice(0, 7) + "-01");
  const [end, setEnd] = useState(localDay());
  const [results, setResults] = useState<Result[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const funds = instruments.filter((i) => i.kind === "fund");
  const name = (id: string) => {
    const i = funds.find((i) => i.id === id);
    return i ? i.name + " · " + i.code : id;
  };
  const clear = () => {
    setResults([]);
    setMessage("");
  };
  const update = (r: Result) =>
    setResults((old) => [...old.filter((v) => v.id !== r.id), r]);
  async function load(ids = selected, retry = false) {
    setBusy(true);
    setMessage("");
    if (!retry) setResults([]);
    try {
      for (let n = 0; n < ids.length; n++) {
        if (!active.current) return;
        const id = ids[n];
        setMessage(`正在查询 ${n + 1}/${ids.length}：${name(id)}`);
        try {
          const preview = await request<Preview>("/fund-nav/preview", "POST", {
            instrument_id: id,
            start,
            end,
            enabled,
          });
          if (!active.current) return;
          update({ id, preview });
        } catch (e) {
          if (!active.current) return;
          update({ id, error: (e as Error).message });
        }
      }
      if (active.current)
        setMessage("查询完成，请逐项核对后确认导入；失败项可重查。");
    } finally {
      if (active.current) setBusy(false);
    }
  }
  async function save() {
    setBusy(true);
    setMessage("");
    let imported = 0,
      skipped = 0,
      failed = 0;
    try {
      for (const r of results.filter(
        (r) =>
          r.preview && !r.imported && r.preview.rows.some((v) => !v.exists),
      )) {
        if (!active.current) return;
        try {
          const value = await request<Imported>("/fund-nav/import", "POST", {
            token: r.preview!.token,
          });
          if (!active.current) return;
          imported += value.imported;
          skipped += value.skipped;
          update({ ...r, error: undefined, imported: value });
        } catch (e) {
          if (!active.current) return;
          failed++;
          update({ ...r, error: (e as Error).message });
        }
      }
      if (active.current) {
        setMessage(
          `已导入 ${imported} 条，跳过已有 ${skipped} 条。${failed ? ` ${failed} 只导入失败，可重查本项后重试。` : ""}`,
        );
        try {
          await saved();
        } catch {
          if (active.current)
            setMessage(`导入结果已保存，但页面刷新失败，请刷新投资查看。`);
        }
      }
    } finally {
      if (active.current) setBusy(false);
    }
  }
  return (
    <section className="card panel" aria-label="联网基金净值">
      <h2>联网基金净值（可选）</h2>
      <p className="footnote">
        获取最新已公布单位净值及历史净值，非盘中实时估值。仅向天天基金发送基金代码与日期范围，数据源可见
        IP；不发送账户、余额或份额。无后台自动请求，离开此页后默认关闭。
      </p>
      <button
        type="button"
        role="switch"
        aria-checked={enabled}
        disabled={busy}
        className={enabled ? "" : "secondary"}
        onClick={() => {
          setEnabled(!enabled);
          clear();
        }}
      >
        {enabled ? "本次联网已启用 · 点击关闭" : "启用本次联网查询"}
      </button>
      {enabled && (
        <>
          <fieldset disabled={busy} className="investment-report-controls">
            <label>
              查询基金（快捷单选）
              <select
                value={selected.length === 1 ? selected[0] : ""}
                onChange={(e) => {
                  setSelected(e.target.value ? [e.target.value] : []);
                  clear();
                }}
              >
                <option value="">请选择，或在下方多选</option>
                {funds.map((i) => (
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
                  clear();
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
                  clear();
                }}
              />
            </label>
          </fieldset>
          <fieldset disabled={busy}>
            <legend>批量选择基金（已选 {selected.length}/10）</legend>
            <div className="recurring-actions">
              <button
                className="secondary"
                onClick={() => {
                  setSelected(funds.slice(0, 10).map((f) => f.id));
                  clear();
                }}
              >
                选择前10只基金
              </button>
              <button
                className="secondary"
                onClick={() => {
                  setSelected([]);
                  clear();
                }}
              >
                清空基金选择
              </button>
            </div>
            <div className="nav-fund-options">
              {funds.map((i) => (
                <label key={i.id}>
                  <input
                    type="checkbox"
                    checked={selected.includes(i.id)}
                    disabled={!selected.includes(i.id) && selected.length >= 10}
                    onChange={(e) => {
                      setSelected(
                        e.target.checked
                          ? [...selected, i.id]
                          : selected.filter((id) => id !== i.id),
                      );
                      clear();
                    }}
                  />
                  {i.name} · {i.code}
                </label>
              ))}
            </div>
          </fieldset>
          <button
            disabled={busy || !selected.length || !start || !end || start > end}
            onClick={() => void load()}
          >
            获取净值预览
          </button>
          <p className="footnote">
            最多10只，按顺序查询，每只最多366天。逐基金独立导入，部分失败不影响其他成功项。有效价格跳过；已作废记录确认后恢复为联网净值并保留修订。预览五分钟有效，过期请重查本项。
          </p>
          {results.map((r) => (
            <div key={r.id} className="preview">
              <h3>{name(r.id)}</h3>
              {r.error && <p>{r.error}</p>}
              {r.imported && (
                <p>
                  已导入 {r.imported.imported} 条，跳过 {r.imported.skipped}{" "}
                  条。
                </p>
              )}
              {r.preview && (
                <>
                  <p>
                    来源：{r.preview.source} · 获取时间：{r.preview.fetched_at}{" "}
                    · {r.preview.rows.length} 条 · 预览 5 分钟内有效
                  </p>
                  {!r.preview.rows.length && (
                    <p>
                      所选日期范围内暂无已公布净值，请扩大日期范围或稍后查询；非交易日或
                      QDII 净值披露延迟时可能没有数据。
                    </p>
                  )}
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
                        {r.preview.rows.map((v) => (
                          <tr key={v.price_date}>
                            <td>{v.price_date}</td>
                            <td>{v.price}</td>
                            <td>
                              {v.exists
                                ? "已有有效价格，将跳过"
                                : v.restore_void
                                  ? "恢复已作废记录"
                                  : "可导入"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
              {!r.imported && (
                <button
                  className="secondary"
                  disabled={busy}
                  onClick={() => void load([r.id], true)}
                >
                  重查本项
                </button>
              )}
            </div>
          ))}
          {!!results.length && (
            <div className="recurring-actions">
              <button
                disabled={
                  busy ||
                  !results.some(
                    (r) =>
                      r.preview &&
                      !r.imported &&
                      r.preview.rows.some((v) => !v.exists),
                  )
                }
                onClick={() => void save()}
              >
                确认导入净值
              </button>
              <button className="secondary" disabled={busy} onClick={clear}>
                取消净值预览
              </button>
            </div>
          )}
        </>
      )}
      {message && <p role="status">{message}</p>}
    </section>
  );
}
