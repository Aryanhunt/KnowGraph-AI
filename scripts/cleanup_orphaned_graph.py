"""One-off maintenance: remove graph and analytics leftovers from deleted material.

Run from the project root with the project venv:

    cd backend
    .venv/bin/python ../scripts/cleanup_orphaned_graph.py [--user-id <id>] [--dry-run]

It deletes:
* concepts whose ``document_ids`` is empty (nodes that point at no document),
* relations with an empty ``evidence`` array (edges that point at no document),
* ``quiz_answer`` / ``flashcard_review`` study events that carry no
  ``document_ids`` — they are the reason topics kept showing up in Analytics
  (knowledge gaps / all topics) after every document was deleted.

With ``--user-id`` only that user's data is touched; otherwise every user's.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from config.settings import get_settings  # noqa: E402
from db.mongo import COLLECTIONS, init_mongo  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Purge graph/analytics orphans left by deleted documents.")
    parser.add_argument("--user-id", default=None, help="restrict cleanup to one user")
    parser.add_argument("--dry-run", action="store_true", help="only report what would be deleted")
    args = parser.parse_args()

    db = init_mongo(get_settings()).connect()
    match_user = {"user_id": str(args.user_id)} if args.user_id else {}

    live_docs = [str(d["_id"]) for d in db[COLLECTIONS["documents"]].find({}, {"_id": 1})]

    # Concepts whose every document reference is dead (documents deleted before
    # the cascade existed) — the "ghost nodes" case.
    dead_concept_ids, dead_slugs = [], set()
    for concept in db[COLLECTIONS["concepts"]].find(match_user, {"_id": 1, "slug": 1, "document_ids": 1}):
        if not any(str(item) in live_docs for item in concept.get("document_ids", [])):
            dead_concept_ids.append(concept["_id"])
            dead_slugs.add(concept["slug"])

    # Relations whose evidence points only at dead documents, or whose source
    # or target concept is gone.
    dead_relations = {
        **match_user,
        "$or": [
            {"evidence": {"$in": [None, []]}},
            {"evidence": {"$not": {"$elemMatch": {"document_id": {"$in": live_docs}}}}},
            {"source_slug": {"$in": list(dead_slugs)}},
            {"target_slug": {"$in": list(dead_slugs)}},
        ],
    }

    jobs = [
        (f"concepts (dead document refs: {len(dead_concept_ids)})", None, dead_concept_ids),
        (COLLECTIONS["concept_relations"], dead_relations, None),
        # study events recorded before document_ids was stored
        (
            COLLECTIONS["study_events"],
            dict(
                match_user,
                event_type={"$in": ["quiz_answer", "flashcard_review"]},
                document_ids={"$in": [None, []]},
            ),
            None,
        ),
    ]

    for name, query, ids in jobs:
        if ids is not None:
            collection = db[COLLECTIONS["concepts"]]
            count = len(ids)
            if args.dry_run:
                print(f"[dry-run] {name}: would delete {count} document(s)")
                continue
            result = collection.delete_many({"_id": {"$in": ids}})
            print(f"{name}: deleted {result.deleted_count} document(s)")
            continue
        collection = db[name]
        count = collection.count_documents(query)
        if args.dry_run:
            print(f"[dry-run] {name}: would delete {count} document(s)")
        else:
            result = collection.delete_many(query)
            print(f"{name}: deleted {result.deleted_count} document(s)")


if __name__ == "__main__":
    main()
