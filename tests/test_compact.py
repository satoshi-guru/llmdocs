import compact  # noqa: F401


def test_module_importable():
    assert hasattr(compact, "minify")
    assert hasattr(compact, "densify")
    assert hasattr(compact, "expand")


# --- fence-safe splitting (the critical correctness primitive) ---

def test_split_keeps_code_fence_verbatim():
    text = "Use **bold**.\n\n```py\nx = a ** b  # ** stays\n```\n\nDone.\n"
    chunks = list(compact._split_on_fences(text))
    code = [c for is_code, c in chunks if is_code]
    prose = [c for is_code, c in chunks if not is_code]
    assert len(code) == 1
    assert "x = a ** b  # ** stays" in code[0]
    assert any("Use **bold**." in p for p in prose)


def test_split_handles_tilde_fences_and_lang():
    text = "~~~bash\necho hi\n~~~\n"
    chunks = list(compact._split_on_fences(text))
    assert len(chunks) == 1 and chunks[0][0] is True


def test_map_prose_skips_code():
    text = "a\n```\nKEEP a\n```\n"
    out = compact._map_prose(text, lambda t: t.replace("a", "Z"))
    assert "KEEP a" in out      # code untouched
    assert out.startswith("Z")  # prose changed


# --- minify (level min) ---

def test_minify_collapses_blank_runs_and_trailing_ws():
    text = "# Title   \n\n\n\nbody line  \n\n\n"
    out = compact.minify(text)
    assert "\n\n\n" not in out          # no 3+ newline runs
    assert "Title\n" in out             # trailing spaces trimmed
    assert out.endswith("\n")           # single trailing newline


def test_minify_drops_html_comments():
    out = compact.minify("a\n<!-- nav cruft -->\nb\n")
    assert "nav cruft" not in out


def test_minify_preserves_code_and_headings_and_tables():
    text = "## Keep\n\n```py\n\n\nx = 1\n\n\n```\n\n| a | b |\n| - | - |\n"
    out = compact.minify(text)
    assert "## Keep" in out                         # heading level preserved
    assert "x = 1" in out and "\n\n\nx = 1" in out   # blank lines INSIDE code kept
    assert "| a | b |" in out                       # table preserved


def test_minify_is_idempotent():
    text = "# T\n\n\nbody\n\n"
    assert compact.minify(compact.minify(text)) == compact.minify(text)


# --- densify (level dense) ---

def test_densify_headings_become_depth_tags():
    assert "[2|Auth]" in compact.densify("## Auth\n")
    assert "[4|Deep]" in compact.densify("#### Deep\n")


def test_densify_tables_become_csv():
    out = compact.densify("| k | v |\n| - | - |\n| a | 1 |\n")
    assert "k,v" in out
    assert "a,1" in out
    assert "---" not in out          # separator row dropped


def test_densify_strips_emphasis_in_prose():
    out = compact.densify("Use **Bearer** and _scopes_.\n")
    assert "Bearer" in out and "**" not in out and "_scopes_" not in out


def test_densify_preserves_code_fences_verbatim():
    text = "## H\n\n```py\na, b = 1, 2\nx = a ** b\n```\n"
    out = compact.densify(text)
    assert "a, b = 1, 2" in out       # NOT turned into CSV
    assert "x = a ** b" in out        # ** not stripped inside code


# --- expand (best-effort dense -> markdown) ---

def test_expand_restores_headings():
    assert "## Auth" in compact.expand("[2|Auth]\n")


def test_expand_restores_table_from_csv():
    out = compact.expand("k,v\na,1\n")
    assert "| k | v |" in out
    assert "| --- | --- |" in out
    assert "| a | 1 |" in out


def test_dense_then_expand_recovers_heading_and_table_text():
    src = "## Params\n\n| name | type |\n| - | - |\n| id | int |\n"
    recovered = compact.expand(compact.densify(src))
    assert "## Params" in recovered
    assert "| name | type |" in recovered
    assert "| id | int |" in recovered


# --- fidelity-grade compaction tests (First Principle) ----------------------
#
# Composite doc with collapsible blank runs + trailing ws + an HTML comment so
# `min` has real work to do, PLUS a multi-signature code block + table whose
# signal MUST survive.

COMPOSITE = """\
# mylib


<!-- nav cruft to strip -->

## install


Install with pip.



```python
def connect(host: str, port: int = 443, *, tls: bool = True) -> Connection: ...
def send(conn: Connection, payload: bytes, retries: int = 3) -> Response: ...
class Client:
    def request(self, method: str, url: str, timeout: float = 30.0) -> Response: ...
```



| param | type | default |
| --- | --- | --- |
| host | str | required |
| port | int | 443 |
"""

_SIGNATURES = ("def connect(", "def send(", "def request(")
_HEADINGS = ("# mylib", "## install")


def test_min_reduces_size():
    out = compact.minify(COMPOSITE)
    assert len(out) < len(COMPOSITE), "min must shrink a doc with collapsible blanks/comments"


def test_min_preserves_every_function_signature():
    out = compact.minify(COMPOSITE)
    for sig in _SIGNATURES:
        assert sig in out, f"min dropped a signature: {sig}"


def test_min_preserves_section_headings():
    out = compact.minify(COMPOSITE)
    for h in _HEADINGS:
        assert h in out, f"min dropped a heading (overview structure): {h}"


def test_dense_reduces_size_but_keeps_signatures():
    out = compact.densify(COMPOSITE)
    assert len(out) < len(COMPOSITE), "dense must shrink the composite doc"
    for sig in _SIGNATURES:
        assert sig in out, f"dense dropped a signature: {sig}"


def test_dense_preserves_headings_as_reachable_tags():
    # dense rewrites '## install' -> '[2|install]'; the title text must remain reachable.
    out = compact.densify(COMPOSITE)
    assert "[1|mylib]" in out, "dense dropped the top-level heading title"
    assert "[2|install]" in out, "dense dropped the install heading title"
