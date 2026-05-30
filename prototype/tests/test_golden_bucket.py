"""Golden Bucket retrieval (R1) with a deterministic offline embedder."""
from retail_agent.golden_bucket import GoldenBucket

_VOCAB = ["customer", "product", "revenue", "category", "brand"]


class FakeEmbeddings:
    """Bag-of-keywords embedder — deterministic, offline."""

    def embed_documents(self, texts):
        return [[float(t.lower().count(w)) for w in _VOCAB] for t in texts]

    def embed_query(self, text):
        return self.embed_documents([text])[0]


TRIOS = [
    {"id": "customers", "question": "who are our top customers", "sql": "s", "report": "r"},
    {"id": "products", "question": "best selling products by revenue", "sql": "s", "report": "r"},
    {"id": "categories", "question": "revenue by product category", "sql": "s", "report": "r"},
]


def _bucket(tmp_path):
    emb = FakeEmbeddings()
    return GoldenBucket(
        trios=TRIOS,
        embed_fn=emb.embed_documents,
        model_id="fake",
        cache_path=tmp_path / "emb.json",
    )


def test_retrieves_most_similar_trio(tmp_path):
    gb = _bucket(tmp_path)
    top = gb.retrieve("which customers spend the most", k=1)
    assert top[0]["id"] == "customers"


def test_top_k_ordering(tmp_path):
    gb = _bucket(tmp_path)
    top = gb.retrieve("product category revenue breakdown", k=3)
    assert {t["id"] for t in top[:2]} == {"categories", "products"}


def test_embeddings_are_cached(tmp_path):
    gb = _bucket(tmp_path)
    gb.retrieve("customers", k=1)
    assert (tmp_path / "emb.json").exists()
    # a fresh bucket reuses the cache (no re-embed needed to build the matrix)
    gb2 = _bucket(tmp_path)
    gb2.ensure_index()
    assert gb2._matrix is not None and gb2._matrix.shape[0] == len(TRIOS)


def test_stale_cache_is_ignored_on_model_change(tmp_path):
    _bucket(tmp_path).retrieve("customers", k=1)
    # different model id -> cache key mismatch -> rebuild rather than reuse
    gb = GoldenBucket(TRIOS, FakeEmbeddings().embed_documents, "different-model",
                      cache_path=tmp_path / "emb.json")
    assert gb._load_cache() is None
