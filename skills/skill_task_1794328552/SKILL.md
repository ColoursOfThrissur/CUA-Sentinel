---
name: skill_task_1794328552
description: Auto-synthesized skill for: Write Python code implementing an LRU Cache data structure with get and put methods and assert tests
version: 1
verified_at: 1794328594.2718947
effect_class: READ_ONLY
---
# skill_task_1794328552 (v1)
Auto-synthesized skill for: Write Python code implementing an LRU Cache data structure with get and put methods and assert tests

## Parameters
```json
{}
```

## Implementation
```python
from collections import OrderedDict


class LRUCache:
    """
    Least Recently Used (LRU) Cache implementation using OrderedDict.
    
    Attributes:
        capacity (int): Maximum number of items the cache can hold.
    
    Methods:
        get(key): Returns value for key if exists, else -1.
        put(key, value): Inserts or updates key-value pair, evicts LRU item if needed.
    """
    
    def __init__(self, capacity: int) -> None:
        """
        Initialize the LRU cache with given capacity.
        
        Args:
            capacity: Maximum number of items in cache (must be >= 0).
        """
        self.capacity = capacity
        self.cache = OrderedDict()
    
    def get(self, key: int) -> int:
        """
        Get value for key if it exists in cache.
        
        Args:
            key: Key to retrieve from cache.
            
        Returns:
            Value associated with key, or -1 if not found.
        """
        if key not in self.cache:
            return -1
        
        # Move accessed item to end (most recently used)
        value = self.cache.pop(key)
        self.cache[key] = value
        return value
    
    def put(self, key: int, value: int) -> None:
        """
        Insert or update key-value pair in cache.
        
        If cache exceeds capacity, remove the least recently used item.
        
        Args:
            key: Key to insert/update.
            value: Value to associate with key.
        """
        if key in self.cache:
            # Update existing key and move to end (most recently used)
            self.cache.pop(key)
        
        self.cache[key] = value
        
        # Evict LRU item if capacity exceeded
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)


def main():
    """Test the LRU Cache implementation with various cases."""
    
    # Test 1: Basic get and put operations
    cache = LRUCache(2)
    assert cache.get(1) == -1, "Empty cache should return -1"
    cache.put(1, 1)
    assert cache.get(1) == 1, "Should return value for existing key"
    
    # Test 2: Put with same key (update)
    cache.put(2, 2)
    assert cache.get(1) == -1, "LRU item should be evicted"
    assert cache.get(2) == 2, "Should return value for second key"
    
    # Test 3: Capacity of 1
    cache = LRUCache(1)
    cache.put(1, 1)
    assert cache.get(1) == 1, "Should return value"
    cache.put(2, 2)
    assert cache.get(1) == -1, "First item should be evicted"
    assert cache.get(2) == 2, "Second item should exist"
    
    # Test 4: Empty capacity edge case
    cache = LRUCache(0)
    assert cache.get(1) == -1, "Empty cache should return -1"
    cache.put(1, 1)
    assert cache.get(1) == -1, "Item should be evicted immediately"
    
    # Test 5: Large capacity
    cache = LRUCache(3)
    cache.put(1, 1)
    cache.put(2, 2)
    cache.put(3, 3)
    assert cache.get(1) == 1, "Should return value"
    assert cache.get(2) == 2, "Should return value"
    assert cache.get(3) == 3, "Should return value"
    
    # Test 6: Accessing middle item makes it most recent
```
