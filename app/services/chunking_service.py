import tiktoken

from app.config import settings

_encoder = tiktoken.encoding_for_model("gpt-4o-mini")


def chunk_text(text: str) -> list[str]:
    """Split text into overlapping chunks of ~500 tokens with 50-token overlap.

    Keeps every chunk that carries new content — including the sole chunk of a
    short page. A short page's only window (`start == 0`) is always kept, even if
    it's smaller than MIN_CHUNK_SIZE; otherwise that page produces zero chunks and
    becomes invisible to search (e.g. a Contact / Intake-form page). A *later*
    window smaller than MIN_CHUNK_SIZE is a pure-overlap tail — it's entirely
    contained in the previous chunk (stride 450 < window 500), so it adds nothing
    and is dropped.
    """
    tokens = _encoder.encode(text)
    chunks = []

    start = 0
    while start < len(tokens):
        end = start + settings.CHUNK_SIZE
        chunk_tokens = tokens[start:end]

        if start == 0 or len(chunk_tokens) >= settings.MIN_CHUNK_SIZE:
            chunks.append(_encoder.decode(chunk_tokens))

        start += settings.CHUNK_SIZE - settings.CHUNK_OVERLAP

    return chunks
