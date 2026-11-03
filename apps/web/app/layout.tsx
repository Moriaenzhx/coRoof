import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "coRoof · 企业运行全景",
  description: "从企业全局，看到每一项工作的真实进展。",
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
