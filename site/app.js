const DATA_URL = "./data/latest.json";
const DCA_URL = "./data/nasdaq-dca.json";
const CODES = { aaii: "AA", ndx_forward_pe: "PE", naaim: "NA", cftc_positioning: "CF", vix: "VX", qqq_rsi: "RS" };
const DCA_DIMENSIONS = [
  ["pe", "PE估值", "12%"], ["pb", "PB估值", "8%"], ["macd", "MACD", "10%"],
  ["rsi", "RSI", "8%"], ["bollinger", "布林带", "7%"], ["ma50", "MA50", "10%"],
  ["ma200", "MA200", "8%"], ["vix", "VIX", "8%"], ["yield10y", "美债10Y", "7%"],
  ["dxy", "美元指数", "6%"], ["fearGreed", "恐惧贪婪", "8%"], ["aaii", "AAII", "8%"],
];

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
}

function dateTime(value) {
  if (!value) return "等待更新";
  return new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value));
}

function indicatorState(item) {
  if (item.score === null || item.value === "不可用") return ["不可用", "danger"];
  if ((item.detail || "").includes("超过") || (item.detail || "").includes("过期")) return ["需更新", "warning"];
  return ["已同步", "ok"];
}

function render(report, mode = "live") {
  const score = Number(report.score ?? 0);
  document.getElementById("score").textContent = report.score ?? "--";
  document.getElementById("scoreGauge").style.setProperty("--score", `${score * 3.6}deg`);
  document.getElementById("recommendation").textContent = report.decision?.recommendation || "数据不足";
  const decisionScore = Number(report.decision?.score ?? 0);
  const decisionNode = document.getElementById("decisionScore");
  decisionNode.textContent = `${decisionScore > 0 ? "+" : ""}${decisionScore.toFixed(1)}`;
  decisionNode.className = decisionScore >= 20 ? "positive" : decisionScore <= -20 ? "negative" : "neutral";
  document.getElementById("marketDate").textContent = `美东 ${report.market_date || "—"} 收盘后`;
  document.getElementById("sentimentLabel").textContent = `市场情绪温度 ${report.label || "--"}`;
  document.getElementById("generatedAt").textContent = `北京 ${dateTime(report.generated_at)}`;

  const indicators = Array.isArray(report.indicators) ? report.indicators : [];
  document.getElementById("indicatorCount").textContent = `${indicators.filter((x) => x.score !== null).length}/6 已同步`;
  document.getElementById("indicatorList").innerHTML = indicators.map((item) => {
    const [state, tone] = indicatorState(item);
    return `<article class="indicator-card"><div class="indicator-code">${escapeHtml(CODES[item.name] || "--")}</div><div><div class="indicator-title-row"><h3>${escapeHtml(item.label)}</h3><span class="status-dot ${tone}">${state}</span></div><p class="indicator-value">${escapeHtml(item.value)}</p><p class="indicator-detail">${escapeHtml(item.detail)}</p></div></article>`;
  }).join("");

  const triggers = report.decision?.triggers || [];
  const stale = report.decision?.suppressed_signals || [];
  document.getElementById("triggerList").innerHTML = triggers.length || stale.length
    ? triggers.map((item) => `<div class="trigger-item ${item.direction}"><span>${item.direction === "buy" ? "买" : "卖"}</span><p>${escapeHtml(item.reason)}</p></div>`).join("") + stale.map((item) => `<div class="trigger-item stale"><span>旧</span><p>${escapeHtml(item)}</p></div>`).join("")
    : '<p class="empty-state">本次没有指标达到预设阈值。</p>';

  const ndx = report.ndx_52_week;
  document.getElementById("ndxDate").textContent = ndx?.date || "等待更新";
  if (ndx) {
    const position = Math.max(0, Math.min(100, 100 - Number(ndx.drawdown_pct || 0)));
    const headline = ndx.is_new_high ? "创52周新高" : `-${Number(ndx.drawdown_pct).toFixed(2)}%`;
    const detail = ndx.is_new_high ? `新高点 ${Number(ndx.latest).toLocaleString()}` : `当前 ${Number(ndx.latest).toLocaleString()} · 高点 ${Number(ndx.high).toLocaleString()}`;
    document.getElementById("ndxPosition").innerHTML = `<div class="high-position-card"><div class="high-position-value"><span>纳斯达克100</span><strong>${headline}</strong><p>${detail}</p></div><div class="high-position-meter" aria-label="当前点位相当于52周高点的${position.toFixed(2)}%"><div class="high-position-fill" style="width:${position}%"></div><div class="high-position-marker" style="left:${position}%"></div></div></div>`;
  } else {
    document.getElementById("ndxPosition").innerHTML = '<p class="empty-state">暂时没有纳斯达克100的52周高点数据。</p>';
  }

  const banner = document.getElementById("modeBanner");
  banner.classList.toggle("is-hidden", mode === "live");
  if (mode !== "live") document.getElementById("modeText").textContent = "网络暂时不可用，显示本机保存的上次数据。";
}

