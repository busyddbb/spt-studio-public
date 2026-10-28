const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '..', 'native', 'PublishingQueue.swift'), 'utf8');

assert.match(source, /\/api\/publishing\/queue/);
assert.match(source, /queue_claim/);
assert.match(source, /queue_event/);
assert.match(source, /queue_cancel/);
assert.match(source, /activeAccounts/);
assert.match(source, /task\.job\.target == "image" \|\| task\.job\.target == "video"/);
assert.match(source, /submit click\n.*implicit/s);
console.log('native publishing queue contract: ok');
