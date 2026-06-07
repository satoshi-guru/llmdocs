"""
compact.py — deterministic, no-LLM Markdown compaction for llmdocs.

Two staged levels (each builds on the previous):
  min   — minified but still-valid Markdown. Collapses blank-line runs, trims
          trailing whitespace, drops HTML comments. Headings, tables, emphasis,
          and code are preserved, so output is still valid Markdown. Safe default
          (this is what the fetch pipeline applies automatically).
  dense — aggressive "machine language". On top of `min`: strips emphasis markers,
          rewrites headings as [depth|Title], rewrites pipe tables as CSV rows,
          removes blank lines. Not valid Markdown — a custom format that expand()
          best-effort round-trips back to readable Markdown.

CRITICAL: every transform skips fenced code blocks (``` / ~~~). Code samples pass
through verbatim. This is the most common silent bug in ad-hoc Markdown compressors.

Relationship to the LLM tier: this is *mechanical* compression (complete, ~30-55%);
`COMPACT.md` (from /doc-indexer) is *semantic* LLM distillation (~99%, lossy). They
coexist — mechanical runs first/early in the core (no API key), semantic on top.
"""

import re

# A fenced code block: opening fence (>=3 backticks or tildes, optional info string)
# through the matching closing fence of the same character, OR running to EOF when
# the fence is never closed (unclosed-at-EOF guard — prevents densify from treating
# the code lines inside an unclosed fence as prose).
_FENCE_RE = re.compile(
    r"^[ \t]*(`{3,}|~{3,})[^\n]*\n"          # opening fence line
    r"(?:.*?^[ \t]*\1[ \t]*$\n?"             # ...through the matching closing fence
    r"|.*\Z)",                               # ...OR to EOF if never closed
    re.DOTALL | re.MULTILINE,
)


def _split_on_fences(text):
    """Yield (is_code, chunk) tuples, preserving fenced blocks verbatim."""
    pos = 0
    for m in _FENCE_RE.finditer(text):
        if m.start() > pos:
            yield (False, text[pos:m.start()])
        yield (True, m.group(0))
        pos = m.end()
    if pos < len(text):
        yield (False, text[pos:])


def _map_prose(text, fn):
    """Apply fn to non-code chunks only; leave fenced code untouched."""
    return "".join(
        chunk if is_code else fn(chunk)
        for is_code, chunk in _split_on_fences(text)
    )


# --- level `min` -----------------------------------------------------------

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_TRAILING_WS = re.compile(r"[ \t]+$", re.MULTILINE)
_BLANK_RUN = re.compile(r"\n{3,}")


def minify(md_text):
    """Level `min`: still-valid Markdown, smaller. Code fences untouched."""
    def prose(t):
        t = _HTML_COMMENT.sub("", t)
        t = _TRAILING_WS.sub("", t)
        t = _BLANK_RUN.sub("\n\n", t)
        return t

    return _map_prose(md_text, prose).strip() + "\n"


# --- level `dense` ---------------------------------------------------------

_BOLD = re.compile(r"(?<!\w)(\*\*|__)(.+?)\1(?!\w)")
_ITALIC = re.compile(r"(?<!\w)(\*|_)(.+?)\1(?!\w)")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$", re.MULTILINE)
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)+\|?\s*$")


_INLINE_CODE = re.compile(r"`[^`]*`")


def _strip_emphasis(line: str) -> str:
    """Remove bold/italic markers from a single PROSE line, but never inside an
    inline `code` span and never on an indented code block (>=4 leading spaces or a
    tab). Without this, dense ate underscores in code identifiers
    (`__name__` -> name, a__b__c -> abc) — code must survive verbatim."""
    if line[:1] == "\t" or re.match(r" {4,}\S", line):
        return line  # indented code block — leave verbatim
    parts = _INLINE_CODE.split(line)        # even idx = prose, odd = `code`
    codes = _INLINE_CODE.findall(line)
    parts = [_ITALIC.sub(r"\2", _BOLD.sub(r"\2", p)) for p in parts]
    out = parts[0]
    for c, p in zip(codes, parts[1:]):
        out += c + p
    return out


def _heading_to_tag(m):
    return f"[{len(m.group(1))}|{m.group(2).strip()}]"


def _row_to_csv(line):
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return ",".join(cells)


def densify(md_text):
    """Level `dense`: custom machine language. Code fences untouched."""
    text = minify(md_text)

    def prose(t):
        # Preserve whether the chunk ends with a newline — needed to keep the
        # separator between a heading tag and the following code fence opening,
        # which would otherwise be joined onto the same line.
        ends_newline = t.endswith("\n")
        t = "\n".join(_strip_emphasis(ln) for ln in t.split("\n"))
        t = _HEADING.sub(_heading_to_tag, t)
        out = []
        for line in t.split("\n"):
            if _TABLE_SEP.match(line):
                continue
            s = line.strip()
            if s.startswith("|") and s.endswith("|"):
                out.append(_row_to_csv(line))
            else:
                out.append(line)
        t = "\n".join(out)
        t = re.sub(r"\n{2,}", "\n", t)
        # Restore the trailing newline consumed by the heading regex's \s* — without
        # this, a prose chunk ending in "heading\n\n" would become "tag" (no \n),
        # and the adjacent code chunk's opening fence would be glued to the tag.
        if ends_newline and not t.endswith("\n"):
            t += "\n"
        return t

    return _map_prose(text, prose).strip() + "\n"


# --- best-effort round-trip: `dense` -> Markdown ---------------------------

_TAG = re.compile(r"^\[(\d)\|(.*)\]$")


_FENCE_OPEN = re.compile(r"^[ \t]*(`{3,}|~{3,})")


def expand(dense_text):
    """Best-effort round-trip of `dense` back to readable Markdown.

    NOTE: lossy by design — emphasis is gone, and a code line containing commas
    cannot be distinguished from a CSV row. `min` is the lossless-ish default;
    use `dense`+`expand` only when you accept this.

    Code fences in the dense input are passed through verbatim (their contents
    are never mis-parsed as CSV rows or headings).
    """
    out = []
    in_table = False
    in_fence = False
    fence_char: str | None = None
    for line in dense_text.split("\n"):
        # Track fence state so code content is never CSV-expanded.
        fm = _FENCE_OPEN.match(line)
        if fm:
            fc = fm.group(1)[0]
            if not in_fence:
                in_fence = True
                fence_char = fc
                in_table = False
                out.append(line)
                continue
            elif fc == fence_char:
                in_fence = False
                fence_char = None
                out.append(line)
                continue
        if in_fence:
            out.append(line)
            continue

        s = line.strip()
        m = _TAG.match(s)
        if m:
            in_table = False
            out += ["", "#" * int(m.group(1)) + " " + m.group(2), ""]
            continue
        if "," in s and not s.startswith("#") and not s.startswith("["):
            cells = [c.strip() for c in s.split(",")]
            out.append("| " + " | ".join(cells) + " |")
            if not in_table:
                out.append("| " + " | ".join(["---"] * len(cells)) + " |")
                in_table = True
            continue
        in_table = False
        out.append(line)
    return "\n".join(out).strip() + "\n"
