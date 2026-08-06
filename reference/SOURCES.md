# 数据源与计算口径

## AAII Investor Sentiment Survey

- 首选：https://insights.aaii.com/feed （AAII 官方周报 RSS）
- 备用：https://www.aaii.com/sentimentsurvey/sent_results
- 字段：Bullish、Neutral、Bearish，以及 Bullish-Bearish spread。
- 周频。RSS 的日期是文章发布日期，历史结果页日期是调查报告日期。

## Nasdaq-100 Forward P/E

- 当前值首选：https://vcpscanner.com/market-valuation/nasdaq-100
- 当前值备用：https://www.nasdaq.com/docs/index/global-index-investment-insights
- 历史样本初始来源：https://trendonify.com/united-states/stock-market/nasdaq-100/forward-pe-ratio
- 当前值首选数据为成分股预估盈利聚合；备用为 Nasdaq Global Index Insights 中的 NTM P/E。
- 百分位公式：近 `NDX_PE_PERCENTILE_YEARS` 年月度样本中，小于等于当前值的样本数 ÷ 总样本数。
- 可用 `NDX_FORWARD_PE_OVERRIDE` 和 `NDX_FORWARD_PE_DATE` 接入用户指定的付费数据源。

## NAAIM Exposure Index

- 页面：https://www.naaim.org/programs/naaim-exposure-index/
- 程序从页面自动发现最新 `USE_Data-since-Inception_*.xlsx`，读取日期与 NAAIM Number。
- 周频。NAAIM 已公告从 2026-08-01 起转为订阅访问；届时通过 Secret `NAAIM_XLSX_URL` 提供订阅下载地址。
- 授权备用源：https://en.macromicro.me/charts/46198/naaim-exposure-index
- MacroMicro公开图表页不作为爬虫源。只有在订阅账户提供API访问权限后，程序才通过`MACROMICRO_NAAIM_API_URL`和`MACROMICRO_API_KEY`调用其官方Bearer Token API。
- 免费手动源：`data/naaim_manual.json`。通过GitHub Actions的“手动更新 NAAIM 数据”填写最新值和美东调查日期，程序保留历史并自动计算最近4期平均值。
- 多个来源同时可用时，以数据日期最新者为准。NAAIM通常于美东周四发布，对应北京时间周五；周五推送会在手动记录尚未更新时提醒。

## CFTC Asset Manager/Institutional Positioning（参考）

- 官方开放数据：https://publicreporting.cftc.gov/resource/gpe5-46if.json
- 数据集：Traders in Financial Futures（TFF）Futures Only，E-mini S&P 500，CFTC合约代码`13874A`。
- 净仓位占比 = Asset Manager/Institutional多仓占总持仓比例 − 空仓占总持仓比例。
- 同时展示最新净仓位、最近4期净仓位平均值，以及在最近160期（约3年）中的百分位。
- 该指标与NAAIM定义不同，权重固定为0%，不参与综合风险偏好或五项加权决策。

## VIX 与 QQQ RSI

- 行情：https://query1.finance.yahoo.com/v8/finance/chart/
- VIX 使用 `^VIX` 最新有效收盘值。
- QQQ RSI 使用调整收盘价，按 Wilder 平滑方法计算，默认14日。

所有网页结构都可能变化。任一采集器失败时，程序会在消息中标明缺失，不会把演示值当成实时值。
