#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===================================
反向分析工具 - LLM 规律分析与策略生成
===================================

用途：对采集到的历史选股数据进行批量横向对比，利用 LLM 识别共同规律，
     并生成可用的 YAML 策略文件。

用法：
    1. 先运行 reverse_collect.py 完成数据采集
    2. 运行分析：
       python scripts/reverse_analyze.py
       python scripts/reverse_analyze.py --input data/reverse/collected.jsonl
       python scripts/reverse_analyze.py --export-strategy   # 同时导出 YAML 策略

    3. 输出：
       - data/reverse/pattern_report.md      (LLM 规律分析报告)
       - data/reverse/strategy.yaml          (可用的策略文件，--export-strategy 时生成)
       - data/reverse/stats.json             (统计数据)
"""

import argparse
import json
import logging
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# 将项目根目录加入 sys.path
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

import litellm
from litellm import completion as litellm_completion

from src.config import get_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("reverse_analyze")

# ============================================================
# 配置
# ============================================================
DATA_DIR = Path("data") / "reverse"
DEFAULT_INPUT = DATA_DIR / "collected.jsonl"
OUTPUT_REPORT = DATA_DIR / "pattern_report.md"
OUTPUT_STRATEGY = DATA_DIR / "strategy.yaml"
OUTPUT_STATS = DATA_DIR / "stats.json"
OUTPUT_SUMMARY_DATA = DATA_DIR / "analysis_summary.json"

# 发送给 LLM 的批量大小（每批最多 N 只股票的数据）
BATCH_SIZE = 30

# ============================================================
# 数据加载与统计
# ============================================================


def load_collected(jsonl_path: Path) -> List[Dict]:
    """加载采集的 JSONL 数据。"""
    if not jsonl_path.exists():
        logger.error(f"找不到数据文件: {jsonl_path}")
        logger.info(f"请先运行 python scripts/reverse_collect.py")
        sys.exit(1)

    records = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    logger.info(f"加载 {len(records)} 条记录")
    return records


def build_statistics(records: List[Dict]) -> Dict:
    """构建统计摘要。"""
    success = [r for r in records if r.get("success") == 1]
    fail = [r for r in records if r.get("success") == 0]

    stats = {
        "total": len(records),
        "success_count": len(success),
        "fail_count": len(fail),
        "success_rate": round(len(success) / max(len(records), 1) * 100, 2),
        "date_range": {
            "start": min(r["pick_date"] for r in records),
            "end": max(r["pick_date"] for r in records),
        },
        "unique_stocks": len(set(r["code"] for r in records)),
        "success": {},
        "fail": {},
    }

    # 对成功/失败组分别分析关键特征的分布
    for group_name, group_data in [("success", success), ("fail", fail)]:
        if not group_data:
            continue
        trend_counts = Counter(r["trend_status"] for r in group_data)
        volume_counts = Counter(r["volume_status"] for r in group_data)
        macd_counts = Counter(r["macd_status"] for r in group_data)

        avg_features = {
            "trend_strength": round(sum(r.get("trend_strength", 0) or 0 for r in group_data) / len(group_data), 2),
            "bias_ma5": round(sum(r.get("bias_ma5", 0) or 0 for r in group_data) / len(group_data), 2),
            "bias_ma10": round(sum(r.get("bias_ma10", 0) or 0 for r in group_data) / len(group_data), 2),
            "volume_ratio_5d": round(sum(r.get("volume_ratio_5d", 0) or 0 for r in group_data) / len(group_data), 2),
        }

        # 筹码数据（可能有空值）
        chip_ratios = [r["chip_ratio"] for r in group_data if r.get("chip_ratio") is not None]
        avg_features["avg_chip_ratio"] = round(sum(chip_ratios) / len(chip_ratios), 2) if chip_ratios else None

        stats[group_name] = {
            "count": len(group_data),
            "trend_status_distribution": dict(trend_counts.most_common()),
            "volume_status_distribution": dict(volume_counts.most_common()),
            "macd_status_distribution": dict(macd_counts.most_common()),
            "avg_features": avg_features,
        }

    return stats


def format_batch_for_llm(records: List[Dict], batch_label: str) -> str:
    """将一批记录格式化为 LLM 可读的文本。"""
    lines = [f"=== {batch_label} ==="]
    for r in records:
        lines.append(f"股票: {r['code']}")
        lines.append(f"  选中日期: {r['pick_date']}")
        lines.append(f"  趋势: {r['trend_status']} (强度: {r['trend_strength']})")
        lines.append(f"  均线: MA5={r['ma5']:.2f}, MA10={r['ma10']:.2f}, MA20={r['ma20']:.2f}")
        lines.append(f"  乖离率: MA5={r['bias_ma5']:.2f}%, MA10={r['bias_ma10']:.2f}%")
        lines.append(f"  量能: {r['volume_status']} (量比5日: {r['volume_ratio_5d']:.2f})")
        lines.append(f"  MACD: {r['macd_status']}")
        lines.append(f"  RSI: {r.get('rsi_status', 'N/A')} (RSI6={r.get('rsi_6', 'N/A')})")
        lines.append(f"  支撑: MA5支撑={r['support_ma5']}, MA10支撑={r['support_ma10']}")
        lines.append(f"  收盘价: {r['latest_close']:.2f}")
        if r.get("chip_ratio") is not None:
            lines.append(f"  筹码获利比例: {r['chip_ratio']:.1f}%, 集中度: {r.get('chip_concentration', 'N/A')}")
        if r.get("pe_ttm") is not None:
            lines.append(f"  PE: {r['pe_ttm']}, PB: {r['pb']}")
            lines.append(f"  总市值: {r['total_mv']}亿, 换手率: {r.get('turnover_ratio', 'N/A')}%")
        lines.append("")
    return "\n".join(lines)


# ============================================================
# LLM 分析
# ============================================================


def _call_llm(prompt: str) -> str:
    """调用 LLM 返回分析文本。"""
    cfg = get_config()
    model = cfg.litellm_model or "gemini/gemini-2.5-flash-preview"

    # 优先获取 API key
    api_key = None
    if cfg.gemini_api_keys:
        api_key = cfg.gemini_api_keys[0]
    elif cfg.openai_api_keys:
        api_key = cfg.openai_api_keys[0]

    response = litellm_completion(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "你是一位专业的 A 股量化分析师，擅长从技术面数据中发现选股规律。回答要简洁、准确、有数据支撑。",
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=4096,
        temperature=0.3,
        api_key=api_key,
    )

    if response and response.choices and response.choices[0].message.content:
        return response.choices[0].message.content
    raise ValueError("LLM 返回空响应")


ANALYSIS_PROMPT_TEMPLATE = """# A 股选股规律反向分析任务

