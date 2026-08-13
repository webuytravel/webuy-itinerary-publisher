/*
 * Fill Skybear's "Create Display Detail" form from a plan + itinerary.
 *
 * Injected into the admin page as one payload, because the form is roughly
 * 230 fields per product and clicking them is not a plan. Everything below
 * was verified live against production on 2026-08-12/13; the notes say which
 * parts are load-bearing.
 *
 * Usage: window.__wbFill(payload) -> report object. Never saves; saving stays
 * a separate, deliberate step so the publish checkbox can be re-read first.
 *
 * ## Selecting the Tour Type (solved 2026-08-12, three wrong turns first)
 *
 * The control looks unfilterable and is not. Reading `input.readOnly` while
 * the field is unfocused returns **true**, which reads as "plain select, pick
 * from the list" — and the list only ever holds 20 options, none of them the
 * one you want. Both conclusions are wrong:
 *
 * 1. `readOnly` flips to **false** once the input is focused. Measure it after
 *    focus or the answer is meaningless.
 * 2. With focus, typing filters server-side down to an exact hit. There is no
 *    need to scroll the list at all, and scrolling never would have worked —
 *    those 20 options are the whole unfiltered response.
 * 3. Click the input **by element reference, not by screen coordinate**.
 *    Coordinate clicks landed on the input itself and cleared the filter.
 * 4. After clicking the option, the value reads back as `''` for a beat.
 *    That is the same lag as the publish checkbox: Element UI settles a tick
 *    later. Wait, then re-read — or look at the rendered page. Retrying here
 *    is what undoes the selection.
 *
 * Selecting the type auto-fills Product Name **with the brochure title**,
 * ampersand included — the exact string Skybear's own validator rejects.
 * `__wbFill` overwrites it; do not assume the auto-filled value is safe.
 *
 * **Selecting the type also clears every image already attached** (observed
 * 2026-08-13: a List Thumbneil uploaded beforehand was gone the moment the
 * type landed). Pick the type first, attach images last.
 *
 * ## Form shape
 *
 *   .itinerary-container .el-collapse-item      ← one per day
 *     .section-content .form-group              Section Name/Title/Location/
 *                                               Description/Photos
 *     .trip-items .trip-item .trip-content      Trip Type/Title/Description/
 *                                               Photos, repeated per landmark
 *
 * Required (`is-required`, measured not guessed): Tour Type, Product Name,
 * Highlight, List Thumbneil, Mobile Display Image, Desktop Display Image,
 * Itinerary, Section Name, Section Title, **Trip Type**, **Trip Title**.
 * Everything else — Route Map, Section Location/Description/Photos, Trip
 * Description/Photos, Cover Video Asset, Flight Info — is optional.
 *
 * ## Images
 *
 * Bytes do NOT come from a loopback server. That approach — `fetch` a local
 * http origin from the https admin page — hangs forever: the promise neither
 * resolves nor rejects and the console stays empty, so it reads as a bug in
 * your own code rather than as mixed-content blocking. Uploads go through the
 * browser extension's own file-input channel instead, driven from outside the
 * page; `__wbSlots()` exists to enumerate the targets for that caller.
 */

