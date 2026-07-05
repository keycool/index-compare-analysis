# ERP 策略扩展方案 v3.0

> 从现有 5-bucket 框架扩展为覆盖 A 股 + 港股全标的的统一执行系统。
> 设计原则：第一性原理驱动，层次清晰，边界明确，不留盲区。

---

## 〇、系统全景：从信号到执行的完整链路

### 现状数据流

```
                        Tushare API
                            │
                   fetch_data.py
                            │
                   raw_data.csv (11指数日线, 2007~)
                            │
                   calculate.py
                   ┌────────┼────────┐
                   ▼        ▼        ▼
           processed_data.csv   analysis_results.json   overlap_snapshot.json
                   │                 │
              main.py           analyze.py
           build_export_          │
           dataframe()      conclusions.json
                   │            (7组比价结论)
         ┌────────┼────────┐
         ▼        ▼        ▼
     Excel     relative_   飞书多维表格
   (25+字段)  signal.json  (Relative表)
         │                      │
         │        ┌─────────────┘
         │        ▼
         │   飞书 Relative 表
         │   (500建议, 1000建议, 创业板建议, 50建议, 300价值建议)
         │        │
         └───────┬┘
                 ▼
         erp_execution_cloud.py
         ┌───────┼────────┐
         ▼       ▼        ▼
     ERP表   Relative表   Asset表
         │       │          │
         ▼       ▼          ▼
    erp_snapshot  relative_   current_
                  snapshot    holdings
         │         │            │
         └─────────┼────────────┘
                   ▼
           build_target_weights()
                   │
           build_rebalance_plan()
                   │
         ┌─────────┼──────────┐
         ▼         ▼          ▼
   execution_plan.json    daily_summary.md    飞书推送
```

### 现有瓶颈

| 瓶颈 | 说明 |
|---|---|
| KC50 在 conclusions.json 中存在，但 Excel 不导出推荐列 | 飞书 Relative 表无 `科创50建议`，执行层读不到 |
| HKTECH 同上 | 无 `恒生科技建议` |
| VAL300 的结论仅作为 style overlay 乘数 | 不产生实际仓位 |
| GRO300 从 conclusions.json 中完全缺失 | 只在 calculate.py 中作为分母参与，analyze.py 不输出 |
| HSI ERP 仅在 generate_report.py 中用于图表展示 | 执行层无法访问 |
| resolve_holding_bucket() 硬编码 `"科创50" → __IGNORE__` | 无法持有科创50 |

---

## 一、第一性原理：策略框架的 5 个基本公理

### 公理 1：所有标的平等

比价对的两端都是可交易指数。比价只是一个跷跷板信号——分位低买分子，分位高买分母。没有任何指数"仅作分母"。

### 公理 2：ERP 决定仓位敞口

沪深300 ERP 分位决定 A 股池的进攻/防守比例。恒生 ERP 分位决定港股池的进攻/防守比例。ERP 低 → 股票相对债券偏贵 → 降低进攻。ERP 高 → 股票便宜 → 提高进攻。

### 公理 3：比价信号决定池内分布

每个池内部，各 bucket 的基础权重 × 比价建议乘数 → 归一化 → 受个顶约束。进攻 bucket 多配便宜的，少配贵的。防守 bucket 同理。

### 公理 4：分层风控不可绕过

每个 bucket 独立受三组风控约束：强制退出（分位打到极值）→ 重入闸门（分位回落 + 持仓清零后才可重新进入）→ 轨迹覆盖（短期动量修正）。强制退出优先级最高。

### 公理 5：市场间独立、顶层统一分配

A 股池和港股池内部各自独立运行（各自的 ERP 驱动），顶层由一个跨市场分配参数决定资金在两个池之间的划分。

---

## 二、顶层架构：三层决策树

```
                           总资产 100%
                                │
              ┌─────────────────┼─────────────────┐
              ▼                                    ▼
        A 股池 (X%)                          港股池 (100-X%)
        由 HS300 ERP 驱动                     由 HSI ERP 驱动
              │                                    │
    ┌─────────┴─────────┐              ┌───────────┴───────────┐
    ▼                   ▼              ▼                       ▼
  A股防守            A股进攻        港股防守                 港股进攻
 (β 底仓 + α)       (比价驱动)     (恒生指数)             (恒生科技)
    │                   │              │                       │
┌───┼───┐       ┌───┼───┐          │                       │
▼   ▼   ▼       ▼   ▼   ▼          ▼                       ▼
HS  SH  VAL/   CYB ZZ5 ZZ1         HSI                    HKTECH
300 50  GRO    创  00  00
     300       业
               板
              KC50
```

