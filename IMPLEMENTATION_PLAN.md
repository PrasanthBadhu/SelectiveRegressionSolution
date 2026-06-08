# Selective Regression Testing — Implementation Plan

## 1. Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  tr/cobalt_search  (READ-ONLY — no changes)                                 │
│  ┌─────────────────────────────────────────────────────┐                    │
│  │  Developer creates / updates a Pull Request         │                    │
│  │  Changed files: CobaltPlatformSearch/…, WLNSearch/… │                    │
│  └────────────────────────────┬────────────────────────┘                    │
└───────────────────────────────┼─────────────────────────────────────────────┘
                                │ (GitHub API, read-only polling)
                                ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  tr/CobaltRegressionTesting  (GitHub Actions host)                          │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  pr-watcher-scheduled.yml   (NEW — runs every 5 minutes)             │   │
│  │                                                                      │   │
│  │  1. Read config/repo-registry.yml                                    │   │
│  │     → list of source repos (cobalt_search + future repos)            │   │
│  │                                                                      │   │
│  │  2. Restore per-repo state from state-tracking branch               │   │
│  │     state/repos/<repo>/last_seen_prs.json                           │   │
│  │                                                                      │   │
│  │  3. For each repo: pr_impact_analyzer.py --repo <full_name>          │   │
│  │     → compares head SHA vs. last seen SHA                            │   │
│  │     → outputs JSON array of new/changed PRs only                    │   │
│  │                                                                      │   │
│  │  4. For each new/changed PR: feature_test_mapper.py                  │   │
│  │     → fetches feature-map.yml from tr/Seven-Kingdoms (GitHub API)   │   │
│  │     → maps changed files → TestCategory → WL_DNet_*.yml             │   │
│  │                                                                      │   │
│  │  5. Dispatch selective-regression.yml (once per PR)                  │   │
│  │     → passes pr_number, dotnet_workflows, TEST_ENVIRONMENT           │   │
│  │                                                                      │   │
│  │  6. Commit updated state to state-tracking branch                   │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                   │                                                          │
│                   ▼                                                          │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  selective-regression.yml   (MINOR UPDATE — added source_repo input) │   │
│  │  → dispatches each WL_DNet_*.yml workflow via workflow_dispatch       │   │
│  └───────────────────────────────┬──────────────────────────────────────┘   │
│                                  │                                           │
│                   ┌──────────────┴───────────────┐                          │
│                   ▼              ▼               ▼                           │
│          WL_DNet_Edge_     WL_DNet_Next_    WL_DNet_ANZ_…                   │
│          CoreSearch.yml    SearchCore.yml                                    │
│          (runs on AWS EC2 via CodeBuild runner)                              │
└──────────────────────────────────────────────────────────────────────────────┘
                   ▲
                   │ (fetches feature-map.yml)
┌──────────────────────────────────────────────────────────────────────────────┐
│  tr/Seven-Kingdoms                                                           │
│  feature-map.yml  (NO CHANGES — already complete)                           │
│  Maps: module/sub_path/keyword → TestCategory → WL_DNet_*.yml               │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Two complementary workflows

| Workflow | Trigger | PRs covered | Purpose |
|---|---|---|---|
| `pr-watcher-scheduled.yml` | Every 5 min + manual | **Open** PRs (new/updated) | Pre-merge quality gate |
| `pr-poller.yml` (existing, unchanged) | Manual only | **Merged** PRs (lookback window) | Post-merge regression sweep |

---

## 2. Mapping Chain (unchanged from existing design)

```
cobalt_search changed files
    │
    ├─ module prefix match  (e.g. CobaltPlatformSearch/)
    ├─ sub-path match       (e.g. WLNSearch/…/aunz/)
    └─ keyword match        (PR title + body)
         │
         ▼
    TestCategory names      (feature-map.yml in Seven-Kingdoms)
         │
         ▼
    WL_DNet_*.yml workflows (CAT_TO_WORKFLOW in feature_test_mapper.py)
         │
         ▼
    selective-regression.yml dispatches each workflow
         │
         ▼
    WL_DNet tests run on AWS EC2 (CodeBuild runner)
```

