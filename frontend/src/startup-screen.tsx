"use client";
import { useEffect, useState } from "react";
import { AppIcon } from "./app-icon";
export function StartupScreen({ error }: { error: string }) {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setSlow(true), 12000);
    return () => clearTimeout(timer);
  }, []);
  return (
    <main className="startup-screen">
      <div className="startup-card">
        <div className="startup-brand">
          <AppIcon name="book" />
          <span>PJZ</span>
        </div>
        {error ? (
          <>
            <h1>暂时无法连接账本</h1>
            <p className="alert error" role="alert">
              {error}
            </p>
            <p>请确认本地软件仍在运行，再重新加载；也可从桌面入口重新打开。</p>
            <button onClick={() => window.location.reload()}>重新加载</button>
          </>
        ) : (
          <>
            <div className="startup-spinner" aria-hidden="true" />
            <h1>正在打开你的账本</h1>
            <p role="status">正在连接本地服务并读取账本，请稍候…</p>
            {slow && (
              <p>
                连接耗时较长，请确认本地软件仍在运行。
                <button
                  className="text-button"
                  onClick={() => window.location.reload()}
                >
                  重新加载
                </button>
              </p>
            )}
            <small>数据保存在本机</small>
          </>
        )}
        <noscript>请启用浏览器 JavaScript 后重新打开账本。</noscript>
      </div>
    </main>
  );
}
