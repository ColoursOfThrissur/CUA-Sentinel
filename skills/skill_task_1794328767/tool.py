from collections import OrderedDict


class LRUCache:
    """
    Least Recently Used (LRU) Cache implementation with fixed capacity.
    
    Maintains an ordered dictionary where keys are accessed in order of usage.
    When capacity is exceeded, the least recently used item is evicted.
    """

    def __init__(self, capacity: int) -> None:
        """
        Initialize the LRU cache with a given capacity.
        
        Args:
            capacity: Maximum number of items the cache can hold.
        """
        self.capacity = capacity
        self.cache: OrderedDict[int, str] = OrderedDict()

    def get(self, key: int) -> int | None:
        """
        Get value for a key from cache. If not found, return None.
        Moves accessed item to end (most recently used).
        
        Args:
            key: The key to retrieve.
            
        Returns:
            The value associated with the key, or None if not found.
        """
        if key in self.cache:
            # Move to end to mark as most recently used
            self.cache.move_to_end(key)
            return self.cache[key]
        return None

    def put(self, key: int, value: str) -> None:
        """
        Insert or update a key-value pair in the cache.
        Evicts least recently used item if capacity is exceeded.
        
        Args:
            key: The key to insert/update.
            value: The value to associate with the key.
        """
        if key in self.cache:
            # Update existing key and move to end
            self.cache.move_to_end(key)
            self.cache[key] = value
        else:
            # Add new key-value pair
            self.cache[key] = value
            # Evict least recently used if over capacity
            if len(self.cache) > self.capacity:
                self.cache.popitem(last=False)


def main() -> None:
    """
    Test the LRU Cache implementation with various scenarios.
    """
    # Test 1: Basic LRU eviction behavior
    cache = LRUCache(2)
    
    # Insert key 1
    cache.put(1, "first")
    assert cache.get(1) == "first", "Key 1 should exist"
    
    # Insert key 2
    cache.put(2, "second")
    assert cache.get(2) == "second", "Key 2 should exist"
    
    # Access key 1 to make it most recently used
    cache.get(1)
    assert cache.get(1) == "first", "Key 1 should still exist after access"
    
    # Insert key 3 - should evict key 2 (least recently used)
    cache.put(3, "third")
    assert cache.get(3) == "third", "Key 3 should exist"
    assert cache.get(2) is None, "Key 2 should be evicted"
    
    # Test 2: Key 1 should be evicted after key 3 is added
    cache.put(4, "fourth")
    assert cache.get(1) is None, "Key 1 should be evicted"
    assert cache.get(4) == "fourth", "Key 4 should exist"
    
    # Test 3: Edge case - capacity of 1
    cache2 = LRUCache(1)
    cache2.put(1, "one")
    assert cache2.get(1) == "one", "Key 1 should exist with capacity 1"
    cache2.put(2, "two")
    assert cache2.get(1) is None, "Key 1 should be evicted with capacity 1"
    assert cache2.get(2) == "two", "Key 2 should exist"
    
    # Test 4: Update existing key
    cache3 = LRUCache(3)
    cache3.put(1, "value1")
    cache3.put(2, "value2")
    cache3.put(3, "value3")
    assert cache3.get(1) == "value1", "Key 1 should exist"
    
    # Update key 1
    cache3.put(1, "updated_value1")
    assert cache3.get(1) == "updated_value1", "Key 1 should be updated"
    
    # Test 5: Empty cache
    cache4 = LRUCache(2)
    assert cache4.get(1) is None, "Empty cache should return None for any key"
    
    # Test 6: Capacity larger than items
    cache5 = LRUCache(5)
    cache5.put(1, "one")
    cache5.put(2, "two")
    assert cache5.get(1) == "one", "Key 1 should exist"
    assert cache5.get(2) == "two", "Key 2 should exist"
    
    # Test 7: Access pattern affects eviction order
    cache6 = LRUCache(3)
    cache6.put(1, "a")
    cache6.put(2, "b")
    cache6.put(3, "c")
    # Access 1 and 2 to make them recently used
    cache6.get(1)
    cache6.get(2)
    # Insert new item - should evict key 3 (least recently used)
    cache6.put(4, "d")
    assert cache6.get(3) is None, "Key 3 should be evicted"
    assert cache6.get(4) == "d", "Key 4 should exist"


if __name__ == "__main__":
    main()