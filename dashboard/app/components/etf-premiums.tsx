"use client";

import { useState } from "react";
import { finite, number, time, validPremiums } from "../lib/market";
import type { Premiums } from "../lib/market";

const COLORS = ["#6aa9c8", "#71c7a6", "#c9f174", "#e5a93f", "#cc5a49"];

export default function EtfPremiums({ data }: { data?: Premiums | null }) {
  const [code, setCode] = useState("159501");
  const premiums = validPremiums(data) ? data : null;
  const fund = premiums?.funds.find(x => x.code === code) || premiums?.funds[0];
  const total = fund?.sample_count || 0;
  let count = 0;
  const gradient = fund?.distribution.map((x, i) => {
    const start = count; count += x.count;
    return `${COLORS[i % COLORS.length]} ${total ? start / total * 100 : 0}% ${total ? count / total * 100 : 0}%`;
  }).join(",");
  return <section className="section-block" id="premium">
    <div className="section-heading"><div><p className="section-kicker">NASDAQ ETF PREMIUM · IOPV</p><h2>纳指ETF溢价查询</h2></div><span className="count-chip">{premiums?.funds.length || "—"}只基金</span></div>
    {fund ? <div className="premium-result" aria-live="polite">
      <label className="fund-selector">选择场内基金<select value={fund.code} onChange={e => setCode(e.target.value)}>{premiums?.funds.map(x => <option key={x.code} value={x.code}>{x.code} · {x.name}</option>)}</select></label>
      <div className="premium-stats">
        <div><span>最新参考溢价 · IOPV</span><strong>{number(fund.current.premium, 2, "%")}</strong><small>{fund.current.status === "intraday" ? "盘中快照" : "收盘后快照"} {fund.current.quote_date || "未知"} {fund.current.quote_at ? time(fund.current.quote_at).slice(-5) : ""}</small></div>
        <div><span>{total >= 120 ? "近120个交易日百分位" : `已积累${total}日 · 百分位`}</span><strong>{number(fund.percentile, 1, "%")}</strong><small>{finite(fund.percentile) ? `高于或等于${number(fund.percentile, 1)}%的同口径收盘样本` : "至少20个有效收盘样本后显示"}</small></div>
      </div>
      <p className="premium-method">场内价格 {number(fund.current.price, 3)} ÷ IOPV {number(fund.current.iopv, 4)} − 1<br/>当前值、收盘记录与历史统计均为 IOPV 口径，不使用滞后单位净值。</p>
      {(fund.current.retained || fund.error || fund.current.error) && <p className="premium-alert" role="status">{fund.current.retained ? "本次未取得有效新行情，保留上次有效值，日期与读取时间未更新。" : "当前行情不可用或未通过校验，不用单位净值替代。"} {fund.error || fund.current.error || ""}</p>}
      {fund.current.status === "stale" && <p className="premium-alert" role="status">行情未覆盖最近一个工作日，可能为休市或上游更新延迟，请核对上方日期。</p>}
      <div className="premium-chart-layout"><div className="premium-donut" style={{ background: total ? `conic-gradient(${gradient})` : "#344b44" }} role="img" aria-label={`${fund.name}的收盘IOPV溢价分布，共${total}个交易日`}><div><strong>{total}</strong><span>收盘样本</span></div></div><div className="premium-legend">{fund.distribution.map((x, i) => <div key={x.key}><i style={{ background: COLORS[i % COLORS.length] }}/><span>{x.label}</span><b>{x.count}天<small>{number(total ? x.count / total * 100 : null, 1, "%")}</small></b></div>)}</div></div>
      <p className="premium-method">各基金独立分档 · 最多保留最近120个有效收盘记录<br/>样本区间 {fund.history_from || "—"} 至 {fund.history_to || "—"}<br/>行情读取（北京）{time(fund.current.retrieved_at)}</p>
      {total < 120 && <p className="premium-method">统一口径后重新积累，现有{total}个有效交易日。旧的净值/IOPV混合记录已退出统计，未收集的历史IOPV不补算。</p>}
      <details className="premium-method"><summary>数据来源与统计方式</summary><p>参考溢价＝（场内价格÷同一行情快照的IOPV−1）×100%。每日A股收盘后记录；盘中快照不写入收盘历史。参考净值是估算值，不等于最终公布的单位净值。</p><p>百分位＝历史收盘样本中小于等于当前参考溢价的比例。不足20日不显示，20至119日仅代表已积累样本。</p><p>数据源自<a href={`https://qt.gtimg.cn/q=${fund.code.startsWith("5") ? "sh" : "sz"}${fund.code}`} target="_blank" rel="noreferrer">腾讯公开行情 ↗</a>，与行情软件采用同一IOPV计算口径；不同供应商的快照时点和四舍五入可能有差异。本网站为定时快照，非盘中实时交易行情。</p></details>
    </div> : <div className="empty-card compact"><p>IOPV溢价数据暂时无法读取。旧的混合净值数据已停用，请稍后刷新。</p></div>}
  </section>;
}