## 背景
有一个高胜率（约98%）的 AI 选股系统，每天 14:30 选出以下股票（A股），这些股票第 T+1 日高开盈利的概率极高。

下面是该系统历史上选出的 **{group_label}** 股票的技术面特征数据（共 {count} 只）：

{stock_data}

## 分析要求
请从以下维度分析这些股票的**共同特征**，找出它们被选中的可能规律：

### 1. 趋势形态共性
- 多头排列比例？MA5>MA10>MA20 占比多少？
- 趋势强度分布（0-100）？
- 有无特定的 K 线形态模式？

### 2. 乖离率特征
- 乖离率范围？集中在什么区间？
- 是否都偏向"回踩均线"类型？

### 3. 量能特征
- 放量还是缩量？量比特征？
- 缩量回调的比例？

### 4. MACD 特征
- MACD 状态分布（金叉/多头/零轴位置）？
- 有无明显规律？

### 5. 筹码特征
- 获利比例分布？集中度分布？
- 有无明显规律？

### 6. 其他特征
- 支撑位位置？
- 换手率特征？
- PE/PB 特征？

## 输出格式
请按以下结构输出分析结果：

## 规律总结
[一句话概括该选股系统的核心规律]

## 各维度详细分析
### 1. 趋势形态
[具体分析]

