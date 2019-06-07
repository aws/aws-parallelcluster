import collections

import pytest

from pcluster.utils import NumberedList


def inizialize_non_empty():
    return NumberedList(("a", "b", "c", "d", "e", "f"))


def ordered_dict():
    return collections.OrderedDict({1: "a", 2: "b", 3: "c"})


def test_empty():
    with pytest.raises(TypeError):
        assert NumberedList()


def test_iterable():
    using_tuple = NumberedList(("a", "b", "c"))
    assert using_tuple.get().items() == ordered_dict().items()
    using_list = NumberedList(["a", "b", "c"])
    assert using_list.get().items() == ordered_dict().items()


def test_value_errors():
    with pytest.raises(ValueError):
        assert inizialize_non_empty().get_item_by_index(-1)
        assert inizialize_non_empty().get_item_by_index("jon snow")
        assert inizialize_non_empty().get_item_by_index(0)
        assert inizialize_non_empty().get_item_by_index(7)


def test_order():
    using_tuple = NumberedList(("a", "c", "b"))
    assert using_tuple.get().items() != ordered_dict().items()


def test_defensive_copy():
    obj = inizialize_non_empty().get()
    obj[1] = "nothing should happen"
    assert inizialize_non_empty().get_item_by_index(1) == "a"


def test_size():
    assert len(inizialize_non_empty().get()) == 6
