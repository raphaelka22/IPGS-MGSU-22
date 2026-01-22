from __future__ import annotations

import argparse
import json
from typing import Iterable, List

from smart_task_tracker.tracker import (
    Task,
    build_plan,
    normalize_tasks,
    normalized_to_dict,
    parse_deadline,
)


def load_tasks(path: str) -> List[Task]:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    tasks = []
    for entry in payload:
        tasks.append(
            Task(
                title=entry["title"],
                importance=entry["importance"],
                urgency=entry["urgency"],
                time_hours=entry["time_hours"],
                energy=entry["energy"],
                deadline=parse_deadline(entry.get("deadline")),
                order=entry.get("order"),
                depends_on=entry.get("depends_on", []),
            )
        )
    return tasks


def serialize_plan(plan: Iterable[dict[str, object]]) -> str:
    return json.dumps(list(plan), ensure_ascii=False, indent=2)


def serialize_normalized(normalized: Iterable[object]) -> str:
    return json.dumps(
        [normalized_to_dict(task) for task in normalized], ensure_ascii=False, indent=2
    )


def render_table(plan: List[dict[str, object]]) -> str:
    headers = [
        "№",
        "Задача",
        "Мой порядок",
        "Важность (1–5)",
        "Срочность (1–5)",
        "Дедлайн",
        "Время",
        "Энергия",
        "Итоговый приоритет (score)",
        "Комментарий “почему так”",
    ]
    rows = []
    for index, item in enumerate(plan, start=1):
        components = item.get("score_components", {})
        pieces = [
            f"срочность {item['urgency']}",
            f"важность {item['importance']}",
        ]
        if item.get("deadline"):
            pieces.append(f"дедлайн {item['deadline']}")
        if components.get("deadline_bonus", 0):
            pieces.append(f"бонус дедлайна +{components['deadline_bonus']}")
        if components.get("short_task_bonus", 0):
            pieces.append("короткая задача +1")
        if item.get("order"):
            pieces.append(f"мой порядок {item['order']}")
        if components.get("order_boost", 0):
            pieces.append(f"бонус порядка +{components['order_boost']}")
        pieces.append(f"штраф длительности -{components.get('duration_penalty')}")
        pieces.append(f"штраф энергии -{components.get('energy_penalty')}")
        comment = ", ".join(pieces)
        rows.append(
            [
                str(index),
                str(item["title"]),
                str(item.get("order") or "—"),
                str(item["importance"]),
                str(item["urgency"]),
                str(item.get("deadline") or "—"),
                f"{item['time_hours']} ч",
                str(item["energy"]),
                str(item["score"]),
                comment,
            ]
        )

    widths = [len(header) for header in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))

    def format_row(values: List[str]) -> str:
        return " | ".join(value.ljust(widths[idx]) for idx, value in enumerate(values))

    output = [format_row(headers), format_row(["-" * width for width in widths])]
    output.extend(format_row(row) for row in rows)
    return "\n".join(output)


def order_plan_for_schedule(plan: List[dict[str, object]]) -> List[dict[str, object]]:
    remaining = list(plan)
    scheduled: List[dict[str, object]] = []
    resolved = set()

    def sort_key(item: dict[str, object]) -> tuple:
        deadline = item.get("deadline") or "9999-12-31"
        return (deadline, -(float(item["score"])))

    while remaining:
        progress = False
        for item in sorted(remaining, key=sort_key):
            dependencies = item.get("depends_on", [])
            if all(dep in resolved for dep in dependencies):
                scheduled.append(item)
                resolved.add(item["title"])
                remaining.remove(item)
                progress = True
                break
        if not progress:
            scheduled.extend(sorted(remaining, key=sort_key))
            break
    return scheduled


def _collect_block_tasks(
    tasks: List[dict[str, object]], limit_hours: float, max_tasks: int | None
) -> List[dict[str, object]]:
    block: List[dict[str, object]] = []
    total = 0.0
    while tasks and (max_tasks is None or len(block) < max_tasks):
        candidate = tasks[0]
        duration = float(candidate["time_hours"])
        if total + duration > limit_hours and block:
            break
        block.append(candidate)
        total = round(total + duration, 2)
        tasks.pop(0)
    return block


def _format_block(title: str, tasks: List[dict[str, object]]) -> List[str]:
    if not tasks:
        return [f"{title}: нет задач"]
    names = ", ".join(task["title"] for task in tasks)
    total = sum(float(task["time_hours"]) for task in tasks)
    return [f"{title}: {names} (≈ {round(total, 2)} ч)"]


def render_schedule(plan: List[dict[str, object]]) -> str:
    ordered = order_plan_for_schedule(plan)
    total_hours = sum(float(item["time_hours"]) for item in ordered)
    many_tasks = len(ordered) > 6 or total_hours > 4

    def build_day_plan(tasks: List[dict[str, object]]) -> List[str]:
        remaining = list(tasks)
        lines = ["План на день:"]
        block1 = _collect_block_tasks(remaining, 1.5, 2)
        block2 = _collect_block_tasks(remaining, 1.0, None)
        block3 = _collect_block_tasks(remaining, 1.0, None)
        lines.extend(_format_block("• Блок 1 (пик энергии)", block1))
        lines.append("• Перерыв")
        lines.extend(_format_block("• Блок 2", block2))
        lines.extend(_format_block("• Блок 3", block3))
        return lines

    def build_two_hour_plan(tasks: List[dict[str, object]]) -> List[str]:
        remaining = list(tasks)
        block = _collect_block_tasks(remaining, 2.0, None)
        lines = ["План на 2 часа (минимальный, самое важное):"]
        lines.extend(_format_block("• Блок (2 часа)", block))
        return lines

    def build_three_day_plan(tasks: List[dict[str, object]]) -> List[str]:
        remaining = list(tasks)
        lines = ["План на 3 дня:"]
        for day in range(1, 4):
            lines.append(f"День {day}:")
            day_block1 = _collect_block_tasks(remaining, 1.5, 2)
            day_block2 = _collect_block_tasks(remaining, 1.0, None)
            day_block3 = _collect_block_tasks(remaining, 1.0, None)
            lines.extend(_format_block("• Блок 1 (пик энергии)", day_block1))
            lines.append("• Перерыв")
            lines.extend(_format_block("• Блок 2", day_block2))
            lines.extend(_format_block("• Блок 3", day_block3))
        return lines

    output: List[str] = []
    if many_tasks:
        output.extend(build_two_hour_plan(ordered))
        output.append("")
        output.extend(build_day_plan(ordered))
        output.append("")
        output.extend(build_three_day_plan(ordered))
    else:
        output.extend(build_day_plan(ordered))
    return "\n".join(output)


def main() -> None:
    parser = argparse.ArgumentParser(description="Smart Task Tracker")
    parser.add_argument("tasks", help="Path to JSON file with tasks")
    parser.add_argument(
        "--output",
        choices=["plan", "normalized", "table", "schedule"],
        default="plan",
        help="Output prioritized plan, normalized list, ranking table, or schedule",
    )
    args = parser.parse_args()

    tasks = load_tasks(args.tasks)
    if args.output == "normalized":
        normalized = normalize_tasks(tasks)
        print(serialize_normalized(normalized))
        return

    plan = build_plan(tasks)
    if args.output == "table":
        print(render_table(plan))
        return
    if args.output == "schedule":
        print(render_schedule(plan))
        return
    print(serialize_plan(plan))


if __name__ == "__main__":
    main()
