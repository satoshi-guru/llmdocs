"""Version canonicalization + skip-pattern behavior.

Regression guard for the matrix-spec bug: a site whose only real docs live under a
numeric version (/v1.18/, reached via a /latest/ alias) must NOT be skipped to a
single page by the generic version-skip, while unversioned-canonical sites
(react-native: /docs/ canonical, /docs/0.77/ = old dup) must still drop old versions.
"""
import llmdocs as L


# --- _detect_concrete_version ------------------------------------------------

def test_concrete_version_from_url():
    assert L._detect_concrete_version("https://spec.matrix.org/v1.18/rooms/") == "v1.18"
    assert L._detect_concrete_version("https://example.com/0.77/api") == "0.77"
    assert L._detect_concrete_version("https://x.io/v0.1.5/guide") == "v0.1.5"


def test_concrete_version_absent():
    assert L._detect_concrete_version("https://reactnative.dev/docs/getting-started") is None
    assert L._detect_concrete_version("https://spec.matrix.org/latest/rooms/") is None


# --- _dominant_linked_version ------------------------------------------------

def test_dominant_linked_version_picks_majority():
    html = "".join(f'<a href="/v1.18/p{i}">x</a>' for i in range(8))
    html += '<a href="/unstable/p">u</a><a href="/about">a</a>'
    assert L._dominant_linked_version(html, "https://spec.matrix.org/latest/") == "v1.18"


def test_dominant_linked_version_no_clear_winner():
    html = ('<a href="/v1.18/a">x</a><a href="/v1.17/b">y</a>'
            '<a href="/v1.16/c">z</a>')  # 1/3 each, none >= 50%
    assert L._dominant_linked_version(html, "https://spec.matrix.org/latest/") is None


def test_dominant_linked_version_none_when_no_versions():
    html = '<a href="/docs/a">x</a><a href="/guide/b">y</a>'
    assert L._dominant_linked_version(html, "https://x.io/latest/") is None


# --- _build_skip_patterns: unversioned canonical (react-native) ---------------

def test_unpinned_skips_old_version_trees():
    pats = L._build_skip_patterns("https://reactnative.dev/docs/getting-started")
    assert L._url_is_skipped("https://reactnative.dev/docs/0.77/intro", pats)
    assert not L._url_is_skipped("https://reactnative.dev/docs/intro", pats)


# --- _build_skip_patterns: pinned canonical version (matrix) ------------------

def test_pinned_version_not_skipped_including_nested():
    pats = L._build_skip_patterns("https://spec.matrix.org/latest/rooms/",
                                  canonical_version="v1.18")
    # canonical tree + legit nested version refs survive
    assert not L._url_is_skipped("https://spec.matrix.org/v1.18/rooms/", pats)
    assert not L._url_is_skipped("https://spec.matrix.org/v1.18/changelog/v1.1/", pats)


def test_locale_skip_unaffected_by_version_pinning():
    pats = L._build_skip_patterns("https://spec.matrix.org/latest/rooms/",
                                  canonical_version="v1.18")
    assert L._url_is_skipped("https://spec.matrix.org/fr/v1.18/rooms/", pats)
    assert not L._url_is_skipped("https://spec.matrix.org/en/v1.18/rooms/", pats)


# --- _path_matches_prefix: directory-index start page ------------------------

def test_prefix_matches_directory_index_without_trailing_slash():
    # start URL "/docs" must be saved even though prefix is normalized to "/docs/"
    assert L._path_matches_prefix("https://www.nativewind.dev/docs", "/docs/")
    assert L._path_matches_prefix("https://www.nativewind.dev/docs/", "/docs/")
    assert L._path_matches_prefix("https://www.nativewind.dev/docs/api", "/docs/")


def test_prefix_does_not_overmatch_sibling():
    assert not L._path_matches_prefix("https://www.nativewind.dev/docsfoo", "/docs/")
    assert not L._path_matches_prefix("https://www.nativewind.dev/about", "/docs/")


def test_empty_prefix_matches_all():
    assert L._path_matches_prefix("https://zod.dev/anything", "")


# --- _derive_scope: directory vs file-leaf crawl scoping ---------------------

def test_derive_scope_directory_url():
    assert L._derive_scope("https://reactnative.dev/docs/getting-started", None, None) == ("/docs/", 4)
    assert L._derive_scope("https://www.nativewind.dev/docs", None, None) == ("/docs/", 4)


def test_derive_scope_file_leaf_scopes_to_parent_and_shallow():
    # man-page leaf -> parent dir silo + depth 1 (page + immediate refs), not a
    # whole-domain crawl that times out
    pfx, depth = L._derive_scope(
        "https://man7.org/linux/man-pages/man8/cryptsetup.8.html", None, None)
    assert pfx == "/linux/man-pages/man8/"
    assert depth == 1


def test_derive_scope_root_file_is_whole_site():
    # a root-level file has no parent dir -> empty prefix (whole site), shallow depth
    assert L._derive_scope("https://example.com/index.html", None, None) == ("", 1)


