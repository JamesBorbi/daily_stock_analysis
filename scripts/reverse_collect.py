#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===================================
反向分析工具 - 历史选股数据采集
===================================

用途：根据用户提供的第三方选股系统历史记录，批量采集每只股票被选中时的技术数据，
     用于后续规律分析。

用法：
    1. 准备 CSV 文件（放在 data/reverse/ 目录下）：
       例如 data/reverse/history.csv:
           date,stock_code,success
           20260601,600519,1
           20260601,300750,1
           20260602,000858,1
           20260603,002415,0
           ...
       (success: 1=第二天盈利, 0=亏损)

    2. 运行采集：
       python scripts/reverse_collect.py
       python scripts/reverse_collect.py --csv data/reverse/history.csv

    3. 输出：
       - data/reverse/collected.jsonl   (每只股票的全量特征数据)
       - data/reverse/summary.json      (汇总统计)
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

# 将项目根目录加入 sys.path
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from data_provider import DataFetcherManager
from data_provider.base import normalize_stock_code
from data_provider.realtime_types import ChipDistribution
from src.stock_analyzer import StockTrendAnalyzer, TrendAnalysisResult, TrendStatus
from src.config import get_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("reverse_collect")

# ============================================================
# 配置
# ============================================================
DATA_DIR = Path("data") / "reverse"
DEFAULT_CSV = DATA_DIR / "history.csv"
OUTPUT_JSONL = DATA_DIR / "collected.jsonl"
OUTPUT_SUMMARY = DATA_DIR / "summary.json"

# 每个股票拉取历史 K 线的天数（选股日前 N 天）
HISTORY_DAYS = 60

# ============================================================
# 核心采集逻辑
# ============================================================


def load_history(csv_path: Path) -> pd.DataFrame:
    """加载历史选股记录 CSV。"""
    if not csv_path.exists():
        logger.error(f"找不到 CSV 文件: {csv_path}")
        logger.info(f"请先创建 {csv_path}，格式: date,stock_code,success")
        sys.exit(1)

    df = pd.read_csv(csv_path, dtype={"stock_code": str})
    df["date"] = pd.to_datetime(df["date"].astype(str), format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["date"])
    df["date"] = df["date"].dt.strftime("%Y%m%d")
    df["success"] = df["success"].astype(int)

    logger.info(f"加载历史记录: {len(df)} 条, "
                f"成功: {df['success'].sum()}, "
                f"失败: {(1 - df['success']).sum()}")
    return df


def collect_stock_features(
    fetcher: DataFetcherManager,
    stock_code: str,
    pick_date: str,
    success: int,
) -> Optional[Dict]:
    """
    采集单只股票在被选中日期的全量特征。

    Args:
        fetcher: 数据获取管理器
        stock_code: 股票代码（如 600519）
        pick_date: 选中日期（YYYYMMDD）
        success: 是否成功 (1/0)

    Returns:
        特征字典，或 None（采集失败时）
    """
    try:
        # 规范化代码
        code = normalize_stock_code(stock_code)

        # 计算日期范围：选股日前 HISTORY_DAYS 天到选股日
        dt = datetime.strptime(pick_date, "%Y%m%d")
        start = (dt - timedelta(days=HISTORY_DAYS)).strftime("%Y%m%d")

        # 1. 获取日 K 线数据
        df, source = fetcher.get_daily_data(code, start_date=start, end_date=pick_date)
        if df is None or df.empty:
            logger.warning(f"  [{pick_date}] {code}: 无 K 线数据（{source}）")
            return None

        # 确保日期列
        if "date" not in df.columns:
            df["date"] = df.index

        # 2. 运行趋势技术分析
        analyzer = StockTrendAnalyzer()
        trend_result: TrendAnalysisResult = analyzer.analyze(df, code)

        # 3. 获取实时行情（盘后拉取，作为参考）
        quote = None
        try:
            quote = fetcher.get_realtime_quote(code)
        except Exception:
            pass

        # 4. 获取筹码分布
        chip = None
        try:
            chip = fetcher.get_chip_distribution(code)
        except Exception:
            pass

        # 5. 构建特征字典
        features = {
            # === 基础信息 ===
            "code": code,
            "pick_date": pick_date,
            "success": success,
            "data_source": source,
            "latest_close": trend_result.current_price,
            "latest_volume": float(df.iloc[-1]["volume"]) if "volume" in df.columns else 0,
            "latest_amount": float(df.iloc[-1].get("amount", 0)),

            # === 趋势特征 ===
            "trend_status": trend_result.trend_status.value,
            "trend_strength": trend_result.trend_strength,
            "ma5": trend_result.ma5,
            "ma10": trend_result.ma10,
            "ma20": trend_result.ma20,
            "ma60": trend_result.ma60,
            "bias_ma5": trend_result.bias_ma5,
            "bias_ma10": trend_result.bias_ma10,
            "bias_ma20": trend_result.bias_ma20,

            # === 量能特征 ===
            "volume_status": trend_result.volume_status.value,
            "volume_ratio_5d": trend_result.volume_ratio_5d,

            # === MACD 特征 ===
            "macd_status": trend_result.macd_status.value,
            "macd_dif": trend_result.macd_dif,
            "macd_dea": trend_result.macd_dea,
            "macd_bar": trend_result.macd_bar,

            # === RSI 特征 ===
            "rsi_status": trend_result.rsi_status.value,
            "rsi_6": trend_result.rsi_6,
            "rsi_12": trend_result.rsi_12,

            # === 支撑压力 ===
            "support_ma5": trend_result.support_ma5,
            "support_ma10": trend_result.support_ma10,

            # === 筹码特征 ===
            "profit_ratio": chip.profit_ratio if chip else None,
            "concentration_90": chip.concentration_90 if chip else None,
            "concentration_70": chip.concentration_70 if chip else None,
            "avg_cost": chip.avg_cost if chip else None,

            # === 实时行情（盘后参考） ===
            "pe_ttm": float(quote.pe_ttm) if quote and hasattr(quote, 'pe_ttm') and quote.pe_ttm else None,
            "pb": float(quote.pb) if quote and hasattr(quote, 'pb') and quote.pb else None,
            "total_mv": float(quote.total_mv) if quote and hasattr(quote, 'total_mv') and quote.total_mv else None,
            "circ_mv": float(quote.circ_mv) if quote and hasattr(quote, 'circ_mv') and quote.circ_mv else None,
            "turnover_ratio": float(quote.turnover_ratio) if quote and hasattr(quote, 'turnover_ratio') and quote.turnover_ratio else None,
            "volume_ratio": float(quote.volume_ratio) if quote and hasattr(quote, 'volume_ratio') and quote.volume_ratio else None,
        }

        return features

    except Exception as e:
        logger.warning(f"  [{pick_date}] {stock_code}: 采集失败 - {e}")
        return None


