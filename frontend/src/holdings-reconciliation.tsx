"use client";

import { useEffect, useRef, useState } from "react";
import type { components } from "./api-schema";
import { request } from "./api";
import { DateStepper } from "./date-stepper";
import { localDay, money, yuanToFen } from "./money";
import { matchReceiptFund } from "./receipt-matching";
import { appendScreenshots, type ScreenshotFile } from "./screenshot-files";

type Page = components["schemas"]["InvestmentPage"];
type Account = components["schemas"]["AccountOutput"];
type Preview = components["schemas"]["HoldingPreview"];
type Report = components["schemas"]["HoldingComparisonOutput"];
type Input = components["schemas"]["HoldingComparisonInput"];
type Draft = {
  instrument: string;
  quantity: string;
  amount: string;
  pending: string;
  nav: string;
  navDate: string;
};
type Item = ScreenshotFile & {
  preview: Preview | null;
  draft: Draft | null;
  error: string;
  included: boolean;
  reviewed: boolean;
  navManual: boolean;
};
function suggestedDate(preview: Preview, day: string) {
  if (preview.nav_date) return preview.nav_date;
  if (!day || !preview.nav_month_day) return "";
  const year =
    Number(day.slice(0, 4)) - (preview.nav_month_day > day.slice(5) ? 1 : 0);
  const candidate = year + "-" + preview.nav_month_day;
  const date = new Date(candidate + "T00:00:00Z");
  return !Number.isNaN(date.getTime()) &&
    date.toISOString().slice(0, 10) === candidate
    ? candidate
    : "";
}
function inputRow(item: Item, asOf: string): Input["rows"][number] {
  const d = item.draft;
  if (
    !d ||
    !d.instrument ||
    !/^(0|[1-9]\d{0,11})(\.\d{1,8})?$/.test(d.quantity) ||
    (d.nav &&
      (!/^(0|[1-9]\d{0,11})(\.\d{1,8})?$/.test(d.nav) ||
        !/[1-9]/.test(d.nav))) ||
    (d.navDate && d.navDate > asOf)
  )
    throw new Error("请核对基金、非负份额、正净值及有效日期。");
  const amount = d.amount ? yuanToFen(d.amount) : null;
  const pending = d.pending ? yuanToFen(d.pending) : null;
  if (
    (amount !== null && BigInt(amount) < 0n) ||
    (pending !== null && BigInt(pending) < 0n)
  )
    throw new Error("金额不能为负数。");
  return {
    instrument_id: d.instrument,
    quantity: d.quantity,
    amount_fen: amount,
    pending_fen: pending,
    unit_nav: d.nav || null,
    nav_date: d.navDate || null,
  };
}
const value = (fen: string | null) => (fen === null ? "未知" : money(fen));
const statuses = {
  exact: "精确一致",
  display: "按截图精度一致",
  different: "份额有差异",
};

