"""Commit streak calculation and visualization."""

from datetime import datetime, timedelta, timezone
from collections import defaultdict
from typing import Optional


def parse_commit_dates(commits: list) -> list[datetime]:
    """Extract sorted commit datetimes from GitHub API commit list."""
    dates = []
    for commit in commits:
        date_str = commit.get("commit", {}).get("author", {}).get("date")
        if date_str:
            try:
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                dates.append(dt)
            except ValueError:
                pass
    return sorted(dates, reverse=True)


def calculate(dates: list[datetime]) -> dict:
    """Compute streak stats from a list of commit datetimes."""
    if not dates:
        return {"current": 0, "longest": 0, "total": 0, "weekly": {}, "last_commit": None}

    today = datetime.now(timezone.utc).date()
    commit_days = sorted(set(d.date() for d in dates), reverse=True)
    total = len(dates)
    last_commit = commit_days[0].isoformat()

    # Current streak: consecutive days ending today or yesterday
    current = 0
    most_recent = commit_days[0]
    if most_recent >= today - timedelta(days=1):
        expected = most_recent
        for day in commit_days:
            if day == expected:
                current += 1
                expected -= timedelta(days=1)
            elif day < expected:
                break

    # Longest streak
    longest = 1
    run = 1
    for i in range(1, len(commit_days)):
        if commit_days[i - 1] - commit_days[i] == timedelta(days=1):
            run += 1
            longest = max(longest, run)
        else:
            run = 1
    longest = max(longest, current)

    # Weekly commit counts (last 12 weeks, 0 = this week)
    weekly: dict[int, int] = defaultdict(int)
    cutoff = today - timedelta(weeks=12)
    for d in dates:
        if d.date() >= cutoff:
            weeks_ago = (today - d.date()).days // 7
            weekly[weeks_ago] += 1

    return {
        "current": current,
        "longest": longest,
        "total": total,
        "weekly": dict(weekly),
        "last_commit": last_commit,
    }


def render_bar(weekly: dict, weeks: int = 12) -> str:
    """Render a compact 12-week activity sparkline using block chars."""
    blocks = " ░▒▓█"
    max_count = max(weekly.values(), default=1)
    bars = []
    for w in range(weeks - 1, -1, -1):
        count = weekly.get(w, 0)
        if count == 0:
            level = 0
        else:
            level = max(1, min(4, round(count / max_count * 4)))
        bars.append(blocks[level])
    return "".join(bars)


def streak_color(current: int) -> str:
    if current == 0:
        return "dim"
    elif current < 3:
        return "yellow"
    elif current < 7:
        return "green"
    elif current < 14:
        return "bright_green"
    else:
        return "bold bright_green"
