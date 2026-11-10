"""Sentinel Contract Library (Upgrade B).
Provides objective, executable behavioral contracts that grade LLM solutions
without letting the model write its own test assertions.
"""
from __future__ import annotations

from typing import Optional


LRU_CACHE_CONTRACT = """
# Sentinel Objective Contract: LRU Cache
c = target_module.LRUCache(2)
assert c.get(1) in (-1, None), f"Empty cache get(1) must be -1 or None, got {c.get(1)}"
c.put(1, 100)
c.put(2, 200)
assert c.get(1) == 100, f"Expected 100 for key 1, got {c.get(1)}"
# Accessing key 1 makes it MRU. Next put must evict key 2!
c.put(3, 300)
assert c.get(2) in (-1, None), f"Key 2 should be evicted under capacity 2, got {c.get(2)}"
assert c.get(1) == 100, f"Key 1 should still exist, got {c.get(1)}"
assert c.get(3) == 300, f"Key 3 should exist, got {c.get(3)}"

# Update existing key without increasing size
c.put(1, 150)
assert c.get(1) == 150, f"Key 1 was not updated, got {c.get(1)}"

# Test capacity 1 edge case
c1 = target_module.LRUCache(1)
c1.put(10, 10)
assert c1.get(10) == 10
c1.put(20, 20)
assert c1.get(10) in (-1, None), "Key 10 should be evicted in capacity 1"
assert c1.get(20) == 20
"""

STACK_CONTRACT = """
# Sentinel Objective Contract: Stack
s = target_module.Stack()
assert s.is_empty() is True or getattr(s, 'is_empty', lambda: len(s) == 0)()
s.push(10)
s.push(20)
assert s.pop() == 20, "Stack must be LIFO"
assert s.pop() == 10
"""

BINARY_SEARCH_CONTRACT = """
# Sentinel Objective Contract: Binary Search
fn = getattr(target_module, 'binary_search', None) or getattr(target_module, 'search', None)
assert fn is not None, "Function binary_search not found"
arr = [1, 3, 5, 7, 9, 11]
assert fn(arr, 7) in (3, [3]), "Index of 7 must be 3"
assert fn(arr, 1) in (0, [0]), "Index of 1 must be 0"
assert fn(arr, 4) in (-1, None), "Missing element must return -1 or None"
"""


class ContractLibrary:
    """Manages domain contracts and matches user goals to objective test harnesses."""

    CONTRACT_MAP = {
        "lru": LRU_CACHE_CONTRACT,
        "cache": LRU_CACHE_CONTRACT,
        "stack": STACK_CONTRACT,
        "binary_search": BINARY_SEARCH_CONTRACT,
        "binary search": BINARY_SEARCH_CONTRACT,
    }

    @classmethod
    def get_contract_for_goal(cls, goal: str) -> Optional[str]:
        """Finds matching behavioral contract for a task goal."""
        lower_g = goal.lower()
        for kw, contract in cls.CONTRACT_MAP.items():
            if kw in lower_g:
                return contract
        return None
