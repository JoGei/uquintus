'use strict';
// Everything is already in the HTML: no fetch, server, CDN or runtime package.
const search = document.getElementById('search');
const statusFilter = document.getElementById('status');
const scope = document.getElementById('scope');
const selectedConfig = new URLSearchParams(location.search).get('config');
function filterRows() {
  const query = search ? search.value.toLowerCase().trim() : '';
  let count = 0;
  document.querySelectorAll('.filter-table tbody tr').forEach(row => {
    const visible = (!query || (row.dataset.search || '').includes(query)) &&
      (!statusFilter || !statusFilter.value || row.dataset.status === statusFilter.value) &&
      (!scope || scope.value === 'all' || row.dataset.latest === '1') &&
      (!selectedConfig || !row.dataset.config || row.dataset.config === selectedConfig);
    row.hidden = !visible;
    if (visible) count++;
  });
  const counter = document.getElementById('visible-count');
  if (counter) counter.textContent = `${count} visible rows`;
}
[search, statusFilter, scope].filter(Boolean).forEach(input => input.addEventListener('input', filterRows));
document.querySelectorAll('.sort').forEach(button => {
  button.addEventListener('click', () => {
    const th = button.closest('th');
    const table = button.closest('table');
    const position = [...th.parentElement.children].indexOf(th);
    const descending = th.getAttribute('aria-sort') === 'ascending';
    table.querySelectorAll('th').forEach(header => header.removeAttribute('aria-sort'));
    th.setAttribute('aria-sort', descending ? 'descending' : 'ascending');
    const rows = [...table.tBodies[0].rows];
    rows.sort((a, b) => a.cells[position].textContent.localeCompare(
      b.cells[position].textContent, undefined, {numeric: true}) * (descending ? -1 : 1));
    rows.forEach(row => table.tBodies[0].appendChild(row));
  });
});
const configurationData = document.getElementById('configuration-data');
if (configurationData) {
  const configs = JSON.parse(configurationData.textContent);
  const left = document.getElementById('compare-a');
  const right = document.getElementById('compare-b');
  if (right.options.length > 1) right.selectedIndex = 1;
  function compare() {
    const a = configs.find(config => config.id === left.value);
    const b = configs.find(config => config.id === right.value);
    const container = document.getElementById('parameter-comparison');
    container.replaceChildren();
    if (!a || !b) return;
    const table = document.createElement('table');
    const header = table.createTHead().insertRow();
    ['Parameter', `${a.name} · ${a.fingerprint.slice(0, 8)}`, `${b.name} · ${b.fingerprint.slice(0, 8)}`].forEach(label => {
      const cell = document.createElement('th'); cell.textContent = label; header.appendChild(cell);
    });
    const body = table.createTBody();
    [...new Set([...Object.keys(a.parameters), ...Object.keys(b.parameters)])].sort().forEach(name => {
      const row = body.insertRow();
      const av = JSON.stringify(a.parameters[name]);
      const bv = JSON.stringify(b.parameters[name]);
      if (av !== bv) row.className = 'different';
      [name, av === undefined ? 'not recorded' : av, bv === undefined ? 'not recorded' : bv].forEach(value => {
        row.insertCell().textContent = value;
      });
    });
    container.appendChild(table);
  }
  left.addEventListener('change', compare);
  right.addEventListener('change', compare);
  compare();
}
filterRows();
