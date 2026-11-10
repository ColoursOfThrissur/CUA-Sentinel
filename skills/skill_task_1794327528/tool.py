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