---

## 3. File Inventory

### What goes in `tr/CobaltRegressionTesting`

| File | Status | Action |
|---|---|---|
| `.github/workflows/pr-watcher-scheduled.yml` | **NEW** | Copy from `CobaltRegressionTesting/.github/workflows/` in this solution |
| `.github/workflows/selective-regression.yml` | **UPDATED** | Replace existing — adds optional `source_repo` input |
| `config/repo-registry.yml` | **NEW** | Copy from `CobaltRegressionTesting/config/` in this solution |
| `tools/pr_impact_analyzer.py` | **UPDATED** | Replace existing — adds `--repo`, `--state-dir`, `--force-prs` CLI flags |
| `.github/workflows/pr-poller.yml` | **UNCHANGED** | No changes required |
| `tools/feature_test_mapper.py` | **UNCHANGED** | No changes required |
| `tools/requirements.txt` | **UNCHANGED** | No changes required |

### What goes in `tr/Seven-Kingdoms`

| File | Status | Action |
|---|---|---|
| `feature-map.yml` | **UNCHANGED** | No changes required — already complete and up-to-date |

### What stays in `tr/cobalt_search`

| File | Status | Action |
|---|---|---|
| *Everything* | **NO CHANGES** | Read-only. No modifications ever. |

---

## 4. Step-by-Step Deployment

### Prerequisites
Ensure these GitHub Secrets exist in `tr/CobaltRegressionTesting` (Settings → Secrets → Actions):

| Secret | Permission | Used by |
|---|---|---|
| `COBALT_READ_TOKEN` | `read:repo` on `tr/cobalt_search` | pr-watcher-scheduled, pr-poller |
| `SEVEN_KINGDOMS_TOKEN` | `read:repo` on `tr/Seven-Kingdoms` | pr-watcher-scheduled, pr-poller |
| `REGRESSION_TRIGGER_PAT` | `workflow:write` on `tr/CobaltRegressionTesting` | pr-watcher-scheduled, pr-poller, selective-regression |

### Deployment Steps

**Step 1 — Create `state-tracking` branch**
```bash
# In tr/CobaltRegressionTesting
git checkout main
git checkout -b state-tracking
git push origin state-tracking
```
This branch holds all runtime state (JSON files). It is never merged back to main.

**Step 2 — Deploy `config/repo-registry.yml`**
```bash
# Copy from C:\SelectiveRegressionSolution\CobaltRegressionTesting\config\repo-registry.yml
# into tr/CobaltRegressionTesting/config/repo-registry.yml
git add config/repo-registry.yml
git commit -m "feat: add repo-registry for multi-repo PR watching"
git push origin main
```

**Step 3 — Deploy `tools/pr_impact_analyzer.py` (updated)**
```bash
# Replace tr/CobaltRegressionTesting/tools/pr_impact_analyzer.py
# with the updated version from this solution
git add tools/pr_impact_analyzer.py
git commit -m "feat: add --repo, --state-dir, --force-prs flags to pr_impact_analyzer"
git push origin main
```

**Step 4 — Deploy `selective-regression.yml` (minor update)**
```bash
# Replace .github/workflows/selective-regression.yml
git add .github/workflows/selective-regression.yml
git commit -m "feat: add source_repo input to selective-regression workflow"
git push origin main
```

**Step 5 — Deploy `pr-watcher-scheduled.yml` (new)**
```bash
# Add .github/workflows/pr-watcher-scheduled.yml
git add .github/workflows/pr-watcher-scheduled.yml
git commit -m "feat: add scheduled PR watcher for automatic selective regression"
git push origin main
```
The schedule trigger activates automatically once the workflow is on the default branch.

**Step 6 — Smoke test (manual dry run)**
```
GitHub UI → tr/CobaltRegressionTesting → Actions → "PR Watcher - Scheduled"
  → Run workflow → dry_run: true → Run
```
Verify the job summary shows detected PRs and their mapped workflows without triggering any actual test runs.

