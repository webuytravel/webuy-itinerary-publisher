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
   * Borrow the headers the app itself sends.
   *
   * The only reliable way to see them is to record what actually goes on the
   * wire: patch the two transports, then make **the app** issue a request and
   * keep whatever it set. Two things that look like they should work and do
   * not, both tried on 2026-09-11:
   *
   *   - calling `fetch(BASE + '/...')` ourselves. That is a bare request; the
   *     app's axios interceptor is what attaches the headers, and we are not
   *     going through it. Nothing is recorded.
   *   - opening an XMLHttpRequest by hand. Same reason, plus it never sends.
   *
   * What does work is making the SPA mount the **dashboard**, which calls half
   * a dozen of its own endpoints on mount. Two details that both cost a
   * 20-second timeout before they were understood:
   *
   *   - the package list route is not a usable trigger. It mounts without
   *     querying anything — the runbook's "click Search" exists precisely
   *     because that page waits for you.
   *   - `location.hash = <the hash it already has>` is a no-op, so a tab
   *     already sitting on the dashboard never re-mounts. We must navigate
   *     *away* first and then back.
   *
   * The operator's original route is restored once the headers are in hand.
   *
   * This is deliberately not a reimplementation of the app's header logic —
   * app_version, the token key and the device-id format have all changed at
   * least once, and a copy would drift. A recording cannot.
   */
  function captureHeaders(timeoutMs) {
    timeoutMs = timeoutMs || 20000;
    var want = ['x-wb-tourt-token', 'authorization-userid',
                'x-web-deviceid', 'app_version'];
    var seen = {};

    var origXhr = XMLHttpRequest.prototype.setRequestHeader;
    XMLHttpRequest.prototype.setRequestHeader = function (k, v) {
      if (want.indexOf(String(k).toLowerCase()) !== -1) seen[k] = v;
      return origXhr.apply(this, arguments);
    };

    // axios may use either transport depending on build; record both.
    var origFetch = window.fetch;
    window.fetch = function (input, init) {
      try {
        var h = (init && init.headers) || {};
        var rec = {};
        if (h && typeof h.forEach === 'function') h.forEach(function (v, k) { rec[k] = v; });
        else Object.assign(rec, h);
        Object.keys(rec).forEach(function (k) {
          if (want.indexOf(k.toLowerCase()) !== -1) seen[k] = rec[k];
        });
      } catch (e) { /* a header bag we cannot read is not fatal */ }
      return origFetch.apply(this, arguments);
    };

    function restore() {
      XMLHttpRequest.prototype.setRequestHeader = origXhr;
      window.fetch = origFetch;
    }

    var DASH = '#/dashboard/index';
    var back = location.hash;
    if (back.indexOf('dashboard') === -1) {
      location.hash = DASH;                       // straight in; it will mount
    } else {
      location.hash = '#/packageDisplayMgmt/packageDisplayList';
      setTimeout(function () { location.hash = DASH; }, 900);  // away, then back
    }

    var t0 = Date.now();
    return new Promise(function (resolve, reject) {
      (function poll() {
        if (seen['x-wb-tourt-token']) {
          restore();
          if (location.hash !== back) location.hash = back;
          HDRS = Object.assign(
            { 'Content-Type': 'application/json;charset=utf-8' }, seen);
          return resolve(Object.keys(seen));
        }
        if (Date.now() - t0 > timeoutMs) {
          restore();
          return reject(new Error(
            'no auth header seen in ' + timeoutMs + 'ms. Either this tab is ' +
            'not logged in (you should be on a dashboard, not SIGN IN), or ' +
            'the session expired — log in again and retry.'));
        }
        setTimeout(poll, 250);
      })();
    });
  }

  /*
   * What `bin/api_upload.py --headers` wants. Copy the printed JSON into a
   * file **outside the repository** — it is a live session bearer token, and
   * it stops working when the session ends, which is the point.
   */
  function headersJSON() {
    var h = Object.assign({}, headers());
    delete h['Content-Type'];   // the Python side sets its own per request
    return JSON.stringify(h, null, 2);
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
    headersJSON: headersJSON,
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
