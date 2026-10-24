"""Tests for aic.py. No network: request() is fed from a temp cache or patched out."""

import argparse
import hashlib
import json

import pytest

import aic


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """Point the cache at a temp dir and make any live request fail the test."""
    monkeypatch.setattr(aic, "CACHE", tmp_path)
    monkeypatch.setattr(aic, "use_cache", True)

    def no_network(*args, **kwargs):
        raise AssertionError("tried to reach the network")

    monkeypatch.setattr(aic.urllib.request, "urlopen", no_network)
    return tmp_path


def seed(cache_dir, url: str, body: dict | None, result: dict) -> None:
    """Write a cache entry under the same key request() computes."""
    data = json.dumps(body, sort_keys=True).encode() if body is not None else b""
    key = hashlib.sha1(url.encode() + data).hexdigest()
    (cache_dir / f"{key}.json").write_text(json.dumps(result), encoding="utf-8")


class TestParseFilters:
    def test_booleans_are_typed(self):
        assert aic.parse_filters(["is_on_view=true", "is_public_domain=false"]) == [
            {"term": {"is_on_view": True}},
            {"term": {"is_public_domain": False}},
        ]

    def test_integers_are_typed_including_negative(self):
        assert aic.parse_filters(["gallery_id=107", "x=-3"]) == [
            {"term": {"gallery_id": 107}},
            {"term": {"x": -3}},
        ]

    def test_strings_stay_strings(self):
        assert aic.parse_filters(["gallery_title.keyword=Gallery 107"]) == [
            {"term": {"gallery_title.keyword": "Gallery 107"}}
        ]

    def test_only_first_equals_splits(self):
        assert aic.parse_filters(["title.keyword=a=b"]) == [{"term": {"title.keyword": "a=b"}}]

    def test_empty(self):
        assert aic.parse_filters([]) == []


class TestSearchBody:
    def test_filters_only(self):
        args = argparse.Namespace(q=None, filter=["is_on_view=true"])
        assert aic.search_body(args) == {"query": {"bool": {"filter": [{"term": {"is_on_view": True}}]}}}

    def test_free_text_adds_must(self):
        body = aic.search_body(argparse.Namespace(q="water lilies", filter=[]))
        assert body["query"]["bool"]["must"] == [{"multi_match": {"query": "water lilies"}}]


class TestIiifUrl:
    def test_uses_base_from_response(self):
        result = {"config": {"iiif_url": "https://example.org/iiif"}}
        assert aic.iiif_url(result, "abc") == "https://example.org/iiif/abc/full/843,/0/default.jpg"

    def test_falls_back_without_config(self):
        assert aic.iiif_url({}, "abc").startswith(aic.IIIF_FALLBACK + "/abc/")


class TestRequest:
    def test_get_served_from_cache(self, cache):
        seed(cache, f"{aic.API}/artworks/27992?fields=id", None, {"data": {"id": 27992}})
        assert aic.request("/artworks/27992/", {"fields": "id"}) == {"data": {"id": 27992}}

    def test_post_cache_key_includes_body(self, cache):
        seed(cache, f"{aic.API}/artworks/search", {"limit": 0}, {"pagination": {"total": 5}})
        assert aic.request("artworks/search", body={"limit": 0}) == {"pagination": {"total": 5}}
        with pytest.raises(AssertionError, match="network"):
            aic.request("artworks/search", body={"limit": 1})

    def test_live_response_is_cached(self, cache, monkeypatch):
        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, *args):
                return b'{"data": []}'

        monkeypatch.setattr(aic.urllib.request, "urlopen", lambda req, timeout: Resp())
        monkeypatch.setattr(aic, "MIN_INTERVAL", 0)
        assert aic.request("galleries") == {"data": []}
        assert len(list(cache.glob("*.json"))) == 1

    def test_no_cache_skips_cached_entry(self, cache, monkeypatch):
        seed(cache, f"{aic.API}/galleries", None, {"data": "stale"})
        monkeypatch.setattr(aic, "use_cache", False)
        with pytest.raises(AssertionError, match="network"):
            aic.request("galleries")


class TestCount:
    @pytest.fixture
    def captured(self, monkeypatch):
        calls = []

        def fake_request(path, params=None, body=None):
            calls.append(body)
            return {
                "pagination": {"total": 3},
                "aggregations": {"counts": {"buckets": [{"key": "Gallery 107", "doc_count": 3}]}},
            }

        monkeypatch.setattr(aic, "request", fake_request)
        return calls

    def args(self, field):
        return argparse.Namespace(field=field, q=None, filter=[], resource="artworks", size=25, raw=False)

    @pytest.mark.parametrize(
        ("field", "expected"),
        [
            ("gallery_title", "gallery_title.keyword"),
            ("gallery_title.keyword", "gallery_title.keyword"),
            ("is_on_view", "is_on_view"),
        ],
    )
    def test_keyword_suffix(self, captured, capsys, field, expected):
        aic.cmd_count(self.args(field))
        assert captured[0]["aggregations"]["counts"]["terms"]["field"] == expected
        assert captured[0]["limit"] == 0
        assert "Gallery 107" in capsys.readouterr().out


class TestShow:
    def test_artwork_gets_image_and_catalogue_links(self, capsys):
        result = {
            "config": {"iiif_url": "https://example.org/iiif"},
            "data": {"id": 27992, "artist_display": "Seurat", "image_id": "img", "_score": 1},
        }
        aic.show(result, raw=False)
        out = capsys.readouterr().out
        assert "https://example.org/iiif/img/full/843,/0/default.jpg" in out
        assert "https://www.artic.edu/artworks/27992" in out
        assert "_score" not in out

    def test_pagination_header(self, capsys):
        aic.show({"pagination": {"total": 40, "current_page": 1, "total_pages": 4}, "data": []}, raw=False)
        assert "# 40 total · page 1 of 4" in capsys.readouterr().out
