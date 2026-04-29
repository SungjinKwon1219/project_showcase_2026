/**
 * Guards profile page markup against reintroducing body-fat bracket UI copy.
 */
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const htmlPath = path.join(__dirname, '..', 'frontend', 'input.html');
const html = fs.readFileSync(htmlPath, 'utf8');

assert.ok(!/\bor pick a bracket\b/i.test(html), 'Bracket picker label must not appear');
assert.ok(html.indexOf('Model bucket') === -1, 'Model bucket wording must not appear');
assert.ok(html.indexOf('fat-btn') === -1, 'fat-btn class must not remain');
assert.ok(html.indexOf('fat-grid') === -1, 'fat-grid must not remain');
assert.ok(html.indexOf('Middle estimate') === -1, 'Middle estimate button copy must not appear');
assert.ok(html.indexOf('Lower estimate') === -1, 'Lower estimate bracket copy must not appear');
assert.ok(html.indexOf('Higher estimate') === -1, 'Higher estimate bracket copy must not appear');

assert.ok(html.indexOf('Used only as a broad modeling input for alcohol distribution') !== -1,
  'Expected neutral Body fat % helper text');

console.log('test_profile_input_markup: ok');
