---
name: financial-analysis-skill-patterns
description: Skill creation patterns extracted from index-compare repository - A comprehensive guide for building data analysis skills for Claude Code
version: 1.0.0
source: local-git-analysis
analyzed_commits: 1
total_python_lines: 2282
repository: 500,1000比价skill
---

# Financial Analysis Skill Creation Patterns

## Overview

This document captures the patterns and best practices extracted from the **index-compare** skill repository, which implements a comprehensive A-share index valuation analysis tool. The skill analyzes price ratios between CSI 500, CSI 1000, and CSI 300 indices, generating intelligent reports with actionable investment recommendations.

**Repository Stats:**
- Total Python Code: ~2,282 lines
- Skill Type: Data analysis and reporting
- Primary Language: Python
- Output Format: Interactive HTML reports (Plotly)

---

## Pattern 1: Skill Architecture - Modular Script Organization

### Structure

```
.claude/skills/{skill-name}/
├── SKILL.md                    # Main skill documentation (user-facing)
├── config.json                 # Configuration parameters
├── analysis-rules.md           # Domain-specific rules (optional)
├── scripts/
│   ├── main.py                # Single entry point (CRITICAL)
│   ├── fetch_data.py          # Data acquisition module
│   ├── calculate.py           # Data processing module
│   ├── analyze.py             # Analysis logic module
│   └── generate_report.py     # Output generation module
├── data/                      # Generated data files
└── reports/                   # Generated reports
```

### Key Principles

1. **Single Entry Point**: Always provide a `main.py` that orchestrates the entire workflow
2. **Modular Separation**: Each script handles one responsibility
3. **Progressive Execution**: Scripts can be run independently or as a pipeline
4. **Data Persistence**: Intermediate results saved for debugging and quick queries

### Example: main.py Structure

```python
def run_pipeline():
    """Complete analysis workflow"""
    # Step 1: Environment check
    # Step 2: Data acquisition
    # Step 3: Data processing
    # Step 4: Analysis
    # Step 5: Report generation
    # Step 6: Display summary

def quick_query(params):
    """Fast mode: read existing data without re-fetching"""
    # Read cached data
    # Display formatted results

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--query', help='Quick query mode')
    args = parser.parse_args()

    if args.query:
        quick_query(args.query)
    else:
        run_pipeline()
```

---

## Pattern 2: SKILL.md Best Practices

### YAML Frontmatter

```yaml
---
name: skill-name
description: Clear description with trigger keywords. Include natural language phrases users might say like "比价分析", "指数对比", "generate report", "index compare"
---
```

### Critical Elements

1. **Trigger-Rich Description**: Include multiple ways users might invoke the skill
   - Technical terms: "index compare", "valuation analysis"
   - Natural language: "how is CSI 500 doing", "generate index report"
   - Domain-specific: "比价分析", "分位数查询"

2. **Quick Start Section**: Show the simplest usage first
   ```markdown
   ## Quick Start

   ### Method 1: Full Analysis (Recommended for first use)
   ```bash
   python scripts/main.py
   ```

   ### Method 2: Quick Query (View existing data)
   ```bash
   python scripts/main.py --query
   ```
   ```

3. **Clear Output Examples**: Show what users will see
   ```markdown
   ## Output Example

   Running `python scripts/main.py` displays:

   ```
   ============================================================
            Index Valuation Analysis
   ============================================================
   [Step 1/5] Checking environment...
   ✓ Token configured
   ...
   ```
   ```

4. **Error Handling Table**: Document common issues
   ```markdown
   | Error | Solution |
   |-------|----------|
   | Token not set | Print setup guide, exit |
   | API call fails | Retry 3 times, 2s interval |
   ```

---

## Pattern 3: Configuration Management

### config.json Structure

