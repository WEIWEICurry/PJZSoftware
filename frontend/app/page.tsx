"use client";

import Link from "next/link";
import { DailyOverview, DailyWorkspace } from "../src/daily";
import { HistoryImport } from "../src/history-import";
import { ReportsPage } from "../src/reports-page";
import { useEffect, useState, type FormEvent } from "react";
import { connect, request, raw, type Ledger, type Preview } from "../src/api";

type Tab = "overview" | "accounts" | "journal" | "reports" | "data" | "plan";
const stages = [
  ["M0", "本地基础", "启动、会话保护、SQLite、备份恢复", "已实现"],
  ["M1", "日常记账", "账户、收入支出、转账与退款", "已实现"],
  ["M2", "历史与报表", "历史导入、日周月年报表与可选分类预算", "当前阶段"],
  ["M3", "投资资产", "A 股、ETF、基金与手动估值", "待开发"],
];
export default function Home() {
  const [tab, setTab] = useState<Tab>("overview");
  const [ledger, setLedger] = useState<Ledger | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [stopped, setStopped] = useState(false);
  const [dailyVersion, setDailyVersion] = useState(0);
  useEffect(() => {
    connect()
      .then(() => request<Ledger>("/ledger"))
      .then((data) => {
        setLedger(data);
        setName(data.name);
      })
      .catch((e: Error) => setError(e.message));
  }, []);
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
  function navigate(next: Tab) {
    setTab(next);
    setNotice("");
    if (ledger) setError("");
  }
  async function rename(event: FormEvent) {
    event.preventDefault();
    if (!ledger) return;
    await act(async () => {
      await request("/ledger", "PUT", {
        name: name.trim(),
        revision: ledger.revision,
      });
      setLedger(await request<Ledger>("/ledger"));
      setNotice("账本名称已保存到本机。");
    });
  }
  async function download() {
    await act(async () => {
      const blob = await (await raw("/backups", "POST")).blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "ledger.pjzbackup";
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
      setNotice("备份已生成，请在浏览器下载记录中确认保存位置。");
    });
  }
  async function choose(file?: File) {
    if (!file) return;
    setPreview(null);
    await act(async () => {
      const form = new FormData();
      form.append("file", file);
      setPreview(await request<Preview>("/restores/preview", "POST", form));
    });
  }
  async function restore() {
    if (!preview) return;
    await act(async () => {
      const result = await request<{ directory: string }>(
        "/restores/commit",
        "POST",
        {
          preview_token: preview.preview_token,
        },
      );
      setPreview(null);
      setNotice(
        "恢复成功，新账本位于：" + result.directory + "。当前账本未切换。",
      );
    });
  }
  const available = !!ledger && !busy && !stopped;
  return (
    <div className="shell">
      <aside className="sidebar">
        <Link className="brand" href="/">
          <span className="brand-mark">记</span>
          <span>
            PJZ<span className="brand-sub">个人资产账本</span>
          </span>
        </Link>
        <div className="workspace-label">我的工作空间</div>
        <nav aria-label="主导航">
          {(
            [
              ["overview", "◫", "总览"],
              ["accounts", "▣", "账户"],
              ["journal", "≡", "日常账本"],
              ["reports", "▥", "报表与预算"],
              ["data", "▤", "数据管理"],
              ["plan", "◇", "开发计划"],
            ] as const
          ).map(([id, icon, label]) => (
            <button
              key={id}
              onClick={() => navigate(id)}
              className={tab === id ? "nav active" : "nav"}
              aria-current={tab === id ? "page" : undefined}
            >
              <span aria-hidden="true">{icon}</span>
              {label}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <span className="status-dot" />
          仅在本机运行<small>日常账本版 · v0.6.0</small>
        </div>
      </aside>
      <div className="workspace">
        <header>
          <span>
            个人空间 <span className="slash">/</span>{" "}
            {
              {
                overview: "总览",
                accounts: "账户",
                journal: "日常账本",
                reports: "报表与预算",
                data: "数据管理",
                plan: "开发计划",
              }[tab]
            }
          </span>
          <span className="local-tag">
            <span className="status-dot" /> 本地模式
          </span>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">YOUR LOCAL LEDGER</div>
              <h1>
                {
                  {
                    overview: "把生活与资产，理清楚。",
                    accounts: "账户清楚，资金有序。",
                    journal: "把每一笔日常，记下来。",
                    reports: "看清收支，按需规划。",
                    data: "数据由你保管。",
                    plan: "一步一步，建立可靠的账本。",
                  }[tab]
                }
              </h1>
              <p>
                {
                  {
                    overview: "从日常收支开始，了解自己的资金变化。",
                    accounts: "期初余额、账户转账和欠款都单独记录。",
                    journal: "记录收入支出，保留每次修改的依据。",
                    reports:
                      "按日、周、月、年查看收支；分类预算由你选择是否设置。",
                    data: "可验证的备份，让换一台电脑也能继续记录。",
                    plan: "先验证数据可靠，再逐步开放记账与投资管理。",
                  }[tab]
                }
              </p>
            </div>
            <span className="phase">M2 · 历史迁移</span>
          </div>
          {error && (
            <div className="alert error" role="alert">
              {error}
            </div>
          )}
          {notice && (
            <div className="alert success" role="status">
              {notice}
            </div>
          )}
          {stopped && (
            <div className="alert" role="status">
              本地服务已退出，可以关闭页面。再次使用请双击启动器。
            </div>
          )}
          {!ledger && !error && (
            <div role="status" className="card">
              正在连接本地账本…
            </div>
          )}
          {tab === "overview" && (
            <>
              <DailyOverview
                key={dailyVersion}
                connected={available}
                open={navigate}
              />
              <section className="card details">
                <div>
                  <span className="section-label">本地账本状态</span>
                  <h2>数据留在你的电脑里</h2>
                </div>
                <div className="detail-row">
                  <span>连接状态</span>
                  <strong>
                    {ledger && !stopped ? "已连接本机服务" : "尚未连接"}
                  </strong>
                </div>
                <div className="detail-row">
                  <span>应用层加密</span>
                  <strong>未启用 · 依赖 Windows 账户保护</strong>
                </div>
                <div className="detail-row">
                  <span>数据存放位置</span>
                  <code>{ledger?.directory ?? "连接后显示"}</code>
                </div>
                <p className="footnote">
                  历史汇总在数据管理中预览导入，不反推账户余额；投资持仓尚未纳入。
                </p>
              </section>
            </>
          )}
          {(tab === "accounts" || tab === "journal") && (
            <DailyWorkspace
              key={tab}
              mode={tab}
              available={available}
              changed={() => {
                setDailyVersion((value) => value + 1);
                void request<Ledger>("/ledger").then(setLedger);
              }}
            />
          )}
          {tab === "reports" && (
            <ReportsPage
              available={available}
              changed={() => {
                setDailyVersion((value) => value + 1);
                void request<Ledger>("/ledger").then(setLedger);
              }}
            />
          )}
          {tab === "data" && (
            <div className="data-grid">
              <HistoryImport
                available={available}
                changed={() => {
                  setDailyVersion((value) => value + 1);
                  void request<Ledger>("/ledger").then(setLedger);
                }}
              />
              <section className="card panel">
                <span className="section-label">01 / 账本信息</span>
                <h2>给账本起个名字</h2>
                <form onSubmit={rename}>
                  <label htmlFor="ledger-name">账本名称</label>
                  <input
                    id="ledger-name"
                    maxLength={60}
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    required
                  />
                  <button disabled={!available || !name.trim()} type="submit">
                    保存名称
                  </button>
                </form>
                <p className="footnote">修改名称不会改变已有账户与流水。</p>
              </section>
              <section className="card panel">
                <span className="section-label">02 / 备份</span>
                <h2>保存一份完整副本</h2>
                <p>
                  使用 SQLite
                  一致性快照并校验文件内容。备份包含账户、流水、分类、历史汇总与原始
                  JSON 来源，以及本地修订记录。
                </p>
                <button disabled={!available} onClick={download}>
                  下载本地备份
                </button>
                <p className="footnote">备份未加密，请保存在你信任的位置。</p>
              </section>
              <section className="card panel full">
                <span className="section-label">03 / 恢复验证</span>
                <h2>先核验，再恢复</h2>
                <p>
                  选择备份后先检查格式和校验和。确认后会备份当前账本，并在新目录恢复，不覆盖当前账本。
                </p>
                <label className="file-label" htmlFor="backup-file">
                  选择 .pjzbackup 备份
                </label>
                <input
                  id="backup-file"
                  type="file"
                  accept=".pjzbackup"
                  disabled={!available}
                  onChange={(e) => {
                    void choose(e.target.files?.[0]);
                    e.target.value = "";
                  }}
                />
                {preview && (
                  <div className="preview">
                    <strong>备份验证通过</strong>
                    <code>SHA-256: {preview.sha256}</code>
                    <p>{preview.message}</p>
                    <button disabled={!available} onClick={restore}>
                      确认恢复到新目录
                    </button>
                  </div>
                )}
                <p className="footnote">
                  当前恢复只验证独立副本，切换账本功能后续开放。基础版本文件上限
                  8 MB。
                </p>
              </section>
            </div>
          )}
          {tab === "plan" && (
            <section className="card roadmap">
              {stages.map(([id, title, description, status]) => (
                <div className="milestone" key={id}>
                  <span className="milestone-id">{id}</span>
                  <div>
                    <h2>{title}</h2>
                    <p>{description}</p>
                  </div>
                  <span className="muted-label">{status}</span>
                </div>
              ))}
            </section>
          )}
          <footer>
            <span>PJZSoftware · 一个属于自己的账本</span>
            <button
              className="text-button"
              disabled={!available}
              onClick={() =>
                void act(async () => {
                  await request("/shutdown", "POST");
                  setStopped(true);
                })
              }
            >
              退出软件
            </button>
          </footer>
        </main>
      </div>
    </div>
  );
}
