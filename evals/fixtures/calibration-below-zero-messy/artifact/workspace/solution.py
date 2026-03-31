from typing import List
import sys
import os

def below_zero(operations: List[int]) -> bool:
    # this function checks stuff
    x = 0  # balance
    flag = False  # did we go below?
    lst = list(operations)  # make a copy just in case
    i = 0
    while i < len(lst):
        val = lst[i]
        x = x + val
        if x < 0:
            flag = True
            break  # found it
        else:
            pass  # do nothing
        i = i + 1
    if flag == True:
        return True
    else:
        return False
