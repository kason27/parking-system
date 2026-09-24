/* ParkFlow frontend: the API is the source of truth for every operator. */
const SLOT_COUNT = 40;
const API_BASE = window.PARKFLOW_API_BASE || '/api';
let records = [];
let slots = [];
let selectedSlot = null;
let checkoutRecordId = null;

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const pad = (value) => String(value).padStart(2, '0');
const formatTime = (date) => `${pad(date.getHours())}:${pad(date.getMinutes())}`;
const formatDuration = (minutes) => `${Math.floor(minutes / 60)}h ${pad(minutes % 60)}m`;
const slotName = (slot) => `G-${String(slot).padStart(2, '0')}`;

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, { headers: { 'Content-Type': 'application/json' }, ...options });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || 'The parking API is unavailable.');
  return payload;
}

function activeRecords() { return records.filter(record => record.status === 'active'); }
function availableSlots() { return slots.filter(slot => slot.status === 'available').map(slot => slot.id); }
function showToast(message, isError = false) {
  $('#toast-message').textContent = message;
  $('#toast').classList.toggle('error', isError);
  $('#toast').classList.add('show');
  setTimeout(() => $('#toast').classList.remove('show'), 3500);
}
function openModal(id) { const modal = $(`#${id}`); modal.classList.add('open'); modal.setAttribute('aria-hidden', 'false'); }
function closeModal(id) { const modal = $(`#${id}`); modal.classList.remove('open'); modal.setAttribute('aria-hidden', 'true'); }

function renderMap() {
  const map = $('#parking-map');
  map.innerHTML = '';
  slots.forEach(slot => {
    const record = activeRecords().find(item => item.slot === slot.id);
    const button = document.createElement('button');
    button.className = `slot ${record ? 'occupied' : ''}`;
    button.textContent = slot.code;
    button.title = record ? `${record.plate} · ${record.vehicleType}` : `Available slot ${slot.code}`;
    if (record) button.addEventListener('click', () => openExit(record.id));
    map.appendChild(button);
  });
  const available = availableSlots().length;
  $('#available-count').textContent = available;
  $('#occupancy-value').innerHTML = `${SLOT_COUNT - available}<span class="stat-denom"> / ${SLOT_COUNT}</span>`;
  $('#occupancy-bar-fill').style.width = `${((SLOT_COUNT - available) / SLOT_COUNT) * 100}%`;
}

function renderStats(summary) {
  $('#vehicles-value').textContent = summary.vehiclesToday;
  $('#vehicles-caption').textContent = `${summary.activeVehicles} currently inside`;
  $('#revenue-value').textContent = `Ksh ${summary.revenue.toLocaleString()}`;
  $('#avg-stay-value').textContent = formatDuration(summary.averageStayMinutes);
  $('#revenue-change').textContent = summary.revenue ? '12%' : '0%';
}

function renderArrivals() {
  const list = $('#arrival-list');
  const empty = $('#empty-arrivals');
  const recent = [...records].sort((a, b) => new Date(b.entryTime) - new Date(a.entryTime)).slice(0, 5);
  list.innerHTML = '';
  empty.style.display = recent.length ? 'none' : 'block';
  recent.forEach(record => {
    const item = document.createElement('div');
    item.className = 'arrival';
    const inside = record.status === 'active';
    item.innerHTML = `<span class="vehicle-icon">${record.vehicleType === 'Motorcycle' ? '♢' : '▰'}</span><div class="arrival-info"><strong>${record.plate}</strong><small>${record.slotCode} · ${record.vehicleType}</small></div><div class="arrival-time">${formatTime(new Date(record.entryTime))}<span class="arrival-status ${inside ? '' : 'out'}">${inside ? 'Inside' : 'Completed'}</span></div>`;
    if (inside) item.addEventListener('click', () => openExit(record.id));
    list.appendChild(item);
  });
}

function renderSlotOptions() {
  const container = $('#slot-options');
  const available = availableSlots();
  container.innerHTML = available.length ? available.map(slot => `<button type="button" class="slot-option" data-slot="${slot}">${slotName(slot)}</button>`).join('') : '<span class="muted">No spaces are available.</span>';
  $$('.slot-option').forEach(button => button.addEventListener('click', () => {
    $$('.slot-option').forEach(option => option.classList.remove('selected'));
    button.classList.add('selected');
    selectedSlot = Number(button.dataset.slot);
  }));
  if (available.length) { selectedSlot = available[0]; $(`.slot-option[data-slot="${selectedSlot}"]`).classList.add('selected'); }
}

async function refresh() {
  const [dashboard, currentSlots] = await Promise.all([api('/dashboard'), api('/slots')]);
  records = dashboard.slots;
  slots = currentSlots;
  renderMap();
  renderStats(dashboard);
  renderArrivals();
}

async function openEntry() {
  try { await refresh(); renderSlotOptions(); if (availableSlots().length) openModal('entry-modal'); else showToast('The car park is currently full.'); }
  catch (error) { showToast(error.message, true); }
}

async function openExit(id) {
  try {
    const quote = await api(`/sessions/${id}/quote`);
    checkoutRecordId = id;
    const record = quote.session;
    $('#checkout-summary').innerHTML = `<div class="checkout-row"><span>Vehicle</span><strong>${record.plate}</strong></div><div class="checkout-row"><span>Parking slot</span><strong>${record.slotCode}</strong></div><div class="checkout-row"><span>Entry time</span><strong>${formatTime(new Date(record.entryTime))}</strong></div><div class="checkout-row"><span>Total time</span><strong>${formatDuration(quote.durationMinutes)}</strong></div><div class="checkout-row checkout-total"><span>Amount due</span><strong>Ksh ${quote.amountDue.toLocaleString()}</strong></div>`;
    openModal('exit-modal');
  } catch (error) { showToast(error.message, true); await refresh(); }
}

$('#open-entry').addEventListener('click', openEntry);
$('#close-entry').addEventListener('click', () => closeModal('entry-modal'));
$('#cancel-entry').addEventListener('click', () => closeModal('entry-modal'));
$('#close-exit').addEventListener('click', () => closeModal('exit-modal'));
$('#cancel-exit').addEventListener('click', () => closeModal('exit-modal'));
$('#entry-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const plate = $('#plate-input').value.trim().toUpperCase();
  if (!selectedSlot || !plate) return;
  try {
    const record = await api('/sessions', { method: 'POST', body: JSON.stringify({ plate, vehicleType: $('#vehicle-type').value, slot: selectedSlot }) });
    closeModal('entry-modal'); event.target.reset(); showToast(`${record.plate} assigned to ${record.slotCode}.`); await refresh();
  } catch (error) { showToast(error.message, true); await refresh(); renderSlotOptions(); }
});
$('#pay-exit').addEventListener('click', async () => {
  if (!checkoutRecordId) return;
  try {
    const result = await api(`/sessions/${checkoutRecordId}/checkout`, { method: 'POST', body: JSON.stringify({ paymentMethod: 'M-Pesa' }) });
    closeModal('exit-modal'); showToast(`Payment received. Barrier ${result.barrier} for ${result.session.plate}.`); checkoutRecordId = null; await refresh();
  } catch (error) { showToast(error.message, true); }
});
$('#view-all').addEventListener('click', () => { $('#activity').scrollIntoView({ behavior: 'smooth' }); showToast('Showing the latest activity.'); });

refresh().catch(error => showToast(`API connection failed: ${error.message}`, true));
