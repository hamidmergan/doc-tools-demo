"""Logic behind the demo. Kept free of Gradio so it can be tested on its own."""

import json
import logging
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple, Union

import doc_chunker
import doc_extract
import office_translate
from office_translate.core import output_path
from office_translate.glossary import load_glossary

PathLike = Union[str, Path]

ENV_PREFIX = "DOC_TOOLS_DEMO_"

# Errors of the three tools. All of them are shown to the user as a message.
TOOL_ERRORS = (doc_extract.ExtractError, doc_chunker.ChunkError, office_translate.TranslateError)


@dataclass(frozen=True)
class Settings:
    """Model access shared by all tabs. Empty values fall back to each tool's own settings."""

    base_url: Optional[str] = None
    model: Optional[str] = None
    vision_model: Optional[str] = None
    api_key: Optional[str] = None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(*(_env(name) for name in ("BASE_URL", "MODEL", "VISION_MODEL", "API_KEY")))

    def clean(self) -> "Settings":
        return Settings(*(_blank_to_none(v) for v in (self.base_url, self.model, self.vision_model, self.api_key)))

    def over(self, fallback: "Settings") -> "Settings":
        """Values of this object, with empty ones taken from ``fallback``."""
        mine, other = self.clean(), fallback.clean()
        return Settings(
            mine.base_url or other.base_url,
            mine.model or other.model,
            mine.vision_model or other.vision_model,
            mine.api_key or other.api_key,
        )

    def text_args(self) -> dict:
        s = self.clean()
        return {"base_url": s.base_url, "model": s.model, "api_key": s.api_key}

    def vision_args(self) -> dict:
        s = self.clean()
        return {"base_url": s.base_url, "model": s.vision_model or s.model, "api_key": s.api_key}


def _env(name: str) -> Optional[str]:
    return _blank_to_none(os.environ.get(ENV_PREFIX + name))


def _blank_to_none(value: Optional[str]) -> Optional[str]:
    if value is None or not str(value).strip():
        return None
    return str(value).strip()


def work_root() -> Path:
    """Parent folder of all result files. The app only serves files from here."""
    root = Path(tempfile.gettempdir()) / "doc-tools-demo"
    root.mkdir(exist_ok=True)
    return root


def work_dir() -> Path:
    """A fresh folder for files the user can download."""
    return Path(tempfile.mkdtemp(dir=work_root()))


def write_file(folder: Path, name: str, text: str) -> Path:
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


def to_jsonl(records: Iterable[dict]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)


# Extract


def extract_markdown(path: PathLike, settings: Settings) -> str:
    """Read an image or PDF with the vision model and return Markdown."""
    return doc_extract.extract(path, **settings.vision_args())


# Chunk


def chunk_file(path: PathLike, chunk_size: Optional[int] = None, overlap: Optional[int] = None) -> List[doc_chunker.Chunk]:
    return doc_chunker.chunk(path, chunk_size=_int_or_none(chunk_size), overlap=_int_or_none(overlap))


def _int_or_none(value) -> Optional[int]:
    if value is None or value == "":
        return None
    return int(value)


# Translate


def build_glossary(rows: Optional[Sequence[Sequence]] = None, file: Optional[PathLike] = None) -> Optional[Dict[str, str]]:
    """Merge a glossary file and table rows. Rows win over the file for the same term."""
    terms: Dict[str, str] = {}
    if file:
        terms.update(load_glossary(file).terms)
    for row in rows or []:
        if not row or len(row) < 1:
            continue
        source = str(row[0] or "").strip()
        target = str(row[1] or "").strip() if len(row) > 1 else ""
        if source:
            terms[source] = target
    return terms or None


