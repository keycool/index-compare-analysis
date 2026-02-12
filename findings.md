# 发现和研究记录

## 项目背景
- 项目名称：index-compare skill（指数比价分析）
- 功能：分析中证500、中证1000相对沪深300的比价关系
- 当前状态：已生成但不标准

## 代码库发现

### 当前目录结构
```
.claude/skills/index-compare/
├── SKILL.md                 # Skill 主文件
├── config.json              # 指数配置
├── analysis-rules.md        # 分析规则说明
├── scripts/
│   ├── main.py             # 主入口脚本
│   ├── fetch_data.py       # 数据获取
│   ├── calculate.py        # 比价计算
│   ├── analyze.py          # 智能分析
│   └── generate_report.py  # 报告生成
├── data/                   # 数据文件
└── reports/                # 生成的报告
```

## Skill规范要求（基于官方文档）

### 核心组件
1. **SKILL.md 文件头部（YAML frontmatter）**
   - `name`: 技能名称（小写，连字符分隔）
   - `description`: 触发描述（最关键，决定何时激活）
   - `allowed-tools`: 可选，限制可用工具
   - `license`: 可选，许可证信息

2. **Description 最佳实践**
   - 从Claude视角编写
   - 包含具体能力、清晰触发词、相关上下文、边界说明
   - 使用动作动词、具体文件类型、明确用例
   - 避免模糊描述

3. **Instructions 结构**
   - 清晰的层次结构（markdown标题）
   - 可扫描的内容（项目符号、代码块）
   - 具体示例展示正确用法
   - 错误处理说明
   - 明确限制条件

4. **文件大小考虑**
   - 避免臃肿的上下文窗口
   - 使用"菜单"方法：主文件描述可用选项，用相对路径引用独立文件
   - Claude只读取任务相关的文件

## 存在的问题

### 1. SKILL.md 格式问题
- ❌ YAML frontmatter 格式不标准（使用了 `---` 但格式可能有问题）
- ❌ `allowed-tools` 字段可能不必要（应该让Claude自动选择）
- ⚠️ Description 可以更具体，增加更多触发场景

### 2. 执行流程问题
- ❌ SKILL.md 中描述的是手动执行多个脚本的流程
- ✅ 实际有 main.py 作为统一入口（这是好的）
- ⚠️ 但 SKILL.md 没有清楚说明应该直接运行 main.py

### 3. 文件组织问题
- ⚠️ analysis-rules.md 和 config.json 可能不需要在主 SKILL.md 中引用
- ⚠️ 应该让 Claude 在需要时才读取这些文件

### 4. 用户体验问题
- ❌ 缺少快速查询模式的实现（SKILL.md 提到但未实现）
- ⚠️ 报告生成后没有自动打开或显示摘要
