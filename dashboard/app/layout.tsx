import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.SITE_URL ?? "http://localhost:3000"),
  title: "Market Pulse｜美股情绪决策",
  description: "每日汇总 AAII、估值、NAAIM、VIX、QQQ RSI 和 CFTC 机构仓位的个人美股情绪 APP。",
  applicationName: "Market Pulse",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/favicon.svg", apple: "/favicon.svg" },
  appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: "美股情绪" },
  formatDetection: { telephone: false },
  openGraph: {
    type: "website",
    locale: "zh_CN",
    title: "Market Pulse｜美股情绪决策",
    description: "把六项市场情绪与风险指标整理成一眼可读的每日决策面板。",
    images: [{ url: "/og.png", width: 1536, height: 1024, alt: "美股情绪决策仪表盘" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "Market Pulse｜美股情绪决策",
    description: "六项市场指标，一张每日决策面板。",
    images: ["/og.png"],
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#081c18",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body id="top">{children}</body>
    </html>
  );
}
