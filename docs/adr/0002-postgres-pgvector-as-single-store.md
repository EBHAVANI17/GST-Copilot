# 2. PostgreSQL with pgvector as the single data store

Date: 2026-10-24
Status: Accepted

## Context

GST Copilot needs: vector similarity search over chunks, keyword (BM25-style)
search for exact identifiers like "16(2)(aa)" and notification numbers,
filtering by metadata such as effective dates, relational data (documents,
index versions, tenants, audit log) and transactions.

## Options considered

1. **PostgreSQL + pgvector + built-in full-text search.** One system for vectors,
   keywords, metadata and relational data.
2. **Dedicated vector database (Qdrant, Pinecone) + PostgreSQL.** Strong vector
   features, but two systems to run, sync and back up, and filters span both.
3. **Elasticsearch / OpenSearch.** Strong keyword search and vectors, heavier to
   operate, and still needs a relational store.

## Decision

Option 1. The corpus is thousands to tens of thousands of chunks, well within
pgvector's comfortable range with an HNSW index. One store keeps date filters,
hybrid search and joins in a single SQL query, and one backup covers everything.

## Consequences

- Hybrid search is written in SQL (vector query + full-text query, fused in code).
- If the corpus grows by orders of magnitude, revisit option 2; the retrieval
  code sits behind one interface so the store can be swapped.
