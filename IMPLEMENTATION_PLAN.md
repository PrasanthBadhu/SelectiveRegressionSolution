# Selective Regression Testing — Implementation Plan

## 1. Architecture Overview

```
┌─────────────────────────┐  ┌─────────────────────────┐  ┌─────────────────────────┐
│  tr/cobalt_search        │  │  tr/cobalt_website       │  │  tr/cobalt_static-content│
│  (READ-ONLY)             │  │  (READ-ONLY)             │  │  (READ-ONLY)             │
│  Developer opens a PR    │  │  Developer opens a PR    │  │  Developer opens a PR    │
└───────────┬─────────────┘  └───────────┬─────────────┘  └───────────┬─────────────┘
            │                            │                             │
            └────────────────────────────┼─────────────────────────────┘
                                         │  GitHub API (read-only polling)
                                         ▼
┌──────────────────────────────────────────────────────────────────────────────────────┐
│  tr/CobaltRegressionTesting  (GitHub Actions host)                                   │
│                                                                                      │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │  pr-poller.yml   (manual dispatch)                                  │   │
│  │                                                                              │   │
│  │  1. Read config/repo-registry.yml                                            │   │
│  │     → 3 source repos: cobalt_search, cobalt_website, cobalt_static-content  │   │
│  │                                                                              │   │
│  │  2. Restore per-repo state from state-tracking branch                       │   │
│  │     state/repos/<repo>/last_seen_prs.json                                   │   │
│  │                                                                              │   │
│  │  3. For each repo: pr_impact_analyzer.py                                    │   │
│  │        --repo <full_name>                                                    │   │
│  │        --feature-map config/feature-map[-<repo>].yml   ← LOCAL file         │   │
│  │        --state-dir state/repos/<repo>                                        │   │
│  │     → compares head SHA vs. last seen SHA                                   │   │
│  │     → maps changed file paths → modules / sub_paths / keywords              │   │
│  │     → outputs impact JSON per PR                                            │   │
│  │                                                                              │   │
│  │  4. For each new/changed PR: feature_test_mapper.py                         │   │
│  │     → reads per-repo feature-map via --feature-map flag (local copy)        │   │
│  │     → maps TestCategory names → WL_DNet_*.yml workflows                    │   │
│  │     → uses CAT_TO_WORKFLOW dict (248 entries) in feature_test_mapper.py     │   │
│  │                                                                              │   │
│  │  5. Dispatch selective-regression.yml (once per PR, per repo)               │   │
│  │     → passes pr_number, source_repo, dotnet_workflows, TEST_ENVIRONMENT     │   │
│  │                                                                              │   │
│  │  6. Commit updated state to state-tracking branch                           │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
│                   │                                                                  │
│                   ▼                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │  selective-regression.yml   (workflow_dispatch — adds source_repo input)     │   │
│  │  → dispatches each WL_DNet_*.yml workflow via workflow_dispatch              │   │
│  └───────────────────────────┬──────────────────────────────────────────────────┘   │
│                               │                                                      │
│           ┌───────────────────┼────────────────────┐                                │
│           ▼                   ▼                    ▼                                │
│  WL_DNet_Edge_       WL_DNet_Next_       WL_DNet_ANZ_…                              │
│  CoreSearch.yml      SearchCore.yml                                                  │
│  (runs on AWS EC2 via CodeBuild runner)                                              │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

### Three feature maps — one per source repo

| Source Repo | Feature Map (local) | Fetched from (fallback) |
|---|---|---|
| tr/cobalt_search | `config/feature-map-search.yml` | tr/Seven-Kingdoms `feature-map-search.yml` |
| tr/cobalt_website | `config/feature-map-website.yml` | tr/Seven-Kingdoms `feature-map-website.yml` |
| tr/cobalt_static-content | `config/feature-map-static-content.yml` | tr/Seven-Kingdoms `feature-map-static-content.yml` |

### Two complementary workflows

| Workflow | Trigger | PRs covered | Purpose |
|---|---|---|---|
| `pr-poller.yml` | Manual only | **Merged** PRs (lookback window) | Post-merge regression sweep |

---

## 2. Mapping Chain

```
source-repo changed files   (cobalt_search | cobalt_website | cobalt_static-content)
    │
    ├─ sub_path match   (longest prefix wins — highest priority)
    ├─ module match     (top-level folder prefix)
    └─ keyword match    (PR title + body, case-insensitive)
         │
         ▼
    TestCategory names   (from the repo's feature-map-*.yml)
         │
         ▼
    WL_DNet_*.yml workflows   (CAT_TO_WORKFLOW dict in feature_test_mapper.py, 248 entries)
         │
         ▼
    selective-regression.yml dispatches each matched workflow
         │
         ▼
    WL_DNet tests run on AWS EC2 (CodeBuild runner)
```

---

## 3. Feature Map Coverage (as of 2026-06-09)

### feature-map-search.yml  (cobalt_search)

| Section | Count | Notes |
|---|---|---|
| Modules | 12 | SearchCommon, SearchMetadataObjects, SearchSerialized, CarswellEcosystem, CobaltPlatformSearch, CarswellSearchWeb, TNPCarswellSearchWeb, WFASearchWeb, WLNSearch, CorrectionalSearch, DraftingSearch, WeblinksSearch |
| Sub-paths | 8 | All within WLNSearch: aunz, wlglobal, casesuk, docketuk, researchuk, wluk, publicrecords, WLUK result service |
| Keywords | 30+ | brazil, wluk, aunz, anz, canada, enhancements, blc, business law, docket, keycite, portal manager, court express, california, alerts, document, delivery, precision, advantage, analytics, related info, foldering, annotation, quick check, tax migration, website, redlining, research report, smart folder, 10k, search 4k, trillium |
| high_risk_always_add | 3 | CoreSearch, GlobalSearch, EdgeSmokeFeatures |

### feature-map-website.yml  (cobalt_website)

| Section | Count | Notes |
|---|---|---|
| Modules | 19 | WLNWebsite, WLNWebsiteCommon, CobaltPlatformWeb (high-risk), CarswellWebsite, ANZWebsite, WFAWebsite, WebsiteDelivery, WebsiteMobile, WebsiteAlerts, WebsiteFoldering, WebsiteAnalytics, WebsitePrecision, WebsiteKeyCite, WebsiteAnnotations, WebsiteResearchReports, WebsiteRedlining, WebsiteQuickCheck, WebsiteWeblinks, WebsiteEnhancements |
| Sub-paths | 22+ | Top-level module shortcuts + deep Java package paths under WLNWebsite/src/main/java/com/tr/cobalt/web/<feature>/ |
| Keywords | 35+ | website, homepage, navigation, delivery, mobile, search, aunz, anz, canada, alert, folder, analytics, precision, advantage, keycite, key cite, related info, annotation, highlight, redlining, quick check, research report, smart folder, trillium, enhancements, blc, business law, tax, tax migration, docket, california, weblinks, portal manager, court express, document, wluk, 10k, search 4k |
| high_risk_always_add | 5 | CoreSearch, GlobalSearch, EdgeSmokeFeatures, WebsiteCore1, WebsiteCore2 |

### feature-map-static-content.yml  (cobalt_static-content)

| Section | Count | Notes |
|---|---|---|
| Modules | 17 | CommonStaticContent, WLNStaticContent, CobaltPlatformStaticContent (high-risk), CarswellStaticContent, ANZStaticContent, WFAStaticContent, StaticContentDelivery, StaticContentMobile, StaticContentAlerts, StaticContentAnalytics, StaticContentPrecision, StaticContentFoldering, StaticContentKeyCite, StaticContentAnnotations, StaticContentResearchReports, StaticContentRedlining, StaticContentWeblinks |
| Sub-paths | 40+ | Typed by content type (css/, js/, templates/) AND product area: CommonStaticContent/css|js|templates, WLNStaticContent/css/common, plus product-specific paths for aunz, canada, mobile, delivery, alerts, analytics, folder, precision, keycite, annotation, homepage, redlining, researchreports, weblinks, tax, blc |
| Keywords | 35+ | Same as website map plus: css, template, static, responsive |
| high_risk_always_add | 5 | CoreSearch, GlobalSearch, EdgeSmokeFeatures, WebsiteCore1, WebsiteCore2 |

### CAT_TO_WORKFLOW coverage summary (248 total entries)

| Category | Count | Examples |
|---|---|---|
| Covered in all 3 maps | ~145 | ANZ suite, Canada suite, Analytics, Precision, Foldering, KeyCite, Annotations, Alerts, Delivery, Redlining, QuickCheck, ResearchReports, BLC, Tax, Weblinks, Website Core |
| cobalt_search map only (intentional) | 13 | AdvancedSearchTemplate, BrowsePageSearch, MultipleSearchWithin_Edge, SearchCore, SearchMetadata, SearchblePdfs, SmartSearch, WlnEdgeSearch, WLNCorrectional, Foldering (Edge variant), AnzUnderDevelopment, AnzUnderDevelopment1, KeyCiteTestFlag |
| In website but **missing from static-content** | 8 | QuickCheckUiCheckWork_1–4, QuickCheckUiJudicial_1–3, QuickCheckUiOpponent ← **known gap** |
| Not in any map | ~82 | All 18 Axe integration tests + search/UI-specific tests (see §10) |

---

## 4. File Inventory

### What goes in `tr/CobaltRegressionTesting`

| File | Status | Change Summary |
|---|---|---|
| `.github/workflows/selective-regression.yml` | **UPDATED** | Added optional `source_repo` input; null-safe `classify_file` |
| `.github/workflows/pr-poller.yml` | **UPDATED** | Same null-safe `classify_file` fix applied |
| `config/repo-registry.yml` | **NEW** | Registers cobalt_search, cobalt_website, cobalt_static-content |
| `config/feature-map-search.yml` | **UPDATED** | Fixed duplicate `analytics` keyword (was silently dropping 5 categories); added TrdSmoke |
| `config/feature-map-website.yml` | **NEW** | Full map: 19 modules, 22+ sub_paths, 35+ keywords |
| `config/feature-map-static-content.yml` | **NEW** | Full map: 17 modules, 40+ sub_paths, 35+ keywords |
| `tools/pr_impact_analyzer.py` | **UPDATED** | Added `--repo`, `--state-dir`, `--feature-map`, `--force-prs` flags; null-safe YAML loading |
| `tools/feature_test_mapper.py` | **UPDATED** | Null-safe YAML loading for all 5 feature-map sections |
| `.github/workflows/pr-poller.yml` | **UNCHANGED** | No changes required |
| `tools/requirements.txt` | **UNCHANGED** | No changes required |

### What goes in `tr/Seven-Kingdoms`

| File | Status | Action |
|---|---|---|
| `feature-map-search.yml` | **UPDATED** | Copy from `config/feature-map-search.yml` — same content, dual-homed for API fallback |
| `feature-map-website.yml` | **NEW** | Copy from `config/feature-map-website.yml` |
| `feature-map-static-content.yml` | **NEW** | Copy from `config/feature-map-static-content.yml` |

> Note: `feature_map_local` in repo-registry.yml points to local `config/` copies, so the Seven-Kingdoms API fetch is only a fallback. Both locations must be kept in sync.

### What stays in the source repos

| Repo | Action |
|---|---|
| tr/cobalt_search | **NO CHANGES** — read-only |
| tr/cobalt_website | **NO CHANGES** — read-only |
| tr/cobalt_static-content | **NO CHANGES** — read-only |

---

## 5. Code Fixes Applied

### Null-safety fix: YAML `modules:` / `sub_paths:` with no value

**Root cause:** YAML parses a key with no value (e.g. `modules:`) as Python `None`. `dict.get("key", {})` returns `None` when the key exists with a `None` value; `None.keys()` raises `AttributeError` and crashes the analyze step silently, producing no impact file and thus no changed files recorded.

**Fix:** All five feature-map section lookups changed from `fm.get("key", {})` to `(fm.get("key") or {})`:

```python
# tools/feature_test_mapper.py  (lines ~337-341)
fm_modules   = (feature_map.get("modules")             or {})
fm_sub_paths = (feature_map.get("sub_paths")           or {})
fm_keywords  = (feature_map.get("keywords")            or {})
fm_ct_rules  = (feature_map.get("change_type_rules")   or {})
fm_high_risk = (feature_map.get("high_risk_always_add") or {})
```

Same pattern applied in `tools/pr_impact_analyzer.py` and both workflow `classify_file` functions.

### Duplicate analytics keyword fix (feature-map-search.yml)

**Root cause:** Two `analytics:` entries in the keywords section. YAML silently drops the first when a key appears twice; the shorter second entry survived, losing `LegalAnalyticsApi`, `LitigationAnalytics`, `TrdLegalAnalyticsUi`, `TrdSmoke`, `TrdApi`, `TrdFacets`.

**Fix:** Removed the duplicate shorter entry. The surviving entry now contains all 8 analytics categories including `TrdSmoke`.

---

## 6. Step-by-Step Deployment

### Prerequisites — GitHub Secrets

Ensure these secrets exist in `tr/CobaltRegressionTesting` (Settings → Secrets → Actions):

| Secret | Permission | Used by |
|---|---|---|
| `COBALT_READ_TOKEN` | `read:repo` on all 3 source repos | pr-watcher-scheduled, pr-poller |
| `SEVEN_KINGDOMS_TOKEN` | `read:repo` on tr/Seven-Kingdoms | feature_test_mapper.py (API fallback) |
| `REGRESSION_TRIGGER_PAT` | `workflow:write` on tr/CobaltRegressionTesting | pr-watcher-scheduled, pr-poller, selective-regression |

> All three source repos (cobalt_search, cobalt_website, cobalt_static-content) share the same `COBALT_READ_TOKEN` — they are in the same org.

### Deployment Steps

**Step 1 — Create `state-tracking` branch**
```bash
# In tr/CobaltRegressionTesting
git checkout main
git checkout -b state-tracking
git push origin state-tracking
```

**Step 2 — Deploy config files**
```bash
git add config/repo-registry.yml
git add config/feature-map-search.yml            # updated (duplicate analytics fix)
git add config/feature-map-website.yml    # new
git add config/feature-map-static-content.yml  # new
git commit -m "feat: add multi-repo registry and feature maps for website and static-content"
git push origin main
```

**Step 3 — Deploy updated Python tools**
```bash
git add tools/pr_impact_analyzer.py   # --repo, --state-dir, --feature-map, --force-prs; null-safe
git add tools/feature_test_mapper.py  # null-safe YAML loading
git commit -m "feat: multi-repo support and null-safe feature map loading"
git push origin main
```

**Step 4 — Deploy updated workflow files**
```bash
git add .github/workflows/selective-regression.yml      # source_repo input; null-safe classify_file
git add .github/workflows/pr-poller.yml  # same null-safe classify_file fix
git commit -m "fix: null-safe classify_file; add source_repo input to selective-regression"
git push origin main
```

**Step 5 — Deploy pr-poller.yml**
```bash
git add .github/workflows/pr-poller.yml
git commit -m "feat: add manual PR poller for selective regression"
git push origin main
```

**Step 6 — Deploy feature maps to Seven-Kingdoms (fallback copies)**
```bash
# In tr/Seven-Kingdoms
cp <solution>/config/feature-map-search.yml .
cp <solution>/config/feature-map-website.yml .
cp <solution>/config/feature-map-static-content.yml .
git add feature-map-search.yml feature-map-website.yml feature-map-static-content.yml
git commit -m "feat: add website and static-content feature maps"
git push origin main
```

**Step 7 — Smoke test (dry run)**
```
GitHub UI → tr/CobaltRegressionTesting → Actions → "PR Watcher - Scheduled"
  → Run workflow → dry_run: true → Run
```
Verify the job summary shows detected PRs from all 3 repos and their mapped workflows, without triggering actual test runs.

**Step 8 — Go live**
```
GitHub UI → Actions → "PR Watcher - Scheduled"
  → Run workflow → dry_run: false → Run
```

---

## 7. Expected Workflow — End to End (example: cobalt_website PR)

```
T+0:00   Developer opens a PR in tr/cobalt_website
         Changed files include: WLNWebsite/src/main/java/com/tr/cobalt/web/analytics/...

T+0–5m   pr-poller.yml triggered manually

T+0:05s  Restore state: state/repos/cobalt_website/last_seen_prs.json

T+0:10s  pr_impact_analyzer.py
           --repo tr/cobalt_website
           --feature-map config/feature-map-website.yml
           --state-dir state/repos/cobalt_website
         → sub_path match: WLNWebsite/.../analytics/ → product:Analytics
         → Writes impact JSON:
           {pr_number, modules_affected:[WebsiteAnalytics],
            sub_products:[analytics], risk_level:medium, ...}

T+0:25s  feature_test_mapper.py
         → analytics sub_path → TestCategories:
           [WLAnalytics, WLAnalyticsIndigo, AnalyticsAlertsEnhancements,
            LegalAnalyticsApi, LitigationAnalytics, TrdLegalAnalyticsUi,
            TrdSmoke, TrdApi, TrdFacets]
         → Maps via CAT_TO_WORKFLOW to WL_DNet workflows:
           [WL_DNet_Analytics_Regression_Next, WL_DNet_Analytics_Edge,
            WL_DNet_Analytics_Alerts_Enhancements_Next,
            WL_DNet_Edge_LegalAnalyticsApi_Edge,
            WL_DNet_Precision_LitigationAnalytics,
            WL_DNet_Edge_TrdLegalAnalyticsUi,
            WL_DNet_Edge_TrdSmoke_Edge,
            WL_DNet_Edge_TrdApi_Edge, WL_DNet_Edge_TrdFacets_Edge]
           + high_risk_always_add: [WebsiteCore1, WebsiteCore2, CoreSearch, GlobalSearch, EdgeSmokeFeatures]

T+0:35s  selective-regression.yml dispatched with:
           source_repo=cobalt_website, pr_number=<N>,
           dotnet_workflows=<list>, TEST_ENVIRONMENT=DEMO

T+0:50s  selective-regression.yml dispatches each WL_DNet_*.yml

T+1–30m  WL_DNet workflows run on AWS EC2 (CodeBuild runner)

T+end    State committed to state-tracking branch:
           state/repos/cobalt_website/last_seen_prs.json updated
           state/repos/cobalt_website/pr_impacts/pr_<N>.json written
           state/repos/cobalt_website/test_plans/pr_<N>.json written
```

---

## 8. State Management

### State directory layout (on `state-tracking` branch)

```
state/
├── repos/
│   ├── cobalt_search/
│   │   ├── last_seen_prs.json
│   │   ├── pr_impacts/
│   │   │   └── pr_<N>.json
│   │   └── test_plans/
│   │       └── pr_<N>.json
│   ├── cobalt_website/
│   │   ├── last_seen_prs.json
│   │   ├── pr_impacts/
│   │   └── test_plans/
│   └── cobalt_static-content/
│       ├── last_seen_prs.json
│       ├── pr_impacts/
│       └── test_plans/
├── prs_to_process.json          # transient: current run only
└── all_impacted_workflows.json  # transient: current run only
```

### Change detection

A PR is re-processed only when:
- It is seen for the first time, OR
- Its `head.sha` has changed (new commit pushed), OR
- `--force-prs` explicitly includes its PR number.

---

## 9. Risk Escalation Rules

| Condition | Effect | Applies to |
|---|---|---|
| Module has `risk_multiplier: high` | Medium risk floor applied | All 3 repos |
| Risk level = `high` | Always adds all `high_risk_always_add` categories | All 3 repos |
| cobalt_search high-risk always-add | CoreSearch, GlobalSearch, EdgeSmokeFeatures | cobalt_search |
| cobalt_website / static-content high-risk always-add | CoreSearch, GlobalSearch, EdgeSmokeFeatures, **WebsiteCore1, WebsiteCore2** | cobalt_website, cobalt_static-content |
| Change type = `docs` | `skip_all: true` — no tests triggered | All 3 repos |
| Change type = `test` | Integration tests skipped (smoke only) | All 3 repos |
| Change type = `chore` | Only smoke tests run (EdgeSmokeFeatures) | cobalt_website, cobalt_static-content |
| Change type = `chore` | Only CoreSearch runs | cobalt_search |
| No categories matched | Fallback: CoreSearch + EdgeSmokeFeatures | All 3 repos |

---

## 10. Known Gaps in Feature Map Coverage

| Gap | Repos affected | Priority |
|---|---|---|
| **QuickCheck 8 categories missing from static-content** | cobalt_static-content | Medium — QuickCheck has CSS/JS assets |
| Axe accessibility tests (18) not mapped anywhere | All 3 | Low — these are run on a fixed schedule, not PR-driven |
| Search-UI features not in any map (~64) | cobalt_search | Low — most need a keyword or sub_path addition to cobalt_search map |

Categories missing from `feature-map-static-content.yml` that are in `feature-map-website.yml`:
```
QuickCheckUiCheckWork_1    QuickCheckUiCheckWork_2
QuickCheckUiCheckWork_3    QuickCheckUiCheckWork_4
QuickCheckUiJudicial_1     QuickCheckUiJudicial_2
QuickCheckUiJudicial_3     QuickCheckUiOpponent
```

Axe categories not in any map (18):
```
AxeIntegrationWLAustralia  AxeIntegrationWLCANext  AxeIntegrationWLNewZealand
AxeIntegrationWestlawEdgeSearch  AxeIntegrationWestlawEdgeWebsite
WLAnalyticsAxeIntegartion  WLEdgeAxeIntegration    WLMobileAxeIntegartion
WLNCorrectionalAxeTest     WLNLinksAxeIntegartion  WLPrecisionAxeIntegration
WestlawNextFeatureAxeIntegartion  WestlawPatronAxeIntegartion
CaseNoteBookAxeIntegartion  OpenWebAxe              RIandDocumnetAxeIntegration
TaxnetProAxe               WLCanadaEdgeAxe
```

---

## 11. Scaling to Additional Repositories

To add a new developer repository (e.g. `tr/cobalt_documents`):

1. **Add entry to `config/repo-registry.yml`**
   ```yaml
   - name:               cobalt_documents
     full_name:          tr/cobalt_documents
     enabled:            true
     description:        "Cobalt Documents delivery platform"
     read_token_secret:  COBALT_READ_TOKEN
     feature_map_repo:   tr/Seven-Kingdoms
     feature_map_path:   feature-map-documents.yml
     feature_map_local:  "config/feature-map-documents.yml"
     test_environment:   DEMO
     lookback_days:      7
   ```

2. **Create `config/feature-map-documents.yml`**
   Follow the same YAML schema:
   ```yaml
   version: "2.0"
   modules:
     MyModule:
       test_categories: [...]
   sub_paths:
     "MyModule/src/path/to/feature/":
       product: MyProduct
       test_categories: [...]
   keywords:
     myfeature:
       product: MyProduct
       test_categories: [...]
   high_risk_always_add:
     test_categories: [CoreSearch, GlobalSearch, EdgeSmokeFeatures]
   ```
   Run `git ls-tree HEAD --name-only` in the target repo to confirm exact top-level folder names before writing module names.

3. **Deploy both files to `tr/CobaltRegressionTesting`** (config/) and **`tr/Seven-Kingdoms`** (repo root).

4. **Merge to main** — the next scheduled run picks it up automatically. No workflow code changes needed.

---

## 12. Secrets Configuration Reference

```
tr/CobaltRegressionTesting → Settings → Secrets and variables → Actions
```

| Secret name | Scope | Notes |
|---|---|---|
| `COBALT_READ_TOKEN` | read:repo on cobalt_search, cobalt_website, cobalt_static-content | One token for all 3 repos (same org) |
| `SEVEN_KINGDOMS_TOKEN` | read:repo on tr/Seven-Kingdoms | Used by feature_test_mapper.py API fallback |
| `REGRESSION_TRIGGER_PAT` | workflow:write on tr/CobaltRegressionTesting | Dispatches workflows + commits state |

---

## 13. Quick Reference — File Locations

```
C:\SelectiveRegressionSolution\
│
├── .github\workflows\
│   ├── selective-regression.yml         ← UPDATED (source_repo input; null-safe classify_file)
│   └── pr-poller.yml                    ← UPDATED (null-safe classify_file)
│
├── config\
│   ├── repo-registry.yml                ← NEW  → deploy to tr/CobaltRegressionTesting
│   ├── feature-map-search.yml                  ← UPDATED (duplicate analytics fix; TrdSmoke added)
│   ├── feature-map-website.yml          ← NEW  → deploy to CobaltRegressionTesting + Seven-Kingdoms
│   └── feature-map-static-content.yml  ← NEW  → deploy to CobaltRegressionTesting + Seven-Kingdoms
│
└── tools\
    ├── pr_impact_analyzer.py            ← UPDATED (multi-repo flags; null-safe YAML)
    ├── feature_test_mapper.py           ← UPDATED (null-safe YAML; 248 CAT_TO_WORKFLOW entries)
    └── requirements.txt                 ← UNCHANGED

Source repos — NO CHANGES ever:
  tr/cobalt_search
  tr/cobalt_website
  tr/cobalt_static-content
```
