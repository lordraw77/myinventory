# Deployment recipes

Scheduling, container and notification recipes for running `myinventory`
unattended. See [`docs/operations.md`](../docs/operations.md) for the full guide.

| File | Purpose |
|---|---|
| [`myinventory.service`](myinventory.service) | systemd oneshot unit that runs `report --html` |
| [`myinventory.timer`](myinventory.timer) | systemd timer firing the service nightly |
| [`crontab.example`](crontab.example) | cron equivalent for non-systemd hosts |
| [`../Dockerfile`](../Dockerfile) | container image bundling all backends + `d2` |

## Concurrency

Every scheduled mechanism leans on the CLI's own lockfile
(`<out>/.myinventory.lock`): a long-running scan that overruns its schedule makes
the next trigger back off (exit code 3) rather than run a second scan over the
same output directory. A lock left by a crashed run is detected (its PID is gone)
and reclaimed automatically. Pass `--no-lock` only for ad-hoc manual runs.

## Secrets

Never inline credentials. Put them in an env file (`chmod 600`) and reference
them from the config as `env:NAME` (or `file:/path`). The systemd unit reads
`/etc/myinventory/secrets.env`; the cron recipe sources it inline.
