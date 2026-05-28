# ERP Execution Config Guide

配置文件位置: [erp_execution_config.json](D:/CC/index-compare-analysis/orchestrator/erp_execution_config.json)

这份配置控制的是执行层，不负责改 ERP 原始信号，也不负责改 `CSI300 relative` 的比价计算。
它只决定一件事:

- 已经有了 `ERP + relative + 300价值/成长` 信号之后，怎么把它们映射成实际目标权重

## 总体结构

配置分成 6 块:

1. `percentile_thresholds`
2. `aggressive_weights`
3. `recommendation_multipliers`
4. `value_style_tilt`
5. `growth_style_tilt`
6. `holding_alias_map / ignored_erp_holdings`

## 1. Percentile Thresholds

```json
"percentile_thresholds": {
  "low": 40.0,
  "high": 60.0
}
```

用途:
- 定义 ERP 历史分位的低位区和高位区

当前逻辑:
- `<= 40` 视为低位区
- `>= 60` 视为高位区
- 中间是过渡区

改大/改小的影响:
- `low` 调高: 更容易进入低位区，整体会更常落在低进攻权重
- `low` 调低: 只有更极端的低分位才会触发低进攻权重
- `high` 调低: 更容易进入高位区，整体会更常落在高进攻权重
- `high` 调高: 只有更极端的高分位才会触发高进攻权重

适合什么时候改:
- 觉得 ERP 太敏感，就把 `low/high` 拉开
- 觉得 ERP 太迟钝，就把 `low/high` 收窄

## 2. Aggressive Weights

```json
"aggressive_weights": {
  "low": 0.35,
  "neutral": 0.5,
  "high": 0.65
}
```

用途:
- 定义 ERP 分位映射成“进攻侧总权重”的三个锚点

当前逻辑:
- 低位区: 进攻侧 35%
- 中性区中心: 进攻侧 50%
- 高位区: 进攻侧 65%

改大/改小的影响:
- `low` 调大: 即使 ERP 偏弱，也不会太防守
- `low` 调小: ERP 一旦偏弱，就更快缩进攻
- `high` 调大: ERP 偏强时会更激进
- `high` 调小: ERP 偏强时也保持克制
- `neutral` 调大或调小: 改的是中枢，不是极端

优先建议:
- 如果你只是想整体更稳或更激进，先改这里
- 不要先动后面的复杂乘数

## 3. Recommendation Multipliers

```json
"recommendation_multipliers": {
  "强烈超配": 1.3,
  "超配": 1.15,
  "标配": 1.0,
  "低配": 0.85,
  "强烈低配": 0.7
}
```

用途:
- 把 `relative` 输出的文字建议映射成权重乘数

当前逻辑:
- `强烈超配` 会放大该桶权重
- `强烈低配` 会压缩该桶权重

改大/改小的影响:
- 提高 `强烈超配` / `超配`: 相对信号会更有主导权
- 降低 `低配` / `强烈低配`: 被看空的桶会被更重地压制
- 如果把所有值都拉近 `1.0`: relative 信号作用会减弱

优先建议:
- 觉得 `500/1000/创业板/50` 的建议对结果影响不够大，就改这里

## 4. Value Style Tilt

```json
"value_style_tilt": {
  "强烈超配": 1.3,
  "超配": 1.15,
  "标配": 1.0,
  "低配": 0.9,
  "强烈低配": 0.8
}
```

用途:
- 把 `300价值 / 300成长` 信号映射成“防守侧价值偏置”

当前逻辑:
- `300价值` 越强，越偏向 `上证50`
- `300价值` 越弱，越偏向 `沪深300`

改大/改小的影响:
- 提高 `强烈超配` / `超配`: 价值风格一旦走强，就更大幅度偏向 `上证50`
- 降低 `低配` / `强烈低配`: 价值风格弱时，会更明显回到 `沪深300`

优先建议:
- 如果你把 `上证50 + 红利` 视作更纯粹的价值代理，这块可以改得更强一点

## 5. Growth Style Tilt

```json
"growth_style_tilt": {
  "强烈超配": {
    "cyb": 0.85,
    "zz500": 1.1,
    "zz1000": 1.1,
    "sh50_bonus": 1.15
  }
}
```

用途:
- 把 `300价值 / 300成长` 信号进一步传播到进攻侧和 `上证50`

理解方式:
- 这里不是 ERP 主信号
- 这是二级风格微调

当前逻辑:
- 当 `300价值` 强时:
  - `cyb` 权重被压一点
  - `zz500 / zz1000` 被抬一点
  - `sh50` 再加一点 bonus
- 当 `300价值` 弱时:
  - 反过来，更容忍成长风格

各字段含义:
- `cyb`: 创业板乘数
- `zz500`: 中证500乘数
- `zz1000`: 中证1000乘数
- `sh50_bonus`: 防守侧里给上证50的额外加成

改大/改小的影响:
- `cyb` 越小: 对创业板压制越强
- `zz500/zz1000` 越大: 价值偏强时越偏向中小盘里的非极致成长部分
- `sh50_bonus` 越大: 价值偏强时更容易把资金回流到大盘价值

优先建议:
- 如果你觉得创业板还是太重，就先改 `cyb`
- 如果你觉得价值风格应该更多流向 50 而不是 500/1000，就先改 `sh50_bonus`

## 6. Holding Alias Map

```json
"holding_alias_map": {
  "沪深300ETF": "hs300",
  "红利ETF": "sh50"
}
```

用途:
- 把资产配置表里的真实持仓名称，映射到执行层桶

当前桶只有 5 个:
- `hs300`
- `sh50`
- `cyb`
- `zz500`
- `zz1000`

改法:
- 新增某个 ETF 要纳入现有桶，就在这里补一行映射

例子:
```json
"某某500ETF": "zz500"
```

## 7. Ignored ERP Holdings

```json
"ignored_erp_holdings": [
  "科创50ETF",
  "恒生消费ETF",
  "十年期国债ETF"
]
```

用途:
- 明确这些虽然在 `β|α` 里被标成 `ERP`，但执行层先不管

什么时候改:
- 你确认某个标的不该进入 ERP 执行层时，放这里
- 你想重新纳入某个标的时，从这里删掉，再去 `holding_alias_map` 给它分桶

## 调参顺序建议

如果以后要调策略，建议按这个顺序来:

1. 先改 `aggressive_weights`
- 这是总进攻/防守框架

2. 再改 `recommendation_multipliers`
- 这是 relative 信号强弱

3. 再改 `value_style_tilt`
- 这是防守侧价值偏置

4. 最后改 `growth_style_tilt`
- 这是最细的风格微调

## 当前版本的直觉

这套配置现在表达的是:

- ERP 决定大方向
- relative 决定主要风格切换
- `300价值/成长` 只做二级微调
- 尽量避免某一个信号单独把组合掰得太狠

如果你后面想把它改得更“果断”，最有效的两个入口通常是:

- 提高 `aggressive_weights.high`
- 拉开 `recommendation_multipliers`
