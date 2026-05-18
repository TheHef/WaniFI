# WaniFi

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-FFDD00?logo=buymeacoffee&logoColor=000)](https://buymeacoffee.com/thehef)

Self-hosted dashboard for UniFi WAN failover monitoring with rule-based automation.

When your UniFi gateway switches to a failover WAN, WaniFi can automatically
stop/start Docker containers, throttle downloads, or cap streaming bitrate
on media servers. Handy for keeping 5G failover costs under control.

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
- 🔁 Rule triggers: `failover`, `restored`, `down`, `high_latency`
- 📈 Live throughput / latency graphs with 1h to 30d ranges
- 🔐 Single-user login (bcrypt; first-run setup wizard)
- 💾 SQLite, no other services required

## Tools

All tools are opt-in and can be toggled on/off individually in Settings → Tools.

| Tool | Actions |
|---|---|
| **Host Command** | Runs arbitrary shell commands on the Docker host via `nsenter` (requires `privileged: true` + `pid: host`) |
| **Docker** | Stop, start, restart, pause, unpause containers via the mounted Docker socket |
| **qBittorrent** | Enable/disable alt speed, set download/upload limit, pause/resume all torrents |
| **Emby** | Set bitrate limit, clear bitrate limit, stop all sessions |
| **Jellyfin** | Set bitrate limit, clear bitrate limit, stop all sessions |
| **Plex** | Set bitrate limit, clear bitrate limit, stop all streams |
| **ntfy** | Push notifications on failover, restore, high latency, and watcher errors |

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
services:
  wanifi:
    image: ghcr.io/thehef/wanifi:latest
    container_name: wanifi
    restart: unless-stopped
    ports:
      - "8765:8000"
    environment:
      TZ: "Europe/Copenhagen"
      PORT: "8000"
    privileged: true
    pid: host
    extra_hosts:
      - "host.docker.internal:host-gateway"
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

### 3. Enable tools

Go to **Settings → Tools** and toggle on the tools you want to use. Each tool exposes its own config section (URL, credentials) once enabled.

### 4. Add rules

Each rule pairs a **trigger** with an **action**. Triggers fire on `failover`, `restored`, `down`, or `high_latency`. Actions depend on which tools you have enabled:

| Tool | Available actions |
|---|---|
| **Docker** | Stop, start, restart, pause, unpause a named container |
| **Host Command** | Run any shell command as root on the Docker host |
| **qBittorrent** | Enable/disable alt speed, set download/upload limit, pause/resume all torrents |
| **Emby** | Set bitrate limit, clear bitrate limit, stop all sessions |
| **Jellyfin** | Set bitrate limit, clear bitrate limit, stop all sessions |
| **Plex** | Set bitrate limit, clear bitrate limit, stop all streams |

Example setup for a 5G failover scenario:

| Rule | Trigger | Action |
|---|---|---|
| Slow QB | On failover | qBittorrent: enable alt speed |
| Normal QB | On restored | qBittorrent: disable alt speed |
| Limit Streams | On failover | Plex: limit remote bitrate 4 Mbps |
| Unlimit Streams | On restored | Plex: clear remote bitrate limit |

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

## Security notes

> ⚠️ **LAN only — do not expose to the public internet.**

WaniFi runs with `privileged: true`, `pid: host`, and a mounted Docker socket. Anyone who can reach the UI can effectively run arbitrary commands as root on your Docker host. That is intentional — it is what makes the automation work — but it means the attack surface is real.

- **Keep it on your LAN.** Login is rate-limited (10 attempts per 5 minutes per IP), but there is no MFA or IP allowlisting. Use a VPN (WireGuard, Tailscale) if you need remote access. Do not port-forward `8765` or stick it behind a public reverse proxy.
- **One password, no MFA.** The login is a single bcrypt password. If that is not enough for your threat model, add a layer in front (e.g. Authelia).
- **Backup `data/wanifi.db`.** This file holds your UniFi API key, tool credentials, and the password hash — it is the only secret store.
- **No external requests at runtime.** All JS and CSS (Alpine.js, Chart.js, Tailwind) is self-hosted and served from the container — no CDN calls, no third-party scripts.
- **Security headers.** Every response includes `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, and `Referrer-Policy: strict-origin-when-cross-origin`.

## Support

If WaniFi saved you some 5G data or just made your homelab a little nicer,
you can [buy me a coffee](https://buymeacoffee.com/thehef). Completely
optional, deeply appreciated.

## License

MIT. See [LICENSE](LICENSE).

## Trademarks and third-party assets

UniFi product names and the device images in `app/static/devices/` are
trademarks and copyrighted material of Ubiquiti Inc. They are included
here only to identify the hardware your controller reports, with no
implied endorsement or affiliation.

**The MIT license on the rest of this repository does not apply to those
images.** They are used under a nominative-use rationale, not granted
onward. If you fork or redistribute WaniFi and want to play it safe,
replace them with your own icons or remove them entirely.
