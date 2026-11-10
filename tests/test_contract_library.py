"""Unit tests for Sentinel Contract Library (Upgrade B)."""
import pytest
from sentinel_core.contract_library import ContractLibrary


def test_contract_matching():
    # LRU Cache
    c1 = ContractLibrary.get_contract_for_goal("Implement an LRU cache data structure")
    assert c1 is not None
    assert "Sentinel Objective Contract: LRU Cache" in c1

    # Stack
    c2 = ContractLibrary.get_contract_for_goal("Build a stack data structure in Python")
    assert c2 is not None
    assert "Sentinel Objective Contract: Stack" in c2

    # Binary search
    c3 = ContractLibrary.get_contract_for_goal("Write a binary search algorithm in python")
    assert c3 is not None
    assert "Sentinel Objective Contract: Binary Search" in c3

    # Unmatched goal returns None gracefully
    c4 = ContractLibrary.get_contract_for_goal("Write a poem about cybersecurity")
    assert c4 is None
