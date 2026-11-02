"use client";

import { useState } from "react";
import type { components } from "./api-schema";
import { request } from "./api";

export type RuntimeInfo = components["schemas"]["RuntimeOutput"];

export function LaunchPanel({
  runtime,
  updated,
}: {
  runtime: RuntimeInfo | null;
  updated: (value: RuntimeInfo) => void;
}) {
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  async function run(manage: boolean) {
    setBusy(true);
    try {
      if (manage) {
        await request("/runtime/manage", "POST");
        setMessage("请在本机启动窗口完成设置或选择更新包。");
      } else {
        updated(await request<RuntimeInfo>("/runtime"));
        setMessage("启动信息已刷新。");
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "操作失败，请重试。");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="card panel full" aria-label="启动与更新">
      <span className="section-label">启动与更新</span>
      <h2>从同一个入口打开账本</h2>
      <p>当前运行版本：{runtime ? `v${runtime.version}` : "正在读取"}</p>
      <p className="footnote">
        运行程序：<code>{runtime?.executable ?? "源码测试环境"}</code>
      </p>
      <p className="footnote">
        固定入口：
        <code>{runtime?.entry ?? "尚未设置，请在启动窗口完成首次设置"}</code>
      </p>
      <button
        disabled={busy || !runtime?.can_manage}
        onClick={() => void run(true)}
      >
        打开启动与更新管理
      </button>
      <button
        className="secondary"
        disabled={busy}
        onClick={() => void run(false)}
      >
        刷新启动信息
      </button>
      {message && <p role="status">{message}</p>}
      <p className="footnote">
        首次设置后可创建桌面快捷方式。更新由你手动选择可信来源的本地程序包，先备份再切换，旧版本保留；程序回退不回退账本数据。未提供后台联网更新。
      </p>
      {runtime && !runtime.can_manage && (
        <p className="footnote">
          当前是源码或无窗口运行模式，请使用 Windows
          便携程序的启动窗口管理入口。
        </p>
      )}
    </section>
  );
}
