"""Baseline chunking: fixed-size character windows with overlap.

Deliberately simple. M1 measures how well this works; M2 replaces it with
structure-aware chunking (one section / rule / paragraph per chunk) and the
evaluation shows how much that helps.
"""


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    """Split text into windows of about `size` characters.

    Neighbouring windows share `overlap` characters so a sentence cut at one
    boundary still appears whole in the next chunk. Cuts are moved back to the
    nearest whitespace so words are never split.
    """
    if size <= 0:
        raise ValueError("size must be positive")
    if not 0 <= overlap < size:
        raise ValueError("overlap must be at least 0 and smaller than size")

    text = text.strip()
    if not text:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            space = text.rfind(" ", start + size // 2, end)  # don't cut mid-word
            newline = text.rfind("\n", start + size // 2, end)
            cut = max(space, newline)
            if cut > start:
                end = cut
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        next_start = end - overlap
        # Start the next chunk at a word boundary too.
        boundary = text.find(" ", next_start, end)
        new_start = boundary + 1 if boundary != -1 else next_start
        # Always move forward, whatever the size/overlap settings: no infinite loop.
        start = new_start if new_start > start else end
    return chunks
