// Root Alpine component backing the WaniFi single-page UI.

window.app = function () {
  return {
    // ---- State ------------------------------------------------------------
    tab: 'dashboard',
    status:    { active_wan: null, raw_wans: [] },
    liveStats: {},
    settings:  {
      unifi_host: '', unifi_api_key: '', unifi_site: 'default',
      primary_wan: 'wan', failover_wan: 'wan2',
      primary_wan_name: '', failover_wan_name: '',
      poll_interval: 60, event_retention_days: 30,
      unifi_api_key_set: false,
      latency_threshold_ms: 0, latency_cooldown_min: 5,
    },
    notifySettings: {
      ntfy_url: '', ntfy_topic: '', ntfy_token: '', ntfy_token_set: false,
      ntfy_on_failover: true, ntfy_on_restored: true,
      ntfy_on_error: false, ntfy_on_high_latency: false,
    },
    qbSettings:   { qb_url: '', qb_username: '', qb_password: '', qb_password_set: false },
    embySettings: { emby_url: '', emby_token: '', emby_token_set: false },
    embyMsg: '',
    rules: [], events: [], containers: [], discoveredWans: [],
    newRule: { rule_type: 'host_command', name: '', container: '', trigger: 'failover', action: 'stop', command: '' },
    confirmModal: { open: false, label: '', confirm: () => {} },
    editModal:    { open: false, rule: {} },

    manualContainer: '',
    manualMsg: '', settingsMsg: '', notifyMsg: '', qbMsg: '', importMsg: '', debugMsg: '',
    runMsg: null,

    eventsLimit: 20, eventsSearch: '', eventsLevel: '',

    timer: null, liveTimer: null,
    liveConnected: false, appConnected: false,

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

      const pathMap = { '/overview':'dashboard', '/rules':'rules', '/settings':'settings', '/events':'events' };
      const fromPath = pathMap[location.pathname];
      if (fromPath) this.tab = fromPath;

      this.$watch('tab', val => {
        const paths = { dashboard:'/overview', rules:'/rules', settings:'/settings', events:'/events' };
        history.replaceState(null, '', paths[val] || '/overview');
      });

      await this.loadSettings();
      await this.loadNotifySettings();
      await this.loadQbSettings();
      await this.loadEmbySettings();
      await this.refreshLive();
      await this.refreshLiveStats();
      this.timer     = setInterval(() => this.refreshLive(),     5000);
      this.liveTimer = setInterval(() => this.refreshLiveStats(), 2000);
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
        const [s, r, e, c] = await Promise.all([
          fetch('/api/status').then(r => r.json()),
          fetch('/api/rules').then(r => r.json()),
          fetch('/api/events').then(r => r.json()),
          fetch('/api/containers').then(r => r.json()),
        ]);
        this.status     = s;
        this.rules      = r.rules;
        this.events     = e.events;
        this.containers = c.containers;
        this.appConnected = true;
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
        host: this.settings.unifi_host,
        api_key_saved: this.settings.unifi_api_key_set,
        site: this.settings.unifi_site,
        primary_wan: this.settings.primary_wan,
        failover_wan: this.settings.failover_wan,
        active_wan: live.active_wan,
        active_wan_ip: live.active_wan_ip,
        extra_devices: live.extra_devices || [],
      };
      console.log('WaniFi debug:', dump);
      this.debugMsg = JSON.stringify(dump, null, 2);
    },

    // ---- Rules ------------------------------------------------------------
    async addRule() {
      if (this.newRule.rule_type === 'docker'       && !this.newRule.container) return;
      if (this.newRule.rule_type === 'host_command' && !this.newRule.command.trim()) return;
      if (this.newRule.rule_type === 'qbittorrent'  && !this.newRule.action) return;
      await fetch('/api/rules', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(this.newRule),
      });
      const keep_type = this.newRule.rule_type, keep_trigger = this.newRule.trigger;
      const default_action = keep_type === 'qbittorrent' ? 'alt_speed_on' : 'stop';
      this.newRule = { rule_type: keep_type, name: '', container: '', trigger: keep_trigger, action: default_action, command: '' };
      await this.refreshLive();
    },

    editRule(id) {
      const r = this.rules.find(r => r.id === id);
      if (!r) return;
      this.editModal = { open: true, rule: { ...r } };
    },

    async saveEditRule() {
      const r = this.editModal.rule;
      await fetch('/api/rules/' + r.id, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(r),
      });
      this.editModal.open = false;
      await this.refreshLive();
    },

    deleteRule(id) {
      const rule = this.rules.find(r => r.id === id);
      const label = rule
        ? (rule.rule_type === 'host_command' ? rule.command
          : rule.rule_type === 'qbittorrent' ? `qB: ${rule.action} → ${rule.trigger}`
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
