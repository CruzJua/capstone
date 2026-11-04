import unittest

from src.rag.offline import InMemoryVectorCollection


def doc(tenant, doc_id, embedding):
    return {"tenant_id": tenant, "doc_id": doc_id, "text": doc_id, "section": "s", "embedding": embedding}


def pipeline(query, tenant, limit=5):
    return [{"$vectorSearch": {"index": "vector_index", "path": "embedding", "queryVector": query,
                               "numCandidates": 100, "limit": limit, "filter": {"tenant_id": {"$eq": tenant}}}}]


class InMemoryVectorCollectionTests(unittest.TestCase):
    def setUp(self):
        self.collection = InMemoryVectorCollection([
            doc("a", "close", [1.0, 0.0]),
            doc("a", "far", [0.0, 1.0]),
            doc("a", "opposite", [-1.0, 0.0]),
            doc("b", "other_tenant", [1.0, 0.0]),
        ])

    def test_orders_by_cosine_similarity(self):
        results = self.collection.aggregate(pipeline([1.0, 0.1], "a"))
        self.assertEqual([r["doc_id"] for r in results], ["close", "far", "opposite"])

    def test_scores_use_atlas_zero_to_one_scale(self):
        results = self.collection.aggregate(pipeline([1.0, 0.0], "a"))
        self.assertAlmostEqual(results[0]["score"], 1.0, places=5)
        self.assertAlmostEqual(results[-1]["score"], 0.0, places=5)

    def test_tenant_filter_excludes_other_tenants(self):
        results = self.collection.aggregate(pipeline([1.0, 0.0], "a"))
        self.assertNotIn("other_tenant", [r["doc_id"] for r in results])

    def test_limit_is_respected_and_embeddings_are_not_returned(self):
        results = self.collection.aggregate(pipeline([1.0, 0.0], "a", limit=1))
        self.assertEqual(len(results), 1)
        self.assertNotIn("embedding", results[0])

    def test_unknown_tenant_returns_nothing(self):
        self.assertEqual(self.collection.aggregate(pipeline([1.0, 0.0], "missing")), [])


if __name__ == "__main__":
    unittest.main()
