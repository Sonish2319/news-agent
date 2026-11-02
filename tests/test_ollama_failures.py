"""
Tests for Ollama / ranking failure paths.

Covers:
  - Connection refused (requests.ConnectionError)
  - HTTP 500 from Ollama
  - Malformed JSON in response
  - Missing 'stories' key
  - Unknown / out-of-range candidate IDs
  - Duplicate candidate IDs in response
  - Retry behaviour and exponential backoff
  - RankingError raised after all retries exhausted
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, call, patch

import pytest
import requests

from news_agent.processing.ranking import RankingError, rank_stories
from tests.conftest import make_story


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_ollama_response(stories: list[dict], status: int = 200) -> MagicMock:
    """Build a fake requests.Response for an Ollama chat reply."""
    mock = MagicMock()
    mock.status_code = status
    mock.raise_for_status = MagicMock()
    if status >= 400:
        mock.raise_for_status.side_effect = requests.HTTPError(
            response=mock
        )
    mock.json.return_value = {
        "message": {"content": json.dumps({"stories": stories})}
    }
    return mock


def _valid_ranked_story(id: int = 0) -> dict:
    return {
        "id": id,
        "score": 8,
        "headline": f"Story {id}",
        "summary": "A meaningful summary for testing purposes.",
        "why_it_matters": "It has broad impact.",
        "category": "World",
    }


STORIES = [make_story(f"Title {i}", f"https://ex.com/{i}") for i in range(5)]


# ── Connection failures ───────────────────────────────────────────────────────

class TestOllamaConnectionFailure:
    @patch("news_agent.processing.ranking.requests.post")
    @patch("news_agent.processing.ranking.time.sleep")
    def test_connection_refused_retries_and_raises(
        self, mock_sleep, mock_post, fake_settings
    ):
        """A persistent connection error triggers all retries then raises."""
        mock_post.side_effect = requests.ConnectionError("Connection refused")

        with pytest.raises(RankingError, match="Ollama ranking failed after"):
            rank_stories(STORIES)

        # 3 retries = 3 POST calls, 2 sleeps (no sleep after last attempt)
        assert mock_post.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("news_agent.processing.ranking.requests.post")
    @patch("news_agent.processing.ranking.time.sleep")
    def test_timeout_retries_and_raises(self, mock_sleep, mock_post, fake_settings):
        """A request timeout triggers all retries then raises."""
        mock_post.side_effect = requests.Timeout("Read timeout")

        with pytest.raises(RankingError):
            rank_stories(STORIES)

        assert mock_post.call_count == 3

    @patch("news_agent.processing.ranking.requests.post")
    @patch("news_agent.processing.ranking.time.sleep")
    def test_exponential_backoff_delays(self, mock_sleep, mock_post, fake_settings):
        """Sleep durations double on each retry: 1s, 2s."""
        mock_post.side_effect = requests.ConnectionError("refused")

        with pytest.raises(RankingError):
            rank_stories(STORIES)

        # sleep(2**0)=1, sleep(2**1)=2
        mock_sleep.assert_has_calls([call(1), call(2)])

    @patch("news_agent.processing.ranking.requests.post")
    @patch("news_agent.processing.ranking.time.sleep")
    def test_succeeds_on_third_attempt(self, mock_sleep, mock_post, fake_settings):
        """Recovery on the third attempt returns valid results."""
        error = requests.ConnectionError("refused")
        ok = _make_ollama_response([_valid_ranked_story(0)])

        mock_post.side_effect = [error, error, ok]

        result = rank_stories(STORIES[:1])
        assert len(result) == 1
        assert result[0].headline == "Story 0"


# ── HTTP error codes ──────────────────────────────────────────────────────────

class TestOllamaHttpErrors:
    @patch("news_agent.processing.ranking.requests.post")
    @patch("news_agent.processing.ranking.time.sleep")
    def test_http_500_retries(self, mock_sleep, mock_post, fake_settings):
        """HTTP 500 from Ollama triggers retries."""
        mock_post.return_value = _make_ollama_response([], status=500)

        with pytest.raises(RankingError):
            rank_stories(STORIES)

        assert mock_post.call_count == 3

    @patch("news_agent.processing.ranking.requests.post")
    def test_http_200_with_empty_stories_list(self, mock_post, fake_settings):
        """An empty stories list from Ollama returns an empty list (not an error)."""
        mock_post.return_value = _make_ollama_response([])

        result = rank_stories(STORIES)
        assert result == []


# ── Malformed JSON ────────────────────────────────────────────────────────────

class TestOllamaMalformedResponse:
    @patch("news_agent.processing.ranking.requests.post")
    @patch("news_agent.processing.ranking.time.sleep")
    def test_non_json_content_retries(self, mock_sleep, mock_post, fake_settings):
        """Non-JSON content body triggers retries."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "message": {"content": "This is not JSON {{{}"}
        }
        mock_post.return_value = mock_resp

        with pytest.raises(RankingError):
            rank_stories(STORIES)

        assert mock_post.call_count == 3

    @patch("news_agent.processing.ranking.requests.post")
    @patch("news_agent.processing.ranking.time.sleep")
    def test_missing_stories_key_retries(self, mock_sleep, mock_post, fake_settings):
        """A response without a 'stories' key triggers retries."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "message": {"content": json.dumps({"wrong_key": []})}
        }
        mock_post.return_value = mock_resp

        with pytest.raises(RankingError):
            rank_stories(STORIES)

    @patch("news_agent.processing.ranking.requests.post")
    @patch("news_agent.processing.ranking.time.sleep")
    def test_stories_not_a_list(self, mock_sleep, mock_post, fake_settings):
        """'stories' being a dict instead of list triggers retries."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "message": {"content": json.dumps({"stories": {"id": 0}})}
        }
        mock_post.return_value = mock_resp

        with pytest.raises(RankingError):
            rank_stories(STORIES)