### 层 0：跨市场分配

```
港股池上限 = configurable (默认 20%)

港股实际分配 = min(港股池上限, 港股 ERP 分位驱动的比例)
  - HSI ERP ≤ 30%: 港股 = 0 (港股太贵, 不配)
  - HSI ERP 30-50%: 线性插值 0 → 港股上限
  - HSI ERP ≥ 50%: 港股 = 港股池上限

A 股池 = 100% - 港股实际分配
```

**设计理由**：港股作为卫星池，恒生 ERP 必须足够有吸引力才配。当恒生 ERP 低时（港股贵），资金留在 A 股。

### 层 1：单池 ERP → 进攻/防守比例

两个池各自独立运行相同的分段线性逻辑：

```
池内进攻仓位 = piecewise_linear_weight(
    本池 ERP 分位,
    low_threshold=40%,      # ERP ≤ 40% → 最防守
    high_threshold=60%,     # ERP ≥ 60% → 最进攻
    low_weight=35%,
    neutral_weight=50%,
    high_weight=65%
)
池内防守仓位 = 1 - 进攻仓位
```

| ERP 分位 | 含义 | 进攻 | 防守 |
|---|---|---|---|
| ≤ 40% | 股权偏贵 | 35% | 65% |
| 40-60% | 中性 | 35→50% | 65→50% |
| ≥ 60% | 股权便宜 | 50→65% | 50→35% |

### 层 2：防守端内部分配

#### A 股防守端（占 A 股池的 defensive_weight%）

```
防守端 Alpha 总预算 = alpha_budget × A股池防守仓位

alpha_budget = piecewise_linear_weight(
    HS300 ERP 分位,
    40%, 60%,
    20%, 28%, 35%        # ERP越高, 防守内Alpha越多
)
alpha_budget = cap(45%)
```

**Sub-bucket 1: 风格对 (VAL300 / GRO300)**

```
风格对预算 = alpha_budget × 风格对占比 (默认 30%)

VAL300 仓位 = 风格对预算 × val300_weight
GRO300 仓位 = 风格对预算 × gro300_weight

val300_weight = f(VAL300/GRO300 比价分位):
  分位 ≤ 30%: val300 占 70%, gro300 占 30%  (价值便宜 → 买价值)
  分位 30-70%: 各 50%
  分位 ≥ 70%: val300 占 30%, gro300 占 70%  (成长便宜 → 买成长)
```

> 取代现有的 style overlay 机制。原来的 value_tilt / growth_tilt 乘数不再需要——300价值/300成长 已经通过真实仓位表达。

**Sub-bucket 2: 防守 Alpha (SH50/红利)**

```
SH50 基础 = alpha_budget × (1 - 风格对占比) × A股池防守仓位
SH50 最终 = SH50基础 × rec_multiplier(SH50建议)
SH50 最终 = cap(SH50最终, SH50个顶 = 18%)
```

**Sub-bucket 3: 核心底仓 (HS300)**

```
HS300 仓位 = A股防守仓位的剩余 = A股防守 - SH50 - VAL300 - GRO300
HS300 仓位 = max(0, 上述值)
```

#### 港股防守端（占港股池的 defensive_weight%）

```
港股防守 = HSI 仓位 = 港股防守仓位 (100% of HK defensive)
```

> 港股防守端只有一个标的：恒生指数本身。它既是锚，也是仓位。

### 层 3：进攻端内部分配

#### A 股进攻端（占 A 股池的 aggressive_weight%）

```
进攻端 Alpha 预算 = alpha_budget × A股池进攻仓位

四标的得分体系:
  cyb_score    = base_0.30 × rec_multiplier(创业板建议)
  zz500_score  = base_0.40 × rec_multiplier(500建议)
  zz1000_score = base_0.30 × rec_multiplier(1000建议)
  kc50_score   = base_0.25 × rec_multiplier(科创50建议)

归一化 → 四标的权重
各标的权重 = 进攻端Alpha预算 × 归一化权重
各标的权重 = cap(标的权重, 标的个顶)
```

