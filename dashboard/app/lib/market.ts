export type Indicator = { name: string; label: string; score: number | null; value: string; detail: string; weight: number };
export type Trigger = { indicator: string; direction: "buy" | "sell"; reason: string };
export type BuyEvent = { market_date: string; recorded_at: string; recommendation: string; decision_score: number | null; buy_reasons: string[] };
export type Report = {
  generated_at: string; market_date: string | null; score: number | null; label: string; mode: string;
  delivery_mode?: "live" | "cached"; read_at?: string; indicators: Indicator[];
  decision: { score: number | null; recommendation: string; triggers: Trigger[]; suppressed_signals: string[]; weights: Record<string, number>; available_indicators?: number; strengths?: Record<string, number> };
  ndx_52_week?: { latest: number; high: number; drawdown_pct: number; is_new_high: boolean; date: string } | null;
  buy_signal_history?: BuyEvent[]; reminders?: string[]; errors?: string[];
  dca?: Dca | null; premiums?: Premiums | null; module_errors?: string[];
};
export type Dimension = { score: number | null; value: number | null; dataType?: string; note?: string };
export type Dca = {
  fetched_at: string;
  top: { totalScore: number | null; multiplier: number | null; advice?: string; eventType?: string; dataQuality?: { fresh?: boolean; staleFields?: string[] } };
  twelve: { dimensions: Record<string, Dimension>; weights?: Record<string, number> };
};
export type PremiumFund = {
  code: string; name: string; current: { premium: number | null; quote_date: string; nav_date: string };
  sample_count: number; percentile: number | null; distribution: { key: string; label: string; count: number }[]; error?: string;
};
export type Premiums = { fetched_at: string; window: { trading_days: number }; funds: PremiumFund[] };
export const weights: Record<string, number> = { aaii: 20, ndx_forward_pe: 10, naaim: 20, vix: 25, qqq_rsi: 25 };
export const names: Record<string, string> = { aaii: "AAII", ndx_forward_pe: "预估市盈率", naaim: "NAAIM", vix: "VIX", qqq_rsi: "QQQ RSI6" };
export function finite(value: unknown): value is number { return typeof value === "number" && Number.isFinite(value); }
export function number(value: unknown, digits = 1, suffix = "") { return finite(value) ? `${value.toFixed(digits)}${suffix}` : "—"; }
export function time(value?: string | null) {
  if (!value || !Number.isFinite(Date.parse(value))) return "未知";
  return new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value));
}
export function dayAt(date: Date, zone = "America/New_York") {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(date);
  const p = Object.fromEntries(parts.map((x) => [x.type, x.value]));
  return `${p.year}-${p.month}-${p.day}`;
}
const shift = (day: string, n: number) => new Date(Date.parse(`${day}T12:00:00Z`) + n * 86400000).toISOString().slice(0, 10);
const weekday = (day: string) => new Date(`${day}T12:00:00Z`).getUTCDay();
function nthMonday(year: number, month: number, n: number) {
  const start = `${year}-${String(month).padStart(2, "0")}-01`;
  return shift(start, (8 - weekday(start)) % 7 + (n - 1) * 7);
}
function holidays(year: number) {
  const observed = (month: string, day: string) => {
    const date = `${year}-${month}-${day}`;
    return shift(date, weekday(date) === 6 ? -1 : weekday(date) === 0 ? 1 : 0);
  };
  const a = year % 19, b = Math.floor(year / 100), c = year % 100;
  const d = Math.floor(b / 4), e = b % 4, f = Math.floor((b + 8) / 25), g = Math.floor((b - f + 1) / 3);
  const h = (19 * a + b - d - g + 15) % 30, i = Math.floor(c / 4), k = c % 4;
  const l = (32 + 2 * e + 2 * i - h - k) % 7, m = Math.floor((a + 11 * h + 22 * l) / 451);
  const month = Math.floor((h + l - 7 * m + 114) / 31), day = (h + l - 7 * m + 114) % 31 + 1;
  const easter = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  const may31 = `${year}-05-31`;
  const thanksgiving = shift(`${year}-11-01`, (11 - weekday(`${year}-11-01`)) % 7 + 21);
  return new Set([
    weekday(`${year}-01-01`) === 0 ? `${year}-01-02` : `${year}-01-01`,
    nthMonday(year, 1, 3), nthMonday(year, 2, 3), shift(easter, -2),
    shift(may31, -((weekday(may31) + 6) % 7)), observed("06", "19"), observed("07", "04"),
    nthMonday(year, 9, 1), thanksgiving, observed("12", "25"),
  ]);
}
function sessionDay(day: string) { return ![0, 6].includes(weekday(day)) && !holidays(Number(day.slice(0, 4))).has(day); }
export function expectedSession(now = new Date()) {
  let day = dayAt(now);
  const hours = Number(new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "2-digit", hourCycle: "h23" }).format(now));
  const minutes = Number(new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", minute: "2-digit" }).format(now));
  // Conservative full-session close, with a 30-minute publishing allowance.
  if (hours * 60 + minutes < 16 * 60 + 30) day = shift(day, -1);
  while (!sessionDay(day)) day = shift(day, -1);
  return day;
}
export function validReport(value: unknown): value is Report {
  if (!value || typeof value !== "object") return false;
  const r = value as Report;
  return r.mode === "live" && typeof r.generated_at === "string" && Number.isFinite(Date.parse(r.generated_at))
    && Array.isArray(r.indicators) && r.indicators.length > 0 && r.indicators.every((x) => x && typeof x.name === "string" && typeof x.detail === "string" && typeof x.value === "string")
    && !!r.decision && typeof r.decision.recommendation === "string" && (r.decision.score === null || finite(r.decision.score))
    && Array.isArray(r.decision.triggers) && Array.isArray(r.decision.suppressed_signals);
}
export function freshness(report: Report, now = new Date()) {
  const expected = expectedSession(now);
  const quoteDates = report.indicators.filter((x) => ["vix", "qqq_rsi"].includes(x.name)).map((x) => x.detail.match(/行情日期 (\d{4}-\d{2}-\d{2})/)?.[1]).filter((x): x is string => !!x);
  const latest = quoteDates.length ? [...quoteDates].sort()[0] : null;
  const generatedDay = dayAt(new Date(report.generated_at));
  const generatedHour = Number(new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "2-digit", hourCycle: "h23" }).format(new Date(report.generated_at)));
  const intraday = !!latest && latest === generatedDay && generatedHour < 16;
  const stale = quoteDates.length < 2 || !latest || latest < expected;
  return { expected, latest, intraday, stale, title: stale ? "收盘数据待更新" : intraday ? "含盘中数据" : "已覆盖最近收盘日" };
}
export function indicatorDate(item: Indicator) { return item.detail.match(/(?:行情日期|数据日期|发布日期) (\d{4}-\d{2}-\d{2})/)?.[1] || null; }
export function indicatorStatus(item: Indicator, now = new Date()) {
  if (item.score === null || item.value === "不可用") return { text: "未获取", tone: "danger" };
  const date = indicatorDate(item);
  const age = date ? (Date.parse(`${dayAt(now)}T12:00:00Z`) - Date.parse(`${date}T12:00:00Z`)) / 86400000 : Infinity;
  if (["vix", "qqq_rsi"].includes(item.name)) return date && date >= expectedSession(now) ? { text: "近期行情", tone: "ok" } : { text: "待更新", tone: "warning" };
  if (age > 7 || /超过|过期/.test(item.detail)) return { text: item.name === "cftc_positioning" ? "周度参考" : "数据过期", tone: "warning" };
  return { text: item.name === "cftc_positioning" ? "周度参考" : "有效期内", tone: "ok" };
}
export function recentEvents(events: BuyEvent[] = [], now = new Date()) {
  const end = dayAt(now), start = shift(end, -179);
  return events.filter((x) => x.market_date >= start && x.market_date <= end).sort((a, b) => b.market_date.localeCompare(a.market_date));
}
