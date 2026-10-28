import type { components } from "./api-schema";

export type Ledger = components["schemas"]["LedgerOutput"];
export type Preview = {
  preview_token: string;
  sha256: string;
  message: string;
};
let csrf = "";
const retryKeys = new Map<string, string>();
const responseSignatures = new WeakMap<Response, string>();
let initialization: Promise<void> | undefined;
const messages: Record<string, string> = {
  INVESTMENT_HISTORY_REQUIRED:
    "该账户标的还没有有效持仓历史，请先录入期初或买入；折算还需要当前有持仓。",
  INVESTMENT_REINVEST_FUND_ONLY:
    "分红再投仅支持公募基金，股票送红股请勿用再投代替。",
  INVESTMENT_SPLIT_MISMATCH:
    "折算前份额与该事件之前的持仓不一致，请核对日期、先后顺序和前后份额。",
  INVESTMENT_SPLIT_EVIDENCE_REQUIRED:
    "请填写平台确认的折算依据，不以任意改份额替代交易。",
  INVALID_EVENT_FIELDS:
    "这类投资事件的金额、费用或份额组合不正确，请按对应操作填写。",
  INVESTMENT_WHOLE_SHARES_REQUIRED:
    "股票和 ETF 数量应为整数股／份，基金允许最多八位小数。",
  INVESTMENT_INVALID_DECIMAL:
    "份额和价格必须大于零，最多八位小数，不能用科学计数法。",
  INVESTMENT_OPENING_ORDER:
    "期初持仓只能是该账户标的第一笔有效记录，且不能重复建立。",
  INVESTMENT_INSUFFICIENT_QUANTITY:
    "持仓不足，或修改后会导致后续卖出数量不足。请先核对相关买卖记录。",
  INVESTMENT_COST_REQUIRED:
    "持仓成本未知，请先修改期初记录补齐剩余总成本，再卖出。",
  INVESTMENT_ACCOUNT_HAS_HOLDINGS:
    "账户仍有投资持仓，不能归档。请先核对或结清持仓。",
  INVESTMENT_ACCOUNT_HAS_HISTORY:
    "账户含投资记录，当前版本暂不支持彻底删除。归档可保留凭证并收起账户。",
  INVESTMENT_USE_WORKSPACE: "请在投资页修改或作废投资记录。",
  INVESTMENT_IDENTITY_IMMUTABLE:
    "修改时不能更换账户、标的或操作，请作废后重新录入。",
  INVESTMENT_INVALID_INSTRUMENT:
    "标的市场与类型不匹配；公募基金请选择基金市场，并填写六位代码。",
  INVESTMENT_INVALID_FACTS: "投资记录关联异常，请保留备份并检查账本。",
  REPORT_INVALID_PERIOD: "所选报表期间无效，请重新选择日期。",
  REPORT_FUTURE_PERIOD: "这个期间尚未开始，请选择今天或更早的日期。",
  REPORT_EXPORT_TOO_LARGE: "当前构成超过 50000 行，请缩小期间或按分类导出。",
  BUDGET_INVALID_MONTH: "预算月份格式不正确，请重新选择。",
  BUDGET_CATEGORY_INVALID: "只能为有效支出分类设置预算，请重新选择。",
  BUDGET_INVALID_LIMIT: "预算必须是大于零的金额，最多保留两位小数。",
  HISTORY_UNSUPPORTED_FORMAT:
    "不支持这个汇总格式，请使用版本 1、人民币、整数分的分类汇总 JSON。",
  HISTORY_INVALID_FILE: "汇总文件结构或文字格式不正确，请核对文件。",
  HISTORY_INVALID_AMOUNT: "汇总金额必须是非负整数分，不能包含小数或负数。",
  HISTORY_INVALID_PERIOD:
    "每个汇总期间必须在同一个月内，起止顺序正确且不能包含未来日期。",
  HISTORY_TOTAL_MISMATCH: "分类金额之和与来源总额不一致，请先核对原资料。",
  HISTORY_SOURCE_OVERLAP: "文件内同分类的汇总期间重复或重叠，请先去重核对。",
  HISTORY_FILE_TOO_LARGE: "历史汇总文件超过 512 KB，请按更小的批次整理。",
  HISTORY_INVALID_MAPPING: "分类映射无效，请选择同方向的账本分类并重新预览。",
  HISTORY_CONFLICT: "该预览包含重复、未映射或重叠内容，请重新预览核对。",
  HISTORY_BATCH_NOT_FOUND: "找不到这个导入批次，请刷新列表。",
  HISTORY_DAILY_UNAVAILABLE:
    "这个期间只有汇总，没有逐日数据，不能截取其中几天计算。",
  CASH_ACCOUNT_REQUIRED: "请选择银行卡、现金等资金账户。",
  COUNTERPARTY_REQUIRED: "请选择匹配的借款对象，或填写对方姓名。",
  RECEIVABLE_EVENT_UNSUPPORTED:
    "应收款请通过借出或收回记录，不直接记普通收支。",
  RESOURCE_DELETED: "账户或流水已删除，请刷新后查看最新数据。",
  ACCOUNT_NOT_ARCHIVED: "请先归档账户，再进行彻底删除。",
  CONFIRM_NAME_MISMATCH: "输入的账户名称不一致，请核对后重试。",
  BACKUP_FAILED:
    "删除前备份未成功，账户未删除。请检查磁盘空间和目录权限后重试。",
  FEE_EXCEEDS_AMOUNT: "借款手续费不能超过借款本金。",
  IDEMPOTENCY_CONFLICT: "重复请求的内容不一致，请刷新后重试。",
  DUPLICATE_OR_INVALID_REFERENCE: "名称已存在或引用数据无效，请检查。",
  ADJUSTMENT_REASON_REQUIRED: "余额校正必须填写原因，金额不能为零。",
  INVALID_AMOUNT: "这类流水的金额必须大于零。",
  DEBT_TRANSFER_UNSUPPORTED: "暂不支持负债账户之间转账。",
  DEBT_INCOME_UNSUPPORTED: "负债账户不能记普通收入；借款请使用借还款。",
  SAME_ACCOUNT: "转出和转入不能是同一个账户。",
  OPENING_IMMUTABLE: "期初记录不能直接修改，请使用余额校正并填写原因。",
  REFUND_BEFORE_EXPENSE: "退款日期不能早于原支出。",
  REFUND_EXCEEDS_EXPENSE: "累计退款不能超过原支出金额。",
  REFUND_SOURCE_INVALID: "原支出不存在、已作废或不再是支出。",
  CATEGORY_MISMATCH: "分类与收支类型不匹配。",
  FUTURE_DATE: "不能记录未来日期的已发生交易。",
  BEFORE_OPENING: "交易不能早于相关账户的期初日期。",
  ACCOUNT_NOT_EMPTY: "余额不为零，请先核对或转移余额再归档。",
  ACCOUNT_ARCHIVED: "账户已归档，请先恢复账户。",
  ACCOUNT_NOT_FOUND: "找不到所选账户，请刷新。",
  AMOUNT_OUT_OF_RANGE: "金额或账户余额超出支持范围。",
  INSUFFICIENT_BALANCE:
    "余额不足、还款超过剩余本金，或这次历史改动会导致后续某一天余额不足。",
  UNAUTHENTICATED: "会话未连接，请通过本地启动器重新打开软件。",
  INVALID_BOOTSTRAP: "启动链接已过期或使用过，请从启动器重新打开。",
  REVISION_CONFLICT: "数据已发生变化，请刷新后重试。",
  INVALID_BACKUP: "无法识别备份文件。",
  BACKUP_CHECKSUM_FAILED: "备份校验失败，请选择完好的备份。",
  PREVIEW_EXPIRED: "预览已过期，请重新打开预览。",
  INVALID_INPUT: "请检查填写内容。",
  REQUEST_TOO_LARGE: "文件超过基础版本的 8 MB 限制。",
};
export function errorMessage(code: string): string {
  return messages[code] ?? `操作失败（${code}），请重试或检查数据。`;
}
async function checked(response: Response): Promise<Response> {
  if (!response.ok) {
    const result = await response.json().catch(() => ({}));
    const code = result.error?.code ?? "UNKNOWN";
    const context = result.error?.effective_date
      ? `（冲突记录：${result.error.effective_date}，流水序号 ${result.error.sequence}）`
      : "";
    throw new Error(errorMessage(code) + context);
  }
  return response;
}
export function connect(): Promise<void> {
  if (initialization) return initialization;
  initialization = (async () => {
    const token = new URLSearchParams(window.location.hash.slice(1)).get(
      "bootstrap",
    );
    window.history.replaceState(
      null,
      "",
      window.location.pathname + window.location.search,
    );
    const response = await checked(
      await fetch(token ? "/api/v1/session/bootstrap" : "/api/v1/session", {
        method: token ? "POST" : "GET",
        credentials: "same-origin",
        headers: token ? { "Content-Type": "application/json" } : undefined,
        body: token ? JSON.stringify({ token }) : undefined,
      }),
    );
    csrf = (await response.json()).csrf_token;
  })();
  return initialization;
}
export async function request<T>(
  path: string,
  method = "GET",
  body?: object | FormData,
): Promise<T> {
  const response = await raw(path, method, body);
  const result = await response.json();
  const signature = responseSignatures.get(response);
  if (signature) retryKeys.delete(signature);
  return result;
}
export async function raw(
  path: string,
  method = "GET",
  body?: object | FormData,
): Promise<Response> {
  const multipart = body instanceof FormData;
  const signature =
    method + path + (multipart ? "" : JSON.stringify(body ?? {}));
  let key = retryKeys.get(signature);
  if (!key) {
    key = crypto.randomUUID();
    retryKeys.set(signature, key);
  }
  const response = await checked(
    await fetch("/api/v1" + path, {
      method,
      credentials: "same-origin",
      headers:
        method === "GET"
          ? {}
          : {
              "X-CSRF-Token": csrf,
              "Idempotency-Key": key,
              ...(!multipart ? { "Content-Type": "application/json" } : {}),
            },
      body:
        method === "GET"
          ? undefined
          : multipart
            ? body
            : JSON.stringify(body ?? {}),
    }),
  );
  responseSignatures.set(response, signature);
  return response;
}