**Step 7 — Go live**
```
GitHub UI → Actions → "PR Watcher - Scheduled"
  → Run workflow → dry_run: false → Run
```
Confirm that `selective-regression.yml` runs are dispatched and WL_DNet workflows start.

---

## 5. Expected Workflow — End to End

```
T+0:00   Developer opens (or pushes new commit to) a PR in tr/cobalt_search
         PR changes files in CobaltPlatformSearch/ and WLNSearch/…/aunz/

T+0–5m  pr-watcher-scheduled.yml fires (cron: */5 * * * *)

T+0:00s  Restore state: pulls state/repos/cobalt_search/last_seen_prs.json
          from state-tracking branch

T+0:05s  pr_impact_analyzer.py --repo tr/cobalt_search
          --state-dir state/repos/cobalt_search
         → PR head SHA differs from last_seen → PR flagged as new/updated
         → Writes impact JSON:
           {pr_number, modules_affected:[CobaltPlatformSearch, WLNSearch],
            sub_products:[aunz], risk_level:medium, change_type:feature, ...}

T+0:20s  feature_test_mapper.py --impact ... --output ...
         → Fetches feature-map.yml from Seven-Kingdoms via GitHub API
         → CobaltPlatformSearch → [CoreSearch, GlobalSearch, Search4KUiIndigo, ...]
         → WLNSearch/…/aunz/ → [AnzEdgeRegression, AnzDocuments, AnzFacet, ...]
         → Maps to WL_DNet workflows:
           [WL_DNet_Edge_CoreSearch, WL_DNet_Edge_Search_Global,
            WL_DNet_ANZ_AnzSearch, WL_DNet_ANZ_AnzDocument, ...]

T+0:30s  selective-regression.yml dispatched with:
           pr_number=<N>, dotnet_workflows=<list>, TEST_ENVIRONMENT=DEMO

T+0:45s  selective-regression.yml dispatches each WL_DNet_*.yml via workflow_dispatch

T+1–30m  WL_DNet_*.yml workflows run on AWS EC2 (CodeBuild runner)
          Each runs its .bat file (e.g. CoreSearch_Edge.bat)
          Results appear in GitHub Actions run summaries

T+end    State committed back to state-tracking branch:
          state/repos/cobalt_search/last_seen_prs.json updated
          state/repos/cobalt_search/pr_impacts/pr_<N>.json written
          state/repos/cobalt_search/test_plans/pr_<N>.json written
```

---

## 6. State Management

### State directory layout (on `state-tracking` branch)

```
state/
├── repos/
│   └── cobalt_search/
│       ├── last_seen_prs.json          # {pr_number: {head_sha, last_triggered}}
│       ├── pr_impacts/
│       │   ├── pr_2460.json            # full impact dict per PR
│       │   └── pr_2461.json
│       └── test_plans/
│           ├── pr_2460.json            # test plan: categories + workflows
│           └── pr_2461.json
├── prs_to_process.json                 # transient: current run only
└── all_impacted_workflows.json         # transient: current run only
```

### Change detection logic

`pr_impact_analyzer.py` compares `pr.head.sha` against the stored `head_sha` in `last_seen_prs.json`.  A PR is re-processed only when:
- It is seen for the first time, OR
- Its head SHA has changed (new commit pushed), OR
- `--force-prs` explicitly includes its number.

This prevents re-triggering tests for unchanged PRs on every 5-minute poll.

---

## 7. Scaling to Additional Repositories

To add a new developer repository (e.g. `tr/cobalt_documents`):

1. **Add entry to `config/repo-registry.yml`**
   ```yaml
   - name:              cobalt_documents
     full_name:         tr/cobalt_documents
     enabled:           true
     read_token_secret: COBALT_READ_TOKEN   # or a new secret if different PAT needed
     feature_map_repo:  tr/Seven-Kingdoms
     feature_map_path:  feature-map-documents.yml   # new map file
     test_environment:  DEMO
     lookback_days:     7
   ```

