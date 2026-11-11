"use client";

import { useEffect, useRef, useState } from "react";
import type { components } from "./api-schema";
import { ApiError, request } from "./api";
import { DateStepper } from "./date-stepper";
import { localDay, money, yuanToFen } from "./money";
import { matchReceiptFund, matchReceiptPayment } from "./receipt-matching";
import type { ReceiptPreview } from "./receipt-import";
import { appendScreenshots } from "./screenshot-files";

type Page = components["schemas"]["InvestmentPage"];
type Account = components["schemas"]["AccountOutput"];
type Batch = components["schemas"]["ReceiptBatchInput"];
type Draft = {
  account_id: string;
  instrument_id: string;
  cash_account_id: string;
  effective_date: string;
  nav_date: string;
  quantity: string;
  amount: string;
  fee: string;
  note: string;
};
type Item = {
  id: string;
  file: File;
  hash: string;
  result: ReceiptPreview | null;
  draft: Draft | null;
  error: string;
  included: boolean;
  reviewed: boolean;
  allowDuplicate: boolean;
  saved: boolean;
};

function transaction(draft: Draft): Batch["rows"][number] {
  if (
    !draft.account_id ||
    !draft.instrument_id ||
    !draft.cash_account_id ||
    !draft.effective_date ||
    !draft.nav_date ||
    draft.effective_date > localDay() ||
    draft.nav_date > draft.effective_date ||
    !/^(0|[1-9]\d*)(\.\d{1,8})?$/.test(draft.quantity) ||
    !/[1-9]/.test(draft.quantity)
  ) {
    throw new Error("请补齐账户、基金、有效日期与正份额。");
  }
  const amount = yuanToFen(draft.amount);
  const fee = yuanToFen(draft.fee);
  if (
    BigInt(amount) <= 0n ||
    BigInt(fee) < 0n ||
    BigInt(fee) >= BigInt(amount)
  ) {
    throw new Error("实际扣款应大于零，费用应不小于零且小于扣款。");
  }
  return {
    account_id: draft.account_id,
    instrument_id: draft.instrument_id,
    cash_account_id: draft.cash_account_id,
    effective_date: draft.effective_date,
    nav_date: draft.nav_date,
    quantity: draft.quantity,
    amount_fen: amount,
    costs_fen: fee,
    action: "buy",
    amount_mode: "net",
    note: draft.note,
    cost_basis_fen: null,
    split_from_quantity: null,
    allow_possible_duplicate: false,
  };
}
function quantityKey(value: string) {
  return value
    .replace(/^0+(?=\d)/, "")
    .replace(/(\.\d*?)0+$/, "$1")
    .replace(/\.$/, "");
}
function sameBuy(a: Batch["rows"][number], b: Batch["rows"][number]) {
  return (
    a.account_id === b.account_id &&
    a.instrument_id === b.instrument_id &&
    a.effective_date === b.effective_date &&
    quantityKey(a.quantity) === quantityKey(b.quantity) &&
    BigInt(a.amount_fen ?? "0") === BigInt(b.amount_fen ?? "0")
  );
}

