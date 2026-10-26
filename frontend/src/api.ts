import type { components } from "./api-schema";

export type Ledger = components["schemas"]["LedgerOutput"];
export type Preview = {
  preview_token: string;
  sha256: string;
  message: string;
};
let csrf = "";
let initialization: Promise<void> | undefined;
const messages: Record<string, string> = {
  UNAUTHENTICATED: "会话未连接，请通过本地启动器重新打开软件。",
  INVALID_BOOTSTRAP: "启动链接已过期或使用过，请从启动器重新打开。",
  REVISION_CONFLICT: "数据已发生变化，请刷新后重试。",
  INVALID_BACKUP: "无法识别备份文件。",
  BACKUP_CHECKSUM_FAILED: "备份校验失败，请选择完好的备份。",
  PREVIEW_EXPIRED: "恢复预览已过期，请重新选择文件。",
  INVALID_INPUT: "请检查填写内容。",
  REQUEST_TOO_LARGE: "文件超过基础版本的 8 MB 限制。",
};
async function checked(response: Response): Promise<Response> {
  if (!response.ok) {
    const result = await response.json().catch(() => ({}));
    const code = result.error?.code ?? "UNKNOWN";
    throw new Error(
      messages[code] ?? `操作失败（${code}），请重试或检查文件。`,
    );
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
  return response.json();
}
export async function raw(
  path: string,
  method = "GET",
  body?: object | FormData,
): Promise<Response> {
  const multipart = body instanceof FormData;
  return checked(
    await fetch("/api/v1" + path, {
      method,
      credentials: "same-origin",
      headers:
        method === "GET"
          ? {}
          : {
              "X-CSRF-Token": csrf,
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
}
