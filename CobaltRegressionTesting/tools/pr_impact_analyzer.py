#!/usr/bin/env python3
"""
pr_impact_analyzer.py  (updated: multi-repo CLI flags)
=======================================================
Polls a GitHub repository for open (and recently merged) PRs, compares
against the last-seen state, and for each NEW or UPDATED PR:
  1. Fetches changed file paths from the GitHub API
  2. Runs heuristic impact analysis (modules, products, risk)
  3. Writes a per-PR impact JSON to <state_dir>/pr_impacts/pr_<N>.json
  4. Prints a JSON array of new/updated PR dicts to stdout (consumed by caller)
  5. Updates <state_dir>/last_seen_prs.json with the latest head SHA per PR

Changes vs. original:
  - Added  --repo      (default: tr/cobalt_search)  so any registered repo can be scanned
  - Added  --state-dir (default: original path)      so state is kept per-repo
  - Added  --force-prs (comma-separated PR numbers)  to force re-analysis without SHA change
  - All detection logic is UNCHANGED (same module prefixes, risk heuristics, etc.)

Called by: pr-watcher-scheduled.yml (scheduled/manual)
Also used by: pr-poller.yml (merged-PR path, existing behaviour preserved)
"""

import os, sys, json, re, argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from github import Github, GithubException

# ---------------------------------------------------------------------------
# Defaults (preserved from original for backwards compatibility)
# ---------------------------------------------------------------------------
_DEFAULT_REPO      = "tr/cobalt_search"
_DEFAULT_STATE_DIR = Path(__file__).parent.parent / "state"

# ---------------------------------------------------------------------------
# Module -> file-path prefix mapping (mirrors cobalt_search structure)
# If monitoring a different repo, the caller may override via a subclass or
# by extending MODULE_PREFIXES via registry config in a future version.
# ---------------------------------------------------------------------------
MODULE_PREFIXES = {
    "SearchCommon":          "SearchCommon/",
    "SearchMetadataObjects": "SearchMetadataObjects/",
    "SearchSerialized":      "SearchSerialized/",
    "CarswellEcosystem":     "CarswellEcosystem/",
    "CobaltPlatformSearch":  "CobaltPlatformSearch/",
    "CarswellSearchWeb":     "CarswellSearchWeb/",
    "TNPCarswellSearchWeb":  "TNPCarswellSearchWeb/",
    "WFASearchWeb":          "WFASearchWeb/",
    "WLNSearch":             "WLNSearch/",
    "CorrectionalSearch":    "CorrectionalSearch/",
    "DraftingSearch":        "DraftingSearch/",
    "WeblinksSearch":        "WeblinksSearch/",
}

# Sub-path -> product keyword (longest match wins)
SUB_PATH_PRODUCTS = {
    "WLNSearch/src/com/trgr/cobalt/search2/wln/aunz/":              "aunz",
    "WLNSearch/src/com/trgr/cobalt/search2/wln/wlglobal/":          "wlglobal",
    "WLNSearch/src/com/trgr/cobalt/search2/wln/content/casesuk/":   "wluk",
    "WLNSearch/src/com/trgr/cobalt/search2/wln/content/docketuk/":  "wluk",
    "WLNSearch/src/com/trgr/cobalt/search2/wln/content/researchuk/":"wluk",
    "WLNSearch/src/com/trgr/cobalt/wln/search/uk/":                 "wluk",
    "WLNSearch/src/com/trgr/cobalt/search2/wln/publicrecords/":     "publicrecords",
    "WLNSearch/src/com/trgr/cobalt/search2/wln/result/service/WLUK":"wluk",
}

CHANGE_TYPE_MAP = [
    (r"^feat",     "feature"),
    (r"^fix",      "bug_fix"),
    (r"^bug",      "bug_fix"),
    (r"^refactor", "refactor"),
    (r"^test",     "test"),
    (r"^docs?",    "docs"),
    (r"^chore",    "chore"),
    (r"^ci",       "chore"),
    (r"^build",    "chore"),
    (r"^breaking", "breaking_change"),
]

HIGH_RISK_PATTERNS = [
    r"breaking", r"migration", r"schema", r"serializ", r"api.?change",
    r"remove", r"deprecat", r"security", r"auth", r"critical",
]
MEDIUM_RISK_PATTERNS = [
    r"fix", r"search", r"query", r"index", r"filter", r"limit",
    r"performance", r"timeout", r"exception",
]
HIGH_RISK_MODULES = {"SearchCommon", "SearchSerialized", "CobaltPlatformSearch"}

LOOKBACK_DAYS = 7


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def load_state(state_file: Path) -> dict:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    if state_file.exists():
        try:
            return json.loads(state_file.read_text())
        except Exception:
            pass
    return {}   # {pr_number_str: {"head_sha": ..., "last_triggered": ...}}


def save_state(state: dict, state_file: Path) -> None:
    state_file.write_text(json.dumps(state, indent=2))


# ---------------------------------------------------------------------------
# Impact detection helpers
# ---------------------------------------------------------------------------

def detect_modules(file_paths: list) -> list:
    found = set()
    for fp in file_paths:
        for mod, prefix in MODULE_PREFIXES.items():
            if fp.startswith(prefix):
                found.add(mod)
    return sorted(found) or ["unknown"]


def detect_sub_products(file_paths: list) -> list:
    found = set()
    for fp in file_paths:
        for prefix, product in SUB_PATH_PRODUCTS.items():
            if fp.startswith(prefix):
                found.add(product)
    return sorted(found)


