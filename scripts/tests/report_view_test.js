// Exercise filtering and parameter comparison without a browser dependency.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(value = '') { this.value = value; this.listeners = {}; this.children = []; }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  change(value) { this.value = value; this.listeners.input?.(); this.listeners.change?.(); }
  replaceChildren() { this.children = []; }
  appendChild(child) { this.children.push(child); }
  insertCell() { const cell = new Element(); this.appendChild(cell); return cell; }
  insertRow() { const row = new Element(); this.appendChild(row); return row; }
  createTHead() { this.head = new Element(); return this.head; }
  createTBody() { this.body = new Element(); return this.body; }
}
const configs = [
  {id: 'a', name: 'rv32i', fingerprint: '00000000', parameters: {ISA_M: 0, ISA_C: 0}},
  {id: 'b', name: 'rv32im', fingerprint: '11111111', parameters: {ISA_M: 1, ISA_C: 0}}
];
const right = new Element('a');
right.options = configs.map(config => ({value: config.id}));
Object.defineProperty(right, 'selectedIndex', {set(index) { this.value = this.options[index].value; }});
const controls = {
  search: new Element(), status: new Element(), scope: new Element('latest'),
  'visible-count': new Element(), 'configuration-data': new Element(),
  'compare-a': new Element('a'), 'compare-b': right,
  'parameter-comparison': new Element()
};
controls['configuration-data'].textContent = JSON.stringify(configs);
const rows = [
  {dataset: {search: 'rv32i alu', status: 'failed', latest: '0', config: 'a'}},
  {dataset: {search: 'rv32i alu', status: 'passed', latest: '1', config: 'a'}},
  {dataset: {search: 'rv32im muldiv', status: 'failed', latest: '1', config: 'b'}}
];
const document = {
  getElementById: id => controls[id],
  querySelectorAll: selector => selector === '.sort' ? [] : rows,
  createElement: () => new Element()
};
const code = fs.readFileSync(process.argv[2], 'utf8');
vm.runInNewContext(code, {document, URLSearchParams, location: {search: ''}});
assert.deepEqual(rows.map(row => row.hidden), [true, false, false]);
assert.equal(controls['visible-count'].textContent, '2 visible rows');
controls.scope.change('all');
assert.deepEqual(rows.map(row => row.hidden), [false, false, false]);
controls.status.change('failed');
assert.deepEqual(rows.map(row => row.hidden), [false, true, false]);
controls.search.change('muldiv');
assert.deepEqual(rows.map(row => row.hidden), [true, true, false]);
const table = controls['parameter-comparison'].children[0];
assert.equal(table.body.children.length, 2);
assert.equal(table.body.children[0].className, undefined); // ISA_C matches.
assert.equal(table.body.children[1].className, 'different'); // ISA_M differs.
controls['compare-b'].change('a');
assert.ok(controls['parameter-comparison'].children[0].body.children.every(row => !row.className));
console.log('Report filtering and parameter comparison passed');
