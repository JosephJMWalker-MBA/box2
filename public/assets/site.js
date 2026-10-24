'use strict';

const bookingForm = document.querySelector('#booking-form');
const bookingFields = document.querySelector('[data-booking-fields]');
const bookingSteps = [...document.querySelectorAll('[data-booking-step]')];
let bookingIndex = 0;
function showBookingStep(index, focus = true) {
  bookingIndex = index;
  bookingSteps.forEach((step, position) => { step.hidden = position !== index; });
  const progress = document.querySelector('[data-booking-progress]');
  if (progress) { progress.hidden = false; progress.textContent = `Booking step ${index + 1} of ${bookingSteps.length}`; }
  if (focus) { const heading = bookingSteps[index].querySelector('h2'); heading.tabIndex = -1; heading.focus(); }
}
function invalidField(step) {
  return [...step.querySelectorAll('input:not(:disabled), select:not(:disabled), textarea:not(:disabled)')]
    .find((field) => !field.checkValidity());
}
if (bookingForm && bookingSteps.length === 3) {
  bookingForm.noValidate = true;
  showBookingStep(0, false);
  bookingForm.querySelectorAll('[data-booking-next], [data-booking-back]').forEach((button) => {
    button.hidden = false;
    button.addEventListener('click', () => {
      if (button.hasAttribute('data-booking-next')) {
        const invalid = invalidField(bookingSteps[bookingIndex]);
        if (invalid) { invalid.reportValidity(); return; }
        showBookingStep(bookingIndex + 1);
      } else showBookingStep(bookingIndex - 1);
    });
  });
  bookingForm.addEventListener('submit', (event) => {
    for (let index = 0; index < bookingSteps.length; index++) {
      const invalid = invalidField(bookingSteps[index]);
      if (invalid) { event.preventDefault(); showBookingStep(index); invalid.reportValidity(); return; }
    }
  });
}

// Enhance a usable server-rendered form; every card acknowledgment is explicit.
const orientation = document.querySelector('[data-orientation]');
if (orientation) {
  const cards = [...orientation.querySelectorAll('.orientation-card')];
  const fields = document.querySelector('[data-booking-fields]');
  const check = orientation.querySelector('[data-orientation-check]');
  const actions = orientation.querySelector('[data-orientation-actions]');
  const previous = orientation.querySelector('[data-orientation-back]');
  const next = orientation.querySelector('[data-orientation-next]');
  const progress = orientation.querySelector('[data-orientation-progress]');
  if (cards.length && fields && check && actions && previous && next && progress) {
    let index = 0;
    const acknowledged = new Set();
    function render() {
      cards.forEach((card, position) => { card.hidden = position !== index; });
      previous.disabled = index === 0;
      progress.textContent = `Card ${index + 1} of ${cards.length} · ${acknowledged.size} acknowledged`;
      const meter = orientation.querySelector('[data-orientation-meter]');
      if (meter) meter.value = acknowledged.size;
      next.textContent = index === cards.length - 1 ? 'I understand. Open booking.' : 'I understand';
      const heading = cards[index].querySelector('h2');
      heading.tabIndex = -1;
    }
    fields.hidden = orientation.dataset.complete !== '1';
    check.closest('label').hidden = true;
    check.checked = orientation.dataset.complete === '1';
    if (check.checked) orientation.hidden = true;
    actions.hidden = false;
    previous.addEventListener('click', () => {
      index = Math.max(0, index - 1);
      render();
      cards[index].querySelector('h2').focus();
    });
    next.addEventListener('click', () => {
      acknowledged.add(index);
      if (index < cards.length - 1) {
        index += 1;
        render();
        cards[index].querySelector('h2').focus();
      } else if (acknowledged.size === cards.length) {
        check.checked = true;
        orientation.hidden = true;
        fields.hidden = false;
        showBookingStep(0);
      }
    });
    render();
  }
}

