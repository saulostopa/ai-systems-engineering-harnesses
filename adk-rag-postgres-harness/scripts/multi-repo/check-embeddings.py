"""Check that this machine's embedder matches the vectors stored in DATABASE_URL.

An index built on one machine is searched with query vectors from another. The model ID alone
does not prove they match: the same Ollama tag can point to other weights. This script embeds a
sample of stored chunks again and compares the cosine of each pair.

usage (from adk-rag-postgres-harness):
  uv run --no-sync python scripts/multi-repo/check-embeddings.py [--sample 20] [--min-cosine 0.99]
"""

import argparse
import json
import math
import sys

from adk_rag_postgres_harness.embeddings import embed_texts, embedder_id, memory_embedder
from adk_rag_postgres_harness.store import PostgresStore

parser = argparse.ArgumentParser()
parser.add_argument("--sample", type=int, default=20)
parser.add_argument("--min-cosine", type=float, default=0.99)
args = parser.parse_args()

embedder = memory_embedder()
model = embedder_id(embedder)
with PostgresStore().connect() as conn:
    rows = conn.execute(
        """
        SELECT DISTINCT ON (c.content_hash) c.content, e.embedding::text AS embedding
        FROM chunks c JOIN embeddings e ON e.content_hash = c.content_hash AND e.model = %s
        ORDER BY c.content_hash
        LIMIT %s
        """,
        (model, args.sample),
    ).fetchall()
if not rows:
    sys.exit(f"no stored vectors for {model}: is DATABASE_URL the right database and the model the same?")

fresh = embed_texts(embedder, [row["content"] for row in rows])


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


scores = [cosine(json.loads(row["embedding"]), vector) for row, vector in zip(rows, fresh)]
print(f"{model}: {len(scores)} chunks, cosine min {min(scores):.4f}, mean {sum(scores) / len(scores):.4f}")
if min(scores) < args.min_cosine:
    sys.exit(f"below {args.min_cosine}: this machine's embedder does not match the index")
print("compatible")
