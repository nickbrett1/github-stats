# github-stats

Weekly GitHub diff stats for the Homepage dashboard widget.

A scheduled GitHub Action (Mondays 05:30 UTC, plus manual dispatch) computes
lines **added / deleted / net** for the last 7 days across every owned
(non-fork, non-archived) repository, and writes `stats/weekly.json`:

```json
{
  "mailroom": { "added": 1240, "deleted": 318, "net": 922 }
}
```

Repos with zero activity in the window are omitted.

The JSON is committed to `main` and served by GitHub Pages:
<https://nickbrett1.github.io/github-stats/stats/weekly.json>

Homepage consumes it via a `customapi` widget (see Homepage `services.yaml`).

## Re-run manually

```sh
gh workflow run weekly-github-stats.yml --repo nickbrett1/github-stats
```

## Notes

- Counts commits by when they landed on the default branch; `Merge ...`
  commits are skipped to avoid double-counting.
- `GH_STATS_TOKEN` is a fine-grained PAT with **read** access to repositories.
  The Action only reads; the commit/push uses the built-in `GITHUB_TOKEN`.
- API usage: a few hundred calls per run (well under the 5,000/hr limit).
