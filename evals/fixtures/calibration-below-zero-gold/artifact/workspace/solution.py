from typing import List


def below_zero(operations: List[int]) -> bool:
    """Detect if bank account balance falls below zero.

    Args:
        operations: List of deposit (positive) and withdrawal (negative) amounts.

    Returns:
        True if balance goes below zero at any point, False otherwise.
    """
    balance = 0
    for op in operations:
        balance += op
        if balance < 0:
            return True
    return False
