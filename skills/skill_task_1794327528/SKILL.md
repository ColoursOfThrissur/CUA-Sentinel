---
name: skill_task_1794327528
description: Auto-synthesized skill for: Write Python code implementing an LRU Cache data structure with get and put methods
version: 1
verified_at: 1794327554.6383002
effect_class: READ_ONLY
---
# skill_task_1794327528 (v1)
Auto-synthesized skill for: Write Python code implementing an LRU Cache data structure with get and put methods

## Parameters
```json
{}
```

## Implementation
```python
```python
from collections import OrderedDict


class LRUCache:
    """
    Least Recently Used (LRU) Cache implementation using OrderedDict.
    
    This cache maintains a fixed maximum size and evicts the least recently
    used items when the cache reaches capacity.
    
    Attributes:
        capacity (int): Maximum number of items the cache can hold.
    """
    
    def __init__(self, capacity: int) -> None:
        """
        Initialize the LRU Cache with a given capacity.
        
        Args:
            capacity: Maximum number of items the cache can store.
        """
        self.capacity = capacity
        self.cache = OrderedDict()
    
    def get(self, key: int) -> int | None:
        """
        Get an item from the cache by key.
        
        If the key
```
