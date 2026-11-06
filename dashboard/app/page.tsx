"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { finite, freshness, indicatorDate, indicatorStatus, names, number, recentEvents, time, validReport, weights } from "./lib/market";
import type { Report } from "./lib/market";
import { loadStaticReport } from "./lib/load-static";
import MarketContextPanel from "./components/market-context";

const CACHE_KEY = "market-pulse-report-v4";
const CODES: Record<string, string> = { aaii: "AA", ndx_forward_pe: "PE", naaim: "NA", cftc_positioning: "CF", vix: "VX", qqq_rsi: "RS" };
const DIMENSIONS = [["pe", "PE估值"], ["pb", "PB估值"], ["macd", "MACD"], ["rsi", "RSI"], ["bollinger", "布林带"], ["ma50", "MA50"], ["ma200", "MA200"], ["vix", "VIX"], ["yield10y", "美债10Y"], ["dxy", "美元指数"], ["fearGreed", "恐惧贪婪"], ["aaii", "AAII"]];
const COLORS = ["#6aa9c8", "#71c7a6", "#c9f174", "#e5a93f", "#cc5a49"];
function signed(value: unknown) { return finite(value) ? `${value > 0 ? "+" : ""}${value.toFixed(1)}` : "—"; }
function cleanDetail(value: string) { return value.replace(/；?(AAII Insights官方周报|VCP Scanner[^；]*|CFTC TFF官方数据|数值越高[^；]*|仅供参考，权重0%，不参与综合评分)/g, ""); }