def detect_keyword_products(title: str, body: str) -> list:
    text = (title + " " + (body or "")).lower()
    found = set()
    kw_map = {
        "brazil": "brazil", "section symbol": "brazil",
        "wluk": "wluk", "uk companies": "wluk",
        "aunz": "aunz", "anz": "aunz",
        "phone plus": "publicrecords",
        "cad alert": "carswell", "cover page": "carswell",
        "citing": "carswell",
        "presearch": "platform", "advanced query": "platform",
        "facet": "wln",
    }
    for kw, product in kw_map.items():
        if kw in text:
            found.add(product)
    return sorted(found)


def detect_change_type(title: str) -> str:
    for pattern, ctype in CHANGE_TYPE_MAP:
        if re.search(pattern, title, re.IGNORECASE):
            return ctype
    return "chore"


def detect_risk(title: str, body: str, modules: list) -> str:
    combined = (title + " " + (body or "")).lower()
    for p in HIGH_RISK_PATTERNS:
        if re.search(p, combined):
            return "high"
    if any(m in HIGH_RISK_MODULES for m in modules):
        return "medium"
    for p in MEDIUM_RISK_PATTERNS:
        if re.search(p, combined):
            return "medium"
    return "low"


def analyze_pr(pr, file_paths: list) -> dict:
    modules      = detect_modules(file_paths)
    sub_products = detect_sub_products(file_paths)
    kw_products  = detect_keyword_products(pr.title, pr.body or "")
    change_type  = detect_change_type(pr.title)
    risk         = detect_risk(pr.title, pr.body or "", modules)
    all_products = sorted(set(sub_products + kw_products) or {"platform"})

    return {
        "pr_number":        pr.number,
        "pr_title":         pr.title,
        "pr_author":        pr.user.login if pr.user else "unknown",
        "pr_url":           pr.html_url,
        "head_sha":         pr.head.sha,
        "base_branch":      pr.base.ref,
        "state":            pr.state,
        "created_at":       pr.created_at.isoformat() if pr.created_at  else None,
        "updated_at":       pr.updated_at.isoformat() if pr.updated_at  else None,
        "merged_at":        pr.merged_at.isoformat()  if pr.merged_at   else None,
        "labels":           [lb.name for lb in pr.labels],
        "changed_files":    pr.changed_files,
        "additions":        pr.additions,
        "deletions":        pr.deletions,
        "file_paths":       file_paths,
        "modules_affected": modules,
        "sub_products":     sub_products,
        "keyword_products": kw_products,
        "all_products":     all_products,
        "change_type":      change_type,
        "risk_level":       risk,
        "analyzed_at":      datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect new/updated PRs in a GitHub repo and emit impact JSON.")
    parser.add_argument(
        "--repo",
        default=_DEFAULT_REPO,
        help="GitHub owner/repo to scan (default: tr/cobalt_search)")
    parser.add_argument(
        "--state-dir",
        default=str(_DEFAULT_STATE_DIR),
        help="Directory for last_seen_prs.json and pr_impacts/ (default: ../state)")
    parser.add_argument(
        "--force-prs",
        default="",
        help="Comma-separated PR numbers to force re-analysis regardless of SHA")
    args = parser.parse_args()

    gh_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("COBALT_READ_TOKEN")
    if not gh_token:
        print("ERROR: GITHUB_TOKEN or COBALT_READ_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    state_dir   = Path(args.state_dir)
    state_file  = state_dir / "last_seen_prs.json"
    impacts_dir = state_dir / "pr_impacts"

    force_pr_set = {int(p) for p in args.force_prs.split(",") if p.strip().isdigit()}

    g    = Github(gh_token)
    repo = g.get_repo(args.repo)

    state          = load_state(state_file)
    impacts_dir.mkdir(parents=True, exist_ok=True)

    cutoff_lookback = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    cutoff_merged   = datetime.now(timezone.utc) - timedelta(hours=24)
    prs_to_trigger  = []

    def process_pr(pr):
        pr_key      = str(pr.number)
        current_sha = pr.head.sha
        seen        = state.get(pr_key, {})

        is_forced   = pr.number in force_pr_set

        if seen.get("head_sha") == current_sha and not is_forced:
            return  # already processed this exact commit

        flag = "[FORCED]" if is_forced else "[NEW/UPDATED]"
        print(f"  {flag} PR #{pr.number}: {pr.title[:70]}", file=sys.stderr)

        try:
            file_paths = [f.filename for f in pr.get_files()]
        except GithubException as e:
            print(f"  Warning: could not get files for PR #{pr.number}: {e}", file=sys.stderr)
            file_paths = []

        impact = analyze_pr(pr, file_paths)

        impact_file = impacts_dir / f"pr_{pr.number}.json"
        impact_file.write_text(json.dumps(impact, indent=2))

        prs_to_trigger.append(impact)

        state[pr_key] = {
            "head_sha":       current_sha,
            "last_triggered": datetime.now(timezone.utc).isoformat(),
            "pr_title":       pr.title,
        }

    # Scan open PRs (the primary path for pre-merge quality gates)
    for pr in repo.get_pulls(state="open", sort="updated", direction="desc"):
        if pr.updated_at and pr.updated_at < cutoff_lookback:
            break
        process_pr(pr)

    # Also scan PRs merged in the last 24 hours (post-merge safety net)
    for pr in repo.get_pulls(state="closed", sort="updated", direction="desc"):
        if pr.merged_at is None:
            continue
        if pr.merged_at < cutoff_merged:
            break
        print(f"  [MERGED] PR #{pr.number}: {pr.title[:70]}", file=sys.stderr)
        process_pr(pr)

    save_state(state, state_file)

    # Output JSON array to stdout for the calling workflow to consume
    print(json.dumps(prs_to_trigger, indent=2))


if __name__ == "__main__":
    main()
