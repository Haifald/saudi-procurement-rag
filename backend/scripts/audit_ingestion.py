"""Run the hybrid PDF/OCR ingestion audit without building embeddings."""

import sys
from pathlib import Path


# Running this file directly sets sys.path to backend/scripts. Add backend so
# the existing app package can be imported from the documented working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingest import load_and_build_docs, print_ingestion_report


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    documents = load_and_build_docs()
    print_ingestion_report(documents)
