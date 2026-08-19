#!/usr/bin/env python3
"""Weekly GitHub diff stats — lines added/deleted per owned repo, last N days.

Aggregates commit-level additions/deletions across the user's owned
(non-fork, non-archived) repositories and writes a JSON object:

    {
      "generated_at": "2026-08-19T18:00:00+00:00",
      "repo-name": {"added": 1240, "deleted": 318, "net": 922},
      ...
    }

Every owned repo is included (zeros are kept so the Homepage table is
complete and can compute totals). Requires GH_TOKEN (fine-grained PAT with
read access to repositories).
"""
import argparse
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request

API = "https://api.github.com"


def gh(path):
    req = urllib.request.Request(f"{API}{path}")
    req.add_header("Authorization", f"Bearer {os.environ['GH_TOKEN']}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out", default="stats/weekly.json")
    ap.add_argument("--max-commits", type=int, default=200)
    args = ap.parse_args()

    since = (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)
    ).isoformat()

    try:
        repos = gh("/user/repos?affiliation=owner&per_page=100&sort=updated")
    except Exception as e:
        print(f"FATAL: cannot list repos ({e}); check GH_TOKEN scope", file=sys.stderr)
        sys.exit(1)
    repos = [r for r in repos if not r["fork"] and not r["archived"]]

    stats = {}
    for repo in repos:
        name = repo["name"]
        branch = repo["default_branch"]
        try:
            commits = []
            page = 1
            while len(commits) < args.max_commits:
                url = (
                    f"/repos/{repo['full_name']}/commits?sha={branch}"
                    f"&since={urllib.parse.quote(since)}&per_page=100&page={page}"
                )
                batch = gh(url)
                if not batch:
                    break
                commits.extend(batch)
                if len(batch) < 100:
                    break
                page += 1
            commits = commits[: args.max_commits]

            added = deleted = 0
            for c in commits:
                msg = (c.get("commit", {}).get("message", "") or "")
                if msg.startswith("Merge "):
                    continue  # squash-merge PRs already attribute to the merge commit
                detail = gh(f"/repos/{repo['full_name']}/commits/{c['sha']}")
                added += detail.get("stats", {}).get("additions", 0)
                deleted += detail.get("stats", {}).get("deletions", 0)

            # always include the repo (zeros kept, totals computed client-side)
            stats[name] = {"added": added, "deleted": deleted, "net": added - deleted}
        except Exception as e:
            print(f"WARN: skipping {name}: {e}", file=sys.stderr)

    out = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    out.update(stats)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2, sort_keys=True)
    print(f"wrote {args.out}: {len(stats)} repos (zeros included)")
    for name, s in sorted(stats.items()):
        print(f"  {name}: +{s['added']} -{s['deleted']} net {s['net']}")


if __name__ == "__main__":
    main()
