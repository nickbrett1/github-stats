#!/usr/bin/env python3
"""Weekly GitHub diff stats — lines added/deleted per owned repo.

Writes:
  stats/weekly.json  — current 7-day snapshot {generated_at, <repo>: {added, deleted, net}}
  stats/history.json — accumulated weekly snapshots {"weeks": [{"week": <Mon-date>, "repos": {...}}, ...]}
                       (idempotent; --backfill N seeds the previous N weeks; never trimmed)

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


def monday_of(d):
    return (d - dt.timedelta(days=d.weekday())).date()


def compute_week(repos, since, until, max_commits):
    """Aggregate additions/deletions for commits in [since, until) (ISO strings)."""
    stats = {}
    for repo in repos:
        name = repo["name"]
        branch = repo["default_branch"]
        try:
            commits = []
            page = 1
            while len(commits) < max_commits:
                url = (
                    f"/repos/{repo['full_name']}/commits?sha={branch}"
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
            commits = commits[:max_commits]

            added = deleted = 0
            for c in commits:
                msg = (c.get("commit", {}).get("message", "") or "")
                if msg.startswith("Merge "):
                    continue  # squash-merge PRs already attribute to the merge commit
                detail = gh(f"/repos/{repo['full_name']}/commits/{c['sha']}")
                added += detail.get("stats", {}).get("additions", 0)
                deleted += detail.get("stats", {}).get("deletions", 0)

            stats[name] = {"added": added, "deleted": deleted, "net": added - deleted}
        except Exception as e:
            print(f"WARN: skipping {name}: {e}", file=sys.stderr)
    return stats


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out", default="stats/weekly.json")
    ap.add_argument("--history", default="stats/history.json")
    ap.add_argument("--max-commits", type=int, default=200)
    ap.add_argument("--backfill", type=int, default=0,
                    help="seed the previous N weeks of history (idempotent)")
    args = ap.parse_args()

    try:
        repos = gh("/user/repos?affiliation=owner&per_page=100&sort=updated")
    except Exception as e:
        print(f"FATAL: cannot list repos ({e}); check GH_TOKEN scope", file=sys.stderr)
        sys.exit(1)
    repos = [r for r in repos if not r["fork"] and not r["archived"]]

    now = dt.datetime.now(dt.timezone.utc)
    history = load_json(args.history, {"weeks": []})
    seen = {w["week"] for w in history.get("weeks", [])}

    def add_week(week_key, end_dt, since, until, label=""):
        if week_key in seen:
            print(f"skip {week_key} (already in history)")
            return
        print(f"computing week {week_key} ({label}) ...", end=" ", flush=True)
        stats = compute_week(repos, since, until, args.max_commits)
        history.setdefault("weeks", []).append({"week": week_key, "repos": stats})
        seen.add(week_key)
        active = sum(1 for s in stats.values() if s["added"] or s["deleted"])
        print(f"{active} active repos")

    cur_key = monday_of(now).isoformat()
    add_week(cur_key, now, (now - dt.timedelta(days=args.days)).isoformat(), now.isoformat(), "current")

    for k in range(1, args.backfill + 1):
        end = now - dt.timedelta(days=7 * k)
        week_key = monday_of(end).isoformat()
        since = (end - dt.timedelta(days=args.days)).isoformat()
        add_week(week_key, end, since, end.isoformat(), f"backfill {k}")

    history["weeks"].sort(key=lambda w: w["week"])

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    cur = history["weeks"][-1]["repos"] if history["weeks"] else {}
    out = {"generated_at": now.isoformat()}
    out.update(cur)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2, sort_keys=True)
    with open(args.history, "w") as f:
        json.dump(history, f, indent=2, sort_keys=True)
    print(f"wrote {args.out} + {args.history}: {len(history['weeks'])} weeks in history")


if __name__ == "__main__":
    main()
