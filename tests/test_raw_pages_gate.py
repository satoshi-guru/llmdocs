"""manifest._raw_pages: count only real text docs (exclude asset/binary), and work
even when the store lives under a dotdir (~/.llmdocs)."""
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "manifest", pathlib.Path(__file__).parent.parent / "scripts" / "manifest.py")
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)


def test_excludes_asset_and_binary_keeps_code_heavy(tmp_path):
    lib = tmp_path / "lib"; lib.mkdir()
    (lib / "guide.md").write_text("# Guide\n\nReal prose with `code` and examples.\n")
    # code/symbol-heavy real doc — must be KEPT (lots of punctuation, still text)
    (lib / "api.md").write_text("def f(a,b,*,o=1)->T: return {k:[v]} # ()[]{}|:=,.<>\n" * 20)
    (lib / "logo.png.md").write_text("iVBORw0KGgoAAAANSUhEUg" * 50)   # asset by extension
    (lib / "blob.md").write_text("\x00\x01\x02\xff" * 500 + "x")       # binary by content
    names = {p.name for p in M._raw_pages(lib)}
    assert "guide.md" in names and "api.md" in names      # real docs kept (incl code-heavy)
    assert "logo.png.md" not in names                     # asset extension excluded
    assert "blob.md" not in names                         # binary content excluded


def test_works_under_dotdir_store(tmp_path):
    # store root is a dotdir (mirrors ~/.llmdocs) — pages must still be found
    lib = tmp_path / ".llmdocs" / "docs" / "lib"; lib.mkdir(parents=True)
    (lib / "page.md").write_text("# Page\n\nContent here.\n")
    assert [p.name for p in M._raw_pages(lib)] == ["page.md"]
