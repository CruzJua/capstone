import os
import sys
import argparse
import json
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

# Load environment variables from project root .env
load_dotenv(project_root / ".env")

TENANT_MAPPINGS = {
    "cinder_and_salt": "data/cinder_and_salt",
    "harbor_view": "data/harbor_view",
    "iron_and_oak": "data/iron_and_oak",
    "kettle_and_loom": "data/kettle_and_loom",
    "northstar_auto": "data/northstar_auto"
}

def main():
    parser = argparse.ArgumentParser(description="Inspect document parsing offline; explicitly opt in to database ingestion.")
    parser.add_argument("--document-parser", choices=["legacy", "structured"], default="legacy")
    parser.add_argument("--tenant-dir", action="append", default=[], metavar="TENANT=PATH",
                        help="Explicit tenant directory; repeatable. Without this flag use project development tenant mappings.")
    parser.add_argument("--inspect-only", action="store_true", help="Inspect shared parsed blocks without MongoDB or embedding initialization.")
    parser.add_argument("--execute", action="store_true", help="Actually replace tenant vector documents; never enabled by inspection.")
    args = parser.parse_args()
    if args.inspect_only and args.execute:
        parser.error("Choose --inspect-only or --execute")
    mappings = dict(TENANT_MAPPINGS)
    if args.tenant_dir:
        mappings = {}
        for value in args.tenant_dir:
            tenant, separator, directory = value.partition("=")
            if not separator or not tenant.strip() or not directory.strip() or tenant in mappings:
                parser.error("--tenant-dir requires distinct TENANT=PATH entries")
            mappings[tenant] = directory
    if args.inspect_only:
        if args.document_parser != "structured":
            parser.error("--inspect-only requires --document-parser structured")
        from src.documents.integration import document_chunks, load_documents
        report = {"mode": "inspect_only", "network_calls": 0, "database_writes": 0,
                  "embedding_jobs": 0, "tenants": {}}
        for tenant, directory in mappings.items():
            base = Path(directory)
            if not base.is_absolute():
                base = project_root / base
            if not base.is_dir():
                parser.error(f"Tenant directory does not exist: {base}")
            blocks = []
            for document in load_documents(base).values():
                blocks.extend(document_chunks(document))
            report["tenants"][tenant] = blocks
        print(json.dumps(report, indent=4, ensure_ascii=False))
        return
    if not args.execute:
        parser.error("Use --inspect-only for offline parsing or --execute to authorize replacing tenant vectors")
    from src.rag.db_config import resolve_training_db_name
    from src.rag.ingestor import RAGDocumentIngestor
    mongo_uri = os.getenv("MONGODB_URI")
    if not mongo_uri or "<username>" in mongo_uri or "<password>" in mongo_uri:
        print("Error: MONGODB_URI is not configured with valid credentials.")
        print("Please edit the .env file in the project root and replace the placeholder credentials:")
        print("  MONGODB_URI=mongodb+srv://<username>:<password>@<cluster-url>/?retryWrites=true&w=majority")
        sys.exit(1)

    # The default mappings are the five development tenants, which belong in the training database.
    # Explicit --tenant-dir tenants (e.g. the held-out demo business) keep the production database.
    if args.tenant_dir:
        db_name = os.getenv("MONGODB_DB_NAME", "rag_knowledge_base")
    else:
        db_name = resolve_training_db_name()
    collection_name = os.getenv("MONGODB_COLLECTION_NAME", "doc_vectors")

    print(f"Connecting to MongoDB (database: '{db_name}', collection: '{collection_name}')...")
    ingestor = RAGDocumentIngestor(document_parser=args.document_parser, db_name=db_name)

    print("Verifying MongoDB Atlas Vector Search Index...")
    ingestor.ensure_vector_search_index()

    base_dir = project_root

    for tenant_id, folder_rel_path in mappings.items():
        tenant_path = base_dir / folder_rel_path
        if not tenant_path.exists():
            print(f"Skipping {tenant_id}: {tenant_path} not found.")
            continue

        print(f"Ingesting docs for tenant '{tenant_id}'...")
        count = ingestor.ingest_tenant_directory(tenant_id, tenant_path)
        print(f"Inserted {count} vector chunks for '{tenant_id}'.")

if __name__ == "__main__":
    main()
