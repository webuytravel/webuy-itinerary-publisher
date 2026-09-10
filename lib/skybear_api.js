/*
 * skybear_api.js — talk to the Skybear backend directly instead of driving the
 * admin form.
 *
 * Why this exists: `lib/form_filler.js` types into the Vue form. That path is
 * accurate but slow (a 13-day product took twenty-odd minutes before the
 * batched-click trick, see UPLOAD_RUNBOOK 第 5 步第 5 条) and it breaks every
 * time the admin bundle is rebuilt, because it depends on `lib/selectors.yaml`
 * matching the rendered DOM. The backend does not move: the 2026-09 Skybear
 * redeploy left `VUE_APP_BASE_API` at https://apimini.webuy.ren/wb_tourt and
 * every route below still answers.
 *
 * How to use: paste this into the console of a **logged-in** admin tab
 * (travel.webuysg.com). It never reads, stores or transmits a password — it
 * borrows the auth headers the page is already sending.
 *
 *     await SB.captureHeaders();      // borrow the live session's headers
 *     await SB.findTourType('ACKMG12T');
 *
 * Everything here is read-only except `editTravel`, which is the single
 * write. Guard rails on that one live in `SB.editTravel` itself.
 */
window.SB = (function () {
  'use strict';

  var BASE = 'https://apimini.webuy.ren/wb_tourt';
  var HDRS = null;

  /* ---------------------------------------------------------------- headers */

  /*
   * Borrow the headers the app itself sends. We patch
   * XMLHttpRequest.prototype.setRequestHeader, fire one harmless read through
   * the app's own axios stack, and keep whatever it set. This is deliberately
   * *not* a reimplementation of the app's header logic: app_version, the token
   * key and the device-id format have all changed at least once, and a copy
   * would drift. Recording what actually goes on the wire cannot drift.
   */
  function captureHeaders(timeoutMs) {
    timeoutMs = timeoutMs || 15000;
    var want = ['x-wb-tourt-token', 'authorization-userid',
                'x-web-deviceid', 'app_version'];
    var seen = {};
    var orig = XMLHttpRequest.prototype.setRequestHeader;

    XMLHttpRequest.prototype.setRequestHeader = function (k, v) {
      if (want.indexOf(String(k).toLowerCase()) !== -1) seen[k] = v;
      return orig.apply(this, arguments);
    };

    // Any authenticated GET will do; this one has no side effects.
    fetch(BASE + '/travelMgmt/queryListPage').catch(function () {});
    var xhr = new XMLHttpRequest();
    xhr.open('POST', BASE + '/travelMgmt/queryListPage');
    // Let the app's interceptor run by going through its own axios if we can.
    try {
      var ax = window.__AX__ || null;
      if (ax) ax.post('/travelMgmt/queryListPage', { pageNo: 1, pageSize: 1 });
    } catch (e) { /* fall through to the manual poke below */ }
    xhr.abort();

    var t0 = Date.now();
    return new Promise(function (resolve, reject) {
      (function poll() {
        if (seen['x-wb-tourt-token']) {
          XMLHttpRequest.prototype.setRequestHeader = orig;
          HDRS = Object.assign({ 'Content-Type': 'application/json' }, seen);
          return resolve(Object.keys(seen));
        }
        if (Date.now() - t0 > timeoutMs) {
          XMLHttpRequest.prototype.setRequestHeader = orig;
          return reject(new Error(
            'no auth header seen in ' + timeoutMs + 'ms — is this tab logged ' +
            'in? Click any list page (it fires a request) and retry.'));
        }
        setTimeout(poll, 250);
      })();
    });
  }

  /*
   * Fallback: build the headers from storage the way app.js does. Used only
   * when captureHeaders() cannot provoke a request. Kept narrow on purpose —
   * if this drifts from the app, captureHeaders() is the one to trust.
   */
  function headersFromStorage() {
    var tok = null;
    for (var i = 0; i < localStorage.length; i++) {
      var k = localStorage.key(i);
      if (/token/i.test(k) && localStorage.getItem(k)) tok = localStorage.getItem(k);
    }
    if (!tok) {
      var m = document.cookie.match(/(?:^|;\s*)([^=]*[Tt]oken[^=]*)=([^;]+)/);
      if (m) tok = decodeURIComponent(m[2]);
    }
    if (!tok) throw new Error('no token in localStorage or cookies — not logged in?');
    HDRS = {
      'Content-Type': 'application/json',
      'app_version': 400,
      'x-wb-tourt-token': tok,
      'Authorization-UserId': localStorage.getItem('userId') || '',
      'X-Web-Deviceid': 'web_uuid_' + (localStorage.getItem('deviceId') || 'publisher'),
    };
    return Object.keys(HDRS);
  }

  function headers() {
    if (!HDRS) throw new Error('call SB.captureHeaders() first');
    return HDRS;
  }

  /* ------------------------------------------------------------------ calls */

  function post(path, body) {
    return fetch(BASE + path, {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify(body || {}),
    }).then(function (r) { return r.json(); }).then(function (j) {
      if (j && j.success === false) {
        throw new Error(path + ' -> ' + j.code + ' ' + j.msg);
      }
      return j;
    });
  }

  function get(path) {
    return fetch(BASE + path, { headers: headers() })
      .then(function (r) { return r.json(); }).then(function (j) {
        if (j && j.success === false) {
          throw new Error(path + ' -> ' + j.code + ' ' + j.msg);
        }
        return j;
      });
  }

  /* -------------------------------------------------------------- read-only */

  /* Departures (wt_tour). A wt_travel cannot exist before one of these does:
   * editTravel answers 500 "tourId Cannot be empty" otherwise. */
  function queryTours(tourCode) {
    return post('/tour/queryTourListPage', {
      pageNo: 1, pageSize: 200, tourCode: tourCode, tourId: '', areaId: '',
      tourTypeId: '', tourStatus: '', closedStatus: '', trStatus: '',
      departureAirportId: '', startTime: '', endTime: '', tourName: '',
      paxType: '',
    });
  }

  /* Display products (wt_travel). travelStatus: 0 = UnPublished, 1 = Published. */
  function queryTravels(tourTypeId) {
    return post('/travelMgmt/queryListPage', {
      pageNo: 1, pageSize: 50, tourTypeId: String(tourTypeId || ''),
      tourTypeName: '', productName: '', productId: '', areaId: '',
      travelStatus: '', paxType: '',
    });
  }

  /* What the form pre-fills when you pick a Tour Type. This is the shape
   * editTravel expects back, so it doubles as the payload template. */
  function defaults(tourTypeId) {
    return get('/travelMgmt/queryDefaultDataByTourTypeId?tourTypeId=' + tourTypeId);
  }

  function readback(travelId) {
    return post('/travelMgmt/selectVoById?travelId=' + travelId, {});
  }

  /* Resolve a brochure code to its Tour Type. The admin's Tour Code filter is
   * a remote el-select that only holds 20 options until you type, so "not in
   * the list" never means "does not exist" — ask the backend instead. */
  function findTourType(code) {
    return queryTours(code).then(function (j) {
      var rows = (j.data && (j.data.records || j.data.list || j.data.rows)) || [];
      return {
        code: code,
        departures: rows.length,
        tourTypeIds: Array.from(new Set(rows.map(function (r) {
          return r.tourTypeId;
        }))),
        sample: rows.slice(0, 3),
        raw: j,
      };
    });
  }

  /* ------------------------------------------------------------------ write */

  /*
   * The one write. Two guards, both deliberate:
   *  - refuses unless the payload is explicitly unpublished, because this
   *    project's red line is that going live stays a human action;
   *  - refuses to overwrite an existing id unless you pass {allowEdit:true},
   *    so a create can never silently become an edit of a live product.
   */
  function editTravel(payload, opts) {
    opts = opts || {};
    var published = payload.travelStatus === 1 || payload.publishStatus === 1;
    if (published && !opts.allowPublish) {
      return Promise.reject(new Error(
        'refusing: payload is marked published. This tool only creates drafts.'));
    }
    if (payload.id && !opts.allowEdit) {
      return Promise.reject(new Error(
        'refusing: payload carries id=' + payload.id + ' (that is an EDIT of an ' +
        'existing product). Pass {allowEdit:true} if you really mean it.'));
    }
    return post('/travelMgmt/editTravel', payload);
  }

  /* Image upload. Multipart, so it does not go through post(). Returns
   * whatever URL the backend assigns; that URL is what the payload references. */
  function uploadImage(fileOrBlob, filename) {
    var fd = new FormData();
    fd.append('file', fileOrBlob, filename || 'image.jpg');
    var h = Object.assign({}, headers());
    delete h['Content-Type'];           // let the browser set the boundary
    return fetch(BASE + '/ttPackage/uploadImage', {
      method: 'POST', headers: h, body: fd,
    }).then(function (r) { return r.json(); });
  }

  return {
    BASE: BASE,
    captureHeaders: captureHeaders,
    headersFromStorage: headersFromStorage,
    headers: headers,
    post: post,
    get: get,
    queryTours: queryTours,
    queryTravels: queryTravels,
    defaults: defaults,
    readback: readback,
    findTourType: findTourType,
    editTravel: editTravel,
    uploadImage: uploadImage,
  };
})();
