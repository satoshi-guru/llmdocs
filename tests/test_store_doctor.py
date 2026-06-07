"""store_doctor audit: asset detection + INDEX drift."""
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "store_doctor", pathlib.Path(__file__).parent.parent / "scripts" / "store_doctor.py")
sd = importlib.util.module_from_spec(spec); spec.loader.exec_module(sd)


def _mk(slug_dir, files, index_rows):
    slug_dir.mkdir(parents=True)
    for f in files:
        p = slug_dir / f; p.parent.mkdir(parents=True, exist_ok=True); p.write_text("x")
    idx = "# I\n\nSource: u\n\n" + "".join(f"- [t]({f})\n" for f in index_rows)
    (slug_dir / "INDEX.md").write_text(idx)


def test_audit_flags_assets_and_drift(tmp_path):
    store = tmp_path / "docs"
    # clean slug: 2 pages, INDEX matches -> no defect
    _mk(store / "clean", ["a.md", "b.md"], ["a.md", "b.md"])
    # asset slug: 1 real + 2 assets, INDEX truncated -> assets + drift
    _mk(store / "dirty", ["a.md", "logo.png.md", "dl.zip.md"], ["a.md"])
    rows = {r["slug"]: r for r in sd.audit(store)}
    assert rows["clean"]["assets"] == 0 and not rows["clean"]["drift"]
    assert rows["dirty"]["assets"] == 2
    assert rows["dirty"]["clean"] == 1
    assert rows["dirty"]["drift"]  # 3 files vs 1 index row


def test_asset_re_matches_binaries_not_docs():
    for good in ["logo.png.md", "a.PDF.md", "x.woff2.md", "app.js.md", "d.tar.gz.md"]:
        assert sd.ASSET_RE.search(good), good
    for doc in ["guide.md", "index.md", "api.html.md", "notes.txt.md"]:
        assert not sd.ASSET_RE.search(doc), doc
