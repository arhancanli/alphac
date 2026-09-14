import numpy as np
import pytest
from funded_inception_runner import InceptionSplitter


class Example:
    def split(self,grid):
        yield np.array([0,1]),np.array([2,3,4,5])
        yield np.array([4,5]),np.array([6,7,8,9])


def test_only_preinception_test_bars_removed_and_later_boundaries_preserved():
    a=list(InceptionSplitter(Example(),4).split(None))
    np.testing.assert_array_equal(a[0][0],[0,1])
    np.testing.assert_array_equal(a[0][1],[4,5])
    np.testing.assert_array_equal(a[1][0],[4,5])
    np.testing.assert_array_equal(a[1][1],[6,7,8,9])


def test_prehistory_only_leg_skipped():
    a=list(InceptionSplitter(Example(),6).split(None))
    assert len(a)==1
    np.testing.assert_array_equal(a[0][1],[6,7,8,9])


def test_singleton_failure_not_silently_merged():
    with pytest.raises(ValueError):list(InceptionSplitter(Example(),5).split(None))


def test_original_splitter_inputs_unchanged():
    source=Example();original=list(source.split(None));list(InceptionSplitter(source,4).split(None))
    for a,b in zip(original,source.split(None)):
        np.testing.assert_array_equal(a[0],b[0]);np.testing.assert_array_equal(a[1],b[1])
