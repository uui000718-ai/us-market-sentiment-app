const DATA_URL = "./data/latest.json";
const DCA_URL = "./data/nasdaq-dca.json";
const PREMIUM_URL = "./data/etf-premiums.json";
const CODES = { aaii: "AA", ndx_forward_pe: "PE", naaim: "NA", cftc_positioning: "CF", vix: "VX", qqq_rsi: "RS" };
const PREMIUM_COLORS = { discount: "#6aa9c8", low: "#71c7a6", medium: "#c9f174", high: "#e5a93f", extreme: "#cc5a49" };
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
  const naaimExcluded = stale.some((item) => String(item).startsWith("NAAIM数据"));
  document.getElementById("decisionWeights").textContent = naaimExcluded
    ? "AAII 20% · 预估市盈率 10% · NAAIM 数据过期（本期不计） · VIX 25% · QQQ RSI 25%"
    : "AAII 20% · 预估市盈率 10% · NAAIM 20% · VIX 25% · QQQ RSI 25%";
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

let premiumPayload = null;

function premiumLevel(percentile) {
  const value = Number(percentile);
  if (!Number.isFinite(value)) return ["样本不足", "neutral"];
  if (value >= 90) return ["历史高位", "danger"];
  if (value >= 75) return ["历史偏高", "warning"];
  if (value <= 10) return ["历史低位", "ok"];
  if (value <= 25) return ["历史偏低", "ok"];
  return ["历史中位", "neutral"];
}

function renderPremiumFund(code) {
  const error = document.getElementById("premiumError");
  const result = document.getElementById("premiumResult");
  error.classList.add("is-hidden");
  const fund = premiumPayload?.funds?.find((item) => item.code === code);
  if (!fund) {
    result.classList.add("is-hidden");
    error.textContent = "没有找到这只基金的溢价数据，请稍后刷新。";
    error.classList.remove("is-hidden");
    return;
  }
  const current = Number(fund.current?.premium);
  const percentile = Number(fund.percentile);
  const [levelText, levelTone] = premiumLevel(percentile);
  document.getElementById("premiumFundCode").textContent = fund.code;
  document.getElementById("premiumFundName").textContent = fund.name;
  document.getElementById("premiumCurrent").textContent = Number.isFinite(current) ? `${current > 0 ? "+" : ""}${current.toFixed(2)}%` : "--";
  document.getElementById("premiumPercentile").textContent = Number.isFinite(percentile) ? `${percentile.toFixed(1)}%` : "--";
  document.getElementById("premiumQuoteDate").textContent = `行情 ${fund.current?.quote_date || "--"} · 净值 ${fund.current?.nav_date || "--"}`;
  document.getElementById("premiumSampleCount").textContent = `有效样本 ${fund.sample_count || 0} 个交易日`;
  const level = document.getElementById("premiumLevel");
  level.textContent = levelText;
  level.className = `premium-level ${levelTone}`;

  const distribution = Array.isArray(fund.distribution) ? fund.distribution : [];
  const total = distribution.reduce((sum, item) => sum + Number(item.count || 0), 0);
  document.getElementById("premiumDays").textContent = total || "--";
  let accumulated = 0;
  const segments = distribution.filter((item) => Number(item.count) > 0).map((item) => {
    const start = accumulated / total * 360;
    accumulated += Number(item.count);
    const end = accumulated / total * 360;
    return `${PREMIUM_COLORS[item.key] || "#aab4b0"} ${start.toFixed(2)}deg ${end.toFixed(2)}deg`;
  });
  const donut = document.getElementById("premiumDonut");
  donut.style.background = total ? `conic-gradient(${segments.join(",")})` : "#e1e5df";
  donut.setAttribute("aria-label", `${fund.name}近180天溢价率分布，共${total}个有效交易日`);
  document.getElementById("premiumLegend").innerHTML = distribution.map((item) => {
    const count = Number(item.count || 0);
    const share = total ? count / total * 100 : 0;
    return `<div class="premium-legend-item"><i style="background:${PREMIUM_COLORS[item.key] || "#aab4b0"}"></i><span>${escapeHtml(item.label)}</span><strong>${count}天</strong><small>${share.toFixed(1)}%</small></div>`;
  }).join("");
  result.classList.remove("is-hidden");
}

function preparePremium(payload) {
  premiumPayload = payload;
  const funds = Array.isArray(payload?.funds) ? payload.funds : [];
  const select = document.getElementById("premiumFundSelect");
  select.innerHTML = funds.map((fund) => `<option value="${escapeHtml(fund.code)}">${escapeHtml(fund.code)} · ${escapeHtml(fund.name)}</option>`).join("");
  document.getElementById("premiumUpdated").textContent = `数据更新：北京 ${dateTime(payload.fetched_at)} · ${payload.window?.calendar_days || 180}天窗口`;
  const defaultFund = funds.find((fund) => fund.code === "159501") || funds[0];
  if (defaultFund) {
    select.value = defaultFund.code;
    renderPremiumFund(defaultFund.code);
  }
}

async function loadPremiumData() {
  const error = document.getElementById("premiumError");
  error.classList.add("is-hidden");
  try {
    const response = await fetch(`${PREMIUM_URL}?t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    if (!Array.isArray(payload.funds) || !payload.funds.length) throw new Error("基金列表为空");
    localStorage.setItem("etf-premium-report", JSON.stringify(payload));
    preparePremium(payload);
  } catch (reason) {
    const cached = localStorage.getItem("etf-premium-report");
    if (cached) preparePremium(JSON.parse(cached));
    else {
      document.getElementById("premiumFundSelect").innerHTML = '<option value="">载入失败，请点击右上角刷新</option>';
      error.textContent = `溢价数据暂时无法读取：${reason.message}。请稍后刷新。`;
      error.classList.remove("is-hidden");
    }
  }
}

function loadAll() {
  return Promise.allSettled([loadData(), loadDcaData(), loadPremiumData()]);
}

const refreshButton = document.getElementById("refreshButton");
if (refreshButton) refreshButton.addEventListener("click", loadAll);
const premiumFundSelect = document.getElementById("premiumFundSelect");
if (premiumFundSelect) premiumFundSelect.addEventListener("change", (event) => renderPremiumFund(event.target.value));
if ("serviceWorker" in navigator) window.addEventListener("load", () => navigator.serviceWorker.register("./sw.js").catch(() => {}));
loadAll();
