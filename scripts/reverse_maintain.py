#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===================================
反向分析策略维护工具
===================================

用途：管理第三方选股系统的历史数据，定期更新策略。

用法：
    # 查看当前状态
    python scripts/reverse_maintain.py status

    # 录入新的选股记录（CSV 文件）
    python scripts/reverse_maintain.py add --csv data/reverse/new_picks.csv

    # 录入截图（自动识别股票代码）
    python scripts/reverse_maintain.py add --image screenshots/20260626.png

    # 重新采集数据并分析（更新策略）
    python scripts/reverse_maintain.py update

    # 一键完成：录入 + 采集 + 分析 + 更新策略
    python scripts/reverse_maintain.py run --csv data/reverse/new_picks.csv

    # 查看历史选股统计
    python scripts/reverse_maintain.py stats
"""

import argparse
import csv
import json
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("reverse_maintain")

DATA_DIR = _project_root / "data" / "reverse"
HISTORY_CSV = DATA_DIR / "history.csv"
COLLECTED_JSONL = DATA_DIR / "collected.jsonl"
BACKUP_DIR = DATA_DIR / "backups"


def _ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _run_script(script: str, *args: str) -> Tuple[int, str]:
    """运行项目中的 Python 脚本。"""
    script_path = _project_root / script
    cmd = [sys.executable, str(script_path)] + list(args)
    logger.info(f"运行: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.stdout:
        print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
    if result.stderr:
        print(result.stderr[-1000:] if len(result.stderr) > 1000 else result.stderr)
    return result.returncode, result.stdout


# ============================================================
# 指令实现
# ============================================================


def cmd_status():
    """查看当前状态。"""
    _ensure_dirs()

    print(f"\n{'='*60}")
    print(f"  反向分析策略 - 状态报告")
    print(f"{'='*60}")

    # 历史记录
    if HISTORY_CSV.exists():
        with open(HISTORY_CSV) as f:
            lines = [l for l in f if l.strip() and not l.startswith("date,")]
        success = sum(1 for l in lines if l.strip().endswith(",1"))
        fail = sum(1 for l in lines if l.strip().endswith(",0"))
        print(f"\n  历史选股记录: {len(lines)} 条")
        print(f"    成功: {success} 次")
        print(f"    失败: {fail} 次")
        print(f"    成功率: {success/max(len(lines),1)*100:.2f}%")
    else:
        print(f"\n  历史选股记录: 无")

    # 采集数据
    if COLLECTED_JSONL.exists():
        with open(COLLECTED_JSONL) as f:
            count = sum(1 for _ in f)
        print(f"  已采集特征数据: {count} 条")
    else:
        print(f"  已采集特征数据: 无")

    # 策略文件
    strategy_file = _project_root / "strategies" / "reverse_engineered.yaml"
    if strategy_file.exists():
        mtime = datetime.fromtimestamp(strategy_file.stat().st_mtime)
        print(f"  策略文件: 存在（更新于 {mtime.strftime('%Y-%m-%d %H:%M')}）")
    else:
        print(f"  策略文件: 无")

    # 最近选股
    if HISTORY_CSV.exists():
        with open(HISTORY_CSV) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        if rows:
            dates = sorted(set(r["date"] for r in rows), reverse=True)
            print(f"\n  最近选股日期: {dates[:5]}")
            print(f"  最早: {dates[-1]}, 最晚: {dates[0]}")

    print()


def cmd_add(csv_path: Optional[str], image_path: Optional[str]):
    """录入新的选股记录。"""
    _ensure_dirs()

    if image_path:
        # 截图模式：用 image_stock_extractor 识别
        logger.info("截图识别模式: 使用 Vision LLM 提取股票代码...")
        try:
            from src.services.image_stock_extractor import extract_stock_codes_from_image

            img_path = Path(image_path)
            if not img_path.exists():
                logger.error(f"截图文件不存在: {image_path}")
                return

            with open(img_path, "rb") as f:
                img_bytes = f.read()

            mime = "image/png"
            if img_path.suffix.lower() in (".jpg", ".jpeg"):
                mime = "image/jpeg"
            elif img_path.suffix.lower() == ".webp":
                mime = "image/webp"

            items, raw = extract_stock_codes_from_image(img_bytes, mime)
            if not items:
                logger.error("截图识别失败，未提取到股票代码")
                return

            logger.info(f"截图识别到 {len(items)} 只股票: {[i[0] for i in items]}")

            # 需要用户输入日期
            date_str = input("请输入选股日期 (YYYYMMDD): ").strip()
            if not date_str:
                logger.error("日期不能为空")
                return

            rows = [(date_str, item[0], 1) for item in items]  # 默认标记为成功
            _append_to_history(rows)
            logger.info(f"已录入 {len(rows)} 条记录（默认标记为成功，请手动修改失败记录）")

        except ImportError as e:
            logger.error(f"截图识别依赖缺失: {e}")
            logger.info("请先用 pip install litellm 安装")
            return

    elif csv_path:
        # CSV 模式：直接导入
        csv_file = Path(csv_path)
        if not csv_file.exists():
            logger.error(f"CSV 文件不存在: {csv_path}")
            return

        rows = []
        with open(csv_file) as f:
            reader = csv.DictReader(f)
            for row in reader:
                date = row.get("date", "").strip()
                code = row.get("stock_code", row.get("code", "")).strip()
                success = row.get("success", "1").strip()
                rows.append((date, code, int(success)))

        if not rows:
            logger.error("CSV 文件为空或格式不正确")
            return

        _append_to_history(rows)
        logger.info(f"已录入 {len(rows)} 条选股记录")
        cmd_status()

    else:
        # 手动输入模式
        logger.info("手动输入模式（输入空行结束）:")
        rows = []
        date_str = input("选股日期 (YYYYMMDD): ").strip()
        print("请输入股票代码（每行一个，空行结束）:")
        while True:
            code = input("  > ").strip()
            if not code:
                break
            if code.isdigit() and len(code) == 6:
                rows.append((date_str, code, 1))
            else:
                print(f"  跳过: {code}（不是有效的6位A股代码）")

        if rows:
            _append_to_history(rows)
            logger.info(f"已录入 {len(rows)} 条记录")
            cmd_status()
        else:
            logger.warning("未录入任何记录")


def _append_to_history(rows: List[Tuple[str, str, int]]):
    """追加记录到 history.csv，自动去重。"""
    _ensure_dirs()

    existing = set()
    if HISTORY_CSV.exists():
        with open(HISTORY_CSV) as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing.add((row["date"], row["stock_code"]))

    new_rows = [(d, c, s) for d, c, s in rows if (d, c) not in existing]
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

    logger.info(f"新增 {len(new_rows)} 条记录（跳过 {len(rows) - len(new_rows)} 条重复）")


def cmd_update():
    """重新采集数据 + 分析 + 更新策略。"""
    _ensure_dirs()

    if not HISTORY_CSV.exists():
        logger.error("没有历史选股数据，请先用 add 命令录入")
        return

    # 备份旧数据
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if COLLECTED_JSONL.exists():
        backup = BACKUP_DIR / f"collected_{timestamp}.jsonl"
        COLLECTED_JSONL.rename(backup)
        logger.info(f"已备份旧数据: {backup}")

    # 步骤 1: 数据采集
    logger.info("\n" + "=" * 50)
    logger.info("步骤 1/3: 数据采集...")
    logger.info("=" * 50)
    ret, _ = _run_script("scripts/reverse_collect.py", "--csv", str(HISTORY_CSV))
    if ret != 0:
        logger.error("数据采集失败，终止流程")
        return

    # 步骤 2: 统计分析和报告生成
    logger.info("\n" + "=" * 50)
    logger.info("步骤 2/3: 统计分析...")
    logger.info("=" * 50)
    ret, _ = _run_script("scripts/generate_report.py")
    if ret != 0:
        logger.error("统计分析失败，终止流程")
        return

    # 步骤 3: 部署策略
    logger.info("\n" + "=" * 50)
    logger.info("步骤 3/3: 策略已更新...")
    logger.info("=" * 50)

    strategy_src = DATA_DIR / "strategy.yaml"
    strategy_dst = _project_root / "strategies" / "reverse_engineered.yaml"
    if strategy_src.exists():
        import shutil
        shutil.copy2(strategy_src, strategy_dst)
        logger.info(f"策略文件已更新: {strategy_dst}")
    else:
        logger.warning("策略文件未生成")

    # 显示更新后的统计信息
    cmd_status()
    logger.info("策略更新完成！下次分析会自动使用最新版本。")

    # 显示报告摘要
    report_file = DATA_DIR / "pattern_report.md"
    if report_file.exists():
        with open(report_file) as f:
            content = f.read()
        # 提取前几行
        lines = content.split("\n")
        summary_lines = [l for l in lines if l.startswith("|") and "趋势强度" in l or "平均乖离" in l or "成功率" in l]
        if summary_lines:
            print("\n📊 更新后的关键指标:")
            for l in summary_lines[:5]:
                print(f"  {l}")


def cmd_stats():
    """查看详细统计。"""
    _ensure_dirs()

    stats_file = DATA_DIR / "stats.json"
    if stats_file.exists():
        with open(stats_file) as f:
            stats = json.load(f)

        print(f"\n{'='*60}")
        print(f"  反向分析策略 - 详细统计")
        print(f"{'='*60}")
        print(f"\n  总样本: {stats['total']} 次选股")
        print(f"  成功率: {stats['success_rate']}%")
        print(f"  时间跨度: {stats['date_range']['start']} ~ {stats['date_range']['end']}")
        print(f"  涉及个股: {stats['unique_stocks']} 只")

        s = stats["success"]
        print(f"\n  📈 成功组 ({s['count']} 只):")
        print(f"    平均趋势强度: {s['avg_features']['trend_strength']}")
        print(f"    平均乖离率MA5: {s['avg_features']['bias_ma5']}%")
        print(f"    平均量比: {s['avg_features']['volume_ratio_5d']}")

        if stats.get("fail", {}).get("count", 0) > 0:
            f = stats["fail"]
            print(f"\n  📉 失败组 ({f['count']} 只):")
            print(f"    平均趋势强度: {f['avg_features']['trend_strength']}")
            print(f"    平均乖离率MA5: {f['avg_features']['bias_ma5']}%")
    else:
        print("\n没有统计数据，请先运行 update 命令\n")


# ============================================================
# 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="反向分析策略维护工具")
    sub = parser.add_subparsers(dest="command", help="可用命令")

    # status
    sub.add_parser("status", help="查看当前状态")

    # add
    p_add = sub.add_parser("add", help="录入新的选股记录")
    p_add.add_argument("--csv", help="CSV 文件路径")
    p_add.add_argument("--image", help="截图文件路径（自动识别股票代码）")

    # update
    sub.add_parser("update", help="重新采集数据、分析并更新策略")

    # run (add + update 一步完成)
    p_run = sub.add_parser("run", help="录入并更新（一步完成）")
    p_run.add_argument("--csv", help="CSV 文件路径")
    p_run.add_argument("--image", help="截图文件路径")

    # stats
    sub.add_parser("stats", help="查看详细统计")

    args = parser.parse_args()

    if args.command == "status":
        cmd_status()
    elif args.command == "add":
        cmd_add(csv_path=args.csv, image_path=args.image)
    elif args.command == "update":
        cmd_update()
    elif args.command == "run":
        cmd_add(csv_path=args.csv, image_path=args.image)
        cmd_update()
    elif args.command == "stats":
        cmd_stats()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
