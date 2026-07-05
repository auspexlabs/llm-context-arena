"""Tests for ColBERT-style late-interaction retrieval."""

from backend.rag.colbert import LateInteractionIndex, maxsim_score, tokenize_for_late_interaction
from backend.rag.types import CodeChunk


def _chunk(symbol: str, content: str, source: str = "a.py") -> CodeChunk:
    return CodeChunk(
        chunk_id=f"id-{symbol}",
        source=source,
        content=content,
        line_start=1,
        line_end=5,
        chunk_type="function",
        symbol=symbol,
        index_text=content,
    )


class TestLateInteractionIndex:
    def test_tokenize_splits_identifiers(self):
        tokens = tokenize_for_late_interaction("authenticate_user verify")
        assert "authenticate_user" in tokens
        assert "verify" in tokens

    def test_maxsim_prefers_token_overlap(self):
        q = tokenize_for_late_interaction("authenticate_user")
        d_match = tokenize_for_late_interaction("def authenticate_user(): pass")
        d_miss = tokenize_for_late_interaction("def other_fn(): pass")
        embed = lambda t: [1.0 if t == "authenticate_user" else 0.0]
        assert maxsim_score(q, d_match, embed) > maxsim_score(q, d_miss, embed)

    def test_search_ranks_symbol_match_higher(self):
        target = _chunk("authenticate_user", "def authenticate_user(): return True", "auth/login.py")
        noise = _chunk("bootstrap", "def bootstrap(): pass", "main.py")
        idx = LateInteractionIndex.from_chunks([noise, target])
        results = idx.search("where is authenticate_user defined", k=2)
        assert results[0][0].symbol == "authenticate_user"