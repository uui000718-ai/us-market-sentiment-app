import { validReport } from "./market";
import type { Report } from "./market";

export async function loadStaticReport(): Promise<Report> {
  const read = async (file: string) => {
    const response = await fetch(`./data/${file}?t=${Date.now()}`, { cache: "no-store", signal: AbortSignal.timeout(12000) });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  };
  const [main, dca, premiums] = await Promise.allSettled([read("latest.json"), read("nasdaq-dca.json"), read("etf-premiums.json")]);
  if (main.status === "rejected" || !validReport(main.value)) throw new Error("实时数据暂不可用");
  return {
    ...main.value, delivery_mode: "live", read_at: new Date().toISOString(),
    dca: dca.status === "fulfilled" && dca.value?.twelve?.dimensions ? dca.value : null,
    premiums: premiums.status === "fulfilled" && Array.isArray(premiums.value?.funds) ? premiums.value : null,
  };
}
