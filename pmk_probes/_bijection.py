"""
A simple implementation of a bijection, which can be thought of as a
bidirectional ``dict``.
Author: Jared Lumpe
"""

from collections.abc import MutableMapping


class Bijection(set):
    """A bijection between two (mathematical) sets, labeled "left" and "right".
	Implements the ``Set`` interface as a collection of
	``(left, right)`` pairs.
	:param items: A collection of ``(left, right)`` pairs (could be another
		:class:`.Bijection`) or a ``dict`` with unique values that will be
		used as the ``left-->right`` mapping.
	.. attribute:: left
		:class:`.BijectionMap` from left set to right.
	.. attribute:: right
		:class:`.BijectionMap` from right set to left.
	"""

    def __init__(self, items=None):

        self.left = BijectionMap()
        self.right = BijectionMap(self.left)
        self.left.other = self.right

        if items is not None:
            if isinstance(items, dict):
                items = items.items()

            for litem, ritem in items:
                self.left[litem] = ritem

    def __len__(self):
        return len(self.left)

    def __iter__(self):
        return self.left.iteritems()

    def __contains__(self, value):
        if not isinstance(value, tuple) or len(value) != 2:
            return False

        lvalue, rvalue = value
        try:
            return self.left[lvalue] == rvalue
        except (KeyError):
            return False

    def __eq__(self, other):
        return isinstance(other, Bijection) and self.left._dict == other.left._dict

    def __repr__(self):
        return '{}({})'.format(type(self).__name__, repr(list(self)))


class BijectionMap(MutableMapping):
    """Mapping from one set of a :class:`.Bijection` to another.
	Shouldn't be used on its own.
	"""

    def __init__(self, other=None):
        self.other = other
        self._dict = dict()

    def __len__(self):
        return len(self._dict)

    def __contains__(self, value):
        return value in self._dict

    def __iter__(self):
        return iter(self._dict)

    def __getitem__(self, key):
        return self._dict[key]

    def __setitem__(self, key, value):
        # Check that we are not creating a duplicate in the other side
        try:
            back = self.other[value]
        except KeyError:
            pass
        else:
            if back != key:
                raise KeyError('Value already exists for another key.')

        self._dict[key] = value
        self.other._dict[value] = key

    def __delitem__(self, key):
        value = self._dict[key]
        del self._dict[key]
        del self.other._dict[value]

    def __repr__(self):
        return '{}({})'.format(type(self).__name__, repr(self._dict))
