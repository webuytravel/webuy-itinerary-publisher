/*
 * Fill Skybear's "Create Display Detail" form from a plan + itinerary.
 *
 * Injected into the admin page as one payload, because the form is roughly
 * 230 fields per product and clicking them is not a plan. Everything below
 * was verified live against production on 2026-08-12; the notes say which
 * parts are load-bearing.
 *
 * Usage: window.__wbFill(payload) -> report object. Never saves; saving stays
 * a separate, deliberate step so the publish checkbox can be re-read first.
 */

window.__wbFill = async function (payload) {
  const report = {filled: {}, warnings: [], images: {}};

  /* Element UI reads v-model off the native input event. Assigning .value
   * directly does NOT notify Vue — you get a field that looks right and
   * submits empty. The prototype setter plus a bubbling input event is what
   * actually lands, and it survives a re-render (verified: values persisted
   * across an Add Section that re-rendered the form). */
  const set = (el, text) => {
    if (!el) return false;
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement : HTMLInputElement;
    Object.getOwnPropertyDescriptor(proto.prototype, 'value').set.call(el, text ?? '');
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
    return true;
  };

  const sleep = (ms) => new Promise(r => setTimeout(r, ms));

  /* Label text is the only stable handle on this form — there are no ids and
   * the class names are Element UI's own. */
  const itemsByLabel = (label) =>
    [...document.querySelectorAll('.el-form-item')].filter(
      f => (f.querySelector('.el-form-item__label') || {}).innerText?.trim() === label);

  const button = (text) =>
    [...document.querySelectorAll('button')].find(b => b.innerText.trim() === text);

  // ---- product name -------------------------------------------------------
  /* Skybear rejects any "&" here with "Cannot contain &", and every brochure
   * title in this batch has one. The caller is expected to have replaced it,
   * so this only guards against a regression. */
  const nameItem = itemsByLabel('Product Name')[0];
  if (nameItem) {
    const [en, zh] = nameItem.querySelectorAll('input.el-input__inner');
    if (/&/.test(payload.product_name.en) || /&/.test(payload.product_name.zh)) {
      report.warnings.push('product name still contains "&" — Skybear will reject it');
    }
    set(en, payload.product_name.en);
    set(zh, payload.product_name.zh);
    report.filled.product_name = true;
  }

  // ---- highlights ---------------------------------------------------------
  /* The form ships a fixed set of highlight rows; extra content is dropped
   * rather than silently truncated into the last row. */
  const hlItem = itemsByLabel('Highlight')[0];
  if (hlItem) {
    const rows = hlItem.querySelectorAll('input.el-input__inner');
    const pairs = Math.floor(rows.length / 2);
    payload.highlights.slice(0, pairs).forEach((h, i) => {
      set(rows[i * 2], h.en);
      set(rows[i * 2 + 1], h.zh);
    });
    report.filled.highlights = Math.min(pairs, payload.highlights.length);
    if (payload.highlights.length > pairs) {
      report.warnings.push(
        `${payload.highlights.length - pairs} highlights dropped — form has ${pairs} rows`);
    }
  }

  // ---- sections + trip items ---------------------------------------------
  /* Each Add Section click appends one block; the buttons are re-queried
   * every iteration because the DOM is rebuilt each time. */
  const wanted = payload.sections.length;
  let guard = 0;
  while (itemsByLabel('Section Name').length < wanted && guard++ < 40) {
    button('Add Section')?.click();
    await sleep(220);
  }

  const nameItems = itemsByLabel('Section Name');
  report.filled.sections = 0;
  report.filled.trip_items = 0;

  for (let i = 0; i < Math.min(wanted, nameItems.length); i++) {
    const section = payload.sections[i];
    /* A section's fields live in the nearest common ancestor that also holds
     * its Section Name — walking up from the label is more robust than
     * assuming a card class name. */
    let block = nameItems[i];
    for (let up = 0; up < 6 && block && !block.querySelector('.el-form-item__label'); up++) {
      block = block.parentElement;
    }
    block = nameItems[i].closest('.el-card, .section-item, form, .el-form') || document;

    const grab = (label) =>
      [...block.querySelectorAll('.el-form-item')].filter(
        f => (f.querySelector('.el-form-item__label') || {}).innerText?.trim() === label);

    const pick = (label, n) => (grab(label)[n] || {}).querySelectorAll
      ? grab(label)[n].querySelectorAll('input.el-input__inner, textarea')
      : [];

    for (const [label, val] of [
      ['Section Name', section.name],
      ['Section Title', section.title],
      ['Section Location', section.location],
      ['Section Description', section.description],
    ]) {
      const fields = pick(label, i);
      if (fields.length >= 2) { set(fields[0], val.en); set(fields[1], val.zh); }
    }
    report.filled.sections++;
  }

  report.note = 'text filled; images and trip items are attached separately';
  return report;
};

/* Attach a generated crop to an el-upload slot.
 *
 * The slot is a plain input[type=file] behind a styled button. Assigning
 * input.files from a DataTransfer and dispatching change is accepted — the
 * component stores {file, preview} locally and uploads on Save. Bytes come
 * from a loopback server because Chrome exempts 127.0.0.1 from mixed-content
 * blocking, which is what lets locally-generated crops in without a picker.
 */
window.__wbAttach = async function (label, urls, nth = 0) {
  const item = [...document.querySelectorAll('.el-form-item')].filter(
    f => (f.querySelector('.el-form-item__label') || {}).innerText?.trim() === label)[nth];
  if (!item) return {ok: false, why: `no slot labelled ${label}`};
  const input = item.querySelector('input[type=file]');
  if (!input) return {ok: false, why: `slot ${label} has no file input`};

  const dt = new DataTransfer();
  for (const url of urls) {
    const res = await fetch(url);
    if (!res.ok) return {ok: false, why: `fetch ${url} -> ${res.status}`};
    const blob = await res.blob();
    dt.items.add(new File([blob], url.split('/').pop(), {type: blob.type || 'image/jpeg'}));
  }
  input.files = dt.files;
  input.dispatchEvent(new Event('change', {bubbles: true}));
  await new Promise(r => setTimeout(r, 400));
  return {ok: true, attached: dt.files.length, slot: label};
};

/* Read the publish checkbox back.
 *
 * On the CREATE form this initialises to **true** and renders already ticked,
 * so "never tick the box" is a no-op here — a plain Save publishes the
 * product to the live site. Always untick, wait, then confirm: the class
 * lags a tick behind the input, and reading too early reports the old value.
 */
window.__wbPublishState = function () {
  const box = [...document.querySelectorAll('.el-checkbox')].find(
    e => /Publish for sale/i.test(e.innerText || ''));
  if (!box) return {found: false};
  return {
    found: true,
    classChecked: box.classList.contains('is-checked'),
    inputChecked: box.querySelector('input')?.checked ?? null,
  };
};

window.__wbUnpublish = async function () {
  const box = [...document.querySelectorAll('.el-checkbox')].find(
    e => /Publish for sale/i.test(e.innerText || ''));
  if (!box) return {found: false};
  if (box.querySelector('input')?.checked) {
    (box.querySelector('.el-checkbox__inner') || box.querySelector('input')).click();
  }
  await new Promise(r => setTimeout(r, 800));  // the class lags the input
  return window.__wbPublishState();
};
