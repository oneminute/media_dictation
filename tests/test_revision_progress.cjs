const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function page(fetch) {
  const elements = new Map(), timers = new Map();
  let timerId = 0;
  function get(id) {
    if (!elements.has(id)) elements.set(id, {
      value: '', textContent: '', style: {}, disabled: false, attrs: {}, events: {},
      addEventListener(name, handler) { this.events[name] = handler; },
      setAttribute(name, value) { this.attrs[name] = value; },
      removeAttribute(name) { delete this.attrs[name]; },
      hasAttribute(name) { return Object.hasOwn(this.attrs, name); }
    });
    return elements.get(id);
  }
  const window = {
    confirm: () => true, addEventListener() {},
    setTimeout(fn, ms) {
      if (ms === 1200) { queueMicrotask(fn); return 0; }
      const id = ++timerId; timers.set(id, fn); return id;
    },
    clearTimeout(id) { timers.delete(id); }
  };
  const context = vm.createContext({document: {getElementById: get}, window, fetch,
    localStorage: {getItem() { return null; }}, console, AbortController});
  const html = fs.readFileSync(path.join(__dirname, '../static/index.html'), 'utf8');
  const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
  vm.runInContext(script.replace('\nbootstrap();', ''), context);
  const run = code => vm.runInContext(code, context);
  run('loadVideo = async function() { return true; }');
  get('url').value = 'https://www.youtube.com/watch?v=UNP03fDSj1U';
  return { get, run, timers, window };
}

const response = job => ({ok: true, status: 200, json: async () => ({ok: true, job})});

test('progress is visible while creation is still waiting; cached result shows 100%', async () => {
  let release;
  const p = page(() => new Promise(resolve => { release = resolve; }));
  const pending = p.run('reviseYouTubeTranscript()');
  assert.equal(p.get('revisionProgress').style.display, 'block');
  assert.equal(p.get('revisionBar').hasAttribute('value'), false);
  assert.match(p.get('revisionDetail').textContent, /正在创建/);
  assert.equal(p.get('reviseYouTube').disabled, true);
  release(response({status: 'completed', cached: true}));
  await pending;
  assert.equal(p.get('revisionBar').value, 100);
  assert.match(p.get('revisionDetail').textContent, /缓存/);
  assert.equal(p.get('reviseYouTube').disabled, false);
  assert.equal(p.get('refreshRevisionProgress').disabled, false);
  assert.equal(p.timers.size, 0);
});

test('cancel does not submit or show progress', async () => {
  const p = page(() => { throw new Error('must not submit'); });
  p.window.confirm = () => false;
  await p.run('reviseYouTubeTranscript()');
  assert.notEqual(p.get('revisionProgress').style.display, 'block');
});

test('queued and running jobs poll until explicitly completed', async () => {
  const replies = [
    {status: 'queued', id: 'job1', progress: 0},
    {status: 'running', id: 'job1', progress: 48, detail: 'Whisper 转写中'},
    {status: 'completed', id: 'job1', progress: 100}
  ];
  const seen = [];
  const p = page(async url => { seen.push(url); return response(replies.shift()); });
  await p.run('reviseYouTubeTranscript()');
  assert.equal(seen.length, 3);
  assert.match(seen[1], /jobs\/job1$/);
  assert.equal(p.get('revisionBar').value, 100);
  assert.match(p.get('revisionDetail').textContent, /完成/);
});

test('creation timeout is visible, controls recover, and refresh resumes without resubmitting', async () => {
  let requests = 0;
  const p = page((url, options) => {
    requests++;
    if (requests > 1) return Promise.resolve(response({status: 'completed', id: 'job1'}));
    return new Promise((resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(new Error('aborted')));
    });
  });
  const pending = p.run('reviseYouTubeTranscript()');
  for (const callback of p.timers.values()) callback();
  await pending;
  assert.match(p.get('revisionDetail').textContent, /20 秒/);
  assert.equal(p.get('refreshRevisionProgress').disabled, false);
  await p.run('resumeRevisionProgress(true)');
  assert.equal(requests, 2);
  assert.equal(p.get('revisionBar').value, 100);
});

test('task failure and malformed job cannot be reported as completed', async () => {
  for (const job of [{status: 'failed', error: 'Whisper 未安装'}, {}, null]) {
    const p = page(async () => response(job));
    await p.run('reviseYouTubeTranscript()');
    assert.notEqual(p.get('revisionBar').value, 100);
    assert.match(p.get('revisionDetail').textContent, /刷新进度/);
    assert.equal(p.get('reviseYouTube').disabled, false);
  }
});

test('server errors stay visible and release controls', async () => {
  const p = page(async () => ({ok: false, status: 500, json: async () => ({ok: false, error: '数据库不可用'})}));
  await p.run('reviseYouTubeTranscript()');
  assert.match(p.get('revisionDetail').textContent, /数据库不可用/);
  assert.equal(p.get('revisionProgress').style.display, 'block');
  assert.equal(p.get('reviseYouTube').disabled, false);
});

test('duplicate click does not submit twice', async () => {
  let count = 0, release;
  const p = page(() => { count++; return new Promise(resolve => { release = resolve; }); });
  const pending = p.run('reviseYouTubeTranscript()');
  await p.run('reviseYouTubeTranscript()');
  assert.equal(count, 1);
  release(response({status: 'completed'}));
  await pending;
});

test('completed task retains load error instead of masking it with success', async () => {
  const p = page(async () => response({status: 'completed'}));
  p.run("loadVideo = async function() { document.getElementById('status').textContent='字幕载入错误'; return false; }");
  await p.run('reviseYouTubeTranscript()');
  assert.equal(p.get('status').textContent, '字幕载入错误');
  assert.match(p.get('revisionDetail').textContent, /字幕载入失败/);
});
