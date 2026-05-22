// Root Alpine component backing the WaniFi single-page UI.

window.app = function () {
  return {
    // ---- State ------------------------------------------------------------
    tab: 'dashboard',
    status:    { active_wan: null, raw_wans: [] },
    liveStats: {},
    settings:  {
      router_type: 'unifi',
      unifi_host: '', unifi_api_key: '', unifi_site: 'default',
      primary_wan: 'wan', failover_wan: 'wan2',
      primary_wan_name: '', failover_wan_name: '',
      poll_interval: 60, event_retention_days: 30,
      unifi_api_key_set: false,
      latency_threshold_ms: 0, latency_cooldown_min: 5,
    },
    openwrtSettings: {
      openwrt_url: '', openwrt_username: 'root', openwrt_password: '',
      openwrt_password_set: false,
      openwrt_primary_iface: 'wan', openwrt_failover_iface: 'wwan',
    },
    openwrtMsg: '', openwrtDiscoveredIfaces: [], openwrtDebugMsg: '', openwrtRouterModel: 'OPENWRT',
    notifySettings: {
      ntfy_url: '', ntfy_topic: '', ntfy_token: '', ntfy_token_set: false,
      ntfy_on_failover: true, ntfy_on_restored: true,
      ntfy_on_error: false, ntfy_on_high_latency: false,
    },
    discordSettings:     { discord_webhook_url: '', discord_webhook_url_set: false },
    telegramSettings:    { telegram_bot_token: '', telegram_bot_token_set: false, telegram_chat_id: '' },
    pushoverSettings:    { pushover_app_token: '', pushover_app_token_set: false, pushover_user_key: '' },
    qbSettings:          { qb_url: '', qb_username: '', qb_password: '', qb_password_set: false },
    sabnzbdSettings:     { sabnzbd_url: '', sabnzbd_api_key_set: false },
    transmissionSettings:{ transmission_url: '', transmission_username: '', transmission_password_set: false },
    delugeSettings:      { deluge_url: '', deluge_password_set: false },
    embySettings:        { emby_url: '', emby_token: '', emby_token_set: false },
    jellyfinSettings:    { jellyfin_url: '', jellyfin_token: '', jellyfin_token_set: false },
    plexSettings:        { plex_url: '', plex_token: '', plex_token_set: false },
    haSettings:          { ha_url: '', ha_token_set: false },
    proxmoxSettings:     { proxmox_url: '', proxmox_username: '', proxmox_password_set: false, proxmox_node: 'pve' },
    sonarrSettings:      { sonarr_url: '', sonarr_api_key_set: false },
    radarrSettings:      { radarr_url: '', radarr_api_key_set: false },
    piholeSettings:      { pihole_url: '', pihole_token_set: false },
    adguardSettings:     { adguard_url: '', adguard_username: '', adguard_password_set: false },
    portainerSettings:   { portainer_url: '', portainer_token_set: false, portainer_env_id: '1' },
    truenasSettings:     { truenas_url: '', truenas_api_key_set: false },
    unraidSettings:      { unraid_url: '', unraid_api_key_set: false },
    noderedSettings:     { nodered_url: '', nodered_username: '', nodered_password_set: false },
    gotifySettings:      { gotify_url: '', gotify_token_set: false, gotify_on_failover: true, gotify_on_restored: true, gotify_on_error: false, gotify_on_high_latency: false },
    nzbgetSettings:      { nzbget_url: '', nzbget_username: '', nzbget_password_set: false },
    npmSettings:         { npm_url: '', npm_username: '', npm_password_set: false },
    cloudflareSettings:  { cloudflare_api_token_set: false, cloudflare_zone_id: '' },
    nutSettings:         { nut_host: '', nut_port: 3493, nut_ups_name: 'ups', nut_username: '', nut_password_set: false },
    speedtestSettings:   { speedtest_server_id: '', speedtest_server_name: '', speedtest_source_ip: '' },
    speedtestServers: [], speedtestServerSearch: '', speedtestServerOpen: false, speedtestServersLoading: false, speedtestServersError: '',

    embyMsg: '', jellyfinMsg: '', plexMsg: '',
    discordMsg: '', telegramMsg: '', pushoverMsg: '',
    sabnzbdMsg: '', transmissionMsg: '', delugeMsg: '',
    haMsg: '', proxmoxMsg: '', sonarrMsg: '', radarrMsg: '',
    piholeMsg: '', adguardMsg: '',
    portainerMsg: '', truenasMsg: '', unraidMsg: '',
    noderedMsg: '', gotifyMsg: '', nzbgetMsg: '',
    npmMsg: '', cloudflareMsg: '', nutMsg: '', speedtestMsg: '',
    speedtestRunning: false, speedtestError: '',

    integrations: {
      host_command: false, docker: false, webhook: false,
      qb: false, sabnzbd: false, transmission: false, deluge: false,
      emby: false, jellyfin: false, plex: false,
      ntfy: false, discord: false, telegram: false, pushover: false,
      homeassistant: false, proxmox: false, sonarr: false, radarr: false,
      pihole: false, adguard: false,
      portainer: false, truenas: false, unraid: false,
      nodered: false, nzbget: false, gotify: false,
      speedtest: false, npm: false, cloudflare: false, nut: false,
    },
    categoryOpen: { media: false, downloaders: false, notifications: false, homelab: false, network: false },
    stats: {},
    rules: [], events: [], containers: [], discoveredWans: [], agents: [],
    agentContainers: [], agentContainersLoading: false,
    agentDockerAction: 'stop', agentDockerContainer: '',
    newAgentName: '', newAgentKey: '', agentMsg: '', keyTab: 'cli', keyMode: 'docker',
    newRule: { rule_type: 'host_command', name: '', container: '', trigger: 'failover', action: 'stop', command: '', delay_seconds: 0 },
    confirmModal: { open: false, label: '', confirm: () => {} },
    editModal:    { open: false, rule: {} },

    manualContainer: '',
    manualMsg: '', settingsMsg: '', notifyMsg: '', qbMsg: '', importMsg: '', debugMsg: '',

    runMsg: null,
    dragSrcIndex: null, dragOverIndex: null,
    agentDragSrcIndex: null, agentDragOverIndex: null,

    eventsLimit: 20, eventsSearch: '', eventsLevel: '',

    timer: null, liveTimer: null,
    liveConnected: false, appConnected: false,
    versionStatus: null,

    // ---- Derived ----------------------------------------------------------
    get filteredEvents() {
      const q = this.eventsSearch.toLowerCase();
      return this.events.filter(e => {
        if (this.eventsLevel && e.level !== this.eventsLevel) return false;
        if (!q) return true;
        return e.message.toLowerCase().includes(q)
          || e.ts.toLowerCase().includes(q)
          || e.level.toLowerCase().includes(q);
      });
    },

    // ---- Lifecycle --------------------------------------------------------
    async init() {
      const saved = localStorage.getItem('wanifi_discovered_wans');
      if (saved) { try { this.discoveredWans = JSON.parse(saved); } catch {} }
      const savedOwrt = localStorage.getItem('wanifi_discovered_owrt');
      if (savedOwrt) { try { this.openwrtDiscoveredIfaces = JSON.parse(savedOwrt); } catch {} }

      const pathMap = { '/overview':'dashboard', '/rules':'rules', '/settings':'settings', '/events':'events' };
      const tabPaths = { dashboard:'/overview', rules:'/rules', settings:'/settings', events:'/events' };
      const fromPath = pathMap[location.pathname];
      if (fromPath) this.tab = fromPath;

      // Stamp current state so every entry in history has a tab key
      history.replaceState({ tab: this.tab }, '', tabPaths[this.tab] || '/overview');

      // Use the browser URL as source of truth — if the URL already matches the
      // target tab (e.g. browser just moved via popstate) we skip pushState entirely.
      // No flags needed; this works regardless of whether $watch fires sync or async.
      this.$watch('tab', val => {
        const target = tabPaths[val] || '/overview';
        if (location.pathname === target) return;
        history.pushState({ tab: val }, '', target);
        window.scrollTo(0, 0);
        if (val === 'rules') this._setDefaultRuleType();
        if (val === 'events') this.eventsLimit = 20;
      });

      window.addEventListener('keydown', e => {
        if (e.key === 'Escape') {
          this.confirmModal.open = false;
          this.editModal.open = false;
        }
      });

      window.addEventListener('popstate', e => {
        const t = e.state?.tab || pathMap[location.pathname];
        if (t && t !== this.tab) {
          this.tab = t;
          window.scrollTo(0, 0);
        }
      });

      await this.loadSettings();
      await this.loadOpenwrtSettings().catch(() => {});
      await this.loadNotifySettings();
      await this.loadDiscordSettings();
      await this.loadTelegramSettings();
      await this.loadPushoverSettings();
      await this.loadQbSettings();
      await this.loadSabnzbdSettings();
      await this.loadTransmissionSettings();
      await this.loadDelugeSettings();
      await this.loadEmbySettings();
      await this.loadJellyfinSettings();
      await this.loadPlexSettings();
      await this.loadHaSettings();
      await this.loadProxmoxSettings();
      await this.loadSonarrSettings();
      await this.loadRadarrSettings();
      await this.loadPiholeSettings();
      await this.loadAdguardSettings();
      await this.loadPortainerSettings();
      await this.loadTruenasSettings();
      await this.loadUnraidSettings();
      await this.loadNoderedSettings();
      await this.loadGotifySettings();
      await this.loadNzbgetSettings();
      await this.loadNpmSettings();
      await this.loadCloudflareSettings();
      await this.loadNutSettings();
      await this.loadSpeedtestSettings();
      await this.loadIntegrations();
      await this.loadAgents();
      await this.loadStats();
      this._setDefaultRuleType();

      const isConfigured = this.settings.router_type === 'openwrt'
        ? (this.openwrtSettings.openwrt_url && this.openwrtSettings.openwrt_password_set)
        : this.settings.unifi_api_key_set;
      if (!isConfigured && !fromPath) {
        history.replaceState({ tab: 'settings' }, '', '/settings');
        this.tab = 'settings';
      }

      await this.refreshLive();
      await this.refreshLiveStats();
      this.timer     = setInterval(() => this.refreshLive(),     5000);
      this.liveTimer = setInterval(() => this.refreshLiveStats(), 2000);
      this.checkVersion();
      setInterval(() => this.checkVersion(), 300000);
    },

    // ---- Version check ----------------------------------------------------
    async checkVersion() {
      try {
        const d = await fetch('/api/version').then(r => r.json());
        this.versionStatus = d;
      } catch {}
    },

    // ---- Polling ----------------------------------------------------------
    async refreshLiveStats() {
      try {
        const data = await fetch('/api/live').then(r => r.json());
        this.liveStats = data;
        this.liveConnected = Object.keys(data).length > 0;
      } catch { this.liveConnected = false; }
    },

    async refreshLive() {
      try {
        const [s, r, e, c, a] = await Promise.all([
          fetch('/api/status').then(r => r.json()),
          fetch('/api/rules').then(r => r.json()),
          fetch('/api/events').then(r => r.json()),
          fetch('/api/containers').then(r => r.json()),
          fetch('/api/agents').then(r => r.json()),
        ]);
        this.status     = s;
        this.rules      = r.rules;
        this.events     = e.events;
        this.containers = c.containers;
        this.agents     = a;
        this.appConnected = true;
        // Docker availability is determined by socket mount — sync and lock the toggle
        if (s.docker_ok !== undefined) this.integrations.docker = s.docker_ok;
        await this.loadStats();
      } catch { this.appConnected = false; }
    },

    // ---- Settings ---------------------------------------------------------
    async loadSettings() {
      const s = await fetch('/api/settings').then(r => r.json());
      this.settings = { ...s, unifi_api_key: '' };
    },

    async saveSettings() {
      const payload = {
        ...this.settings,
        unifi_api_key: this.$refs.unifiApiKey ? this.$refs.unifiApiKey.value : this.settings.unifi_api_key,
      };
      const r = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      this.settingsMsg = r.ok ? '✓ Saved' : '✗ Error';
      setTimeout(() => this.settingsMsg = '', 3000);
      await this.loadSettings();
      if (this.$refs.unifiApiKey) this.$refs.unifiApiKey.value = '';
    },

    async testUnifi() {
      await this.saveSettings();
      this.settingsMsg = 'Testing…';
      const d = await fetch('/api/test-unifi', { method: 'POST' }).then(r => r.json());
      if (d.ok) {
        this.discoveredWans = d.discovered_wans || [];
        localStorage.setItem('wanifi_discovered_wans', JSON.stringify(this.discoveredWans));
        this.settingsMsg = `✓ OK — ${this.discoveredWans.length} WAN(s) found`;
      } else {
        this.settingsMsg = '✗ ' + (d.error || 'Test failed');
      }
    },

    dropWan(event, role) {
      let w;
      try { w = JSON.parse(event.dataTransfer.getData('wan')); } catch { return; }
      if (role === 'primary') {
        this.settings.primary_wan = w.subsystem;
        if (!this.settings.primary_wan_name) this.settings.primary_wan_name = w.isp_name || '';
      } else {
        this.settings.failover_wan = w.subsystem;
        if (!this.settings.failover_wan_name) this.settings.failover_wan_name = w.isp_name || '';
      }
    },

    async debugDump() {
      const live = await fetch('/api/live').then(r => r.json()).catch(() => ({}));
      const dump = {
        router_type: this.settings.router_type,
        host: this.settings.unifi_host,
        api_key_saved: this.settings.unifi_api_key_set,
        site: this.settings.unifi_site,
        primary_wan: this.settings.primary_wan,
        failover_wan: this.settings.failover_wan,
        openwrt_url: this.openwrtSettings.openwrt_url,
        openwrt_primary_iface: this.openwrtSettings.openwrt_primary_iface,
        openwrt_failover_iface: this.openwrtSettings.openwrt_failover_iface,
        active_wan: live.active_wan,
        active_wan_ip: live.active_wan_ip,
        extra_devices: live.extra_devices || [],
      };
      console.log('WaniFi debug:', dump);
      this.debugMsg = JSON.stringify(dump, null, 2);
    },

    // ---- OpenWrt settings --------------------------------------------------
    async loadOpenwrtSettings() {
      const s = await fetch('/api/openwrt/settings').then(r => r.json());
      this.openwrtSettings = { ...s, openwrt_password: '' };
      if (s.openwrt_router_model) this.openwrtRouterModel = s.openwrt_router_model;
    },

    async saveOpenwrtSettings() {
      const payload = {
        ...this.openwrtSettings,
        openwrt_password: this.$refs.openwrtPassword ? this.$refs.openwrtPassword.value : this.openwrtSettings.openwrt_password,
      };
      const r = await fetch('/api/openwrt/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      this.openwrtMsg = r.ok ? '✓ Saved' : '✗ Error';
      setTimeout(() => this.openwrtMsg = '', 3000);
      await this.loadOpenwrtSettings();
      if (this.$refs.openwrtPassword) this.$refs.openwrtPassword.value = '';
    },

    async testOpenwrt() {
      await this.saveOpenwrtSettings();
      await this.saveSettings();
      this.openwrtMsg = 'Testing…';
      const d = await fetch('/api/openwrt/test', { method: 'POST' }).then(r => r.json());
      if (d.ok) {
        this.openwrtDiscoveredIfaces = d.interfaces || [];
        this.openwrtRouterModel = d.router_model || 'OPENWRT';
        localStorage.setItem('wanifi_discovered_owrt', JSON.stringify(this.openwrtDiscoveredIfaces));
        this.openwrtMsg = `✓ ${d.message}`;
      } else {
        this.openwrtDiscoveredIfaces = [];
        this.openwrtMsg = '✗ ' + (d.error || 'Test failed');
      }
    },

    dropOpenwrtIface(event, role) {
      let iface;
      try { iface = JSON.parse(event.dataTransfer.getData('owrt_iface')); } catch { return; }
      if (role === 'primary') {
        this.openwrtSettings.openwrt_primary_iface = iface.interface;
      } else {
        this.openwrtSettings.openwrt_failover_iface = iface.interface;
      }
    },

    async debugOpenwrt() {
      await this.saveOpenwrtSettings();
      this.openwrtMsg = 'Debugging…';
      const d = await fetch('/api/openwrt/debug', { method: 'POST' }).then(r => r.json());
      this.openwrtDebugMsg = JSON.stringify(d, null, 2);
      this.openwrtMsg = '';
    },

    // ---- Rules ------------------------------------------------------------
    async addRule() {
      if (this.newRule.rule_type === 'docker'       && !this.newRule.container) return;
      if (this.newRule.rule_type === 'host_command' && !this.newRule.command.trim()) return;
      if (this.newRule.rule_type === 'qbittorrent'  && !this.newRule.action) return;
      if (this.newRule.rule_type === 'remote_agent' && this.newRule.action === 'docker') {
        if (!this.newRule.container || !this.agentDockerContainer) return;
        this.newRule.command = this.agentDockerAction + '|' + this.agentDockerContainer;
      }
      try {
        const r = await fetch('/api/rules', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(this.newRule),
        });
        if (!r.ok) {
          const d = await r.json().catch(() => ({}));
          console.error('addRule failed:', d.detail || d.error || r.status);
          return;
        }
      } catch (e) {
        console.error('addRule error:', e);
        return;
      }
      const keep_type = this.newRule.rule_type, keep_trigger = this.newRule.trigger;
      this.newRule = { rule_type: keep_type, name: '', container: '', trigger: keep_trigger, action: '', command: '' };
      this._setDefaultRuleType();
      this.newRule.trigger = keep_trigger;
      await this.refreshLive();
    },

    editRule(id) {
      const r = this.rules.find(r => r.id === id);
      if (!r) return;
      this.editModal = { open: true, rule: { ...r } };
    },

    async saveEditRule() {
      const r = this.editModal.rule;
      try {
        const resp = await fetch('/api/rules/' + r.id, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(r),
        });
        if (!resp.ok) {
          const d = await resp.json().catch(() => ({}));
          console.error('saveEditRule failed:', d.detail || d.error || resp.status);
          return;
        }
      } catch (e) {
        console.error('saveEditRule error:', e);
        return;
      }
      this.editModal.open = false;
      await this.refreshLive();
    },

    deleteRule(id) {
      const rule = this.rules.find(r => r.id === id);
      const label = rule
        ? (rule.rule_type === 'host_command' ? rule.command
          : rule.rule_type === 'qbittorrent' ? `qB: ${rule.action} → ${rule.trigger}`
          : rule.rule_type === 'emby'         ? `Emby: ${rule.action} → ${rule.trigger}`
          : rule.rule_type === 'jellyfin'     ? `Jellyfin: ${rule.action} → ${rule.trigger}`
          : rule.rule_type === 'plex'         ? `Plex: ${rule.action} → ${rule.trigger}`
          : `${rule.action} ${rule.container} → ${rule.trigger}`)
        : `Rule #${id}`;
      this.confirmModal = {
        open: true, label,
        confirm: async () => {
          this.confirmModal.open = false;
          await fetch('/api/rules/' + id, { method: 'DELETE' });
          await this.refreshLive();
        },
      };
    },

    async toggleRule(id) {
      await fetch('/api/rules/' + id + '/toggle', { method: 'POST' });
      await this.refreshLive();
    },

    async reorderRules(fromIndex, toIndex) {
      if (fromIndex === null || fromIndex === toIndex) return;
      const arr = [...this.rules];
      const [moved] = arr.splice(fromIndex, 1);
      arr.splice(toIndex, 0, moved);
      this.rules = arr;
      await fetch('/api/rules/reorder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: arr.map(r => r.id) }),
      });
    },

    async runRule(id) {
      const r = await fetch('/api/rules/' + id + '/run', { method: 'POST' });
      const d = await r.json().catch(() => ({}));
      this.runMsg = { id, ok: d.ok, text: d.ok ? '✓ ' + (d.message || 'ok') : '✗ ' + (d.message || 'error') };
      setTimeout(() => { if (this.runMsg.id === id) this.runMsg = null; }, 4000);
    },

    // ---- Events -----------------------------------------------------------
    deleteEvent(id, message) {
      this.confirmModal = {
        open: true, label: message,
        confirm: async () => {
          this.confirmModal.open = false;
          await fetch('/api/events/' + id, { method: 'DELETE' });
          await this.refreshLive();
        },
      };
    },

    async exportEvents() {
      const d = await fetch('/api/events?limit=100000').then(r => r.json()).catch(() => null);
      if (!d) return;
      const rows = d.events || [];
      const lines = rows.map(e => {
        const ts = new Date(e.ts).toLocaleString('sv-SE', { hour12: false }).replace('T', ' ');
        const lvl = (e.level || 'info').toUpperCase().padEnd(5);
        return `${ts}  [${lvl}]  ${e.message}`;
      });
      const blob = new Blob([lines.join('\n')], { type: 'text/plain' });
      const url  = URL.createObjectURL(blob);
      const a    = Object.assign(document.createElement('a'), {
        href: url, download: `wanifi-events-${new Date().toISOString().slice(0,10)}.txt`,
      });
      a.click();
      URL.revokeObjectURL(url);
    },

    clearAllEvents() {
      this.confirmModal = {
        open: true, label: 'All events will be permanently deleted',
        confirm: async () => {
          this.confirmModal.open = false;
          await fetch('/api/events', { method: 'DELETE' });
          await this.refreshLive();
        },
      };
    },

    // ---- qBittorrent ------------------------------------------------------
    async loadQbSettings() {
      const d = await fetch('/api/qb-settings').then(r => r.json());
      this.qbSettings = { ...d, qb_password: '' };
    },

    async saveQbSettings() {
      try {
        const payload = { qb_url: this.qbSettings.qb_url, qb_username: this.qbSettings.qb_username };
        if (this.qbSettings.qb_password) payload.qb_password = this.qbSettings.qb_password;
        const r = await fetch('/api/qb-settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const d = await r.json().catch(() => ({}));
        this.qbMsg = (r.ok && d.ok) ? '✓ Saved' : '✗ ' + (d.detail || d.error || 'Error');
        await this.loadQbSettings();
        setTimeout(() => this.qbMsg = '', 3000);
      } catch (e) {
        this.qbMsg = '✗ ' + e.message;
        setTimeout(() => this.qbMsg = '', 4000);
      }
    },

    async testQb() {
      await this.saveQbSettings();
      this.qbMsg = 'Testing…';
      try {
        const r = await fetch('/api/test-qb', { method: 'POST' });
        const d = await r.json().catch(() => ({}));
        this.qbMsg = d.ok ? '✓ Connected' : '✗ ' + (d.error || 'Failed');
      } catch (e) {
        this.qbMsg = '✗ ' + e.message;
      }
      setTimeout(() => this.qbMsg = '', 5000);
    },

    // ---- Emby -------------------------------------------------------------
    async loadEmbySettings() {
      const d = await fetch('/api/emby-settings').then(r => r.json());
      this.embySettings = { ...d, emby_token: '' };
    },

    async saveEmbySettings() {
      try {
        const payload = { emby_url: this.embySettings.emby_url };
        if (this.embySettings.emby_token) payload.emby_token = this.embySettings.emby_token;
        const r = await fetch('/api/emby-settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const d = await r.json().catch(() => ({}));
        this.embyMsg = (r.ok && d.ok) ? '✓ Saved' : '✗ ' + (d.detail || d.error || 'Error');
        await this.loadEmbySettings();
        setTimeout(() => this.embyMsg = '', 3000);
      } catch (e) {
        this.embyMsg = '✗ ' + e.message;
        setTimeout(() => this.embyMsg = '', 4000);
      }
    },

    async testEmby() {
      await this.saveEmbySettings();
      this.embyMsg = 'Testing…';
      try {
        const r = await fetch('/api/test-emby', { method: 'POST' });
        const d = await r.json().catch(() => ({}));
        this.embyMsg = d.ok ? '✓ ' + (d.message || 'Connected') : '✗ ' + (d.error || 'Failed');
      } catch (e) {
        this.embyMsg = '✗ ' + e.message;
      }
      setTimeout(() => this.embyMsg = '', 5000);
    },

    // ---- Jellyfin ---------------------------------------------------------
    async loadJellyfinSettings() {
      const d = await fetch('/api/jellyfin-settings').then(r => r.json());
      this.jellyfinSettings = { ...d, jellyfin_token: '' };
    },

    async saveJellyfinSettings() {
      try {
        const payload = { jellyfin_url: this.jellyfinSettings.jellyfin_url };
        if (this.jellyfinSettings.jellyfin_token) payload.jellyfin_token = this.jellyfinSettings.jellyfin_token;
        const r = await fetch('/api/jellyfin-settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const d = await r.json().catch(() => ({}));
        this.jellyfinMsg = (r.ok && d.ok) ? '✓ Saved' : '✗ ' + (d.detail || d.error || 'Error');
        await this.loadJellyfinSettings();
        setTimeout(() => this.jellyfinMsg = '', 3000);
      } catch (e) {
        this.jellyfinMsg = '✗ ' + e.message;
        setTimeout(() => this.jellyfinMsg = '', 4000);
      }
    },

    async testJellyfin() {
      await this.saveJellyfinSettings();
      this.jellyfinMsg = 'Testing…';
      try {
        const r = await fetch('/api/test-jellyfin', { method: 'POST' });
        const d = await r.json().catch(() => ({}));
        this.jellyfinMsg = d.ok ? '✓ ' + (d.message || 'Connected') : '✗ ' + (d.error || 'Failed');
      } catch (e) {
        this.jellyfinMsg = '✗ ' + e.message;
      }
      setTimeout(() => this.jellyfinMsg = '', 5000);
    },

    // ---- Plex -------------------------------------------------------------
    async loadPlexSettings() {
      const d = await fetch('/api/plex-settings').then(r => r.json());
      this.plexSettings = { ...d, plex_token: '' };
    },

    async savePlexSettings() {
      try {
        const payload = { plex_url: this.plexSettings.plex_url };
        if (this.plexSettings.plex_token) payload.plex_token = this.plexSettings.plex_token;
        const r = await fetch('/api/plex-settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const d = await r.json().catch(() => ({}));
        this.plexMsg = (r.ok && d.ok) ? '✓ Saved' : '✗ ' + (d.detail || d.error || 'Error');
        await this.loadPlexSettings();
        setTimeout(() => this.plexMsg = '', 3000);
      } catch (e) {
        this.plexMsg = '✗ ' + e.message;
        setTimeout(() => this.plexMsg = '', 4000);
      }
    },

    async testPlex() {
      await this.savePlexSettings();
      this.plexMsg = 'Testing…';
      try {
        const r = await fetch('/api/test-plex', { method: 'POST' });
        const d = await r.json().catch(() => ({}));
        this.plexMsg = d.ok ? '✓ ' + (d.message || 'Connected') : '✗ ' + (d.error || 'Failed');
      } catch (e) {
        this.plexMsg = '✗ ' + e.message;
      }
      setTimeout(() => this.plexMsg = '', 5000);
    },

    // ---- Discord ----------------------------------------------------------
    async loadDiscordSettings() {
      this.discordSettings = await fetch('/api/discord-settings').then(r => r.json());
    },
    async saveDiscordSettings() {
      const r = await fetch('/api/discord-settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ discord_webhook_url: this.$refs.discordWebhook?.value || '' }) });
      const d = await r.json().catch(() => ({}));
      this.discordMsg = (r.ok && d.ok) ? '✓ Saved' : '✗ Error';
      await this.loadDiscordSettings();
      setTimeout(() => this.discordMsg = '', 3000);
    },
    async testDiscord() {
      await this.saveDiscordSettings();
      this.discordMsg = 'Sending…';
      const d = await fetch('/api/test-discord', { method: 'POST' }).then(r => r.json());
      this.discordMsg = d.ok ? '✓ Sent' : '✗ ' + (d.error || 'Failed');
      setTimeout(() => this.discordMsg = '', 5000);
    },

    // ---- Telegram ---------------------------------------------------------
    async loadTelegramSettings() {
      this.telegramSettings = await fetch('/api/telegram-settings').then(r => r.json());
    },
    async saveTelegramSettings() {
      const payload = { telegram_chat_id: this.telegramSettings.telegram_chat_id };
      const token = this.$refs.telegramToken?.value;
      if (token) payload.telegram_bot_token = token;
      const r = await fetch('/api/telegram-settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const d = await r.json().catch(() => ({}));
      this.telegramMsg = (r.ok && d.ok) ? '✓ Saved' : '✗ Error';
      await this.loadTelegramSettings();
      setTimeout(() => this.telegramMsg = '', 3000);
    },
    async testTelegram() {
      await this.saveTelegramSettings();
      this.telegramMsg = 'Sending…';
      const d = await fetch('/api/test-telegram', { method: 'POST' }).then(r => r.json());
      this.telegramMsg = d.ok ? '✓ Sent' : '✗ ' + (d.error || 'Failed');
      setTimeout(() => this.telegramMsg = '', 5000);
    },

    // ---- Pushover ---------------------------------------------------------
    async loadPushoverSettings() {
      this.pushoverSettings = await fetch('/api/pushover-settings').then(r => r.json());
    },
    async savePushoverSettings() {
      const payload = { pushover_user_key: this.pushoverSettings.pushover_user_key };
      const token = this.$refs.pushoverToken?.value;
      if (token) payload.pushover_app_token = token;
      const r = await fetch('/api/pushover-settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const d = await r.json().catch(() => ({}));
      this.pushoverMsg = (r.ok && d.ok) ? '✓ Saved' : '✗ Error';
      await this.loadPushoverSettings();
      setTimeout(() => this.pushoverMsg = '', 3000);
    },
    async testPushover() {
      await this.savePushoverSettings();
      this.pushoverMsg = 'Sending…';
      const d = await fetch('/api/test-pushover', { method: 'POST' }).then(r => r.json());
      this.pushoverMsg = d.ok ? '✓ Sent' : '✗ ' + (d.error || 'Failed');
      setTimeout(() => this.pushoverMsg = '', 5000);
    },

    // ---- SABnzbd ----------------------------------------------------------
    async loadSabnzbdSettings() {
      this.sabnzbdSettings = await fetch('/api/sabnzbd-settings').then(r => r.json());
    },
    async saveSabnzbdSettings() {
      const payload = { sabnzbd_url: this.sabnzbdSettings.sabnzbd_url };
      const key = this.$refs.sabnzbdKey?.value;
      if (key) payload.sabnzbd_api_key = key;
      const r = await fetch('/api/sabnzbd-settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const d = await r.json().catch(() => ({}));
      this.sabnzbdMsg = (r.ok && d.ok) ? '✓ Saved' : '✗ Error';
      await this.loadSabnzbdSettings();
      setTimeout(() => this.sabnzbdMsg = '', 3000);
    },
    async testSabnzbd() {
      await this.saveSabnzbdSettings();
      this.sabnzbdMsg = 'Testing…';
      const d = await fetch('/api/test-sabnzbd', { method: 'POST' }).then(r => r.json());
      this.sabnzbdMsg = d.ok ? '✓ Connected' : '✗ ' + (d.error || 'Failed');
      setTimeout(() => this.sabnzbdMsg = '', 5000);
    },

    // ---- Transmission -----------------------------------------------------
    async loadTransmissionSettings() {
      this.transmissionSettings = await fetch('/api/transmission-settings').then(r => r.json());
    },
    async saveTransmissionSettings() {
      const payload = { transmission_url: this.transmissionSettings.transmission_url, transmission_username: this.transmissionSettings.transmission_username };
      const pw = this.$refs.transmissionPw?.value;
      if (pw) payload.transmission_password = pw;
      const r = await fetch('/api/transmission-settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const d = await r.json().catch(() => ({}));
      this.transmissionMsg = (r.ok && d.ok) ? '✓ Saved' : '✗ Error';
      await this.loadTransmissionSettings();
      setTimeout(() => this.transmissionMsg = '', 3000);
    },
    async testTransmission() {
      await this.saveTransmissionSettings();
      this.transmissionMsg = 'Testing…';
      const d = await fetch('/api/test-transmission', { method: 'POST' }).then(r => r.json());
      this.transmissionMsg = d.ok ? '✓ Connected' : '✗ ' + (d.error || 'Failed');
      setTimeout(() => this.transmissionMsg = '', 5000);
    },

    // ---- Deluge -----------------------------------------------------------
    async loadDelugeSettings() {
      this.delugeSettings = await fetch('/api/deluge-settings').then(r => r.json());
    },
    async saveDelugeSettings() {
      const payload = { deluge_url: this.delugeSettings.deluge_url };
      const pw = this.$refs.delugePw?.value;
      if (pw) payload.deluge_password = pw;
      const r = await fetch('/api/deluge-settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const d = await r.json().catch(() => ({}));
      this.delugeMsg = (r.ok && d.ok) ? '✓ Saved' : '✗ Error';
      await this.loadDelugeSettings();
      setTimeout(() => this.delugeMsg = '', 3000);
    },
    async testDeluge() {
      await this.saveDelugeSettings();
      this.delugeMsg = 'Testing…';
      const d = await fetch('/api/test-deluge', { method: 'POST' }).then(r => r.json());
      this.delugeMsg = d.ok ? '✓ Connected' : '✗ ' + (d.error || 'Failed');
      setTimeout(() => this.delugeMsg = '', 5000);
    },

    // ---- Home Assistant ---------------------------------------------------
    async loadHaSettings() {
      this.haSettings = await fetch('/api/ha-settings').then(r => r.json());
    },
    async saveHaSettings() {
      const payload = { ha_url: this.haSettings.ha_url };
      const token = this.$refs.haToken?.value;
      if (token) payload.ha_token = token;
      const r = await fetch('/api/ha-settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const d = await r.json().catch(() => ({}));
      this.haMsg = (r.ok && d.ok) ? '✓ Saved' : '✗ Error';
      await this.loadHaSettings();
      setTimeout(() => this.haMsg = '', 3000);
    },
    async testHa() {
      await this.saveHaSettings();
      this.haMsg = 'Testing…';
      const d = await fetch('/api/test-ha', { method: 'POST' }).then(r => r.json());
      this.haMsg = d.ok ? '✓ Connected' : '✗ ' + (d.error || 'Failed');
      setTimeout(() => this.haMsg = '', 5000);
    },

    // ---- Proxmox ----------------------------------------------------------
    async loadProxmoxSettings() {
      this.proxmoxSettings = await fetch('/api/proxmox-settings').then(r => r.json());
    },
    async saveProxmoxSettings() {
      const payload = { proxmox_url: this.proxmoxSettings.proxmox_url, proxmox_username: this.proxmoxSettings.proxmox_username, proxmox_node: this.proxmoxSettings.proxmox_node };
      const pw = this.$refs.proxmoxPw?.value;
      if (pw) payload.proxmox_password = pw;
      const r = await fetch('/api/proxmox-settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const d = await r.json().catch(() => ({}));
      this.proxmoxMsg = (r.ok && d.ok) ? '✓ Saved' : '✗ Error';
      await this.loadProxmoxSettings();
      setTimeout(() => this.proxmoxMsg = '', 3000);
    },
    async testProxmox() {
      await this.saveProxmoxSettings();
      this.proxmoxMsg = 'Testing…';
      const d = await fetch('/api/test-proxmox', { method: 'POST' }).then(r => r.json());
      this.proxmoxMsg = d.ok ? '✓ ' + (d.error ? '' : 'Connected') : '✗ ' + (d.error || 'Failed');
      setTimeout(() => this.proxmoxMsg = '', 5000);
    },

    // ---- Sonarr -----------------------------------------------------------
    async loadSonarrSettings() {
      this.sonarrSettings = await fetch('/api/sonarr-settings').then(r => r.json());
    },
    async saveSonarrSettings() {
      const payload = { sonarr_url: this.sonarrSettings.sonarr_url };
      const key = this.$refs.sonarrKey?.value;
      if (key) payload.sonarr_api_key = key;
      const r = await fetch('/api/sonarr-settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const d = await r.json().catch(() => ({}));
      this.sonarrMsg = (r.ok && d.ok) ? '✓ Saved' : '✗ Error';
      await this.loadSonarrSettings();
      setTimeout(() => this.sonarrMsg = '', 3000);
    },
    async testSonarr() {
      await this.saveSonarrSettings();
      this.sonarrMsg = 'Testing…';
      const d = await fetch('/api/test-sonarr', { method: 'POST' }).then(r => r.json());
      this.sonarrMsg = d.ok ? '✓ v' + (d.error || '') : '✗ ' + (d.error || 'Failed');
      setTimeout(() => this.sonarrMsg = '', 5000);
    },

    // ---- Radarr -----------------------------------------------------------
    async loadRadarrSettings() {
      this.radarrSettings = await fetch('/api/radarr-settings').then(r => r.json());
    },
    async saveRadarrSettings() {
      const payload = { radarr_url: this.radarrSettings.radarr_url };
      const key = this.$refs.radarrKey?.value;
      if (key) payload.radarr_api_key = key;
      const r = await fetch('/api/radarr-settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const d = await r.json().catch(() => ({}));
      this.radarrMsg = (r.ok && d.ok) ? '✓ Saved' : '✗ Error';
      await this.loadRadarrSettings();
      setTimeout(() => this.radarrMsg = '', 3000);
    },
    async testRadarr() {
      await this.saveRadarrSettings();
      this.radarrMsg = 'Testing…';
      const d = await fetch('/api/test-radarr', { method: 'POST' }).then(r => r.json());
      this.radarrMsg = d.ok ? '✓ v' + (d.error || '') : '✗ ' + (d.error || 'Failed');
      setTimeout(() => this.radarrMsg = '', 5000);
    },

    // ---- Pi-hole ----------------------------------------------------------
    async loadPiholeSettings() {
      this.piholeSettings = await fetch('/api/pihole-settings').then(r => r.json());
    },
    async savePiholeSettings() {
      const payload = { pihole_url: this.piholeSettings.pihole_url };
      const token = this.$refs.piholeToken?.value;
      if (token) payload.pihole_token = token;
      const r = await fetch('/api/pihole-settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const d = await r.json().catch(() => ({}));
      this.piholeMsg = (r.ok && d.ok) ? '✓ Saved' : '✗ Error';
      await this.loadPiholeSettings();
      setTimeout(() => this.piholeMsg = '', 3000);
    },
    async testPihole() {
      await this.savePiholeSettings();
      this.piholeMsg = 'Testing…';
      const d = await fetch('/api/test-pihole', { method: 'POST' }).then(r => r.json());
      this.piholeMsg = d.ok ? '✓ Connected' : '✗ ' + (d.error || 'Failed');
      setTimeout(() => this.piholeMsg = '', 5000);
    },

    // ---- AdGuard Home -----------------------------------------------------
    async loadAdguardSettings() {
      this.adguardSettings = await fetch('/api/adguard-settings').then(r => r.json());
    },
    async saveAdguardSettings() {
      const payload = { adguard_url: this.adguardSettings.adguard_url, adguard_username: this.adguardSettings.adguard_username };
      const pw = this.$refs.adguardPw?.value;
      if (pw) payload.adguard_password = pw;
      const r = await fetch('/api/adguard-settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const d = await r.json().catch(() => ({}));
      this.adguardMsg = (r.ok && d.ok) ? '✓ Saved' : '✗ Error';
      await this.loadAdguardSettings();
      setTimeout(() => this.adguardMsg = '', 3000);
    },
    async testAdguard() {
      await this.saveAdguardSettings();
      this.adguardMsg = 'Testing…';
      const d = await fetch('/api/test-adguard', { method: 'POST' }).then(r => r.json());
      this.adguardMsg = d.ok ? '✓ Connected' : '✗ ' + (d.error || 'Failed');
      setTimeout(() => this.adguardMsg = '', 5000);
    },

    // ---- Portainer --------------------------------------------------------
    async loadPortainerSettings() {
      this.portainerSettings = await fetch('/api/portainer-settings').then(r => r.json());
    },
    async savePortainerSettings() {
      const payload = { portainer_url: this.portainerSettings.portainer_url, portainer_env_id: this.portainerSettings.portainer_env_id };
      const token = this.$refs.portainerToken?.value;
      if (token) payload.portainer_token = token;
      const r = await fetch('/api/portainer-settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const d = await r.json().catch(() => ({}));
      this.portainerMsg = (r.ok && d.ok) ? '✓ Saved' : '✗ Error';
      await this.loadPortainerSettings();
      setTimeout(() => this.portainerMsg = '', 3000);
    },
    async testPortainer() {
      await this.savePortainerSettings();
      this.portainerMsg = 'Testing…';
      const d = await fetch('/api/test-portainer', { method: 'POST' }).then(r => r.json());
      this.portainerMsg = d.ok ? '✓ Connected' : '✗ ' + (d.error || 'Failed');
      setTimeout(() => this.portainerMsg = '', 5000);
    },

    // ---- TrueNAS ----------------------------------------------------------
    async loadTruenasSettings() {
      this.truenasSettings = await fetch('/api/truenas-settings').then(r => r.json());
    },
    async saveTruenasSettings() {
      const payload = { truenas_url: this.truenasSettings.truenas_url };
      const key = this.$refs.truenasKey?.value;
      if (key) payload.truenas_api_key = key;
      const r = await fetch('/api/truenas-settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const d = await r.json().catch(() => ({}));
      this.truenasMsg = (r.ok && d.ok) ? '✓ Saved' : '✗ Error';
      await this.loadTruenasSettings();
      setTimeout(() => this.truenasMsg = '', 3000);
    },
    async testTruenas() {
      await this.saveTruenasSettings();
      this.truenasMsg = 'Testing…';
      const d = await fetch('/api/test-truenas', { method: 'POST' }).then(r => r.json());
      this.truenasMsg = d.ok ? '✓ Connected' : '✗ ' + (d.error || 'Failed');
      setTimeout(() => this.truenasMsg = '', 5000);
    },

    // ---- Unraid -----------------------------------------------------------
    async loadUnraidSettings() {
      this.unraidSettings = await fetch('/api/unraid-settings').then(r => r.json());
    },
    async saveUnraidSettings() {
      const payload = { unraid_url: this.unraidSettings.unraid_url };
      const key = this.$refs.unraidKey?.value;
      if (key) payload.unraid_api_key = key;
      const r = await fetch('/api/unraid-settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const d = await r.json().catch(() => ({}));
      this.unraidMsg = (r.ok && d.ok) ? '✓ Saved' : '✗ Error';
      await this.loadUnraidSettings();
      setTimeout(() => this.unraidMsg = '', 3000);
    },
    async testUnraid() {
      await this.saveUnraidSettings();
      this.unraidMsg = 'Testing…';
      const d = await fetch('/api/test-unraid', { method: 'POST' }).then(r => r.json());
      this.unraidMsg = d.ok ? '✓ Connected' : '✗ ' + (d.error || 'Failed');
      setTimeout(() => this.unraidMsg = '', 5000);
    },

    // ---- Node-RED ---------------------------------------------------------
    async loadNoderedSettings() {
      this.noderedSettings = await fetch('/api/nodered-settings').then(r => r.json());
    },
    async saveNoderedSettings() {
      const payload = { nodered_url: this.noderedSettings.nodered_url, nodered_username: this.noderedSettings.nodered_username };
      const pw = this.$refs.noderedPw?.value;
      if (pw) payload.nodered_password = pw;
      const r = await fetch('/api/nodered-settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const d = await r.json().catch(() => ({}));
      this.noderedMsg = (r.ok && d.ok) ? '✓ Saved' : '✗ Error';
      await this.loadNoderedSettings();
      setTimeout(() => this.noderedMsg = '', 3000);
    },
    async testNodered() {
      await this.saveNoderedSettings();
      this.noderedMsg = 'Testing…';
      const d = await fetch('/api/test-nodered', { method: 'POST' }).then(r => r.json());
      this.noderedMsg = d.ok ? '✓ Connected' : '✗ ' + (d.error || 'Failed');
      setTimeout(() => this.noderedMsg = '', 5000);
    },

    // ---- Gotify -----------------------------------------------------------
    async loadGotifySettings() {
      this.gotifySettings = await fetch('/api/gotify-settings').then(r => r.json());
    },
    async saveGotifySettings() {
      const payload = { ...this.gotifySettings };
      const token = this.$refs.gotifyToken?.value;
      if (token) payload.gotify_token = token;
      delete payload.gotify_token_set;
      const r = await fetch('/api/gotify-settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const d = await r.json().catch(() => ({}));
      this.gotifyMsg = (r.ok && d.ok) ? '✓ Saved' : '✗ Error';
      await this.loadGotifySettings();
      setTimeout(() => this.gotifyMsg = '', 3000);
    },
    async testGotify() {
      await this.saveGotifySettings();
      this.gotifyMsg = 'Sending…';
      const d = await fetch('/api/test-gotify', { method: 'POST' }).then(r => r.json());
      this.gotifyMsg = d.ok ? '✓ Sent' : '✗ ' + (d.error || 'Failed');
      setTimeout(() => this.gotifyMsg = '', 5000);
    },

    // ---- NZBGet -----------------------------------------------------------
    async loadNzbgetSettings() {
      this.nzbgetSettings = await fetch('/api/nzbget-settings').then(r => r.json());
    },
    async saveNzbgetSettings() {
      const payload = { nzbget_url: this.nzbgetSettings.nzbget_url, nzbget_username: this.nzbgetSettings.nzbget_username };
      const pw = this.$refs.nzbgetPw?.value;
      if (pw) payload.nzbget_password = pw;
      const r = await fetch('/api/nzbget-settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const d = await r.json().catch(() => ({}));
      this.nzbgetMsg = (r.ok && d.ok) ? '✓ Saved' : '✗ Error';
      await this.loadNzbgetSettings();
      setTimeout(() => this.nzbgetMsg = '', 3000);
    },
    async testNzbget() {
      await this.saveNzbgetSettings();
      this.nzbgetMsg = 'Testing…';
      const d = await fetch('/api/test-nzbget', { method: 'POST' }).then(r => r.json());
      this.nzbgetMsg = d.ok ? '✓ Connected' : '✗ ' + (d.error || 'Failed');
      setTimeout(() => this.nzbgetMsg = '', 5000);
    },

    // ---- NPM ---------------------------------------------------------------
    async loadNpmSettings() {
      this.npmSettings = await fetch('/api/npm-settings').then(r => r.json());
    },
    async saveNpmSettings() {
      const payload = { npm_url: this.npmSettings.npm_url, npm_username: this.npmSettings.npm_username, npm_password: this.$refs.npmPassword?.value || null };
      const r = await fetch('/api/npm-settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const d = await r.json().catch(() => ({}));
      this.npmMsg = (r.ok && d.ok) ? '✓ Saved' : '✗ ' + (d.detail || d.error || 'Error');
      await this.loadNpmSettings();
      setTimeout(() => this.npmMsg = '', 3000);
    },
    async testNpm() {
      await this.saveNpmSettings();
      this.npmMsg = 'Testing…';
      const d = await fetch('/api/test-npm', { method: 'POST' }).then(r => r.json());
      this.npmMsg = d.ok ? '✓ Connected' : '✗ ' + (d.error || 'Failed');
      setTimeout(() => this.npmMsg = '', 5000);
    },

    // ---- Cloudflare --------------------------------------------------------
    async loadCloudflareSettings() {
      this.cloudflareSettings = await fetch('/api/cloudflare-settings').then(r => r.json());
    },
    async saveCloudflareSettings() {
      const payload = { cloudflare_api_token: this.$refs.cfToken?.value || null, cloudflare_zone_id: this.cloudflareSettings.cloudflare_zone_id };
      const r = await fetch('/api/cloudflare-settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const d = await r.json().catch(() => ({}));
      this.cloudflareMsg = (r.ok && d.ok) ? '✓ Saved' : '✗ ' + (d.detail || d.error || 'Error');
      await this.loadCloudflareSettings();
      if (this.$refs.cfToken) this.$refs.cfToken.value = '';
      setTimeout(() => this.cloudflareMsg = '', 3000);
    },
    async testCloudflare() {
      await this.saveCloudflareSettings();
      this.cloudflareMsg = 'Testing…';
      const d = await fetch('/api/test-cloudflare', { method: 'POST' }).then(r => r.json());
      this.cloudflareMsg = d.ok ? '✓ Connected' : '✗ ' + (d.error || 'Failed');
      setTimeout(() => this.cloudflareMsg = '', 5000);
    },

    // ---- NUT / UPS ---------------------------------------------------------
    async loadNutSettings() {
      this.nutSettings = await fetch('/api/nut-settings').then(r => r.json());
    },
    async saveNutSettings() {
      const payload = { nut_host: this.nutSettings.nut_host, nut_port: this.nutSettings.nut_port, nut_ups_name: this.nutSettings.nut_ups_name, nut_username: this.nutSettings.nut_username, nut_password: this.$refs.nutPassword?.value || null };
      const r = await fetch('/api/nut-settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const d = await r.json().catch(() => ({}));
      this.nutMsg = (r.ok && d.ok) ? '✓ Saved' : '✗ ' + (d.detail || d.error || 'Error');
      await this.loadNutSettings();
      setTimeout(() => this.nutMsg = '', 3000);
    },
    async testNut() {
      await this.saveNutSettings();
      this.nutMsg = 'Testing…';
      const d = await fetch('/api/test-nut', { method: 'POST' }).then(r => r.json());
      this.nutMsg = d.ok ? '✓ Connected' : '✗ ' + (d.error || 'Failed');
      setTimeout(() => this.nutMsg = '', 5000);
    },

    // ---- Speedtest ----------------------------------------------------------
    async loadSpeedtestSettings() {
      this.speedtestSettings = await fetch('/api/speedtest-settings').then(r => r.json());
    },
    async saveSpeedtestSettings() {
      const r = await fetch('/api/speedtest-settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ speedtest_server_id: this.speedtestSettings.speedtest_server_id }) });
      const d = await r.json().catch(() => ({}));
      this.speedtestMsg = (r.ok && d.ok) ? '✓ Saved' : '✗ ' + (d.detail || d.error || 'Error');
      setTimeout(() => this.speedtestMsg = '', 3000);
    },
    async fetchSpeedtestServers() {
      this.speedtestServersLoading = true;
      this.speedtestServerOpen = true;
      this.speedtestServerSearch = '';
      try {
        const d = await fetch('/api/speedtest-servers').then(r => r.json());
        this.speedtestServers = d.servers || [];
        this.speedtestServersError = d.ok === false ? (d.error || 'Failed to load servers') : '';
      } catch (e) {
        this.speedtestServers = [];
        this.speedtestServersError = 'Request failed: ' + e.message;
      }
      this.speedtestServersLoading = false;
    },
    speedtestServerFiltered() {
      const q = this.speedtestServerSearch.toLowerCase();
      return q ? this.speedtestServers.filter(s => s.label.toLowerCase().includes(q) || s.id.includes(q)) : this.speedtestServers;
    },
    selectSpeedtestServer(server) {
      this.speedtestSettings.speedtest_server_id = server.id;
      this.speedtestSettings.speedtest_server_name = server.label;
      this.speedtestServerOpen = false;
      this.speedtestServerSearch = '';
    },

    // ---- Stats ------------------------------------------------------------
    async loadStats() {
      try { this.stats = await fetch('/api/stats').then(r => r.json()); } catch {}
    },

    async runSpeedtest() {
      if (this.speedtestRunning) return;
      this.speedtestRunning = true;
      this.speedtestError = '';
      try {
        const d = await fetch('/api/run-speedtest', { method: 'POST' }).then(r => r.json());
        if (d.result) this.stats = { ...this.stats, last_speedtest: d.result };
        if (!d.ok) this.speedtestError = d.msg || 'Speedtest failed';
      } catch (e) {
        this.speedtestError = 'Request failed';
      }
      this.speedtestRunning = false;
    },

    // ---- Agents -----------------------------------------------------------
    async loadAgents() {
      try { this.agents = await fetch('/api/agents').then(r => r.json()); } catch {}
    },

    async reorderAgents(fromIndex, toIndex) {
      if (fromIndex === null || fromIndex === toIndex) return;
      const arr = [...this.agents];
      const [moved] = arr.splice(fromIndex, 1);
      arr.splice(toIndex, 0, moved);
      this.agents = arr;
      await fetch('/api/agents/reorder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: arr.map(a => a.id) }),
      });
    },

    async addAgent() {
      if (!this.newAgentName.trim()) return;
      const data = await fetch('/api/agents', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({name: this.newAgentName.trim()})
      }).then(r => r.json());
      this.newAgentKey = data.api_key;
      this.keyTab = 'cli';
      this.newAgentName = '';
      await this.loadAgents();
    },

    async deleteAgent(id) {
      await fetch('/api/agents/' + id, {method: 'DELETE'});
      await this.loadAgents();
    },

    cliSnippet() {
      const url = window.location.origin;
      const extra = this.keyMode === 'full' ? ' \\\n  --privileged \\\n  --pid host' : '';
      return `docker run -d \\\n  --name wanifi-agent \\\n  -e WANIFI_URL=${url} \\\n  -e AGENT_API_KEY=${this.newAgentKey} \\\n  -v /var/run/docker.sock:/var/run/docker.sock${extra} \\\n  --restart unless-stopped \\\n  ghcr.io/thehef/wanifi-agent:latest`;
    },

    composeSnippet() {
      const url = window.location.origin;
      const extra = this.keyMode === 'full' ? '\n    privileged: true\n    pid: host' : '';
      return `services:\n  wanifi-agent:\n    image: ghcr.io/thehef/wanifi-agent:latest\n    environment:\n      - WANIFI_URL=${url}\n      - AGENT_API_KEY=${this.newAgentKey}\n    volumes:\n      - /var/run/docker.sock:/var/run/docker.sock${extra}\n    restart: unless-stopped`;
    },

    copyKey() {
      const text = this.keyTab === 'cli' ? this.cliSnippet() : this.composeSnippet();
      navigator.clipboard.writeText(text);
      this.agentMsg = 'Copied!';
      setTimeout(() => this.agentMsg = '', 2000);
    },

    async loadAgentContainers() {
      const agent = this.agents.find(a => a.api_key === this.newRule.container);
      if (!agent || this.newRule.action !== 'docker') { this.agentContainers = []; return; }
      this.agentContainersLoading = true;
      this.agentContainers = [];
      try {
        const data = await fetch(`/api/agents/${agent.id}/containers`).then(r => r.json());
        this.agentContainers = Array.isArray(data) ? data : [];
      } catch {}
      this.agentContainersLoading = false;
    },

    // ---- Integrations -----------------------------------------------------
    async loadIntegrations() {
      this.integrations = await fetch('/api/integrations').then(r => r.json());
    },

    _setDefaultRuleType() {
      const order = [
        ['host_command',  'host_command',  ''],
        ['docker',        'docker',        'stop'],
        ['qbittorrent',   'qb',            'alt_speed_on'],
        ['sabnzbd',       'sabnzbd',       'pause'],
        ['transmission',  'transmission',  'pause_all'],
        ['deluge',        'deluge',        'pause_all'],
        ['emby',          'emby',          'set_bitrate_limit'],
        ['jellyfin',      'jellyfin',      'set_bitrate_limit'],
        ['plex',          'plex',          'set_wan_bitrate'],
        ['homeassistant', 'homeassistant', 'call_webhook'],
        ['proxmox',       'proxmox',       'stop_vm'],
        ['sonarr',        'sonarr',        'disable_indexers'],
        ['radarr',        'radarr',        'disable_indexers'],
        ['pihole',        'pihole',        'disable'],
        ['adguard',       'adguard',       'disable_protection'],
        ['portainer',     'portainer',     'stop_container'],
        ['truenas',       'truenas',       'stop_service'],
        ['unraid',        'unraid',        'stop_vm'],
        ['nodered',       'nodered',       'trigger_flow'],
        ['nzbget',        'nzbget',        'pause'],
        ['speedtest',     'speedtest',     'run'],
        ['npm',           'npm',           'disable_host'],
        ['cloudflare',    'cloudflare',    'enable_under_attack'],
        ['nut',           'nut',           'get_status'],
        ['webhook',       'webhook',       'send'],
        ['remote_agent',  '_agents',       'docker'],
      ];
      for (const [rtype, ikey, action] of order) {
        if (ikey === '_agents' ? this.agents.length > 0 : this.integrations[ikey]) {
          this.newRule.rule_type = rtype;
          this.newRule.action    = action;
          return;
        }
      }
    },

    async toggleIntegration(name) {
      const r = await fetch(`/api/integrations/${name}/toggle`, { method: 'POST' });
      const d = await r.json().catch(() => ({}));
      if (d.ok) {
        this.integrations[name] = d.enabled;
        if (d.enabled) {
          if (['emby', 'jellyfin', 'plex', 'sonarr', 'radarr'].includes(name))                      this.categoryOpen.media = true;
          else if (['qb', 'sabnzbd', 'transmission', 'deluge', 'nzbget'].includes(name))                    this.categoryOpen.downloaders = true;
          else if (['ntfy', 'discord', 'telegram', 'pushover', 'gotify'].includes(name))                    this.categoryOpen.notifications = true;
          else if (['homeassistant', 'proxmox', 'portainer', 'truenas', 'unraid', 'nodered'].includes(name)) this.categoryOpen.homelab = true;
          else if (['pihole', 'adguard', 'speedtest'].includes(name))                                        this.categoryOpen.network = true;
          else if (['npm', 'cloudflare', 'nut'].includes(name))                                              this.categoryOpen.homelab = true;
        }
      }
    },

    // ---- Notifications ----------------------------------------------------
    async loadNotifySettings() {
      const d = await fetch('/api/notify-settings').then(r => r.json());
      this.notifySettings = { ...d, ntfy_token: '' };
    },

    async saveNotifySettings() {
      const payload = { ...this.notifySettings };
      if (!payload.ntfy_token) delete payload.ntfy_token;
      const r = await fetch('/api/notify-settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      this.notifyMsg = r.ok ? '✓ Saved' : '✗ Error';
      await this.loadNotifySettings();
      setTimeout(() => this.notifyMsg = '', 3000);
    },

    async testNotify() {
      await this.saveNotifySettings();
      this.notifyMsg = 'Sending…';
      const d = await fetch('/api/test-notify', { method: 'POST' }).then(r => r.json());
      this.notifyMsg = d.ok ? '✓ Notification sent' : '✗ ' + (d.error || 'failed');
      setTimeout(() => this.notifyMsg = '', 5000);
    },

    // ---- Manual control ---------------------------------------------------
    async manual(action) {
      if (!this.manualContainer) return;
      const d = await fetch(`/api/manual/${action}/${this.manualContainer}`, { method: 'POST' }).then(r => r.json());
      this.manualMsg = d.message;
      setTimeout(() => this.manualMsg = '', 4000);
      await this.refreshLive();
    },

    // ---- Backup / restore -------------------------------------------------
    async importBackup(event) {
      const file = event.target.files[0];
      if (!file) return;
      event.target.value = '';
      this.confirmModal = {
        open: true,
        label: `Restore from "${file.name}"? This replaces current settings, rules and events.`,
        confirm: async () => {
          this.confirmModal.open = false;
          try {
            const data = JSON.parse(await file.text());
            if (!data.wanifi_backup_version && !data.wanifi_export_version) {
              this.importMsg = '✗ Not a valid WaniFi backup file';
            } else {
              const r = await fetch('/api/backup/import', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
              });
              const d = await r.json().catch(() => ({}));
              if (r.ok && d.ok) {
                const c = d.imported || {};
                this.importMsg = `✓ Restored ${c.settings || 0} settings, ${c.rules || 0} rules, ${c.events || 0} events`;
                await this.loadSettings();
                await this.loadNotifySettings();
                await this.loadQbSettings();
                await this.loadEmbySettings();
                await this.loadJellyfinSettings();
                await this.loadPlexSettings();
                await this.loadIntegrations();
                await this.refreshLive();
              } else {
                this.importMsg = '✗ ' + (d.detail || d.error || 'Restore failed');
              }
            }
          } catch {
            this.importMsg = '✗ Invalid file';
          }
          setTimeout(() => this.importMsg = '', 5000);
        },
      };
    },

    // ---- Small helpers ----------------------------------------------------
    fmtSpeed(mbps) {
      if (mbps === null || mbps === undefined) return '—';
      if (mbps < 0.01) return '0 Mbps';
      return mbps.toFixed(1) + ' Mbps';
    },
    signalBars(dbm) {
      // RSSI/RSRP to 0-5 bar mapping. ≥-65 = 5 bars, ≤-110 = 0 bars.
      if (dbm == null) return 0;
      if (dbm >= -65) return 5;
      if (dbm >= -75) return 4;
      if (dbm >= -85) return 3;
      if (dbm >= -95) return 2;
      if (dbm >= -110) return 1;
      return 0;
    },
    signalColor(dbm) {
      const b = this.signalBars(dbm);
      if (b >= 4) return 'text-emerald-400';
      if (b >= 3) return 'text-sky-400';
      if (b >= 2) return 'text-amber-400';
      return 'text-red-400';
    },
    fmtSince(iso) {
      if (!iso) return '—';
      const secs = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
      if (secs <= 0) return 'now';
      if (secs < 60) return secs + 's';
      const h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60);
      return h > 0 ? h + 'h ' + m + 'm' : m + 'm';
    },
    deviceIcon: (m) => window.deviceIcon(m),
    fmtModel:   (m) => window.fmtModel(m),
  };
};
