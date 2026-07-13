"""Engram Python SDK — give any agent long-term memory in three lines.

    from engram import Engram

    em = Engram("http://localhost:8000")
    em.create_memory("Docker layers are cached by instruction order.")
    print(em.search("what did I learn about docker?")[0].content)
"""

from .client import Engram, EngramError, MemoryRecord, SearchHit

__all__ = ["Engram", "EngramError", "MemoryRecord", "SearchHit"]
__version__ = "0.1.0"
