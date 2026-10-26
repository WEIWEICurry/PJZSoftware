"use client";
import { useEffect, useRef, useState } from "react";
import type { components } from "./api-schema";
import { errorMessage } from "./api";
import { money } from "./money";

export type AccountDeletePreview = components["schemas"]["DeletePreview"];

export function AccountDeleteDialog({
  preview,
  busy,
  error,
  cancel,
  confirm,
}: {
  preview: AccountDeletePreview;
  busy: boolean;
  error: string;
  cancel: () => void;
  confirm: (name: string) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState("");
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);
  return (
    <dialog
      ref={dialog}
      className="delete-dialog"
      aria-labelledby="delete-account-title"
      aria-describedby="delete-account-description"
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) cancel();
      }}
    >
      <h2 id="delete-account-title">彻底删除「{preview.account_name}」？</h2>
      <p id="delete-account-description">
        将从当前账本删除这个账户及 {preview.event_count}{" "}
        条相关流水，包含期初和已作废记录。
      </p>
      {(preview.transfer_count > 0 || preview.refund_count > 0) && (
        <div className="alert">
          其中有 {preview.transfer_count} 条转账、{preview.refund_count}{" "}
          条退款。关联转账会从两端一起删除，关联退款也会删除。
        </div>
      )}
      {preview.other_accounts.length > 0 && (
        <div className="table-scroll">
          <table>
            <caption>其他账户的余额影响</caption>
            <thead>
              <tr>
                <th>账户</th>
                <th className="amount-column">当前余额</th>
                <th className="amount-column">删除后余额</th>
              </tr>
            </thead>
            <tbody>
              {preview.other_accounts.map((item) => (
                <tr key={item.account_id}>
                  <td>{item.name}</td>
                  <td className="amount-column">{money(item.before_fen)}</td>
                  <td className="amount-column">{money(item.after_fen)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {!preview.can_delete && (
        <div className="alert error" role="alert">
          <strong>当前无法删除</strong>
          <p>
            {preview.reason === "INSUFFICIENT_BALANCE"
              ? "删除会导致其他账户在某一天余额不足。请保留归档，或先核对这些关联流水。"
              : errorMessage(preview.reason ?? "INVALID_INPUT")}
          </p>
        </div>
      )}
      <p className="delete-backup-note">
        执行前会自动保存完整备份。删除不能在软件内撤销，可以通过备份恢复；旧备份仍保留原数据。
      </p>
      {preview.can_delete && (
        <label className="delete-name-label">
          输入账户名称以确认
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            autoComplete="off"
            spellCheck={false}
            maxLength={60}
            disabled={busy}
            placeholder={preview.account_name}
          />
        </label>
      )}
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
      <div className="dialog-actions">
        <button
          type="button"
          className="secondary"
          disabled={busy}
          onClick={cancel}
        >
          {preview.can_delete ? "取消" : "关闭"}
        </button>
        {preview.can_delete && (
          <button
            type="button"
            className="destructive-button"
            disabled={busy || name !== preview.account_name}
            onClick={() => confirm(name)}
          >
            {busy ? "正在备份并删除…" : "确认彻底删除"}
          </button>
        )}
      </div>
    </dialog>
  );
}