class _Collect(logging.Handler):
    def __init__(self, thread_id: int):
        super().__init__(logging.WARNING)
        self.thread_id = thread_id
        self.messages: List[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        # The app serves several users at once, so only keep messages of this request.
        if record.thread == self.thread_id:
            self.messages.append(record.getMessage())


@contextmanager
def collect_warnings() -> Iterator[List[str]]:
    """Collect warnings of office-translate, for example unused glossary terms."""
    logger = logging.getLogger("office_translate")
    handler = _Collect(threading.get_ident())
    logger.addHandler(handler)
    try:
        yield handler.messages
    finally:
        logger.removeHandler(handler)


def make_translator(
    settings: Settings,
    target_lang: str,
    source_lang: Optional[str] = None,
    glossary: Optional[Dict[str, str]] = None,
    instructions: Optional[str] = None,
    strict_glossary: bool = False,
) -> office_translate.Translator:
    return office_translate.Translator(
        target_lang,
        _blank_to_none(source_lang),
        glossary,
        _blank_to_none(instructions),
        strict_glossary=strict_glossary,
        **settings.text_args(),
    )


def translate_document(path: PathLike, folder: Path, translator: office_translate.Translator) -> Tuple[Path, List[str]]:
    """Translate a file into `folder`. Returns the new file and any warnings."""
    out = folder / output_path(Path(path), translator.target_lang).name
    with collect_warnings() as warnings:
        result = translator.translate_file(path, out)
    return result, list(warnings)


def translate_plain(text: str, translator: office_translate.Translator) -> Tuple[str, List[str]]:
    """Translate text paragraph by paragraph. Empty lines are kept."""
    with collect_warnings() as warnings:
        lines = translator.translate(text.split("\n"))
    return "\n".join(lines), list(warnings)


# Pipeline

_PAGE_MARKER = re.compile(r"^<!-- page (\d+) -->[ \t]*$", re.MULTILINE)


def split_pages(markdown: str) -> List[Tuple[Optional[int], str]]:
    """Split doc-extract output at its page markers. Without markers the whole text is one part."""
    found = list(_PAGE_MARKER.finditer(markdown))
    if not found:
        return [(None, markdown)]
    parts = []
    for i, match in enumerate(found):
        end = found[i + 1].start() if i + 1 < len(found) else len(markdown)
        parts.append((int(match.group(1)), markdown[match.end():end]))
    return parts


def chunk_pages(markdown: str, folder: Path, chunk_size=None, overlap=None) -> List[Tuple[Optional[int], str]]:
    """Chunk each page on its own, so every chunk keeps its page number."""
    result = []
    for page, text in split_pages(markdown):
        if not text.strip():
            continue
        part = write_file(folder, f"page-{page or 1}.md", text)
        try:
            chunks = chunk_file(part, chunk_size, overlap)
        except doc_chunker.NoTextError:
            continue
        finally:
            part.unlink()
        result.extend((page, c.text) for c in chunks)
    return result


@dataclass
class PipelineResult:
    markdown: str
    rows: List[dict]
    markdown_file: Path
    jsonl_file: Path
    warnings: List[str]


def run_pipeline(
    path: PathLike,
    settings: Settings,
    translator: Optional[office_translate.Translator] = None,
    chunk_size: Optional[int] = None,
    overlap: Optional[int] = None,
) -> PipelineResult:
    """Image or PDF to Markdown, Markdown to chunks, and optionally chunks to the target language."""
    path = Path(path)
    folder = work_dir()
    markdown = extract_markdown(path, settings)
    md_file = write_file(folder, path.stem + ".md", markdown)
    chunks = chunk_pages(markdown, folder, chunk_size, overlap)
    if not chunks:
        raise doc_chunker.NoTextError(f"No text found in {path.name}.")

    warnings: List[str] = []
    translated: List[Optional[str]] = [None] * len(chunks)
    if translator is not None:
        with collect_warnings() as found:
            translated = translator.translate([text for _, text in chunks])
        warnings = list(found)

    rows = []
    for index, ((page, text), new) in enumerate(zip(chunks, translated)):
        row = {"source": path.name, "index": index, "page": page, "text": text}
        if translator is not None:
            row["translation"] = new
            row["target_lang"] = translator.target_lang
        rows.append(row)
    jsonl = write_file(folder, path.stem + ".chunks.jsonl", to_jsonl(rows))
    return PipelineResult(markdown, rows, md_file, jsonl, warnings)
