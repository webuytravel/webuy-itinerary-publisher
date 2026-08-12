import json

import pytest

from lib.mcp_photos import Candidate, McpError, _first_json_block, _unwrap


def test_unwrap_reads_a_plain_json_body():
    assert _unwrap('{"jsonrpc":"2.0","result":{"ok":1}}')["result"] == {"ok": 1}


def test_unwrap_reads_an_sse_frame():
    # The same endpoint answers JSON for some methods and SSE for others,
    # so both shapes have to work or half the calls fail.
    raw = 'event: message\ndata: {"jsonrpc":"2.0","result":{"ok":2}}\n\n'
    assert _unwrap(raw)["result"] == {"ok": 2}


def test_unwrap_ignores_the_sse_terminator():
    raw = 'data: [DONE]\ndata: {"result":{"ok":3}}\n'
    assert _unwrap(raw)["result"] == {"ok": 3}


def test_unwrap_fails_loud_on_junk():
    with pytest.raises(McpError):
        _unwrap("<html>502 Bad Gateway</html>")


def test_first_json_block_skips_prose_blocks():
    # Tool replies lead with a human-readable note before the payload.
    content = [
        {"type": "text", "text": "Look at the thumbnails and pick one."},
        {"type": "text", "text": json.dumps({"ok": True, "candidates": []})},
    ]
    assert _first_json_block(content) == {"ok": True, "candidates": []}


def test_first_json_block_fails_loud_when_there_is_no_payload():
    with pytest.raises(McpError):
        _first_json_block([{"type": "image", "data": "..."}])


def test_generated_candidates_are_flagged():
    # The review page has to be able to say "this picture was invented",
    # so the distinction rides on the candidate itself.
    assert Candidate(1, "u", "generated").is_ai_generated
    assert not Candidate(1, "u", "pexels").is_ai_generated
