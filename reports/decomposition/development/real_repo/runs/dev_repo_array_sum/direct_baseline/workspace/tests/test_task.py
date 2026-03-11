import importlib


def test_sum_positive():
    task = importlib.import_module("calculator.task")
    assert task.solve([1, 2, 3]) == 6


def test_sum_negative():
    task = importlib.import_module("calculator.task")
    assert task.solve([-1, 1, 5]) == 5