export function HoldingsReconciliation({
  page,
  accounts,
  disabled,
  trace,
}: {
  page: Page;
  accounts: Account[];
  disabled: boolean;
  trace: (account: string, asset: string) => void;
}) {
  const cash = accounts.filter(
    (a) => !["receivable", "liability"].includes(a.kind),
  );
  const funds = page.instruments.filter((i) => i.kind === "fund");
  const [account, setAccount] = useState(
    cash.find((a) => a.name === "支付宝")?.id ?? "",
  );
  const [asOf, setAsOf] = useState(localDay());
  const [items, setItems] = useState<Item[]>([]);
  const [active, setActive] = useState("");
  const [image, setImage] = useState<{ file: File; url: string } | null>(null);
  const [busy, setBusy] = useState("");
  const running = useRef(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<{ report: Report; basis: Page } | null>(
    null,
  );
  const current = items.find((item) => item.id === active);
  const file = current?.file;
  const locked = disabled || !!busy;
  const selected = items.filter((item) => item.included);
  useEffect(() => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string")
        setImage({ file, url: reader.result });
    };
    reader.readAsDataURL(file);
    return () => {
      if (reader.readyState === FileReader.LOADING) reader.abort();
    };
  }, [file]);
  function update(id: string, change: Partial<Item>) {
    setResult(null);
    setItems((rows) =>
      rows.map((item) => (item.id === id ? { ...item, ...change } : item)),
    );
  }
  function edit(field: keyof Draft, text: string) {
    if (!current?.draft) return;
    update(current.id, {
      draft: { ...current.draft, [field]: text },
      reviewed: false,
      ...(field === "navDate" ? { navManual: true } : {}),
    });
  }
  async function choose(files: File[]) {
    if (locked || running.current) return;
    running.current = true;
    setBusy("正在检查截图");
    setError("");
    setResult(null);
    try {
      const added = await appendScreenshots(items, files);
      setItems((rows) => [
        ...rows,
        ...added.added.map((file) => ({
          ...file,
          preview: null,
          draft: null,
          error: "",
          included: true,
          reviewed: false,
          navManual: false,
        })),
      ]);
      if (!active && added.added.length) setActive(added.added[0].id);
      setMessage(added.message);
    } catch {
      setError("无法读取截图，请重新选择。");
    } finally {
      running.current = false;
      setBusy("");
    }
  }
  async function recognize() {
    if (locked || running.current) return;
    running.current = true;
    setError("");
    setResult(null);
    setMessage("");
    const queue = items.filter((item) => !item.preview);
    try {
      for (const [index, item] of queue.entries()) {
        setBusy("正在识别 " + (index + 1) + "/" + queue.length);
        const body = new FormData();
        body.append("file", item.file, "holding");
        try {
          const preview = await request<Preview>(
            "/investments/holding-preview",
            "POST",
            body,
          );
          update(item.id, {
            preview,
            error: "",
            reviewed: false,
            navManual: false,
            draft: {
              instrument: matchReceiptFund(
                funds,
                preview.code,
                preview.code ? null : preview.product,
              ),
              quantity: preview.quantity ?? "",
              amount: preview.amount ?? "",
              pending: preview.pending ?? "",
              nav: preview.unit_nav ?? "",
              navDate: suggestedDate(preview, asOf),
            },
          });
        } catch (e) {
          update(item.id, {
            error: e instanceof Error ? e.message : "识别失败，请重试。",
          });
        }
      }
      setMessage("识别结束，请逐张核对并确认截图对应的持仓日期。");
    } finally {
      running.current = false;
      setBusy("");
    }
  }
  function issue(item: Item) {
    try {
      inputRow(item, asOf);
    } catch (e) {
      return (e as Error).message;
    }
    if (!item.reviewed) return "请核对并勾选本张截图。";
    if (
      selected.filter(
        (other) => other.draft?.instrument === item.draft?.instrument,
      ).length > 1
    )
      return "同一基金存在多张截图，请排除重复项。";
    return "";
  }
  async function compare() {
    if (
      locked ||
      running.current ||
      !account ||
      !asOf ||
      asOf > localDay() ||
      !selected.length ||
      selected.some(issue)
    )
      return;
    running.current = true;
    setBusy("正在对账");
    setError("");
    setResult(null);
    try {
      const report = await request<Report>(
        "/investments/holdings/reconcile",
        "POST",
        {
          account_id: account,
          as_of: asOf,
          rows: selected.map((item) => inputRow(item, asOf)),
        } satisfies Input,
      );
      setResult({ report, basis: page });
    } catch (e) {
      setError(e instanceof Error ? e.message : "对账失败，请重试。");
    } finally {
      running.current = false;
      setBusy("");
    }
  }
  const report = result?.basis === page ? result.report : null;
  return (
    <section className="card panel" aria-label="支付宝持仓对账">
      <h2>支付宝持仓对账</h2>
      <p className="footnote">
        选择展开了持有份额的「资产详情」截图。每批最多 20 张、累计 40
        MB；逐张核对后比较所选账户。净值日期按每张截图分别使用。
      </p>
      <fieldset disabled={locked} className="investment-fields">
        <label>
          持仓账户
          <select
            aria-label="对账持仓账户"
            value={account}
            onChange={(e) => {
              setAccount(e.target.value);
              setResult(null);
              setItems((rows) =>
                rows.map((item) => ({ ...item, reviewed: false })),
              );
            }}
          >
            <option value="">请选择账户</option>
            {cash.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
                {a.archived ? "（已归档）" : ""}
              </option>
            ))}
          </select>
        </label>
        <label>
          截图对应持仓日期（请确认）
          <DateStepper
            stepLabel="截图持仓日期"
            value={asOf}
            max={localDay()}
            onValueChange={(day) => {
              setAsOf(day);
              setResult(null);
              setItems((rows) =>
                rows.map((item) => ({
                  ...item,
                  reviewed: false,
                  draft:
                    item.draft && item.preview && !item.navManual
                      ? {
                          ...item.draft,
                          navDate: suggestedDate(item.preview, day),
                        }
                      : item.draft,
                })),
              );
            }}
          />
        </label>
        <label>
          添加持仓截图
          <input
            type="file"
            multiple
            accept="image/png,image/jpeg"
            onChange={(e) => {
              const files = Array.from(e.currentTarget.files ?? []);
              e.currentTarget.value = "";
              void choose(files);
            }}
          />
        </label>
      </fieldset>
      <div
        className="receipt-paste"
        tabIndex={0}
        aria-label="持仓截图粘贴区"
        onPaste={(e) => {
          if (e.clipboardData.files.length && !locked) {
            e.preventDefault();
            void choose(Array.from(e.clipboardData.files));
          }
        }}
      >
        点击此处后按 Ctrl+V 粘贴截图，也可继续添加文件。
      </div>
      <div className="holding-reconcile-actions">
        <button
          type="button"
          className="secondary"
          disabled={locked || !items.some((item) => !item.preview)}
          onClick={() => void recognize()}
        >
          识别持仓截图及失败项
        </button>
        <button
          type="button"
          className="secondary"
          disabled={locked || !items.length}
          onClick={() => {
            setItems([]);
            setActive("");
            setResult(null);
            setError("");
            setMessage("");
          }}
        >
          清空本批截图
        </button>
      </div>
      {busy && <p role="status">{busy}，请稍候…</p>}
      {error && (
        <p role="alert" className="alert error">
          {error}
        </p>
      )}
      {message && (
        <p role="status" className="alert">
          {message}
        </p>
      )}
      {!!items.length && (
        <div className="batch-receipt-layout">
          <div className="batch-receipt-queue" aria-label="持仓截图队列">
            {items.map((item, index) => (
              <div
                key={item.id}
                className={item.id === active ? "batch-receipt-active" : ""}
              >
                <label className="recurring-check-label">
                  <input
                    type="checkbox"
                    className="recurring-check"
                    aria-label={"对账第" + (index + 1) + "张"}
                    disabled={locked}
                    checked={item.included}
                    onChange={(e) =>
                      update(item.id, { included: e.target.checked })
                    }
                  />
                  {item.error
                    ? "识别失败"
                    : item.reviewed
                      ? "已核对"
                      : item.preview
                        ? "待核对"
                        : "待识别"}
                </label>
                <button
                  type="button"
                  className="secondary"
                  disabled={!!busy}
                  aria-pressed={item.id === active}
                  onClick={() => setActive(item.id)}
                >
                  {"核对第" + (index + 1) + "张"}
                </button>
                <small className="batch-receipt-filename">
                  {item.file.name}
                </small>
                {item.preview && (
                  <small>
                    {item.preview.product || item.preview.code || "基金待匹配"}
                  </small>
                )}
                <button
                  type="button"
                  className="secondary"
                  disabled={locked}
                  onClick={() => {
                    setItems((rows) =>
                      rows.filter((row) => row.id !== item.id),
                    );
                    setResult(null);
                    if (active === item.id)
                      setActive(
                        items.find((row) => row.id !== item.id)?.id ?? "",
                      );
                  }}
                >
                  移除
                </button>
              </div>
            ))}
          </div>
          {current && (
            <div className="receipt-comparison">
              {image?.file === file && image && (
                // Local image only, without a remote optimizer.
                // eslint-disable-next-line @next/next/no-img-element
                <img src={image.url} alt="当前持仓截图" />
              )}
              <div>
                {current.error && (
                  <p role="alert" className="alert error">
                    {current.error}
                  </p>
                )}
                {current.preview && (
                  <p className="footnote">
                    截图基金 {current.preview.product ?? "未识别"} · 代码{" "}
                    {current.preview.code ?? "未识别"} · 持仓成本价{" "}
                    {current.preview.cost_price ?? "未识别"}（参考）
                  </p>
                )}
                {current.preview?.warnings.map((warning) => (
                  <p key={warning} className="alert">
                    {warning}
                  </p>
                ))}
                {current.draft && (
                  <fieldset disabled={locked} className="batch-receipt-fields">
                    <label>
                      匹配基金
                      <select
                        aria-label="对账基金"
                        value={current.draft.instrument}
                        onChange={(e) => edit("instrument", e.target.value)}
                      >
                        <option value="">请选择基金</option>
                        {funds.map((i) => (
                          <option key={i.id} value={i.id}>
                            {i.name} · {i.code}
                          </option>
                        ))}
                      </select>
                    </label>
                    {(["quantity", "amount", "pending", "nav"] as const).map(
                      (field) => (
                        <label key={field}>
                          {
                            {
                              quantity: "截图持有份额",
                              amount: "截图持有金额（元）",
                              pending: "截图待确认金额（元）",
                              nav: "截图单位净值",
                            }[field]
                          }
                          <input
                            inputMode="decimal"
                            value={current.draft![field]}
                            onChange={(e) => edit(field, e.target.value)}
                          />
                        </label>
                      ),
                    )}
                    <label>
                      截图净值所属日
                      <DateStepper
                        stepLabel="对账净值所属日"
                        value={current.draft.navDate}
                        max={asOf || localDay()}
                        onValueChange={(day) => edit("navDate", day)}
                      />
                    </label>
                    {!current.draft.navDate && (
                      <small>
                        净值日期未填，仅核对份额；金额参考值将显示未知。
                      </small>
                    )}
                    <label className="recurring-check-label">
                      <input
                        type="checkbox"
                        className="recurring-check"
                        checked={current.reviewed}
                        onChange={(e) =>
                          update(current.id, { reviewed: e.target.checked })
                        }
                      />
                      已核对持仓日期及本张截图
                    </label>
                    <small>{issue(current) || "已具备对账条件。"}</small>
                  </fieldset>
                )}
              </div>
            </div>
          )}
        </div>
      )}
      <div className="holding-reconcile-actions">
        <button
          type="button"
          disabled={
            locked ||
            !account ||
            !asOf ||
            asOf > localDay() ||
            !selected.length ||
            selected.some(issue)
          }
          onClick={() => void compare()}
        >
          {"开始对账（" + selected.length + "张）"}
        </button>
      </div>
      {result && !report && (
        <p className="alert">本地数据已刷新，请重新对账。</p>
      )}
      {report && (
        <section aria-label="持仓对账结果">
          <h3>对账结果</h3>
          <p className="footnote">
            持仓截至 {report.as_of} · 账本版本 {report.revision} ·
            差额方向为本地减截图。金额参考按截图净值计算，最多一分的差额标为舍入差异。
          </p>
          <div className="table-scroll">
            <table className="investment-table">
              <thead>
                <tr>
                  <th>基金</th>
                  <th>截图份额</th>
                  <th>本地精确份额</th>
                  <th>份额差额</th>
                  <th>份额核对</th>
                  <th>同口径市值差额</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {report.rows.map((row) => (
                  <tr key={row.instrument_id}>
                    <td>
                      {row.name}
                      <small>{row.code}</small>
                    </td>
                    <td>{row.platform_quantity}</td>
                    <td>{row.local_quantity}</td>
                    <td>{row.quantity_delta}</td>
                    <td
                      className={
                        row.quantity_status === "different" ? "trade-red" : ""
                      }
                    >
                      {statuses[row.quantity_status]}
                    </td>
                    <td>
                      {value(row.value_delta_fen)}
                      {row.value_delta_fen !== null &&
                        BigInt(row.value_delta_fen) !== 0n &&
                        BigInt(row.value_delta_fen) >= -1n &&
                        BigInt(row.value_delta_fen) <= 1n && (
                          <small>舍入差异</small>
                        )}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="secondary"
                        onClick={() =>
                          trace(report.account_id, row.instrument_id)
                        }
                      >
                        查看相关投资记录
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {report.rows.map((row) => (
            <details
              key={row.instrument_id}
              className="holding-reconcile-detail"
            >
              <summary>{row.name} · 金额与日期核对</summary>
              <p>
                截图持有金额 {value(row.platform_value_fen)}；按本地份额 ×
                截图净值计算 {value(row.reference_value_fen)}。
              </p>
              <p>
                截图净值 {row.unit_nav ?? "未知"} · {row.nav_date ?? "日期未知"}
                。本地净值 {row.local_price ?? "未知"} ·{" "}
                {row.local_price_date ?? "日期未知"}，本地估值{" "}
                {value(row.local_value_fen)}。
              </p>
              {!row.same_price_date && (
                <p className="alert">
                  估值日期不同或缺少本地估值，请先核对净值更新日期。
                </p>
              )}
              {row.quantity_status === "different" && (
                <p>
                  请检查漏记、重复买卖、确认日期或份额事件；相关投资记录可帮助定位。
                </p>
              )}
              {row.quantity_status === "display" && (
                <p>按截图小数位四舍五入后份额一致，本地仍保留精确份额。</p>
              )}
              <p>
                截图待确认金额 {value(row.pending_fen)}；本地剩余成本{" "}
                {value(row.local_cost_fen)}。
              </p>
              {row.pending_fen !== null && BigInt(row.pending_fen) > 0n && (
                <p className="alert">平台有待确认资金，请另行核对在途申购。</p>
              )}
            </details>
          ))}
          {!!report.unprovided.length && (
            <details>
              <summary>
                未提供截图的本地持仓（{report.unprovided.length}项）
              </summary>
              {report.unprovided.map((row) => (
                <p key={row.instrument_id}>
                  {row.name} · {row.quantity} 份
                </p>
              ))}
            </details>
          )}
        </section>
      )}
    </section>
  );
}