### 2. 乖离率
[具体分析]

...

## 选股规则提取
请将识别出的规律转化为可执行的选股规则，格式如下：
```yaml
rule_1:
  condition: "MA5 > MA10 > MA20"
  threshold: "超过XX%的选股满足此条件"
  description: "趋势描述"

rule_2:
  condition: "乖离率范围 -X% ~ Y%"
  ...
```

## 置信度评分
[给这套规律的整体可靠性打分 0-100，说明理由]
"""


def run_llm_analysis(records: List[Dict], stats: Dict) -> str:
    """使用 LLM 分析选股规律。"""
    success = [r for r in records if r.get("success") == 1]
    fail = [r for r in records if r.get("success") == 0]

    logger.info(f"成功组: {len(success)} 只, 失败组: {len(fail)} 只")

    report_parts = [
        "# 选股规律反向分析报告",
        "",
        f"**分析时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**总样本**: {stats['total']} 次选股",
        f"**成功率**: {stats['success_rate']}%",
        f"**时间范围**: {stats['date_range']['start']} ~ {stats['date_range']['end']}",
        f"**涉及个股**: {stats['unique_stocks']} 只",
        "",
        "---",
        "",
    ]

    # 逐批分析成功组（失败组样本少，一次即可）
    # 优先分析成功组寻找共性规律
    batches = []
    for i in range(0, len(success), BATCH_SIZE):
        batch = success[i:i + BATCH_SIZE]
        label = f"成功组 第{i//BATCH_SIZE + 1}批 (共{len(batch)}只)"
        batches.append((label, batch))

    # 如果失败组也有数据，也分析
    if fail:
        batches.append((f"失败组 (共{len(fail)}只)", fail))

    for label, batch in batches:
        logger.info(f"分析: {label}")
        stock_data = format_batch_for_llm(batch, label)
        prompt = ANALYSIS_PROMPT_TEMPLATE.format(
            group_label=label,
            count=len(batch),
            stock_data=stock_data,
        )
        result = _call_llm(prompt)
        report_parts.append(f"## {label}\n\n{result}\n\n---\n")

    # 如果有多批成功组，再加上综合交叉分析
    if len(batches) > 1:
        logger.info("执行综合交叉分析...")
        cross_prompt = (
            f"你对同一选股系统的 {len(success)} 只成功股票和 {len(fail)} 只失败股票分别做了分析。"
            f"请综合所有分析结果，给出最关键的 5 条选股规则，并按重要性排序。"
            f"每条规则需要说明：条件、支持该条件的股票比例、置信度。"
        )
        cross_result = _call_llm(cross_prompt)
        report_parts.append(f"## 综合交叉分析\n\n{cross_result}")

    full_report = "\n".join(report_parts)
    return full_report


# ============================================================
# 策略 YAML 生成
# ============================================================


def generate_strategy_yaml(stats: Dict) -> str:
    """基于统计结果生成策略 YAML 骨架（详细规则需人工审核后填充）。"""
    trend_dist = stats["success"].get("trend_status_distribution", {})
    top_trend = list(trend_dist.keys())[:3] if trend_dist else []

    strategy = f"""# 反向分析策略 - 基于第三方选股系统历史数据
# 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
# 样本量: {stats['total']} 次选股, 成功率 {stats['success_rate']}%

name: reverse_engineered
display_name: 反向分析选股
description: >
  基于高胜率（{stats['success_rate']}%）第三方选股系统{stats['total']}次历史选股数据，
  通过 LLM 逆向分析提炼出的选股策略。
category: pattern
core_rules: [1, 2, 4]
required_tools:
  - daily_kline
  - trend_analyzer
  - chip_distribution
  - realtime_quote
  - sector_concept
default_active: true
default_router: true
default_priority: 50
market_regimes:
  - trending_up
  - trending_down
  - volatile