def collect_all(history_csv: str) -> None:
    """主采集流程。"""
    csv_path = Path(history_csv)
    records = load_history(csv_path)

    # 创建输出目录
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 初始化数据获取器
    fetcher = DataFetcherManager()
    logger.info("数据获取管理器已初始化")

    # 按日期分组处理
    grouped = records.groupby("date")
    total = len(records)
    collected = []
    success_count = 0
    fail_count = 0

    logger.info(f"开始采集 {total} 条记录...")

    for pick_date, group in grouped:
        stocks = group.to_dict("records")
        logger.info(f"\n=== {pick_date}: 采集 {len(stocks)} 只股票 ===")

        for i, stock in enumerate(stocks, 1):
            code = stock["stock_code"]
            success = stock["success"]
            logger.info(f"  [{i}/{len(stocks)}] {code}...")

            features = collect_stock_features(
                fetcher, code, pick_date, success
            )
            if features:
                collected.append(features)
                success_count += 1
                # 逐条写入 JSONL（防止中途失败丢失数据）
                with open(OUTPUT_JSONL, "a", encoding="utf-8") as f:
                    f.write(json.dumps(features, ensure_ascii=False, default=str) + "\n")
            else:
                fail_count += 1

        logger.info(f"  -> 当前进度: {success_count + fail_count}/{total}, "
                     f"成功: {success_count}, 失败: {fail_count}")

    # 输出汇总
    summary = {
        "total_records": total,
        "collected": success_count,
        "failed": fail_count,
        "success_rate": round(success_count / total * 100, 2) if total > 0 else 0,
        "output_file": str(OUTPUT_JSONL),
        "collection_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(OUTPUT_SUMMARY, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    logger.info(f"\n========== 采集完成 ==========")
    logger.info(f"  总记录: {total}")
    logger.info(f"  采集成功: {success_count}")
    logger.info(f"  采集失败: {fail_count}")
    logger.info(f"  成功率: {summary['success_rate']}%")
    logger.info(f"  数据文件: {OUTPUT_JSONL}")
    logger.info(f"  汇总文件: {OUTPUT_SUMMARY}")


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="反向分析 - 历史选股数据采集")
    parser.add_argument(
        "--csv", default=str(DEFAULT_CSV),
        help=f"历史选股 CSV 文件路径（默认: {DEFAULT_CSV}）"
    )
    parser.add_argument(
        "--days", type=int, default=HISTORY_DAYS,
        help=f"拉取历史 K 线天数（默认: {HISTORY_DAYS}）"
    )
    args = parser.parse_args()
    collect_all(args.csv)
