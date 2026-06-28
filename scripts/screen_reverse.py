#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===================================
反向分析选股 - 全市场扫描引擎
===================================

用途：扫描全市场 A 股，应用反向分析策略规则，选出适合尾盘买入、隔日卖出的股票。

两种使用方式：
    1. 命令行：python scripts/screen_reverse.py --top 3
    2. 作为 API 被 AlphaSift 流程调用返回候选列表

输出：top N 候选股票，含详细分析理由
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from data_provider import DataFetcherManager
from data_provider.base import normalize_stock_code, is_bse_code
from src.stock_analyzer import StockTrendAnalyzer, TrendStatus, VolumeStatus, MACDStatus
from src.stock_analyzer import RSIStatus

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("screen_reverse")

# ============================================================
# 策略规则配置（基于 215 次历史选股数据分析）
# ============================================================

# 规则 1: 趋势强度硬门槛
MIN_TREND_STRENGTH = 30       # 成功组均值 44，失败组均值 21
MAX_TREND_STRENGTH = 70       # 太强可能追高

# 规则 2: 价格位置要求
MIN_BIAS_MA5 = -3.0           # 不要低于 MA5 太多
MAX_BIAS_MA5 = 5.0            # 不要追高太多

# 规则 3: 量能要求
MIN_VOLUME_RATIO = 0.5
MAX_VOLUME_RATIO = 2.5

# 规则 4: MACD 规避
AVOID_MACD_DEATH_CROSS = True

# 规则 5: 排除 ST
EXCLUDE_ST = True

# 规则 6: 排除极端低价股
MIN_PRICE = 3.0

# 扫描参数
ANALYSIS_DAYS = 60            # 分析使用的 K 线天数
MAX_CANDIDATES_FOR_DEEP = 100  # 先快速筛选 N 只，再对它们做深度分析
TARGET_TOP_N = 3               # 最终输出几只


