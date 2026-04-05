# SWARM CLI

Track your startup progress with your cohort.

## Installation

```bash
uv tool install git+https://github.com/the-canteen-dev/SWARM-cli.git
```

## Upgrade

```bash
uv tool install --reinstall git+https://github.com/the-canteen-dev/SWARM-cli.git
```

## Commands

### Top-level

| Command | Description |
|---|---|
| `swarm` | Show your dashboard (default when no subcommand given) |
| `swarm login` | Authenticate with GitHub and set up your profile |
| `swarm logout` | Clear your local credentials |
| `swarm status [-r]` | Show your SWARM dashboard (`-r` / `--refresh` to force-refresh commit data) |
| `swarm push` | Push any queued local events to the SWARM server |
| `swarm ls [traction\|product\|all]` | List all updates |
| `swarm history [traction\|product\|all]` | List all updates (alias for `ls`) |
| `swarm profile-edit` | Shortcut for `swarm profile edit` |
| `swarm update-traction` | Shortcut for `swarm update traction` |
| `swarm update-product` | Shortcut for `swarm update product` |

### `swarm profile`

| Command | Description |
|---|---|
| `swarm profile` | View your profile |
| `swarm profile edit` | Edit your Discord handle, Telegram, and Luma email |

### `swarm repo`

| Command | Description |
|---|---|
| `swarm repo` | Show repo activity and commit streak |
| `swarm repo set <owner/repo>` | Set your primary work repo (accepts `owner/repo` or full GitHub URL) |

### `swarm update`

| Command | Description |
|---|---|
| `swarm update` | Show recent traction and product updates |
| `swarm update traction` | Submit a traction update — who's interested, who's using it |
| `swarm update product` | Submit a product update — what you've shipped (include a Loom link if you have one) |