export default function Home({ staticMode = false }: { staticMode?: boolean }) {
  const [report, setReport] = useState<Report | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const [message, setMessage] = useState("");
  const [now, setNow] = useState(() => new Date());
  const [fundCode, setFundCode] = useState("159501");
  const [nav, setNav] = useState("top");
  const inFlight = useRef(false);
  const lastAttempt = useRef(0);

  const loadReport = useCallback(async (manual = false) => {
    if (inFlight.current || (!manual && Date.now() - lastAttempt.current < 60000)) return;
    inFlight.current = true;
    lastAttempt.current = Date.now();
    setRefreshing(true);
    try {
      const readServer = async () => {
        const response = await fetch(`/api/report?t=${Date.now()}`, { cache: "no-store", signal: AbortSignal.timeout(15000) });
        if (!response.ok) throw new Error("实时数据读取失败");
        return response.json();
      };
      const next: unknown = staticMode ? await loadStaticReport() : await readServer();
      if (!validReport(next)) throw new Error("数据格式异常");
      setReport(next);
      try { localStorage.setItem(CACHE_KEY, JSON.stringify(next)); } catch { /* Storage is optional. */ }
      setMessage(manual ? "已重新读取服务器数据；行情日期见下方状态。" : "");
    } catch {
      let cached: Report | null = null;
      try {
        const value: unknown = JSON.parse(localStorage.getItem(CACHE_KEY) || "null");
        if (validReport(value)) cached = value;
      } catch { /* A damaged cache must not prevent retry. */ }
      if (cached) setReport({ ...cached, delivery_mode: "cached" });
      else setReport((previous) => previous ? { ...previous, delivery_mode: "cached" } : null);
      setMessage("本次读取失败。已有数据会标记为本机缓存，请稍后重试。");
    } finally {
      inFlight.current = false;
      setAttempted(true);
      setRefreshing(false);
      setNow(new Date());
    }
  }, [staticMode]);

  useEffect(() => {
    void loadReport();
    const visible = () => { if (document.visibilityState === "visible") void loadReport(); };
    const timer = window.setInterval(() => { setNow(new Date()); visible(); }, 5 * 60000);
    document.addEventListener("visibilitychange", visible);
    window.addEventListener("focus", visible);
    window.addEventListener("online", visible);
    if ("serviceWorker" in navigator) void navigator.serviceWorker.register(staticMode ? "./sw.js" : "/sw.js").catch(() => undefined);
    return () => { window.clearInterval(timer); document.removeEventListener("visibilitychange", visible); window.removeEventListener("focus", visible); window.removeEventListener("online", visible); };
  }, [loadReport, staticMode]);

  const fresh = report ? freshness(report, now) : null;
  const events = recentEvents(report?.buy_signal_history, now);
  const decision = report?.decision;
  const cached = report?.delivery_mode === "cached";
  const caution = cached || fresh?.stale || fresh?.intraday;
  const dca = report?.dca;
  const premiums = report?.premiums;
  const fund = premiums?.funds.find((x) => x.code === fundCode) || premiums?.funds[0];
  const total = fund?.distribution.reduce((sum, x) => sum + x.count, 0) || 0;
  let count = 0;
  const gradient = fund?.distribution.map((x, i) => { const start = count; count += x.count; return `${COLORS[i % COLORS.length]} ${total ? start / total * 100 : 0}% ${total ? count / total * 100 : 0}%`; }).join(",");
  const unavailable = report?.indicators.filter((x) => x.score === null || x.value === "不可用").length || 0;

  return <main className="app-shell" aria-busy={refreshing}>
    <header className="topbar">
      <a className="brand-lockup" href="#top" aria-label="Market Pulse 首页"><span className="brand-mark"><svg viewBox="0 0 40 40" aria-hidden="true"><path d="M6 31H34M7 31V8" className="chart-grid"/><path d="M8 27L14 21L19 24L25 14L32 9M26 9H32V15"/></svg></span><div><p className="eyebrow">YOUR DAILY MARKET BRIEF</p><h1>MARKET PULSE</h1></div></a>
      <button className={`refresh-button ${refreshing ? "spinning" : ""}`} onClick={() => void loadReport(true)} disabled={refreshing} aria-label="重新读取数据">↻</button>
    </header>

    <section className={`sync-panel ${caution ? "warning" : report ? "ok" : "neutral"}`} aria-label="数据更新状态" aria-live="polite">
      <div className="sync-title"><span className="status-light"/><strong>{cached ? "读取失败 · 显示本机缓存" : fresh?.title || (attempted ? "暂时无法读取数据" : "正在读取最新数据")}</strong><span>{refreshing ? "同步中" : report ? "自动同步" : ""}</span></div>
      <p>{fresh ? `应覆盖美东 ${fresh.expected} 收盘 · 当前行情 ${fresh.latest || "未知"}` : "打开页面、回到前台时会检查；停留期间每5分钟重新读取。"}</p>
      {report && <div className="sync-times"><span>数据生成（北京）<b>{time(report.generated_at)}</b></span><span>服务读取（北京）<b>{time(report.read_at)}</b></span></div>}
      {fresh?.intraday && <p className="sync-explain">此批行情生成于美股收盘前，暂不能视为当日最终收盘值。</p>}
      {fresh?.stale && <p className="sync-explain">抓取或发布可能延迟，下方保留原始日期及上次判断。</p>}
    </section>
    {message && <p className="inline-message" role="status">{message}</p>}

    {!report ? <section className="empty-card"><span className={refreshing ? "loader" : "empty-symbol"}>{refreshing ? "" : "↻"}</span><h2>{attempted ? "数据暂时不可用" : "正在同步市场快照"}</h2><p>{attempted ? "请检查网络后重试。未读取成功时不会展示模拟分数。" : "正在核对自有指标、第三方评分与ETF溢价。"}</p>{attempted && <button className="primary-button" onClick={() => void loadReport(true)}>重新读取</button>}</section> : <>
      <section className="active-module" aria-label="纳指主动加仓指标">
        <div className="module-head"><div><p className="section-kicker">NASDAQ-100 ACTIVE ALLOCATION</p><h2>纳指主动加仓指标</h2></div><span className="source-chip">自有指标</span></div>
        <div className="hero-card">
          <div><p className="hero-date">{caution ? "本批数据判断" : "最近收盘判断"} · 美东 {fresh?.latest || report.market_date || "未知"}</p><h3>{decision?.recommendation || "数据不足"}</h3><p className="hero-description">五项指标加权 · {decision?.available_indicators ?? "—"}/5 项可用</p></div>
          <div className={`decision-score ${finite(decision?.score) && decision.score >= 20 ? "positive" : finite(decision?.score) && decision.score <= -20 ? "negative" : "neutral"}`}><strong>{signed(decision?.score)}</strong><span>买入决策分</span></div>
          <div className="score-scale"><i style={{ left: `${finite(decision?.score) ? (Math.max(-100, Math.min(100, decision.score)) + 100) / 2 : 50}%` }}/></div><div className="score-labels"><span>偏向卖出 −100</span><span>观望</span><span>+100 偏向买入</span></div>
          <details className="score-help"><summary>如何读懂这个分数</summary><p>买入决策分为 −100 至 +100，越高越偏向买入。≥50 强烈买入，≥20 建议买入，−20 至20之间观望。它是现有阈值规则的加权结果，不是上涨概率。</p><p>市场情绪温度 {number(report.score, 1)} / 100 · {report.label}。情绪温度与买入决策分是两种不同口径。</p></details>
        </div>
      </section>

      <section className="section-block insight-card" id="decision"><div className="section-heading"><div><p className="section-kicker">WHY THIS CALL</p><h2>本次判断依据</h2></div><span className="count-chip">{decision?.triggers.length || 0} 项触发</span></div>
        <div className="trigger-list">{decision?.triggers.length ? decision.triggers.map((x, i) => <div className={`trigger-item ${x.direction}`} key={i}><span>{x.direction === "buy" ? "买" : "卖"}</span><p>{x.reason}</p></div>) : <p className="empty-state">没有指标达到预设触发阈值。</p>}{decision?.suppressed_signals.map((x, i) => <div className="trigger-item stale" key={`s${i}`}><span>旧</span><p>{x}</p></div>)}</div>
        <details className="weights-detail"><summary>评分权重与数据覆盖</summary><div className="weight-grid">{Object.entries(weights).map(([key, value]) => { const item = report.indicators.find((x) => x.name === key); const excluded = !item || item.score === null || (key === "naaim" && indicatorStatus(item, now).tone === "warning"); return <div key={key}><span>{names[key]}</span><b>{value}%</b><small>{excluded ? "本批不计" : "原始设定"}</small></div>; })}</div><p>缺失项及过期NAAIM不参与本批综合判断，按其余可用项归一化；AAII与市盈率超过7天停止买入提示。</p></details>
      </section>

      <section className="section-block" id="indicators"><div className="section-heading"><div><p className="section-kicker">DATA HEALTH</p><h2>指标与数据状态</h2></div><span className="count-chip">{report.indicators.length - unavailable}/{report.indicators.length} 已获取</span></div><div className="indicator-list">{report.indicators.map((item) => { const state = indicatorStatus(item, now); return <article className="indicator-card" key={item.name}><div className="indicator-code">{CODES[item.name] || "IN"}</div><div className="indicator-main"><div className="indicator-title-row"><h3>{item.label}</h3><span className={`status-dot ${state.tone}`}>{state.text}</span></div><p className="indicator-value">{item.value}</p><p className="indicator-detail">{cleanDetail(item.detail)}</p><span className="data-date">{indicatorDate(item) || "日期未知"} · {item.name === "cftc_positioning" ? "独立参考" : ["aaii", "naaim", "cftc_positioning"].includes(item.name) ? "周度更新" : item.name === "ndx_forward_pe" ? "以来源发布为准" : "日线行情"}</span></div></article>; })}</div></section>

      <MarketContextPanel data={report.market_context} now={now} cached={cached}/>

      <section className="section-block dca-module" id="dca"><div className="module-head"><div><p className="section-kicker">NASDAQ-100 DCA</p><h2>纳指定投评分</h2></div><span className="source-chip">第三方参考</span></div>{dca ? <><div className="dca-summary"><div><span>综合评分</span><strong>{number(dca.top.totalScore, 0)}<small>/100</small></strong></div><div><span>建议定投倍数</span><strong className="amber">{number(dca.top.multiplier, 2, "×")}</strong></div></div><p className="dca-advice">{dca.top.advice || "来源暂未给出建议"}</p><p className="dca-meta">北京 {time(dca.fetched_at)} · 数据源自 <a href="https://www.btcdca.me/nasdaq/" target="_blank" rel="noreferrer">btcdca.me ↗</a></p>{dca.top.dataQuality?.fresh === false && <p className="dca-quality">来源提示部分数据存在估算或滞后：{dca.top.dataQuality.staleFields?.join("、") || "请核对来源"}</p>}<details className="dimension-details"><summary>查看12维度数据</summary><div className="dimension-grid">{DIMENSIONS.map(([key, label]) => { const x = dca.twelve.dimensions[key]; const w = dca.twelve.weights?.[key]; return <div className="dimension" key={key}><header><span>{label}</span><small>{finite(w) ? `${w}%` : "未分配"}</small></header><strong>{number(x?.score, 0)}<small> 分</small></strong><p>数值 {number(x?.value, 2)}</p><div className="dimension-bar"><i style={{width:`${finite(x?.score) ? Math.max(0, Math.min(100, x.score)) : 0}%`}}/></div><small>{x?.dataType === "pending" ? "来源尚未接入" : x?.dataType === "estimated" ? "估算值" : "来源数据"}</small></div>; })}</div></details></> : <p className="module-empty">第三方评分暂时无法读取，下次刷新会重试。</p>}</section>

      <section className="section-block" id="premium"><div className="section-heading"><div><p className="section-kicker">NASDAQ ETF PREMIUM</p><h2>纳指ETF溢价查询</h2></div><span className="count-chip">{premiums?.funds.length || "—"}只基金</span></div>{fund ? <div className="premium-result"><label className="fund-selector">选择场内基金<select value={fund.code} onChange={(e) => setFundCode(e.target.value)}>{premiums?.funds.map((x) => <option key={x.code} value={x.code}>{x.code} · {x.name}</option>)}</select></label><div className="premium-stats"><div><span>当前溢价率</span><strong>{number(fund.current.premium, 2, "%")}</strong><small>行情 {fund.current.quote_date || "未知"}</small></div><div><span>近120个交易日百分位</span><strong>{number(fund.percentile, 1, "%")}</strong><small>{finite(fund.percentile) ? `高于或等于${number(fund.percentile, 1)}%的历史样本` : "样本不足"}</small></div></div><div className="premium-chart-layout"><div className="premium-donut" style={{ background: total ? `conic-gradient(${gradient})` : "#344b44" }} role="img" aria-label={`${fund.name}的溢价率分布，共${total}个交易日`}><div><strong>{total}</strong><span>有效交易日</span></div></div><div className="premium-legend">{fund.distribution.map((x, i) => <div key={x.key}><i style={{ background: COLORS[i % COLORS.length] }}/><span>{x.label}</span><b>{x.count}天<small>{number(total ? x.count / total * 100 : null, 1, "%")}</small></b></div>)}</div></div><p className="premium-method">各基金独立分档 · 最近120个交易日滚动统计<br/>净值基准日期 {fund.current.nav_date || "未知"} · 读取于北京 {time(premiums?.fetched_at)}</p>{fund.sample_count < 120 && <p className="premium-method">当前仅有{fund.sample_count}个有效样本，尚未达到120个交易日。</p>}{fund.error && <p className="premium-method">部分历史获取失败，当前保留已有样本。</p>}</div> : <div className="empty-card compact"><p>ETF溢价数据暂时无法读取，请稍后刷新。</p></div>}</section>

      <section className="section-block trend-card" id="position"><div className="section-heading"><div><p className="section-kicker">52-WEEK POSITION</p><h2>距离52周高点</h2></div></div>{report.ndx_52_week ? <div className="high-position-card"><span>纳斯达克100 · {report.ndx_52_week.date}</span><strong>{report.ndx_52_week.is_new_high ? `新高 ${number(report.ndx_52_week.latest, 2)}` : `−${number(report.ndx_52_week.drawdown_pct, 2, "%")}`}</strong><p>当前 {number(report.ndx_52_week.latest, 2)} · 52周高点 {number(report.ndx_52_week.high, 2)}</p></div> : <p className="empty-state">行情暂未获取。</p>}</section>

      <section className="section-block history-card" id="history"><div className="section-heading"><div><p className="section-kicker">BUY SIGNAL HISTORY</p><h2>主动加仓信号记录</h2></div><span className="count-chip">近180天 · {events.length}次</span></div><p className="section-note">自有指标进入买入区间的首次记录日，连续买入不重复。按美东日期，最新记录在前。</p><div className="history-list">{events.length ? events.map((x) => <article className="history-item" key={`${x.market_date}-${x.recorded_at}`}><div className="history-date"><small>美东</small><strong>{x.market_date}</strong><span>{x.recommendation}</span></div><div className="history-content"><header><b>买入决策分</b><strong>{signed(x.decision_score)}</strong></header><ul>{x.buy_reasons?.map((reason, i) => <li key={i}>{reason}</li>)}</ul><small>首次记录 · 北京 {time(x.recorded_at)}</small></div></article>) : <p className="empty-state">近180天尚无已记录的买入信号。没有历史数据的日期不会补算。</p>}</div></section>
    </>}

    {report && ((report.reminders?.length || 0) + (report.errors?.length || 0) + (report.module_errors?.length || 0) > 0) && <details className="source-notices"><summary>数据源提醒（{(report.reminders?.length || 0) + (report.errors?.length || 0) + (report.module_errors?.length || 0)}）</summary>{[...(report.reminders || []), ...(report.errors || []), ...(report.module_errors || [])].map((x, i) => <p key={i}>{x}</p>)}</details>}
    <footer><p>数据按来源发布节奏更新 · 刷新页面不会触发上游重新抓取</p><p>规则信号仅供信息参考。</p><a href="https://uui000718-ai.github.io/us-market-sentiment-app/" target="_blank" rel="noreferrer">GitHub Pages 备用入口 ↗</a></footer>
    <nav className="bottom-nav" aria-label="应用导航">{[["top", "◉", "今日"], ["indicators", "▦", "指标"], ["premium", "◔", "溢价"], ["history", "↗", "记录"]].map(([id, icon, label]) => <a href={`#${id}`} className={nav === id ? "active" : ""} onClick={() => setNav(id)} key={id}><span>{icon}</span>{label}</a>)}</nav>
  </main>;
}
