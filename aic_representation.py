"""Count what the Art Institute of Chicago itself labels, by department.

The question: how much of the AIC's collection is by Black artists, and how
much by European ones? The collection has no field for an artist's race, so
this script does not guess. It counts only labels the AIC has applied:

    Theme tags      "African American artists" and "African Diaspora", which AIC
                    staff attach to individual artworks (theme_titles).
    Departments     The AIC's own curatorial divisions (department_title),
                    several of which are named for Europe.

So every number means "works the AIC labels as X". A work by a Black artist
that carries neither tag lands in the untagged count, not anywhere else. How
far that undercounts is a question about the labeling, which is why the script
also reports how many works carry no theme tag of any kind.

Requests go through request() in aic.py, which spaces them a second apart and 
sends the AIC-User-Agent header
"""

import datetime
import sys

import aic

THEMES = ["African American artists", "African Diaspora"]

ON_VIEW = {"term": {"is_on_view": True}}
TAGGED = {"terms": {"theme_titles.keyword": THEMES}}  # either theme
NO_THEME = {"bool": {"must_not": {"exists": {"field": "theme_titles"}}}}


def theme(name: str) -> dict:
    return {"term": {"theme_titles.keyword": name}}


def count(*filters: dict) -> tuple[int, dict[str, int]]:
    """Works matching every filter: the total, and the same split by department."""
    body = {
        "query": {"bool": {"filter": list(filters)}},
        "limit": 0,  # no records, just the counts
        "aggregations": {"dept": {"terms": {"field": "department_title.keyword", "size": 100}}},
    }
    result = aic.request("artworks/search", body=body)
    by_dept = {b["key"]: b["doc_count"] for b in result["aggregations"]["dept"]["buckets"]}
    total = result["pagination"]["total"]
    # Each work has at most one department; whatever the buckets miss has none.
    by_dept["(no department)"] = total - sum(by_dept.values())
    return total, by_dept


def pct(nom: int, denom: int) -> str:
    if not denom or denom == 0:
        return "-"
    if nom == 0:
        return "0%"
    safe_div = nom / denom
    if safe_div < 0.0001:
        return "<0.01%"
    return f"{safe_div:.2%}"


def main() -> None:
    aic.use_cache = False  # the date printed below has to be the date of the numbers
    sys.stdout.reconfigure(encoding="utf-8")

    all_works, dept_all = count()
    on_view, dept_view = count(ON_VIEW)
    tagged, dept_tagged = count(TAGGED)
    tagged_view, dept_tagged_view = count(TAGGED, ON_VIEW)

    print(f"# AIC collection — what the museum labels\n")
    print(f"Counted {datetime.date.today().isoformat()} from api.artic.edu. Script: `aic_representation.py`.\n")

    print("## Theme tags\n")
    print("| | Collection | % | On view | % |")
    print("|---|---:|---:|---:|---:|")
    print(f"| All works | {all_works:,} | | {on_view:,} | |")
    for name in THEMES:
        n, _ = count(theme(name))
        v, _ = count(theme(name), ON_VIEW)
        print(f"| Tagged *{name}* | {n:,} | {pct(n, all_works)} | {v:,} | {pct(v, on_view)} |")
    print(f"| Tagged either | {tagged:,} | {pct(tagged, all_works)} | {tagged_view:,} | {pct(tagged_view, on_view)} |")
    untagged, _ = count(NO_THEME)
    untagged_view, _ = count(NO_THEME, ON_VIEW)
    print(f"| **No theme tag of any kind** | {untagged:,} | {pct(untagged, all_works)} "
          f"| {untagged_view:,} | {pct(untagged_view, on_view)} |")

    print("\n## By department\n")
    print("Department names are the AIC's. *Tagged* means either theme above.\n")
    print("| Department | Works | Tagged | % | On view | Tagged on view | % |")
    print("|---|---:|---:|---:|---:|---:|---:|")
    for dept in sorted(dept_all, key=dept_all.get, reverse=True):
        if not dept_all[dept]:
            continue
        t, v, tv = dept_tagged.get(dept, 0), dept_view.get(dept, 0), dept_tagged_view.get(dept, 0)
        print(f"| {dept} | {dept_all[dept]:,} | {t:,} | {pct(t, dept_all[dept])} "
              f"| {v:,} | {tv:,} | {pct(tv, v)} |")


if __name__ == "__main__":
    main()
