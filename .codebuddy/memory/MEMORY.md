# 项目长期记忆

## 反向分析第三方程股系统（2026-06-27 建立）

### 项目背景
- 有一个第三方 AI 选股系统，每天 14:30 选出 A 股，次日高开概率极高
- 历史数据：215 次选股，211 次成功，4 次失败，成功率 98.14%
- 用户获取选股结果在闭市后（>15:00），形式为截图或文本

### 核心发现（基于 215 条数据分析）
- **不局限于强势股票**：空头排列+强势空头占 44.5%，系统捕捉的是低位反转/超跌反弹
- **趋势强度关键门槛**：成功组均值 44.17，失败组均值 21.25，阈值约 30
- **价格必须贴近均线**：成功组乖离率接近 0，失败组乖离率 -1.7%
- **量能正常**：78% 量能正常，不追爆量，不接缩量死股
- **失败 4 只共性**：趋势极弱(<25)、价格远低于均线、量能偏低

### 产出文件
| 文件 | 用途 |
|------|------|
| `scripts/reverse_collect.py` | 历史选股数据采集（拉取K线+技术分析） |
| `scripts/reverse_analyze.py` | LLM 规律分析（需 API Key） |
| `scripts/generate_report.py` | 无 LLM 的统计报告生成 |
| `scripts/screen_reverse.py` | **全市场扫描引擎**（选股核心） |
| `scripts/reverse_train.py` | **训练对比工具**（CMD 版） |
| `scripts/reverse_maintain.py` | 旧版维护工具 |
| `strategies/reverse_engineered.yaml` | **已部署的选股策略** |
| `data/reverse/history.csv` | 215 条原始选股记录（date, stock_code, success, gain） |
| `data/reverse/collected.jsonl` | 215 只股票技术特征数据 |
| `data/reverse/pattern_report.md` | 规律分析报告 |

### 系统集成
- **后端 API**：`api/v1/endpoints/reverse_training.py`（9个端点）
- **前端页面**：`apps/dsa-web/src/pages/ReverseTrainingPage.tsx`（路由 `/reverse-training`）
- **侧边栏**：导航项「策略训练」
- **AlphaSift 集成**：`reverse_engineered` 策略已注入策略列表，在选股页面可直接选择

### 失败案例（4只）
- 鼎泰高科 301377（2026/3/26）-4.95%
- 豪威集团 603501（2026/3/20）-1.80%
- 弘信电子 300657（2026/3/20）-0.30%
- 先惠技术 688155（2026/3/6）-3.03%

### 待办
- 配置 LLM API Key 后可使用 `reverse_analyze.py` 做更深层分析
- 每日 14:30 运行 `reverse_train.py scan` 或通过页面操作
- 持续录入第三方选股数据，用 `train` 命令重新训练策略
