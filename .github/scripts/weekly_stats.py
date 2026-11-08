#!/usr/bin/env python3
"""Rolling GitHub diff stats — lines added/deleted per owned repo, bucketed by UTC day.

Writes:
  stats/daily.json   rolling window, oldest day first:
                     {"generated_at": iso, "window_days": 7,
                      "days": [{"date": "YYYY-MM-DD", "repos": {name: {added, deleted, net}}}]}
  stats/weekly.json  flat 7-day totals, same shape as before
                     {"generated_at": iso, <repo>: {added, deleted, net}}   (legacy/consumers)

One pass over the window: commits are fetched once per repo for [start, now) and
flagged into per-day buckets by their committer date, so a daily run costs the
same number of API calls as the old weekly run.

Requires GH_TOKEN (fine-grained PAT with read access to repositories).
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request

API = "https://api.github.com"


def gh(path):
    req = urllib.request.Request(f"{API}{path}")
    req.add_header("Authorization", f"Bearer {os.environ['GH_TOKEN']}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    time.sleep(0.25)  # pace requests to avoid GitHub secondary rate limits
    return data


def day_of(ts):
    """'2026-11-02T13:43:24Z' -> '2026-11-02' (UTC)."""
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(
        dt.timezone.utc
    ).date().isoformat()


def fetch_commits(repo, since, until, max_commits):
    commits = []
    page = 1
    while len(commits) < max_commits:
        url = (
            f"/repos/{repo['full_name']}/commits?sha={repo['default_branch']}"
            f"&since={urllib.parse.quote(since)}&until={urllib.parse.quote(until)}"
            f"&per_page=100&page={page}"
        )
        batch = gh(url)
        if not batch:
            break
        commits.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return commits[:max_commits]


def compute_window(repos, start_day, until, max_commits):
    """Return (per_day, totals) for [start_day 00:00 UTC, until).

    per_day: {"YYYY-MM-DD": {repo: {added, deleted, net}}} for every day in the
    window, including quiet days (so the chart has no gaps).
    totals:  {repo: {added, deleted, net}} across the whole window.
    """
    n_days = (until.date() - start_day).days + 1
    per_day = {
        (start_day + dt.timedelta(days=i)).isoformat(): {} for i in range(n_days)
    }
    totals = {}
    since = dt.datetime.combine(start_day, dt.time.min, tzinfo=dt.timezone.utc)
    since_iso = since.isoformat()
    until_iso = until.isoformat()

    for repo in repos:
        name = repo["name"]
        try:
            commits = fetch_commits(repo, since_iso, until_iso, max_commits)
            buckets = {}
            for c in commits:
                msg = c.get("commit", {}).get("message", "") or ""
                if msg.startswith("Merge "):
                    continue  # squash-merge PRs already attribute to the merge commit
                detail = gh(f"/repos/{repo['full_name']}/commits/{c['sha']}")
                st = detail.get("stats", {})
                a = st.get("additions", 0)
                d = st.get("deletions", 0)
                ts = (
                    (c.get("commit", {}).get("committer") or {}).get("date")
                    or (c.get("commit", {}).get("author") or {}).get("date")
                )
                if not ts:
                    continue
                day = day_of(ts)
                if day not in per_day:
                    continue  # landed outside the window (clock skew / rebase)
                row = buckets.setdefault(day, {"added": 0, "deleted": 0, "net": 0})
                row["added"] += a
                row["deleted"] += d
                row["net"] = row["added"] - row["deleted"]

            for day, row in buckets.items():
                per_day[day][name] = row
                t = totals.setdefault(name, {"added": 0, "deleted": 0, "net": 0})
                t["added"] += row["added"]
                t["deleted"] += row["deleted"]
                t["net"] = t["added"] - t["deleted"]
        except Exception as e:
            print(f"WARN: skipping {name}: {e}", file=sys.stderr)
    return per_day, totals


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7, help="rolling window length")
    ap.add_argument("--out", default="stats/daily.json")
    ap.add_argument("--legacy", default="stats/weekly.json",
                    help="flat 7-day totals, same shape as the old weekly.json")
    ap.add_argument("--max-commits", type=int, default=200)
    args = ap.parse_args()
    if args.days < 1:
        ap.error("--days must be >= 1")

    try:
        repos = gh("/user/repos?affiliation=owner&per_page=100&sort=updated")
    except Exception as e:
        print(f"FATAL: cannot list repos ({e}); check GH_TOKEN scope", file=sys.stderr)
        sys.exit(1)
    repos = [r for r in repos if not r["fork"] and not r["archived"]]

    now = dt.datetime.now(dt.timezone.utc)
    start_day = (now - dt.timedelta(days=args.days - 1)).date()

    per_day, totals = compute_window(repos, start_day, now, args.max_commits)
    days = [
        {"date": day, "repos": per_day[day]} for day in sorted(per_day)
    ]

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(
            {
                "generated_at": now.isoformat(),
                "window_days": args.days,
                "days": days,
            },
            f,
            indent=2,
            sort_keys=True,
        )
    out = {"generated_at": now.isoformat()}
    out.update(totals)
    with open(args.legacy, "w") as f:
        json.dump(out, f, indent=2, sort_keys=True)

    active = sum(1 for s in totals.values() if s["added"] or s["deleted"])
    print(
        f"wrote {args.out} ({len(days)} days) + {args.legacy} "
        f"({active} active repos of {len(repos)})"
    )


if __name__ == "__main__":
    main()
