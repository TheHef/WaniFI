// Alpine x-data factory for the throughput + latency charts on the dashboard.

window.metricsChart = function () {
  return {
    range: '1h',
    chartRx: null,
    chartLat: null,
    timer: null,
    lastRx: null,
    lastTx: null,
    lastLat: null,

    init() {
      this.loadMetrics();
      this.timer = setInterval(() => this.loadMetrics(), 30000);

      this._resizeObs = new ResizeObserver(() => {
        if (this.chartRx)  this.chartRx.resize();
        if (this.chartLat) this.chartLat.resize();
      });
      this._resizeObs.observe(this.$el);
    },
    destroy() {
      if (this.timer) clearInterval(this.timer);
      if (this._resizeObs) this._resizeObs.disconnect();
    },

    async setRange(r) {
      this.range = r;
      this._destroyCharts();
      await this.loadMetrics();
    },

    _destroyCharts() {
      if (this.chartRx)  { this.chartRx.destroy();  this.chartRx  = null; }
      if (this.chartLat) { this.chartLat.destroy(); this.chartLat = null; }
    },

    _fmtLabel(ts) {
      const dt = new Date(ts);
      if (['1h','3h','6h','12h','1d'].includes(this.range)) {
        return dt.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
      }
      return dt.toLocaleDateString('en-GB', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    },

    async loadMetrics() {
      let d;
      try {
        const res = await fetch('/api/metrics?range=' + this.range);
        if (!res.ok) return;
        d = await res.json();
      } catch { return; }
      if (!d.labels || !d.labels.length) return;

      // Update live stat pills with the most recent data point
      const last = d.labels.length - 1;
      this.lastRx  = d.rx[last]      ?? null;
      this.lastTx  = d.tx[last]      ?? null;
      this.lastLat = d.latency[last] ?? null;

      const labels = d.labels.map(ts => this._fmtLabel(ts));
      const base = { borderWidth: 2, pointRadius: 0, tension: 0.4, fill: true };

      if (this.chartRx) {
        this.chartRx.data.labels = labels;
        this.chartRx.data.datasets[0].data = d.rx;
        this.chartRx.data.datasets[1].data = d.tx;
        this.chartRx.update('none');
      } else {
        const ctx = document.getElementById('chart-throughput').getContext('2d');

        const gradRx = ctx.createLinearGradient(0, 0, 0, 200);
        gradRx.addColorStop(0, 'rgba(52,211,153,0.18)');
        gradRx.addColorStop(1, 'rgba(52,211,153,0.01)');

        const gradTx = ctx.createLinearGradient(0, 0, 0, 200);
        gradTx.addColorStop(0, 'rgba(56,189,248,0.14)');
        gradTx.addColorStop(1, 'rgba(56,189,248,0.01)');

        this.chartRx = new Chart(ctx, {
          type: 'line',
          data: {
            labels,
            datasets: [
              { label: '↓ Download', data: d.rx, borderColor: 'rgb(52,211,153)', backgroundColor: gradRx,
                shadowColor: 'rgba(52,211,153,0.4)', shadowBlur: 8, ...base },
              { label: '↑ Upload',   data: d.tx, borderColor: 'rgb(56,189,248)', backgroundColor: gradTx,
                shadowColor: 'rgba(56,189,248,0.4)', shadowBlur: 8, ...base },
            ],
          },
          options: this._lineOpts('Mbps'),
        });
      }

      if (this.chartLat) {
        this.chartLat.data.labels = labels;
        this.chartLat.data.datasets[0].data = d.latency;
        this.chartLat.update('none');
      } else {
        const ctx2 = document.getElementById('chart-latency').getContext('2d');

        const gradLat = ctx2.createLinearGradient(0, 0, 0, 200);
        gradLat.addColorStop(0, 'rgba(251,191,36,0.16)');
        gradLat.addColorStop(1, 'rgba(251,191,36,0.01)');

        this.chartLat = new Chart(ctx2, {
          type: 'line',
          data: {
            labels,
            datasets: [{ label: 'Latency', data: d.latency, borderColor: 'rgb(251,191,36)', backgroundColor: gradLat, ...base }],
          },
          options: this._lineOpts('ms'),
        });
      }
    },

    _lineOpts(unit) {
      return {
        responsive: true, maintainAspectRatio: false, animation: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend:  { display: false },
          tooltip: {
            backgroundColor: 'rgba(15,23,42,0.95)',
            borderColor: 'rgba(51,65,85,0.8)',
            borderWidth: 1,
            titleColor: '#94a3b8',
            bodyColor: '#e2e8f0',
            padding: 10,
            cornerRadius: 10,
            callbacks: { label: ctx => '  ' + ctx.dataset.label + ':  ' + (ctx.parsed.y ?? '—') + ' ' + unit },
          },
        },
        scales: {
          x: {
            ticks: { color: '#334155', maxTicksLimit: 7, font: { size: 10 } },
            grid:  { color: 'rgba(30,41,59,0.8)', drawBorder: false },
            border: { display: false },
          },
          y: {
            ticks: { color: '#334155', font: { size: 10 }, callback: v => v + ' ' + unit },
            grid:  { color: 'rgba(30,41,59,0.8)', drawBorder: false },
            border: { display: false },
            min: 0,
          },
        },
      };
    },
  };
};