```json
{
  "indices": {
    "HS300": {
      "code": "000300.SH",
      "name": "沪深300",
      "role": "benchmark"
    },
    "ZZ500": {
      "code": "000905.SH",
      "name": "中证500",
      "role": "target"
    }
  },
  "analysis": {
    "ma_window": 30,
    "recent_days": 1000,
    "percentile_base": "all_history"
  },
  "output": {
    "report_dir": "../../",
    "data_dir": "data",
    "format": "html"
  },
  "api": {
    "retry_times": 3,
    "retry_interval": 2,
    "timeout": 30
  }
}
```

### Key Principles

1. **Hierarchical Organization**: Group related settings
2. **Self-Documenting**: Use clear key names
3. **Sensible Defaults**: Provide working defaults for all parameters
4. **Extensibility**: Easy to add new indices or parameters

---

## Pattern 4: User Experience - Dual Mode Operation

### Full Analysis Mode

**Purpose**: Complete data refresh and analysis
**Use Case**: Daily/weekly reports, first-time use
**Execution Time**: 30-60 seconds

```bash
python scripts/main.py
```

**Output**:
- Progress indicators for each step
- Data summary table
- Configuration recommendations
- Report file path

### Quick Query Mode

**Purpose**: Instant access to cached results
**Use Case**: Quick checks, follow-up questions
**Execution Time**: < 1 second

```bash
python scripts/main.py --query          # All indices
python scripts/main.py --query ZZ500    # Specific index
```

**Output**:
- Formatted table with key metrics
- Latest data timestamp
- Actionable recommendations

### Implementation Pattern

```python
def quick_query(index_code=None):
    """Fast mode: read existing data"""
    # Check if data files exist
    if not conclusions_file.exists():
        print("[ERROR] Data files not found")
        print("Please run full analysis first:")
        print("  python scripts/main.py")
        sys.exit(1)

    # Load cached data
    with open(conclusions_file, 'r') as f:
        conclusions = json.load(f)

    # Display formatted results
    print_summary_table(conclusions, index_code)
```

---

## Pattern 5: Progressive Output - User Feedback

### Step-by-Step Progress Indicators

```python
print("=" * 60)
print("         Index Valuation Analysis")
print("=" * 60)
print(f"Execution time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 60)

print("\n[Step 1/5] Checking environment...")
# ... validation logic ...
print("[OK] Token configured")

print("\n[Step 2/5] Fetching index data...")
# ... data fetching ...
print("[OK] Data fetched")

print("\n[Step 3/5] Calculating price ratios...")
# ... calculation ...
print("[OK] Calculations complete")

print("\n[Step 4/5] Generating analysis...")
# ... analysis ...
print("[OK] Analysis complete")

print("\n[Step 5/5] Generating HTML report...")
# ... report generation ...
print("[OK] Report generated")
```

### Summary Display Pattern

```python
# Display data summary table
print("\n[DATA] Latest data (2026-01-25):")
print("+-------------+----------+----------+----------+")
print("| Metric      | CSI 500  | CSI 1000 | CSI 300  |")
print("+-------------+----------+----------+----------+")
print(f"| Close       | {val1:>8.2f} | {val2:>8.2f} | {val3:>8.2f} |")
print(f"| Ratio       | {val4:>8.4f} | {val5:>8.4f} | (base)   |")
print(f"| Percentile  | {val6:>7.1f}% | {val7:>7.1f}% |    -     |")
print("+-------------+----------+----------+----------+")

# Display recommendations
print("\n[RECOMMEND] Configuration suggestions:")
for index, conclusion in conclusions.items():
    rec = conclusion.get('recommendation', {})
    print(f"\n【{index}】{rec['icon']} {rec['action']}")
    for reason in rec['reasons']:
        print(f"  - {reason}")
```

---

## Pattern 6: Environment Management

### Token Handling Pattern