window.__wbFill = async function (payload) {
  const report = {filled: {}, warnings: [], sections: []};

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
  const label = (f) => (f.querySelector('.el-form-item__label') || {}).innerText?.trim() || '';
  const itemsIn = (root, want) =>
    [...root.querySelectorAll('.el-form-item')].filter(f => label(f) === want);
  const fieldsOf = (root, want, n = 0) => {
    const item = itemsIn(root, want)[n];
    return item ? [...item.querySelectorAll('input.el-input__inner, textarea')] : [];
  };
  const setPair = (root, want, value) => {
    const f = fieldsOf(root, want);
    if (f.length >= 2) { set(f[0], value.en); set(f[1], value.zh); return true; }
    if (f.length === 1) { set(f[0], value.en); return true; }
    return false;
  };

  const button = (root, text) =>
    [...root.querySelectorAll('button')].find(b => b.innerText.trim() === text);

  /* An el-select cannot be filled the way a text input can — the visible
   * input is a display shadow and writing to it leaves the bound value unset.
   * Element UI 2.x hangs the component off the element as `__vue__`, and
   * `handleOptionSelect` is the same entry point a real click goes through,
   * so this is a genuine selection rather than a painted one. */
  const setSelect = (root, want, optionLabel) => {
    const item = itemsIn(root, want)[0];
    const vm = item && item.querySelector('.el-select')?.__vue__;
    if (!vm) return false;
    const option = (vm.options || []).find(o => o.label === optionLabel);
    if (!option) return false;
    vm.handleOptionSelect(option);
    return true;
  };

  // ---- product name -------------------------------------------------------
  /* Skybear rejects any "&" here with "Cannot contain &", and every brochure
   * title in this batch has one. The caller is expected to have replaced it,
   * so this only guards against a regression — but the field arrives
   * pre-filled by the Tour Type selection with the raw brochure title, so
   * overwriting is mandatory, not cosmetic. */
  const form = document;
  if (/&/.test(payload.product_name.en) || /&/.test(payload.product_name.zh)) {
    report.warnings.push('product name still contains "&" — Skybear will reject it');
  }
  report.filled.product_name = setPair(form, 'Product Name', payload.product_name);

  // ---- highlights ---------------------------------------------------------
  const hlItem = [...document.querySelectorAll('.el-form-item')].find(f => label(f) === 'Highlight');
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

  // ---- sections -----------------------------------------------------------
  /* Fire every Add click in ONE synchronous burst, then wait once.
   *
   * The obvious shape — click, await, click, await — is what the first
   * version did, and on the 13-day tour it took over twenty minutes and still
   * had not finished. Each `await` hands control back to Vue, which re-renders
   * the entire itinerary before the next click; that render costs more with
   * every section already on the page, so the loop degrades from 250 ms per
   * click to tens of seconds per click.
   *
   * Vue batches: N clicks dispatched inside one synchronous block push N
   * entries onto the model and cost exactly ONE render. The same 13-day form
   * that took twenty minutes takes about sixteen seconds this way.
   *
   * The corollary is that nothing may be held across the burst — every
   * element queried before it is detached afterwards, and writing to a
   * detached input succeeds silently while changing nothing. So: burst, wait,
   * re-query, fill.
   */
  const sectionBlocks = () => [...document.querySelectorAll('.itinerary-container .el-collapse-item')];
  const settle = async (test, tries = 40, gap = 500) => {
    for (let i = 0; i < tries; i++) {
      if (test()) return true;
      await sleep(gap);
    }
    return false;
  };

  const wanted = payload.sections.length;
  const addSection = button(document, 'Add Section');
  for (let i = sectionBlocks().length; i < wanted; i++) addSection?.click();
  if (!await settle(() => sectionBlocks().length >= wanted)) {
    report.warnings.push(`only ${sectionBlocks().length}/${wanted} sections appeared`);
  }

  /* Trip items next, again as one burst across every section at once. Each
   * section arrives with exactly one trip item already present. */
  sectionBlocks().forEach((block, i) => {
    const section = payload.sections[i];
    if (!section) return;
    const add = button(block, 'Add Trip Item');
    const have = block.querySelectorAll('.trip-items .trip-item').length;
    for (let k = have; k < section.trip_items.length; k++) add?.click();
  });
  await settle(() => sectionBlocks().every((block, i) => !payload.sections[i]
    || block.querySelectorAll('.trip-items .trip-item').length
       >= payload.sections[i].trip_items.length));

  for (let i = 0; i < Math.min(wanted, sectionBlocks().length); i++) {
    const section = payload.sections[i];
    const blockAt = () => sectionBlocks()[i];
    const group = blockAt().querySelector('.form-group') || blockAt();

    setPair(group, 'Section Name', section.name);
    setPair(group, 'Section Title', section.title);
    setPair(group, 'Section Location', section.location);
    setPair(group, 'Section Description', section.description);

    /* Trip Type and Trip Title are both required, so a trip item that exists
     * and is left blank fails validation on Save. A day with no landmarks at
     * all — WBCHET's day 9 is just the flight home — therefore needs its
     * default row *deleted*, not filled with something invented; the caller
     * does that, since it takes a confirm dialog. */
    const trips = [...blockAt().querySelectorAll('.trip-items .trip-item')];
    if (!section.trip_items.length && trips.length) {
      report.warnings.push(`day ${section.day}: ${trips.length} blank trip item(s) to delete`);
    }
    let done = 0;
    for (let j = 0; j < Math.min(section.trip_items.length, trips.length); j++) {
      const item = section.trip_items[j];
      const root = trips[j];
      setSelect(root, 'Trip Type', item.trip_type || 'Attractions');
      setPair(root, 'Trip Title', item.title);
      setPair(root, 'Trip Description', item.description);
      done++;
    }
    report.sections.push({day: section.day, trips: done, of: section.trip_items.length});
  }

  // `blocks` never existed — this threw ReferenceError on every run, after the
  // form was already filled, so the fill looked like it failed and the report
  // was lost. The list is re-queried on purpose: the Add burst above detaches
  // anything captured earlier.
  report.filled.sections = Math.min(wanted, sectionBlocks().length);
  report.filled.trip_items = report.sections.reduce((n, s) => n + s.trips, 0);
  report.note = 'text filled; images are attached separately by the caller';
  return report;
};

/* Enumerate the upload targets so the caller can drive them.
 *
 * The extension's file upload wants an element reference it obtained itself,
 * so this does not attach anything — it reports how many slots exist per
 * label and in what order, which is what turns "the 4th Section Photos input"
 * into "day 4". Order is document order, and document order is day order.
 */
window.__wbSlots = function () {
  const label = (f) => (f.querySelector('.el-form-item__label') || {}).innerText?.trim() || '';
  const out = {};
  [...document.querySelectorAll('.el-form-item')].forEach(f => {
    const input = f.querySelector('input[type=file]');
    if (!input) return;
    (out[label(f)] = out[label(f)] || []).push(input.files.length);
  });
  return out;
};

/* Read the publish checkbox back.
 *
 * The initial value is **not predictable**: 2026-08-06 the CREATE form came up
 * with it already ticked, 2026-08-13 three consecutive creates came up with it
 * clear (it re-initialises when the Tour Type lands). So neither "it defaults
 * on" nor "it defaults off" is a rule you can code against — read it back
 * before every save, and look at the rendered page too. Always untick, wait,
 * then confirm: the class lags a tick behind the input, and reading too early
 * reports the old value, which makes a caller click again and tick it back on.
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
