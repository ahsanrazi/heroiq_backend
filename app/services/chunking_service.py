import tiktoken

from app.config import settings

_encoder = tiktoken.encoding_for_model("gpt-4o-mini")


def chunk_text(text: str) -> list[str]:
    """Split text into overlapping chunks of ~500 tokens with 50-token overlap.
    Skips chunks smaller than MIN_CHUNK_SIZE tokens.
    """
    tokens = _encoder.encode(text)
    chunks = []

    start = 0
    while start < len(tokens):
        end = start + settings.CHUNK_SIZE
        chunk_tokens = tokens[start:end]

        if len(chunk_tokens) >= settings.MIN_CHUNK_SIZE:
            chunks.append(_encoder.decode(chunk_tokens))

        start += settings.CHUNK_SIZE - settings.CHUNK_OVERLAP

    return chunks