```python
def check_environment():
    """Check and load API token"""
    token = os.environ.get('TUSHARE_TOKEN')

    # Fallback: try loading from .env file
    if not token:
        env_file = Path('.env')
        if env_file.exists():
            with open(env_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip().startswith('TUSHARE_TOKEN='):
                        token = line.split('=', 1)[1].strip()
                        os.environ['TUSHARE_TOKEN'] = token
                        break

    if not token:
        print("ERROR: TUSHARE_TOKEN not set")
        print("\nPlease set it using:")
        print("  Windows PowerShell: $env:TUSHARE_TOKEN = 'your_token'")
        print("  Windows CMD: set TUSHARE_TOKEN=your_token")
        print("  Linux/Mac: export TUSHARE_TOKEN=your_token")
        print("  Or create .env file: TUSHARE_TOKEN=your_token")
        print("\nGet token: https://tushare.pro/register")
        sys.exit(1)

    print("[OK] Token configured")
    return token
```

---

## Pattern 7: Data Pipeline Architecture

### Module Responsibilities

| Module | Input | Output | Purpose |
|--------|-------|--------|---------|
| `fetch_data.py` | API credentials, index codes | `raw_data.csv` | Data acquisition |
| `calculate.py` | `raw_data.csv` | `processed_data.csv` | Ratio calculation, percentiles |
| `analyze.py` | `processed_data.csv` | `conclusions.json` | Trend analysis, recommendations |
| `generate_report.py` | `processed_data.csv`, `conclusions.json` | `report.html` | Visualization |

### Data Flow

```
[API] → fetch_data.py → raw_data.csv
                            ↓
                      calculate.py → processed_data.csv
                                          ↓
                                    analyze.py → conclusions.json
                                                      ↓
                                              generate_report.py → report.html
```

### Error Handling Strategy

```python
def fetch_with_retry(func, max_retries=3, interval=2):
    """Retry wrapper for API calls"""
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"[WARN] Attempt {attempt + 1} failed: {e}")
                print(f"[INFO] Retrying in {interval}s...")
                time.sleep(interval)
            else:
                print(f"[ERROR] All {max_retries} attempts failed")
                raise
```

---

## Pattern 8: Intelligent Analysis Integration

### Analysis Dimensions

1. **Trend Analysis**: Compare current vs historical values
2. **Percentile Ranking**: Position in historical distribution
3. **Mean Reversion**: Deviation from moving average
4. **Actionable Recommendations**: Synthesize all signals

### Analysis Output Structure

```json
{
  "ZZ500": {
    "current_ratio": 1.2345,
    "percentile": {
      "value": 35.2,
      "level": "relative_undervalued"
    },
    "deviation": {
      "value": -3.5,
      "status": "oversold"
    },
    "trend": {
      "direction": "upward",
      "strength": "moderate"
    },
    "recommendation": {
      "action": "overweight",
      "icon": "📈",
      "reasons": [
        "Historical percentile at 35%, relatively undervalued",
        "Short-term oversold, potential rebound",
        "Upward trend confirmed"
      ]
    },
    "summary": "CSI 500 vs CSI 300 ratio at 1.2345 (35th percentile)..."
  }
}
```

### Recommendation Logic

```python
def generate_recommendation(percentile, deviation, trend):
    """Generate actionable recommendation"""
    if percentile < 20 and deviation < -5:
        return {
            "action": "Strong Overweight",
            "icon": "🚀",
            "reasons": [
                f"Extremely undervalued (percentile: {percentile:.1f}%)",
                f"Oversold condition (deviation: {deviation:.1f}%)",
                "High probability of mean reversion"
            ]
        }
    elif percentile < 40:
        return {
            "action": "Overweight",
            "icon": "📈",
            "reasons": [
                f"Relatively undervalued (percentile: {percentile:.1f}%)",
                "Favorable risk/reward ratio"
            ]
        }
    # ... more conditions ...
```

---

## Pattern 9: Report Generation - Interactive Visualization

### HTML Report Structure