class ReverseScreenEngine:
    """反向分析选股引擎。"""

    def __init__(self, config: Optional[Dict] = None):
        self.fetcher = DataFetcherManager()
        self.config = config or {}
        self.top_n = self.config.get("top_n", TARGET_TOP_N)
        self.analyzer = StockTrendAnalyzer()

    def screen(self, market: str = "cn", max_results: int = 3) -> Dict[str, Any]:
        """执行全市场扫描选股。"""
        logger.info(f"开始全市场扫描 (market={market}, max_results={max_results})")

        start_time = time.time()

        # Step 1: 获取全市场实时行情（快速筛选）
        all_quotes, snapshot_source = self._get_all_quotes()
        if not all_quotes:
            return {
                "enabled": True,
                "candidates": [],
                "error": "无法获取全市场行情数据",
                "snapshot_count": 0,
            }
        snapshot_count = len(all_quotes)
        logger.info(f"  全市场快照: {snapshot_count} 只股票, source={snapshot_source}")

        # Step 2: 快速初筛
        prelim = self._quick_filter(all_quotes)
        logger.info(f"  快速初筛后: {len(prelim)} 只")

        # Step 3: 对初筛候选做深度技术分析
        deep_analyzed = self._deep_analysis(prelim)
        logger.info(f"  深度分析完成: {len(deep_analyzed)} 只")

        # Step 4: 评分和排名
        ranked = self._rank_candidates(deep_analyzed)
        logger.info(f"  排名完成: {len(ranked)} 只")

        # Step 5: 取 top N
        selected = ranked[:max_results]
        elapsed = time.time() - start_time

        result = {
            "enabled": True,
            "strategy": "reverse_engineered",
            "market": market,
            "candidates": selected,
            "candidate_count": len(selected),
            "snapshot_count": snapshot_count,
            "snapshot_source": snapshot_source,
            "after_filter_count": len(deep_analyzed),
            "llm_ranked": False,
            "elapsed_seconds": round(elapsed, 1),
        }
        return result

    def _get_all_quotes(self) -> Tuple[List[Dict], str]:
        """获取全市场股票实时行情。

        通过 efinance 的批量行情接口获取所有 A 股数据。
        包含：代码、名称、价格、涨跌幅、量比、换手率、PE、PB、总市值、流通市值等。
        """
        try:
            import efinance as ef
            import pandas as pd

            logger.info("[API调用] ef.stock.get_realtime_quotes() 获取全市场行情...")
            df = ef.stock.get_realtime_quotes()
            if df is None or df.empty:
                logger.warning("全市场行情数据为空")
                return [], "efinance"

            logger.info(f"  返回 {len(df)} 只股票")
            quotes = []
            for _, row in df.iterrows():
                try:
                    code = str(row.get("股票代码", "")).strip()
                    name = str(row.get("股票名称", "")).strip()
                    price = float(row.get("最新价", 0) or row.get("最新价", 0))
                    change_pct = float(row.get("涨跌幅", 0) or 0)
                    volume_ratio = float(row.get("量比", 0) or 0)
                    turnover = float(row.get("换手率", 0) or 0)
                    total_mv = float(row.get("总市值", 0) or 0)
                    pe = float(row.get("市盈率-动态", 0) or 0)

                    quotes.append({
                        "code": code,
                        "name": name,
                        "price": price,
                        "change_pct": change_pct,
                        "volume_ratio": volume_ratio,
                        "turnover": turnover,
                        "total_mv": total_mv,
                        "pe": pe,
                    })
                except (ValueError, KeyError, TypeError):
                    continue

            return quotes, "efinance"
        except ImportError:
            logger.error("efinance 未安装")
            return [], "efinance"
        except Exception as e:
            logger.error(f"获取全市场行情失败: {e}")
            return [], "efinance"

    def _quick_filter(self, quotes: List[Dict]) -> List[Dict]:
        """快速初筛：排除明显不符合策略条件的股票。"""
        filtered = []
        for q in quotes:
            try:
                code = q["code"]

                # 排除非 A 股代码（6位纯数字）
                if not (code.isdigit() and len(code) == 6):
                    continue

                # 排除北交所
                if is_bse_code(code):
                    continue

                # 排除 ST 股
                if EXCLUDE_ST and ("ST" in q["name"] or "*ST" in q["name"]):
                    continue

                # 排除极端低价股
                if q["price"] < MIN_PRICE:
                    continue

                # 排除量比过低/过高的
                if q["volume_ratio"] < MIN_VOLUME_RATIO or q["volume_ratio"] > MAX_VOLUME_RATIO:
                    continue

                # 排除当天涨停的（无法买入）
                if q["change_pct"] >= 9.5:
                    continue

                # 排除 PE 过高的亏损股
                if q["pe"] > 200:
                    continue

                # ETF 排除（代码以 15/16 开头且名称含 ETF）
                if "ETF" in q["name"].upper():
                    continue

                filtered.append(q)
            except Exception:
                continue

        # 按量比排序，取活跃度最高的前 N 只做深度分析
        filtered.sort(key=lambda x: -x["volume_ratio"])
        return filtered[:MAX_CANDIDATES_FOR_DEEP * 2]

    def _deep_analysis(self, candidates: List[Dict]) -> List[Dict]:
        """对候选股票做深度技术分析。"""
        results = []
        total = len(candidates)

        for i, c in enumerate(candidates):
            code = c["code"]
            try:
                logger.debug(f"  深度分析 [{i+1}/{total}] {code} {c['name']}...")

                # 获取日 K 线数据
                end = datetime.now().strftime("%Y%m%d")
                start = (datetime.now() - timedelta(days=ANALYSIS_DAYS)).strftime("%Y%m%d")

                df, source = self.fetcher.get_daily_data(code, start_date=start, end_date=end)
                if df is None or df.empty or len(df) < 20:
                    continue

                # 运行趋势分析
                trend = self.analyzer.analyze(df, code)

                # 应用策略规则过滤
                reasons = []
                score = 50  # 基础分

                # NaN defense
                ts = trend.trend_strength if trend.trend_strength == trend.trend_strength else 0
                b5 = trend.bias_ma5 if trend.bias_ma5 == trend.bias_ma5 else 0
                r6 = trend.rsi_6 if trend.rsi_6 == trend.rsi_6 else 50

                # 规则 1: 趋势强度
                if ts < MIN_TREND_STRENGTH:
                    continue
                if ts >= 44:  # 成功组均值
                    score += 15
                    reasons.append(f"趋势强度 {ts:.0f}（超过成功组均值44）")
                elif ts >= 30:
                    score += 8
                    reasons.append(f"趋势强度 {ts:.0f}（达标）")

                # 规则 2: 价格位置
                if b5 > abs(MIN_BIAS_MA5) and b5 > 0:
                    score -= 10
                    reasons.append(f"乖离率偏高 {b5:.1f}%")
                    continue  # 不追高
                if b5 < -3:  # 低于 MA5 太多
                    score -= 15
                    reasons.append(f"价格低于MA5 {b5:.1f}%")
                    continue  # 太低也不去
                if -1 <= b5 <= 2:
                    score += 12
                    reasons.append(f"价格贴近MA5（乖离率 {b5:.1f}%）✓")
                else:
                    score += 5
                    reasons.append(f"价格在MA5附近（乖离率 {b5:.1f}%）")

                # 规则 3: 量能正常
                if trend.volume_status == VolumeStatus.NORMAL:
                    score += 8
                    reasons.append("量能正常 ✓")
                elif trend.volume_status == VolumeStatus.SHRINK_VOLUME_DOWN:
                    score += 10
                    reasons.append("缩量回调（优质买点）✓")
                elif trend.volume_status == VolumeStatus.HEAVY_VOLUME_UP:
                    score += 3
                    reasons.append("放量上涨中")
                elif trend.volume_status == VolumeStatus.HEAVY_VOLUME_DOWN:
                    continue  # 放量下跌直接排除

                # 规则 4: MACD 状态
                if trend.macd_status == MACDStatus.DEATH_CROSS:
                    if AVOID_MACD_DEATH_CROSS:
                        continue
                    score -= 10
                elif trend.macd_status == MACDStatus.GOLDEN_CROSS:
                    score += 15
                    reasons.append("MACD 金叉 ✓")
                elif trend.macd_status == MACDStatus.GOLDEN_CROSS_ZERO:
                    score += 20
                    reasons.append("MACD 零轴上金叉（强势信号）✓✓")
                elif trend.macd_status == MACDStatus.BULLISH:
                    score += 8
                    reasons.append("MACD 多头 ✓")

                # RSI 参考
                if r6 < 30:
                    score += 10
                    reasons.append(f"RSI6={r6:.0f}（超卖区反弹机会）")
                elif 30 <= r6 <= 60:
                    score += 5
                    reasons.append(f"RSI6={r6:.0f}（中性偏强）")

                # 均线支撑
                if trend.support_ma5:
                    score += 8
                    reasons.append("MA5 构成支撑 ✓")
                if trend.support_ma10:
                    score += 5
                    reasons.append("MA10 构成支撑 ✓")

                # 基本判断
                buy_signal_text = {
                    "强烈买入": "强烈买入信号",
                    "买入": "买入信号",
                    "持有": "持有信号",
                    "观望": "观望",
                }.get(trend.buy_signal.value, trend.buy_signal.value)

                results.append({
                    "code": code,
                    "name": c["name"],
                    "price": c["price"],
                    "change_pct": c["change_pct"],
                    "volume_ratio": c["volume_ratio"],
                    "score": score,
                    "trend_status": trend.trend_status.value if trend.trend_status else "",
                    "trend_strength": round(ts, 1),
                    "bias_ma5": round(b5, 2),
                    "bias_ma10": round(trend.bias_ma10 if trend.bias_ma10 == trend.bias_ma10 else 0, 2),
                    "volume_status": trend.volume_status.value if trend.volume_status else "",
                    "macd_status": trend.macd_status.value if trend.macd_status else "",
                    "rsi_6": round(r6, 1),
                    "support_ma5": trend.support_ma5,
                    "support_ma10": trend.support_ma10,
                    "buy_signal": trend.buy_signal.value if trend.buy_signal else "",
                    "signal_score": trend.signal_score,
                    "reason": "；".join(reasons[:5]),
                    "ma_alignment": trend.ma_alignment,
                })

            except Exception as e:
                logger.debug(f"  深度分析 {code} 失败: {e}")
                continue

        return results

    def _rank_candidates(self, candidates: List[Dict]) -> List[Dict]:
        """根据评分排名。"""
        # 按评分降序排列
        ranked = sorted(candidates, key=lambda x: -x["score"])

        # 添加排名
        for i, c in enumerate(ranked):
            c["rank"] = i + 1

        return ranked


