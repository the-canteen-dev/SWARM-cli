"""GitHub API helpers."""

import httpx
from typing import Optional


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_repo(token: str, owner: str, repo: str) -> Optional[dict]:
    """Returns repo data dict, or None if not found."""
    resp = httpx.get(
        f"https://api.github.com/repos/{owner}/{repo}",
        headers=_headers(token),
        timeout=10,
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def get_commits(token: str, owner: str, repo: str, max_commits: int = 500) -> list:
    """Fetch up to max_commits recent commits from a repo."""
    commits = []
    page = 1
    per_page = 100

    while len(commits) < max_commits:
        resp = httpx.get(
            f"https://api.github.com/repos/{owner}/{repo}/commits",
            params={"per_page": per_page, "page": page},
            headers=_headers(token),
            timeout=15,
        )
        if resp.status_code in (404, 409):  # not found or empty repo
            break
        resp.raise_for_status()
        data = resp.json()
        if not data:
            break
        commits.extend(data)
        if len(data) < per_page:
            break
        page += 1

    return commits[:max_commits]


def parse_repo_input(repo_input: str) -> tuple[str, str]:
    """Parse 'owner/repo' or full GitHub URL into (owner, repo)."""
    s = repo_input.strip().rstrip("/")
    if "github.com" in s:
        s = s.split("github.com/")[-1].split("?")[0]
    if "/" in s:
        parts = s.split("/")
        if len(parts) >= 2:
            return parts[0], parts[1]
    raise ValueError(
        f"Could not parse repo: {repo_input!r}\n"
        "Expected format: owner/repo  or  https://github.com/owner/repo"
    )
