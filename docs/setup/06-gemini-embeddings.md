# Step 6: Gemini Embeddings

`gemini-embedding-001` is your embedding model. It converts raw text into 3072-dimensional vectors that Qdrant stores and searches over. It runs on Google's infrastructure, is free tier, and requires no local GPU.

The embedding code lives in `server/embeddings.py`, already written in step 3. This doc explains how it works, how to test it, and what to do if you want to swap it out later.

---

## How the free tier works

The Gemini API free tier for embeddings allows 10 million tokens per minute. At personal knowledge base ingestion volume — even aggressive ingestion of years of notes — you will not approach this limit.

The free tier logs prompts to Google for model improvement. Review Google's data usage policy if this is a concern for your use case.

---

## Task types

The Gemini embedding API accepts a `task_type` parameter that shapes the embedding toward a specific use case. Your server uses two:

| Task type | When used | Why |
|---|---|---|
| `retrieval_document` | Writing memories to Qdrant | Optimizes the vector for being found by queries |
| `retrieval_query` | Searching for memories | Optimizes the vector to match documents |

Using mismatched task types (querying with a document embedding or vice versa) will reduce recall quality. The `embed()` and `embed_query()` functions in `embeddings.py` handle this automatically.

---

## Testing embeddings

Confirm your Gemini API key is working:

```bash
source /opt/logios-brain/.env
python3 -c "
import google.generativeai as genai
genai.configure(api_key='$GEMINI_API_KEY')
result = genai.embed_content(
    model='models/text-embedding-004',
    content='Test memory about personal AI infrastructure',
    task_type='retrieval_document',
)
vector = result['embedding']
print(f'Embedding dimension: {len(vector)}')
print(f'First 5 values: {vector[:5]}')
"
```

Expected output:
```
Embedding dimension: 3072
First 5 values: [0.02341..., -0.01234..., ...]
```

---

## End-to-end write test

This tests the full write path: embed → store in Qdrant → write to Supabase:

```bash
source /opt/logios-brain/.env
cd /opt/logios-brain/server
python3 -c "
from tools.remember import remember
result = remember(
    content='Test memory: Logios Brain is now storing memories across Supabase, Qdrant, and Neo4j.',
    source='manual',
    metadata={'test': True},
)
print(result)
"
```

Expected output:
```json
{"memory_id": "some-uuid", "status": "stored", "source": "manual"}
```

Then verify it appeared in Supabase (Table Editor → memories) and in Qdrant (check vector count in the Cloud dashboard).

---

## Switching embedding models

The embedding model is configured in two places:

1. `server/embeddings.py` — the `MODEL` constant and the `genai.embed_content()` call
2. `server/db/qdrant.py` — the `EMBEDDING_DIM` constant

If you change models, you must update both and **recreate the Qdrant collection** with the new dimension. Mixing embedding dimensions in one collection will break search entirely.

To recreate the collection:
```python
client.delete_collection("memories")
ensure_collection()  # recreates with new EMBEDDING_DIM
```

This also means re-embedding all existing memories, since old vectors are incompatible with a new model.

### Alternative models

| Model | Dimension | Notes |
|---|---|---|
| `gemini-embedding-001` (current) | 3072 | Free, high quality, Google-hosted |
| `nomic-embed-text` via Ollama | 768 | Free, fully local, good quality |
| `bge-large-en-v1.5` via Ollama | 1024 | Free, fully local, strong English retrieval |
| `text-embedding-3-small` via OpenAI | 1536 | Paid, ~$0.02/1M tokens, commercially permissive |

To switch to a local model via Ollama on your local machine, change `embeddings.py` to call your Ollama endpoint instead of the Gemini API. Update `EMBEDDING_DIM` in `qdrant.py` to match the new model's output size.

---

**Next: [Skills and Evidence Layer](07-skills-evidence.md)**