# ── Bad candidate IDs ─────────────────────────────────────────────────────────

class TestOllamaBadIds:
    @patch("news_agent.processing.ranking.requests.post")
    def test_unknown_ids_are_filtered(self, mock_post, fake_settings):
        """Stories with IDs not in the candidate list are silently dropped."""
        mock_post.return_value = _make_ollama_response([
            _valid_ranked_story(id=0),   # valid
            _valid_ranked_story(id=99),  # unknown – should be ignored
        ])

        result = rank_stories(STORIES)
        assert len(result) == 1
        assert result[0].id == 0

    @patch("news_agent.processing.ranking.requests.post")
    def test_duplicate_ids_are_filtered(self, mock_post, fake_settings):
        """Stories with repeated IDs keep only the first occurrence."""
        mock_post.return_value = _make_ollama_response([
            _valid_ranked_story(id=0),
            _valid_ranked_story(id=0),  # duplicate – should be ignored
        ])

        result = rank_stories(STORIES)
        assert len(result) == 1


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestOllamaEdgeCases:
    def test_empty_story_list_returns_empty(self, fake_settings):
        """rank_stories([]) short-circuits without calling Ollama."""
        with patch("news_agent.processing.ranking.requests.post") as mock_post:
            result = rank_stories([])
        assert result == []
        mock_post.assert_not_called()

    @patch("news_agent.processing.ranking.requests.post")
    def test_result_sorted_by_score_descending(self, mock_post, fake_settings):
        """Results are returned highest-score first."""
        mock_post.return_value = _make_ollama_response([
            {**_valid_ranked_story(0), "score": 3},
            {**_valid_ranked_story(1), "score": 9},
            {**_valid_ranked_story(2), "score": 6},
        ])

        result = rank_stories(STORIES[:3])
        scores = [r.score for r in result]
        assert scores == sorted(scores, reverse=True)
