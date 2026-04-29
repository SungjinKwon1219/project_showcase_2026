const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const htmlPath = path.join(__dirname, '..', 'frontend', 'bac-calculator.html');
const html = fs.readFileSync(htmlPath, 'utf8');

function extractFunctionSource(name) {
  const start = html.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `Could not find function ${name}`);
  let depth = 0;
  let end = -1;
  for (let i = start; i < html.length; i++) {
    const ch = html[i];
    if (ch === '{') depth += 1;
    else if (ch === '}') {
      depth -= 1;
      if (depth === 0) {
        end = i + 1;
        break;
      }
    }
  }
  assert.ok(end > start, `Could not parse function ${name}`);
  return html.slice(start, end);
}

const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(extractFunctionSource('curveSignatureFromPayload'), sandbox);
vm.runInContext(extractFunctionSource('estimateNearZeroHourFromCurve'), sandbox);
vm.runInContext(extractFunctionSource('finiteNumberOrNull'), sandbox);
vm.runInContext(extractFunctionSource('bacZoneForValue'), sandbox);
vm.runInContext(extractFunctionSource('graphYForBac'), sandbox);
vm.runInContext(extractFunctionSource('updateZoneLegend'), sandbox);

const signature = sandbox.curveSignatureFromPayload;
const nearZeroFromCurve = sandbox.estimateNearZeroHourFromCurve;
const bacZoneForValue = sandbox.bacZoneForValue;
const graphYForBac = sandbox.graphYForBac;
const updateZoneLegend = sandbox.updateZoneLegend;

const basePayload = {
  profile: { sex: 'male', age_years: 28, height_cm: 178, weight_kg: 72, body_fat_percent: 19, drinks_per_week: 4 },
  session: {
    grams_alcohol: 14,
    standard_drinks: 1,
    hours_elapsed: 0.5,
    drink_events: [{ grams_alcohol: 14, hours_from_session_start: 0.0 }],
  },
  history: { session_implied_betas: [] },
  personalization_settings: { limited_personalization_enabled: true },
};

const elapsedOnlyChanged = JSON.parse(JSON.stringify(basePayload));
elapsedOnlyChanged.session.hours_elapsed = 1.25;
assert.strictEqual(
  signature(basePayload),
  signature(elapsedOnlyChanged),
  'Signature should stay stable when only elapsed time changes'
);

const gramsChanged = JSON.parse(JSON.stringify(basePayload));
gramsChanged.session.grams_alcohol = 42;
gramsChanged.session.standard_drinks = 3;
gramsChanged.session.drink_events = [
  { grams_alcohol: 14, hours_from_session_start: 0.0 },
  { grams_alcohol: 14, hours_from_session_start: 0.0 },
  { grams_alcohol: 14, hours_from_session_start: 0.0 },
];
assert.notStrictEqual(
  signature(basePayload),
  signature(gramsChanged),
  'Signature should change when drink totals/events change'
);

const settingsChanged = JSON.parse(JSON.stringify(basePayload));
settingsChanged.personalization_settings.limited_personalization_enabled = false;
assert.notStrictEqual(
  signature(basePayload),
  signature(settingsChanged),
  'Signature should change when personalization settings change'
);

const curve = [
  { hour: 0.0, estimate: 0.0 },
  { hour: 0.5, estimate: 0.08 },
  { hour: 1.0, estimate: 0.12 },
  { hour: 1.5, estimate: 0.06 },
  { hour: 2.0, estimate: 0.002 },
];
assert.strictEqual(
  nearZeroFromCurve(curve, 0.0, 1.0),
  2.0,
  'Near-zero lookup should use the first <= threshold point after peak/current search start'
);

assert.strictEqual(bacZoneForValue(0.001), 'lower', '0.001 should map to lower');
assert.strictEqual(bacZoneForValue(0.080), 'mild', '0.080 should map to mild');
assert.strictEqual(bacZoneForValue(0.149), 'mild', '0.149 should map to mild');
assert.strictEqual(bacZoneForValue(0.150), 'intoxication', '0.150 should map to intoxication');
assert.strictEqual(bacZoneForValue(0.249), 'intoxication', '0.249 should map to intoxication');
assert.strictEqual(bacZoneForValue(0.250), 'heavy', '0.250 should map to heavy');

const y008 = graphYForBac(0.08, 0.40, 300);
const y006 = graphYForBac(0.06, 0.40, 300);
assert.ok(y006 > y008, '0.060 marker should render below the 0.08 threshold line');

function fakeCard(zone) {
  return {
    dataset: { bacZone: zone },
    classList: {
      _active: false,
      toggle(cls, on) {
        if (cls === 'active') this._active = Boolean(on);
      },
      contains(cls) {
        return cls === 'active' ? this._active : false;
      },
    },
    _attrs: {},
    setAttribute(name, value) { this._attrs[name] = value; },
    removeAttribute(name) { delete this._attrs[name]; },
  };
}

const cards = [fakeCard('lower'), fakeCard('mild'), fakeCard('intoxication'), fakeCard('heavy')];
sandbox.document = {
  querySelectorAll() { return cards; },
};

updateZoneLegend(0.07);
assert.ok(cards[0].classList.contains('active'), 'lower should be active at 0.07');
assert.ok(!cards[1].classList.contains('active'), 'mild should be inactive at 0.07');

updateZoneLegend(0.16);
assert.ok(!cards[0].classList.contains('active'), 'lower should deactivate when BAC increases');
assert.ok(cards[2].classList.contains('active'), 'intoxication should activate at 0.16');

updateZoneLegend(0.26);
assert.ok(cards[3].classList.contains('active'), 'heavy should activate at 0.26');
assert.strictEqual(cards.filter(c => c.classList.contains('active')).length, 1, 'only one zone card should be active');

console.log('test_bac_curve_cache_and_clear_time: ok');
