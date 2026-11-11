---
name: skill_task_1794328360
description: Auto-synthesized skill for: Write Python code implementing an LRU Cache data structure with get and put methods
version: 1
verified_at: 1794328391.6446805
effect_class: READ_ONLY
---
# skill_task_1794328360 (v1)
Auto-synthesized skill for: Write Python code implementing an LRU Cache data structure with get and put methods

## Parameters
```json
{}
```

## Implementation
```python
"""
LRU Cache Implementation

A Least Recently Used (LRU) Cache data structure that evicts the least 
recently accessed items when capacity is reached.

Time Complexity:
    - get(): O(1)
    - put(): O(1)

Space Complexity: O(capacity)
"""

from collections import OrderedDict
from typing import Any, Optional


class LRUCache:
    """
    A cache that stores key-value pairs and evicts the least recently used 
    item when capacity is reached.
    
    Attributes:
        capacity (int): Maximum number of items the cache can hold.
    """

    def __init__(self, capacity: int) -> None:
        """
        Initialize the LRU Cache with a given capacity.

        Args:
            capacity: Maximum number of items the cache can store.
                      Must be a positive integer.
        """
        if capacity <= 0:
            raise ValueError("Capacity must be a positive integer.")
        
        self.capacity = capacity
        self.cache: OrderedDict[Any, Any] = OrderedDict()

    def get(self, key: Any) -> Optional[Any]:
        """
        Get an item from the cache by key.
        
        If the key exists, move it to the end (most recently used).
        If the key doesn't exist, return None.

        Args:
            key: The key to retrieve from the cache.

        Returns:
            The value associated with the key, or None if not found.
        """
        if key in self.cache:
            # Move accessed item to end (most recently used)
            self.cache.move_to_end(key)
            return self.cache[key]
        return None

    def put(self, key: Any, value: Any) -> None:
        """
        Put a key-value pair into the cache.
        
        If the key already exists, update its value and move to end.
        If the cache is at capacity, evict the least recently used item.

        Args:
            key: The key to store in the cache.
            value: The value to associate with the key.
        """
        if key in self.cache:
            # Update existing key and move to end
            self.cache.move_to_end(key)
            self.cache[key] = value
        else:
            # Add new key-value pair
            self.cache[key] = value
            
            # Evict least recently used item if at capacity
            if len(self.cache) > self.capacity:
                # Remove the first item (least recently used)
                oldest_key, _ = self.cache.popitem(last=False)
                del self.cache[oldest_key]


def main() -> None:
    """
    Example usage of the LRU Cache.
    """
    # Create cache with capacity of 2
    cache = LRUCache(capacity=2)

    # Put items in cache
    cache.put(1, "first")
    cache.put(2, "second")
    
    print(f"get(1): {cache.get(1)}")  # Output: first
    print(f"get(2): {cache.get(2)}")  # Output: second
    
    # Access key 1 (makes it most recently used)
    cache.get(1)
    
    # Put a new item - should evict key 2
    cache.put(3, "third")
    
    print(f"get(1): {cache.get(1)}")  # Output: first
    print(f"get(2): {cache.get(2)}")  # Output: None (evicted)
    print(f"get(3): {cache.get(3)}")  # Output: third
    
    # Update existing key
    cache.put(1, "updated_first")
    
    print(f"get(1): {cache.get(1)}")  # Output: updated_first


if __name__ == "__main__":
    main()
```