```python
def generate_report(data_file, conclusions_file, output_dir):
    """Generate interactive HTML report with Plotly"""
    # Load data
    df = pd.read_csv(data_file, parse_dates=['trade_date'])
    with open(conclusions_file, 'r') as f:
        conclusions = json.load(f)

    # Create Plotly figures
    fig1 = create_ratio_chart(df, 'ZZ500')
    fig2 = create_ratio_chart(df, 'ZZ1000')

    # Build HTML with embedded charts
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Index Valuation Analysis</title>
        <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            .summary-card {{ border: 1px solid #ddd; padding: 15px; margin: 10px 0; }}
        </style>
    </head>
    <body>
        <h1>Index Valuation Analysis Report</h1>
        <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>

        <div id="chart1"></div>
        <div id="chart2"></div>

        <div class="summary-card">
            <h2>Analysis Summary</h2>
            {format_conclusions(conclusions)}
        </div>
    </body>
    </html>
    """

    # Save report
    report_path = Path(output_dir) / f"index_compare_{timestamp}.html"
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(html)

    return str(report_path)
```

---

## Pattern 10: Workflow Patterns from Task Planning

### Development Workflow

Based on the `task_plan.md` and `findings.md` files, the repository follows this workflow:

1. **Initial Exploration**: Understand existing skill implementations
2. **Problem Identification**: Document what doesn't meet standards
3. **Solution Design**: Create detailed adjustment plan with priorities
4. **Iterative Implementation**: Execute P0 → P1 → P2 tasks
5. **Testing & Validation**: Test trigger scenarios and full workflows

### Priority Classification

| Priority | Description | Examples |
|----------|-------------|----------|
| **P0** | Must fix - affects core functionality | SKILL.md format, execution flow |
| **P1** | Should optimize - improves UX | Output formatting, quick query mode |
| **P2** | Nice to have - polish | File structure optimization |

### Testing Scenarios

```markdown
### Test Scenario 1: Trigger Test
- Input: "生成比价分析报告"
- Input: "/index-compare"
- Input: "分析中证500和中证1000"
- Expected: Skill correctly triggered

### Test Scenario 2: Full Report Generation
- Run complete workflow
- Verify report files generated
- Validate data summary display

### Test Scenario 3: Quick Query
- Input: "查询中证500当前比价"
- Expected: Fast response without re-fetching data
```

---

## Pattern 11: Documentation Hierarchy

### Three-Tier Documentation

1. **SKILL.md** (User-facing)
   - Quick start guide
   - Common usage patterns
   - Error handling
   - Keep concise and scannable

2. **config.json** (Configuration)
   - All tunable parameters
   - Self-documenting structure
   - Sensible defaults

3. **analysis-rules.md** (Domain knowledge)
   - Detailed methodology
   - Interpretation guidelines
   - Reference material
   - Claude reads only when needed

### Menu Pattern

Instead of embedding everything in SKILL.md:

```markdown
## Technical Details

For more information, see:
- `config.json` - Index configuration and analysis parameters
- `analysis-rules.md` - Detailed analysis methodology
- `scripts/` - Individual module documentation
```

This keeps SKILL.md focused while making detailed info available on demand.

---

## Pattern 12: Commit Message Conventions

### Observed Pattern

From the repository's single commit:
```
36d182f 0.1.0调试阶段
```

### Recommended Convention

For skill development projects, use semantic versioning in commits:

```
v0.1.0 - Initial skill structure
v0.2.0 - Add quick query mode
v0.3.0 - Improve output formatting
v1.0.0 - Production ready
```

Or conventional commits:
```
feat: add quick query mode for cached data
fix: handle missing TUSHARE_TOKEN gracefully
docs: update SKILL.md with output examples
refactor: modularize data fetching logic
```

---

## Pattern 13: File Organization Best Practices

### What to Include in Skill Directory

✅ **Include:**
- `SKILL.md` - Main documentation
- `config.json` - Configuration
- `scripts/*.py` - Executable scripts
- `data/` - Generated data (gitignored)
- `reports/` - Generated reports (gitignored)