instructions: |
  ## 选股规则

  ### 【规则 1 - 趋势要求】
  - 优先选择 MA5 > MA10 > MA20 多头排列的股票
  - 趋势强度不低于 50
  - 避免 MA5 < MA10 的死叉状态

  ### 【规则 2 - 乖离率控制】
  - 股价在 MA5 附近的乖离率控制在合理范围
  - 不追高（乖离率不宜过大）
  - 关注回踩 MA5/MA10 支撑的买点

  ### 【规则 3 - 量能配合】
  - 优先选择缩量回调或量能正常的股票
  - 避免放量下跌
  - 量比结合 5 日均量综合判断

  ### 【规则 4 - MACD 状态】
  - 优先选择 MACD 金叉或多头状态的股票
  - 避免 MACD 死叉

  ### 【规则 5 - 筹码结构】
  - 关注筹码集中度适中的股票
  - 获利比例不宜过高（过高的获利盘容易引发抛压）

  ### 【规则 6 - 市值管理】
  - PE/PB 在合理范围内
  - 换手率适中

  ## 补充说明
  本策略基于 {stats['total']} 次历史选股数据统计分析生成，
  建议在实际使用前先用回测验证，并根据最新数据持续修正参数。
"""
    return strategy


# ============================================================
# 入口
# ============================================================


def analyze(input_path: str, export_strategy: bool = False) -> None:
    """主分析流程。"""
    jsonl_path = Path(input_path)
    records = load_collected(jsonl_path)

    # 1. 统计数据
    logger.info("构建统计摘要...")
    stats = build_statistics(records)

    with open(OUTPUT_STATS, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"统计摘要已保存: {OUTPUT_STATS}")

    # 打印关键统计
    s = stats["success"]
    f_stats = stats.get("fail", {})
    logger.info(f"===== 统计概览 =====")
    logger.info(f"成功组: {s['count']} 只")
    logger.info(f"  趋势分布 top5: {dict(list(s['trend_status_distribution'].items())[:5])}")
    logger.info(f"  量能分布 top5: {dict(list(s['volume_status_distribution'].items())[:5])}")
    logger.info(f"  平均乖离率MA5: {s['avg_features']['bias_ma5']}%")
    logger.info(f"  平均趋势强度: {s['avg_features']['trend_strength']}")
    if f_stats:
        logger.info(f"失败组: {f_stats['count']} 只")
        logger.info(f"  平均乖离率MA5: {f_stats['avg_features']['bias_ma5']}%")
        logger.info(f"  平均趋势强度: {f_stats['avg_features']['trend_strength']}")

    # 2. LLM 规律分析
    logger.info("\n调用 LLM 进行规律分析...")
    report = run_llm_analysis(records, stats)

    with open(OUTPUT_REPORT, "w", encoding="utf-8") as f:
        f.write(report)
    logger.info(f"规律分析报告已保存: {OUTPUT_REPORT}")

    # 也保存一份结构化摘要供后续使用
    summary_data = {
        "stats": stats,
        "report_file": str(OUTPUT_REPORT),
        "analyzed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(OUTPUT_SUMMARY_DATA, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=2)

    # 3. 导出策略 YAML
    if export_strategy:
        strategy = generate_strategy_yaml(stats)
        with open(OUTPUT_STRATEGY, "w", encoding="utf-8") as f:
            f.write(strategy)
        logger.info(f"策略文件已生成: {OUTPUT_STRATEGY}")

    # 打印报告前几行
    print("\n" + "=" * 60)
    print("分析完成！报告摘要:")
    print("=" * 60)
    print(report[:2000])
    print(f"\n... (完整报告见 {OUTPUT_REPORT})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="反向分析 - LLM 规律分析与策略生成")
    parser.add_argument(
        "--input", default=str(DEFAULT_INPUT),
        help=f"采集数据 JSONL 文件路径（默认: {DEFAULT_INPUT}）"
    )
    parser.add_argument(
        "--export-strategy", action="store_true",
        help="同时导出 YAML 策略文件"
    )
    args = parser.parse_args()
    analyze(args.input, export_strategy=args.export_strategy)
