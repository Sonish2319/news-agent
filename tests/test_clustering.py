"""
Tests for event clustering (processing/clustering.py).
"""

from __future__ import annotations

import pytest

from news_agent.processing.clustering import cluster_stories
from tests.conftest import make_story


class TestClustering:
    def test_empty_list_returns_empty(self, fake_settings):
        assert cluster_stories([]) == []

    def test_distinct_stories_all_kept(self, fake_settings):
        stories = [
            make_story("Nepal earthquake kills dozens", "https://ex.com/1"),
            make_story("India launches Mars mission", "https://ex.com/2"),
            make_story("UK election results confirmed", "https://ex.com/3"),
        ]
        result = cluster_stories(stories)
        assert len(result) == 3

    def test_near_duplicate_titles_merged(self, fake_settings):
        """Two very similar headlines → only one representative kept."""
        stories = [
            make_story("Nepal earthquake kills dozens in Kathmandu", "https://ex.com/1"),
            make_story("Nepal earthquake kills dozens in Kathmandu!", "https://ex.com/2"),
        ]
        result = cluster_stories(stories)
        assert len(result) == 1

    def test_first_occurrence_is_representative(self, fake_settings):
        """The first story in the input is chosen as the cluster representative."""
        s1 = make_story("Nepal quake kills dozens", "https://ex.com/1")
        s2 = make_story("Nepal quake kills dozens today", "https://ex.com/2")

        result = cluster_stories([s1, s2])
        assert result[0].url == s1.url

    def test_different_sources_same_event_merged(self, fake_settings):
        """Same event from different sources should be clustered."""
        stories = [
            make_story("Major flood hits southern Nepal", "https://bbc.com/1", source="BBC"),
            make_story("Major flood hits southern Nepal", "https://kpost.com/2", source="KPost"),
        ]
        result = cluster_stories(stories)
        assert len(result) == 1

    def test_threshold_controls_aggressiveness(self, fake_settings):
        """A high threshold (1.0) only merges exact titles."""
        stories = [
            make_story("Nepal quake kills dozens", "https://ex.com/1"),
            make_story("Nepal quake kills dozens of people", "https://ex.com/2"),
        ]
        # Threshold=1.0 means only exact matches merge → both kept
        result = cluster_stories(stories, threshold=1.0)
        assert len(result) == 2

    def test_order_preserved_for_representatives(self, fake_settings):
        """Output order matches input order of first-seen representatives."""
        stories = [
            make_story("Alpha story", "https://ex.com/a"),
            make_story("Beta story", "https://ex.com/b"),
            make_story("Gamma story", "https://ex.com/c"),
        ]
        result = cluster_stories(stories, threshold=0.99)
        titles = [str(s.url) for s in result]
        assert titles == ["https://ex.com/a", "https://ex.com/b", "https://ex.com/c"]