| Bucket | 基础权重 | 个顶 | 与创业板的关系 |
|---|---|---|---|
| 创业板 (cyb) | 0.30 | 8% | — |
| 中证500 (zz500) | 0.40 | 12% | — |
| 中证1000 (zz1000) | 0.30 | 8% | — |
| 科创50 (kc50) | 0.25 | 6% | 同属科技成长, elastic 更高, cap 更紧 |

**KC50 的特殊处理**：

- KC50 = SH50 / KC50，其中 SH50 做分子。分位低 → 分子(SH50)便宜 → 买 SH50，不是买 KC50。分位高 → 分母(KC50)便宜 → 买 KC50。
- 所以 KC50 bucket 只在 **比价建议为「低配」或「强烈低配」时才有仓位**（即分位高 → 分母便宜）。
- 建议为「超配」或「强烈超配」时 → KC50 仓位 = 0（此时应该买 SH50，但 SH50 已由防守端的 SH50 bucket 覆盖）。
- **实现方式**：rec_multiplier 对 KC50 使用反向映射——「强烈超配」→ 0，「强烈低配」→ 1.30。

> 这就是跷跷板逻辑的直接体现：比价高（分子贵）→ 买分母（KC50）；比价低（分子便宜）→ 买分子（SH50），后者已由防守端覆盖。

#### 港股进攻端（占港股池的 aggressive_weight%）

```
港股进攻 = HKTECH 仓位 = 港股进攻仓位 (100% of HK aggressive)
```

> 港股进攻端只有一个标的：恒生科技。比价建议来自恒生科技/恒生指数。

---

## 四、风控层（所有 bucket 统一适用）

### 4.1 强制退出（优先级最高）

| Bucket | 退出分位 | 逻辑 |
|---|---|---|
| sh50 | 95% | SH50/创业板 比价分位达 95% → 上证50 极贵 → 清仓 |
| zz500 | 95% | 500/300 比价分位达 95% → 中证500 极贵 → 清仓 |
| zz1000 | 95% | 1000/300 比价分位达 95% → 中证1000 极贵 → 清仓 |
| cyb | 95% | 创业板/300 比价分位达 95% → 创业板 极贵 → 清仓 |
| kc50 | 95% | KC50/SH50 比价分位达 95% → KC50 极贵 → 清仓 |
| hstech | 95% | 恒生科技/恒生 比价分位达 95% → 恒生科技 极贵 → 清仓 |
| val300 | 95% | 300价值/300成长 比价分位达 95% → 300价值 极贵 → 清仓（全配成长） |
| gro300 | 5% | 300价值/300成长 比价分位 ≤ 5% → 300成长 极贵 → 清仓（全配价值） |

> VAL300/GRO300 构成对称跷跷板——两者强制退出阈值互补。

### 4.2 重入闸门

强制退出后，仓位被清零。只有当比价分位回落至重入阈值以下 + 当前持仓 ≤ min_amount（默认 1000 元），才允许重新进入。

| Bucket | 重入阈值 | 理由 |
|---|---|---|
| zz500 | 40% | 回到低估区域才允许回补 |
| zz1000 | 35% | 小盘弹性更大 → 更严格 |
| cyb | 30% | 高弹性 → 最严格 |
| kc50 | 25% | 比创业板更极端 |
| hstech | 30% | 参考创业板 |
| val300 | 50% | 风格轮动更快 → 中性就可回补 |
| gro300 | 50% | 同上 |

### 4.3 轨迹叠加（Trajectory Overlay）

基于最近 5 日比价变化率 + 30 日偏离度的短期动量修正。所有进攻 bucket + SH50 + VAL300/GRO300 均适用。HS300 和 HSI（核心底仓）不适用——它们是残差兜底，不做动量修正。

| 状态 | 条件 | 乘数 | 逻辑 |
|---|---|---|---|
| 🔥 Hot | 偏离 > 4% 且/或 5日涨 > 3% | ×0.60 | 追高风险 |
| 🌤 Warm | 偏离 > 2% 且/或 5日涨 > 1% | ×0.80 | 偏热减仓 |
| 🩹 强修复 | 偏离 < -3% 且 5日不跌 | ×1.15 | 超跌反弹 |
| 🩹 轻修复 | 偏离 < -1% 且 5日不跌 | ×1.05 | 轻度修复 |
| 📉 Falling | 偏离 < 0 且 5日跌 | ×0.85 | 下跌中继 |

