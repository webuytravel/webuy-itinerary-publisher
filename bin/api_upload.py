#!/usr/bin/env python3
"""Upload one product to Skybear through the backend API.

The alternative is `lib/form_filler.js`, which types into the admin's Vue form.
That path works but depends on `lib/selectors.yaml` still matching a bundle
that gets rebuilt without notice; the 2026-09 Skybear redeploy is what prompted
this one. The backend contract has not moved since the 408 batch —
`VUE_APP_BASE_API` is still https://apimini.webuy.ren/wb_tourt and every route
below still answers.

Two steps, in this order, because the payload has to carry the image URLs:

  1. POST every crop in `work/<CODE>/out/` (+ `out_mobile/`) to
     `ttPackage/uploadImage`, which returns an OSS URL per file.
  2. POST the assembled record to `travelMgmt/editTravel`.

Auth is **borrowed, never minted**. `--headers` points at a JSON file holding
the headers a logged-in admin tab is already sending (capture them with
`lib/skybear_api.js`). This tool has no password, no API key and no login call;
when the token expires the fix is to re-capture from a live tab. Keep that file
outside the repo — it is a live session bearer token.

    python3 bin/api_upload.py ACKMG12T --headers /tmp/sb_headers.json --dry-run
    python3 bin/api_upload.py ACKMG12T --headers /tmp/sb_headers.json

`--dry-run` does everything except the two mutating calls, so it is the cheap
way to confirm the slot mapping before anything reaches production.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BASE = "https://apimini.webuy.ren/wb_tourt"
WORK = Path("work")


def _req(url: str, headers: dict, data: bytes | None = None,
         content_type: str | None = None) -> dict:
    h = {k: str(v) for k, v in headers.items()}
    if content_type:
        h["Content-Type"] = content_type
    req = urllib.request.Request(url, data=data, headers=h,
                                 method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        # A bare "HTTP Error 500" hides the one useful thing the server said.
        body = e.read().decode("utf-8", "replace")[:600]
        raise SystemExit(f"{url} -> HTTP {e.code}\n{body}") from None


def post_json(path: str, headers: dict, body: dict) -> dict:
    out = _req(BASE + path, headers, json.dumps(body).encode(),
               "application/json;charset=utf-8")
    if out.get("success") is False:
        raise SystemExit(f"{path} -> {out.get('code')} {out.get('msg')}")
    return out


def upload_image(path: Path, headers: dict) -> str:
    """POST one file as multipart/form-data; return the URL Skybear assigns.

    The form field is **`photoInput`**, and the URL comes back at
    `data.documentUrl`. Both were read off the admin bundle's own call site —
    guessing `file` (the obvious name, and what six other uploaders in the same
    bundle use) gets a bare HTTP 500 with no message saying what is wrong.
    """
    boundary = "----webuy" + uuid.uuid4().hex
    ctype = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="photoInput"; '
        f'filename="{path.name}"\r\n'.encode(),
        f"Content-Type: {ctype}\r\n\r\n".encode(),
        path.read_bytes(),
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    out = _req(BASE + "/ttPackage/uploadImage", headers, body,
               f"multipart/form-data; boundary={boundary}")
    if out.get("success") is False:
        raise SystemExit(f"uploadImage {path.name} -> {out.get('code')} {out.get('msg')}")
    data = out.get("data") or {}
    url = data if isinstance(data, str) else (
        data.get("documentUrl") or data.get("url") or data.get("imageUrl"))
    if not url:
        raise SystemExit(f"uploadImage {path.name}: no URL in response {out}")
    return url


def image_entry(url: str, path: Path, sort_num: int) -> dict:
    """The shape `desktopImageList` / `mobileImageList` / `imageList` use.

    Read off product 424 via `travelMgmt/selectVoById`: `imageName` is a slug
    the admin generates client-side and the backend does not interpret, so the
    crop's own stem is a more useful value than a random one — it points back
    at the file in `work/<CODE>/out/` that produced it.
    """
    return {"imageName": path.stem, "imageUrl": url, "sortNum": sort_num}


def collect(code: str, plan: dict, headers: dict, dry: bool) -> dict:
    """Upload every crop the plan materialised, keyed by slot."""
    out: dict = {"carousel": {}, "mobile": {}, "section": {}, "trip": {},
                 "thumbnail": None}

    # Uploading is idempotent from Skybear's side — the same file posted twice
    # gets two OSS objects — so a failed `editTravel` must not mean 51 fresh
    # copies on the next attempt. The cache is keyed on the crop's path plus
    # its bytes, so re-running after a recompose re-uploads only what changed.
    cache_path = WORK / code / "uploaded.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    fresh = 0

    def send(p: Path) -> str:
        nonlocal fresh
        if dry:
            return f"(dry-run) {p.name}"
        key = f"{p}:{p.stat().st_size}"
        if key in cache:
            return cache[key]
        url = upload_image(p, headers)
        cache[key] = url
        fresh += 1
        print(f"    {p.name:<28} -> {url}", file=sys.stderr)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n")
        return url

    placements = [p for p in plan["placements"] if p.get("out_path")]

    for p in sorted(placements, key=lambda p: (p["slot"], p["position"],
                                               p.get("trip_index") or 0)):
        path = Path(p["out_path"])
        if not path.exists():
            raise SystemExit(
                f"{code}: {path} is missing — run bin/compose.py then "
                f"bin/resharpen.py / bin/mobile_crops.py first.")
        slot = p["slot"]
        if slot == "thumbnail":
            out["thumbnail"] = send(path)
        elif slot == "carousel":
            out["carousel"][p["position"]] = (send(path), path)
        elif slot == "section":
            out["section"].setdefault(p["position"], []).append((send(path), path))
        elif slot == "trip":
            key = (p["position"], p.get("trip_index") or 0)
            out["trip"].setdefault(key, []).append((send(path), path))

    # The portrait halves are produced by bin/mobile_crops.py and are not
    # placements — Mobile Display Image is a required slot, so a missing file
    # here is a hard stop rather than a thinner carousel.
    mob_dir = WORK / code / "out_mobile"
    for pos in sorted(out["carousel"]):
        m = mob_dir / f"carousel_{pos:02d}_mobile.jpg"
        if not m.exists():
            raise SystemExit(
                f"{code}: {m} is missing — Mobile Display Image is required; "
                f"run `python3 bin/mobile_crops.py {code} --assets-root .`")
        out["mobile"][pos] = (send(m), m)
    if not dry:
        print(f"    ({fresh} newly uploaded, "
              f"{len(cache) - fresh} reused from {cache_path})", file=sys.stderr)
    return out


def attach(payload: dict, images: dict) -> dict:
    """Put the uploaded URLs into the payload's image fields."""
    payload = json.loads(json.dumps(payload))

    payload["thumbneilList"] = [images["thumbnail"]] if images["thumbnail"] else []
    payload["desktopImageList"] = [
        image_entry(url, path, i)
        for i, (url, path) in enumerate(
            images["carousel"][k] for k in sorted(images["carousel"]))
    ]
    payload["mobileImageList"] = [
        image_entry(url, path, i)
        for i, (url, path) in enumerate(
            images["mobile"][k] for k in sorted(images["mobile"]))
    ]

    for section in payload["sectionList"]:
        day = section["sortNum"] + 1
        section["imageList"] = [
            image_entry(url, path, i)
            for i, (url, path) in enumerate(images["section"].get(day, []))
        ]
        for item in section["itemList"]:
            got = images["trip"].get((day, item["sortNum"]), [])
            item["imageList"] = [
                image_entry(url, path, i) for i, (url, path) in enumerate(got)
            ]
    return payload