async function loadData() {
  const button = document.getElementById("refreshButton");
  const error = document.getElementById("errorPanel");
  button.classList.add("spinning");
  error.classList.add("is-hidden");
  try {
    const response = await fetch(`${DATA_URL}?t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const report = await response.json();
    localStorage.setItem("sentiment-report", JSON.stringify(report));
    render(report, "live");
  } catch (reason) {
    const cached = localStorage.getItem("sentiment-report");
    if (cached) render(JSON.parse(cached), "cached");
    else {
      error.textContent = `数据暂时无法读取：${reason.message}。请稍后刷新。`;
      error.classList.remove("is-hidden");
    }
  } finally { button.classList.remove("spinning"); }
}

function compactNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return Math.abs(number) >= 1000 ? number.toLocaleString("zh-CN", { maximumFractionDigits: 0 }) : number.toFixed(2).replace(/\.00$/, "");
}

function renderDca(payload) {
  const top = payload.top || {};
  const twelve = payload.twelve || {};
  document.getElementById("dcaScore").textContent = top.totalScore ?? "--";
  document.getElementById("dcaMultiplier").textContent = `${Number(top.multiplier ?? twelve.multiplier ?? 0).toFixed(2)}x`;
  document.getElementById("dcaEvent").textContent = top.eventType || top.status || "等待数据";
  document.getElementById("dcaAdvice").textContent = top.advice || "暂无定投建议";
  const valuation = top.indicators?.valuation || {};
  const priceChange = Number(top.priceChange);
  document.getElementById("dcaMarketStrip").innerHTML = [
    ["NASDAQ-100", `$${compactNumber(top.qqqPrice)}`],
    ["PE", compactNumber(valuation.pe)],
    ["PB", compactNumber(valuation.pb)],
  ].map(([label, value], index) => `<div class="dca-market-item"><span>${label}</span><strong>${value}${index === 0 && Number.isFinite(priceChange) ? ` <small class="${priceChange >= 0 ? "positive" : "negative"}">${priceChange >= 0 ? "+" : ""}${priceChange.toFixed(2)}%</small>` : ""}</strong></div>`).join("");
  document.getElementById("dcaUpdated").textContent = `北京 ${dateTime(payload.fetched_at)}`;
  const dimensions = twelve.dimensions || {};
  document.getElementById("dcaDimensions").innerHTML = DCA_DIMENSIONS.map(([key, label, weight]) => {
    const item = dimensions[key] || {};
    const score = Number(item.score);
    const safeScore = Number.isFinite(score) ? Math.max(0, Math.min(100, score)) : 0;
    return `<article class="dca-dimension-card"><div class="dca-dimension-title"><span>${label}</span><small>${weight}</small></div><div class="dca-dimension-score"><strong>${Number.isFinite(score) ? score.toFixed(0) : "--"}</strong><span>数值 ${compactNumber(item.value)}</span></div><div class="dca-dimension-bar"><i style="width:${safeScore}%"></i></div></article>`;
  }).join("");
}

async function loadDcaData() {
  try {
    const response = await fetch(`${DCA_URL}?t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    localStorage.setItem("nasdaq-dca-report", JSON.stringify(payload));
    renderDca(payload);
  } catch {
    const cached = localStorage.getItem("nasdaq-dca-report");
    if (cached) renderDca(JSON.parse(cached));
    else document.getElementById("dcaDimensions").innerHTML = '<p class="empty-state">第三方纳指评分暂时无法读取。</p>';
  }
}

function loadAll() {
  return Promise.allSettled([loadData(), loadDcaData()]);
}

document.getElementById("refreshButton").addEventListener("click", loadAll);
if ("serviceWorker" in navigator) window.addEventListener("load", () => navigator.serviceWorker.register("./sw.js").catch(() => {}));
loadAll();
