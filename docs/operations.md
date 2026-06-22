# Operations

Running `myinventory` unattended: scheduling, locking, change notifications, the
static HTML site, multi-site profiles and the container image. This is the
Milestone 6 ("operability & polish") surface; for the day-to-day commands see
[usage.md](usage.md).

## Scheduling

A census is most useful run on a schedule so `diff`, the changelog and stale-host
detection accumulate history. Ready-made recipes live in
[`deploy/`](../deploy/).

### systemd timer (recommended)

```bash
sudo cp deploy/myinventory.service deploy/myinventory.timer /etc/systemd/system/
sudo mkdir -p /etc/myinventory /var/lib/myinventory
sudo cp myinventory.yaml /etc/myinventory/config.yaml
sudo install -m600 /dev/stdin /etc/myinventory/secrets.env <<'EOF'
PROXMOX_TOKEN=...
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now myinventory.timer
systemctl list-timers myinventory.timer      # confirm the next run
```

The unit runs `report --html` as a hardened `DynamicUser` oneshot
(`ProtectSystem=strict`, writing only its `StateDirectory`). Edit `OnCalendar`
in the timer to change the cadence.

### cron

For hosts without systemd, [`deploy/crontab.example`](../deploy/crontab.example)
sources the secrets file inline and runs the same `report --html`.

## The scan lockfile

`scan` and `report` take an advisory lockfile at `<out>/.myinventory.lock` for
the duration of the run. If a scheduled scan overruns its interval, the next
trigger finds the lock held by a live process and **backs off** (exit code 3)
instead of running a second scan over the same output directory and corrupting
the snapshot/merge sequence.

A lock left behind by a crashed scan records that process's PID; when the PID is
no longer alive the next run detects the stale lock and reclaims it
automatically, so a crash never wedges the schedule.

Pass `--no-lock` to skip it — only sensible for an ad-hoc manual run you know is
not racing the scheduler.

## Change notifications

With a [`notifications`](configuration.md#notifications) block enabled, each scan
diffs itself against the previous snapshot and, when something changed, posts a
summary to every configured webhook and emails it. Channels are best-effort: a
failing webhook or SMTP server is reported on stderr and recorded as a scan
error, never aborting the run.

- **Webhook** — `format: slack` posts `{"text": ...}` for Slack/Mattermost
  incoming webhooks; `format: json` posts `{title, summary, body, diff}` (the
  `diff` is the same structure as `myinventory diff --json`) for your own
  consumers.
- **Email** — plain-text (the change summary) over SMTP, STARTTLS optional.

The first scan against an empty history never notifies — there is nothing to
compare yet. Set `on_change_only: false` to get a summary after every scan.

## HTML site

`render --html` (and `report --html`) writes a self-contained static site under
`<out>/site/`: an `index.html` with the summary and subnet tables, a page per
host, and a shared stylesheet. When the [`d2`](https://d2lang.com) binary is on
`PATH`, the network diagram is compiled to SVG and embedded on the index;
without it the site still builds, just without the picture.

```bash
myinventory render -i ./out/inventory.json -o ./out --html
python -m http.server -d ./out/site 8080      # preview locally
```

The site is plain files — serve it with any web server, or publish `out/site/`
to GitHub Pages / an S3 bucket / an internal share.

## Multiple sites (profiles)

One config file can describe several estates via
[`profiles`](configuration.md#profiles-and-site); select one per run with
`--profile`:

```bash
myinventory report -c sites.yaml --profile home   -o ./out/home   --html
myinventory report -c sites.yaml --profile office -o ./out/office --html
```

Give each profile its own `-o` output directory so their inventories and history
stay separate. The profile name flows through to the HTML title and notification
subjects as the `site` label.

## Container image

The [`Dockerfile`](../Dockerfile) builds an image with every optional backend
and the `d2` binary, running as an unprivileged user:

```bash
docker build -t myinventory .
docker run --rm --network host \
  -v "$PWD/myinventory.yaml:/etc/myinventory/config.yaml:ro" \
  -v "$PWD/out:/var/lib/myinventory/out" \
  -e PROXMOX_TOKEN \
  myinventory report -c /etc/myinventory/config.yaml -o /var/lib/myinventory/out --html
```

`--network host` lets the LAN sweeps reach the local segment (ARP/ICMP in
particular need it). Mount the config read-only and the output directory
read-write; pass secrets as `-e NAME` env vars referenced as `env:NAME`.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | no command / usage error |
| 2 | config error (bad file, missing secret, unknown profile) |
| 3 | lock held by another running scan |

Per-target failures during a scan are **not** fatal — they are printed to stderr
and recorded, and the scan still produces output for everything that worked.
