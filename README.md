# doc-tools-demo

A small web app to try [doc-extract](https://github.com/hamidmergan/doc-extract), [doc-chunker](https://github.com/hamidmergan/doc-chunker) and [office-translate](https://github.com/hamidmergan/office-translate) in the browser. It is built with Gradio and works with any OpenAI-compatible model server, for example Ollama, vLLM, LM Studio or a hosted API.

The app has four tabs:

- Extract: PDF or image to Markdown with a vision model
- Chunk: PDF, DOCX, PPTX, TXT or MD to chunks for RAG, runs locally
- Translate: DOCX, PPTX, MD, TXT or pasted text to another language, with an optional glossary
- Pipeline: PDF or image to Markdown, then to chunks with page numbers, then optionally to another language

## Prerequisites

- Python 3.10 or newer
- An OpenAI-compatible endpoint for Extract, Translate and Pipeline
- A vision model for Extract and Pipeline, for example `qwen2.5vl` in Ollama

The Chunk tab needs no model. If you run the model yourself, your documents never leave your network.

## Installation

doc-tools-demo is installed from GitHub:

```bash
pip install git+https://github.com/hamidmergan/doc-tools-demo.git
```

Alternatively, you can install it from a local copy:

```bash
git clone https://github.com/hamidmergan/doc-tools-demo.git
cd doc-tools-demo
pip install .
```

## Usage

Start the app and open http://127.0.0.1:7860 in your browser:

```bash
doc-tools-demo --base-url http://localhost:11434/v1 --model llama3.1 --vision-model qwen2.5vl
```

You can also start it without flags and fill in the model settings at the top of the page.

With a hosted API:

```bash
export DOC_TOOLS_DEMO_API_KEY=sk-...
doc-tools-demo --base-url https://api.openai.com/v1 --model gpt-4o-mini
```

### Tabs

- Extract: upload a PDF or image and get Markdown. Several pages are marked with `<!-- page N -->`.
- Chunk: choose chunk size and overlap and download the chunks as JSON Lines.
- Translate: upload a file or paste text and set the target language. Open "Glossary" to fix terms, either in the table or as a CSV, TSV or JSON file. Rows in the table win over the file. An empty target keeps the term unchanged. Unused glossary terms are listed as warnings.
- Pipeline: upload a PDF or image. Leave the target language empty to only extract and chunk. With the box ticked, source language, instructions and glossary from the Translate tab are used too. You get the Markdown and a JSON Lines file with `source`, `index`, `page`, `text` and, when translated, `translation` and `target_lang`.

### Settings

Order: flag, then environment variable. There are no defaults for the model server.

| Flag | Environment variable | Meaning |
| --- | --- | --- |
| `--base-url` | `DOC_TOOLS_DEMO_BASE_URL` | OpenAI-compatible endpoint |
| `--model` | `DOC_TOOLS_DEMO_MODEL` | text model for translation |
| `--vision-model` | `DOC_TOOLS_DEMO_VISION_MODEL` | vision model for extraction, default is `--model` |
| `--api-key` | `DOC_TOOLS_DEMO_API_KEY` | API key, optional for local servers |
| `--host` | | address to listen on, default `127.0.0.1` |
| `--port` | | port, default `7860` |

Values from flags or environment variables stay on the server. They are not shown on the page and not sent to the browser, so the fields stay empty. Values typed into the page win and only apply to that browser tab. If neither is set, the settings of each tool are used, for example `DOC_EXTRACT_BASE_URL` or `OFFICE_TRANSLATE_MODEL`.

## Limitations

- This is a demo. It has no login. Keep the default host `127.0.0.1` or put it behind your own access control before you share it.
- Result files are written to a `doc-tools-demo` folder in the system temp directory and are not deleted by the app.
- Large PDFs take a while, since every page goes to the vision model.
- The limits of the three tools apply. See their READMEs.

## Running Tests

```bash
pip install -e ".[test]"
pytest
```

The tests start a small fake model server and create their own sample files. No real model is needed.

## License

MIT
