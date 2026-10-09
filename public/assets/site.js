'use strict';

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
      next.textContent = index === cards.length - 1 ? 'I understand. Open booking.' : 'I understand';
      const heading = cards[index].querySelector('h2');
      heading.tabIndex = -1;
    }
    fields.hidden = true;
    check.closest('label').hidden = true;
    check.checked = false;
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
        fields.querySelector('legend').tabIndex = -1;
        fields.querySelector('legend').focus();
      }
    });
    render();
  }
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
