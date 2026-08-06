const DATA_URL = "./data/latest.json";
const CODES = { aaii: "AA", ndx_forward_pe: "PE", naaim: "NA", cftc_positioning: "CF", vix: "VX", qqq_rsi: "RS" };
let installPrompt = null;

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
  document.getElementById("sentimentLabel").textContent = `市场情绪 ${report.label || "--"}`;
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
    document.getElementById("ndxPosition").innerHTML = `<div class="high-position-card"><div class="high-position-value"><span>纳斯达克100</span><strong>${headline}</strong><p>${detail}</p></div><div class="high-position-meter" aria-label="当前点位相当于52周高点的${position.toFixed(2)}%"><div class="high-position-fill" style="width:${position}%"></div><div class="high-position-marker" style="left:${position}%"></div></div><div class="high-position-labels"><span>0</span><span>52周高点 = 100%</span></div></div>`;
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

window.addEventListener("beforeinstallprompt", (event) => { event.preventDefault(); installPrompt = event; });
document.getElementById("refreshButton").addEventListener("click", loadData);
document.getElementById("installButton").addEventListener("click", async () => {
  if (installPrompt) { await installPrompt.prompt(); installPrompt = null; }
  else alert("iPhone：点击 Safari 分享按钮，再选择“添加到主屏幕”。\nAndroid：打开浏览器菜单，选择“安装应用”。");
});
if ("serviceWorker" in navigator) window.addEventListener("load", () => navigator.serviceWorker.register("./sw.js").catch(() => {}));
loadData();
