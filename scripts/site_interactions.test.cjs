// SPDX-License-Identifier: Apache-2.0
// Code authors: Vijay and Codex
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../assets/site.js'), 'utf8');
const eventOptions = {
  url: 'https://llm-measurement.github.io/litellm-spend.html',
  props: { path: '/litellm-spend.html' },
};

class Element {
  constructor(tag, text = '', attrs = {}) {
    this.tagName = tag.toUpperCase();
    this.textContent = text;
    this.attrs = attrs;
    this.dataset = {};
    this.children = [];
    this.listeners = {};
  }
  hasAttribute(name) { return name in this.attrs; }
  setAttribute(name, value) { this.attrs[name] = value; }
  querySelector(tag) { return this.children.find(c => c.tagName === tag.toUpperCase()); }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  fire(name) { return this.listeners[name]?.(); }
  append(...children) {
    for (const child of children) {
      if (child.parentNode) child.parentNode.children = child.parentNode.children.filter(c => c !== child);
      child.parentNode = this;
      this.children.push(child);
    }
  }
  insertBefore(child, before) {
    child.parentNode = this;
    this.children.splice(this.children.indexOf(before), 0, child);
  }
}

function setup({ text = '  command --value "private-ID"\n\n', attrs = {}, clipboard = true, analytics = true } = {}) {
  const pre = new Element('pre', '', attrs);
  const code = new Element('code', text);
  pre.append(code);
  const main = new Element('main');
  main.append(pre);
  const links = ['email', 'questions', 'show-and-tell'].map(name => {
    const link = new Element('a');
    link.dataset.contact = name;
    return link;
  });
  const copies = [], events = [];
  const window = { location: {
    origin: 'https://llm-measurement.github.io', pathname: '/litellm-spend.html',
    search: '?email=private-email&userid=private-ID&command=private-command', hash: '#private-ID',
  } };
  if (analytics) window.plausible = (name, options) => events.push(JSON.parse(JSON.stringify({ name, options })));
  const navigator = clipboard ? { clipboard: { writeText: async value => copies.push(value) } } : {};
  const document = {
    createElement: tag => new Element(tag),
    querySelectorAll: selector => {
      if (selector === 'a[data-contact]') return links;
      assert.equal(selector, 'main pre:not(.output)');
      return attrs.class === 'output' ? [] : [pre];
    },
  };
  vm.runInNewContext(source, { window, document, navigator });
  const tools = pre.parentNode === main ? null : pre.parentNode.children[0];
  return { code, pre, main, links, window, copies, events, button: tools?.children[1], status: tools?.children[0], navigator };
}

test('copy preserves displayed whitespace and never includes the button/status text', async () => {
  const value = ["  printf 'a & b < c' \\" , '  --identifier=private-ID', '', ''].join('\n');
  const state = setup({ text: value });
  assert.equal(state.button.tagName, 'BUTTON');
  assert.equal(state.button.type, 'button');
  assert.equal(state.button.attrs['aria-label'], 'Copy analysis command');
  assert.equal(state.status.attrs.role, 'status');
  await state.button.fire('click');
  assert.deepEqual(state.copies, [value]);
  assert.equal(state.code.textContent, value);
  assert.equal(state.status.textContent, 'Copied');
  assert.deepEqual(state.events, [{ name: 'Copy analysis command', options: eventOptions }]);
});

for (const [attrs, text, event] of [
  [{}, 'curl install-fleetdiff.sh', 'Copy install command'],
  [{}, 'python3 -m pip install tool', 'Copy install command'],
  [{}, 'go get example.com/tool', 'Copy install command'],
  [{}, 'fleetdiff investigate --litellm-db', 'Copy database command'],
  [{}, 'psql "$DATABASE_URL"', 'Copy database command'],
  [{ 'data-sql': 'never-send-this-id' }, 'GRANT SELECT', 'Copy database command'],
  [{ 'data-config': 'private-ID' }, 'exporters:\n  file:', 'Copy configuration'],
  [{ 'data-review': 'private-ID' }, 'gh attestation verify', 'Copy verification command'],
  [{ 'data-run': 'private-ID' }, 'run-example', 'Copy example command'],
]) {
  test(event + ' uses only its fixed name and page path', async () => {
    const state = setup({ attrs, text });
    await state.button.fire('click');
    assert.deepEqual(state.copies, [text]);
    assert.deepEqual(state.events, [{ name: event, options: eventOptions }]);
  });
}

test('output blocks receive no command button', () => {
  assert.equal(setup({ attrs: { class: 'output' } }).button, undefined);
});

test('clipboard denial or absence is accessible and never records successful copying', async () => {
  for (const missing of [false, true]) {
    const state = setup({ clipboard: !missing });
    if (!missing) state.navigator.clipboard.writeText = async () => { throw new Error('denied'); };
    await state.button.fire('click');
    assert.equal(state.status.textContent, 'Copy unavailable; select the text to copy.');
    assert.deepEqual(state.events, []);
    assert.equal(state.button.attrs['aria-label'], 'Copy analysis command');
  }
});

test('contact events contain only the fixed event name and page path', () => {
  const state = setup();
  state.links.forEach(link => link.fire('click'));
  assert.deepEqual(state.events, ['Contact email', 'Contact Q&A', 'Contact Show-and-tell'].map(name => ({
    name, options: eventOptions,
  })));
});

test('missing or failing analytics cannot break copying or contact activation', async () => {
  for (const present of [false, true]) {
    const state = setup({ analytics: present });
    if (present) state.window.plausible = () => { throw new Error('blocked'); };
    await state.button.fire('click');
    assert.equal(state.status.textContent, 'Copied');
    state.links.forEach(link => assert.doesNotThrow(() => link.fire('click')));
  }
});
