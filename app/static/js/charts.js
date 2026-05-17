// Alpine x-data factory for the throughput + latency charts on the dashboard.

window.metricsChart = function () {
  return {
    range: '1h',
    chartRx: null,
    chartLat: null,
    timer: null,

    init() {
      this.loadMetrics();
      this.timer = setInterval(() => this.loadMetrics(), 30000);

      // Resize charts when the section becomes visible again (tab switching)
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
      if (this.range === '1h' || this.range === '12h' || this.range === '1d') {
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

      const labels = d.labels.map(ts => this._fmtLabel(ts));
      const base = { borderWidth: 1.5, pointRadius: 0, tension: 0.3, fill: true };

      if (this.chartRx) {
        this.chartRx.data.labels = labels;
        this.chartRx.data.datasets[0].data = d.rx;
        this.chartRx.data.datasets[1].data = d.tx;
        this.chartRx.update('none');
      } else {
        this.chartRx = new Chart(document.getElementById('chart-throughput'), {
          type: 'line',
          data: {
            labels,
            datasets: [
              { label: '↓ Download', data: d.rx, borderColor: 'rgb(52,211,153)', backgroundColor: 'rgba(52,211,153,0.08)', ...base },
              { label: '↑ Upload',   data: d.tx, borderColor: 'rgb(56,189,248)', backgroundColor: 'rgba(56,189,248,0.06)', ...base },
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
        this.chartLat = new Chart(document.getElementById('chart-latency'), {
          type: 'line',
          data: {
            labels,
            datasets: [{ label: 'Latency', data: d.latency, borderColor: 'rgb(251,191,36)', backgroundColor: 'rgba(251,191,36,0.07)', ...base }],
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
          legend:  { labels: { color: '#94a3b8', boxWidth: 12, font: { size: 11 } } },
          tooltip: { callbacks: { label: ctx => ' ' + ctx.dataset.label + ': ' + (ctx.parsed.y ?? '—') + ' ' + unit } },
        },
        scales: {
          x: { ticks: { color: '#475569', maxTicksLimit: 8, font: { size: 10 } }, grid: { color: 'rgba(51,65,85,0.4)' } },
          y: { ticks: { color: '#475569', font: { size: 10 }, callback: v => v + ' ' + unit }, grid: { color: 'rgba(51,65,85,0.4)' }, min: 0 },
        },
      };
    },
  };
};
