# spaCy — Entity Preflight Extraction

## What spaCy Is

spaCy is a Python library for industrial-strength natural language processing. Unlike libraries that wrap LLMs or remote APIs, spaCy runs entirely locally and provides:

- **Tokenization** — segmentation of text into words and punctuation
- **Part-of-speech tagging** — VB, NN, DT, etc. per token
- **Dependency parsing** — syntactic tree structure (head, deprel)
- **Lemmatization** — base forms of words (run → run, ran → run)
- **Named Entity Recognition (NER)** — detection of spans like person names, organizations, locations
- **Sentence boundary detection** — splitting text into sentences
- **Rule-based matching** — pattern matching over token sequences

## spaCy vs. LLMs for NER

| | spaCy | LLM |
|---|---|---|
| Speed | ~1-5ms per document | 100-500ms+ per call |
| Cost | Free (local) | API costs / token |
| Infrastructure | Just the model file | Running model server |
| PERSON/GPE/ORG accuracy | Good | Excellent |
| Novel/rare entity types | Poor | Excellent |
| Relationships | None | Can extract |

**We use both.** The spaCy preflight runs first — it catches obvious PERSON and GPE entities quickly and cheaply. The LLM then focuses on harder things: Decisions, Concepts, Tools, and relationships between entities. This division of labor means the LLM does less work per extraction.

## The Language Model Problem

This is the most important thing to understand about spaCy:

**The `spacy` library alone cannot do NER. You need a trained model.**

Without a model, `spacy.load("en_core_web_sm")` raises `OSError`. The `en_core_web_sm` model is a separate ~12 MB download that contains:

- Trained权重 (weights for the statistical NER component)
- Vocabulary data
- Meta information

```
pip install spacy
python -m spacy download en_core_web_sm   # required for NER
```

This is why our `entity_preflight.py` uses lazy loading and graceful degradation — if the model isn't installed, spaCy extraction is skipped and the LLM handles everything.

### Model Sizes

| Model | Size | Vectors | NER | Notes |
|---|---|---|---|---|
| `en_core_web_sm` | ~12 MB | None | Yes | Our default — smallest |
| `en_core_web_md` | ~40 MB | 20k word vectors | Yes | Includes word vectors |
| `en_core_web_lg` | ~500 MB | 500k word vectors | Yes | Large vectors |
| `en_core_web_trf` | ~500 MB | Transformer-based | Yes | Best accuracy, GPU recommended |

The `sm` variant is sufficient for our use case — we only need entity spans, not word vectors.

### Declaring the Model as a Dependency

spaCy models are Python packages, but they aren't on PyPI. They can be installed via:

```bash
python -m spacy download en_core_web_sm
```

For reproducible environments, add the model to `pyproject.toml` using pip's direct reference:

```toml
[project]
dependencies = [
    "spacy>=3.8.0",
    "en-core-web-sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl",
]
```

**Important:** `uv sync` removes packages not declared in `pyproject.toml`. If you installed `en_core_web_sm` manually and then run `uv sync`, it will be removed and NER preflight will silently degrade. Always declare it explicitly.

## How spaCy Is Used in Logios Brain

```
memory content
    │
    ▼
┌─────────────────────┐
│  spaCy preflight     │  ← en_core_web_sm: PERSON, GPE (fast, deterministic)
│  entity_preflight.py │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  LLM extraction     │  ← Decision, Concept, Tool, relationships
│  task_extract_entities│  (slower, probabilistic, richer)
└─────────────────────┘
```

In `app/genai/entity_preflight.py`:

```python
nlp = spacy.load("en_core_web_sm")
doc = nlp(text)

for ent in doc.ents:
    if ent.label_ == "PERSON":
        label = "Person"
    elif ent.label_ in ("GPE", "LOC"):
        label = "Location"
    # ...
```

The preflight entities are merged with LLM entities via `merge_entities()`. Preflight wins on name collisions — deterministic extraction takes precedence over probabilistic LLM extraction for the same name.

## Graceful Degradation

The `_load_spacy()` function in `entity_preflight.py` handles missing models:

```python
def _load_spacy():
    try:
        import spacy
        try:
            return spacy.load("en_core_web_sm")
        except OSError:
            return None  # model not installed
    except ImportError:
        return None  # spacy not installed
```

If spaCy or the model is absent:
- `preflight_extract()` returns only dictionary-matched Tool entities
- No exception is raised
- LLM handles all entity extraction

Tests verify this: `test_spacy_failure_is_non_fatal` monkeypatches `_nlp` to a broken value and confirms Tool extraction still works.

## Entity Labels in en_core_web_sm

The model recognizes these entity types (not all are used in our pipeline):

| Label | Meaning | Used in Logios? |
|---|---|---|
| `PERSON` | People | Yes → mapped to `Person` |
| `ORG` | Companies, agencies | No (no `Organization` type in our schema) |
| `GPE` | Countries, cities, states | Yes → mapped to `Location` |
| `LOC` | Non-GPE locations | Yes → mapped to `Location` |
| `DATE` | Date expressions | No |
| `MONEY` | Monetary values | No |
| `LANGUAGE` | Any named language | No |
| `EVENT` | Named events | No |
| `WORK_OF_ART` | Titles of works | No |
| `LAW` | Named laws | No |
| `PRODUCT` | Products | No |
| `NORP` | Nationalities, religious groups | No |
| `FAC` | Buildings, airports, etc. | No |
| `WORK_OF_ART` | Titles of books, songs | No |

Our pipeline only maps PERSON and GPE/LOC from spaCy — other labels are silently skipped. This keeps the preflight fast and focused.

## Common Errors

### OSError: [E050] Can't find model en_core_web_sm

The model isn't installed. Install it:

```bash
python -m spacy download en_core_web_sm
```

Or add to `pyproject.toml` and run `uv sync`.

### Model version mismatch

spaCy models are versioned to match the spaCy release. `en_core_web_sm-3.8.0` requires `spacy>=3.8.0`. Mixing versions causes `OSError` on load.

When upgrading spaCy, re-download the model:

```bash
python -m spacy download en_core_web_sm
```

### uv sync removes the model

This happens when the model isn't in `pyproject.toml`. Add it as a direct pip URL dependency:

```toml
en-core-web-sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl
```

Then run `uv sync`.

## Further Reading

- [spaCy API documentation](https://spacy.io/api)
- [EntityRecognizer component](https://spacy.io/api/entityrecognizer)
- [Named entity recognition guide](https://spacy.io/usage/linguistic-features#named-entities)
- [Training custom NER models](https://spacy.io/usage/training#ner)
- [Rule-based matching with EntityRuler](https://spacy.io/api/entityruler)
