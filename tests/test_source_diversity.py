"""
Tests for source-diversity enforcement in ranking.py.

These tests drive _enforce_source_diversity directly so they run without
any Ollama dependency.
"""

from __future__ import annotations

import pytest

from news_agent.processing.ranking import _enforce_source_diversity
from tests.conftest import make_ranked, make_story


def _make_setup(source_list: list[str]):
    """Build a (ranked, candidates, stories) triple from a source list."""
    stories = [
        make_story(f"T{i}", f"https://ex.com/{i}", source=src)
        for i, src in enumerate(source_list)
    ]
    candidates = [
        {"id": i, "title": s.title, "source": s.source, "summary": ""}
        for i, s in enumerate(stories)
    ]
    ranked = [make_ranked(id=i, score=10 - i) for i in range(len(stories))]
    return ranked, candidates, stories


class TestSourceDiversityDirect:
    def test_no_cap_when_diversity_is_fine(self):
        """A already-diverse list is returned unchanged."""
        ranked, candidates, stories = _make_setup(
            ["BBC", "CNN", "Reuters", "AP", "Al Jazeera"]
        )
        result = _enforce_source_diversity(ranked, candidates, stories)
        assert len(result) == 5

    def test_bbc_capped_at_two(self):
        """Three BBC stories → only the top 2 (by score) survive."""
        ranked, candidates, stories = _make_setup(
            ["BBC", "BBC", "BBC"]
        )
        result = _enforce_source_diversity(ranked, candidates, stories)
        bbc_count = sum(1 for r in result if stories[r.id].source == "BBC")
        assert bbc_count == 2

    def test_third_bbc_replaced_by_cnn(self):
        """The 3rd BBC story is evicted; CNN fills the slot."""
        ranked, candidates, stories = _make_setup(
            ["BBC", "BBC", "BBC", "CNN"]
        )
        result = _enforce_source_diversity(ranked, candidates, stories, top_n=4)
        ids = {r.id for r in result}
        # CNN story has id=3
        assert 3 in ids

    def test_all_same_source_capped_at_two(self):
        ranked, candidates, stories = _make_setup(["X"] * 6)
        result = _enforce_source_diversity(ranked, candidates, stories)
        assert len(result) == 2

    def test_preserves_score_order_within_source(self):
        """The two kept stories from the same source are the highest-scored ones."""
        ranked, candidates, stories = _make_setup(
            ["BBC", "BBC", "BBC"]
        )
        result = _enforce_source_diversity(ranked, candidates, stories)
        # ranked is sorted score desc (10, 9, 8); we should keep id=0 (score 10)
        # and id=1 (score 9), not id=2 (score 8)
        ids = {r.id for r in result}
        assert 0 in ids
        assert 1 in ids
        assert 2 not in ids

    def test_top_n_respected(self):
        """Output never exceeds top_n even if more diverse stories exist."""
        ranked, candidates, stories = _make_setup(
            ["A", "B", "C", "D", "E"]
        )
        result = _enforce_source_diversity(
            ranked, candidates, stories, top_n=3
        )
        assert len(result) <= 3

    def test_overflow_backfill_when_allowed(self):
        """When allow_overflow_backfill=True, overflow stories are used to reach top_n."""
        ranked, candidates, stories = _make_setup(["BBC"] * 8)
        result = _enforce_source_diversity(
            ranked, candidates, stories,
            max_per_source=2,
            top_n=6,
            allow_overflow_backfill=True,
        )
        assert len(result) == 6

    def test_dynamic_max_per_source_kept(self):
        """When max_per_source is higher (e.g. 5 for top 10), it allows more stories per source."""
        ranked, candidates, stories = _make_setup(["BBC"] * 5 + ["CNN"] * 5)
        result = _enforce_source_diversity(
            ranked, candidates, stories,
            max_per_source=5,
            top_n=10,
        )
        assert len(result) == 10
