"""Dry run of the indexer: files, chunks and tokens per worktree. Nothing is written.

It uses the indexer's own discovery, filters and chunkers, so the counts match what `index`
would store. Tokens use the harness estimate, (characters + 3) // 4. Vectors are keyed by
content hash and shared across projects, so `unique_tokens` is what the embedding model reads.

usage (from adk-rag-postgres-harness):
  uv run --no-sync python scripts/multi-repo/estimate.py WORKTREES_DIR [TOKENS_PER_SECOND]
"""

import csv
import sys
from collections import Counter
from pathlib import Path

from adk_rag_postgres_harness.ingest import INDEXED_EXTS, _inspect, _read_file
from rag_harness.indexer import discover_files

worktrees = Path(sys.argv[1])
rate = float(sys.argv[2]) if len(sys.argv) > 2 else None
with open(worktrees / "manifest.tsv", newline="") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))

seen: set[str] = set()
totals = Counter()
print(f"{'project':40} {'files':>6} {'chunks':>7} {'docs':>6} {'tokens':>10} {'unique':>10}  skipped")
for row in rows:
    root = Path(row["worktree"]).resolve()
    counts = Counter()
    skipped = Counter()
    for full in discover_files(str(root), INDEXED_EXTS):
        digest, reason = _inspect(root, full)
        if reason:
            skipped[reason.split(":")[0]] += 1
            continue
        indexed = _read_file(root, full, digest)
        counts["files"] += 1
        for chunk in indexed.chunks:
            tokens = (len(chunk.content) + 3) // 4
            counts["chunks"] += 1
            counts["docs"] += indexed.collection == "docs"
            counts["tokens"] += tokens
            if chunk.content_hash not in seen:
                seen.add(chunk.content_hash)
                counts["unique"] += tokens
    totals.update(counts)
    print(f"{row['project']:40} {counts['files']:6} {counts['chunks']:7} {counts['docs']:6} "
          f"{counts['tokens']:10} {counts['unique']:10}  {dict(skipped) or ''}", flush=True)

print(f"{'total':40} {totals['files']:6} {totals['chunks']:7} {totals['docs']:6} {totals['tokens']:10} {totals['unique']:10}")
# Measured on the pilot index: about 22 KB of database per chunk, vectors and indexes included.
print(f"estimated database size: {totals['chunks'] * 22 / 1024:.0f} MB")
if rate:
    print(f"estimated embedding time at {rate:g} tokens/s: {totals['unique'] / rate / 3600:.1f} h")
