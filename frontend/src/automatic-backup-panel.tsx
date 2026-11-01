"use client";

import { useState } from "react";
import type { components } from "./api-schema";
import { raw, request } from "./api";

export type BackupStatus = components["schemas"]["AutomaticBackupStatus"];

export function AutomaticBackupPanel({
  status,
  updated,
}: {
  status: BackupStatus | null;
  updated: (status: BackupStatus) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function retry() {
    setBusy(true);
    setMessage("");
    try {
      const next = await request<BackupStatus>(
        "/automatic-backups/retry",
        "POST",
      );
      updated(next);
      setMessage(
        next.error
          ? "备份未成功，旧副本保留，请检查磁盘空间或目录权限后重试。"
          : "备份已校验并保存。",
      );
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "备份失败，请重试。");
    } finally {
      setBusy(false);
    }
  }
  async function download(id: string) {
    setBusy(true);
    setMessage("");
    try {
      const blob = await (await raw(`/automatic-backups/${id}`)).blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `daily-${id}.pjzbackup`;
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
      setMessage(
        "备份已核验，请在浏览器下载记录中确认保存位置；可用下方恢复入口验证。",
      );
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "下载失败，请重试。");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="card panel full" aria-label="自动备份保障">
      <span className="section-label">自动备份</span>
      <h2>让账本多一份保障</h2>
      <p>
        默认启用，每分钟检查变更，正常退出时再检查一次。当天有变更会更新当天副本，保留最近{" "}
        {status?.retention ?? 14} 份成功每日备份。
      </p>
      <p>
        最近成功：
        {status?.last_success_at
          ? new Date(status.last_success_at).toLocaleString("zh-CN")
          : "尚未生成"}
      </p>
      <p>
        {status
          ? `已备份版本 ${status.last_revision ?? "—"} / 当前版本 ${status.current_revision} · ${status.pending ? "有变更待备份" : "当前变更已备份"}`
          : "正在读取备份状态…"}
      </p>
      {status?.invalid_count ? (
        <p role="alert">
          发现 {status.invalid_count} 份异常备份，已保留原文件，不作为可用副本。
        </p>
      ) : null}
      <p className="footnote">
        本机目录：<code>{status?.directory ?? "—"}</code>
      </p>
      <button disabled={busy || !status} onClick={() => void retry()}>
        {busy ? "正在处理备份…" : "立即备份／重试"}
      </button>
      {message && <p role="status">{message}</p>}
      <details>
        <summary>查看可用每日备份（{status?.files.length ?? 0} 份）</summary>
        {status?.files.map((file) => (
          <p key={file.id}>
            {file.id} · 版本 {file.revision}{" "}
            <button
              className="secondary"
              disabled={busy}
              onClick={() => void download(file.id)}
            >
              下载 {file.id} 备份
            </button>
          </p>
        ))}
      </details>
      <p className="footnote">
        同盘备份不能防止硬盘损坏，请定期下载到移动硬盘。备份未加密，不包含原截图图片。自动清理仅处理每日备份，手动、升级前和恢复前备份均保留。
      </p>
    </section>
  );
}
