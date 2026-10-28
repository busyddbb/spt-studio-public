'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const appPath = path.join(__dirname, '..', 'app', 'static', 'app.js');

// Evaluate the actual top-level function, without booting the DOM application or
// duplicating its implementation. These declarations share the module's indent.
function applicationFunction(name, globals = {}) {
  const source = fs.readFileSync(appPath, 'utf8');
  const declaration = new RegExp(`^  (?:async )?function ${name}\\(`, 'm');
  const start = source.search(declaration);
  assert.notEqual(start, -1, `Missing application function: ${name}`);
  const afterStart = source.slice(start + 1);
  const next = afterStart.search(/^  (?:async )?function [\w$]+\(/m);
  const functionSource = next === -1 ? source.slice(start) : source.slice(start, start + 1 + next);
  return vm.runInNewContext(`${functionSource}\n${name};`, globals, {filename: appPath});
}

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return {promise, resolve};
}

const flushPromises = () => new Promise(resolve => setImmediate(resolve));

test('late account full-state response cannot overwrite the newly selected dataset', async () => {
  const S = {
    request: 0, dataset: 'demo', accountId: 'demo-account', full: null,
    data: null, loading: false, error: '', view: 'planner'
  };
  const requests = [];
  const renders = [];
  const loadState = applicationFunction('loadState', {
    S,
    api(url) {
      const pending = deferred();
      requests.push({url, ...pending});
      return pending.promise;
    },
    render() { renders.push({dataset: S.dataset, full: S.full, data: S.data}); },
    loadResearch() { throw new Error('Calendar state loading should not request research'); }
  });

  const staleLoad = loadState();
  requests[0].resolve({dataset: 'demo', accounts: [{id: 'demo-account'}], drafts: []});
  await flushPromises();
  assert.equal(requests.length, 2, 'the account request is waiting for its full dataset');
  assert.equal(requests[1].url, '/api/state?dataset=demo');

  // This corresponds to the persistent demo banner's "return to real workspace"
  // action while the selected account's second request remains outstanding.
  S.dataset = 'real';
  S.accountId = '';
  S.full = null;
  const currentLoad = loadState();
  assert.equal(requests[2].url, '/api/state?dataset=real');
  const realState = {dataset: 'real', accounts: [{id: 'real-account'}], drafts: [{id: 'real-draft'}]};
  requests[2].resolve(realState);
  await currentLoad;
  assert.strictEqual(S.full, realState);
  assert.strictEqual(S.data, realState);
  const rendersAfterCurrentLoad = renders.length;

  requests[1].resolve({dataset: 'demo', accounts: [{id: 'demo-account'}], drafts: []});
  await staleLoad;
  assert.strictEqual(S.full, realState, 'old full response must not replace real accounts or drafts');
  assert.strictEqual(S.data, realState, 'old filtered response must not replace the new dataset');
  assert.equal(S.dataset, 'real');
  assert.equal(S.loading, false);
  assert.equal(S.error, '');
  assert.equal(renders.length, rendersAfterCurrentLoad, 'a stale response must not render again');
});

test('scheduleISO rejects the Los Angeles DST gap and preserves valid or empty schedules', () => {
  const previousTimezone = process.env.TZ;
  process.env.TZ = 'America/Los_Angeles';
  try {
    const scheduleISO = applicationFunction('scheduleISO', {Date, Intl});
    assert.throws(() => scheduleISO('2027-03-14T02:30'), undefined,
      '02:30 does not exist during the spring daylight-saving transition');
    assert.equal(scheduleISO('2027-03-14T03:30'), '2027-03-14T10:30:00.000Z');
    assert.equal(scheduleISO(''), '');
  } finally {
    if (previousTimezone === undefined) delete process.env.TZ;
    else process.env.TZ = previousTimezone;
  }
});

test('editing text preserves ordered media, appends new choices and removes unchecked files', () => {
  const S = {model:{media_ids:['c','a'],platforms:['instagram'],account_ids:[]},editorPlatform:'base'};
  let selected = ['a','b','c'];
  const form = {querySelector:()=>({}),querySelectorAll:()=>[{value:'instagram'}]};
  const nodes = {'draft-form':form,'char-count':{},'preview-container':{}};
  class FormDataMock {
    get(key) { return key==='body'?'编辑过的正文':key==='title'?'标题':''; }
    getAll(key) { return key==='media_ids'?selected:[]; }
  }
  const updateModel = applicationFunction('updateModel', {
    S, FormData:FormDataMock, $:id=>nodes[id], accountById:()=>null,
    editorText:()=>S.model.body,renderPreview:()=>'',renderDraftEditor:()=>''
  });
  updateModel();
  assert.deepEqual(Array.from(S.model.media_ids),['c','a','b']);
  updateModel();
  assert.deepEqual(Array.from(S.model.media_ids),['c','a','b']);
  selected=['b','c'];
  updateModel();
  assert.deepEqual(Array.from(S.model.media_ids),['c','b']);
});
