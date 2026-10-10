const dataSize = value => {
  const match = /^(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB)$/i.exec(String(value || '').trim());
  return match ? Number(match[1]) * 1024 ** ['KB', 'MB', 'GB', 'TB'].indexOf(match[2].toUpperCase()) : NaN;
};

class SimpoyoGauges extends HTMLElement {
  setConfig(config) {
    if (!config.entity) throw new Error('Simpoyo usage entity is required');
    this._entity = config.entity;
    this._signature = null;
    if (!this.shadowRoot) {
      const root = this.attachShadow({ mode: 'open' });
      root.innerHTML = '<style>.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:8px}</style><div id="grid" class="grid"></div>';
      this._grid = root.getElementById('grid');
    }
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._grid) return;
    if (this._helpers) return this._render();
    this._loading ||= window.loadCardHelpers().then(helpers => {
      this._helpers = helpers;
      this._render();
    });
  }

  _render() {
    const hass = this._hass;
    const source = hass.states[this._entity];
    const dateParts = new Intl.DateTimeFormat('en-US', {
      timeZone: hass.config?.time_zone, year: 'numeric', month: '2-digit', day: '2-digit',
    }).formatToParts(new Date());
    const parts = Object.fromEntries(dateParts.map(part => [part.type, part.value]));
    const today = Number(parts.year + parts.month + parts.day);
    const attrs = source?.attributes || {};
    const rows = Array.from({ length: Number(attrs.active_plan_count) || 0 }, (_, offset) => {
      const index = offset + 1;
      return {
        index,
        name: attrs[`plan_${index}_name`], iccid: attrs[`plan_${index}_iccid`],
        data_left: attrs[`plan_${index}_data_left`], total_data: attrs[`plan_${index}_total_data`],
        valid_until: attrs[`plan_${index}_valid_until`],
      };
    });
    const plans = rows.flatMap(plan => {
      const date = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(plan.valid_until || '');
      const expiry = date && Number(date[3] + date[2] + date[1]);
      const left = dataSize(plan.data_left);
      const total = dataSize(plan.total_data);
      if (!expiry || expiry < today || !(left > 0) || !(total > 0)) return [];
      return [{ ...plan, percent: Math.min(100, Math.max(0.01, Math.round(left / total * 10000) / 100)) }];
    });
    const signature = JSON.stringify(plans.map(plan => [plan.index, plan.name, plan.iccid, plan.data_left, plan.total_data]));
    if (signature !== this._signature) {
      this._signature = signature;
      this._cards = plans.map(plan => this._helpers.createCardElement({
        type: 'gauge',
        entity: this._entity,
        attribute: `simpoyo_plan_${plan.index}_percent`,
        name: `${plan.name || `SIM ••••${String(plan.iccid || '').slice(-4)}`} · ${plan.data_left} left`,
        unit: '%', min: 0, max: 100, needle: true,
        severity: { red: 0, yellow: 20, green: 60 },
      }));
      this._grid.replaceChildren(...this._cards);
    }
    if (!source) return;
    const virtualState = { ...source, attributes: { ...source.attributes } };
    for (const plan of plans) virtualState.attributes[`simpoyo_plan_${plan.index}_percent`] = plan.percent;
    const virtualHass = { ...hass, states: { ...hass.states, [this._entity]: virtualState } };
    for (const card of this._cards) card.hass = virtualHass;
  }

  getCardSize() { return 3; }
}

customElements.define('simpoyo-gauges', SimpoyoGauges);
