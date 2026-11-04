import { validReport } from "../../lib/market";

const BASE = "https://uui000718-ai.github.io/us-market-sentiment-app/data/";
export const dynamic = "force-dynamic";
const headers = { "Cache-Control": "no-store, max-age=0", Pragma: "no-cache" };
async function read(url: string) {
  const freshUrl = new URL(url);
  freshUrl.searchParams.set("_read", String(Date.now()));
  const response = await fetch(freshUrl, { headers: { Accept: "application/json" }, cache: "no-store", signal: AbortSignal.timeout(10000) });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}
export async function GET() {
  const [main, dca, premiums] = await Promise.allSettled([
    read(process.env.SENTIMENT_DATA_URL || `${BASE}latest.json`),
    read(`${BASE}nasdaq-dca.json`), read(`${BASE}etf-premiums.json`),
  ]);
  if (main.status === "rejected" || !validReport(main.value)) {
    return Response.json({ error: "实时数据暂时无法读取，请稍后重试。", read_at: new Date().toISOString() }, { status: 503, headers });
  }
  return Response.json({
    ...main.value, delivery_mode: "live", read_at: new Date().toISOString(),
    dca: dca.status === "fulfilled" && dca.value?.top && dca.value?.twelve ? dca.value : null,
    premiums: premiums.status === "fulfilled" && Array.isArray(premiums.value?.funds) ? premiums.value : null,
    module_errors: [dca.status === "rejected" ? "第三方定投评分读取失败" : "", premiums.status === "rejected" ? "ETF溢价数据读取失败" : ""].filter(Boolean),
  }, { headers });
}
