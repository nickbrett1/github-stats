# github-stats

Rolling GitHub diff stats for the Homepage dashboard widget.

A scheduled GitHub Action (daily, 06:17 UTC, plus manual dispatch) computes
lines **added / deleted / net** for the **last 7 days** across every owned
(non-fork, non-archived) repository, bucketed by UTC day. One API pass covers
the whole window; commits are flagged into per-day buckets by committer date.

Outputs:

`stats/daily.json` — the rolling 7-day series (quiet days included, so the
chart has no gaps):

```json
{
  "generated_at": "2026-11-08T23:30:00+00:00",
  "window_days": 7,
  "days": [
    {
      "date": "2026-11-02",
      "repos": { "mailroom": { "added": 1240, "deleted": 318, "net": 922 } }
    }
  ]
}
```

`stats/weekly.json` — flat 7-day totals, same shape as before (kept for
compatibility, and as the fallback if `daily.json` is missing):

```json
{
  "generated_at": "2026-11-08T23:30:00+00:00",
  "mailroom": { "added": 1240, "deleted": 318, "net": 922 }
}
```

Repos with zero activity in the window are omitted from both.

`stats/history.json` is the old weekly-snapshot archive. The page no longer
reads it and the script no longer writes it; it is kept only as history.

The JSON is committed to `main` and served by GitHub Pages:
<https://nickbrett1.github.io/github-stats/stats/daily.json>

## Re-run manually

```sh
gh workflow run weekly-github-stats.yml --repo nickbrett1/github-stats
```

Locally, with a token that can read all owned repos:

```sh
GH_TOKEN=... python3 .github/scripts/weekly_stats.py --days 7 --out stats/daily.json
```

## Notes

- Counts commits by when they landed on the default branch (committer date);
  `Merge ...` commits are skipped to avoid double-counting.
- The window is inclusive of today, so the newest point is a partial day.
- API usage: a few hundred calls per run (well under the 5,000/hr limit).
- `GH_STATS_TOKEN` is a fine-grained PAT with **read** access to repositories.
  The Action only reads; the commit/push uses the built-in `GITHUB_TOKEN`.
