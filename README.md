# WaniFi

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-FFDD00?logo=buymeacoffee&logoColor=000)](https://buymeacoffee.com/thehef)

Self-hosted dashboard for UniFi WAN failover monitoring with rule-based automation.

When your UniFi gateway switches to a failover WAN, WaniFi can automatically
stop/start Docker containers or run host commands. Handy for things like
pausing qBittorrent on 5G failover so you don't burn through mobile data.

> **Heads up: this is a beta hobby project.**
>
> I'm not a developer or engineer by trade, just a UniFi user who needed
> something like this and couldn't find it. So I built it for myself and
> figured I'd share it in case anyone else is in the same boat. Expect rough
> edges, missing features, and code that an actual engineer would probably
> rewrite.
>
> Not affiliated with Ubiquiti in any way. Just a UniFi user (and fan).

![Overview](docs/screenshots/overview.png)

## Features

- 📡 Polls a UniFi controller (UDM / UCG / UX) via the official API key
- 🐳 Controls Docker containers through the host's Docker socket
- 💻 Runs arbitrary shell commands on the Docker host (via `nsenter`)
- 🔁 Rule triggers: `failover`, `restored`, `down`, `high_latency`
- 📈 Live throughput / latency graphs with 1h to 30d ranges
- 🔔 Optional ntfy push notifications
- 🔐 Single-user login (bcrypt; first-run setup wizard)
- 💾 SQLite, no other services required

## Quick start

Create a folder for WaniFi, drop in a `compose.yaml`, and start it:

```bash
mkdir wanifi && cd wanifi
mkdir -p data
curl -O https://raw.githubusercontent.com/TheHef/WaniFI/main/compose.yaml
docker compose up -d
```

That's it. Docker pulls the pre-built image from GitHub Container Registry
(`ghcr.io/thehef/wanifi`) and starts it on port `8765`. Open
`http://<docker-host>:8765` in a browser.

### compose.yaml

If you'd rather paste it yourself:

```yaml
name: wanifi

services:
  wanifi:
    image: ghcr.io/thehef/wanifi:latest
    container_name: wanifi
    restart: unless-stopped
    ports:
      - "8765:8000"
    environment:
      TZ: "Europe/Copenhagen"
    privileged: true
    pid: host
    volumes:
      - ./data:/data
      - /var/run/docker.sock:/var/run/docker.sock
```

> `privileged: true` and `pid: host` are required so WaniFi can run host
> commands via `nsenter`. If you don't need host commands you can drop them
> both and stick to Docker container rules.

To update later: `docker compose pull && docker compose up -d`.

## Setup

### 1. Pick an admin password

On first visit you'll be redirected to `/setup` to choose an admin password.
The bcrypt hash is stored in the local SQLite database, no env vars needed.

### 2. Configure your UniFi controller

In the WaniFi UI go to **Settings**:

- **Controller URL:** `https://<your-UCG-or-UDM-IP>`
- **API Key:** generate one in UniFi OS → Settings → Control Plane →
  Integrations → API Keys (requires UniFi OS 3.x+)
- Click **Test Connection** and your WAN interfaces appear as draggable chips
- Drop one chip into **Primary WAN** and another into **Failover WAN**
- Give them friendly names and hit **Save**

![Settings](docs/screenshots/settings.png)

### 3. Add rules

Rules tie a WAN event to an action. Examples:

- `qbittorrent` · *On failover* · *Pause container*
- `qbittorrent` · *On restored* · *Unpause container*
- Host command · *On high latency* · `systemctl restart smokeping`

![Rules](docs/screenshots/rules.png)

## Events

Every state change, rule firing, error and manual action is logged. Filter
by level or search the message column; deletion is per-row or all-at-once.

![Events](docs/screenshots/events.png)

## Building from source

If you'd rather hack on the code instead of using the published image:

```bash
git clone https://github.com/TheHef/WaniFI.git
cd WaniFI
docker build -t wanifi:local .
```

Then point the `image:` field in your `compose.yaml` at `wanifi:local` and
run `docker compose up -d`.

## Architecture

```
app/
  main.py          FastAPI app, lifespan, router wiring
  config.py        constants, logging, paths
  db.py            SQLite + settings cache + async helpers
  auth.py          session tokens + first-run setup
  unifi.py         UniFi Network API client
  docker_ops.py    Docker singleton + container actions
  notify.py        ntfy push notifications
  watcher.py       background polling + rule firing loops
  models.py        Pydantic request models
  routes/          one APIRouter per concern
    auth.py system.py rules.py settings.py
    events.py manual.py notify.py
  static/
    css/style.css
    js/app.js           Alpine.js SPA logic
    js/charts.js        Chart.js wrappers
    js/device-icons.js  UniFi model to icon/name maps
    devices/            device images
  templates/
    base.html app.html login.html setup.html
    partials/_header.html dashboard.html rules.html
             settings.html events.html _modals.html
```

A background task polls the UniFi controller, updates live stats for the
dashboard every 2 seconds, and detects WAN state changes to fire your rules.

## Security notes

> ⚠️ **LAN only. Do not expose this to the public internet.**
>
> WaniFi needs root-equivalent access to your Docker host to function
> (`privileged: true`, `pid: host`, mounted Docker socket). It is built to
> live behind your firewall on a trusted LAN and nothing else. There is no
> rate limiting, no MFA, no audit logging, and the host-command feature lets
> the admin run arbitrary shell as root. If you absolutely must reach it
> from outside, use a VPN (WireGuard, Tailscale). Do **not** port-forward
> `8765`, and do **not** stick it directly behind a reverse proxy without
> additional authentication. You have been warned.

WaniFi is designed to run **inside your network**, full stop. The threat
model assumes only trusted users can reach the UI.

- **Root on the host.** The container runs with `privileged: true`,
  `pid: host`, and a mounted Docker socket so it can use `nsenter` for
  host-command rules and the Docker API for container actions. Anyone with
  admin access to the WaniFi UI effectively has root on your Docker host.
- **Single-user auth, no MFA, no rate limiting.** The login is one bcrypt
  password and nothing else. Brute-force protection, IP allowlisting, audit
  logging — none of that is in here.
- **Arbitrary shell execution by design.** The "Host Command" rule type
  runs whatever string you type, as root, on the host. That is the feature.
  It is also why this should never be reachable from the public internet.
- **Do not port-forward 8765.** Do not place it behind a reverse proxy
  exposed to the internet, even with HTTPS. If you need remote access, use
  a VPN (WireGuard, Tailscale, etc.) so the WaniFi UI stays on a private
  network where it belongs.
- **Backup `data/wanifi.db`.** It contains your UniFi API key, ntfy token,
  and the bcrypt password hash. It is the only secret store.

## Updating

```bash
docker compose pull
docker compose up -d
```

Schema migrations run automatically on startup. New image versions are
published to `ghcr.io/thehef/wanifi` on every push to `main`.

## Troubleshooting

- **Stuck on `/setup` after restart:** the bcrypt hash lives in
  `data/wanifi.db`. If the bind mount is wrong it'll keep regenerating.
- **WAN detection wrong:** click **Debug** in Settings to dump live UniFi
  data to the browser console; verify your `primary_wan` / `failover_wan`
  match the `subsystem` field shown in the discovered chips.
- **Container `not found`:** rule containers must match `docker ps` names,
  not Compose service names.

## Support

If WaniFi saved you some 5G data or just made your homelab a little nicer,
you can [buy me a coffee](https://buymeacoffee.com/thehef). Completely
optional, deeply appreciated.

## License

MIT. See [LICENSE](LICENSE).

## Trademarks

UniFi product names and device images shown in the UI are trademarks of
Ubiquiti Inc. They are used here only to identify the hardware your
controller reports, with no implied endorsement or affiliation.
