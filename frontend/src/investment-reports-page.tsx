"use client";

import { useEffect, useState } from "react";
import type { components } from "./api-schema";
import { raw, request } from "./api";
import { fenToYuan, localDay, money } from "./money";
import { ReportPeriodPicker } from "./report-period-picker";

type Report = components["schemas"]["InvestmentReportOutput"];
type Period = Report["period"];
const kinds = { stock: "股票", etf: "ETF", fund: "公募基金" };
const actions = {
  opening: "期初持仓",
  buy: "买入／申购",
  sell: "卖出／赎回",
  cash_dividend: "现金分红",
  reinvest: "基金分红再投",
  split: "份额折算",
};
const value = (amount: string | null) =>
  amount === null ? "—" : money(amount);

export function InvestmentReportsPage({ available }: { available: boolean }) {
  const [period, setPeriod] = useState<Period>("month");
  const [anchor, setAnchor] = useState(localDay());
  const [start, setStart] = useState(localDay().slice(0, 7) + "-01");
  const [end, setEnd] = useState(localDay());
  const [account, setAccount] = useState("");
  const [instrument, setInstrument] = useState("");
  const [kind, setKind] = useState("");
  const [includeVoid, setIncludeVoid] = useState(false);
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [group, setGroup] = useState<"instrument" | "account" | "kind">(
    "instrument",
  );
  const [loaded, setLoaded] = useState<{ key: string; data: Report } | null>(
    null,
  );
  const [failure, setFailure] = useState<{
    key: string;
    message: string;
  } | null>(null);
  const [downloadError, setDownloadError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const params = new URLSearchParams({
    period,
    include_void: String(includeVoid),
  });
  if (period === "custom") {
    params.set("start", start);
    params.set("end", end);
  } else params.set("anchor", anchor);
  if (account) params.set("account_id", account);
  if (instrument) params.set("instrument_id", instrument);
  if (kind) params.set("kind", kind);
  const baseQuery = params.toString();
  const query = baseQuery + "&offset=" + offset;
  const key = query + ":" + refresh;
  const valid =
    period !== "custom" ||
    (!!start && !!end && start <= end && start <= localDay());
  const data = loaded?.key === key && valid ? loaded.data : null;
  const options = loaded?.data;
  useEffect(() => {
    if (!available || !valid) return;
    let current = true;
    request<Report>("/investment-reports?" + query)
      .then((result) => {
        if (current) {
          setLoaded({ key, data: result });
          setFailure(null);
        }
      })
      .catch((e: Error) => {
        if (current) setFailure({ key, message: e.message });
      });
    return () => {
      current = false;
    };
  }, [available, valid, key, query]);
  function changed() {
    setOffset(0);
    setNotice("");
    setDownloadError("");
  }
  async function download(
    dataset: "report" | "trades" | "positions" | "valuations",
  ) {
    setBusy(true);
    setDownloadError("");
    setNotice("");
    try {
      const response = await raw(
        "/investment-reports/export?" + baseQuery + "&dataset=" + dataset,
      );
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `pjz-investment-${dataset}-${dataset === "positions" ? localDay() : data?.start + "_" + data?.end}.csv`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
      setNotice(
        "CSV 已生成，请在浏览器下载记录中确认。导出按下载时的账本重新计算，文件包含账本版本与范围。",
      );
    } catch (e) {
      setDownloadError(e instanceof Error ? e.message : "导出失败，请重试。");
    } finally {
      setBusy(false);
    }
  }
  const enabled = available && !busy;
  return (
    <div className="investment-report-page">
      <section className="card panel">
        <div className="section-heading">
          <h2>期间投资报表</h2>
          <button
            className="secondary"
            disabled={!enabled || !valid}
            onClick={() => {
              setRefresh((r) => r + 1);
              setNotice("");
            }}
          >
            刷新投资报表
          </button>
        </div>
        <div role="group" aria-label="投资报表期间" className="investment-tabs">
          {(
            [
              ["month", "月报"],
              ["year", "年报"],
              ["custom", "自选期间"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              aria-pressed={period === id}
              className={period === id ? "" : "secondary"}
              disabled={!enabled}
              onClick={() => {
                setPeriod(id);
                changed();
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <fieldset disabled={!enabled} className="investment-report-controls">
          {period === "custom" ? (
            <>
              <label>
                开始日期
                <input
                  type="date"
                  required
                  max={localDay()}
                  value={start}
                  onChange={(e) => {
                    setStart(e.target.value);
                    changed();
                  }}
                />
              </label>
              <label>
                结束日期
                <input
                  type="date"
                  required
                  max={localDay()}
                  value={end}
                  onChange={(e) => {
                    setEnd(e.target.value);
                    changed();
                  }}
                />
              </label>
            </>
          ) : (
            <ReportPeriodPicker
              period={period}
              anchor={anchor}
              disabled={!enabled}
              choose={(day) => {
                setAnchor(day);
                changed();
              }}
            />
          )}
          <label>
            持仓账户筛选
            <select
              value={account}
              onChange={(e) => {
                setAccount(e.target.value);
                changed();
              }}
            >
              <option value="">全部资金账户</option>
              {options?.accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                  {a.archived ? "（已归档）" : ""}
                </option>
              ))}
            </select>
          </label>
          <label>
            投资标的筛选
            <select
              value={instrument}
              onChange={(e) => {
                setInstrument(e.target.value);
                changed();
              }}
            >
              <option value="">全部标的</option>
              {options?.instruments.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.name} · {i.code}
                </option>
              ))}
            </select>
          </label>
          <label>
            投资类型筛选
            <select
              value={kind}
              onChange={(e) => {
                setKind(e.target.value);
                changed();
              }}
            >
              <option value="">全部类型</option>
              {Object.entries(kinds).map(([id, name]) => (
                <option key={id} value={id}>
                  {name}
                </option>
              ))}
            </select>
          </label>
        </fieldset>
        <p className="footnote">
          账户按持仓所属账户筛选，分红实际到账账户在明细另列。有效记录计入统计，期初与折算不计收支；不含普通账户转账与日常收支。
        </p>
      </section>
      {!valid && (
        <div className="alert error" role="alert">
          请选择有效起止日期，开始不能晚于结束或今天。
        </div>
      )}
      {failure?.key === key && (
        <div className="alert error" role="alert">
          {failure.message}
        </div>
      )}
      {downloadError && (
        <div className="alert error" role="alert">
          {downloadError}
        </div>
      )}
      {notice && (
        <div className="alert success" role="status">
          {notice}
        </div>
      )}
      {available && valid && !data && failure?.key !== key && (
        <p role="status">正在读取投资报表…</p>
      )}
      {data && (
        <>
          <p className="footnote">
            实际统计 {data.start} 至 {data.end}
            {data.end !== data.requested_end
              ? `（原期间截至 ${data.requested_end}，未来日期未计入）`
              : ""}{" "}
            · 有效记录 {data.totals.record_count} 条 · 账本版本{" "}
            {data.ledger_revision}
          </p>
          <div className="stat-grid">
            {[
              ["买入实际扣款", data.totals.buy_outflow_fen],
              ["卖出净到账", data.totals.sell_inflow_fen],
              ["已实现卖出盈亏", data.totals.realized_fen],
              ["现金净分红", data.totals.cash_dividends_fen],
              ["再投净分红", data.totals.reinvested_dividends_fen],
              ["已计入费用", data.totals.fees_fen],
            ].map(([label, amount]) => (
              <div className="card metric" key={label}>
                <span>{label}</span>
                <strong>{money(amount)}</strong>
              </div>
            ))}
          </div>
          <div className="alert">
            已实现与分红合计 {money(data.totals.realized_and_dividends_fen)}
            ，不含期间浮动盈亏，不能当作期间总收益。费用已计入成本或净到账，不能再次扣减。相关投资事件现金净变动{" "}
            {money(data.totals.cash_delta_fen)}，不等于所选账户余额变化。
          </div>
          <section className="card panel">
            <h2>已实现与分红构成</h2>
            {!data.contributions.length ? (
              <p className="empty-state">所选期间没有有效投资记录。</p>
            ) : (
              <div className="table-scroll">
                <table className="investment-table" aria-label="期间收益构成">
                  <thead>
                    <tr>
                      <th>标的／记录数</th>
                      <th>买入扣款／卖出到账</th>
                      <th>已实现卖出盈亏</th>
                      <th>现金净分红</th>
                      <th>再投净分红</th>
                      <th>已计入费用</th>
                      <th>已实现与分红合计</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.contributions.map((row) => (
                      <tr key={row.instrument_id}>
                        <td>
                          {row.instrument_name}
                          <small>
                            {row.market} {row.code} · {row.record_count} 条
                          </small>
                        </td>
                        <td>
                          {money(row.buy_outflow_fen)}
                          <small>{money(row.sell_inflow_fen)}</small>
                        </td>
                        <td>{money(row.realized_fen)}</td>
                        <td>{money(row.cash_dividends_fen)}</td>
                        <td>{money(row.reinvested_dividends_fen)}</td>
                        <td>{money(row.fees_fen)}</td>
                        <td>{money(row.realized_and_dividends_fen)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
          <section className="card panel" aria-label="当前资产配置">
            <div className="section-heading">
              <h2>当前资产配置</h2>
              <div
                className="investment-tabs"
                role="group"
                aria-label="配置分组"
              >
                {(
                  [
                    ["instrument", "按标的"],
                    ["account", "按账户"],
                    ["kind", "按类型"],
                  ] as const
                ).map(([id, label]) => (
                  <button
                    key={id}
                    className={group === id ? "" : "secondary"}
                    aria-pressed={group === id}
                    onClick={() => setGroup(id)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <p>
              当前已知持仓市值 {money(data.current_allocation.known_value_fen)}
              {data.current_allocation.missing_price_count
                ? `，${data.current_allocation.missing_price_count} 项待估值，全部占比未知。`
                : "。"}
            </p>
            <p className="footnote">
              当前已录持仓（{data.current_allocation.as_of_date}
              ），不是所选期间的期末快照，不随报表日期回溯。按各自手动价格计价；筛选只改变显示，占比分母仍为全部持仓市值，不含现金。当前选中{" "}
              {data.current_allocation.selected_position_count} 项未清仓持仓。
            </p>
            {!data.current_allocation.selected_position_count ? (
              <p className="empty-state">没有匹配的当前未清仓持仓。</p>
            ) : (
              <div className="table-scroll">
                <table className="investment-table" aria-label="当前配置明细">
                  <thead>
                    <tr>
                      <th>分组</th>
                      <th>持仓数</th>
                      <th>市值</th>
                      <th>占全部持仓</th>
                      <th>有效价格日期</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.current_allocation.groups
                      .filter((row) => row.group_by === group)
                      .map((row) => (
                        <tr key={row.id}>
                          <td>{row.label}</td>
                          <td>{row.position_count}</td>
                          <td>
                            {row.value_fen === null ? (
                              <>
                                待估值
                                <small>
                                  已知小计 {money(row.known_value_fen)} · 缺{" "}
                                  {row.missing_price_count} 项
                                </small>
                              </>
                            ) : (
                              money(row.value_fen)
                            )}
                          </td>
                          <td>
                            {row.share_bps === null
                              ? data.current_allocation.missing_price_count
                                ? "待估值"
                                : "—"
                              : fenToYuan(row.share_bps) + "%"}
                          </td>
                          <td>
                            {row.price_start === null
                              ? "—"
                              : row.price_start === row.price_end
                                ? row.price_start
                                : `${row.price_start} ～ ${row.price_end}`}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
          <section className="card panel" aria-label="投资构成明细">
            <div className="section-heading">
              <h2>投资事件明细</h2>
              <label className="investment-checkbox">
                <input
                  type="checkbox"
                  checked={includeVoid}
                  disabled={!enabled}
                  onChange={(e) => {
                    setIncludeVoid(e.target.checked);
                    changed();
                  }}
                />
                包含作废记录
              </label>
            </div>
            <p className="footnote">
              共 {data.entries.total}{" "}
              条；作废行只用于追溯，不计入以上金额。分摊成本和已实现盈亏来自完整历史重放。
            </p>
            {!data.entries.items.length ? (
              <p className="empty-state">没有匹配的投资事件。</p>
            ) : (
              <div className="table-scroll">
                <table className="investment-table" aria-label="投资事件明细">
                  <thead>
                    <tr>
                      <th>日期／操作</th>
                      <th>持仓账户／标的</th>
                      <th>数量／折算</th>
                      <th>实际现金变动</th>
                      <th>分摊成本／已实现</th>
                      <th>费用</th>
                      <th>备注／状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.entries.items.map((row) => (
                      <tr key={row.id}>
                        <td>
                          {row.effective_date}
                          <small>
                            {actions[row.action]} · #{row.sequence}
                          </small>
                        </td>
                        <td>
                          {row.account_name}
                          <small>
                            {row.instrument_name} · {row.code}
                          </small>
                        </td>
                        <td>
                          {row.action === "cash_dividend"
                            ? "—"
                            : row.action === "split"
                              ? `${row.split_from_quantity} → ${row.quantity}`
                              : row.quantity}
                        </td>
                        <td>
                          {row.status === "void"
                            ? "不计入"
                            : value(row.cash_delta_fen)}
                          <small>{row.cash_account_name}</small>
                        </td>
                        <td>
                          {row.action === "sell" ? (
                            <>
                              {value(row.allocated_cost_fen)}
                              <small>{value(row.realized_fen)}</small>
                            </>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td>{money(row.costs_fen)}</td>
                        <td>
                          {row.note || "—"}
                          <small>
                            {row.status === "void"
                              ? "已作废（不计入）"
                              : "有效"}
                          </small>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="investment-pagination">
              <button
                className="secondary"
                disabled={!enabled || offset === 0}
                onClick={() => setOffset(Math.max(0, offset - 20))}
              >
                上一页投资记录
              </button>
              <span>第 {Math.floor(offset / 20) + 1} 页</span>
              <button
                className="secondary"
                disabled={!enabled || offset + 20 >= data.entries.total}
                onClick={() => setOffset(offset + 20)}
              >
                下一页投资记录
              </button>
            </div>
          </section>
          <section className="card panel">
            <h2>CSV 导出</h2>
            <p className="footnote">
              报表只含有效事件；投资记录包含所选期间全部分页，沿用作废选项；持仓为当前未清仓持仓，不受期间日期限制；估值按所选期间且含作废。代码请在
              Excel 中按文本导入，未知值留空，单次最多 50000 行。
            </p>
            <div className="investment-tabs investment-export-buttons">
              {(
                [
                  ["report", "期间报表 CSV"],
                  ["trades", "投资记录 CSV"],
                  ["positions", "当前持仓 CSV"],
                  ["valuations", "手动估值 CSV（含作废）"],
                ] as const
              ).map(([id, label]) => (
                <button
                  key={id}
                  disabled={!enabled || !data}
                  onClick={() => void download(id)}
                >
                  {label}
                </button>
              ))}
            </div>
          </section>
          <p className="footnote">
            本阶段不计算完整期间总盈亏、年化收益率、回撤或历史收益曲线；不把当前累计盈亏当成本期收益，不做基金穿透分析。CSV
            用于核对，完整迁移仍使用账本备份。
          </p>
        </>
      )}
    </div>
  );
}
