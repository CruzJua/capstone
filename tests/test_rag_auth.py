"""HF credentials are passed to model loading without printing or persisting them."""
import importlib
import unittest
from unittest.mock import patch


class RAGAuthenticationTests(unittest.TestCase):
    def test_both_embedding_loaders_use_optional_environment_token(self):
        for module_name, class_name in (
            ('src.rag.retriever', 'RAGRetriever'),
            ('src.rag.ingestor', 'RAGDocumentIngestor'),
        ):
            module = importlib.import_module(module_name)
            for token in ('test-only-not-a-real-token', ''):
                with self.subTest(module=module_name, has_token=bool(token)), patch.dict(
                    'os.environ', {'HF_TOKEN': token, 'MONGODB_URI': 'mongodb://localhost:27017'}
                ), patch.object(module, 'load_dotenv'), patch.object(module, 'MongoClient'), patch.object(
                    module, 'SentenceTransformer'
                ) as model:
                    getattr(module, class_name)()
                    self.assertEqual(model.call_args.kwargs['token'], token or None)
