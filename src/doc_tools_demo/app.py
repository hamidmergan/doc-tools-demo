"""Gradio UI with one tab per tool and a pipeline tab."""

import argparse
import functools
from pathlib import Path
from typing import List, Optional

import gradio as gr

from . import __version__, core

EXTRACT_TYPES = [".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"]
CHUNK_TYPES = [".pdf", ".docx", ".pptx", ".txt", ".md", ".markdown"]
TRANSLATE_TYPES = [".docx", ".docm", ".pptx", ".pptm", ".md", ".txt"]
GLOSSARY_TYPES = [".csv", ".tsv", ".txt", ".json"]

INTRO = """# doc-tools-demo

Try [doc-extract](https://github.com/hamidmergan/doc-extract), [doc-chunker](https://github.com/hamidmergan/doc-chunker) and [office-translate](https://github.com/hamidmergan/office-translate) in the browser.
Set the model server below. Chunking runs locally and needs no model."""


def _settings(base_url, model, vision_model, api_key) -> core.Settings:
    return core.Settings(base_url, model, vision_model, api_key)


def _shows_errors(func):
    """Turn tool errors into a message in the UI instead of a stack trace."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except gr.Error:
            raise
        except core.TOOL_ERRORS as e:
            raise gr.Error(_hint(e), print_exception=False)
        except ValueError as e:
            raise gr.Error(str(e), print_exception=False)

    return wrapper


def _hint(error: Exception) -> str:
    text = str(error)
    if type(error).__name__ == "ConfigError" and ("base_url" in text or "model" in text):
        return text + " In this app, fill in Base URL and Model under Model settings."
    return text


def _need(value, message: str):
    if value is None or (isinstance(value, str) and not value.strip()):
        raise gr.Error(message, print_exception=False)
    return value


def _notes(warnings: List[str]) -> str:
    if not warnings:
        return ""
    return "**Warnings**\n\n" + "\n".join(f"- {w}" for w in warnings)


@_shows_errors
def run_extract(file, base_url, model, vision_model, api_key):
    _need(file, "Upload a PDF or an image first.")
    markdown = core.extract_markdown(file, _settings(base_url, model, vision_model, api_key))
    out = core.write_file(core.work_dir(), Path(file).stem + ".md", markdown)
    return markdown, str(out)


@_shows_errors
def run_chunk(file, chunk_size, overlap):
    _need(file, "Upload a file first.")
    chunks = core.chunk_file(file, chunk_size, overlap)
    rows = [[c.index, c.page if c.page is not None else "", c.text] for c in chunks]
    out = core.write_file(core.work_dir(), Path(file).name + ".jsonl", core.to_jsonl(c.to_dict() for c in chunks))
    return rows, str(out), f"{len(chunks)} chunks"


def _translator(settings, target_lang, source_lang, glossary_rows, glossary_file, instructions, strict):
    _need(target_lang, "Enter a target language, for example German or de.")
    glossary = core.build_glossary(glossary_rows, glossary_file)
    return core.make_translator(settings, target_lang, source_lang, glossary, instructions, strict)


@_shows_errors
def run_translate(
    file, text, target_lang, source_lang, instructions, glossary_rows, glossary_file, strict,
    base_url, model, vision_model, api_key,
):
    if not file and not (text and text.strip()):
        raise gr.Error("Upload a file or enter some text.", print_exception=False)
    settings = _settings(base_url, model, vision_model, api_key)
    translator = _translator(settings, target_lang, source_lang, glossary_rows, glossary_file, instructions, strict)
    out_file: Optional[str] = None
    out_text = ""
    warnings: List[str] = []
    if file:
        path, found = core.translate_document(file, core.work_dir(), translator)
        out_file = str(path)
        warnings += found
    if text and text.strip():
        out_text, found = core.translate_plain(text, translator)
        warnings += found
    return out_file, out_text, _notes(warnings)


@_shows_errors
def run_pipeline(
    file, target_lang, chunk_size, overlap, use_glossary,
    source_lang, instructions, glossary_rows, glossary_file, strict,
    base_url, model, vision_model, api_key,
):
    _need(file, "Upload a PDF or an image first.")
    settings = _settings(base_url, model, vision_model, api_key)
    translator = None
    if target_lang and target_lang.strip():
        if not use_glossary:
            # Settings of the Translate tab only apply when the box is ticked.
            source_lang, instructions, glossary_rows, glossary_file, strict = None, None, None, None, False
        translator = _translator(settings, target_lang, source_lang, glossary_rows, glossary_file, instructions, strict)
    result = core.run_pipeline(file, settings, translator, chunk_size, overlap)
    table = [
        [r["index"], r["page"] if r["page"] is not None else "", r["text"], r.get("translation", "")]
        for r in result.rows
    ]
    summary = f"{len(result.rows)} chunks"
    notes = _notes(result.warnings)
    return result.markdown, table, [str(result.markdown_file), str(result.jsonl_file)], summary + ("\n\n" + notes if notes else "")


def build(defaults: Optional[core.Settings] = None) -> gr.Blocks:
    defaults = defaults or core.Settings.from_env()

    with gr.Blocks(title="doc-tools-demo") as demo:
        gr.Markdown(INTRO)

        with gr.Accordion("Model settings", open=not (defaults.base_url and defaults.model)):
            with gr.Row():
                base_url = gr.Textbox(defaults.base_url or "", label="Base URL", placeholder="http://localhost:11434/v1")
                api_key = gr.Textbox(defaults.api_key or "", label="API key (optional)", type="password")
            with gr.Row():
                model = gr.Textbox(defaults.model or "", label="Model", info="Used for translation.")
                vision_model = gr.Textbox(
                    defaults.vision_model or "", label="Vision model (optional)",
                    info="Used for extraction. Empty means the model above, which then must read images.",
                )
        model_inputs = [base_url, model, vision_model, api_key]

        with gr.Tab("Extract"):
            gr.Markdown("Read a PDF or an image with a vision model and get Markdown.")
            ex_file = gr.File(label="PDF or image", file_types=EXTRACT_TYPES, type="filepath")
            ex_button = gr.Button("Extract", variant="primary")
            ex_text = gr.Textbox(label="Markdown", lines=18, buttons=["copy"])
            ex_out = gr.File(label="Download")
            ex_button.click(run_extract, [ex_file, *model_inputs], [ex_text, ex_out])

        with gr.Tab("Chunk"):
            gr.Markdown("Split a document into chunks for RAG. Runs locally.")
            ch_file = gr.File(label="Document", file_types=CHUNK_TYPES, type="filepath")
            with gr.Row():
                ch_size = gr.Number(1000, label="Chunk size (characters)", precision=0, minimum=50)
                ch_overlap = gr.Number(150, label="Overlap (characters)", precision=0, minimum=0)
            ch_button = gr.Button("Chunk", variant="primary")
            ch_info = gr.Markdown()
            ch_table = gr.Dataframe(headers=["index", "page", "text"], wrap=True, interactive=False)
            ch_out = gr.File(label="Download JSONL")
            ch_button.click(run_chunk, [ch_file, ch_size, ch_overlap], [ch_table, ch_out, ch_info])

        with gr.Tab("Translate"):
            gr.Markdown("Translate a Word, PowerPoint, Markdown or text file, or paste text. Formatting stays as it is.")
            with gr.Row():
                tr_file = gr.File(label="File", file_types=TRANSLATE_TYPES, type="filepath")
                tr_text = gr.Textbox(label="Or text", lines=6)
            with gr.Row():
                tr_target = gr.Textbox("German", label="Target language")
                tr_source = gr.Textbox("", label="Source language (optional)")
            tr_instructions = gr.Textbox("", label="Instructions (optional)", placeholder="Formal tone, audience is engineers")
            with gr.Accordion("Glossary", open=False):
                gr.Markdown("Fixed terms. An empty target keeps the term unchanged. Table rows win over the file.")
                tr_glossary = gr.Dataframe(
                    headers=["source", "target"], column_count=2, row_count=3,
                    datatype=["str", "str"], type="array", interactive=True,
                )
                tr_glossary_file = gr.File(label="Glossary file (CSV, TSV or JSON)", file_types=GLOSSARY_TYPES, type="filepath")
                tr_strict = gr.Checkbox(False, label="Strict glossary (exact terms, no inflection)")
            tr_button = gr.Button("Translate", variant="primary")
            tr_out_file = gr.File(label="Download")
            tr_out_text = gr.Textbox(label="Translated text", lines=6, buttons=["copy"])
            tr_notes = gr.Markdown()
            tr_button.click(
                run_translate,
                [tr_file, tr_text, tr_target, tr_source, tr_instructions, tr_glossary, tr_glossary_file, tr_strict, *model_inputs],
                [tr_out_file, tr_out_text, tr_notes],
            )

        with gr.Tab("Pipeline"):
            gr.Markdown(
                "PDF or image to Markdown, Markdown to chunks, chunks to the target language. "
                "Leave the target language empty to skip translation."
            )
            pi_file = gr.File(label="PDF or image", file_types=EXTRACT_TYPES, type="filepath")
            with gr.Row():
                pi_target = gr.Textbox("", label="Target language (optional)")
                pi_size = gr.Number(1000, label="Chunk size (characters)", precision=0, minimum=50)
                pi_overlap = gr.Number(150, label="Overlap (characters)", precision=0, minimum=0)
            pi_glossary = gr.Checkbox(True, label="Use source language, instructions and glossary from the Translate tab")
            pi_button = gr.Button("Run", variant="primary")
            pi_info = gr.Markdown()
            pi_table = gr.Dataframe(headers=["index", "page", "text", "translation"], wrap=True, interactive=False)
            with gr.Accordion("Markdown", open=False):
                pi_text = gr.Textbox(label="Markdown", lines=14, buttons=["copy"])
            pi_out = gr.File(label="Download", file_count="multiple")
            pi_button.click(
                run_pipeline,
                [pi_file, pi_target, pi_size, pi_overlap, pi_glossary,
                 tr_source, tr_instructions, tr_glossary, tr_glossary_file, tr_strict, *model_inputs],
                [pi_text, pi_table, pi_out, pi_info],
            )

        gr.Markdown(f"<small>doc-tools-demo {__version__}</small>")
    return demo


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="doc-tools-demo",
        description="Web demo for doc-extract, doc-chunker and office-translate.",
    )
    p.add_argument("--base-url", help="OpenAI-compatible endpoint, for example http://localhost:11434/v1")
    p.add_argument("--model", help="text model for translation")
    p.add_argument("--vision-model", help="vision model for extraction (default: --model)")
    p.add_argument("--api-key", help="API key, optional for local servers")
    p.add_argument("--host", default="127.0.0.1", help="address to listen on (default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=7860, help="port (default: 7860)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: Optional[List[str]] = None) -> None:
    args = _parser().parse_args(argv)
    env = core.Settings.from_env()
    defaults = core.Settings(
        args.base_url or env.base_url,
        args.model or env.model,
        args.vision_model or env.vision_model,
        args.api_key or env.api_key,
    )
    build(defaults).launch(
        server_name=args.host,
        server_port=args.port,
        allowed_paths=[str(core.work_root())],
    )


if __name__ == "__main__":
    main()
