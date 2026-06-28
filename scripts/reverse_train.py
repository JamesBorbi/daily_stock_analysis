#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===================================
反向分析策略 - 训练对比平台
===================================

核心功能：
1. 维护第三方选股历史库（216只 + 持续新增）
2. 每天 14:30 运行反向分析策略，选出 top N
3. 对比策略选出的 vs 第三方选出的 → 验证策略准确度
4. 根据对比结果持续优化策略

用法：
    # 查看第三方历史选股列表
    python scripts/reverse_train.py list

    # 录入第三方新选股（CSV）
    python scripts/reverse_train.py add --csv data/reverse/new_picks.csv

    # 录入第三方新选股（手动输入）
    python scripts/reverse_train.py add --manual

    # 运行反向分析策略扫描（14:30 执行）
    python scripts/reverse_train.py scan --top 5

    # 对比：策略 vs 第三方（今天）
    python scripts/reverse_train.py compare

    # 对比：策略 vs 第三方（指定日期）
    python scripts/reverse_train.py compare --date 20260626

    # 训练优化：用最新数据重新分析并更新策略
    python scripts/reverse_train.py train

    # 查看策略准确度趋势
    python scripts/reverse_train.py accuracy

    # 一键完成：录入 + 训练 + 对比
    python scripts/reverse_train.py daily --csv data/reverse/today_picks.csv