def test_derive_scope_dotted_or_empty_segment_no_prefix():
    assert L._derive_scope("https://zod.dev", None, None) == ("", 4)
    assert L._derive_scope("https://x.io/v1.2.3", None, None)[0] == ""  # dotted first seg


def test_derive_scope_explicit_args_win_including_depth_zero():
    # --path-prefix and --max-depth override; max-depth 0 must NOT be coerced to default
    assert L._derive_scope("https://man7.org/a/b/c.8.html", "/custom/", 0) == ("/custom/", 0)
    assert L._derive_scope("https://reactnative.dev/docs/x", None, 7) == ("/docs/", 7)


# --- binary-asset link filtering (no PDF/PNG/ZIP -> .md) ---------------------

def _links(html, base="https://docs.arbitrum.io/intro"):
    from bs4 import BeautifulSoup
    cfg = {"url": base, "same_domain_only": True,
           "_skip_patterns": L._build_skip_patterns(base)}
    return L._links_from_soup(BeautifulSoup(html, "lxml"), base, cfg)


def test_asset_links_are_not_followed():
    html = (
        '<a href="/docs/intro">doc</a>'
        '<a href="/assets/files/audit.pdf">pdf</a>'
        '<a href="/img/logo.png">png</a>'
        '<a href="/dl/sdk.zip">zip</a>'
        '<a href="/fonts/x.woff2">font</a>'
        '<a href="/static/app.js">js</a>'
        '<a href="/theme.css">css</a>'
        '<a href="/diagram.svg">svg</a>'
        '<a href="/report.PDF">UPPER pdf</a>'
    )
    links = _links(html)
    assert any(u.endswith("/docs/intro") for u in links)
    assert not any(L._ASSET_EXT_RE.search(u) for u in links), links
    assert len(links) == 1


def test_document_extensions_still_followed():
    html = ('<a href="/a.html">h</a><a href="/b.md">m</a>'
            '<a href="/c.txt">t</a><a href="/d/">dir</a>')
    links = _links(html)
    assert len(links) == 4


# --- phase4_write: frontmatter url must be the SOURCE url, not the file path ----

def test_phase4_writes_source_url_not_filepath(tmp_path):
    out = tmp_path / "out"; out.mkdir()
    fp = out / "guide" / "intro.md"
    page = {"url": "https://example.com/guide/intro", "title": "Intro",
            "markdown": "Body text here, long enough to matter.",
            "filepath": fp, "depth": 1}
    # sorted_pages is keyed by output-file (the dedup key) — NOT the url
    entries = L.phase4_write([(str(fp), page)], out, compact_pages=False)
    written = fp.read_text()
    assert "url: https://example.com/guide/intro" in written
    assert str(out) not in written.split("\n# ")[0]  # no local path in frontmatter
    assert entries[0]["url"] == "https://example.com/guide/intro"


# --- _write_page: shared per-page writer (incremental crawl + github) ---------

def test_write_page_frontmatter_and_entry(tmp_path):
    out = tmp_path / "o"; out.mkdir()
    fp = out / "a" / "b.md"
    page = {"url": "https://x.io/a/b", "title": "B", "markdown": "Body.",
            "filepath": fp, "depth": 1}
    entry = L._write_page(page, out, minify=None)
    txt = fp.read_text()
    assert 'url: https://x.io/a/b' in txt and txt.startswith("---")
    assert entry == {"title": "B", "url": "https://x.io/a/b", "file": "a/b.md"}


def test_write_page_applies_minify(tmp_path):
    out = tmp_path / "o"; out.mkdir(); fp = out / "p.md"
    page = {"url": "https://x.io/p", "title": "P",
            "markdown": "line1\n\n\n\n\nline2", "filepath": fp, "depth": 0}
    L._write_page(page, out, minify=lambda s: s.replace("\n\n\n\n\n", "\n\n"))
    assert "\n\n\n\n" not in fp.read_text()


# --- provenance stamping (B1) + archive-on-overwrite (B2) --------------------

def test_write_page_stamps_provenance(tmp_path):
    out = tmp_path / "o"; out.mkdir(); fp = out / "p.md"
    page = {"url": "https://x.io/p", "title": "P", "markdown": "Body.",
            "filepath": fp, "depth": 0}
    L._write_page(page, out, minify=None,
                  provenance={"engine": "abc123", "fetched_at": "2026-06-07"})
    txt = fp.read_text()
    assert "fetched_with: abc123" in txt and "fetched_at: 2026-06-07" in txt


def test_archive_existing_moves_old_copy(tmp_path):
    store = tmp_path / "docs"; slug = store / "lib"; slug.mkdir(parents=True)
    (slug / "INDEX.md").write_text("# I\nEngine: oldsha  \nPages: 1\n")
    (slug / "a.md").write_text("old")
    dest = L._archive_existing(slug)
    assert dest is not None and dest.exists()
    assert "@oldsha-" in dest.name
    assert (dest / "a.md").read_text() == "old"
    assert not slug.exists()  # moved away, ready for a fresh write


def test_archive_existing_noop_when_empty(tmp_path):
    store = tmp_path / "docs"; slug = store / "lib"; slug.mkdir(parents=True)
    assert L._archive_existing(slug) is None  # nothing to archive
