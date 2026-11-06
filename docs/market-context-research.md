# 市场环境模块：取舍与数据口径

现有五项自有指标以情绪、估值和短线超卖为主；第三方12维度已含VIX、名义利率、均线和恐惧贪婪。因此本次选择补充市场参与度、实际利率和金融压力，保持自有权重和邮件触发规则不变。

| 参考网站 | 值得借鉴 | 本站采用方式 |
| --- | --- | --- |
| [Koyfin Market Dashboards](https://www.koyfin.com/features/market-dashboards/) | 将权益、利率和宏观条件放在同一观察界面 | 增加独立的市场环境模块，各数据保留自己的观测日期 |
| [Finviz Groups](https://finviz.com/groups?g=sector&v=140) | 多周期横向比较，而不是只看当日涨跌 | 等权ETF/市值权重ETF比率提供20与60个共同交易日切换 |
| [StockCharts Price Relative](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/price-relative-relative-strength) | 用价格比率区分相对强弱 | 计算QQQE/QQQ与RSP/SPY的复权价格比率变化，图表起点归一为100 |
| [FRED DFII10](https://fred.stlouisfed.org/series/DFII10) | 官方、注明频率和来源的实际利率序列 | 显示10年期TIPS实际收益率、20个有效观测日变化（bp）和近3年内样本百分位 |
| [FRED STLFSI4](https://fred.stlouisfed.org/series/STLFSI4) | 综合金融压力而不只看股票波动 | 显示周度压力指数、4周变化及近3年内样本位置；0为长期平均，不能与样本百分位混淆 |

## 没有采用的方案

- 未重复添加另一个恐惧贪婪总分，避免与已有第三方模块重复。
- 没有把等权相对表现称为“上涨股票比例”或真实市场广度；它还受行业结构、再平衡和ETF费用影响。
- [ICE BofA高收益利差](https://fred.stlouisfed.org/series/BAMLH0A0HYM2)的官方页面要求事先许可才能向第三方分发，因此未抓取或公开再发布该系列。STLFSI4允许按要求注明来源引用，DFII10标记为公共领域、建议注明出处；本站都提供官方链接与署名。
- 未直接拷贝其他网站的评分、付费历史数据或设计素材；参考其信息组织方法，数据直接来自公开行情及官方FRED序列。

## 实现约束

行情使用共同日期的复权价格，排除当天未完成日线；相对表现按价格比率变化计算，而非两只ETF收益率相减。真实利率变化以bp表示，1bp=0.01个百分点；周度变化按28天前最近有效观测对齐。

数据脚本随现有GitHub自动更新。某个来源失败时保留之前的观测日期和成功读取时间，明确标记保留样本，不将缺失当作零，也不阻断自有核心指标。FRED历史数据可能修订，不将当前历史序列伪装成当时可交易的回测数据。