export function BatchReceiptImport({
  disabled,
  page,
  accounts,
  refresh,
}: {
  disabled: boolean;
  page: Page;
  accounts: Account[];
  refresh: (notice: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Item[]>([]);
  const [active, setActive] = useState("");
  const [image, setImage] = useState("");
  const [busy, setBusy] = useState("");
  const running = useRef(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState<Batch | null>(null);
  const current = items.find((item) => item.id === active);
  const file = current?.file;
  const locked = !!busy || !!pending || disabled;
  const cashAccounts = accounts.filter(
    (a) => !a.archived && !["liability", "receivable"].includes(a.kind),
  );
  const funds = page.instruments.filter((i) => i.kind === "fund");
  const selected = items.filter((item) => item.included && !item.saved);
  useEffect(() => {
    setImage("");
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

  function update(id: string, values: Partial<Item>) {
    setItems((previous) =>
      previous.map((item) => (item.id === id ? { ...item, ...values } : item)),
    );
  }
  function edit(field: keyof Draft, value: string) {
    if (!current?.draft) return;
    update(current.id, {
      draft: { ...current.draft, [field]: value },
      reviewed: false,
      allowDuplicate: false,
    });
  }
  async function choose(files: File[]) {
    if (running.current || locked) return;
    running.current = true;
    setBusy("正在检查截图");
    setError("");
    setMessage("");
    try {
      const result = await appendScreenshots(items, files);
      const added: Item[] = result.added.map((file) => ({
        ...file,
        result: null,
        draft: null,
        error: "",
        included: true,
        reviewed: false,
        allowDuplicate: false,
        saved: false,
      }));
      setItems((previous) => [...previous, ...added]);
      if (!active && added.length) setActive(added[0].id);
      setMessage(result.message);
    } catch {
      setError("无法读取图片，请重新选择。");
    } finally {
      running.current = false;
      setBusy("");
    }
  }

  async function recognize() {
    if (running.current || locked) return;
    running.current = true;
    setError("");
    setMessage("");
    const queue = items.filter((item) => !item.result && !item.saved);
    try {
      for (const [index, item] of queue.entries()) {
        setBusy("正在识别 " + (index + 1) + "/" + queue.length);
        const body = new FormData();
        body.append("file", item.file, "receipt");
        try {
          const result = await request<ReceiptPreview>(
            "/investments/receipt-preview",
            "POST",
            body,
          );
          update(item.id, {
            result,
            error: "",
            reviewed: false,
            draft: {
              account_id:
                cashAccounts.find((a) => a.name === "支付宝")?.id ?? "",
              cash_account_id: matchReceiptPayment(
                cashAccounts,
                result.payment_hint,
              ),
              instrument_id: matchReceiptFund(
                funds,
                result.code,
                result.product,
              ),
              effective_date: result.confirmation_date ?? "",
              nav_date: result.nav_date ?? "",
              quantity: result.quantity ?? "",
              amount: result.amount ?? "",
              fee: result.fee ?? "",
              note: "",
            },
          });
        } catch (e) {
          update(item.id, {
            error: e instanceof Error ? e.message : "识别失败，请重试。",
          });
        }
      }
      setMessage("识别结束，请逐张核对。失败项可再次点击识别按钮重试。");
    } finally {
      running.current = false;
      setBusy("");
    }
  }
  function duplicate(item: Item) {
    if (!item.draft) return false;
    try {
      const row = transaction(item.draft);
      const existing = page.trades.some(
        (trade) =>
          trade.status === "active" &&
          trade.action === "buy" &&
          sameBuy(row, {
            ...row,
            account_id: trade.account_id,
            instrument_id: trade.instrument_id,
            effective_date: trade.effective_date,
            quantity: trade.quantity,
            amount_fen: (
              BigInt(trade.gross_fen) + BigInt(trade.costs_fen)
            ).toString(),
          }),
      );
      return (
        existing ||
        items.some((other) => {
          if (
            other.id === item.id ||
            !other.included ||
            other.saved ||
            !other.draft
          )
            return false;
          try {
            return sameBuy(row, transaction(other.draft));
          } catch {
            return false;
          }
        })
      );
    } catch {
      return false;
    }
  }
  function validation(item: Item) {
    if (!item.draft) return "请先识别成功。";
    try {
      transaction(item.draft);
    } catch (e) {
      return (e as Error).message;
    }
    if (!item.reviewed) return "请核对并勾选本张截图。";
    if (duplicate(item) && !item.allowDuplicate) return "请核对疑似重复记录。";
    return "";
  }
  async function save() {
    if (running.current || disabled) return;
    let payload = pending;
    if (!payload) {
      if (!selected.length || selected.some((item) => validation(item))) return;
      payload = {
        rows: selected.map((item) => ({
          ...transaction(item.draft!),
          allow_possible_duplicate: item.allowDuplicate,
        })),
      };
    }
    running.current = true;
    setBusy("正在保存所选交易");
    setError("");
    setMessage("");
    setPending(payload);
    try {
      await request("/investments/receipt-batches", "POST", payload);
      setItems((previous) =>
        previous.map((item) =>
          item.included && !item.saved
            ? { ...item, saved: true, included: false }
            : item,
        ),
      );
      setPending(null);
      setMessage("所选 " + payload.rows.length + " 笔交易已全部保存。");
      await refresh("批量投资记录已保存，持仓和现金已更新。");
    } catch (e) {
      if (e instanceof ApiError && e.status >= 400 && e.status < 500) {
        setPending(null);
        setError(e.message + " 本批次全部未保存，请修改后重试。");
        await refresh("");
      } else {
        setError("保存结果尚未确认，请重试原批次以确认结果。");
      }
    } finally {
      running.current = false;
      setBusy("");
    }
  }
  let total = 0n,
    fees = 0n;
  for (const item of selected) {
    try {
      const row = transaction(item.draft!);
      total += BigInt(row.amount_fen ?? "0");
      fees += BigInt(row.costs_fen);
    } catch {
      /* Invalid drafts are excluded from the displayed valid subtotal. */
    }
  }
  return (
    <div className="batch-receipt-import">
      <button
        type="button"
        className="secondary"
        disabled={disabled || !!busy || !!pending}
        aria-expanded={open}
        onClick={() => {
          setOpen(!open);
          setItems([]);
          setActive("");
          setError("");
          setMessage("");
        }}
      >
        {open ? "关闭批量截图录入" : "批量截图录入"}
      </button>
      {open && (
        <section aria-label="批量截图核对" className="receipt-review">
          <p className="footnote">
            一次最多 20 张、累计 40
            MB。支持已确认的支付宝基金买入回执，核对后整批保存。
          </p>
          <label>
            添加多张截图
            <input
              type="file"
              multiple
              accept="image/png,image/jpeg"
              disabled={locked}
              onChange={(e) => {
                const files = Array.from(e.currentTarget.files ?? []);
                e.currentTarget.value = "";
                void choose(files);
              }}
            />
          </label>
          <div
            className="receipt-paste"
            tabIndex={0}
            aria-label="批量截图粘贴区"
            onPaste={(e) => {
              if (e.clipboardData.files.length && !locked) {
                e.preventDefault();
                void choose(Array.from(e.clipboardData.files));
              }
            }}
          >
            点击此处后按 Ctrl+V 粘贴截图，可继续添加。
          </div>
          <button
            type="button"
            className="secondary"
            disabled={
              locked || !items.some((item) => !item.result && !item.saved)
            }
            onClick={() => void recognize()}
          >
            识别待处理及失败截图
          </button>
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
              <div className="batch-receipt-queue" aria-label="截图队列">
                {items.map((item, index) => (
                  <div
                    key={item.id}
                    className={item.id === active ? "batch-receipt-active" : ""}
                  >
                    <label className="recurring-check-label">
                      <input
                        className="recurring-check"
                        type="checkbox"
                        aria-label={"录入第" + (index + 1) + "张"}
                        checked={item.included}
                        disabled={locked || item.saved}
                        onChange={(e) =>
                          update(item.id, { included: e.target.checked })
                        }
                      />
                      <span>
                        {item.saved
                          ? "已保存"
                          : item.error
                            ? "识别失败"
                            : item.reviewed
                              ? "已核对"
                              : item.result
                                ? "待核对"
                                : "待识别"}
                      </span>
                    </label>
                    <button
                      type="button"
                      className="secondary"
                      disabled={!!busy}
                      onClick={() => setActive(item.id)}
                      aria-pressed={item.id === active}
                    >
                      {"查看第" + (index + 1) + "张"}
                    </button>
                    <span className="batch-receipt-filename">
                      {item.file.name}
                    </span>
                    {item.draft && (
                      <small className="batch-receipt-filename">
                        {item.draft.effective_date || "确认日期待填"} ·{" "}
                        {item.draft.quantity || "—"} 份 · 扣款 ¥
                        {item.draft.amount || "—"}
                      </small>
                    )}
                    {!item.saved && (
                      <button
                        type="button"
                        className="secondary"
                        disabled={locked}
                        onClick={() => {
                          setItems((rows) =>
                            rows.filter((row) => row.id !== item.id),
                          );
                          if (active === item.id)
                            setActive(
                              items.find((row) => row.id !== item.id)?.id ?? "",
                            );
                        }}
                      >
                        移除
                      </button>
                    )}
                  </div>
                ))}
              </div>
              {current && (
                <div className="receipt-comparison">
                  {image && (
                    // Selected local image, rendered without an optimizer or network access.
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={image} alt="当前待核对的基金回执" />
                  )}
                  <div aria-label="当前截图草稿">
                    {current.error && (
                      <p role="alert" className="alert error">
                        {current.error}
                      </p>
                    )}
                    {current.result && (
                      <p className="footnote">
                        {current.result.product ?? "基金待匹配"} ·{" "}
                        {current.result.payment_hint ?? "扣款账户待核对"} ·
                        确认金额 {current.result.confirmed_amount ?? "待核对"}{" "}
                        元 · 确认净值 {current.result.unit_nav ?? "待核对"}
                      </p>
                    )}
                    {current.result?.warnings.map((warning) => (
                      <p className="alert" key={warning}>
                        {warning}
                      </p>
                    ))}
                    {current.draft && (
                      <fieldset
                        disabled={locked || current.saved}
                        className="batch-receipt-fields"
                      >
                        <label>
                          持仓账户
                          <select
                            aria-label="持仓账户"
                            value={current.draft.account_id}
                            onChange={(e) => edit("account_id", e.target.value)}
                          >
                            <option value="">请选择账户</option>
                            {cashAccounts.map((a) => (
                              <option key={a.id} value={a.id}>
                                {a.name}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label>
                          投资标的
                          <select
                            aria-label="投资标的"
                            value={current.draft.instrument_id}
                            onChange={(e) =>
                              edit("instrument_id", e.target.value)
                            }
                          >
                            <option value="">请选择基金</option>
                            {funds.map((i) => (
                              <option key={i.id} value={i.id}>
                                {i.name} · {i.code}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label>
                          扣款账户
                          <select
                            aria-label="扣款账户"
                            value={current.draft.cash_account_id}
                            onChange={(e) =>
                              edit("cash_account_id", e.target.value)
                            }
                          >
                            <option value="">请选择扣款账户</option>
                            {cashAccounts.map((a) => (
                              <option key={a.id} value={a.id}>
                                {a.name}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label>
                          成交／确认日期
                          <DateStepper
                            stepLabel="批量成交／确认日期"
                            value={current.draft.effective_date}
                            max={localDay()}
                            onValueChange={(value) =>
                              edit("effective_date", value)
                            }
                          />
                        </label>
                        <label>
                          成交净值所属日
                          <DateStepper
                            stepLabel="批量成交净值所属日"
                            value={current.draft.nav_date}
                            max={current.draft.effective_date || localDay()}
                            onValueChange={(value) => edit("nav_date", value)}
                          />
                        </label>
                        {(["quantity", "amount", "fee"] as const).map(
                          (field) => (
                            <label key={field}>
                              {
                                {
                                  quantity: "确认份额",
                                  amount: "实际扣款（元，含费）",
                                  fee: "费用合计（元）",
                                }[field]
                              }
                              <input
                                value={current.draft![field]}
                                inputMode="decimal"
                                onChange={(e) => edit(field, e.target.value)}
                              />
                            </label>
                          ),
                        )}
                        <label>
                          备注
                          <input
                            maxLength={500}
                            value={current.draft.note}
                            onChange={(e) => edit("note", e.target.value)}
                          />
                        </label>
                        {duplicate(current) && (
                          <label className="recurring-check-label">
                            <input
                              type="checkbox"
                              className="recurring-check"
                              checked={current.allowDuplicate}
                              onChange={(e) =>
                                update(current.id, {
                                  allowDuplicate: e.target.checked,
                                  reviewed: false,
                                })
                              }
                            />
                            已核对疑似重复，确认是独立交易
                          </label>
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
                          已核对本张截图
                        </label>
                        {!current.saved && (
                          <small>
                            {validation(current) || "已具备保存条件。"}
                          </small>
                        )}
                      </fieldset>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
          {!!items.length && (
            <>
              <p>
                已选 {selected.length} 笔，有效草稿扣款小计{" "}
                {money(total.toString())}，其中费用 {money(fees.toString())}
                。请核对所有选中草稿后保存。
              </p>
              <button
                type="button"
                disabled={
                  disabled ||
                  !!busy ||
                  (!pending &&
                    (!selected.length ||
                      selected.some((item) => validation(item))))
                }
                onClick={() => void save()}
              >
                {pending ? "重试确认原批次保存结果" : "确认保存所选交易"}
              </button>
            </>
          )}
        </section>
      )}
    </div>
  );
}
