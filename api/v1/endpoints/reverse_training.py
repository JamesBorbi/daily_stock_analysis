# -*- coding: utf-8 -*-
"""反向分析训练 - API 端点（数据库版）。"""

from __future__ import annotations

import csv
import json
import logging
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.repositories.reverse_repo import ReverseRepository

router = APIRouter()
logger = logging.getLogger("reverse_training")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "reverse"
HISTORY_CSV = DATA_DIR / "history.csv"
ACCURACY_FILE = DATA_DIR / "accuracy.jsonl"
COMPARE_LOG = DATA_DIR / "compare_log.jsonl"
COMPARE_CACHE = DATA_DIR / "last_compare.json"

_TRAIN_TASKS: Dict[str, Dict] = {}


# ============================================================
# Models
# ============================================================

class PickItem(BaseModel):
    stock_code: str = Field(..., description="股票代码")
    stock_name: str = Field(default="", description="股票名称")
    pick_price: Optional[float] = Field(default=None, description="选中时价格")
    prev_close: Optional[float] = Field(default=None, description="前收盘价")
    pick_day_change: Optional[float] = Field(default=None, description="当日涨跌幅%")
    next_day_change: Optional[float] = Field(default=None, description="隔日涨跌幅%")
    success: int = Field(default=1, description="1=成功 0=失败")

class AddPicksRequest(BaseModel):
    date: str = Field(..., description="选股日期 YYYYMMDD")
    picks: List[PickItem] = Field(..., description="选股列表")
    success_flags: Optional[Dict[str, int]] = Field(default=None, description="失败标记 {code: 0}（兼容旧格式）")

class UpdatePickRequest(BaseModel):
    id: int = Field(..., description="记录 ID")
    stock_name: Optional[str] = None
    pick_price: Optional[float] = None
    prev_close: Optional[float] = None
    pick_day_change: Optional[float] = None
    next_day_change: Optional[float] = None
    success: Optional[int] = None

class ScanRequest(BaseModel):
    top_n: int = Field(5, ge=1, le=20)

class CompareRequest(BaseModel):
    date: str = Field(default="", description="对比日期，默认今天")

class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    progress: int
    message: str
    result: Optional[Any] = None


# ============================================================
# Helpers
# ============================================================

def _get_repo() -> ReverseRepository:
    return ReverseRepository()


def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        s = str(val).strip()
        return float(s) if s else None
    except (ValueError, TypeError):
        return None

