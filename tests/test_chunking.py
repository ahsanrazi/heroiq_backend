"""Unit tests for chunk_text — the short-page keep-rule + redundant-tail drop.

chunk_text is a pure function (only tiktoken + settings), so these need no
mocking, network, or DB.
"""
import pytest

from app.config import settings
from app.services import chunking_service

enc = chunking_service._encoder
SIZE = settings.CHUNK_SIZE
OVER = settings.CHUNK_OVERLAP
MIN = settings.MIN_CHUNK_SIZE
STRIDE = SIZE - OVER

# A long token pool we slice to build texts of a known length. Decoding a token
# slice and re-encoding round-trips at token boundaries, so the built text's real
# length is (near) the requested count — tests read the real length back to stay
# exact regardless of any 1-token drift.
_POOL = enc.encode(
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod "
    "tempor incididunt ut labore et dolore magna aliqua. " * 400
)


def _text_of(n_tokens: int) -> str:
    return enc.decode(_POOL[:n_tokens])


def _expected_chunks(n_tokens: int) -> int:
    """Reference mirror of the intended keep-rule: the first/only window is always
    kept; later windows are kept only when >= MIN_CHUNK_SIZE (pure-overlap tails
    dropped)."""
    cnt = start = 0
    while start < n_tokens:
        clen = min(start + SIZE, n_tokens) - start
        if start == 0 or clen >= MIN:
            cnt += 1
        start += STRIDE
    return cnt


def test_empty_text_returns_no_chunks():
    # Trigger for the index-time title-only fallback.
    assert chunking_service.chunk_text("") == []


def test_short_page_keeps_its_only_chunk():
    """The fix: a page shorter than MIN_CHUNK_SIZE tokens is now indexed as one
    chunk. Under the old `>= MIN_CHUNK_SIZE` gate it produced zero chunks and was
    invisible to search (e.g. a Contact / Intake-form page)."""
    short = "New Patient Intake Form"
    assert len(enc.encode(short)) < MIN          # precondition: old rule dropped it
    chunks = chunking_service.chunk_text(short)
    assert len(chunks) == 1
    assert chunks[0].strip() == short


def test_redundant_trailing_fragment_is_dropped():
    """A page just under one full window: the whole page is one chunk and the tiny
    trailing fragment (< MIN, fully inside chunk 1) is not emitted — no waste."""
    text = _text_of(SIZE - 30)                   # 470 tokens → 1 chunk, tail dropped
    real = len(enc.encode(text))
    assert real < SIZE
    assert len(chunking_service.chunk_text(text)) == 1


@pytest.mark.parametrize("n", [1, 5, 49, 50, 100, 460, 470, 500, 510, 950, 1000, 2126])
def test_chunk_count_matches_keep_rule(n):
    text = _text_of(n)
    real = len(enc.encode(text))                 # guard against round-trip drift
    assert len(chunking_service.chunk_text(text)) == _expected_chunks(real)


def test_long_page_multi_window():
    """A comfortably-long page chunks into multiple windows, matching the keep-rule
    for whatever CHUNK_SIZE/OVERLAP are configured (no hardcoded count)."""
    text = _text_of(1000)
    real = len(enc.encode(text))
    n = len(chunking_service.chunk_text(text))
    assert n == _expected_chunks(real)
    assert n >= 3  # 1000 tokens spans several windows at any sane chunk size
