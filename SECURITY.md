# Security

## Reporting

Please report privately through
[GitHub's advisory form](https://github.com/muhzuhaib/willitbite/security/advisories/new)
rather than opening a public issue. I will confirm receipt, and I will say
plainly if I cannot fix something.

## What this tool can reach

It is worth knowing how small the exposure is.

- **It only ever reads, locally.** It reads the Python files under the path you
  point it at, and in `--json` mode it reads the warnings file you hand it.
  Nothing is sent anywhere, nothing is cached to disk, and no telemetry is
  collected.
- **It shells out to `ruff` when ruff is on your `PATH`.** This is the one
  honest supply-chain note: the tool executes whatever `ruff` resolves to on
  your machine, so an attacker who controls your `PATH` controls what runs.
  If you would rather not allow that, run ruff yourself and pass the JSON file
  to `willitbite --json` instead; that mode never launches anything.
- **No tokens, no credentials.** There is nothing to leak because there is
  nothing to authenticate with.

## Supported versions

The latest release. This is a small tool with no runtime dependencies, so the
practical advice for any problem is to upgrade.
