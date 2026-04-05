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
team_app = typer.Typer(help="Manage teammates.", no_args_is_help=True)
repo_app = typer.Typer(help="Track your primary repo.", no_args_is_help=False)
update_app = typer.Typer(help="Submit traction and product updates.", no_args_is_help=True)

app.add_typer(profile_app, name="profile")
app.add_typer(team_app, name="team")
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


def _fmt_date(date_str: Optional[str]) -> str:
    if not date_str:
        return "unknown"
    try:
        dt = datetime.fromisoformat(str(date_str))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        days = delta.days
        if days == 0:
            h = delta.seconds // 3600
            return "just now" if h == 0 else f"{h}h ago"
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
    """Open $EDITOR for multiline input; fall back to a single prompt."""
    import click

    template = f"\n\n# {hint}\n# (Lines starting with # are ignored. Save and close when done.)\n"
    try:
        result = click.edit(template)
        if result is None:
            return None
        lines = [ln for ln in result.splitlines() if not ln.startswith("#")]
        text = "\n".join(lines).strip()
        return text or None
    except Exception:
        console.print(f"[dim]({hint})[/dim]")
        text = typer.prompt("Enter text").strip()
        return text or None


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
    teammates: list = config.get("teammates") or []

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

    # ── Teammates ──
    if teammates:
        team_str = "  ".join(f"@{t}" for t in teammates)
        lines.append(f"  [dim]Team[/dim]  {team_str}")
        lines.append("")

    # ── Updates ──
    traction = config.get("updates.traction") or []
    product = config.get("updates.product") or []

    if traction:
        lines.append(f"  [dim]Traction update[/dim]  {_fmt_date(traction[-1].get('date'))}")
    else:
        lines.append("  [dim]No traction update.[/dim]  Run [bold]swarm update traction[/bold]")

    if product:
        lines.append(f"  [dim]Product update[/dim]   {_fmt_date(product[-1].get('date'))}")
    else:
        lines.append("  [dim]No product update.[/dim]   Run [bold]swarm update product[/bold]")

    console.print(Panel("\n".join(lines), title=title, border_style="cyan", padding=(0, 1)))


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
# swarm team
# ---------------------------------------------------------------------------

@team_app.callback(invoke_without_command=True)
def _team_root(ctx: typer.Context) -> None:
    """List and manage teammates."""
    if ctx.invoked_subcommand is None:
        _require_login()
        _team_list()


def _team_list() -> None:
    teammates: list = config.get("teammates") or []
    if not teammates:
        console.print("[dim]No teammates added yet.[/dim]  Run [bold]swarm team add <handle>[/bold]")
        return
    for t in teammates:
        console.print(f"  @{t}")


@team_app.command("add")
def team_add(handle: str = typer.Argument(..., help="GitHub handle to add")) -> None:
    """Add a teammate by GitHub handle."""
    _require_login()
    handle = handle.lstrip("@")
    teammates: list = config.get("teammates") or []
    if handle in teammates:
        console.print(f"[yellow]@{handle} already in team.[/yellow]")
        return
    teammates.append(handle)
    config.set_val("teammates", teammates)
    console.print(f"[green]Added @{handle}[/green]")


@team_app.command("remove")
def team_remove(handle: str = typer.Argument(..., help="GitHub handle to remove")) -> None:
    """Remove a teammate."""
    _require_login()
    handle = handle.lstrip("@")
    teammates: list = config.get("teammates") or []
    if handle not in teammates:
        console.print(f"[yellow]@{handle} not in team.[/yellow]")
        return
    teammates.remove(handle)
    config.set_val("teammates", teammates)
    console.print(f"[dim]Removed @{handle}[/dim]")


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


@repo_app.command("status")
def repo_status(
    refresh: Annotated[bool, typer.Option("--refresh", "-r")] = False,
) -> None:
    """Show commit streak and activity for your repo."""
    _require_login()
    _repo_status(refresh=refresh)


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
    config.set_val("cache.streak", None)  # invalidate cache

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

@update_app.command("traction")
def update_traction() -> None:
    """Submit a traction update (users, interest, examples)."""
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
    """Submit a product update (new features, Luma or other link)."""
    _require_login()
    _require_discord()

    console.print("[bold]Product Update[/bold]")
    console.print("[dim]What have you shipped since your last update?[/dim]\n")

    link = typer.prompt(
        "Link (Luma event, demo, etc. — optional, press Enter to skip)",
        default="",
    ).strip()

    text = _get_multiline_text(
        "What new features have you added since your last update?"
    )

    if not text and not link:
        console.print("[yellow]No update submitted.[/yellow]")
        return

    entry: dict = {"date": datetime.now(timezone.utc).isoformat()}
    if link:
        entry["link"] = link
    if text:
        entry["text"] = text

    updates: list = config.get("updates.product") or []
    updates.append(entry)
    config.set_val("updates.product", updates)
    console.print("\n[green]Product update saved.[/green]")


@update_app.command("history")
def update_history(
    kind: Annotated[str, typer.Argument(help="traction | product | all")] = "all",
) -> None:
    """View recent update history."""
    _require_login()

    if kind in ("traction", "all"):
        items = config.get("updates.traction") or []
        console.print("[bold]Traction Updates[/bold]" if items else "[dim]No traction updates yet.[/dim]")
        for u in list(reversed(items))[:5]:
            console.print(f"\n  [dim]{_fmt_date(u.get('date'))}[/dim]")
            text = u.get("text", "")
            console.print(f"  {text[:300]}{'…' if len(text) > 300 else ''}")

    if kind in ("product", "all"):
        if kind == "all":
            console.print()
        items = config.get("updates.product") or []
        console.print("[bold]Product Updates[/bold]" if items else "[dim]No product updates yet.[/dim]")
        for u in list(reversed(items))[:5]:
            console.print(f"\n  [dim]{_fmt_date(u.get('date'))}[/dim]")
            if u.get("link"):
                console.print(f"  [cyan]{u['link']}[/cyan]")
            text = u.get("text", "")
            if text:
                console.print(f"  {text[:300]}{'…' if len(text) > 300 else ''}")
