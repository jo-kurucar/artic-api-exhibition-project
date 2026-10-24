"""Explore the Art Institute of Chicago public API from the command line.

No key, no account, stdlib only. Light weight by design on purpose.

API conventions (https://api.artic.edu/docs/#conventions):
    Rate limit      60 requests/minute per IP, anonymous. This script spaces
                    requests 1 s apart, as the docs ask of anything that loops.
    Identify        AIC-User-Agent header: "project-name (contact email)".
    Pagination      12 per page by default; `limit` max 100; `page` is 1-based.
                    limit=0 returns just the total — what `count` relies on.
                    Docs say 10,000 results max per search; in practice paging
                    past page 10 at limit=100 already returns 403.
    fields          Ask only for the fields you need — faster, and the docs ask.
    ids             Batch detail lookups: get artworks --param ids=111628,27992
    include         Embed subresources: --param include=artist_pivots,place_pivots
    q vs query      `q` is free text; `query` is Elasticsearch DSL (term, exists,
                    bool, range) and `aggregations` count facets. POST for both.
    Field names     snake_case; refs are {x}_id/{x}_title, plurals {x}_ids/{x}_titles.
                    Empty values are null or [], never "".
    Caching         Responses are cached in ./.cache (the docs ask callers to
                    cache). --no-cache to force a fresh request.
    Bulk work       Over ~10,000 records, use the nightly data dump instead of
                    the API: https://github.com/art-institute-of-chicago/api-data
    Images          IIIF; base URL comes from the response's config.iiif_url,
                    not hardcoded. 843px wide is the cached, copyright-safe size
                    (200/400/600 also cached; 1686 public-domain only). Prefer
                    is_public_domain=true. Download images one at a time, 1 s apart.
    Licensing       Data CC0; description fields CC-BY 4.0; places CC-BY (Getty).

Examples:
    python aic.py get artworks/27992
    python aic.py get galleries --param limit=5 --fields id,title,floor
    python aic.py search "water lilies" --fields id,title,artist_display,gallery_title
    python aic.py search --filter gallery_title.keyword="Gallery 50" --filter is_on_view=true
    python aic.py count department_title --filter is_on_view=true
    python aic.py count gallery_title --q "water" --filter is_on_view=true
    python aic.py fields artworks
    python aic.py artwork 27992 --all
    python aic.py get artworks --param ids=64339,27992 --fields id,title
    python aic.py --no-cache search "mummy"
"""

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.artic.edu/api/v1"
IIIF_FALLBACK = "https://www.artic.edu/iiif/2"  # used only if a response has no config.iiif_url
CACHE = Path(__file__).parent / ".cache"
MIN_INTERVAL = 1.0  # seconds between live requests
_last_request = 0.0
use_cache = True
# AIC asks for "project-name (contact email)" so they can reach you before blocking
# a heavy caller. Add an email inside the parentheses if you want them able to.
HEADERS = {
    "AIC-User-Agent": "kurucar-lis507-exploration",
    "User-Agent": "kurucar-lis507-exploration",
    "Content-Type": "application/json",
}

TOMBSTONE = [
    "id", "title", "artist_display", "date_display", "medium_display", "dimensions",
    "credit_line", "main_reference_number", "gallery_title", "is_on_view",
    "is_public_domain", "image_id",
]


def request(path: str, params: dict | None = None, body: dict | None = None) -> dict:
    """GET (or POST, if body is given) an API path and return the parsed JSON.

    Cached on disk by URL + body, and throttled to one live request per second.
    """
    global _last_request
    url = f"{API}/{path.strip('/')}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body, sort_keys=True).encode() if body is not None else None
    cached = CACHE / (hashlib.sha1(url.encode() + (data or b"")).hexdigest() + ".json")
    if use_cache and cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))

    wait = MIN_INTERVAL - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, data=data, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.load(resp)
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} from {url}\n{e.read().decode(errors='replace')[:500]}")
    finally:
        _last_request = time.monotonic()
    CACHE.mkdir(exist_ok=True)
    cached.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


def iiif_url(result: dict, image_id: str) -> str:
    """843px image URL, built from the base the API itself reports."""
    base = result.get("config", {}).get("iiif_url", IIIF_FALLBACK)
    return f"{base}/{image_id}/full/843,/0/default.jpg"


def parse_filters(pairs: list[str]) -> list[dict]:
    """Turn field=value strings into Elasticsearch term filters.

    true/false/numbers are typed; anything else stays a string. Text fields
    need the .keyword suffix or they silently match nothing.
    """
    filters = []
    for pair in pairs:
        field, _, raw = pair.partition("=")
        value: object = raw
        if raw in ("true", "false"):
            value = raw == "true"
        elif raw.lstrip("-").isdigit():
            value = int(raw)
        filters.append({"term": {field: value}})
    return filters


