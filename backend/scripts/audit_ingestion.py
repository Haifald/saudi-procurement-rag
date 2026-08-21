"""Run the hybrid PDF/OCR ingestion audit without building embeddings."""

import sys

from app.ingest import load_and_build_docs, print_ingestion_report


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    documents = load_and_build_docs()
    print_ingestion_report(documents)
