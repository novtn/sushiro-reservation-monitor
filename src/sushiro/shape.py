"""Turn raw API payloads into something readable.

The API speaks in compact codes: ``date`` is ``20261105``, ``start`` is
``111500``, and availability is the string ``AVAILABLE``. Everything here
converts that to normal forms and groups slots by day so a terminal output and
a JSON consumer share one implementation.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date as Date

AVAILABLE = "AVAILABLE"


def iso_date(raw: str) -> str:
    """``20261105`` -> ``2026-11-05``."""
    text = str(raw)
    if len(text) != 8 or not text.isdigit():
        return text
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}"


def clock(raw: str) -> str:
    """``111500`` -> ``11:15``."""
    text = str(raw)
    if len(text) < 4 or not text.isdigit():
        return text
    return f"{text[:2]}:{text[2:4]}"


def parse_date(text: str) -> str:
    """Accept ``2026-11-05`` or ``20261105`` and return the ISO form."""
    digits = "".join(ch for ch in str(text) if ch.isdigit())
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return str(text)


@dataclass
class Day:
    date: str
    available: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.available) + len(self.blocked)


def normalize(slot: dict) -> dict:
    status = str(slot.get("availability", "")).upper()
    return {
        "date": iso_date(slot.get("date", "")),
        "start": clock(slot.get("start", "")),
        "end": clock(slot.get("end", "")),
        "available": status == AVAILABLE,
        "availability": status,
    }


def group_by_day(slots: list[dict]) -> list[Day]:
    buckets: dict[str, Day] = defaultdict(lambda: Day(date=""))
    for slot in slots:
        item = normalize(slot)
        day = buckets[item["date"]]
        day.date = item["date"]
        (day.available if item["available"] else day.blocked).append(item["start"])
    days = sorted(buckets.values(), key=lambda d: d.date)
    for day in days:
        day.available.sort()
        day.blocked.sort()
    return days


def filter_days(days: list[Day], *, date: str | None = None,
                days_ahead: int | None = None, today: Date | None = None) -> list[Day]:
    """Slice the schedule by a single date or a horizon measured from today."""
    if date:
        wanted = parse_date(date)
        return [day for day in days if day.date == wanted]
    if days_ahead is not None:
        start = today or Date.today()
        allowed = {
            Date.fromordinal(start.toordinal() + offset).isoformat()
            for offset in range(days_ahead)
        }
        return [day for day in days if day.date in allowed]
    return days


def summarize(days: list[Day]) -> dict:
    return {
        "days": len(days),
        "slots": sum(day.total for day in days),
        "available": sum(len(day.available) for day in days),
    }


def format_days(days: list[Day], *, show_blocked: bool = False) -> str:
    lines: list[str] = []
    for day in days:
        head = f"{day.date}  {len(day.available):>2}/{day.total:<2}"
        if day.available:
            head += "  " + " ".join(day.available)
        else:
            head += "  无"
        lines.append(head)
        if show_blocked and day.blocked:
            lines.append("              " + " ".join(day.blocked))
    return "\n".join(lines)


# -- stores ---------------------------------------------------------------


def store_line(store: dict) -> str:
    name = store.get("name") or store.get("nameKana") or "?"
    store_id = store.get("id", "?")
    address = store.get("address") or ""
    return f"{store_id:>5}  {name}  {address}".rstrip()


def store_detail(store: dict) -> str:
    """Human summary of one store, using only fields the API actually returns."""
    name = store.get("name") or store.get("nameKana") or "?"
    lines = [f"{name} ({store.get('id', '?')})"]
    if store.get("address"):
        lines.append(f"地址：{store['address']}")
    if store.get("area"):
        lines.append(f"商圈：{store['area']}")

    status = store.get("storeStatus", "?")
    ticket = store.get("netTicketStatus", "?")
    wait = store.get("wait")
    bits = [status]
    if ticket and ticket != status:
        bits.append(f"取号 {ticket}")
    if isinstance(wait, int) and wait >= 0:
        bits.append(f"排队 {wait} 桌")
    lines.append("状态：" + " · ".join(str(bit) for bit in bits))

    low = store.get("minCustomersMobileTable")
    high = store.get("maxCustomersMobileTable")
    if low is not None and high is not None:
        lines.append(f"桌位：{low}–{high} 人")
    reservation = store.get("reservationStatus")
    if reservation:
        lines.append(f"预约：{reservation}")
    if store.get("tablesCapacity") is not None:
        lines.append(f"桌数上限：{store['tablesCapacity']}")
    return "\n".join(lines)
