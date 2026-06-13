# CDM_INFLUX

CDM_INFLUX is a lightweight production-oriented Python application that collects, structures, stores and explores YouTube creator predictions for the 2026 FIFA World Cup.

## Why Streamlit first?

The first version uses **Streamlit only** to keep the stack simple and ship an end-to-end workflow quickly. The application is intentionally split into configuration, services, extraction and storage layers so a **FastAPI internal API can be added later** without rewriting business logic.

## Features in v1

- YAML-based channel configuration
- Demo YouTube ingestion pipeline with multilingual World Cup 2026 detection
- Transcript extraction via YouTube captions API first, then youtube-transcript-api fallback with explicit status handling
- Rule-based prediction extraction with an optional Ollama extension point
- SQLite storage with repositories and migration bootstrap
- Streamlit dashboard with overview, explorer, video detail, creator comparison, match consensus and reliability views
- Basic unit tests for config loading, extraction rules and repositories

## Project structure

```text
app/
  dashboard/
  extraction/
  ingestion/
  models/
  services/
  storage/
  utils/
config/
data/
tests/
app.py
pyproject.toml
README.md
```

## Requirements

- Python 3.11+
- pip

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

## Run the demo ingestion pipeline

```bash
python -m app.cli seed
```

This command:
- creates the SQLite database in `data/cdm_influx.db`
- loads `config/channels.yml`
- ingests demo videos from `data/demo_videos.json`
- extracts demo transcripts when bundled, otherwise tries the YouTube captions API first and falls back to `youtube-transcript-api`
- stores the results for the dashboard

## Build local RAG index

```bash
python -m app.cli index-rag
```

This command indexes already stored transcripts into a persistent local ChromaDB collection (`data/chroma` by default).

## Launch the dashboard

```bash
streamlit run app.py
```

The dashboard auto-initializes the demo dataset if the database is empty.

## Run tests

```bash
pytest
```

## Configuration

- Channel list: `config/channels.yml`
- Demo dataset: `data/demo_videos.json`
- Database path can be overridden with `CDM_INFLUX_DB_PATH`
- YouTube API key: set `YOUTUBE_API_KEY` in your shell or in a `.env` file at the repository root
- Optional OAuth token for the captions API download route: `YOUTUBE_CAPTIONS_OAUTH_TOKEN`
- Optional YouTube override: set `youtube_channel_id` per channel in `config/channels.yml` to skip handle resolution
- Optional YouTube result limit: `YOUTUBE_MAX_RESULTS` (defaults to `10`)
- If `YOUTUBE_API_KEY` is not set, ingestion keeps using the bundled demo dataset
- Live transcript fetching is **disabled by default** (to avoid IP-blocking errors from cloud environments). Set `YOUTUBE_TRANSCRIPTS_ENABLED=true` in your `.env` or shell to enable it.
- Caption API calls are processed in batches with `YOUTUBE_CAPTION_BATCH_SIZE` (defaults to `10`)
- The fallback queue waits `YOUTUBE_TRANSCRIPT_FALLBACK_DELAY_SECONDS` seconds between `youtube-transcript-api` calls (defaults to `30`)
- Local RAG switch: `RAG_ENABLED=true`
- Ollama endpoint: `OLLAMA_BASE_URL` (defaults to `http://localhost:11434`)
- Ollama embedding model: `OLLAMA_EMBED_MODEL` (defaults to `nomic-embed-text`)
- Ollama chat model: `OLLAMA_CHAT_MODEL` (defaults to `llama3`)
- Chroma persistence path: `CDM_INFLUX_CHROMA_PATH` (defaults to `data/chroma`)

## Notes for future evolution

- **YouTube API integration**: the ingestion service already exposes clear TODO hooks where the real API client should be plugged in.
- **Ollama integration**: `app/extraction/llm.py` contains the extension point for local LLM enrichment.
- **FastAPI roadmap**: the `app/services` and `app/storage` layers are UI-agnostic so an internal API can be added with minimal changes.
