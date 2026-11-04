import unittest

from src.rag.retriever import BGE_QUERY_PREFIX, RAGRetriever


class FakeModel:
    def __init__(self):
        self.encoded = []

    def encode(self, text):
        self.encoded.append(text)
        return _Vector()


class _Vector:
    def tolist(self):
        return [0.0, 0.0]


class FakeCollection:
    def __init__(self, docs):
        self.docs = docs
        self.pipeline = None

    def aggregate(self, pipeline):
        self.pipeline = pipeline
        return list(self.docs)


class FakeReranker:
    def __init__(self, scores_by_text):
        self.scores_by_text = scores_by_text

    def predict(self, pairs):
        return [self.scores_by_text[text] for _, text in pairs]


def make_retriever(docs, reranker=None, min_score=None):
    retriever = RAGRetriever.__new__(RAGRetriever)
    retriever.model = FakeModel()
    retriever.collection = FakeCollection(docs)
    retriever.index_name = "vector_index"
    retriever.query_prefix = BGE_QUERY_PREFIX
    retriever.reranker_model_name = "fake-reranker" if reranker else None
    retriever.rerank_candidates = 20
    retriever.min_rerank_score = min_score
    retriever._reranker = reranker
    return retriever


def doc(text, doc_id, score=0.9):
    return {"tenant_id": "t1", "text": text, "doc_id": doc_id, "section": "s", "score": score}


class RetrieverRerankTests(unittest.TestCase):
    def test_query_gets_bge_prefix(self):
        retriever = make_retriever([doc("a", "d1")])
        retriever.retrieve("hello", "t1")
        self.assertEqual(retriever.model.encoded, [BGE_QUERY_PREFIX + "hello"])

    def test_rerank_reorders_by_cross_encoder_score(self):
        docs = [doc("low", "d1", 0.95), doc("high", "d2", 0.80)]
        reranker = FakeReranker({"low": -9.0, "high": 3.0})
        results = make_retriever(docs, reranker).retrieve("q", "t1", top_k=2)
        self.assertEqual([r["text"] for r in results], ["high", "low"])
        self.assertEqual(results[0]["vector_score"], 0.80)

    def test_cutoff_drops_irrelevant_chunks_and_can_return_empty(self):
        docs = [doc("a", "d1"), doc("b", "d2")]
        reranker = FakeReranker({"a": -9.0, "b": -11.0})
        self.assertEqual(make_retriever(docs, reranker, min_score=-5.0).retrieve("q", "t1"), [])

    def test_cutoff_keeps_relevant_chunks(self):
        docs = [doc("a", "d1"), doc("b", "d2")]
        reranker = FakeReranker({"a": 2.0, "b": -11.0})
        results = make_retriever(docs, reranker, min_score=-5.0).retrieve("q", "t1")
        self.assertEqual([r["text"] for r in results], ["a"])

    def test_rerank_widens_candidate_fetch_and_keeps_tenant_filter(self):
        retriever = make_retriever([doc("a", "d1")], FakeReranker({"a": 1.0}))
        retriever.retrieve("q", "t1", top_k=4)
        stage = retriever.collection.pipeline[0]["$vectorSearch"]
        self.assertGreaterEqual(stage["limit"], 20)
        self.assertEqual(stage["filter"], {"tenant_id": {"$eq": "t1"}})

    def test_other_tenant_chunks_are_never_returned(self):
        foreign = {**doc("x", "d9"), "tenant_id": "t2"}
        reranker = FakeReranker({"a": 1.0})
        results = make_retriever([doc("a", "d1"), foreign], reranker).retrieve("q", "t1")
        self.assertEqual([r["text"] for r in results], ["a"])

    def test_without_reranker_behavior_is_unchanged(self):
        results = make_retriever([doc("a", "d1"), doc("b", "d2")]).retrieve("q", "t1")
        self.assertEqual([r["text"] for r in results], ["a", "b"])
        self.assertNotIn("rerank_score", results[0])


if __name__ == "__main__":
    unittest.main()
