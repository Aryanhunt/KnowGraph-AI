"""
Backfill missing confidence / verification_status on relation edges.

Some relation documents in the ``concept_relations`` collection were written
by an older pipeline version that did not store top-level ``confidence`` or
``verification_status`` fields.  MongoDB's ``{"confidence": {"$gte": 0.0}}``
query silently excludes those documents, so the "All" graph view returned
zero edges.

This script is idempotent: it only touches documents that are missing the
field, and recomputes the deterministic value using the *current* logic in
``models/graph.py`` (so it stays in sync with the code).

Usage:
    cd backend
    .venv/bin/python ../scripts/backfill_relation_metadata.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running from anywhere inside the repo
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from db.study_repositories import RelationRepository  # noqa: E402
from models.graph import (  # noqa: E402
    default_relation_confidence,
    verification_for_method,
)


def backfill() -> None:
    repo = RelationRepository()
    collection = repo.collection

    # Find docs that are missing either field (older writes skipped them).
    cursor = collection.find({
        "$or": [
            {"confidence": {"$exists": False}},
            {"verification_status": {"$exists": False}},
        ]
    })

    updated = 0
    skipped = 0
    for doc in cursor:
        method = doc.get("method", "cooccurrence")
        evidence = doc.get("evidence", [])

        confidence = default_relation_confidence(method, evidence)
        verification_status = doc.get("verification_status") or verification_for_method(method)

        updates: dict = {
            "$set": {
                "confidence": round(float(confidence), 2),
                "verification_status": verification_status,
            }
        }

        # Backfill evidence-array elements too, so the edge-inspector can
        # show the right badge without re-deriving everything at read time.
        needs_evidence_fix = False
        for item in evidence:
            if "confidence" not in item or "verification_status" not in item:
                item["confidence"] = round(float(confidence), 2)
                item["verification_status"] = verification_status
                needs_evidence_fix = True
        if needs_evidence_fix:
            updates["$set"]["evidence"] = evidence

        result = collection.update_one({"_id": doc["_id"]}, updates)
        if result.modified_count:
            updated += 1
        else:
            skipped += 1

    print(f"Updated {updated} relation documents.")
    if skipped:
        print(f"  {skipped} matched but no fields changed (already current).")


if __name__ == "__main__":
    backfill()
