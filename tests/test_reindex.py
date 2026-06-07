"""reindex.py: rebuild a slug's INDEX from disk pages (truncated & inflated drift)."""
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "reindex", pathlib.Path(__file__).parent.parent / "scripts" / "reindex.py")
R = importlib.util.module_from_spec(spec); spec.loader.exec_module(R)


def _page(d, rel, title, url):
    p = d / rel; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f'---\ntitle: "{title}"\nurl: {url}\n---\n\n# {title}\n\nbody\n')


def test_reindex_repairs_truncated_and_inflated(tmp_path):
    slug = tmp_path / "lib"; slug.mkdir()
    _page(slug, "a.md", "A", "https://x.io/docs/a")
    _page(slug, "b.md", "B", "https://x.io/docs/b")
    _page(slug, "sub/c.md", "C", "https://x.io/docs/sub/c")
    # truncated INDEX (1 row for 3 pages) with a Source header to preserve
    (slug / "INDEX.md").write_text("# Lib — LLM Index\n\nSource: https://x.io/docs  \nPages: 1\n\n---\n\n- [A](a.md)\n")
    n = R.reindex(slug)
    assert n == 3
    idx = (slug / "INDEX.md").read_text()
    rows = [ln for ln in idx.splitlines() if ln.startswith("- [")]
    assert len(rows) == 3                       # matches disk now
    assert "Source: https://x.io/docs" in idx   # header preserved
    assert "Pages: 3" in idx


def test_reindex_falls_back_to_heading_when_no_frontmatter(tmp_path):
    slug = tmp_path / "lib"; slug.mkdir()
    (slug / "p.md").write_text("# Just A Heading\n\ncontent\n")
    n = R.reindex(slug)
    assert n == 1 and "Just A Heading" in (slug / "INDEX.md").read_text()
