"""Print the arithmetic of the agent layer's claim against its own record."""

from collections import Counter

from ofag.agent.lessons import Lesson, load_lessons
from ofag.agent.retrospect import retrospect, unenforced
from ofag.agent.roles import owner_of


def corpus(lessons: tuple[Lesson, ...]) -> None:
    """What the corpus holds, counted."""

    def table(title: str, counts: Counter[str]) -> None:
        print(f"  {title}")
        for key, n in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
            print(f"    {key:30s} {n:3d}")

    table("by source", Counter(x.source for x in lessons))
    methods = Counter(m for x in lessons for m in x.methods)
    methods["(no survey data)"] = sum(1 for x in lessons if not x.methods)
    table("by method (a lesson can name two)", methods)
    table("by who found it", Counter(x.found_by.value for x in lessons))
    table("by decision", Counter(x.decision.value for x in lessons))
    table(
        "by owning role (from its procedure step)",
        Counter(owner.value if (owner := owner_of(x.procedure)) else "(no step)" for x in lessons),
    )
    print()


def main() -> None:
    lessons = load_lessons()
    total = len(lessons)
    reaches = retrospect(lessons)

    print(f"{total} recorded failures, {sum(x.silent for x in lessons)} of which ran clean.\n")
    corpus(lessons)
    print(
        f"{'what refuses':52s} {'proc':>5s} {'reach':>6s} {'silent':>7s} "
        f"{'tested':>7s} {'shown':>6s}"
    )
    for reach in reaches:
        procedure = reach.enforcement.enforces or "--"
        print(
            f"  {reach.enforcement.what[:50]:50s} {procedure:>5s} "
            f"{len(reach.lessons):6d} {reach.silent:7d} {reach.checked:7d} "
            f"{len(reach.shown):6d}"
        )

    addressed = {lesson.id for reach in reaches for lesson in reach.lessons}
    checked = {lesson.id for lesson in lessons if lesson.covered_by is not None}
    print()
    print(f"  addressed by something that refuses   {len(addressed):3d} of {total}")
    print(f"  with a test that fires on it          {len(checked):3d} of {total}")
    shown = {lesson for reach in reaches for lesson in reach.shown}
    print(f"  both                                  {len(addressed & checked):3d} of {total}")
    print(f"  shown refused by a test               {len(shown):3d} of {total}")

    print("\nprocedures the corpus uses and nothing enforces\n")
    gaps = unenforced(lessons)
    for procedure, rows in sorted(gaps.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        name = procedure or "not placed in any procedure"
        print(f"  {name:32s} {len(rows):3d}  {' '.join(x.id for x in rows)}")

    widest = sorted(((k, v) for k, v in gaps.items() if k), key=lambda kv: -len(kv[1]))[:2]
    print()
    print(
        "  the next two to build: "
        + " and ".join(f"{k} ({len(v)})" for k, v in widest)
        + f", {sum(len(v) for _, v in widest)} recorded failures between them"
    )


if __name__ == "__main__":
    main()
