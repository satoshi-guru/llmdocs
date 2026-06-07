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
