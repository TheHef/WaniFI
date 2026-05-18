<div align="center">
  <img src="docs/logo.svg" width="96" alt="WaniFi" />
  <h1>WaniFi</h1>
  <p><strong>Failover handled.</strong></p>
  <a href="https://buymeacoffee.com/thehef">
    <img src="https://img.shields.io/badge/Buy%20Me%20a%20Coffee-%23FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black" alt="Buy Me a Coffee" />
  </a>
  &nbsp;
  <img src="https://img.shields.io/badge/version-0.6.5-blue?style=for-the-badge" alt="v0.6.5" />
  &nbsp;
  <img src="https://img.shields.io/badge/license-MIT-green?style=for-the-badge" alt="MIT" />
</div>

---

Self-hosted dashboard for UniFi WAN failover monitoring with rule-based automation.

When your UniFi gateway switches to a failover WAN, WaniFi can automatically
stop/start Docker containers, throttle downloads, cap streaming bitrate on media
servers, disable DNS filtering, trigger home automations, and more.
Handy for keeping 5G failover costs under control.

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
- 📈 Live throughput / latency graphs with 1 h to 30 d ranges
- 🔔 Push notifications via ntfy, Discord, Telegram, Pushover, or Gotify
- 🔐 Single-user login (bcrypt; first-run setup wizard)
- 💾 SQLite, no other services required

---

## Integrations

All integrations are opt-in and toggled on/off individually in **Settings**.

### 📥 Downloads

| Integration | Actions |
|---|---|
| **qBittorrent** | Pause/resume all, enable/disable alt speed, set download/upload limit |
| **SABnzbd** | Pause, resume, set speed limit |
| **NZBGet** | Pause, resume, set speed limit |
| **Transmission** | Pause/resume all, enable/disable alt speed, set download/upload limit |
| **Deluge** | Pause/resume all, set download/upload limit |

### 🎬 Media

| Integration | Actions |
|---|---|
| **Emby** | Set/clear remote bitrate limit, stop all sessions |
| **Jellyfin** | Set/clear remote bitrate limit, stop all sessions |
| **Plex** | Set/clear remote bitrate limit, stop all streams |
| **Sonarr** | Disable/enable indexers, disable/enable download clients, search missing, refresh all |
| **Radarr** | Disable/enable indexers, disable/enable download clients, search missing, refresh all |
| **Seerr** *(Overseerr / Jellyseerr)* | Trigger sync jobs (Sync Radarr, Sync Sonarr) |

### 🏠 Homelab

| Integration | Actions |
|---|---|
| **Home Assistant** | Call webhook, turn on/off entity |
| **Proxmox** | Start, stop, shutdown, suspend, resume VM or LXC container |
| **Portainer** | Start, stop, restart, pause, unpause container |
| **TrueNAS** | Start/stop pool scrub, set replication throttle |
| **Unraid** | Start/stop VMs and user scripts |
| **Node-RED** | Trigger any HTTP-in flow endpoint |

### 🌐 Network

| Integration | Actions |
|---|---|
| **Pi-hole** | Enable/disable DNS filtering (v5 and v6 API supported) |
| **AdGuard Home** | Enable/disable DNS filtering |

### 🖥️ Infrastructure

| Integration | Actions |
|---|---|
| **Docker** | Stop, start, restart, pause, unpause containers via the Docker socket |
| **Host Command** | Run arbitrary shell commands on the Docker host via `nsenter` |

### 🔔 Notifications

Each notification channel can independently opt in or out of each event type
(`failover`, `restored`, `high_latency`, `error`) via per-channel toggles.

| Channel | Notes |
|---|---|
| **ntfy** | Self-hosted or ntfy.sh; optional Bearer token auth |
| **Discord** | Webhook URL |
| **Telegram** | Bot token + chat ID |
| **Pushover** | App token + user key |
| **Gotify** | Self-hosted; API token |

---

## Quick start

Create a folder for WaniFi, drop in a `compose.yaml`, and start it:

```bash
mkdir wanifi && cd wanifi
mkdir -p data
curl -O https://raw.githubusercontent.com/TheHef/WaniFI/main/compose.yaml
docker compose up -d
```

Docker pulls the pre-built image from GitHub Container Registry
(`ghcr.io/thehef/wanifi`) and starts it on port `4444`. Open
`http://<docker-host>:4444` in a browser.

### compose.yaml

