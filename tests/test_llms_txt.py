"""Tests for the llms-txt acquisition strategy (crawler.phase1_llms_txt helpers).

Network-free: _fetch_raw_md is exercised with a stub session that records the
requested URL and returns canned responses.
"""
import threading
from pathlib import Path

import crawler as L


class _Resp:
    def __init__(self, status=200, ctype="text/markdown",
                 text="# Title\n\nThis documentation page body has enough text to pass the floor."):
        self.status_code = status
        self.headers = {"Content-Type": ctype}
        self.text = text


class _Session:
    """Records the last URL requested so tests can assert query-param handling."""
    def __init__(self, resp):
        self._resp = resp
        self.last_url = None

    def get(self, url, **kwargs):
        self.last_url = url
        return self._resp


def _call(resp, url="https://docs.x.com/a/b.md", **kw):
    sess = _Session(resp)
    page, err = L._fetch_raw_md(
        url, sess, L._FetchThrottle(0), threading.Lock(),
        Path("/tmp/out"), title_hint="Hint", **kw)
    return sess, page, err


# --- happy path -------------------------------------------------------------

def test_fetch_raw_md_returns_page_for_markdown():
    sess, page, err = _call(_Resp(text="# API Documentation\n\nThis endpoint returns market data as JSON objects."))
    assert err is None
    assert page["markdown"].startswith("# API Documentation")
    assert page["url"] == "https://docs.x.com/a/b.md"
    # title comes from the first heading, not the link hint
    assert page["title"] == "API Documentation"


def test_fetch_raw_md_appends_agent_instructions_param():
    sess, page, err = _call(_Resp())
    assert "displayAgentInstructions=false" in sess.last_url


def test_fetch_raw_md_uses_amp_when_url_already_has_query():
    sess, page, err = _call(_Resp(), url="https://docs.x.com/a/b.md?v=2")
    assert "?v=2&displayAgentInstructions=false" in sess.last_url


def test_fetch_raw_md_human_url_is_src_when_probing_twin():
    # When probing the .md twin of an HTML page, page url must be the human page.
    sess, page, err = _call(_Resp(), url="https://docs.x.com/a/b.md",
                            src_url="https://docs.x.com/a/b")
    assert page["url"] == "https://docs.x.com/a/b"


# --- rejection paths --------------------------------------------------------

def test_fetch_raw_md_rejects_soft_404_html():
    # 200 OK but HTML body (a soft-404) must NOT be saved as markdown.
    sess, page, err = _call(_Resp(ctype="text/html", text="<html>not found</html>"))
    assert page is None
    assert err and "not markdown" in err["error"]


def test_fetch_raw_md_rejects_html_body_even_with_md_ctype():
    sess, page, err = _call(_Resp(ctype="text/markdown", text="<!DOCTYPE html><html>"))
    assert page is None and err is not None


def test_fetch_raw_md_rejects_non_200():
    sess, page, err = _call(_Resp(status=404, text="nope"))
    assert page is None and err["status"] == 404


def test_fetch_raw_md_rejects_empty():
    sess, page, err = _call(_Resp(text="   \n  "))
    assert page is None and err is not None


# --- _write_page: no duplicate H1 (the bug the smoke-test caught) ------------

def test_write_page_no_duplicate_h1_when_body_has_heading(tmp_path):
    out = tmp_path / "o"; out.mkdir()
    fp = out / "p.md"
    page = {"url": "https://x.io/p", "title": "Login",
            "markdown": "# Login\n\nConnect your wallet.", "filepath": fp, "depth": 0}
    L._write_page(page, out, minify=None)
    body = fp.read_text().split("---\n\n", 1)[1]   # drop frontmatter
    assert body.count("# Login") == 1, body


def test_write_page_still_adds_heading_when_body_has_none(tmp_path):
    out = tmp_path / "o"; out.mkdir()
    fp = out / "p.md"
    page = {"url": "https://x.io/p", "title": "Login",
            "markdown": "Connect your wallet.", "filepath": fp, "depth": 0}
    L._write_page(page, out, minify=None)
    assert "# Login\n" in fp.read_text()