2. **Add `feature-map-documents.yml` to `tr/Seven-Kingdoms`**
   Follow the same schema as `feature-map.yml` — define modules, sub_paths, keywords, and test_categories for the new repo's structure.

3. **Add a GitHub Secret** (`COBALT_READ_TOKEN` usually suffices if on same org)

4. **Merge to main** — the next scheduled run picks it up automatically. No workflow changes needed.

---

## 8. Secrets Configuration Reference

```
tr/CobaltRegressionTesting → Settings → Secrets and variables → Actions
```

| Secret name | Scope | Notes |
|---|---|---|
| `COBALT_READ_TOKEN` | read:repo on tr/cobalt_search | Also used for any new repo unless overridden |
| `SEVEN_KINGDOMS_TOKEN` | read:repo on tr/Seven-Kingdoms | Used by feature_test_mapper.py |
| `REGRESSION_TRIGGER_PAT` | workflow:write on tr/CobaltRegressionTesting | Dispatches workflows + commits state |

---

## 9. Risk Escalation Rules (from feature-map.yml)

| Condition | Effect |
|---|---|
| Module has `risk_multiplier: high` | Medium risk floor applied |
| PR title/body matches HIGH_RISK_PATTERNS | Risk elevated to **high** |
| Risk level = `high` | `CoreSearch`, `GlobalSearch`, `EdgeSmokeFeatures` always added |
| Change type = `docs` | `skip_all: true` — no tests triggered |
| Change type = `test` | Integration tests skipped (smoke only) |
| Change type = `chore` | Only `CoreSearch` runs |
| No categories matched | Fallback: `CoreSearch` + `EdgeSmokeFeatures` |

---

## 10. Assumptions and Known Constraints

| Item | Detail |
|---|---|
| tr/cobalt_search is read-only | Solved by polling from CobaltRegressionTesting — no webhook setup needed in cobalt_search |
| GitHub API rate limits | pr_impact_analyzer.py uses PyGithub which handles rate limiting. With ≤100 open PRs and a 5-min schedule, rate limits will not be hit. |
| Schedule frequency | `*/5 * * * *` = 12 runs/hour. GitHub free tier: 2,000 minutes/month. Each run takes ≤2 min → well within limits. |
| WL_DNet workflow env aliases | Some accept `Demo`, others `DEMO`. selective-regression.yml tries both — existing behaviour preserved. |
| feature-map.yml updates | Because feature_test_mapper.py fetches it via GitHub API at runtime, any change to feature-map.yml in Seven-Kingdoms is picked up immediately on the next PR poll. |
| state-tracking branch conflicts | Each run uses GraphQL `createCommitOnBranch` which requires the current HEAD OID. Concurrent runs could race. If this becomes an issue, add a mutex via a workflow concurrency group. |
| Concurrency group (recommended) | Add to pr-watcher-scheduled.yml: `concurrency: { group: pr-watcher, cancel-in-progress: false }` to prevent overlapping runs. |

---

## 11. Quick Reference — File Locations

```
C:\SelectiveRegressionSolution\
│
├── CobaltRegressionTesting\                    ← Deploy to: tr/CobaltRegressionTesting
│   ├── .github\workflows\
│   │   ├── pr-watcher-scheduled.yml            ← NEW
│   │   └── selective-regression.yml            ← UPDATED (source_repo input added)
│   ├── config\
│   │   └── repo-registry.yml                   ← NEW
│   └── tools\
│       └── pr_impact_analyzer.py               ← UPDATED (--repo, --state-dir, --force-prs)
│
└── Seven-Kingdoms\                             ← Deploy to: tr/Seven-Kingdoms
    └── feature-map.yml                         ← REFERENCE (no changes)

Existing files — NO CHANGES needed:
  tr/CobaltRegressionTesting/.github/workflows/pr-poller.yml
  tr/CobaltRegressionTesting/tools/feature_test_mapper.py
  tr/CobaltRegressionTesting/tools/requirements.txt
  tr/Seven-Kingdoms/feature-map.yml
```
