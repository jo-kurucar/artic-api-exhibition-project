"""Tests for aic_representation.py, with aic.request patched out."""

import pytest

import aic
import aic_representation as rep


class TestPct:
    @pytest.mark.parametrize(
        ("part", "whole", "expected"),
        [
            (0, 0, "-"),
            (0, 10000, "0%"),
            (1, 10001, "<0.01%"),
            (1, 9999, "0.01%"),
            (1, 10000, "0.01%"),
            (1, 4, "25.00%"),
        ],
    )
    def test_formatting(self, part, whole, expected):
        assert rep.pct(part, whole) == expected


class TestCount:
    @pytest.fixture
    def bodies(self, monkeypatch):
        sent = []

        def fake_request(path, params=None, body=None):
            sent.append(body)
            return {
                "pagination": {"total": 10},
                "aggregations": {
                    "dept": {
                        "buckets": [
                            {"key": "Painting and Sculpture of Europe", "doc_count": 6},
                            {"key": "Arts of Africa", "doc_count": 3},
                        ]
                    }
                },
            }

        monkeypatch.setattr(aic, "request", fake_request)
        return sent

    def test_remainder_goes_to_no_department(self, bodies):
        total, by_dept = rep.count(rep.ON_VIEW)
        assert total == 10
        assert by_dept["(no department)"] == 1
        assert sum(by_dept.values()) == total

    def test_filters_are_combined_and_no_records_requested(self, bodies):
        rep.count(rep.TAGGED, rep.ON_VIEW)
        assert bodies[0]["query"]["bool"]["filter"] == [rep.TAGGED, rep.ON_VIEW]
        assert bodies[0]["limit"] == 0


def test_theme_filter_uses_keyword():
    assert rep.theme("African Diaspora") == {"term": {"theme_titles.keyword": "African Diaspora"}}
