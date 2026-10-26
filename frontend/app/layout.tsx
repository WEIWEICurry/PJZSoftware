import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PJZSoftware · 本地账本",
  description: "只在本机运行的个人账本",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
