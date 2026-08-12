"""Source #3 and #4: the photo tools on the live `webuy-itinerary-mcp` service.

`webuy-itinerary-creation` already solved "find a picture of this landmark",
and it is deployed with the Shutterstock/Unsplash/Pexels/Gemini keys held
**server side** — so this project reaches it over HTTP rather than vendoring
the search code and asking for its own keys. `/health` reports which keys are
configured without ever revealing them.

Two tools matter here:

* `fetch_photo` — stock search across Unsplash + Pexels, returning candidate
  URLs plus 440px thumbnails. Measurably better than the Wikimedia-Commons-only
  fallback this project had before ("Keketuohai" used to come back as mineral
  specimens; it now returns actual Xinjiang landscape) but **not** reliable on
  its own: one launch probe returned a photo of Ashgabat, Turkmenistan for a
  Urumqi query.
* `generate_image` — Gemini text-to-image, for the long tail stock has never
  photographed.

Three operational facts, each learned the hard way:

1. **`quick=False` is unusable in a loop.** It adds Gemini vision verification
   and aesthetic ranking, and measured >6 minutes for a *single* subject. The
   service's own tool description says never to use it for a whole deck. So we
   always call `quick=True` and do the judging ourselves — the caller is
   multimodal and looks at the thumbnails.
2. **Asset URLs are ephemeral.** The service hands back `/asset/<id>.png` paths
   that a Render restart wipes. `download()` immediately, never store the URL.
3. **The endpoint is currently unauthenticated.** `WEBUY_MCP_TOKEN` is not set
   on the deployment, so the handshake succeeds with no Authorization header.
   `MCP_TOKEN` here is wired up ready for when that is fixed; it is sent only
   when set.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .photo_source import USER_AGENT, download

ENDPOINT = os.environ.get(
    "WEBUY_MCP_URL", "https://webuy-itinerary-mcp.onrender.com/mcp")

# Not set on the deployment today; sent only when present so this keeps
# working unchanged once the service starts requiring it.
MCP_TOKEN = os.environ.get("WEBUY_MCP_TOKEN", "")

PROTOCOL_VERSION = "2024-11-05"


class McpError(RuntimeError):
    """The service refused, or answered something we can't parse.

    Raised rather than returning empty so a sourcing gap is never silently
    mistaken for "no photo exists".
    """


@dataclass
class Candidate:
    """One stock result. `title` is the uploader's own caption.

    Treat `title` the way `pdf_images` treats a brochure caption: a prior,
    not a fact. It is a better prior than a brochure caption (the uploader
    photographed the thing) but the search that surfaced it may still have
    gone to the wrong country.
    """

    n: int
    url: str
    source: str
    title: str = ""
    thumb: str = ""

    @property
    def is_ai_generated(self) -> bool:
        return self.source == "generated"


def _rpc(method: str, params: dict | None, session: str | None = None, *,
         notify: bool = False) -> dict:
    """One JSON-RPC call over MCP Streamable HTTP.

    The transport answers either `application/json` or an SSE stream
    depending on the method, so both shapes are unwrapped here.

    `notify=True` sends a notification instead of a request. The difference
    is only the absence of `id`, but it is load-bearing: carrying an `id` on
    `notifications/initialized` makes the server read it as a request and
    reject the handshake with "Invalid request parameters".
    """
    body = {"jsonrpc": "2.0", "method": method}
    if not notify:
        body["id"] = str(uuid.uuid4())
    if params is not None:
        body["params"] = params
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": USER_AGENT,
    }
    if MCP_TOKEN:
        headers["Authorization"] = f"Bearer {MCP_TOKEN}"
    if session:
        headers["Mcp-Session-Id"] = session

    request = Request(ENDPOINT, data=json.dumps(body).encode(), headers=headers)
    try:
        with urlopen(request, timeout=180) as response:
            raw = response.read().decode("utf-8", "replace")
            sid = response.headers.get("Mcp-Session-Id") or session
    except (HTTPError, URLError, TimeoutError) as exc:
        raise McpError(f"{method}: {exc}") from exc

    # A notification is answered with 202 and an empty body — nothing to parse.
    if notify:
        return {"result": {}, "session": sid}

    payload = _unwrap(raw)
    if "error" in payload:
        raise McpError(f"{method}: {payload['error']}")
    return {"result": payload.get("result", {}), "session": sid}


def _unwrap(raw: str) -> dict:
    """Parse a plain JSON body or pull the JSON out of an SSE frame."""
    text = raw.strip()
    if text.startswith("{"):
        return json.loads(text)
    for line in text.splitlines():
        if line.startswith("data:"):
            chunk = line[5:].strip()
            if chunk and chunk != "[DONE]":
                return json.loads(chunk)
    raise McpError(f"unparseable response: {text[:200]!r}")


def _session() -> str:
    """Handshake, and return the session id the service wants echoed back."""
    opened = _rpc("initialize", {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "webuy-itinerary-publisher", "version": "0.1.0"},
    })
    sid = opened["session"]
    _rpc("notifications/initialized", {}, sid, notify=True)
    return sid


def _call_tool(name: str, arguments: dict, session: str | None = None) -> list:
    """Invoke a tool, returning its raw `content` blocks."""
    sid = session or _session()
    answer = _rpc("tools/call", {"name": name, "arguments": arguments}, sid)
    return answer["result"].get("content", [])


def _first_json_block(content: list) -> object:
    """Tool payloads arrive as a text block of JSON, then image blocks."""
    for block in content:
        if block.get("type") == "text":
            text = (block.get("text") or "").strip()
            if text.startswith(("{", "[")):
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    continue
    raise McpError("no JSON payload in tool response")


def search(subject: str, region: str = "", count: int = 4,
           session: str | None = None) -> list[Candidate]:
    """Stock candidates for `subject`, newest-first as the service ranks them.

    Always `quick=True` — see the module docstring for why the verifying
    mode is off the table. Nothing here judges the pictures; the caller is
    expected to look at `thumb` before choosing.
    """
    content = _call_tool("fetch_photo", {
        "subject": subject,
        "region": region,
        "count": count,
        "quick": True,
    }, session)

    payload = _first_json_block(content)
    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    if not isinstance(payload, dict) or not payload.get("ok", True):
        raise McpError(f"fetch_photo({subject!r}) refused: {payload}")

    # Image blocks follow the JSON, in candidate order.
    thumbs = [b for b in content if b.get("type") == "image"]
    out = []
    for i, row in enumerate(payload.get("candidates", [])):
        out.append(Candidate(
            n=row.get("n", i + 1),
            url=row.get("url", ""),
            source=row.get("source", ""),
            title=row.get("title", ""),
            thumb=thumbs[i].get("data", "") if i < len(thumbs) else "",
        ))
    return out


def generate(prompt: str, aspect_ratio: str = "4:3",
             session: str | None = None) -> Candidate:
    """Make a picture that stock does not have.

    The escape hatch for subjects no photo library covers. **Whether an
    invented image belongs on a page selling a real trip to a real place is
    an editorial call, not a technical one** — this function is deliberately
    separate from `search()` so that choice is always explicit at the call
    site, and `Candidate.is_ai_generated` carries it downstream to the
    review page.
    """
    content = _call_tool("generate_image", {
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "thumbnail": True,
    }, session)
    payload = _first_json_block(content)
    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    url = payload.get("image_url") or payload.get("url", "")
    if not url:
        raise McpError(f"generate_image returned no url: {payload}")
    return Candidate(n=1, url=url, source="generated", title=prompt[:80])


def fetch(candidate: Candidate, dest: str | Path) -> Path:
    """Pull the full-size file down. Do this immediately — see docstring #2."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    download(candidate.url, dest)
    return dest


def health() -> dict:
    """Which keys the service has, as booleans. Never returns key material."""
    url = re.sub(r"/mcp/?$", "/health", ENDPOINT)
    try:
        with urlopen(Request(url, headers={"User-Agent": USER_AGENT}),
                     timeout=30) as response:
            return json.loads(response.read())
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise McpError(f"health: {exc}") from exc
