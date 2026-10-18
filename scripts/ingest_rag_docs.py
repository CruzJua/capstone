import os
import sys
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

# Load environment variables from project root .env
load_dotenv(project_root / ".env")

from src.rag.ingestor import RAGDocumentIngestor

TENANT_MAPPINGS = {
    "cinder_and_salt": "data/cinder_and_salt",
    "harbor_view": "data/harbor_view",
    "iron_and_oak": "data/iron_and_oak",
    "kettle_and_loom": "data/kettle_and_loom",
    "northstar_auto": "data/northstar_auto"
}

def main():
    mongo_uri = os.getenv("MONGODB_URI")
    if not mongo_uri or "<username>" in mongo_uri or "<password>" in mongo_uri:
        print("Error: MONGODB_URI is not configured with valid credentials.")
        print("Please edit the .env file in the project root and replace the placeholder credentials:")
        print("  MONGODB_URI=mongodb+srv://<username>:<password>@<cluster-url>/?retryWrites=true&w=majority")
        sys.exit(1)

    db_name = os.getenv("MONGODB_DB_NAME", "rag_knowledge_base")
    collection_name = os.getenv("MONGODB_COLLECTION_NAME", "doc_vectors")

    print(f"Connecting to MongoDB (database: '{db_name}', collection: '{collection_name}')...")
    ingestor = RAGDocumentIngestor()

    print("Verifying MongoDB Atlas Vector Search Index...")
    ingestor.ensure_vector_search_index()

    base_dir = project_root

    for tenant_id, folder_rel_path in TENANT_MAPPINGS.items():
        tenant_path = base_dir / folder_rel_path
        if not tenant_path.exists():
            print(f"Skipping {tenant_id}: {tenant_path} not found.")
            continue

        print(f"Ingesting docs for tenant '{tenant_id}'...")
        count = ingestor.ingest_tenant_directory(tenant_id, tenant_path)
        print(f"Inserted {count} vector chunks for '{tenant_id}'.")

if __name__ == "__main__":
    main()