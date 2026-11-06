"use client";
import { useState } from "react";
import { dayAt, finite, number, time } from "../lib/market";
import type { ContextMetric, ContextPoint, MarketContext } from "../lib/market";

function signed(value: unknown, digits = 2, unit = "") { return finite(value) ? `${value > 0 ? "+" : ""}${value.toFixed(digits)}${unit}` : "—"; }
function itemStatus(item: ContextMetric, now: Date, cached: boolean) {
  if (!finite(item.value) || !item.as_of) return "未获取";
  if (cached) return "本机缓存";
  if (item.retained) return "保留上次";
  const age = (Date.parse(`${dayAt(now)}T12:00:00Z`) - Date.parse(`${item.as_of}T12:00:00Z`)) / 86400000;
  if (!Number.isFinite(age) || age > (item.kind === "stress" ? 21 : 7)) return "数据较旧";
  return item.kind === "relative" ? "日线收盘" : item.kind === "stress" ? "周度发布" : "日度发布";
}

function MiniChart({ series, relative, period, label }: { series: ContextPoint[]; relative: boolean; period: number; label: string }) {
  const valid = series.filter((p) => finite(p.value)).slice(-(relative ? period + 1 : 61));
  if (valid.length < 2 || (relative && valid[0].value === 0)) return <div className="context-chart-empty">暂无可用趋势序列</div>;
  const values = valid.map((p) => relative ? p.value / valid[0].value * 100 : p.value);
  const low = Math.min(...values), high = Math.max(...values);
  const span = high - low || Math.max(Math.abs(low) * .01, .01);
  const y = (n: number) => high === low ? 41 : 10 + (high - n) / span * 62;
  const path = values.map((v, i) => `${i ? "L" : "M"}${(8 + i / (values.length - 1) * 264).toFixed(2)},${y(v).toFixed(2)}`).join(" ");
  const baseline = relative ? 100 : 0;
  return <figure className="context-chart"><svg viewBox="0 0 280 82" role="img" aria-label={`${label}，${valid[0].date}至${valid.at(-1)?.date}的趋势${relative ? "，起点归一为100" : ""}`}>
    {baseline >= low && baseline <= high && <line x1="8" y1={y(baseline)} x2="272" y2={y(baseline)} stroke="#b4c5b8" strokeDasharray="3 4"/>}
    <path d={path} fill="none" stroke="#087455" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"/>
    <circle cx="272" cy={y(values.at(-1)!)} r="3" fill="#087455"/>
  </svg><figcaption><span>{valid[0].date.slice(5)}</span><span>{relative ? "相对比率 · 起点100" : "最近有效观测"}</span><span>{valid.at(-1)?.date.slice(5)}</span></figcaption></figure>;
}

