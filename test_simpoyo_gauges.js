const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

test('creates and updates one built-in gauge per active plan with data left', async () => {
  let Card;
  const grid = { children: [], replaceChildren(...children) { this.children = children; } };
  class HTMLElement {
    attachShadow() {
      if (this.shadowRoot) throw new Error('shadow root already attached');
      this.shadowRoot = { innerHTML: '', getElementById: () => grid };
      return this.shadowRoot;
    }
  }
  const helpers = {
    createCardElement(config) {
      return { config, set hass(value) { this.currentHass = value; } };
    },
  };
  const context = {
    HTMLElement,
    customElements: { define(name, value) { if (name === 'simpoyo-gauges') Card = value; } },
    window: { loadCardHelpers: async () => helpers },
    Intl,
    Date,
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'simpoyo-gauges.js'), 'utf8'), context);
  assert.ok(Card, 'card is registered');

  const card = new Card();
  card.setConfig({ entity: 'sensor.simpoyo_data_used' });
  card.setConfig({ entity: 'sensor.simpoyo_data_used' });
  const plan = (name, left, total, until) => ({
    name, iccid: '12345678901234567890', plan: 'Travel',
    data_left: left, total_data: total, valid_until: until,
  });
  const state = plans => {
    const attributes = { active_plan_count: plans.length };
    plans.forEach((plan, index) => {
      for (const [key, value] of Object.entries(plan)) attributes[`plan_${index + 1}_${key}`] = value;
    });
    return {
      config: { time_zone: 'America/Denver' },
      states: {
        'sensor.simpoyo_data_used': { state: '16.08', attributes },
      },
    };
  };

  card.hass = state([
    plan('Usable', '0.42GB', '8GB', '30/09/2099'),
    plan('Empty', '0GB', '8GB', '30/09/2099'),
    plan('Expired', '1GB', '8GB', '01/01/2000'),
  ]);
  await new Promise(setImmediate);
  assert.equal(grid.children.length, 1);
  assert.equal(grid.children[0].config.type, 'gauge');
  assert.match(grid.children[0].config.name, /Usable.*0\.42GB/);
  assert.equal(grid.children[0].currentHass.states['sensor.simpoyo_data_used'].attributes[grid.children[0].config.attribute], 5.25);

  card.hass = state([
    plan('Usable', '0.42GB', '8GB', '30/09/2099'),
    plan('Empty', '512MB', '1GB', '30/09/2099'),
  ]);
  await new Promise(setImmediate);
  assert.equal(grid.children.length, 2);
  assert.equal(grid.children[1].config.type, 'gauge');
  assert.equal(grid.children[1].currentHass.states['sensor.simpoyo_data_used'].attributes[grid.children[1].config.attribute], 50);

  card.hass = state([plan('Empty', '0GB', '8GB', '30/09/2099')]);
  await new Promise(setImmediate);
  assert.equal(grid.children.length, 0);
});