const lengthSelect = document.querySelector('#set-length');
const slotGrid = document.querySelector('#slot-grid');
function filterStarts() {
  if (!slotGrid || !lengthSelect) return;
  slotGrid.querySelectorAll('.slot').forEach((label) => {
    const fits = label.dataset.durations.split(',').includes(lengthSelect.value);
    label.hidden = label.classList.contains('available') && !fits;
    const input = label.querySelector('input');
    input.disabled = !fits;
    if (!fits) input.checked = false;
  });
}
if (lengthSelect) { lengthSelect.addEventListener('change', filterStarts); filterStarts(); }

// Changing nights replaces schedule controls only; performer details and grants stay in this form.
const nightForm = document.querySelector('#night-picker-form');
const nightSelect = document.querySelector('#night');
if (nightForm && nightSelect && bookingForm && slotGrid && lengthSelect) {
  let pending;
  async function refreshNight() {
    if (pending) pending.abort();
    pending = new AbortController();
    const status = document.querySelector('#slot-status');
    status.textContent = 'Loading actual stage allocations…';
    slotGrid.replaceChildren();
    const preferredLength = lengthSelect.value;
    lengthSelect.replaceChildren();
    try {
      const response = await fetch(`${nightForm.dataset.slotsUrl}?night=${encodeURIComponent(nightSelect.value)}`, { signal: pending.signal });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Stage allocations could not be loaded.');
      const durations = [...new Set(data.slots.flatMap((slot) => slot.durations))].sort((a, b) => a - b);
      durations.forEach((minutes) => {
        const option = document.createElement('option');
        option.value = String(minutes); option.textContent = `${minutes} min set · ${minutes * 2} min reserved`;
        lengthSelect.append(option);
      });
      if (durations.includes(Number(preferredLength))) lengthSelect.value = preferredLength;
      data.slots.forEach((slot) => {
        const label = document.createElement('label'); label.className = `slot ${slot.state}`;
        label.dataset.durations = slot.durations.join(','); label.dataset.visibility = slot.visibility;
        const input = document.createElement('input'); input.type = 'radio'; input.name = 'slot_id'; input.required = true; input.value = String(slot.id);
        const span = document.createElement('span'); span.textContent = slot.label;
        const detail = document.createElement('small');
        detail.textContent = slot.state !== 'available' ? slot.state : (slot.visibility === 'private' ? 'Private · no recording' : 'Public · livestream permission required');
        span.append(detail); label.append(input, span); slotGrid.append(label);
      });
      bookingForm.querySelector('[name="night_id"]').value = nightSelect.value;
      bookingSteps.forEach((step) => { step.querySelector('fieldset').disabled = !data.bookings_enabled; });
      status.textContent = durations.length ? `${data.night.show_date} · ${data.night.status}${data.night.override_note ? ` · ${data.night.override_note}` : ''}` : 'No consecutive open allocations fit a set on this show.';
      if (!data.bookings_enabled) status.textContent += ' Reservations are not open.';
      filterStarts();
    } catch (error) {
      if (error.name !== 'AbortError') status.textContent = error.message;
    }
  }
  nightForm.addEventListener('submit', (event) => { event.preventDefault(); refreshNight(); });
  nightSelect.addEventListener('change', refreshNight);
}

document.querySelectorAll('[data-share-url]').forEach((button) => {
  button.addEventListener('click', async () => {
    const link = button.dataset.shareUrl;
    const status = button.closest('.sharing').querySelector('[data-share-status]');
    try {
      if (navigator.share) await navigator.share({ title: 'BOX2 — Come Tell It Here First', url: link });
      else if (navigator.clipboard) { await navigator.clipboard.writeText(link); status.textContent = 'Link copied.'; }
      else { status.textContent = `Share this link: ${link}`; }
    } catch (error) { if (error.name !== 'AbortError') status.textContent = `Share this link: ${link}`; }
  });
});
