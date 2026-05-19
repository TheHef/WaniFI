"""Pydantic request models and shared validation constants."""
from typing import Optional

from pydantic import BaseModel, Field

from .config import POLL_INTERVAL_DEFAULT

VALID_TRIGGERS             = ("failover", "restored", "down", "high_latency")
VALID_ACTIONS              = ("stop", "start", "restart", "pause", "unpause")
VALID_QB_ACTIONS           = ("alt_speed_on", "alt_speed_off", "set_dl_limit", "set_ul_limit", "pause_all", "resume_all")
VALID_EMBY_ACTIONS         = ("set_bitrate_limit", "set_bitrate_and_restream", "clear_bitrate_limit", "stop_all_sessions")
VALID_JELLYFIN_ACTIONS     = ("set_bitrate_limit", "set_bitrate_and_restream", "clear_bitrate_limit", "stop_all_sessions")
VALID_PLEX_ACTIONS         = ("set_wan_bitrate", "clear_wan_bitrate", "stop_all_streams")
VALID_SABNZBD_ACTIONS      = ("pause", "resume", "set_speed_limit")
VALID_TRANSMISSION_ACTIONS = ("alt_speed_on", "alt_speed_off", "set_dl_limit", "set_ul_limit", "pause_all", "resume_all")
VALID_DELUGE_ACTIONS       = ("set_dl_limit", "set_ul_limit", "pause_all", "resume_all")
VALID_HA_ACTIONS           = ("call_webhook", "turn_on", "turn_off")
VALID_PROXMOX_ACTIONS      = ("stop_vm", "shutdown_vm", "suspend_vm", "resume_vm", "start_vm")
VALID_SONARR_ACTIONS       = ("disable_indexers", "enable_indexers", "disable_download_clients", "enable_download_clients", "search_missing", "refresh_all")
VALID_RADARR_ACTIONS       = ("disable_indexers", "enable_indexers", "disable_download_clients", "enable_download_clients", "search_missing", "refresh_all")
VALID_WEBHOOK_ACTIONS      = ("send",)
VALID_PIHOLE_ACTIONS       = ("enable", "disable")
VALID_ADGUARD_ACTIONS      = ("enable_protection", "disable_protection")
VALID_PORTAINER_ACTIONS    = ("start_container", "stop_container", "restart_container")
VALID_TRUENAS_ACTIONS      = ("start_service", "stop_service", "restart_service")
VALID_UNRAID_ACTIONS       = ("start_vm", "stop_vm", "pause_vm", "resume_vm")
VALID_NODERED_ACTIONS      = ("trigger_flow",)
VALID_NZBGET_ACTIONS       = ("pause", "resume", "set_speed_limit")
VALID_UNIFI_RULE_ACTIONS   = ("kick_all_clients", "disable_wlan", "enable_wlan", "block_client", "unblock_client")


class SetupIn(BaseModel):
    password: str = Field(min_length=8, max_length=256)


class SettingsIn(BaseModel):
    unifi_host: str
    unifi_api_key: Optional[str] = None
    unifi_site: str = "default"
    primary_wan: str
    failover_wan: str
    primary_wan_name: str = ""
    failover_wan_name: str = ""
    poll_interval: int = POLL_INTERVAL_DEFAULT
    event_retention_days: int = 30
    latency_threshold_ms: int = 0
    latency_cooldown_min: int = 5


class RuleIn(BaseModel):
    rule_type: str = "docker"
    name: str = ""
    container: str = ""
    action: str = ""
    command: str = ""
    trigger: str
    enabled: bool = True
    delay_seconds: int = 0


class NotifySettingsIn(BaseModel):
    ntfy_url: str = ""
    ntfy_topic: str = ""
    ntfy_token: Optional[str] = None
    ntfy_on_failover: bool = True
    ntfy_on_restored: bool = True
    ntfy_on_error: bool = False
    ntfy_on_high_latency: bool = False


class DiscordSettingsIn(BaseModel):
    discord_webhook_url: str = ""


class TelegramSettingsIn(BaseModel):
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""


class PushoverSettingsIn(BaseModel):
    pushover_app_token: str = ""
    pushover_user_key: str = ""


class QbSettingsIn(BaseModel):
    qb_url: str = ""
    qb_username: str = ""
    qb_password: Optional[str] = None


class EmbySettingsIn(BaseModel):
    emby_url: str = ""
    emby_token: Optional[str] = None


class JellyfinSettingsIn(BaseModel):
    jellyfin_url: str = ""
    jellyfin_token: Optional[str] = None


class PlexSettingsIn(BaseModel):
    plex_url: str = ""
    plex_token: Optional[str] = None


class SabnzbdSettingsIn(BaseModel):
    sabnzbd_url: str = ""
    sabnzbd_api_key: Optional[str] = None


class TransmissionSettingsIn(BaseModel):
    transmission_url: str = ""
    transmission_username: str = ""
    transmission_password: Optional[str] = None


class DelugeSettingsIn(BaseModel):
    deluge_url: str = ""
    deluge_password: Optional[str] = None


class HomeAssistantSettingsIn(BaseModel):
    ha_url: str = ""
    ha_token: Optional[str] = None


class ProxmoxSettingsIn(BaseModel):
    proxmox_url: str = ""
    proxmox_username: str = ""
    proxmox_password: Optional[str] = None
    proxmox_node: str = ""


class SonarrSettingsIn(BaseModel):
    sonarr_url: str = ""
    sonarr_api_key: Optional[str] = None


class RadarrSettingsIn(BaseModel):
    radarr_url: str = ""
    radarr_api_key: Optional[str] = None



class PiholeSettingsIn(BaseModel):
    pihole_url: str = ""
    pihole_token: Optional[str] = None


class AdGuardSettingsIn(BaseModel):
    adguard_url: str = ""
    adguard_username: str = ""
    adguard_password: Optional[str] = None


class PortainerSettingsIn(BaseModel):
    portainer_url: str = ""
    portainer_token: Optional[str] = None
    portainer_env_id: str = "1"


class TrueNASSettingsIn(BaseModel):
    truenas_url: str = ""
    truenas_api_key: Optional[str] = None


class UnraidSettingsIn(BaseModel):
    unraid_url: str = ""
    unraid_api_key: Optional[str] = None


class NodeRedSettingsIn(BaseModel):
    nodered_url: str = ""
    nodered_username: str = ""
    nodered_password: Optional[str] = None


class GotifySettingsIn(BaseModel):
    gotify_url: str = ""
    gotify_token: Optional[str] = None
    gotify_on_failover: bool = True
    gotify_on_restored: bool = True
    gotify_on_error: bool = False
    gotify_on_high_latency: bool = False


class NZBGetSettingsIn(BaseModel):
    nzbget_url: str = ""
    nzbget_username: str = ""
    nzbget_password: Optional[str] = None