def screen_stocks(top_n: int = 3, market: str = "cn") -> Dict[str, Any]:
    """便捷函数：执行全市场反向分析选股。"""
    engine = ReverseScreenEngine({"top_n": top_n})
    result = engine.screen(market=market, max_results=top_n)
    return result


def print_results(result: Dict[str, Any]) -> None:
    """打印选股结果到控制台。"""
    print("\n" + "=" * 70)
    print("  【反向分析选股】全市场扫描结果")
    print("=" * 70)
    print(f"  扫描股票: {result.get('snapshot_count', 0)} 只")
    print(f"  初筛候选: {result.get('after_filter_count', 0)} 只")
    print(f"  耗时: {result.get('elapsed_seconds', 0):.1f} 秒")
    print(f"  策略: {result.get('strategy', '')}")
    print("-" * 70)

    candidates = result.get("candidates", [])
    if not candidates:
        print("  ❌ 未找到符合条件的股票。")
        print("=" * 70)
        return

    for i, c in enumerate(candidates, 1):
        print(f"\n  🔥 TOP {i}: {c['name']} ({c['code']})")
        print(f"    价格: {c['price']:.2f}  涨跌幅: {c['change_pct']:+.2f}%")
        print(f"    评分: {c['score']}/100")
        print(f"    趋势: {c['trend_status']} (强度: {c['trend_strength']})")
        print(f"    乖离率: MA5={c['bias_ma5']:+.2f}%, MA10={c['bias_ma10']:+.2f}%")
        print(f"    MACD: {c['macd_status']}  RSI6: {c['rsi_6']}")
        print(f"    量能: {c['volume_status']}")
        print(f"    选股理由: {c['reason']}")
        print(f"    买卖信号: {c['buy_signal']} (综合: {c['signal_score']}/100)")

    print("\n" + "=" * 70)
    print("  📌 尾盘买入建议")
    for i, c in enumerate(candidates[:3], 1):
        print(f"    {i}. {c['name']} ({c['code']}) - {c['reason'][:60]}...")
    print("  ⚡ 隔日卖出策略：次日开盘观察，高开及时止盈")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="反向分析选股 - 全市场扫描")
    parser.add_argument("--top", type=int, default=3, help="返回前几只（默认 3）")
    parser.add_argument("--market", default="cn", help="市场（仅支持 cn）")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出（供 API 调用）")
    args = parser.parse_args()

    result = screen_stocks(top_n=args.top, market=args.market)

    if args.json:
        # JSON mode: only output JSON to stdout for API consumption
        json.dump(result, sys.stdout, ensure_ascii=False, default=str)
    else:
        print_results(result)
        # 输出 JSON 到文件
        output_path = Path("data") / "reverse" / "screen_result.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        print(f"完整结果已保存: {output_path}")
