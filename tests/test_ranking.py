"""
Tests for ranking.py.

Covers:
  - Topic preference injection into the prompt
  - Source diversity enforcement (max 2 stories per source)
  - Score sorting
  - Candidates capped at MAX_CANDIDATES (40)
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from news_agent.processing.ranking import (
    _build_prompt,
    _enforce_source_diversity,
    rank_stories,
)
from tests.conftest import make_ranked, make_story


# ── Prompt building ───────────────────────────────────────────────────────────

class TestPromptBuilding:
    def test_no_preferences_no_preferences_section(self, fake_settings):
        prompt = _build_prompt([], "Nepal", 5, topic_preferences=[])
        assert "USER PREFERENCES" not in prompt

    def test_preferences_injected(self, fake_settings):
        prefs = ["Technology", "Science"]
        prompt = _build_prompt([], "Nepal", 5, topic_preferences=prefs)
        assert "USER PREFERENCES" in prompt
        assert "Technology" in prompt
        assert "Science" in prompt

    def test_nepal_priority_text(self, fake_settings):
        prompt = _build_prompt([], "Nepal", 5)
        assert "Nepal" in prompt

    def test_india_priority_text(self, fake_settings):
        prompt = _build_prompt([], "India", 5)
        assert "India" in prompt

    def test_international_priority_text(self, fake_settings):
        prompt = _build_prompt([], "International", 5)
        assert "globally significant" in prompt.lower()


# ── Source diversity ──────────────────────────────────────────────────────────

class TestSourceDiversity:
    def _make_stories_for_sources(self, source_ids: list[str]) -> list:
        return [
            make_story(f"T{i}", f"https://ex.com/{i}", source=src)
            for i, src in enumerate(source_ids)
        ]

    def test_max_two_per_source(self, fake_settings):
        """No source appears more than twice in the output."""
        sources = ["BBC", "BBC", "BBC", "CNN", "CNN"]
        stories = self._make_stories_for_sources(sources)
        candidates = [
            {"id": i, "title": s.title, "source": s.source, "summary": ""}
            for i, s in enumerate(stories)
        ]
        ranked = [make_ranked(id=i, score=10 - i) for i in range(5)]

        result = _enforce_source_diversity(ranked, candidates, stories)

        bbc_count = sum(1 for r in result if stories[r.id].source == "BBC")
        cnn_count = sum(1 for r in result if stories[r.id].source == "CNN")
        assert bbc_count <= 2
        assert cnn_count <= 2

    def test_diversity_backfills_from_overflow(self, fake_settings):
        """Dropped stories from overrepresented sources are replaced."""
        sources = ["BBC", "BBC", "BBC", "CNN"]  # 3 BBC → 3rd dropped, CNN backfills
        stories = self._make_stories_for_sources(sources)
        candidates = [
            {"id": i, "title": s.title, "source": s.source, "summary": ""}
            for i, s in enumerate(stories)
        ]
        ranked = [make_ranked(id=i, score=10 - i) for i in range(4)]

        result = _enforce_source_diversity(ranked, candidates, stories, top_n=4)

        # CNN story (id=3) should be in the result despite low original rank.
        ids_in_result = {r.id for r in result}
        assert 3 in ids_in_result

    def test_single_source_monopoly_capped(self, fake_settings):
        """All-same-source input is capped to 2."""
        sources = ["BBC"] * 5
        stories = self._make_stories_for_sources(sources)
        candidates = [
            {"id": i, "title": s.title, "source": s.source, "summary": ""}
            for i, s in enumerate(stories)
        ]
        ranked = [make_ranked(id=i, score=10 - i) for i in range(5)]

        result = _enforce_source_diversity(ranked, candidates, stories)
        assert len(result) <= 2


# ── Integration with mocked Ollama ────────────────────────────────────────────

class TestRankingIntegration:
    def _ok_response(self, items: list[dict]) -> MagicMock:
        mock = MagicMock()
        mock.raise_for_status = MagicMock()
        mock.json.return_value = {
            "message": {"content": json.dumps({"stories": items})}
        }
        return mock

    @patch("news_agent.processing.ranking.requests.post")
    def test_topic_preferences_passed_to_ollama(self, mock_post, fake_settings):
        """When topic_preferences is set, the prompt reaching Ollama includes them."""
        # Create a settings copy with topic_preferences populated.
        prefs_settings = fake_settings.model_copy(
            update={"topic_preferences": "Science,Health"}
        )

        captured_payload: list[dict] = []

        def capture(url, *, json, timeout):
            captured_payload.append(json)
            return self._ok_response([{
                "id": 0, "score": 7, "headline": "H",
                "summary": "S" * 20, "why_it_matters": "W" * 15,
                "category": "Science",
            }])

        mock_post.side_effect = capture

        stories = [make_story("Science breakthrough", "https://ex.com/1")]

        with patch("news_agent.processing.ranking.get_settings", return_value=prefs_settings):
            rank_stories(stories, country="International")

        assert captured_payload, "POST was never called"
        user_msg = captured_payload[0]["messages"][1]["content"]
        assert "Science" in user_msg
        assert "Health" in user_msg

    @patch("news_agent.processing.ranking.requests.post")
    def test_results_sorted_by_score(self, mock_post, fake_settings):
        stories = [make_story(f"T{i}", f"https://ex.com/{i}") for i in range(3)]
        mock_post.return_value = self._ok_response([
            {"id": 0, "score": 4, "headline": "H0", "summary": "S" * 20,
             "why_it_matters": "W" * 15, "category": "World"},
            {"id": 1, "score": 9, "headline": "H1", "summary": "S" * 20,
             "why_it_matters": "W" * 15, "category": "World"},
            {"id": 2, "score": 6, "headline": "H2", "summary": "S" * 20,
             "why_it_matters": "W" * 15, "category": "World"},
        ])

        result = rank_stories(stories)
        scores = [r.score for r in result]
        assert scores == sorted(scores, reverse=True)

    @patch("news_agent.processing.ranking.requests.post")
    def test_top_ten_stories_not_capped_at_two(self, mock_post, fake_settings):
        """Requesting 10 stories returns 10 stories rather than being choked down to 2."""
        # 10 candidate stories from 2 sources
        stories = (
            [make_story(f"KP-{i}", f"https://ex.com/kp/{i}", source="Kathmandu Post") for i in range(5)]
            + [make_story(f"OK-{i}", f"https://ex.com/ok/{i}", source="OnlineKhabar") for i in range(5)]
        )
        mock_post.return_value = self._ok_response([
            {"id": i, "score": 10 - i, "headline": f"H{i}", "summary": "S" * 20,
             "why_it_matters": "W" * 15, "category": "Nepal"}
            for i in range(10)
        ])

        result = rank_stories(stories, country="Nepal", top_stories=10)
        assert len(result) == 10

    def test_interleave_by_source(self):
        from news_agent.processing.ranking import _interleave_by_source
        stories = (
            [make_story("A1", "https://ex.com/a1", source="Source A")]
            + [make_story("A2", "https://ex.com/a2", source="Source A")]
            + [make_story("B1", "https://ex.com/b1", source="Source B")]
            + [make_story("B2", "https://ex.com/b2", source="Source B")]
        )
        interleaved = _interleave_by_source(stories)
        sources = [s.source for s in interleaved]
        assert sources == ["Source A", "Source B", "Source A", "Source B"]
