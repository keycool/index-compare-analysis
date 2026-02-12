# 任务计划：调整index-compare Skill使其符合标准

## 目标
调整已生成的index-compare skill，使其符合Claude Code skill的标准规范

## 当前状态
- [x] 初始探索 - 了解现有skill实现
- [x] 识别问题 - 明确哪些地方不标准
- [x] 制定方案 - 设计调整策略
- [ ] 执行调整 - 修改代码和配置
- [ ] 测试验证 - 确保skill正常工作

---

## 调整方案总览

### 优先级分类
- 🔴 **P0 - 必须修复**：影响skill正常触发和执行
- 🟡 **P1 - 应该优化**：提升用户体验和代码质量
- 🟢 **P2 - 可以改进**：锦上添花的优化

---

## 详细调整计划

### 📋 任务1: 修复SKILL.md格式 (P0)

**问题：**
- YAML frontmatter格式不标准
- 执行流程描述不清晰（描述了5个独立步骤，但实际应该运行main.py）
- Description可以更具体

**调整内容：**
1. 修正YAML frontmatter格式
2. 移除`allowed-tools`字段（让Claude自动选择）
3. 优化description，增加更多触发场景
4. 简化执行流程，明确指出运行`python scripts/main.py`
5. 移除手动执行多个脚本的复杂说明

**涉及文件：**
- `.claude/skills/index-compare/SKILL.md`

---

### 📋 任务2: 优化执行流程说明 (P0)

**问题：**
- SKILL.md描述的是分步执行5个脚本
- 实际有main.py统一入口但未突出说明

**调整内容：**
1. 在SKILL.md开头明确说明：直接运行`python scripts/main.py`即可
2. 简化"执行步骤"部分，只保留关键信息
3. 将详细的技术实现移到单独的文档（如果需要）

**涉及文件：**
- `.claude/skills/index-compare/SKILL.md`

---

### 📋 任务3: 改进main.py输出格式 (P1)

**问题：**
- 报告生成后只打印文件路径
- 缺少数据摘要展示

**调整内容：**
1. 在main.py完成后读取关键数据
2. 打印格式化的摘要表格（最新比价、分位、偏离度）
3. 打印简要的配置建议

**涉及文件：**
- `.claude/skills/index-compare/scripts/main.py`

---

### 📋 任务4: 添加快速查询模式 (P1)

**问题：**
- SKILL.md提到"快速查询模式"但未实现

**调整内容：**
1. 在main.py添加`--query`参数支持
2. 查询模式：只读取已有数据，不重新获取
3. 支持查询特定指数（如`--query ZZ500`）

**涉及文件：**
- `.claude/skills/index-compare/scripts/main.py`
- `.claude/skills/index-compare/SKILL.md`（更新使用说明）

---

### 📋 任务5: 优化文件引用结构 (P2)

**问题：**
- SKILL.md中引用了config.json和analysis-rules.md
- 这些文件应该按需读取，不应在主文件中详细说明

**调整内容：**
1. 在SKILL.md中简化对配置文件的说明
2. 只在需要时让Claude读取这些文件
3. 保持SKILL.md简洁，聚焦核心使用流程

**涉及文件：**
- `.claude/skills/index-compare/SKILL.md`

---

## 关键文件清单

### 需要修改的文件
1. `.claude/skills/index-compare/SKILL.md` - 主要调整
2. `.claude/skills/index-compare/scripts/main.py` - 功能增强

### 参考文件（不修改）
- `config.json` - 配置参考
- `analysis-rules.md` - 分析规则参考
- 其他Python脚本 - 保持不变

---

## 执行顺序

1. **先修改SKILL.md** (任务1, 2, 5)
   - 这是最关键的，影响skill触发和使用

2. **再优化main.py** (任务3, 4)
   - 提升用户体验

3. **最后测试验证**
   - 测试skill触发
   - 测试完整报告生成
   - 测试快速查询模式

---

## 测试计划

### 测试场景1: 触发测试
- 输入："生成比价分析报告"
- 输入："/index-compare"
- 输入："分析中证500和中证1000"
- 预期：skill正确触发

### 测试场景2: 完整报告生成
- 运行完整流程
- 检查报告文件生成
- 验证数据摘要显示

### 测试场景3: 快速查询
- 输入："查询中证500当前比价"
- 预期：快速返回结果，不重新获取数据

---

## 风险和注意事项

1. **环境依赖**
   - 需要TUSHARE_TOKEN环境变量
   - 需要Python依赖包已安装

2. **数据文件**
   - 保留现有data/目录中的数据
   - 不要删除已生成的报告

3. **向后兼容**
   - 确保现有功能不受影响
   - main.py的基本用法保持不变
