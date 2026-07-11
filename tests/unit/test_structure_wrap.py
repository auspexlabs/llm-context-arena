"""Tests for structure wrap/restore gate (DEC-018 B4)."""

from backend.structure_wrap import detect_structure_lines, restore_after_summarize, wrap_for_summarize


def test_wrap_and_restore_citation_headers():
    text = "--- src/a.py:1-10 ---\nbody\n--- src/b.py:2-4 ---\nmore\n"
    wrapped, spans = wrap_for_summarize(text)
    assert "⟦S0⟧" in wrapped
    assert "--- src/a.py" not in wrapped
    restored, preserved = restore_after_summarize(wrapped.replace("⟦S0⟧", "--- src/a.py:1-10 ---\n"), spans)
    assert preserved is True
    assert "--- src/a.py:1-10 ---" in restored


def test_detect_structure_lines_finds_symbols():
    text = "# MyClass\nclass MyClass:\n  pass\n"
    spans = detect_structure_lines(text)
    assert len(spans) == 1
    assert spans[0].original.startswith("# MyClass")