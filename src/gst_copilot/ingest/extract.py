"""Turn source files into clean plain text."""

import re
from pathlib import Path


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        raw = _pdf_text(path)
    elif suffix in {".txt", ".md"}:
        raw = path.read_text(encoding="utf-8")
    else:
        raise ValueError(f"Unsupported file type: {path.name} (use .pdf, .txt or .md)")
    return clean_text(raw)


def _pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n\n".join(pages)
    if len(text.strip()) < 50:
        # Scanned PDFs are images; pypdf can't read them. They need OCR (not in M1).
        raise ValueError(f"{path.name}: almost no text extracted. Is it a scanned PDF?")
    return text


def clean_text(text: str) -> str:
    """Normalise whitespace, fix words broken across lines, drop page-number lines."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # "regis-\ntration" -> "registration"
    lines = [ln.strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if not re.fullmatch(r"(page\s*)?\d{1,4}(\s*of\s*\d+)?", ln, re.I)]
    text = "\n".join(lines)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