❌ **Exclude from Git:**
- Generated reports (`.html`, `.pdf`)
- Cached data files (`.csv`, `.json` in `data/`)
- Temporary files
- API tokens or credentials

### .gitignore Pattern

```gitignore
# Generated reports
*.html
*.pdf
reports/

# Data files
data/*.csv
data/*.json

# Environment
.env
*.pyc
__pycache__/
```

---

## Pattern 14: Chinese-English Bilingual Support

### Observed Pattern

The skill seamlessly supports both Chinese and English:

**Chinese Triggers:**
- "比价分析"
- "指数对比"
- "500和1000怎么样"
- "中证500分位"

**English Triggers:**
- "index compare"
- "generate index report"
- "valuation analysis"

### Implementation

```python
# Chinese output with clear formatting
print("【中证500】📈 超配")
print("  - 历史分位35%，相对低估")
print("  - 短期超卖，可能反弹")

# Or English equivalent
print("【CSI 500】📈 Overweight")
print("  - Historical percentile 35%, relatively undervalued")
print("  - Short-term oversold, potential rebound")
```

### Best Practice

For bilingual skills:
1. Use both languages in SKILL.md description
2. Support natural language triggers in both languages
3. Choose one primary language for output (consistency)
4. Use emojis and symbols for universal understanding

---

## Pattern 15: Dependency Management

### Requirements Pattern

```python
# In scripts, check dependencies gracefully
try:
    import tushare as ts
    import pandas as pd
    import numpy as np
    import plotly.graph_objects as go
    from scipy import stats
except ImportError as e:
    print(f"[ERROR] Missing dependency: {e}")
    print("\nPlease install required packages:")
    print("  pip install tushare pandas numpy plotly scipy")
    sys.exit(1)
```

### Document in SKILL.md

```markdown
## Environment Requirements

**Python Dependencies:**
```
tushare>=1.2.0
pandas>=1.5.0
numpy>=1.20.0
plotly>=5.0.0
scipy>=1.7.0
```

**Installation:**
```bash
pip install tushare pandas numpy plotly scipy
```
```

---

## Summary: Key Takeaways

### Essential Patterns for Data Analysis Skills

1. **Single Entry Point**: Always provide `main.py` with clear workflow
2. **Dual Mode**: Full analysis + quick query for different use cases
3. **Progressive Feedback**: Show step-by-step progress with clear indicators
4. **Rich Output**: Tables, summaries, and actionable recommendations
5. **Graceful Errors**: Helpful error messages with solutions
6. **Modular Design**: Separate concerns into focused modules
7. **Configuration-Driven**: Externalize parameters to `config.json`
8. **Interactive Reports**: Use Plotly for rich visualizations
9. **Bilingual Support**: Natural language triggers in multiple languages
10. **Documentation Hierarchy**: SKILL.md (concise) + detailed references

### Skill Quality Checklist

- [ ] SKILL.md has trigger-rich description
- [ ] Quick start section shows simplest usage
- [ ] Single `main.py` entry point exists
- [ ] Quick query mode for cached data
- [ ] Progress indicators for long operations
- [ ] Summary tables with key metrics
- [ ] Actionable recommendations displayed
- [ ] Error messages include solutions
- [ ] Environment setup documented
- [ ] Dependencies listed with versions
- [ ] Output examples shown
- [ ] Configuration externalized
- [ ] Reports are interactive (if applicable)
- [ ] Bilingual triggers supported (if applicable)

---

## Application to Other Domains

These patterns can be adapted for:

- **Stock Analysis**: Portfolio optimization, risk analysis
- **Data Science**: ML model training, data profiling
- **DevOps**: Log analysis, performance monitoring
- **Content Generation**: Report generation, document processing
- **Research**: Literature review, data extraction

The core principles remain:
1. Clear entry point
2. Progressive feedback
3. Actionable output
4. Graceful error handling
5. Modular architecture

---

*Generated by /skill-create analysis of index-compare repository*
*Repository: 500,1000比价skill*
*Analysis Date: 2026-01-30*
