# -*- coding: utf-8 -*-
"""Reverse analysis repository - database access for reverse pick records."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, desc, func, or_, select, delete, asc
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from src.storage import DatabaseManager, ReversePick

logger = logging.getLogger(__name__)


class ReverseRepository:
    """DB access layer for reverse analysis picks."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    # ========== 查询 ==========

    def get_by_id(self, record_id: int) -> Optional[ReversePick]:
        with self.db.get_session() as session:
            return session.execute(
                select(ReversePick).where(ReversePick.id == record_id)
            ).scalar_one_or_none()

    def find_by_date_code(self, pick_date: str, stock_code: str) -> Optional[ReversePick]:
        with self.db.get_session() as session:
            return session.execute(
                select(ReversePick).where(
                    and_(
                        ReversePick.pick_date == pick_date,
                        ReversePick.stock_code == stock_code,
                    )
                )
            ).scalar_one_or_none()

    def list_paged(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        stock_code: Optional[str] = None,
        success: Optional[int] = None,
        sort_by: str = "pick_date",
        sort_desc: bool = True,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """分页查询选股记录，返回 (记录列表, 总数)。"""
        with self.db.get_session() as session:
            query = select(ReversePick)
            count_query = select(func.count(ReversePick.id))

            # 筛选条件
            conditions = []
            if date_from:
                conditions.append(ReversePick.pick_date >= date_from)
            if date_to:
                conditions.append(ReversePick.pick_date <= date_to)
            if stock_code:
                conditions.append(ReversePick.stock_code.like(f"%{stock_code}%"))
            if success is not None:
                conditions.append(ReversePick.success == success)

            if conditions:
                query = query.where(and_(*conditions))
                count_query = count_query.where(and_(*conditions))

            # 总数
            total = session.execute(count_query).scalar() or 0

            # 排序
            sort_col = getattr(ReversePick, sort_by, ReversePick.pick_date)
            order = desc(sort_col) if sort_desc else asc(sort_col)
            query = query.order_by(order)

            # 分页
            offset = (page - 1) * page_size
            query = query.offset(offset).limit(page_size)

            results = session.execute(query).scalars().all()
            return [r.to_dict() for r in results], total

    def get_date_groups(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int, int]:
        """按日期分组查询，返回 (日期组列表, 成功总数, 失败总数)。"""
        with self.db.get_session() as session:
            base_conditions = []
            if date_from:
                base_conditions.append(ReversePick.pick_date >= date_from)
            if date_to:
                base_conditions.append(ReversePick.pick_date <= date_to)

            # 总记录数和成功/失败统计
            all_query = select(ReversePick)
            if base_conditions:
                all_query = all_query.where(and_(*base_conditions))

            all_rows = session.execute(all_query).scalars().all()
            total = len(all_rows)
            success_count = sum(1 for r in all_rows if r.success == 1)
            fail_count = total - success_count

            # 按日期分组
            date_groups: Dict[str, list] = {}
            for r in all_rows:
                groups = r.pick_date
                if groups not in date_groups:
                    date_groups[groups] = []
                date_groups[groups].append(r.to_dict())

            # 排序
            sorted_dates = sorted(date_groups.keys(), reverse=True)

            result = []
            for d in sorted_dates:
                picks = date_groups[d]
                sc = sum(1 for p in picks if p["success"] == 1)
                fc = len(picks) - sc
                result.append({
                    "date": d,
                    "picks": picks,
                    "success_count": sc,
                    "fail_count": fc,
                    "total": len(picks),
                })

            return result, success_count, fail_count

    # ========== 增删改 ==========

    def upsert(self, record: Dict[str, Any]) -> int:
        """插入或更新一条记录。返回记录 ID。"""
        pick_date = record["pick_date"]
        stock_code = record["stock_code"]

        with self.db.get_session() as session:
            existing = session.execute(
                select(ReversePick).where(
                    and_(
                        ReversePick.pick_date == pick_date,
                        ReversePick.stock_code == stock_code,
                    )
                )
            ).scalar_one_or_none()

            if existing:
                # 更新
                for key in ("stock_name", "pick_price", "prev_close",
                            "pick_day_change", "next_day_change", "success"):
                    if key in record and record[key] is not None:
                        setattr(existing, key, record[key])
                existing.updated_at = datetime.now()
                session.commit()
                return existing.id
            else:
                # 插入
                obj = ReversePick(
                    pick_date=pick_date,
                    stock_code=stock_code,
                    stock_name=record.get("stock_name", ""),
                    pick_price=record.get("pick_price"),
                    prev_close=record.get("prev_close"),
                    pick_day_change=record.get("pick_day_change"),
                    next_day_change=record.get("next_day_change"),
                    success=record.get("success", 1),
                )
                session.add(obj)
                session.commit()
                session.refresh(obj)
                return obj.id

    def batch_upsert(self, records: List[Dict[str, Any]]) -> int:
        """批量插入/更新。返回操作条数。"""
        count = 0
        for r in records:
            try:
                self.upsert(r)
                count += 1
            except Exception as e:
                logger.warning(f"  upsert 失败 {r.get('stock_code')}: {e}")
        return count

    def delete(self, record_id: int) -> bool:
        """删除一条记录。"""
        with self.db.get_session() as session:
            obj = session.execute(
                select(ReversePick).where(ReversePick.id == record_id)
            ).scalar_one_or_none()
            if obj:
                session.delete(obj)
                session.commit()
                return True
            return False

    def delete_by_date(self, pick_date: str) -> int:
        """删除某日所有记录。返回删除条数。"""
        with self.db.get_session() as session:
            result = session.execute(
                delete(ReversePick).where(ReversePick.pick_date == pick_date)
            )
            session.commit()
            return result.rowcount

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计数据。"""
        with self.db.get_session() as session:
            total = session.execute(select(func.count(ReversePick.id))).scalar() or 0
            success = session.execute(
                select(func.count(ReversePick.id)).where(ReversePick.success == 1)
            ).scalar() or 0
            fail = total - success

            unique = session.execute(
                select(func.count(func.distinct(ReversePick.stock_code)))
            ).scalar() or 0

            date_range = session.execute(
                select(
                    func.min(ReversePick.pick_date),
                    func.max(ReversePick.pick_date),
                )
            ).one()

            collected = 0
            from pathlib import Path
            collected_file = Path("data") / "reverse" / "collected.jsonl"
            if collected_file.exists():
                with open(collected_file) as f:
                    collected = sum(1 for _ in f)

            return {
                "history_count": total,
                "success_count": success,
                "fail_count": fail,
                "success_rate": round(success / max(total, 1) * 100, 2),
                "unique_stocks": unique,
                "date_range": {
                    "start": date_range[0] or "",
                    "end": date_range[1] or "",
                },
                "collected_count": collected,
            }
