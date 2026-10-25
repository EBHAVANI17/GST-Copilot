# 3. Embedding model, LLM access and baseline retrieval

Date: 2026-10-24
Status: Accepted

## Context

M1 needs embeddings for chunks and questions, an LLM to write answers, and a first
retrieval method. We need a baseline we can measure before improving anything.

## Decisions

1. **Embeddings: BAAI/bge-small-en-v1.5 through fastembed, run locally.**
   384 dimensions, small, runs on CPU without PyTorch, free. Hidden behind an
   `Embedder` interface so an API model can be compared later. A deterministic
   `FakeEmbedder` (word hashing) is used in tests and CI so they need no download.
2. **LLM: any OpenAI-compatible chat API**, configured with `LLM_BASE_URL`,
   `LLM_MODEL` and `LLM_API_KEY`. One client works with Ollama (local, free) and
   hosted providers. With no LLM configured, `/ask` returns passages only
   ("retrieval-only mode"), which is also how retrieval is evaluated on its own.
3. **Baseline retrieval: fixed-size character chunks (1,200 chars, 200 overlap) and
   pure vector search with an HNSW index.** Deliberately simple. M2 adds
   structure-aware chunks, keyword search and reranking, and the golden set shows
   the gain of each.
4. **Citations are checked, not trusted.** Every passage gets a tag
   (`DOC-ID#chunk`); answers must cite tags; tags the model invents are reported
   as `invalid_citations`.

## Options rejected

- sentence-transformers locally: needs PyTorch, a much larger Docker image.
- A framework (LangChain, LlamaIndex) for M1: hides the steps we want to measure
  and explain. Can be revisited where it clearly saves work.

## Consequences

- The vector column is fixed at 384 dimensions. Changing the model to one with a
  different size needs a migration and re-ingestion.
- The first run downloads about 130 MB of model files (cached in a Docker volume).
