from solution import below_zero


def test_empty():
    assert below_zero([]) == False

def test_all_positive():
    assert below_zero([1, 2, 3]) == False

def test_goes_below():
    assert below_zero([1, 2, -4, 5]) == True

def test_touches_zero():
    assert below_zero([1, 2, -3, 1, 2, -3]) == False

def test_immediate_negative():
    assert below_zero([-1, 2, 3]) == True

def test_deep_negative():
    assert below_zero([1, -1, 2, -2, 5, -5, 4, -5]) == True