"""

import argparse
import csv
import json
import logging
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("reverse_train")

DATA_DIR = _project_root / "data" / "reverse"
HISTORY_CSV = DATA_DIR / "history.csv"
STRATEGY_YAML = _project_root / "strategies" / "reverse_engineered.yaml"
REPORT_FILE = DATA_DIR / "pattern_report.md"
ACCURACY_FILE = DATA_DIR / "accuracy.jsonl"
COMPARE_LOG = DATA_DIR / "compare_log.jsonl"
BACKUP_DIR = DATA_DIR / "backups"

# ============================================================
# 工具函数
# ============================================================


def _ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _run_script(script: str, *args: str, timeout: int = 600) -> Tuple[int, str, str]:
    script_path = _project_root / script
    cmd = [sys.executable, str(script_path)] + list(args)
    logger.info(f"运行: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.returncode, result.stdout, result.stderr


def _load_history() -> List[Dict]:
    """加载历史选股记录。"""
    _ensure_dirs()
    if not HISTORY_CSV.exists():
        return []
    rows = []
    with open(HISTORY_CSV) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def _load_strategy_picks(date_str: str) -> List[str]:
    """加载某一天反向分析策略选出的股票列表。"""
    records = _load_compare_log()
    for r in records:
        if r.get("date") == date_str:
            return r.get("strategy_picks", [])
    return []


def _load_compare_log() -> List[Dict]:
    """加载对比日志。"""
    _ensure_dirs()
    if not COMPARE_LOG.exists():
        return []
    records = []
    with open(COMPARE_LOG) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _today_str() -> str:
    return datetime.now().strftime("%Y%m%d")


def _is_trading_time() -> bool:
    """判断是否在交易时段（9:30-15:00）。"""
    now = datetime.now()
    if now.weekday() >= 5:  # 周末
        return False
    t = now.hour * 100 + now.minute
    return 930 <= t <= 1500


# ============================================================
# 指令：list - 查看第三方历史选股列表
# ============================================================


def cmd_list(date: Optional[str] = None, top: int = 50):
    """查看第三方历史选股列表。"""
    rows = _load_history()
    if not rows:
        print("\n  ❌ 还没有第三方选股记录\n")
        return

    if date:
        rows = [r for r in rows if r["date"] == date]

    # 统计
    success = sum(1 for r in rows if r.get("success") == "1")
    fail = sum(1 for r in rows if r.get("success") == "0")

    print(f"\n{'='*70}")
    print(f"  第三方选股历史库")
    print(f"{'='*70}")

    # 按日期分组显示
    from collections import defaultdict as dd
    by_date = dd(list)
    for r in rows:
        by_date[r["date"]].append(r)

    sorted_dates = sorted(by_date.keys(), reverse=True)
    total_shown = 0

    for d in sorted_dates:
        if total_shown >= top:
            print(f"  ... 还有 {len(rows) - total_shown} 条记录未显示")
            break

        picks = by_date[d]
        codes = [p["stock_code"] for p in picks]
        success_count = sum(1 for p in picks if p.get("success") == "1")
        fail_count = sum(1 for p in picks if p.get("success") == "0")

        # 显示日期 + 成功率
        if fail_count > 0:
            status = f"✅ {success_count}/{len(picks)} 成功, ❌ {fail_count} 失败"
        else:
            status = f"✅ {success_count}/{len(picks)} 全部成功"

        print(f"\n  📅 {d}  {status}")
        # 显示股票（每行最多6只）
        for i in range(0, len(codes), 6):
            chunk = codes[i:i + 6]
            line = "     "
            for code in chunk:
                idx = picks[[p["stock_code"] for p in picks].index(code)]
                marker = " ⚠️" if idx.get("success") == "0" else ""
                line += f" {code}{marker}"
            print(line)

        total_shown += len(picks)

    print(f"\n  共 {len(rows)} 条记录, {success} 成功, {fail} 失败")
    print(f"  成功率: {success/max(len(rows),1)*100:.2f}%")
    print(f"  时间跨度: {sorted_dates[-1]} ~ {sorted_dates[0]}")
    print()


# ============================================================
# 指令：add - 录入第三方新选股
# ============================================================


def cmd_add(csv_path: Optional[str] = None, manual: bool = False):
    """录入第三方新的选股记录。"""
    _ensure_dirs()

    rows = []

    if csv_path:
        csv_file = Path(csv_path)
        if not csv_file.exists():
            logger.error(f"CSV 文件不存在: {csv_path}")
            return
        with open(csv_file) as f:
            reader = csv.DictReader(f)
            for row in reader:
                date = row.get("date", "").strip()
                code = row.get("stock_code", row.get("code", "")).strip()
                success = row.get("success", "1").strip()
                rows.append((date, code, int(success)))
        logger.info(f"从 CSV 读取 {len(rows)} 条记录")

    elif manual:
        print("\n  手动录入第三方选股")
        print("  " + "-" * 40)
        date_str = input("  选股日期 (YYYYMMDD): ").strip()
        if not date_str:
            logger.error("日期不能为空")
            return

        # 先查今天是否有记录
        existing = _load_history()
        existing_today = [r for r in existing if r["date"] == date_str]
        if existing_today:
            print(f"\n  📋 该日期已有 {len(existing_today)} 条记录:")
            for r in existing_today:
                print(f"    {r['stock_code']}")
            overwrite = input("\n  是否覆盖? (y/n): ").strip().lower()
            if overwrite == "y":
                # 删除该日期的旧记录
                existing = [r for r in existing if r["date"] != date_str]
                logger.info("已清除该日期的旧记录")

        print("\n  请输入股票代码（每行一个，空行结束）:")
        print("  格式: 600519 或 600519,1 (1=成功, 0=失败)")
        while True:
            line = input("  > ").strip()
            if not line:
                break
            parts = line.replace("，", ",").split(",")
            code = parts[0].strip()
            if code.isdigit() and len(code) == 6:
                success = int(parts[1].strip()) if len(parts) > 1 and parts[1].strip().isdigit() else 1
                rows.append((date_str, code, success))
            else:
                print(f"  跳过: {code}（格式不对）")
        logger.info(f"录入 {len(rows)} 条记录")

    else:
        logger.error("请指定 --csv 或 --manual 参数")
        return

    if not rows:
        logger.warning("没有可录入的记录")
        return

    # 追加到 CSV
    existing_set = set()
    if HISTORY_CSV.exists():
        with open(HISTORY_CSV) as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_set.add((row["date"], row["stock_code"]))

    new_rows = [(d, c, s) for d, c, s in rows if (d, c) not in existing_set]
    if not new_rows:
        logger.info("所有记录已存在，无新增")
        return

    file_exists = HISTORY_CSV.exists()
    with open(HISTORY_CSV, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["date", "stock_code", "success"])
        for row in new_rows:
            writer.writerow(row)

    logger.info(f"✅ 新增 {len(new_rows)} 条记录（跳过 {len(rows) - len(new_rows)} 条重复）")

    # 显示最新统计
    total = _load_history()
    success_count = sum(1 for r in total if r.get("success") == "1")
    fail_count = sum(1 for r in total if r.get("success") == "0")
    print(f"\n  当前第三方选股库: {len(total)} 条")
    print(f"  成功率: {success_count}/{len(total)} = {success_count/max(len(total),1)*100:.2f}%")


# ============================================================
# 指令：scan - 运行反向分析策略扫描
# ============================================================


def cmd_scan(top_n: int = 5):
    """运行反向分析策略，扫描全市场选股。"""
    if not _is_trading_time():
        now = datetime.now()
        if now.weekday() >= 5:
            logger.warning("今天是周末，非交易日")
        else:
            logger.warning(f"当前时间 {now.strftime('%H:%M')}，建议 9:30-15:00 交易时段运行")

    logger.info(f"运行反向分析策略扫描（top {top_n}）...")
    print(f"\n  🔄 正在扫描全市场 A 股（约 5000 只）...")

    ret, stdout, stderr = _run_script(
        "scripts/screen_reverse.py",
        "--top", str(top_n),
        "--json",
        timeout=600,
    )

    if ret != 0:
        logger.error(f"扫描失败: {stderr[:200]}")
        return None

    try:
        result = json.loads(stdout)
    except json.JSONDecodeError:
        logger.error(f"输出解析失败: {stdout[:200]}")
        return None

    candidates = result.get("candidates", [])
    print(f"  扫描完成: {result.get('snapshot_count', 0)} 只股票 -> 初筛 {result.get('after_filter_count', 0)} 只")
    print(f"  耗时: {result.get('elapsed_seconds', 0):.1f} 秒")

    if not candidates:
        print("\n  ❌ 未找到符合条件的股票\n")
        return candidates

    print(f"\n  🔥 反向分析策略选出的 Top {len(candidates)}:")
    print(f"  {'='*60}")
    for i, c in enumerate(candidates, 1):
        print(f"\n  #{i} {c['name']} ({c['code']})")
        print(f"     价格: {c['price']:.2f}  评分: {c['score']}/100")
        print(f"     趋势: {c['trend_status']}  强度: {c['trend_strength']}")
        print(f"     理由: {c.get('reason', '')[:80]}")
    print()

    # 保存扫描结果到比较日志
    date_str = _today_str()
    _append_scan_result(date_str, candidates)

    return candidates


def _append_scan_result(date_str: str, candidates: List[Dict]):
    """保存扫描结果，用于后续对比。"""
    _ensure_dirs()
    codes = [c["code"] for c in candidates]

    # 读现有记录
    records = _load_compare_log()
    records = [r for r in records if r.get("date") != date_str]

    new_record = {
        "date": date_str,
        "scan_time": datetime.now().strftime("%H:%M"),
        "strategy_picks": codes,
        "candidates_detail": candidates,
    }
    records.append(new_record)

    # 按日期排序写入
    records.sort(key=lambda x: x["date"])
    with open(COMPARE_LOG, "w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")

    logger.info(f"扫描结果已保存（{len(codes)} 只）")


# ============================================================
# 指令：compare - 对比策略 vs 第三方
# ============================================================


def cmd_compare(date_str: Optional[str] = None):
    """对比策略选出的股票和第三方选出的股票。"""
    date_str = date_str or _today_str()
    rows = _load_history()
    third_party_picks = [r for r in rows if r["date"] == date_str]

    if not third_party_picks:
        print(f"\n  📅 {date_str}: 第三方没有选股记录")
        print(f"  请先用 add 命令录入第三方的选股\n")
        return

    third_party_codes = set(r["stock_code"] for r in third_party_picks)
    third_party_fail = set(r["stock_code"] for r in third_party_picks if r.get("success") == "0")

    # 加载策略扫描结果
    strategy_codes = []
    strategy_detail = []
    compare_records = _load_compare_log()
    scan_record = [r for r in compare_records if r["date"] == date_str]

    if scan_record:
        strategy_codes = scan_record[0].get("strategy_picks", [])
        strategy_detail = scan_record[0].get("candidates_detail", [])
    else:
        logger.info(f"{date_str} 还没有策略扫描结果，正在运行扫描...")
        candidates = cmd_scan(top_n=max(len(third_party_picks), 5))
        if candidates:
            strategy_codes = [c["code"] for c in candidates]
            strategy_detail = candidates

    if not strategy_codes:
        print("\n  ❌ 策略扫描无结果，无法对比\n")
        return

    strategy_set = set(strategy_codes)

    # ========== 对比分析 ==========
    matches = third_party_codes & strategy_set
    only_third = third_party_codes - strategy_set
    only_strategy = strategy_set - third_party_codes

    print(f"\n{'='*70}")
    print(f"  📊 对比报告: {date_str}")
    print(f"{'='*70}")

    # 第三方信息
    third_party_str = ", ".join(sorted(third_party_codes))
    third_party_fail_str = ", ".join(sorted(third_party_fail))
    print(f"\n  📋 第三方选出 ({len(third_party_codes)} 只):")
    print(f"     {third_party_str}")
    if third_party_fail_str:
        print(f"     ⚠️ 失败: {third_party_fail_str}")

    # 策略信息
    strategy_str = ", ".join(strategy_codes)
    print(f"\n  🤖 策略选出 ({len(strategy_codes)} 只):")
    print(f"     {strategy_str}")

    # 匹配结果
    print(f"\n  {'='*50}")
    if matches:
        match_str = ", ".join(sorted(matches))
        print(f"  ✅ 匹配: {len(matches)}/{len(third_party_codes)} 只")
        print(f"     {match_str}")
        match_rate = len(matches) / len(third_party_codes) * 100
        print(f"     匹配率: {match_rate:.1f}%")
    else:
        print(f"  ❌ 完全不匹配")
        match_rate = 0

    if only_third:
        print(f"\n  ⚠️ 第三方有但策略没选 ({len(only_third)} 只):")
        for code in sorted(only_third):
            is_fail = " ⚠️(失败)" if code in third_party_fail else ""
            print(f"     {code}{is_fail}")
            # 显示这只股票的历史分析
            detail = next((c for c in strategy_detail if c["code"] == code), None)
            if detail:
                print(f"       趋势: {detail.get('trend_status','?')} 强度:{detail.get('trend_strength','?')}")

    if only_strategy:
        print(f"\n  🤔 策略有但第三方没选 ({len(only_strategy)} 只):")
        for code in sorted(only_strategy):
            detail = next((c for c in strategy_detail if c["code"] == code), None)
            if detail:
                print(f"     {code} {detail.get('name','')} - {detail.get('reason','')[:60]}")

    # 策略匹配度评级
    print(f"\n  {'='*50}")
    if match_rate >= 80:
        grade = "🟢 优秀"
    elif match_rate >= 50:
        grade = "🟡 良好"
    elif match_rate >= 30:
        grade = "🟠 一般"
    else:
        grade = "🔴 需优化"

    print(f"  评级: {grade} (匹配率 {match_rate:.1f}%)")
    if match_rate < 50:
        print(f"  建议: 运行 train 命令，用最新数据重新训练策略")
    elif match_rate >= 80:
        print(f"  建议: 策略表现良好，可继续观察")
    print()

    # 存储对比结果
    _log_accuracy(date_str, match_rate, len(matches), len(third_party_codes))


def _log_accuracy(date_str: str, match_rate: float, match_count: int, total_count: int):
    """记录准确度日志。"""
    _ensure_dirs()
    records = []
    if ACCURACY_FILE.exists():
        with open(ACCURACY_FILE) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    records = [r for r in records if r["date"] != date_str]
    records.append({
        "date": date_str,
        "match_rate": round(match_rate, 1),
        "match_count": match_count,
        "total_count": total_count,
        "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    records.sort(key=lambda x: x["date"])
    with open(ACCURACY_FILE, "w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ============================================================
# 指令：accuracy - 查看策略准确度趋势
# ============================================================


def cmd_accuracy():
    """查看策略准确度历史趋势。"""
    records = _load_compare_log()
    accuracy_records = []
    if ACCURACY_FILE.exists():
        with open(ACCURACY_FILE) as f:
            for line in f:
                line = line.strip()
                if line:
                    accuracy_records.append(json.loads(line))

    print(f"\n{'='*70}")
    print(f"  策略准确度趋势")
    print(f"{'='*70}")

    if not accuracy_records:
        # 还没有对比记录，用扫描记录估算
        if records:
            print("\n  还没有对比记录。请先运行 compare 命令。\n")
            print(f"  已有扫描记录日期: {[r['date'] for r in records]}")
        else:
            print("\n  还没有任何数据。请先：")
            print("    1. add    录入第三方选股")
            print("    2. scan   运行策略扫描")
            print("    3. compare 对比结果")
        print()
        return

    # 计算累计趋势
    print(f"\n  📈 准确度历史:")
    print(f"  {'日期':<12} {'第三方数量':<12} {'匹配数量':<12} {'匹配率':<10}")
    print(f"  {'-'*46}")

    rates = []
    for r in accuracy_records:
        print(f"  {r['date']:<12} {r['total_count']:<12} {r['match_count']:<12} {r['match_rate']:<10}%")
        rates.append(r['match_rate'])

    if rates:
        avg = sum(rates) / len(rates)
        trend = "上升" if len(rates) > 1 and rates[-1] > rates[0] else "下降" if len(rates) > 1 and rates[-1] < rates[0] else "稳定"
        print(f"\n  平均匹配率: {avg:.1f}%")
        print(f"  趋势: {trend}")

        # 最新评级
        latest = rates[-1]
        if latest >= 80:
            print(f"\n  🟢 当前状态: 优秀（策略可以信任）")
        elif latest >= 50:
            print(f"  🟡 当前状态: 良好（继续观察）")
        elif latest >= 30:
            print(f"  🟠 当前状态: 一般（需要优化）")
        else:
            print(f"  🔴 当前状态: 需优化（马上训练）")
    print()


# ============================================================
# 指令：train - 训练优化策略
# ============================================================


def cmd_train(full: bool = False):
    """用最新数据重新训练并更新策略。"""
    rows = _load_history()
    if not rows:
        logger.error("没有历史选股数据，请先用 add 命令录入")
        return

    print(f"\n{'='*60}")
    print(f"  🏋️  开始策略训练")
    print(f"{'='*60}")
    print(f"  训练数据: {len(rows)} 条选股记录")
    print(f"  时间跨度: {rows[0]['date']} ~ {rows[-1]['date']}")

    # 备份
    _ensure_dirs()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    collected_file = COLLECTED_JSONL if 'COLLECTED_JSONL' in dir() else DATA_DIR / "collected.jsonl"
    if collected_file.exists():
        backup = BACKUP_DIR / f"collected_{timestamp}.jsonl"
        shutil.copy2(collected_file, backup)
        logger.info(f"已备份旧采集数据")

    # Step 1: 数据采集
    print(f"\n  📥 步骤 1/3: 重新采集技术数据...")
    ret, stdout, stderr = _run_script("scripts/reverse_collect.py", "--csv", str(HISTORY_CSV))
    if ret != 0:
        logger.error(f"采集失败: {stderr[:200]}")
        return
    print(f"  ✅ 采集完成")

    # Step 2: 统计分析
    print(f"\n  📊 步骤 2/3: 统计分析...")
    ret, stdout, stderr = _run_script("scripts/generate_report.py")
    if ret != 0:
        logger.error(f"分析失败: {stderr[:200]}")
        return

    # 显示更新后的关键指标
    stats_file = DATA_DIR / "stats.json"
    if stats_file.exists():
        with open(stats_file) as f:
            stats = json.load(f)
        s = stats["success"]
        f_stats = stats.get("fail", {})
        print(f"\n  更新后的关键指标:")
        print(f"    成功率: {stats['success_rate']}%")
        print(f"    成功组趋势强度: {s['avg_features']['trend_strength']}")
        print(f"    成功组乖离率MA5: {s['avg_features']['bias_ma5']}%")
        if f_stats:
            print(f"    失败组趋势强度: {f_stats['avg_features']['trend_strength']}")
            print(f"    失败组乖离率MA5: {f_stats['avg_features']['bias_ma5']}%")

    # Step 3: 部署策略
    print(f"\n  📝 步骤 3/3: 更新策略文件...")
    strategy_src = DATA_DIR / "strategy.yaml"
    if strategy_src.exists():
        shutil.copy2(strategy_src, STRATEGY_YAML)
        print(f"  ✅ 策略已更新: {STRATEGY_YAML}")
    else:
        logger.warning("策略文件未生成")
        return

    print(f"\n{'='*60}")
    print(f"  ✅ 训练完成！")
    print(f"{'='*60}")
    print(f"\n  建议立即运行 compare 命令验证更新效果\n")


# ============================================================
# 指令：daily - 每日一键流程
# ============================================================


def cmd_daily(csv_path: Optional[str] = None):
    """每日流程：录入第三方选股 → 训练 → 扫描 → 对比。"""
    print(f"\n{'='*60}")
    print(f"  📅 每日策略流程: {_today_str()}")
    print(f"{'='*60}")

    if csv_path:
        print(f"\n  1/4 录入第三方选股...")
        cmd_add(csv_path=csv_path)
    else:
        print(f"\n  1/4 跳过录入（未提供 --csv）")

    print(f"\n  2/4 训练优化策略...")
    cmd_train()

    print(f"\n  3/4 运行策略扫描...")
    cmd_scan(top_n=5)

    print(f"\n  4/4 对比结果...")
    cmd_compare()

    print(f"\n  ✅ 每日流程完成！")
    print(f"  下次操作建议:")
    print(f"    1. 拿到第三方结果后，保存为 CSV")
    print(f"    2. 运行: python scripts/reverse_train.py daily --csv new_picks.csv")
    print(f"    3. 查看对比报告，判断策略是否需要继续优化")


# ============================================================
# 入口
# ============================================================


def main():
    parser = argparse.ArgumentParser(description="反向分析策略 - 训练对比平台")
    sub = parser.add_subparsers(dest="command", help="可用命令")

    # list
    p_list = sub.add_parser("list", help="查看第三方历史选股")
    p_list.add_argument("--date", help="指定日期（YYYYMMDD）")
    p_list.add_argument("--top", type=int, default=50, help="显示前 N 条（默认 50）")

    # add
    p_add = sub.add_parser("add", help="录入第三方新选股")
    p_add.add_argument("--csv", help="CSV 文件路径")
    p_add.add_argument("--manual", action="store_true", help="手动输入")

    # scan
    p_scan = sub.add_parser("scan", help="运行策略扫描全市场")
    p_scan.add_argument("--top", type=int, default=5, help="选几只（默认 5）")

    # compare
    p_cmp = sub.add_parser("compare", help="对比策略 vs 第三方")
    p_cmp.add_argument("--date", help="对比日期（默认今天）")

    # train
    p_train = sub.add_parser("train", help="训练优化策略")
    p_train.add_argument("--full", action="store_true", help="全量训练")

    # accuracy
    sub.add_parser("accuracy", help="查看策略准确度趋势")

    # daily
    p_daily = sub.add_parser("daily", help="每日一键流程")
    p_daily.add_argument("--csv", help="今日第三方选股 CSV")

    args = parser.parse_args()

    if args.command == "list":
        cmd_list(date=args.date, top=args.top)
    elif args.command == "add":
        cmd_add(csv_path=args.csv, manual=args.manual)
    elif args.command == "scan":
        cmd_scan(top_n=args.top)
    elif args.command == "compare":
        cmd_compare(date_str=args.date)
    elif args.command == "train":
        cmd_train(full=args.full)
    elif args.command == "accuracy":
        cmd_accuracy()
    elif args.command == "daily":
        cmd_daily(csv_path=args.csv)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
