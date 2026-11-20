# Area Copilot — business context for agents
# (area spreadsheets, documents and data; engine: rag_harness)

import os
import sys

# The engine lives in ../rag-harness (sibling directory)
_RAG_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "rag-harness"))
if _RAG_ROOT not in sys.path:
    sys.path.insert(0, _RAG_ROOT)