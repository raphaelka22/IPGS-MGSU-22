from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from math import ceil
from typing import Iterable, List, Optional


@dataclass(frozen=True)
class Task:
    title: str
    importance: int
    urgency: int
    time_hours: float
    energy: int
    deadline: Optional[date] = None
    order: Optional[int] = None
    depends_on: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("Task title cannot be empty")
        for field_name, value in (
            ("importance", self.importance),
            ("urgency", self.urgency),
            ("energy", self.energy),
        ):
            if not 1 <= value <= 5:
                raise ValueError(f"{field_name} must be between 1 and 5")
        if self.time_hours <= 0:
            raise ValueError("time_hours must be greater than 0")
        if self.order is not None and self.order < 1:
            raise ValueError("order must be a positive integer")


@dataclass(frozen=True)
class NormalizedTask:
    title: str
    importance: int
    urgency: int
    time_hours: float
    energy: int
    deadline: Optional[str]
    order: Optional[int]
    depends_on: List[str]
    subtasks: List["NormalizedTask"] = field(default_factory=list)


def parse_deadline(value: str | None) -> Optional[date]:
    if value is None:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def normalize_title(title: str) -> str:
    cleaned = " ".join(title.strip().split())
    cleaned = cleaned.rstrip(".!?")
    if not cleaned:
        return cleaned
    return cleaned[0].upper() + cleaned[1:]


def _deadline_bonus(task_deadline: Optional[date], today: date) -> float:
    if task_deadline is None:
        return 0.0
    days_left = (task_deadline - today).days
    if days_left < 0:
        return 3.0
    if days_left <= 1:
        return 2.0
    if days_left <= 3:
        return 1.5
    if days_left <= 7:
        return 1.0
    return 0.0


def priority_score(task: Task, today: Optional[date] = None) -> float:
    """
    Calculate a priority score using:
    urgency + importance + deadline + order - duration_penalty - energy_penalty.
    """
    reference_date = today or date.today()
    base = float(task.urgency + task.importance)
    order_boost = 0.0 if task.order is None else max(0, 6 - task.order) * 0.5
    duration_penalty = round(task.time_hours * 0.8, 2)
    energy_penalty = round(task.energy * 0.6, 2)
    bonus = _deadline_bonus(task.deadline, reference_date)
    if task.time_hours <= (25 / 60):
        bonus += 1.0
    score = base + bonus + order_boost - duration_penalty - energy_penalty
    return round(score, 2)


def priority_tier(score: float) -> str:
    if score >= 14:
        return "high"
    if score >= 9:
        return "medium"
    return "low"


def _merge_task(base: Task, incoming: Task) -> Task:
    deadline = min(
        [d for d in (base.deadline, incoming.deadline) if d is not None],
        default=None,
    )
    order = min(
        [value for value in (base.order, incoming.order) if value is not None],
        default=None,
    )
    depends_on = sorted(set(base.depends_on + incoming.depends_on))
    return Task(
        title=base.title,
        importance=max(base.importance, incoming.importance),
        urgency=max(base.urgency, incoming.urgency),
        time_hours=round(base.time_hours + incoming.time_hours, 2),
        energy=max(base.energy, incoming.energy),
        deadline=deadline,
        order=order,
        depends_on=depends_on,
    )


def deduplicate_tasks(tasks: Iterable[Task]) -> List[Task]:
    merged: dict[str, Task] = {}
    for task in tasks:
        normalized_title = normalize_title(task.title)
        normalized_task = Task(
            title=normalized_title,
            importance=task.importance,
            urgency=task.urgency,
            time_hours=task.time_hours,
            energy=task.energy,
            deadline=task.deadline,
            order=task.order,
            depends_on=[normalize_title(dep) for dep in task.depends_on],
        )
        if normalized_title in merged:
            merged[normalized_title] = _merge_task(merged[normalized_title], normalized_task)
        else:
            merged[normalized_title] = normalized_task
    return list(merged.values())