---

## 五、配置结构

### 5.1 erp_execution_config.json 扩展

```jsonc
{
  // === 跨市场 ===
  "cross_market": {
    "hk_pool_cap": 0.20,                    // 港股池上限 20%
    "hk_min_erp_percentile": 30,            // HSI ERP ≤ 30%时不配港股
    "hk_full_erp_percentile": 50            // HSI ERP ≥ 50%时满配港股上限
  },

  // === ERP 阈值 (A股用, 港股复用) ===
  "percentile_thresholds": {
    "low": 40.0,
    "high": 60.0
  },
  "aggressive_weights": {
    "low": 0.35,
    "neutral": 0.50,
    "high": 0.65
  },

  // === Alpha 预算 ===
  "alpha_budget_weights": {
    "low": 0.20,
    "neutral": 0.28,
    "high": 0.35
  },

  // === 防守端: 风格对 ===
  "style_pair": {
    "budget_ratio": 0.30,                   // 风格对占 Alpha 预算的比例
    "split": {
      "value_cheap_weight": 0.70,           // 价值便宜 → VAL300占70%
      "neutral_weight": 0.50,               // 中性 → 各50%
      "growth_cheap_weight": 0.70           // 成长便宜 → GRO300占70%
    },
    "percentile_thresholds": {
      "low": 30,
      "high": 70
    }
  },

  // === 比价建议乘数 ===
  "recommendation_multipliers": {
    "强烈超配": 1.30,
    "超配": 1.15,
    "标配": 1.00,
    "低配": 0.85,
    "强烈低配": 0.70
  },

  // === 进攻端基础权重 ===
  "alpha_base_weights": {
    "sh50": 1.00,
    "zz500": 0.40,
    "zz1000": 0.30,
    "cyb": 0.30,
    "kc50": 0.25
  },

  // === 个顶 ===
  "alpha_bucket_caps": {
    "sh50": 0.18,
    "val300": 0.10,
    "gro300": 0.10,
    "zz500": 0.12,
    "zz1000": 0.08,
    "cyb": 0.08,
    "kc50": 0.06,
    "hstech": 0.08
  },

  // === 强制退出 ===
  "forced_exit_percentiles": {
    "sh50": 95.0,
    "zz500": 95.0,
    "zz1000": 95.0,
    "cyb": 95.0,
    "kc50": 95.0,
    "hstech": 95.0,
    "val300": 95.0,
    "gro300": 5.0                       // 注意: GRO300的"贵"对应的是低分位
  },

  // === 重入闸门 ===
  "aggressive_reentry_percentiles": {
    "zz500": 40.0,
    "zz1000": 35.0,
    "cyb": 30.0,
    "kc50": 25.0,
    "hstech": 30.0,
    "val300": 50.0,
    "gro300": 50.0
  },
  "reentry_min_current_amount": 1000.0,

  // === 轨迹叠加 ===
  "trajectory_overlay": { /* 不变, 同现有 */ },

  // === 港股 ERP 参数 ===
  "hk_erp": {
    "percentile_thresholds": { "low": 40.0, "high": 60.0 },
    "aggressive_weights": { "low": 0.30, "neutral": 0.45, "high": 0.60 }
    // 港股进攻仓位比 A 股保守 5 个百分点
  },

  // === 持仓映射 ===
  "holding_alias_map": {
    // ... 现有映射 ...
    "科创50ETF": "kc50",
    "科创50": "kc50",
    "300价值ETF": "val300",
    "300价值": "val300",
    "300成长ETF": "gro300",
    "300成长": "gro300",
    "恒生ETF": "hsi",
    "恒生指数ETF": "hsi",
    "恒生科技ETF": "hstech",
    "恒生科技": "hstech"
  },

  // 从 ignored 中移除科创50
  "ignored_erp_holdings": [
    "恒生消费ETF",
    "十年期国债ETF"
  ],

  // === 新增 bucket 元数据 ===
  "bucket_metadata": {
    "hs300":  { "label": "沪深300",       "sleeve": "defensive",  "pool": "ashare" },
    "sh50":   { "label": "上证50/红利",   "sleeve": "defensive",  "pool": "ashare" },
    "val300": { "label": "300价值",       "sleeve": "defensive",  "pool": "ashare" },
    "gro300": { "label": "300成长",       "sleeve": "defensive",  "pool": "ashare" },
    "cyb":    { "label": "创业板",        "sleeve": "aggressive", "pool": "ashare" },
    "zz500":  { "label": "中证500",       "sleeve": "aggressive", "pool": "ashare" },
    "zz1000": { "label": "中证1000",      "sleeve": "aggressive", "pool": "ashare" },
    "kc50":   { "label": "科创50",        "sleeve": "aggressive", "pool": "ashare" },
    "hsi":    { "label": "恒生指数",      "sleeve": "defensive",  "pool": "hkshare" },
    "hstech": { "label": "恒生科技",      "sleeve": "aggressive", "pool": "hkshare" }
  }
}
```