def search_body(args: argparse.Namespace) -> dict:
    bool_query: dict = {"filter": parse_filters(args.filter)}
    if args.q:
        bool_query["must"] = [{"multi_match": {"query": args.q}}]
    return {"query": {"bool": bool_query}}


def show(result: dict, raw: bool) -> None:
    if raw:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    if "pagination" in result:
        p = result["pagination"]
        print(f"# {p.get('total')} total · page {p.get('current_page')} of {p.get('total_pages')}\n")
    data = result.get("data", result)
    for record in data if isinstance(data, list) else [data]:
        for key, value in record.items():
            if key.startswith("_"):
                continue
            print(f"{key:22} {value}")
        if record.get("image_id"):
            print(f"{'image':22} {iiif_url(result, record['image_id'])}")
        if "id" in record and "artist_display" in record:
            print(f"{'catalogue':22} https://www.artic.edu/artworks/{record['id']}")
        print()


def cmd_get(args: argparse.Namespace) -> None:
    params = dict(p.split("=", 1) for p in args.param)
    if args.fields:
        params["fields"] = args.fields
    show(request(args.path, params), args.raw)


def cmd_search(args: argparse.Namespace) -> None:
    body = search_body(args)
    body.update(limit=args.limit, page=args.page, fields=args.fields.split(","))
    show(request(f"{args.resource}/search", body=body), args.raw)


def cmd_count(args: argparse.Namespace) -> None:
    """Bucket counts for one field — how the gallery table in aic-api.md was built."""
    field = args.field if "." in args.field or args.field.startswith("is_") else f"{args.field}.keyword"
    body = search_body(args)
    body.update(limit=0, aggregations={"counts": {"terms": {"field": field, "size": args.size}}})
    result = request(f"{args.resource}/search", body=body)
    buckets = result["aggregations"]["counts"]["buckets"]
    if args.raw:
        print(json.dumps(buckets, indent=2, ensure_ascii=False))
        return
    print(f"# {result['pagination']['total']} matching records, top {len(buckets)} values of {field}\n")
    for b in buckets:
        print(f"{b['doc_count']:7}  {b['key']}")


def cmd_fields(args: argparse.Namespace) -> None:
    """List every field a resource returns, with a sample value from one record."""
    record = request(args.resource, {"limit": 1})["data"][0]
    for key, value in record.items():
        sample = json.dumps(value, ensure_ascii=False)
        print(f"{key:32} {sample[:90]}")


def cmd_artwork(args: argparse.Namespace) -> None:
    fields = None if args.all else ",".join(TOMBSTONE)
    show(request(f"artworks/{args.id}", {"fields": fields} if fields else None), args.raw)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw", action="store_true", help="print the full JSON response")
    parser.add_argument("--no-cache", action="store_true", help="skip ./.cache and hit the API")
    sub = parser.add_subparsers(required=True)

    p = sub.add_parser("get", help="GET any path, e.g. artworks/27992 or exhibitions")
    p.add_argument("path")
    p.add_argument("--param", action="append", default=[], help="key=value query param, repeatable")
    p.add_argument("--fields", help="comma-separated fields to return")
    p.set_defaults(func=cmd_get)

    p = sub.add_parser("search", help="full-text search plus term filters")
    p.add_argument("q", nargs="?", help="free-text query (optional)")
    p.add_argument("--resource", default="artworks")
    p.add_argument("--filter", action="append", default=[], help="field=value term filter, repeatable")
    p.add_argument("--fields", default=",".join(TOMBSTONE))
    p.add_argument("--limit", type=int, default=10, help="max 100")
    p.add_argument("--page", type=int, default=1)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("count", help="aggregate: how many records per value of a field")
    p.add_argument("field", help="e.g. department_title, gallery_title, artwork_type_title")
    p.add_argument("--q", help="free-text query to narrow the records first")
    p.add_argument("--resource", default="artworks")
    p.add_argument("--filter", action="append", default=[], help="field=value term filter, repeatable")
    p.add_argument("--size", type=int, default=25, help="number of buckets")
    p.set_defaults(func=cmd_count)

    p = sub.add_parser("fields", help="list every field on a resource")
    p.add_argument("resource", nargs="?", default="artworks")
    p.set_defaults(func=cmd_fields)

    p = sub.add_parser("artwork", help="one artwork's tombstone, with image and catalogue links")
    p.add_argument("id")
    p.add_argument("--all", action="store_true", help="every field, not just the tombstone")
    p.set_defaults(func=cmd_artwork)

    args = parser.parse_args()
    global use_cache
    use_cache = not args.no_cache
    sys.stdout.reconfigure(encoding="utf-8")  # Windows defaults to cp1252; titles carry accents
    args.func(args)


if __name__ == "__main__":
    main()