def split_large_tasks(task: Task, max_hours: float = 2.0) -> List[Task]:
    if task.time_hours <= max_hours:
        return [task]
    chunks = int(ceil(task.time_hours / max_hours))
    per_chunk = round(task.time_hours / chunks, 2)
    subtasks = []
    for index in range(1, chunks + 1):
        subtasks.append(
            Task(
                title=f"{task.title} (часть {index}/{chunks})",
                importance=task.importance,
                urgency=task.urgency,
                time_hours=per_chunk,
                energy=task.energy,
                deadline=task.deadline,
                order=task.order,
                depends_on=task.depends_on,
            )
        )
    return subtasks


def normalize_tasks(tasks: Iterable[Task]) -> List[NormalizedTask]:
    normalized = []
    for task in deduplicate_tasks(tasks):
        subtasks_raw = split_large_tasks(task)
        subtasks = [
            NormalizedTask(
                title=subtask.title,
                importance=subtask.importance,
                urgency=subtask.urgency,
                time_hours=subtask.time_hours,
                energy=subtask.energy,
                deadline=subtask.deadline.isoformat() if subtask.deadline else None,
                order=subtask.order,
                depends_on=subtask.depends_on,
                subtasks=[],
            )
            for subtask in subtasks_raw
        ]
        normalized.append(
            NormalizedTask(
                title=task.title,
                importance=task.importance,
                urgency=task.urgency,
                time_hours=task.time_hours,
                energy=task.energy,
                deadline=task.deadline.isoformat() if task.deadline else None,
                order=task.order,
                depends_on=task.depends_on,
                subtasks=subtasks if len(subtasks) > 1 else [],
            )
        )
    return normalized


def normalized_to_dict(task: NormalizedTask) -> dict[str, object]:
    return {
        "title": task.title,
        "importance": task.importance,
        "urgency": task.urgency,
        "time_hours": task.time_hours,
        "energy": task.energy,
        "deadline": task.deadline,
        "order": task.order,
        "depends_on": task.depends_on,
        "subtasks": [normalized_to_dict(subtask) for subtask in task.subtasks],
    }


def build_plan(tasks: Iterable[Task], today: Optional[date] = None) -> List[dict[str, object]]:
    reference_date = today or date.today()
    scored = []
    for task in deduplicate_tasks(tasks):
        score = priority_score(task, reference_date)
        deadline_bonus = _deadline_bonus(task.deadline, reference_date)
        short_bonus = 1.0 if task.time_hours <= (25 / 60) else 0.0
        order_boost = 0.0 if task.order is None else max(0, 6 - task.order) * 0.5
        duration_penalty = round(task.time_hours * 0.8, 2)
        energy_penalty = round(task.energy * 0.6, 2)
        scored.append(
            {
                "title": task.title,
                "importance": task.importance,
                "urgency": task.urgency,
                "time_hours": task.time_hours,
                "energy": task.energy,
                "deadline": task.deadline.isoformat() if task.deadline else None,
                "order": task.order,
                "depends_on": task.depends_on,
                "suggested_slot": suggested_energy_slot(task.energy),
                "score": score,
                "tier": priority_tier(score),
                "score_components": {
                    "deadline_bonus": deadline_bonus,
                    "short_task_bonus": short_bonus,
                    "order_boost": order_boost,
                    "duration_penalty": duration_penalty,
                    "energy_penalty": energy_penalty,
                },
            }
        )
    scored.sort(
        key=lambda item: (
            {"high": 0, "medium": 1, "low": 2}[item["tier"]],
            -(item["score"]),
            item["deadline"] or "9999-12-31",
            item["order"] or 9999,
        )
    )
    return scored


def suggested_energy_slot(energy: int) -> str:
    if energy >= 4:
        return "morning/day"
    if energy == 3:
        return "day"
    return "evening"
