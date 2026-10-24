# artic-api-exhibition-project

Python scripts used to gather data from the Art Institute of Chicago's (ARTIC) public API, for the
exhibition project in LIS 507 (Introduction to Museum Studies) at Simmons University.

No API key, no account, standard library only.

## Scripts

| | |
|---|---|
| `aic.py` | Command-line explorer for the API: get any path, search with term filters, count records per field value, list a resource's fields, print one artwork's tombstone. `python aic.py --help` lists everything. |
| `aic_representation.py` | Counts what the AIC itself labels, by department: works tagged *African American artists* or *African Diaspora*, works with no theme tag at all, and how much of each is on view. Prints Markdown tables. Always hits the API live, so the date it prints is the date of the numbers. |

```bash
python aic.py artwork 27992
python aic.py search --filter gallery_title.keyword="Gallery 107" --filter is_on_view=true
python aic.py count department_title --filter is_on_view=true
python aic_representation.py > representation.md
```

## Being a good API citizen

The AIC's [conventions](https://api.artic.edu/docs/#conventions) ask for three things, and `aic.py` does all of them:

- **Throttling.** Live requests are spaced one second apart, well under the 60/minute anonymous limit.
- **Identification.** Every request sends an `AIC-User-Agent` header. It also sends a plain `User-Agent`, because Cloudflare rejects urllib's default with a 403.
- **Caching.** Responses are cached in `.cache/` (git-ignored). Pass `--no-cache` to force a fresh request.

Collection data is CC0 and description fields are CC-BY 4.0.

## Setup and tests

```bash
conda env create -f environment.yml
conda run -n artic-api pytest
```

The tests never touch the network: requests are served from a temporary cache or patched out.

## AI Notice: 
the readme.md and unit tests were written by cluade code and verified by JAK. (otherwise these likely just wouldn't exist for this project)
