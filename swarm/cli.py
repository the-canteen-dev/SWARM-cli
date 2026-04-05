"""SWARM CLI - main entry point."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from typing import Annotated, Optional
from datetime import datetime, timezone

from . import config, auth, github, streak

app = typer.Typer(
    name="swarm",
    help="SWARM CLI — Track your startup progress with your cohort.",
    no_args_is_help=False,
    add_completion=True,
)

profile_app = typer.Typer(help="View and edit your profile.", no_args_is_help=False)
repo_app = typer.Typer(help="Track your primary repo.", no_args_is_help=False)
update_app = typer.Typer(help="Submit traction and product updates.", no_args_is_help=False)

app.add_typer(profile_app, name="profile")
app.add_typer(repo_app, name="repo")
app.add_typer(update_app, name="update")

console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_login() -> None:
    if not config.is_logged_in():
        console.print("[red]Not logged in.[/red] Run [bold cyan]swarm login[/bold cyan] first.")
        raise typer.Exit(1)


def _require_discord() -> None:
    if not config.has_discord():
        console.print(
            "[yellow]Discord handle required.[/yellow] "
            "Run [bold cyan]swarm profile edit[/bold cyan]"
        )
        raise typer.Exit(1)


def _fmt_date(date_str) -> str:
    if not date_str:
        return "unknown"
    try:
        if isinstance(date_str, datetime):
            dt = date_str
        else:
            dt = datetime.fromisoformat(str(date_str))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        if delta.total_seconds() < 0:
            return dt.strftime("%b %d, %Y")
        days = delta.days
        if days == 0:
            h = delta.seconds // 3600
            m = (delta.seconds % 3600) // 60
            s = delta.seconds % 60
            if h == 0 and m == 0:
                return "just now" if s < 5 else f"{s}s ago"
            if h == 0:
                return f"{m}m ago"
            return f"{h}h ago"
        if days == 1:
            return "yesterday"
        if days < 7:
            return f"{days} days ago"
        if days < 30:
            w = days // 7
            return f"{w} week{'s' if w > 1 else ''} ago"
        return dt.strftime("%b %d, %Y")
    except Exception:
        return str(date_str)


def _get_streak_data(force_refresh: bool = False) -> dict:
    """Return streak stats, using a 1-hour cache."""
    cached = config.get("cache.streak")
    if not force_refresh and cached:
        fetched_at_str = cached.get("fetched_at")
        if fetched_at_str:
            try:
                fetched_at = datetime.fromisoformat(str(fetched_at_str))
                if fetched_at.tzinfo is None:
                    fetched_at = fetched_at.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
                if age < 3600:
                    return cached
            except Exception:
                pass

    token = config.get("auth.github_token")
    repo_full = config.get("repo.full_name")
    if not token or not repo_full:
        return {}

    try:
        owner, repo_name = repo_full.split("/", 1)
        with console.status(f"[dim]Fetching commits from {repo_full}...[/dim]"):
            commits = github.get_commits(token, owner, repo_name)

        dates = streak.parse_commit_dates(commits)
        data = streak.calculate(dates)
        data["fetched_at"] = datetime.now(timezone.utc).isoformat()
        config.set_val("cache.streak", data)
        return data
    except Exception as e:
        console.print(f"[dim]Could not fetch commits: {e}[/dim]")
        return cached or {}


def _get_multiline_text(hint: str) -> Optional[str]:
    """Collect multiline input inline. Empty line to finish."""
    console.print(f"[dim]{hint}[/dim]")
    console.print("[dim](Empty line to finish)[/dim]\n")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line == "":
            if lines:
                break
        else:
            lines.append(line)
    return "\n".join(lines).strip() or None


def _recent_updates(n: int = 5) -> list[dict]:
    """Return the n most recent updates across both traction and product."""
    traction = [{"kind": "traction", **u} for u in (config.get("updates.traction") or [])]
    product = [{"kind": "product", **u} for u in (config.get("updates.product") or [])]
    combined = sorted(traction + product, key=lambda u: u.get("date", ""), reverse=True)
    return combined[:n]


def _print_updates(updates: list[dict], full: bool = False) -> None:
    """Print a list of update dicts."""
    if not updates:
        console.print("[dim]No updates yet.[/dim]")
        return
    for u in updates:
        kind = u.get("kind", "")
        kind_label = "[cyan]product[/cyan]" if kind == "product" else "[green]traction[/green]"
        date_label = f"[dim]{_fmt_date(u.get('date'))}[/dim]"
        console.print(f"\n  {kind_label}  {date_label}")
        text = u.get("text", "")
        limit = None if full else 120
        if text:
            snippet = text if (full or len(text) <= 120) else text[:120] + "…"
            console.print(f"  {snippet}")


# ---------------------------------------------------------------------------
# Root — no subcommand → show status
# ---------------------------------------------------------------------------

@app.callback(invoke_without_command=True)
def _root(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        if not config.is_logged_in():
            console.print(Panel(
                "[bold]Welcome to SWARM CLI[/bold]\n\n"
                "Run [bold cyan]swarm login[/bold cyan] to get started.",
                border_style="cyan",
                padding=(1, 2),
            ))
        else:
            _show_dashboard(refresh=False)


# ---------------------------------------------------------------------------
# swarm login / logout
# ---------------------------------------------------------------------------

@app.command()
def login() -> None:
    """Authenticate with GitHub and set up your profile."""
    if config.is_logged_in():
        handle = config.get("auth.github_handle")
        console.print(f"Already logged in as [bold]@{handle}[/bold].")
        if not typer.confirm("Re-authenticate?", default=False):
            return

    console.print("\n[bold cyan]Logging in with GitHub...[/bold cyan]")
    try:
        token_data = auth.device_flow_login()
        token = token_data["access_token"]
        with console.status("Fetching your GitHub profile..."):
            user = auth.get_github_user(token)
    except RuntimeError as e:
        console.print(f"[red]Login failed:[/red] {e}")
        raise typer.Exit(1)

    cfg = config.load()
    cfg.setdefault("auth", {})
    cfg["auth"]["github_token"] = token
    cfg["auth"]["github_handle"] = user["login"]
    cfg["auth"]["github_name"] = user.get("name") or user["login"]
    config.save(cfg)

    console.print(f"\n[bold green]Logged in as @{user['login']}[/bold green]")

    # Require Discord immediately if not set
    if not config.has_discord():
        console.print(
            "\n[bold]One more thing[/bold] — your Discord handle is required to complete setup."
        )
        discord = typer.prompt("Discord handle").strip().lstrip("@")
        while not discord:
            console.print("[red]Discord handle cannot be empty.[/red]")
            discord = typer.prompt("Discord handle").strip().lstrip("@")
        config.set_val("profile.discord", discord)
        console.print(f"[green]Discord set:[/green] @{discord}")

    console.print(
        "\nRun [bold cyan]swarm status[/bold cyan] to see your dashboard, "
        "or [bold cyan]swarm --help[/bold cyan] to explore commands."
    )


@app.command()
def logout() -> None:
    """Clear your local credentials."""
    if not config.is_logged_in():
        console.print("[dim]Not logged in.[/dim]")
        return
    handle = config.get("auth.github_handle")
    if typer.confirm(f"Log out @{handle}?", default=True):
        cfg = config.load()
        cfg.pop("auth", None)
        config.save(cfg)
        console.print("[dim]Logged out.[/dim]")


# ---------------------------------------------------------------------------
# swarm status
# ---------------------------------------------------------------------------

@app.command()
def status(
    refresh: Annotated[bool, typer.Option("--refresh", "-r", help="Force-refresh commit data")] = False,
) -> None:
    """Show your SWARM dashboard."""
    _require_login()
    _show_dashboard(refresh=refresh)


def _show_dashboard(refresh: bool = False) -> None:
    handle = config.get("auth.github_handle")
    name = config.get("auth.github_name")
    discord = config.get("profile.discord")
    telegram = config.get("profile.telegram")
    luma_email = config.get("profile.luma_email")
    repo_full = config.get("repo.full_name")
    repo_public = config.get("repo.is_public")
    title = f"[bold cyan]@{handle}[/bold cyan]"
    if name and name != handle:
        title += f"  [dim]{name}[/dim]"

    lines: list[str] = []

    # ── Profile ──
    if discord:
        lines.append(f"  [dim]Discord[/dim]   @{discord}")
    else:
        lines.append("  [dim]Discord[/dim]   [yellow]not set[/yellow] — run [bold]swarm profile edit[/bold]")
    if telegram:
        lines.append(f"  [dim]Telegram[/dim]  {telegram}")
    if luma_email:
        lines.append(f"  [dim]Email[/dim]     {luma_email}")
    lines.append("")

    # ── Repo + streak ──
    if repo_full:
        badge = "[green]public[/green]" if repo_public else "[red]private[/red]"
        lines.append(f"  [dim]Repo[/dim]  [bold]{repo_full}[/bold]  {badge}")

        data = _get_streak_data(force_refresh=refresh)
        if data:
            bar = streak.render_bar(data.get("weekly", {}))
            current = data.get("current", 0)
            longest = data.get("longest", 0)
            total = data.get("total", 0)
            color = streak.streak_color(current)
            lines.append(f"  [dim]{bar}[/dim]  [dim](12 wks)[/dim]")
            lines.append(
                f"  Streak [{color}]{current}d[/{color}]  "
                f"│ Longest [bold]{longest}d[/bold]  "
                f"│ Commits [bold]{total}[/bold]"
            )
        if not repo_public:
            lines.append("  [yellow]⚠ Consider making this repo public[/yellow]")
    else:
        lines.append("  [dim]No repo set.[/dim]  Run [bold]swarm repo set owner/repo[/bold]")

    lines.append("")

    # ── Recent updates ──
    recent = _recent_updates(5)
    if recent:
        lines.append("  [dim]Recent updates[/dim]")
        for u in recent:
            kind = u.get("kind", "")
            kind_label = "[cyan]product[/cyan] " if kind == "product" else "[green]traction[/green]"
            date_label = f"[dim]{_fmt_date(u.get('date'))}[/dim]"
            text = u.get("text", "")
            snippet = (text[:80] + "…") if len(text) > 80 else text
            lines.append(f"  {kind_label}  {date_label}  {snippet}")
    else:
        lines.append(
            "  [dim]No updates yet.[/dim]  "
            "Run [bold]swarm update traction[/bold] or [bold]swarm update product[/bold]"
        )

    lines.append("")
    lines.append(
        "  [dim]swarm update-traction[/dim] · [dim]swarm update-product[/dim]"
    )

    console.print(Panel("\n".join(lines), title=title, border_style="cyan", padding=(0, 1)))


# ---------------------------------------------------------------------------
# swarm ls / swarm history
# ---------------------------------------------------------------------------

@app.command("ls")
def ls(
    kind: Annotated[str, typer.Argument(help="traction | product | all")] = "all",
) -> None:
    """List all updates (traction and product)."""
    _require_login()
    _print_all_updates(kind, full=True)


@app.command("history")
def history(
    kind: Annotated[str, typer.Argument(help="traction | product | all")] = "all",
) -> None:
    """List all updates (alias for swarm ls)."""
    _require_login()
    _print_all_updates(kind, full=True)


@app.command("update-traction")
def update_traction_shortcut() -> None:
    """Shortcut for swarm update traction."""
    _require_login()
    _require_discord()
    update_traction()


@app.command("update-product")
def update_product_shortcut() -> None:
    """Shortcut for swarm update product."""
    _require_login()
    _require_discord()
    update_product()


def _print_all_updates(kind: str, full: bool = False) -> None:
    traction = config.get("updates.traction") or []
    product = config.get("updates.product") or []

    if kind == "traction":
        updates = [{"kind": "traction", **u} for u in traction]
    elif kind == "product":
        updates = [{"kind": "product", **u} for u in product]
    else:
        updates = (
            [{"kind": "traction", **u} for u in traction]
            + [{"kind": "product", **u} for u in product]
        )

    updates = sorted(updates, key=lambda u: u.get("date", ""), reverse=True)
    _print_updates(updates, full=full)


# ---------------------------------------------------------------------------
# swarm profile
# ---------------------------------------------------------------------------

@profile_app.callback(invoke_without_command=True)
def _profile_root(ctx: typer.Context) -> None:
    """View and edit your profile."""
    if ctx.invoked_subcommand is None:
        _require_login()
        _profile_show()


def _profile_show() -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim")
    table.add_column()
    table.add_row("GitHub", f"@{config.get('auth.github_handle')}")
    name = config.get("auth.github_name")
    if name:
        table.add_row("Name", name)
    discord = config.get("profile.discord")
    table.add_row("Discord", f"@{discord}" if discord else "[yellow]not set[/yellow]")
    telegram = config.get("profile.telegram")
    if telegram:
        table.add_row("Telegram", telegram)
    email = config.get("profile.luma_email")
    if email:
        table.add_row("Luma email", email)
    console.print(Panel(table, title="[bold]Profile[/bold]", border_style="cyan"))


@profile_app.command("edit")
def profile_edit() -> None:
    """Edit your Discord handle, Telegram, and Luma email."""
    _require_login()

    console.print("[bold]Edit profile[/bold]  [dim](Enter to keep current value, '-' to clear optional fields)[/dim]\n")

    # Discord (required)
    cur = config.get("profile.discord") or ""
    val = typer.prompt("Discord handle", default=cur).strip().lstrip("@")
    if not val:
        console.print("[red]Discord handle is required.[/red]")
        raise typer.Exit(1)
    config.set_val("profile.discord", val)

    # Telegram (optional)
    cur = config.get("profile.telegram") or ""
    val = typer.prompt("Telegram (optional, '-' to clear)", default=cur).strip()
    if val == "-":
        config.set_val("profile.telegram", None)
    elif val:
        config.set_val("profile.telegram", val if val.startswith("@") else f"@{val}")

    # Luma email (optional)
    cur = config.get("profile.luma_email") or ""
    val = typer.prompt("Luma invite email (optional, '-' to clear)", default=cur).strip()
    if val == "-":
        config.set_val("profile.luma_email", None)
    elif val:
        config.set_val("profile.luma_email", val)

    console.print("\n[green]Profile updated.[/green]")



# ---------------------------------------------------------------------------
# swarm repo
# ---------------------------------------------------------------------------

@repo_app.callback(invoke_without_command=True)
def _repo_root(ctx: typer.Context) -> None:
    """Show repo activity and streak."""
    if ctx.invoked_subcommand is None:
        _require_login()
        _repo_status()


def _repo_status(refresh: bool = False) -> None:
    repo_full = config.get("repo.full_name")
    if not repo_full:
        console.print("[dim]No repo set.[/dim]  Run [bold]swarm repo set owner/repo[/bold]")
        return

    is_public = config.get("repo.is_public")
    badge = "[green]public[/green]" if is_public else "[red]private[/red]"

    data = _get_streak_data(force_refresh=refresh)
    if not data:
        console.print("[yellow]Could not fetch commit data.[/yellow]")
        return

    bar = streak.render_bar(data.get("weekly", {}))
    current = data.get("current", 0)
    longest = data.get("longest", 0)
    total = data.get("total", 0)
    last_commit = data.get("last_commit")
    color = streak.streak_color(current)

    lines = [
        f"  {repo_full}  {badge}",
        "",
        f"  [bold]{bar}[/bold]",
        f"  [dim]← 12 weeks ago                  now →[/dim]",
        "",
        f"  [dim]Current streak[/dim]  [{color}]{current} days[/{color}]",
        f"  [dim]Longest streak[/dim]  [bold]{longest} days[/bold]",
        f"  [dim]Total commits[/dim]   [bold]{total}[/bold]",
    ]
    if last_commit:
        lines.append(f"  [dim]Last commit[/dim]     {_fmt_date(str(last_commit))}")
    if not is_public:
        lines.extend([
            "",
            "  [yellow]⚠ This repo is private.[/yellow]",
            "  [dim]Making it public lets the cohort see your progress.[/dim]",
        ])

    console.print(Panel("\n".join(lines), title="[bold]Repo Activity[/bold]", border_style="green"))


@repo_app.command("set")
def repo_set(
    repo: str = typer.Argument(..., help="owner/repo or full GitHub URL"),
) -> None:
    """Set your primary work repo."""
    _require_login()

    try:
        owner, repo_name = github.parse_repo_input(repo)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    token = config.get("auth.github_token")
    with console.status(f"Checking {owner}/{repo_name}..."):
        repo_data = github.get_repo(token, owner, repo_name)

    if repo_data is None:
        console.print(f"[red]Repo not found:[/red] {owner}/{repo_name}")
        raise typer.Exit(1)

    is_public = not repo_data.get("private", True)
    full_name = repo_data["full_name"]

    config.set_val("repo.full_name", full_name)
    config.set_val("repo.url", repo_data["html_url"])
    config.set_val("repo.is_public", is_public)
    config.set_val("cache.streak", None)

    console.print(f"[green]Repo set:[/green] {full_name}")

    if not is_public:
        console.print(
            "\n[yellow]⚠ This repo is private.[/yellow]\n"
            "  We recommend making it public so your work is visible.\n"
            f"  [dim]{repo_data['html_url']}/settings → Danger Zone → Change visibility[/dim]"
        )


# ---------------------------------------------------------------------------
# swarm update
# ---------------------------------------------------------------------------

@update_app.callback(invoke_without_command=True)
def _update_root(ctx: typer.Context) -> None:
    """Show recent updates, or submit a new one."""
    if ctx.invoked_subcommand is None:
        _require_login()
        console.print(
            "  [bold]swarm update-traction[/bold]  submit a traction update\n"
            "  [bold]swarm update-product[/bold]   submit a product update\n"
        )
        _print_all_updates("all")


@update_app.command("traction")
def update_traction() -> None:
    """Submit a traction update — who's interested, who's using it."""
    _require_login()
    _require_discord()

    console.print("[bold]Traction Update[/bold]")
    console.print(
        "[dim]How many users have expressed interest? Who is using it? Give examples.[/dim]\n"
    )

    text = _get_multiline_text(
        "How many users have expressed interest in your product? "
        "Explain who and give examples. Who is using it currently?"
    )
    if not text:
        console.print("[yellow]No update submitted.[/yellow]")
        return

    updates: list = config.get("updates.traction") or []
    updates.append({"date": datetime.now(timezone.utc).isoformat(), "text": text})
    config.set_val("updates.traction", updates)
    console.print("\n[green]Traction update saved.[/green]")


@update_app.command("product")
def update_product() -> None:
    """Submit a product update — what you've shipped. Include a Loom if you have one."""
    _require_login()
    _require_discord()

    console.print("[bold]Product Update[/bold]")
    console.print(
        "[dim]What have you shipped? Include a Loom link in your update if you have one.[/dim]\n"
    )

    text = _get_multiline_text(
        "What have you shipped since your last update? "
        "Paste a Loom link (loom.com/share/...) if you have one — "
        "then describe the new features."
    )
    if not text:
        console.print("[yellow]No update submitted.[/yellow]")
        return

    updates: list = config.get("updates.product") or []
    updates.append({"date": datetime.now(timezone.utc).isoformat(), "text": text})
    config.set_val("updates.product", updates)
    console.print("\n[green]Product update saved.[/green]")