### 5.2 数据管道变更

#### 5.2.1 main.py: `build_export_dataframe()` 扩展

在 Excel 导出中新增列：
- `科创50建议`（从 conclusions.json 中取 KC50.recommendation.action）
- `恒生科技建议`（从 conclusions.json 中取 HKTECH.recommendation.action）
- `300成长分位`（新增计算，取 100 - VAL300_percentile 或独立计算）
- `300成长建议`（反向于 VAL300 建议）

飞书 Relative 表同步新增这些字段。

#### 5.2.2 erp_execution_cloud.py: HSI ERP 数据源

新增 `compute_hsi_erp_snapshot()` 函数，从飞书表格读取恒生 ERP 历史：

**方案 A（推荐）**：新增飞书表格 `HSI ERP 表`，由 master scheduler 在运行 report generation 后自动填充。

```
ERP 表     (HS300)  — 已有, 外部 ERP 项目维护
Relative 表         — 已有, CSI300 Relative 项目维护
Asset 表            — 已有, 手工维护持仓
HSI ERP 表          — 新增, CSI300 Relative 项目 report generation 自动填充
```

**方案 B（备选）**：如果不想新开表，在 `generate_report.py` 的 `build_hsi_erp_history()` 完成后，将 HSI ERP 快照写入 `shared/hsi_erp_signal.json`，执行层从 shared 目录读取。

> 推荐方案 A，与其他两个 ERP 表保持一致。方案 B 要求 GitHub Actions 有文件系统读写权限且 artifact 传递。

#### 5.2.3 compute_relative_snapshot() 扩展

读取新增字段：
```
"recommendations": {
    "zz500": ..., "zz1000": ..., "cyb": ..., "sh50": ...,
    "kc50": ...,      // 新增
    "hstech": ...,     // 新增
    "val300": ...,     // 已有, 从300价值建议取
    "gro300": ...      // 新增, 反向于300价值建议
}
```

#### 5.2.4 resolve_holding_bucket() 扩展

从 ignored 中移除 `科创50`。新增 `kc50`、`val300`、`gro300`、`hsi`、`hstech` 的匹配规则。

#### 5.2.5 build_target_weights() 重构

当前函数约 130 行，扩展后预计 250+ 行。建议拆分为：

```
build_cross_market_allocation()   → A股池%, 港股池%
build_ashare_targets()            → A股 10 bucket 目标权重
build_hkshare_targets()           → 港股 2 bucket 目标权重
apply_risk_controls()             → 强制退出 + 重入闸门 + 轨迹叠加
compute_residual_core()           → HS300 / HSI 残差计算
```

---

## 六、以 100 万为例的完整数值推演

假设当前信号状态：

### 输入信号

| 信号 | 值 |
|---|---|
| HS300 ERP 分位 | 55%（中性偏高） |
| HSI ERP 分位 | 62%（已触发满配） |
| 500建议 | 超配 |
| 1000建议 | 标配 |
| 创业板建议 | 低配 |
| 50建议 | 超配 |
| 科创50建议 | 强烈低配（→ 反向 = KC50 应买入） |
| 300价值建议 | 低估（→ VAL300 便宜） |
| 恒生科技建议 | 强烈超配 |

### Step 0: 跨市场分配

