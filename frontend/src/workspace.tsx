"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { AppIcon } from "./app-icon";
import { LaunchPanel, type RuntimeInfo } from "./launch-panel";
import {
  AutomaticBackupPanel,
  type BackupStatus,
} from "./automatic-backup-panel";
import { InvestmentAssets, InvestmentsPage } from "./investments-page";
import { DailyOverview, DailyWorkspace } from "./daily";
import { HistoryImport } from "./history-import";
import { ReportsPage } from "./reports-page";
import { InvestmentReportsPage } from "./investment-reports-page";
import { useEffect, useState, type FormEvent } from "react";
import { connect, request, raw, type Ledger, type Preview } from "./api";

type Tab =
  | "overview"
  | "accounts"
  | "journal"
  | "reports"
  | "investments"
  | "investmentReports"
  | "data"
  | "plan";
const routes: Record<Tab, string> = {
  overview: "/",
  accounts: "/accounts/",
  journal: "/journal/",
  reports: "/reports/",
  investments: "/investments/",
  investmentReports: "/investment-reports/",
  data: "/data/",
  plan: "/plan/",
};
const stages = [
  ["M0", "本地基础", "启动、会话保护、SQLite、备份恢复", "已实现"],
  ["M1", "日常记账", "账户、收入支出、转账与退款", "已实现"],
  ["M2", "历史与报表", "历史导入、日周月年报表与可选分类预算", "已实现"],
  ["M3", "投资资产", "期间总盈亏、边界持仓、配置与导出", "当前阶段"],
];
export default function Workspace() {
  const [runtime, setRuntime] = useState<RuntimeInfo | null>(null);
  const [restoredToken, setRestoredToken] = useState<string | null>(null);
  const [backupStatus, setBackupStatus] = useState<BackupStatus | null>(null);
  const [backupUnavailable, setBackupUnavailable] = useState(false);
  const pathname = usePathname();
  const router = useRouter();
  const tab =
    (Object.keys(routes) as Tab[]).find((key) => routes[key] === pathname) ??
    "overview";
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
        void request<RuntimeInfo>("/runtime")
          .then(setRuntime)
          .catch(() => setRuntime(null));
      })
      .catch((e: Error) => setError(e.message));
  }, []);
  useEffect(() => {
    if (!ledger || stopped) return;
    let active = true;
    const refresh = () => {
      void request<BackupStatus>("/automatic-backups")
        .then((value) => {
          if (active) {
            setBackupStatus(value);
            setBackupUnavailable(false);
          }
        })
        .catch(() => {
          if (active) setBackupUnavailable(true);
        });
    };
    refresh();
    const timer = setInterval(refresh, 30000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [ledger, stopped]);
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
    router.push(routes[next]);
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
      const result = await request<{
        directory: string;
        restore_token: string;
      }>("/restores/commit", "POST", {
        preview_token: preview.preview_token,
      });
      setPreview(null);
      setRestoredToken(result.restore_token);
      setNotice(
        "恢复成功，新账本位于：" +
          result.directory +
          '。当前账本未切换。退出软件后，可使用启动器参数打开副本：PJZSoftware.exe --data-dir "' +
          result.directory +
          '"。',
      );
    });
  }
  const available = !!ledger && !busy && !stopped;
  return (
    <div className="shell">
      <aside className="sidebar">
        <Link className="brand" href="/">
          <span className="brand-mark">
            <AppIcon name="book" />
          </span>
          <span>
            PJZ<span className="brand-sub">个人资产账本</span>
          </span>
        </Link>
        <nav aria-label="主导航">
          {(
            [
              [
                "生活账本",
                [
                  ["overview", "总览"],
                  ["accounts", "账户"],
                  ["journal", "日常账本"],
                  ["reports", "报表与预算"],
                ],
              ],
              [
                "投资资产",
                [
                  ["investments", "投资"],
                  ["investmentReports", "投资报表"],
                ],
              ],
              [
                "工作空间",
                [
                  ["data", "数据管理"],
                  ["plan", "开发计划"],
                ],
              ],
            ] as const
          ).map(([group, items]) => (
            <div className="nav-group" key={group}>
              <div className="workspace-label">{group}</div>
              {items.map(([id, label]) => (
                <Link
                  role="button"
                  href={routes[id]}
                  key={id}
                  onClick={() => {
                    setNotice("");
                    if (ledger) setError("");
                  }}
                  className={tab === id ? "nav active" : "nav"}
                  aria-current={tab === id ? "page" : undefined}
                >
                  <AppIcon name={id} />
                  {label}
                </Link>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <span className="status-dot" />
          仅在本机运行
          <small>
            记账与投资版 · {runtime ? `v${runtime.version}` : "版本待确认"}
          </small>
        </div>
      </aside>
      <div className="workspace">
        <header>
          <span>
            {ledger?.name || "个人空间"} <span className="slash">/</span>{" "}
            {
              {
                overview: "总览",
                accounts: "账户",
                journal: "日常账本",
                reports: "报表与预算",
                investments: "投资",
                investmentReports: "投资报表",
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
              <h1>
                {
                  {
                    overview: "资产总览",
                    accounts: "账户管理",
                    journal: "日常账本",
                    reports: "报表与预算",
                    investments: "投资资产",
                    investmentReports: "投资报表",
                    data: "数据管理",
                    plan: "开发计划",
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
                    investments:
                      "管理股票、ETF 与基金；现金、成本和手动估值各有依据。",
                    investmentReports:
                      "期间收益构成、当前资产配置与可追溯的 CSV 导出。",
                    data: "可验证的备份，让换一台电脑也能继续记录。",
                    plan: "先验证数据可靠，再逐步开放记账与投资管理。",
                  }[tab]
                }
              </p>
            </div>
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
          {(backupStatus?.error || backupUnavailable) && !stopped && (
            <div className="alert" role="alert">
              自动备份尚未成功或状态无法读取，现有账本不受影响。请到数据管理检查磁盘空间、目录权限并重试。
            </div>
          )}
          {tab === "overview" && (
            <>
              <DailyOverview
                key={dailyVersion}
                connected={available}
                open={navigate}
              />
              <InvestmentAssets key={dailyVersion} connected={available} />
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
                  历史汇总不反推账户余额；持仓按手动价格估值，缺失部分单独提示。
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
          {tab === "investments" && (
            <InvestmentsPage
              available={available}
              changed={() => {
                setDailyVersion((v) => v + 1);
                void request<Ledger>("/ledger").then(setLedger);
              }}
            />
          )}
          {tab === "investmentReports" && (
            <InvestmentReportsPage available={available} />
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
              <LaunchPanel runtime={runtime} updated={setRuntime} />
              <AutomaticBackupPanel
                status={backupStatus}
                updated={setBackupStatus}
              />
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
                {restoredToken && runtime?.can_switch && (
                  <button
                    disabled={!available}
                    onClick={() =>
                      void act(async () => {
                        await request("/runtime/open-restored", "POST", {
                          restore_token: restoredToken,
                        });
                        setRestoredToken(null);
                        setNotice(
                          "请在本机启动窗口确认，随后将退出并打开恢复副本；当前账本会保留保护备份。",
                        );
                      })
                    }
                  >
                    退出并打开恢复副本
                  </button>
                )}
                <p className="footnote">
                  恢复到独立目录；固定入口模式可退出并打开恢复副本，便携模式仍可用启动参数打开。基础版本文件上限
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
