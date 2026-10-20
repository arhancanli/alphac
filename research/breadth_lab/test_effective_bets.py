import numpy as np
import pandas as pd

from research.breadth_lab.effective_bets import idea_clusters, participation, report, weekly_corr

DAYS = pd.bdate_range("2000-01-03", periods=2000, tz="UTC")


def _noise(n: int, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).normal(0, 0.01, (len(DAYS), n))


def test_independent_series_count_fully_and_copies_count_once():
    x = _noise(5, 1)
    assert participation(np.corrcoef(x.T)) > 4.8
    copies = np.repeat(x[:, :1], 5, axis=1)
    assert participation(np.corrcoef(copies.T)) < 1.01


def test_sign_flips_do_not_add_ideas():
    x = _noise(4, 2)
    flipped = x * np.array([1, -1, 1, -1])
    assert abs(participation(np.corrcoef(x.T)) - participation(np.corrcoef(flipped.T))) < 1e-9


def test_many_sleeves_of_two_ideas_are_two_ideas():
    base = _noise(2, 3)
    cols, data = [], []
    for f in range(2):
        for k in range(10):
            cols.append(f"sig{f}|ind{k}")
            data.append(base[:, f] + 0.004 * _noise(1, 100 + 10 * f + k)[:, 0])
    sleeves = pd.DataFrame(np.array(data).T, index=DAYS, columns=cols)
    r = report(sleeves, {c: c.split("|")[0] for c in cols})
    assert r["sleeves"] == 20 and r["families"] == 2
    assert r["effective_bets_families"] > 1.9
    assert r["effective_bets_sleeves"] < 3
    assert r["ideas"] == 2


def test_correlated_families_join_into_one_idea():
    base = _noise(1, 4)[:, 0]
    books = pd.DataFrame({f"f{k}": base + 0.003 * _noise(1, 200 + k)[:, 0] for k in range(3)}, index=DAYS)
    books["other"] = _noise(1, 9)[:, 0]
    clusters = idea_clusters(weekly_corr(books), 0.5)
    assert sorted(map(sorted, clusters)) == [["f0", "f1", "f2"], ["other"]]