```
港股池上限 = 20%
HSI ERP = 62% ≥ 50% → 满配
港股 = 20%
A股 = 80%
```

### Step 1: A 股池 (80万)

```
HS300 ERP = 55% → 进攻 = piecewise(55, 40, 60, 0.35, 0.50, 0.65)

midpoint = 50%
55% > 50% → 在 50%-60% 段
ratio = (55-50)/(60-50) = 0.5
进攻 = 0.50 + (0.65-0.50) × 0.5 = 0.575

A股进攻 = 80万 × 57.5% = 46万
A股防守 = 80万 × 42.5% = 34万

alpha_budget = piecewise(55, 40, 60, 0.20, 0.28, 0.35)
= 0.28 + (0.35-0.28)×0.5 = 0.315, cap 45% → 31.5%
```

### Step 2: A 股防守端 (34万)

```
防守 Alpha 总预算 = 34万 × 31.5% = 10.71万

风格对 (30% of Alpha) = 10.71万 × 30% = 3.21万
  VAL300: 分位 27.4% ≤ 30% → 价值便宜, VAL300占70%
    VAL300 = 3.21万 × 70% = 2.25万
    GRO300 = 3.21万 × 30% = 0.96万

SH50 (70% of Alpha) = 10.71万 × 70% = 7.50万
  × rec_multiplier(超配) = 7.50万 × 1.15 = 8.62万
  cap 18% of 34万 = 6.12万 → 取 6.12万

HS300 = 34万 - 2.25万 - 0.96万 - 6.12万 = 24.67万
```

### Step 3: A 股进攻端 (46万)

```
进攻 Alpha 预算 = 46万 × 31.5% = 14.49万

scores:
  cyb    = 0.30 × 0.85(低配)    = 0.255
  zz500  = 0.40 × 1.15(超配)    = 0.460
  zz1000 = 0.30 × 1.00(标配)    = 0.300
  kc50   = 0.25 × 1.30(强烈低配→反向买入) = 0.325
  total  = 1.340

weights (归一化):
  cyb    = 0.255/1.340 = 19.0%
  zz500  = 0.460/1.340 = 34.3%
  zz1000 = 0.300/1.340 = 22.4%
  kc50   = 0.325/1.340 = 24.3%

amounts (14.49万 × weight):
  cyb    = 2.75万 → cap 8% × 80万 = 6.4万 → OK
  zz500  = 4.97万 → cap 12% × 80万 = 9.6万 → OK
  zz1000 = 3.25万 → cap 8% × 80万 = 6.4万 → OK
  kc50   = 3.52万 → cap 6% × 80万 = 4.8万 → OK
```

### Step 4: 港股池 (20万)

```
HSI ERP = 62% ≥ 60% → 进攻 = 0.60 (high weight)

港股进攻 = 20万 × 60% = 12万 → HKTECH
港股防守 = 20万 × 40% = 8万  → HSI
```

### Step 5: 汇总

| Pool | Bucket | 金额 | 占总资产 |
|---|---|---|---|
| A股防守 | 沪深300 | 24.67万 | 24.7% |
| | 上证50/红利 | 6.12万 | 6.1% |
| | 300价值 | 2.25万 | 2.3% |
| | 300成长 | 0.96万 | 1.0% |
| A股进攻 | 中证500 | 4.97万 | 5.0% |
| | 中证1000 | 3.25万 | 3.2% |
| | 创业板 | 2.75万 | 2.7% |
| | 科创50 | 3.52万 | 3.5% |
| 港股防守 | 恒生指数 | 8.00万 | 8.0% |
| 港股进攻 | 恒生科技 | 12.00万 | 12.0% |
| **已分配** | | **68.49万** | **68.5%** |

> 剩余 31.51 万来自 A 股进攻端未被 Alpha 预算覆盖的部分（46万 - 14.49万），这部分逻辑上是跟随 HS300 底仓的被动大盘敞口。如果需要，可以设一个"剩余资金"bucket，或者并入 HS300。

---

## 七、实施路径

### Phase 1: 数据管道补齐（无风险，不改执行层）

