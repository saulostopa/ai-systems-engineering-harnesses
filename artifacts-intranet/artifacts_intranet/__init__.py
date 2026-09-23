# Artifacts intranet — RAG search over what the harness generated.

import os
import sys

# RAG engine: sibling directories (rag-harness and area-copilot)
_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
for pkg in ("rag-harness", "area-copilot"):
    p = os.path.join(_REPO, pkg)
    if p not in sys.path:
        sys.path.insert(0, p)