def _get_accuracy_log() -> List[Dict]:
    if not ACCURACY_FILE.exists():
        return []
    records = []
    with open(ACCURACY_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _sync_csv_from_db():
    """将数据库全部数据同步到 CSV 文件。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    repo = _get_repo()
    items, _ = repo.list_paged(page=1, page_size=100000)
    items.sort(key=lambda x: (x["pick_date"], x["stock_code"]))
    with open(HISTORY_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "stock_code", "stock_name", "pick_price",
                     "prev_close", "pick_day_change", "next_day_change", "success"])
        for r in items:
            w.writerow([r["pick_date"], r["stock_code"],
                        r.get("stock_name", ""), r.get("pick_price", ""),
                        r.get("prev_close", ""), r.get("pick_day_change", ""),
                        r.get("next_day_change", ""), r["success"]])
    logger.info(f"CSV 已同步: {len(items)} 条" if items else "CSV 已清空")
    if not ACCURACY_FILE.exists():
        return []
    records = []
    with open(ACCURACY_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _append_accuracy_log(date_str: str, match_rate: float, match_count: int, total_count: int):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    records = _get_accuracy_log()
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


def _run_python(script: str, *args: str, timeout: int = 600) -> str:
    script_path = PROJECT_ROOT / script
    cmd = [sys.executable, str(script_path)] + list(args)
    logger.info(f"运行: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[:500])
    return result.stdout


# ============================================================
# Endpoints
# ============================================================

@router.get("/status")
def get_status() -> Dict:
    """获取系统状态。首次访问自动从 CSV 迁移历史数据。"""
    repo = _get_repo()
    stats = repo.get_statistics()

    # 自动迁移：数据库为空但 CSV 存在时
    if stats["history_count"] == 0 and HISTORY_CSV.exists():
        try:
            records = []
            with open(HISTORY_CSV) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    records.append({
                        "pick_date": row["date"],
                        "stock_code": row["stock_code"],
                        "stock_name": "",
                        "pick_price": None,
                        "prev_close": None,
                        "pick_day_change": None,
                        "next_day_change": float(row["gain"]) if row.get("gain", "").strip() else None,
                        "success": int(row.get("success", "1")),
                    })
            if records:
                repo.batch_upsert(records)
                logger.info(f"自动迁移 {len(records)} 条 CSV 数据到数据库")
                stats = repo.get_statistics()
        except Exception as e:
            logger.warning(f"CSV 自动迁移失败: {e}")

    accuracy_records = _get_accuracy_log()
    stats["accuracy_log"] = accuracy_records
    return stats


@router.get("/history")
def get_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    stock_code: Optional[str] = Query(None),
    success: Optional[int] = Query(None),
) -> Dict:
    """分页查询历史选股记录。默认按日期倒序分页返回。"""
    repo = _get_repo()
    items, total = repo.list_paged(
        page=page, page_size=page_size,
        date_from=date_from, date_to=date_to,
        stock_code=stock_code, success=success,
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


@router.post("/picks")
def add_picks(req: AddPicksRequest) -> Dict:
    """录入第三方选股（支持结构化数据和旧格式兼容）。"""
    repo = _get_repo()

    records = []
    for pick in req.picks:
        records.append({
            "pick_date": req.date,
            "stock_code": pick.stock_code,
            "stock_name": pick.stock_name or "",
            "pick_price": pick.pick_price,
            "prev_close": pick.prev_close,
            "pick_day_change": pick.pick_day_change,
            "next_day_change": pick.next_day_change,
            "success": pick.success,
        })

    # 兼容旧格式：success_flags 覆盖
    if req.success_flags:
        for r in records:
            code = r["stock_code"]
            if code in req.success_flags:
                r["success"] = req.success_flags[code]

    added = repo.batch_upsert(records)
    _sync_csv_from_db()
    stats = repo.get_statistics()
    return {
        "added": added,
        "total": stats["history_count"],
        "success_rate": stats["success_rate"],
    }


@router.put("/picks/{record_id}")
def update_pick(record_id: int, req: UpdatePickRequest) -> Dict:
    """更新一条选股记录。"""
    repo = _get_repo()
    existing = repo.get_by_id(record_id)
    if not existing:
        raise HTTPException(status_code=404, detail="记录不存在")

    update_data = {}
    if req.stock_name is not None:
        update_data["stock_name"] = req.stock_name
    if req.pick_price is not None:
        update_data["pick_price"] = req.pick_price
    if req.prev_close is not None:
        update_data["prev_close"] = req.prev_close
    if req.pick_day_change is not None:
        update_data["pick_day_change"] = req.pick_day_change
    if req.next_day_change is not None:
        update_data["next_day_change"] = req.next_day_change
    if req.success is not None:
        update_data["success"] = req.success
    update_data["pick_date"] = existing.pick_date
    update_data["stock_code"] = existing.stock_code

    repo.upsert(update_data)
    _sync_csv_from_db()
    updated = repo.get_by_id(record_id)
    return {"success": True, "record": updated.to_dict() if updated else None}


@router.delete("/picks/{record_id}")
def delete_pick(record_id: int) -> Dict:
    """删除一条选股记录。"""
    repo = _get_repo()
    ok = repo.delete(record_id)
    if not ok:
        raise HTTPException(status_code=404, detail="记录不存在")
    _sync_csv_from_db()
    return {"success": True}


@router.delete("/picks")
def delete_picks_by_date(date: str = Query(...)) -> Dict:
    """删除某日所有选股记录。"""
    repo = _get_repo()
    count = repo.delete_by_date(date)
    _sync_csv_from_db()
    return {"success": True, "deleted": count}


@router.post("/scan")
def run_scan(req: ScanRequest) -> Dict:
    """运行反向策略扫描。"""
    try:
        stdout = _run_python(
            "scripts/screen_reverse.py",
            "--top", str(req.top_n),
            "--json",
        )
        result = json.loads(stdout)
        date_str = datetime.now().strftime("%Y%m%d")
        compare_logs = _load_jsonl(COMPARE_LOG)
        compare_logs = [r for r in compare_logs if r.get("date") != date_str]
        compare_logs.append({
            "date": date_str,
            "scan_time": datetime.now().strftime("%H:%M"),
            "strategy_picks": [c["code"] for c in result.get("candidates", [])],
            "candidates_detail": result.get("candidates", []),
        })
        compare_logs.sort(key=lambda x: x["date"])
        _write_jsonl(COMPARE_LOG, compare_logs)
        return result
    except (subprocess.TimeoutExpired, RuntimeError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/compare")
def run_compare(req: CompareRequest) -> Dict:
    """对比策略 vs 第三方。"""
    date_str = req.date or datetime.now().strftime("%Y%m%d")
    repo = _get_repo()
    third_party, _ = repo.list_paged(
        date_from=date_str, date_to=date_str, page_size=1000
    )

    if not third_party:
        raise HTTPException(status_code=404, detail=f"{date_str} 没有第三方选股记录")

    third_set = set(r["stock_code"] for r in third_party)
    third_fail = set(r["stock_code"] for r in third_party if r.get("success") == 0)

    compare_logs = _load_jsonl(COMPARE_LOG)
    scan = next((r for r in compare_logs if r["date"] == date_str), None)
    strategy_codes = scan.get("strategy_picks", []) if scan else []
    strategy_detail = scan.get("candidates_detail", []) if scan else []

    strategy_set = set(strategy_codes)
    matches = third_set & strategy_set
    only_third = third_set - strategy_set
    only_strategy = strategy_set - third_set
    match_rate = round(len(matches) / max(len(third_set), 1) * 100, 1)

    _append_accuracy_log(date_str, match_rate, len(matches), len(third_set))

    only_third_detail = []
    for code in sorted(only_third):
        is_fail = code in third_fail
        detail = next((c for c in strategy_detail if c["code"] == code), None)
        third_rec = next((r for r in third_party if r["stock_code"] == code), {})
        only_third_detail.append({
            "code": code,
            "is_fail": is_fail,
            "name": third_rec.get("stock_name", ""),
            "pick_price": third_rec.get("pick_price"),
            "next_day_change": third_rec.get("next_day_change"),
        })

    only_strategy_detail = []
    for code in sorted(only_strategy):
        detail = next((c for c in strategy_detail if c["code"] == code), None)
        only_strategy_detail.append(detail or {"code": code})

    result = {
        "date": date_str,
        "third_party": [r["stock_code"] for r in third_party],
        "third_party_detail": [
            {
                "code": r["stock_code"],
                "name": r.get("stock_name", ""),
                "pick_price": r.get("pick_price"),
                "prev_close": r.get("prev_close"),
                "pick_day_change": r.get("pick_day_change"),
                "next_day_change": r.get("next_day_change"),
                "success": r.get("success"),
            }
            for r in third_party
        ],
        "third_party_fail": sorted(list(third_fail)),
        "strategy_picks": strategy_codes,
        "matches": sorted(list(matches)),
        "match_count": len(matches),
        "match_rate": match_rate,
        "only_third": only_third_detail,
        "only_strategy": only_strategy_detail,
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(COMPARE_CACHE, "w") as f:
        json.dump(result, f, ensure_ascii=False, default=str)
    return result


@router.get("/compare/latest")
def get_latest_compare() -> Dict:
    if COMPARE_CACHE.exists():
        with open(COMPARE_CACHE) as f:
            return json.load(f)
    return {}


@router.post("/train")
def run_training() -> Dict:
    """训练优化策略。"""
    task_id = str(uuid.uuid4())[:8]
    _TRAIN_TASKS[task_id] = {"status": "running", "progress": 0, "message": "初始化..."}

    try:
        _TRAIN_TASKS[task_id] = {"status": "running", "progress": 20, "message": "数据采集中..."}
        _run_python("scripts/reverse_collect.py", "--csv", str(HISTORY_CSV))

        _TRAIN_TASKS[task_id] = {"status": "running", "progress": 60, "message": "分析数据中..."}
        _run_python("scripts/generate_report.py")

        _TRAIN_TASKS[task_id] = {"status": "running", "progress": 90, "message": "更新策略..."}
        strategy_src = DATA_DIR / "strategy.yaml"
        strategy_dst = PROJECT_ROOT / "strategies" / "reverse_engineered.yaml"
        if strategy_src.exists():
            import shutil
            shutil.copy2(strategy_src, strategy_dst)

        _TRAIN_TASKS[task_id] = {"status": "completed", "progress": 100, "message": "训练完成"}
        stats = _get_repo().get_statistics()
        return {
            "task_id": task_id,
            "status": "completed",
            "message": "训练完成，策略已更新",
            "stats": stats,
        }
    except Exception as e:
        _TRAIN_TASKS[task_id] = {"status": "failed", "progress": 0, "message": str(e)}
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/train/status/{task_id}")
def get_training_status(task_id: str) -> TaskStatusResponse:
    task = _TRAIN_TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return TaskStatusResponse(
        task_id=task_id,
        status=task["status"],
        progress=task["progress"],
        message=task["message"],
    )


@router.get("/accuracy")
def get_accuracy() -> List[Dict]:
    return _get_accuracy_log()


@router.post("/migrate-from-csv")
def migrate_from_csv() -> Dict:
    """从 CSV 初始化数据库（新电脑首次运行）。支持新旧两种 CSV 格式。"""
    if not HISTORY_CSV.exists():
        raise HTTPException(status_code=404, detail="CSV 文件不存在")

    repo = _get_repo()
    records = []
    with open(HISTORY_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            r = {
                "pick_date": row.get("date", ""),
                "stock_code": row.get("stock_code", ""),
                "stock_name": row.get("stock_name", ""),
                "pick_price": _safe_float(row.get("pick_price")),
                "prev_close": _safe_float(row.get("prev_close")),
                "pick_day_change": _safe_float(row.get("pick_day_change")),
                "next_day_change": _safe_float(row.get("next_day_change")),
                "success": int(row.get("success", row.get("gain", "1")) or "1"),
            }
            # 兼容旧格式：只把 gain 非空的转为 next_day_change
            if not r["next_day_change"] and row.get("gain"):
                r["next_day_change"] = _safe_float(row.get("gain"))
            records.append(r)

    added = repo.batch_upsert(records)
    return {"migrated": len(records), "inserted_or_updated": added}


# ============================================================
# Internal helpers
# ============================================================

def _load_jsonl(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _write_jsonl(path: Path, records: List[Dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