| 步骤 | 改动文件 | 内容 |
|---|---|---|
| 1.1 | `main.py` `build_export_dataframe()` | 新增 `科创50建议`、`恒生科技建议`、`300成长分位`、`300成长建议` 列 |
| 1.2 | `main.py` `export_shared_signal()` | 同步新增字段到 shared signal JSON |
| 1.3 | `config.json` | GRO300 role 从 `reference` 改为 `target`，新增 `domain` 字段 |
| 1.4 | 飞书 Relative 表 | 新增对应列 |

### Phase 2: 港股 ERP 数据源

| 步骤 | 改动文件 | 内容 |
|---|---|---|
| 2.1 | 飞书新建 HSI ERP 表 | 字段: 日期, 恒生ERP, HSI PE, 盈利收益率, 10Y美债 |
| 2.2 | `generate_report.py` | `build_hsi_erp_history()` 完成后写入飞书 HSI ERP 表 |
| 2.3 | master scheduler workflow | 新增步骤: 调用 report generation → 自动填充 HSI ERP 表 |

### Phase 3: 执行层扩展

| 步骤 | 改动文件 | 内容 |
|---|---|---|
| 3.1 | `erp_execution_config.json` | 按上述 schema 扩展 |
| 3.2 | `erp_execution_cloud.py` | 新增跨市场分配、HSI ERP 读取、KC50/HKTECH/VAL300/GRO300 bucket |
| 3.3 | `erp_execution.py` (本地版) | 同步扩展 |
| 3.4 | `render_erp_daily_summary_v4.py` | 新增 bucket 展示 |

### Phase 4: 文档 & 测试

| 步骤 | 内容 |
|---|---|
| 4.1 | 更新 README / SKILL.md 中的标的角色表 |
| 4.2 | 用历史数据跑一次完整推演，验证无 NaN/除零/权重爆炸 |
| 4.3 | Git tag v3.0.0 |

---

## 八、盲区与边界声明

### 8.1 已知不覆盖的场景

| 盲区 | 说明 | 处理方式 |
|---|---|---|
| **多信号冲突** | 创业板同时在 cyb/HS300 和 SH50/cyb 两组比价对中，信号可能打架 | 各自独立输出，不综合。文档注明 |
| **HKD/CNY 汇率** | 港股仓位以 HKD 计价但总资产以 CNY 计 | 当前忽略汇率波动。文档注明 |
| **恒生科技历史短** | HKTECH 始于 2020 年，分位计算样本有限 | 使用 expanding percentile，从有数据第一天开始计算 |
| **KC50 NaN MA** | 实际数据中 KC50 的 MA30 为 NaN（可能数据不足 30 天） | trajectory overlay 对 NaN 返回 neutral（×1.0） |
| **HSI ERP 数据频率** | PE 是月度，US10Y 是日度，存在时点错配 | 取月末最后一日对齐 |
| **总资产 ≠ 100%** | 由于 rounding / cap 截断，sum(target_weights) 可能 < 1.0 | 残差全部归入 HS300（A 股）+ HSI（港股） |
| **风格对同时退出** | VAL300 和 GRO300 同时触发强制退出的概率极低（需要比价分位同时 ≥ 95% 且 ≤ 5%） | 数学上不可能，但代码防御: 两者同时触发 → 风格对预算全归零 |

### 8.2 有意不纳入的标的

| 标的 | 理由 |
|---|---|
| 上证综指 | 不可直接交易, 仅作参考 |
| 科创50/上证50 作为独立 bucket | 已在 KC50 bucket 中通过跷跷板逻辑覆盖，不再单独拆分 |
| 创业板作为分母的 bucket | SH50/创业板比价已覆盖 |

---

## 九、从旧版迁移的 Breaking Changes

| 旧行为 | 新行为 | 影响 |
|---|---|---|
| style overlay (value_tilt / growth_tilt 乘数) | 移除, 由 VAL300/GRO300 真实仓位替代 | `erp_execution_config.json` 中相关字段废弃 |
| 科创50 在 ignored_erp_holdings | 升级为进攻 bucket | 需要配置 kc50 alias mapping |
| 5 bucket 系统 | 10 bucket 系统 (+kc50, +val300, +gro300, +hsi, +hstech) | daily summary 模板需要更新 |
| HS300 残差兜底覆盖全部 | HS300 兜底 A 股，HSI 兜底港股 | 总残差 = HS300 残差 + HSI 残差 |

---

*方案版本: v1.0 | 日期: 2026-07-05 | 状态: 待审阅*