```yaml
services:
  wanifi:
    image: ghcr.io/thehef/wanifi:latest
    container_name: wanifi
    restart: unless-stopped
    ports:
      - "4444:8000"
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

> `privileged: true` and `pid: host` are only required for **Host Command** rules
> (so WaniFi can run commands via `nsenter`). If you don't use host commands,
> you can safely drop both and keep just the Docker socket mount.

To update: `docker compose pull && docker compose up -d`

---

## Setup

### 1. Pick an admin password

On first visit you'll be redirected to `/setup` to choose an admin password.
The bcrypt hash is stored in the local SQLite database — no env vars needed.

### 2. Configure your UniFi controller

In the WaniFi UI go to **Settings → Network**:

- **Controller URL:** `https://<your-UCG-or-UDM-IP>`
- **API Key:** generate one in UniFi OS → Settings → Control Plane →
  Integrations → API Keys (requires UniFi OS 3.x+)
- Click **Test Connection** — your WAN interfaces appear as draggable chips
- Drop one into **Primary WAN** and another into **Failover WAN**
- Give them friendly names and hit **Save**

![Settings](docs/screenshots/settings.png)

### 3. Enable integrations

Go to **Settings** and toggle on the integrations you need.
Each one reveals its own config section (URL, credentials) when enabled.

### 4. Add rules

Go to the **Rules** tab. Each rule pairs a **trigger** with an **action**:

| Trigger | Fires when… |
|---|---|
| `On failover` | Gateway switches to the failover WAN |
| `On restored` | Gateway switches back to the primary WAN |
| `On WAN down` | No WAN connectivity is detected |
| `On high latency` | Latency exceeds the configured threshold |

Example setup for a 5G failover scenario:

| Rule name | Trigger | Action |
|---|---|---|
| Slow QB | On failover | qBittorrent: enable alt speed |
| Normal QB | On restored | qBittorrent: disable alt speed |
| Limit Streams | On failover | Plex: set remote bitrate 4 Mbps |
| Unlimit Streams | On restored | Plex: clear remote bitrate |
| Disable DNS filter | On failover | Pi-hole: disable filtering |
| Enable DNS filter | On restored | Pi-hole: enable filtering |

![Rules](docs/screenshots/rules.png)

### 5. Configure notifications (optional)

In **Settings → Notifications** enable one or more channels and enter the
relevant credentials. Each channel has individual event toggles so you can,
for example, only get Gotify alerts for failover/restored and skip high latency.

---

## Events

Every state change, rule firing, error, and manual action is logged.
Filter by level or search the message column; rows can be deleted individually
or all at once.

![Events](docs/screenshots/events.png)

---

## Building from source

```bash
git clone https://github.com/TheHef/WaniFI.git
cd WaniFI
docker build -t wanifi:local .
```

Then point the `image:` field in your `compose.yaml` at `wanifi:local` and
run `docker compose up -d`.

---

## Security notes

> ⚠️ **LAN only — do not expose to the public internet.**

WaniFi runs with `privileged: true`, `pid: host`, and a mounted Docker socket.
Anyone who can reach the UI can effectively run arbitrary commands as root on
your Docker host. That is intentional — it is what makes the automation work —
but the attack surface is real.

- **Keep it on your LAN.** Login is rate-limited (10 attempts / 5 min / IP),
  but there is no MFA or IP allowlisting. Use a VPN (WireGuard, Tailscale) if
  you need remote access.
- **One password, no MFA.** If that isn't enough for your threat model, put an
  auth proxy in front (e.g. Authelia).
- **Backup `data/wanifi.db`.** This file holds your UniFi API key, all
  integration credentials, and the password hash — it is the only secret store.
- **No external requests at runtime.** All JS and CSS (Alpine.js, Chart.js,
  Tailwind) is self-hosted inside the container — no CDN calls, no third-party
  scripts.
- **Security headers.** Every response includes `X-Frame-Options: DENY`,
  `X-Content-Type-Options: nosniff`, and `Referrer-Policy: strict-origin-when-cross-origin`.

---

## Support

If WaniFi saved you some 5G data or just made your homelab a little nicer,
you can [buy me a coffee ☕](https://buymeacoffee.com/thehef).
Completely optional, deeply appreciated.

---

## License

MIT. See [LICENSE](LICENSE).

## Trademarks and third-party assets

UniFi product names and the device images in `app/static/devices/` are
trademarks and copyrighted material of Ubiquiti Inc. They are included here
only to identify the hardware your controller reports, with no implied
endorsement or affiliation.

**The MIT license on the rest of this repository does not apply to those
images.** They are used under a nominative-use rationale, not granted onward.
If you fork or redistribute WaniFi and want to play it safe, replace them with
your own icons or remove them entirely.
