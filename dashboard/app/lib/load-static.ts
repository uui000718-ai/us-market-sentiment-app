import { validReport, validContext } from "./market";
import type { Report } from "./market";

export async function loadStaticReport(): Promise<Report> {
  const read = async (file: string) => {
    const response = await fetch(`./data/${file}?t=${Date.now()}`, { cache: "no-store", signal: AbortSignal.timeout(12000) });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  };
  const [main, dca, premiums, context] = await Promise.allSettled([read("latest.json"), read("nasdaq-dca.json"), read("etf-premiums.json"), read("market-context.json")]);
  if (main.status === "rejected" || !validReport(main.value)) throw new Error("实时数据暂不可用");
  return {
    ...main.value, delivery_mode: "live", read_at: new Date().toISOString(),
    dca: dca.status === "fulfilled" && dca.value?.twelve?.dimensions ? dca.value : null,
    premiums: premiums.status === "fulfilled" && Array.isArray(premiums.value?.funds) ? premiums.value : null,
    market_context: context.status === "fulfilled" && validContext(context.value) ? context.value : null,
    module_errors: context.status === "rejected" || !validContext(context.value) ? ["市场环境数据暂不可用"] : [],
  };
}
