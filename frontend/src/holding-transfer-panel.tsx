"use client";
import { useState } from "react";
import { request } from "./api";
import { money } from "./money";
type Item = { id: string; name: string };
type Preview = {
  ledger_revision: number;
  preview_token: string;
  event_count: number;
  quantity: string;
  cost_fen: string | null;
  realized_fen: string;
  previous_realized_fen: string;
};
export function HoldingTransferPanel({
  accounts,
  instruments,
  enabled,
  changed,
}: {
  accounts: Item[];
  instruments: Item[];
  enabled: boolean;
  changed: () => void;
}) {
  const [asset, setAsset] = useState("");
  const [target, setTarget] = useState("");
  const [sources, setSources] = useState<string[]>([]);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const payload = {
    instrument_id: asset,
    target_account_id: target,
    source_account_ids: sources,
  };
  async function act(commit: boolean) {
    setBusy(true);
    setMessage("");
    try {
      if (commit && preview) {
        const result = await request<{ backup_path: string }>(
          "/investments/holding-transfer/commit",
          "POST",
          {
            ...payload,
            ledger_revision: preview.ledger_revision,
            preview_token: preview.preview_token,
          },
        );
        setPreview(null);
        setSources([]);
        setMessage("归并完成，保护备份：" + result.backup_path);
        changed();
      } else {
        setPreview(null);
        setPreview(
          await request<Preview>(
            "/investments/holding-transfer/preview",
            "POST",
            payload,
          ),
        );
      }
    } catch (e) {
      setPreview(null);
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="card panel">
      <summary>整理持仓归属（保留原扣款账户）</summary>
      <p>
        支付宝或券商作为持仓账户，银行卡只作为支付账户。请先在账户管理中建立平台账户，期初日期不晚于投资历史，现金余额可为零。旧记录不会自动归并。
      </p>
      <fieldset className="investment-fields" disabled={!enabled || busy}>
        <label>
          归并标的
          <select
            aria-label="归并标的"
            value={asset}
            onChange={(e) => {
              setAsset(e.target.value);
              setPreview(null);
            }}
          >
            <option value="">请选择</option>
            {instruments.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          目标持仓账户
          <select
            aria-label="目标持仓账户"
            value={target}
            onChange={(e) => {
              setTarget(e.target.value);
              setSources(sources.filter((s) => s !== e.target.value));
              setPreview(null);
            }}
          >
            <option value="">请选择支付宝或券商账户</option>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <div>
          <span>原归属账户（可多选）</span>
          {accounts
            .filter((a) => a.id !== target)
            .map((a) => (
              <label className="investment-checkbox" key={a.id}>
                <input
                  type="checkbox"
                  checked={sources.includes(a.id)}
                  onChange={(e) => {
                    setSources(
                      e.target.checked
                        ? [...sources, a.id]
                        : sources.filter((s) => s !== a.id),
                    );
                    setPreview(null);
                  }}
                />
                {a.name}
              </label>
            ))}
        </div>
      </fieldset>
      <p className="footnote">
        归并该标的在所选来源账户的全部历史及相关定投计划，保留交易
        ID、日期、费用与现金去向。合并后重算移动加权成本；多个期初或顺序冲突会拒绝处理。不同平台不要合并。
      </p>
      <button
        disabled={!enabled || busy || !asset || !target || !sources.length}
        onClick={() => void act(false)}
      >
        预览持仓归并
      </button>
      {preview && (
        <div className="preview">
          <p>
            将调整 {preview.event_count} 笔记录；合并后 {preview.quantity}{" "}
            份／股，成本{" "}
            {preview.cost_fen == null ? "未知" : money(preview.cost_fen)}
            。原已实现盈亏 {money(preview.previous_realized_fen)}，重算后{" "}
            {money(preview.realized_fen)}。银行卡余额保持不变，确认前自动备份。
          </p>
          <button disabled={!enabled || busy} onClick={() => void act(true)}>
            备份并确认归并
          </button>
        </div>
      )}
      {message && <p role="status">{message}</p>}
    </details>
  );
}