def main() -> None:
    global WORK
    ap = argparse.ArgumentParser()
    ap.add_argument("code")
    ap.add_argument("--headers", type=Path, required=True,
                    help="JSON file of headers borrowed from a logged-in tab")
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    WORK = args.work
    base = WORK / args.code

    headers = json.loads(args.headers.read_text())
    payload = json.loads((base / "api_payload.json").read_text())
    plan = json.loads((base / "plan.json").read_text())

    # Guard rails. Publishing stays a human action, and a create must never
    # become an edit of something already live.
    if payload.get("travelStatus") != 0:
        raise SystemExit(
            f"refusing: travelStatus={payload.get('travelStatus')}; this tool "
            f"only creates drafts (0 = UnPublished).")
    if payload.get("id"):
        raise SystemExit(
            f"refusing: payload carries id={payload['id']}, which would edit an "
            f"existing product rather than create one.")

    print(f"== {args.code}  ({'DRY RUN' if args.dry_run else 'LIVE'})",
          file=sys.stderr)
    print("  uploading crops", file=sys.stderr)
    images = collect(args.code, plan, headers, args.dry_run)
    final = attach(payload, images)

    n_trip = sum(len(i["imageList"]) for s in final["sectionList"]
                 for i in s["itemList"])
    n_sec = sum(len(s["imageList"]) for s in final["sectionList"])
    print(f"  thumbnail={len(final['thumbneilList'])} "
          f"desktop={len(final['desktopImageList'])} "
          f"mobile={len(final['mobileImageList'])} "
          f"section={n_sec} trip={n_trip}", file=sys.stderr)

    (base / "api_payload_final.json").write_text(
        json.dumps(final, ensure_ascii=False, indent=2) + "\n")

    if args.dry_run:
        print("  dry run — nothing written to production", file=sys.stderr)
        return

    print("  POST travelMgmt/editTravel", file=sys.stderr)
    res = post_json("/travelMgmt/editTravel", headers, final)
    print(f"  -> {json.dumps(res, ensure_ascii=False)[:400]}", file=sys.stderr)

    listing = post_json("/travelMgmt/queryListPage", headers, {
        "pageNo": 1, "pageSize": 50, "tourTypeId": str(final["tourTypeId"]),
        "tourTypeName": "", "productName": "", "productId": "", "areaId": "",
        "travelStatus": "", "paxType": "",
    })
    # The paged envelope calls it `list`. It is not `records` — that guess cost
    # a silent empty readback on the first successful write, which is the one
    # moment you actually want the confirmation to print.
    data = listing.get("data") or {}
    rows = data.get("list") or data.get("records") or []
    if not rows:
        print(f"  READBACK: queryListPage returned no rows for tourTypeId "
              f"{final['tourTypeId']} — check by hand before trusting this run.",
              file=sys.stderr)
    for r in rows:
        print(f"  READBACK id={r.get('id')} status={r.get('travelStatus')} "
              f"(0=UnPublished) name={r.get('productName')}", file=sys.stderr)


if __name__ == "__main__":
    main()