export default function MarketContextPanel({ data, now, cached = false }: { data?: MarketContext | null; now: Date; cached?: boolean }) {
  const [period, setPeriod] = useState(20);
  return <section className="section-block context-section" id="market-context">
    <div className="section-heading"><div><p className="section-kicker">BEYOND THE SIGNAL</p><h2>市场环境观察</h2></div><span className="count-chip">辅助观察</span></div>
    <p className="context-intro">买入信号之外，看看行情参与度、真实利率和金融压力。</p>
    {!data ? <div className="context-unavailable"><p>市场环境数据暂未读取成功，核心指标仍可正常查看。</p></div> : <>
      <div className="context-period"><span>等权相对表现区间</span><div role="group" aria-label="选择相对表现区间">{[20, 60].map((n) => <button key={n} onClick={() => setPeriod(n)} aria-pressed={period === n}>{n}交易日</button>)}</div></div>
      <div className="context-grid">{data.items.map((item) => {
        const relative = item.kind === "relative";
        const selected = relative ? item.changes?.[String(period)] : item.value;
        const available = finite(selected);
        const status = itemStatus(item, now, cached);
        const frequency = item.kind === "stress" ? "周度" : "日度";
        const explanation = !available ? "等待可用数据" : relative ? selected > 0 ? "等权相对领先" : selected < 0 ? "市值权重相对领先" : "两者相对持平" : item.kind === "stress" ? selected > 0 ? "高于长期平均压力" : selected < 0 ? "低于长期平均压力" : "长期平均压力水平" : "TIPS实际收益率";
        return <article className={`context-card ${!available || ["保留上次", "数据较旧", "本机缓存"].includes(status) ? "context-muted" : ""}`} key={item.id}>
          <header><div><span className="context-symbol">{item.symbol}</span><h3>{item.title}</h3></div><span className="context-status">{status}</span></header>
          <div className="context-value"><strong>{relative ? signed(selected, 2, "%") : `${number(selected, item.kind === "stress" ? 3 : 2)}${available && item.kind === "yield" ? "%" : ""}`}</strong><span>{explanation}</span></div>
          <p className="context-comparison">{relative ? `比率较${period}个共同交易日前的变化` : item.kind === "yield" ? `较20个有效观测日前 ${signed(item.change, 0, " bp")}` : `较4周前 ${signed(item.change, 3)}`}</p>
          <MiniChart series={item.series} relative={relative} period={period} label={item.title}/>
          {!relative && <div className="context-percentile"><span>近3年内样本百分位</span><b>{number(item.percentile, 1, "%")}</b><div><i style={{ width: `${finite(item.percentile) ? Math.max(0, Math.min(100, item.percentile)) : 0}%` }}/></div><small>{item.window_from || "—"} 至 {item.window_to || "—"} · {item.sample_count ?? 0}个有效样本</small></div>}
          <div className="context-provenance"><span>观测日期 <b>{item.as_of || "未知"}</b> · {frequency}</span><span>成功读取 · 北京 {time(item.retrieved_at)}</span></div>
          {item.retained && <p className="context-retained">{item.error || "本次抓取未成功，保留已有日期的样本。"}</p>}
          <details className="context-method"><summary>怎么读 · 来源与方法</summary>{relative ? <><p>正值表示等权ETF相对市值权重ETF更强，负值相反。以两只ETF的共同交易日复权价格比率计算变化，已排除当天未完成的日线。</p><p>这是参与度的代理观察，不能当成上涨股票比例。行业权重、季度再平衡和基金费用也会影响比率。</p><a href={item.id === "nasdaq_participation" ? "https://www.direxion.com/product/nasdaq-100-equal-weighted-index-etf" : "https://www.invesco.com/us/financial-products/etfs/product-detail?productId=RSP"} target="_blank" rel="noreferrer">等权ETF说明 ↗</a><span> · 行情源自 Yahoo Finance</span></> : item.kind === "yield" ? <><p>美国10年期通胀保值国债实际收益率；它和普通10年期国债的名义收益率不同。1 bp = 0.01个百分点。百分位只描述该数值在近3年内样本中的位置，不是买入分数。</p><p>数据：美国联储理事会 H.15，经FRED分发。日度发布可能晚于股票行情；以观测日期为准。</p><a href="https://fred.stlouisfed.org/series/DFII10" target="_blank" rel="noreferrer">DFII10 · FRED官方数据 ↗</a></> : <><p>圣路易斯联储金融压力指数由18项周度金融序列构建。0代表长期平均；大于0表示压力高于平均，小于0表示压力低于平均。其百分位基于近3年内有效样本，两种口径不同。</p><p>数据：Federal Reserve Bank of St. Louis，STLFSI4，经FRED分发。周度指标不能替代实时市场信息，历史值可能修订。</p><a href="https://fred.stlouisfed.org/series/STLFSI4" target="_blank" rel="noreferrer">STLFSI4 · FRED官方数据 ↗</a></>}</details>
        </article>;
      })}</div>
      <p className="context-footnote">各数据按自己的日度或周度节奏发布；本模块不参与五项指标评分。抓取检查：北京 {time(data.fetched_at)}。</p>
    </>}
  </section>;
}
