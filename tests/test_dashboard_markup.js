const assert = require('assert');
const fs = require('fs');
const path = require('path');

const htmlPath = path.join(__dirname, '..', 'frontend', 'dashboard.html');
const html = fs.readFileSync(htmlPath, 'utf8');

assert.ok(!/Session Context/.test(html), 'Session Context card should not be rendered');
assert.ok(!/Threshold Reference/.test(html), 'Threshold Reference card should not be rendered');
assert.ok(!/Not available yet/.test(html), 'Session Context placeholder should be removed');
assert.ok(!/This feature is not available yet/.test(html), 'Session Context empty-state copy should be removed');
assert.ok(!/Future versions may summarize validated post-session feedback here/.test(html), 'Future placeholder copy should be removed');
assert.ok(!/Not enough information to estimate a personal threshold yet/.test(html), 'Threshold placeholder copy should be removed');

assert.ok(/id="personalizationCard"/.test(html), 'Limited personalization card should still render');

console.log('test_dashboard_markup: ok');
