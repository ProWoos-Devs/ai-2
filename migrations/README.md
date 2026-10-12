# Migrations

A migration is a small script that finishes an update for the account that runs it. A package upgrade replaces the files the package owns and nothing else; what it cannot reach is a user's own state under the home directory. A migration is how a release repairs that, once per account, instead of leaving it to a FAQ entry.

`ai-2 update` runs the pending ones after a successful upgrade. Every graphical login runs them for the account logging in, silently, with a record in `~/.local/state/ai2/migrate.log`, so an update made through Software Updates or a plain pacman is finished at the next login. `ai-2 migrate` runs them by hand and `ai-2 migrate --pending` lists what is waiting; `ai-2 doctor` reports them too.

## Rules

- **Only the running user's own files.** A migration never needs a password and never touches `/etc`, `/usr` or another account. Anything system-wide is a pacman hook (`packaging/ai-2/*.hook`, run as root inside the transaction; `etc-refresh.sh` is the example).
- **Idempotent.** Check the state before changing it. Running a migration twice must be harmless, because a half-run one is rerun.
- **One sentence first.** The first line is a comment saying what the script does. It is what the user sees, after `ok` or `FAIL`.
- **Name order is run order.** `YYYYMMDD-NN-what-it-does.sh`, the date it was written, a two-digit sequence within that day, lowercase words with hyphens. They stop at the first failure, which stays pending with the ones after it.
- **No shebang, mode 644.** The runner executes `bash -euo pipefail FILE` from the home directory. Keep to what bash and coreutils offer; no `ai-2` subcommands inside a migration, because the account's state is exactly what they would read.
- **Say what changed, or nothing.** `echo` one short line when something was done; stay silent when there was nothing to do.

## What the script gets

| Variable | Value |
|---|---|
| `AI2_STATE_DIR` | `~/.local/state/ai2` (honoring `XDG_STATE_HOME`) |
| `AI2_CONFIG_DIR` | `~/.config/ai2` (honoring `XDG_CONFIG_HOME`) |
| `AI2_DATA_DIR` | `~/.local/share/ai2` (honoring `XDG_DATA_HOME`) |
| `AI2_VERSION` | the `ai-2` version running it |

## Trying one

```
HOME=$(mktemp -d) AI2_STATE_DIR=$HOME/.local/state/ai2 AI2_CONFIG_DIR=$HOME/.config/ai2 \
  AI2_DATA_DIR=$HOME/.local/share/ai2 AI2_VERSION=test bash -euo pipefail migrations/NAME.sh
```

To run one again on a real account, delete its marker in `~/.local/state/ai2/migrations/` and run `ai-2 migrate`. The test suite runs every shipped migration twice against an empty home and refuses a name, a shebang or a missing first-line comment that breaks the rules.
