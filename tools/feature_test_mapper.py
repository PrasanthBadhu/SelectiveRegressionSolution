#!/usr/bin/env python3
"""
feature_test_mapper.py
======================
Reads feature-map-search.yml from tr/Seven-Kingdoms (via GitHub API) and resolves
which WL_DNet_*.yml workflows to run for a given PR impact dict.

Mapping chain:
  cobalt_search changed files
    -> module / sub_path / keyword  (pr_impact_analyzer.py)
      -> TestCategory names          (feature-map-search.yml in Seven-Kingdoms)
        -> bat files                 (CATEGORY_NAME=TestCategory=<name> in bat files)
          -> WL_DNet_*.yml workflows (bat_file: <name>.bat in workflow yml files)

Usage (called by pr-poller.yml):
    python feature_test_mapper.py --impact state/pr_impacts/pr_2460.json \
                                  --output state/test_plans/pr_2460.json

Output JSON:
    {
      "pr_number":        2460,
      "dotnet_workflows": ["WL_DNet_Edge_CoreSearch", ...],
      "test_categories":  ["CoreSearch", "GlobalSearch", ...],
      "skip_all":         false,
      "reason":           "module:WLNSearch | keyword:aunz"
    }
"""

import os, sys, json, re, argparse
from pathlib import Path
from github import Github, GithubException

try:
    import yaml
except ImportError:
    yaml = None

TEST_MAP_REPO = "tr/Seven-Kingdoms"
TEST_MAP_PATH = "feature-map-search.yml"

# ---------------------------------------------------------------------------
# TestCategory -> WL_DNet workflow mapping
# Built from: grep CATEGORY_NAME config/dotnet/**/*.bat  +  bat_file: in WL_DNet*.yml
# ---------------------------------------------------------------------------
CAT_TO_WORKFLOW = {
    "10KResultsEdge": ["WL_DNet_Edge_10K_Enhanced_Search"],
    "10KResultsWln": ["WL_DNet_Next_10K_Enhanced_Search"],
    "AdvancedSearchTemplate": ["WL_DNet_Next_Search_Advanced"],
    "Agreements": ["WL_DNet_Edge_BLC_Agreements_Edge"],
    "Alert": ["WL_DNet_Edge_BLC_Alerts_Edge"],
    "AlertAccess": ["WL_DNet_Edge_AlertAccess"],
    "Alerts": ["WL_DNet_CA_CanadaAlerts_Next"],
    "AlertsAdmin": ["WL_DNet_CA_AlertsAdmin"],
    "AlertsMobile": ["WL_DNet_Next_WebsiteAlertsMobile_Next"],
    "AnalyticsAlertsEnhancements": ["WL_DNet_Analytics_Alerts_Enhancements_Next"],
    "AnzAlerts": ["WL_DNet_ANZ_AnzAlerts"],
    "AnzContacts": ["WL_DNet_ANZ_AnzContacts"],
    "AnzContinuousClient": ["WL_DNet_ANZ_AnzContinuousClient"],
    "AnzCustomPages": ["WL_DNet_ANZ_CustomsPages"],
    "AnzDocuments": ["WL_DNet_ANZ_AnzDocument"],
    "AnzEdgeRegression": ["WL_DNet_ANZ_AnzSearch", "WL_DNet_ANZ_AnzSearchNZ"],
    "AnzFacet": ["WL_DNet_ANZ_AnzFacets"],
    "AnzFavorites": ["WL_DNet_ANZ_AnzFavourites"],
    "AnzFindAndPrint": ["WL_DNet_ANZ_AnzFindandPrint"],
    "AnzFoldering": ["WL_DNet_ANZ_AnzFoldering"],
    "AnzNotes": ["WL_DNet_ANZ_AnzNotes"],
    "AnzNzFindAndPrint": ["WL_DNet_ANZ_ANZFindAndPrintNZ"],
    "AnzRelatedInfo": ["WL_DNet_ANZ_AnzRelatedInfo"],
    "AnzResponsive": ["WL_DNet_ANZ_AnzResponsive"],
    "AnzUnderDevelopment": ["WL_DNet_ANZ_ANZFindAndPrintAU"],
    "AnzUnderDevelopment1": ["WL_DNet_ANZ_AnzBauSearch"],
    "AnzWebsite": ["WL_DNet_ANZ_AnzWebsite"],
    "AuProdSmokeTest": ["WL_DNet_ANZ_AuClassicProdSmoke"],
    "Aug2025-Transition": ["WL_DNet_ANZ_ANZBAUStoriesNBugs"],
    "BLCCommon": ["WL_DNet_Edge_BLC_Common_Edge"],
    "BLT2015": ["WL_DNet_Edge_BLT2015_Edge"],
    "BasicQnA": ["WL_DNet_Next_BasicQnA"],
    "BillingTests": ["WL_DNet_Next_Billing"],
    "BrowsePageSearch": ["WL_DNet_Edge_BrowsePageSearch"],
    "BusinessLawTransition": ["WL_DNet_Next_BusinessLawTransition_Next"],
    "CCPAEdge": ["WL_DNet_Edge_CaliforniaConsumerPrivacyAct"],
    "CCPAWln": ["WL_DNet_Next_CaliforniaConsumerPrivacyAct"],
    "CanadaDocDisplay": ["WL_DNet_CA_DocumentDisplay"],
    "CapitolWatch": ["WL_DNet_Edge_CapitolWatch", "WL_DNet_Next_WebsiteAlertsCapitolWatch"],
    "CaseEvaluator": ["WL_DNet_Edge_Case_Evaluator", "WL_DNet_Next_CaseEvaluator_Next"],
    "CaseNotebook": ["WL_DNet_Next_CaseNotebookApi_Next"],
    "CaseNotebookUi": ["WL_DNet_Next_CaseNoteBookUI"],
    "CitingReferences": ["WL_DNet_Edge_CitingReferences_Edge"],
    "ClientValidations": ["WL_DNet_Next_ClientValidations"],
    "ClientValidationsEdge": ["WL_DNet_Edge_ClientValidations"],
    "CoCites": ["WL_DNet_Advantage_CoCites", "WL_DNet_Precision_CoCites_WLPrecision"],
    "ContentType": ["WL_DNet_CA_ContentType"],
    "ContinuousClient": ["WL_DNet_Edge_ContinuousClient", "WL_DNet_Next_Continuous_Client"],
    "CopyCitationEdge_Regression": ["WL_DNet_Edge_CopyCitation_Edge"],
    "CopyCitationWln_Regression": ["WL_DNet_Next_CopyCitation_Next"],
    "CopyHyperlink": ["WL_DNet_CA_CopyHyperlink"],
    "CoreSearch": ["WL_DNet_Edge_CoreSearch"],
    "CoreWebsite": ["WL_DNet_Edge_WebsiteCore"],
    "CourtExpress": ["WL_DNet_Edge_CourtExpress_Edge", "WL_DNet_Next_CourtExpress_Next"],
    "CustomDigestSearch": ["WL_DNet_Edge_CustomDigestSearch"],
    "CustomPages": ["WL_DNet_CA_CustomPages", "WL_DNet_Edge_CustomPages"],
    "DOCX": ["WL_DNet_Edge_Docx_Delivery"],
    "DefendingThePremium": ["WL_DNet_Edge_DefendingThePremium_Edge"],
    "DocDisplay": ["WL_DNet_Edge_DocDisplay"],
    "DocketTests": ["WL_DNet_Next_WLNEnhancements_Dockets"],
    "Document": ["WL_DNet_Edge_Document"],
    "DocumentMisc": ["WL_DNet_CA_DocumentMisc"],
    "EdgeCaliforniaOfficialReports_Regression": ["WL_DNet_Edge_CaliforniaOfficialReports"],
    "EdgeCustomPageAdmin": ["WL_DNet_Edge_CustomPageAdmin"],
    "EdgeCustomPages": ["WL_DNet_Edge_CustomPages_Create_Preference"],
    "EdgeSmoke": ["WL_DNet_CA_EdgeSmoke"],
    "EdgeSmoke2.0": ["WL_DNet_Advantage_Smoke_Features", "WL_DNet_Precision_Smoke_Features"],
    "EdgeSmokeFeatures": ["WL_DNet_Edge_Smoke_Features"],
    "EditAnnotationsColorEdge_Regression": ["WL_DNet_Edge_EditAnnotationColor_Edge"],
    "EditAnnotationsColorWln_Regression": ["WL_DNet_Next_EditAnnotationColor_Next"],
    "ExpertRelationships": ["WL_DNet_Next_WLNFR_ExpertRelationship_Next"],
    "FavoriteSearches": ["WL_DNet_Edge_FavoriteSearch"],
    "FilerSearch": ["WL_DNet_Edge_BLC_FilerSearch_Edge"],
    "FilterPanelUpdateEdge": ["WL_DNet_Edge_FilterPanelUpdate_Edge"],
    "FocusHighlighting": ["WL_DNet_Edge_QueryExpansionSelectHighlighting_Part1"],
    "FocusHighlighting1": ["WL_DNet_Edge_QueryExpansionSelectHighlighting_Part2"],
    "FolderAnalysisKeyCite": ["WL_DNet_Edge_FolderAnalysisKeyCite"],
    "FolderRecommendations": ["WL_DNet_Edge_Folder_Analysis_Recommendations"],
    "FolderRedesign1": ["WL_DNet_Edge_Folder_Redesign1"],
    "FolderRedesign2": ["WL_DNet_Edge_Folder_Redesign2"],
    "Foldering": ["WL_DNet_Edge_Foldering_Core"],
    "GlobalIpSmokeTransition": ["WL_DNet_Edge_GlobalIP", "WL_DNet_Next_GlobalIpSmoke_Next"],
    "GlobalSearch": ["WL_DNet_Edge_Search_Global"],
    "GoldReportQuery": ["WL_DNet_Edge_Search_Gold_Report_Query_1", "WL_DNet_Next_Search_Gold_Report"],
    "GoldReportQuery2": ["WL_DNet_Edge_SearchGoldReportQuery_2", "WL_DNet_Next_Search_Gold_Report2"],
    "GovernmentWeblinks": ["WL_DNet_Next_GovernmentWeblinksAPDT"],
    "GraphicalHistory": ["WL_DNet_Advantage_GraphicalHistory", "WL_DNet_Precision_Graphical_History"],
    "HeaderRedesign": ["WL_DNet_Next_HeaderRedesign_Next"],
    "HighQLinkEdge": ["WL_DNet_Edge_HighQ_Edge"],
    "HighQLinkWln": ["WL_DNet_Next_HighQ_Next"],
    "HomePage": ["WL_DNet_CA_HomePage"],
    "HomePageTour": ["WL_DNet_Edge_HomePageTour_Edge"],
    "HotDocs": ["WL_DNET_Edge_Hotdocs"],
    "ImageEdgeSearch": ["WL_DNet_Edge_ImageSearch"],
    "ImageSearch": ["WL_DNet_Next_ImageSearch"],
    "ImpliedOverrulings": ["WL_DNet_Edge_ImpliedOverrulings"],
    "IndigoRetainDataAfterToggling": ["WL_DNet_Edge_RetainDataAfterToggling"],
    "IndigoTrdPage": ["WL_DNet_Edge_TrdPage_Edge"],
    "IndigoTrdTypeahead": ["WL_DNet_Edge_TrdTypeahead_Edge"],
    "InternationalFind": ["WL_DNet_Edge_InternationalFind_Edge", "WL_DNet_Next_InternationalFind_Next"],
    "ItDepends": ["WL_DNet_Edge_ItDepends_Edge"],
    "KeyCiteTestFlag": ["WL_DNet_ANZ_AnzLegislationKeyciteFlag"],
    "LA_Filtering": ["WL_DNet_Precision_LitigationAnalytics_Filtering"],
    "LA_OpportunityFinderTests": ["WL_DNet_Precision_LitigationAnalytics_OpportunityFinder"],
    "LegalAnalyticsApi": ["WL_DNet_Edge_LegalAnalyticsApi_Edge"],
    "LitigationAnalyticsDeliveryTests": ["WL_DNet_Precision_LitigationAnalytics_Delivery"],
    "Links": ["WL_DNet_Next_WLNLinks"],
    "LiveChat": ["WL_DNet_Next_Tax_Migration_LiveChat"],
    "LiveChat_OffHours": ["WL_DNet_Next_Tax_Migration_LiveChat_OffHours"],
    "MasterTaxonomy": ["WL_DNet_CA_MasterTaxonomy"],
    "MedicalLitigator": ["WL_DNet_Edge_MedicalLitigator_Edge"],
    "MedicalLitigatorRegression": ["WL_DNet_Next_MedicalLitigator_Next"],
    "MiscellaneousSearch": ["WL_DNet_Edge_MiscellaneousSearch"],
    "MultipleSearchWithinTermNavigation": ["WL_DNet_Edge_MswTermNavigation"],
    "MultipleSearchWithin_Edge": ["WL_DNet_Edge_Multiple_Search_Within"],
    "NegativeHistory": ["WL_DNet_Edge_NegativeHistory"],
    "NewSmartFolders": ["WL_DNet_Edge_SmartFolders"],
    "NextMissingTerms": ["WL_DNet_Edge_MissingTerms_Edge"],
    "NonBillable": ["WL_DNet_Edge_BLC_NonBillable_Edge"],
    "NzFormsNPrecedent": ["WL_DNet_ANZ_ANZFormsNPrecedent"],
    "NzLawlink": ["WL_DNet_ANZ_ANZLawLinks"],
    "NzProdSmokeTest": ["WL_DNet_ANZ_NzClassicProdSmoke"],
    "OpenWeb": ["WL_DNet_Next_DefendingThePremium_OpenWeb"],
    "PageHeaderRedesign": ["WL_DNet_Edge_HeaderRedesign_Edge"],
    "ParagraphHighlighting": ["WL_DNet_Edge_ParagraphHighlighting"],
    "ParallelSearch": ["WL_DNet_Precision_ParallelSearch"],
    "Patron": ["WL_DNet_PatronAccess"],
    "PortalManager": ["WL_DNet_Edge_PortalManager"],
    "PortalManagerSearch": ["WL_DNet_Next_PortalManagerComplete"],
    "PrPSynopsisDelivery": ["WL_DNet_Edge_DeliverProceduralPosture"],
    "PreviousInteractions": ["WL_DNet_Edge_PUI"],
    "ProceduralPosture": ["WL_DNet_Edge_ProceduralPosture"],
    "PublicDomainCitationsEdge": ["WL_DNet_Edge_PublicDomainCitations"],
    "PublicDomainCitationsWln": ["WL_DNet_Next_PublicDomainCitations"],
    "QuickCheckUiCheckWork_1": ["WL_DNet_Edge_QuickCheckUI_CheckWork_Part1"],
    "QuickCheckUiCheckWork_2": ["WL_DNet_Edge_QuickCheckUI_CheckWork_Part2"],
    "QuickCheckUiCheckWork_3": ["WL_DNet_Edge_QuickCheckUI_CheckWork"],
    "QuickCheckUiCheckWork_4": ["WL_DNet_Edge_QuickCheckUI_CheckWork_Part4"],
    "QuickCheckUiJudicial_1": ["WL_DNet_Edge_QuickCheckUI_Judicial_Part1"],
    "QuickCheckUiJudicial_2": ["WL_DNet_Edge_QuickCheckUI_Judicial_Part2"],
    "QuickCheckUiJudicial_3": ["WL_DNet_Edge_QuickCheckUI_Judicial_Part3"],
    "QuickCheckUiOpponent": ["WL_DNet_Edge_QuickCheckUI_Opposing"],
    "Redlining": ["WL_DNet_Edge_Redlining"],
    "RedliningRegressionTestSuite": ["WL_DNet_Next_Redlining"],
    "RelatedInfoContent": ["WL_DNet_Edge_RelatedInfoContent"],
    "RelatedInfoDelivery": ["WL_DNet_Edge_RelatedInfoDelivery_Edge"],
    "RelatedInfoFacets": ["WL_DNet_Edge_RelatedInfoFacets"],
    "RelatedInfoFlags": ["WL_DNet_Edge_RelatedInfoFlags"],
    "RelatedInfoIpTools": ["WL_DNet_Edge_RelatedInfopTools"],
    "RelatedInfoKeyciteCommand": ["WL_DNet_Edge_RelatedInfoKeyciteCommand"],
    "RelatedInfoMiscellaneous": ["WL_DNet_Next_RelatedInfoMiscellaneous_Next"],
    "RelatedInfoReferences": ["WL_DNet_Next_RelatedInfoReferences_Next"],
    "RelatedInfoTabs": ["WL_DNet_Edge_RelatedInfoTabs"],
    "RepealedFacets": ["WL_DNet_Edge_RepealedFacets_Edge"],
    "ResearchOrganizer": ["WL_DNet_Next_Foldering_Core1"],
    "ResearchOrganizer2": ["WL_DNet_Next_Foldering_Core2"],
    "ResearchOrganizer3": ["WL_DNet_Next_Foldering_Core3"],
    "ResearchOrganizer4": ["WL_DNet_Next_Foldering_Core4"],
    "ResearchOutlineBuilder": ["WL_DNet_Precision_OutlineBuilder_WLPrecision"],
    "ResearchRecommendations1": ["WL_DNet_Edge_Research_Recommendation1", "WL_DNet_Next_ResearchAccelerator"],
    "ResearchRecommendations2": ["WL_DNet_Edge_Research_Recommendation", "WL_DNet_Next_ResearchAccelerator2"],
    "ResearchReports": ["WL_DNet_Edge_ResearchReports"],
    "ResearchReportsDelivery": ["WL_DNet_Edge_ResearchReportsDelivery"],
    "SaveSnippet_Edge": ["WL_DNet_Edge_Non_Root_Folder_Snippets"],
    "Search": ["WL_DNet_CA_Search"],
    "Search4KUiIndigo": ["WL_DNet_Edge_Search4K"],
    "Search4KUiWln": ["WL_DNet_Next_Search4K"],
    "SearchCore": ["WL_DNet_Next_SearchCore"],
    "SearchEnhancements": ["WL_DNet_Edge_SmallEnhancements"],
    "SearchMetadata": ["WL_DNet_Next_Search_Metadata", "WL_DNet_Edge_Search_Metadata"],
    "SearchMiscellaneous": ["WL_DNet_Next_MiscellaneousSearch"],
    "SearchTermEmphasis_Edge": ["WL_DNet_Edge_SearchTermEmphasis"],
    "SearchblePdfs": ["WL_DNet_Edge_SearchblePDFs_Edge"],
    "SecFilingsSectionSearchFandQdocuments": ["WL_DNet_Edge_BLC_SEC_Fillings_SectionSearch"],
    "SecFilingsSectionSearchKdocuments": ["WL_DNet_Edge_BLC_SectionSearchK_Edge"],
    "SecondarySources": ["WL_DNet_Edge_Secondary_Sources"],
    "SectionSearch": ["WL_DNet_Edge_BLC_SectionSearch_Edge"],
    "SharedAnnotations": ["WL_DNet_Edge_SharedAnnotations", "WL_DNet_Next_SharedAnnotations"],
    "SmartFolders": ["WL_DNet_Next_SmartFolders"],
    "SmartSearch": ["WL_DNet_Edge_SmartSearch_Edge"],
    "SnippetCompare": ["WL_DNet_Edge_CompareText"],
    "SnippetNav": ["WL_DNet_Edge_SnippetNavigation"],
    "TCOSectionEdge": ["WL_DNet_Edge_TCO_Typehead_Edge"],
    "TCOSectionWln": ["WL_DNet_Next_TCO_Typehead_Next"],
    "TermHighlight": ["WL_DNet_TaxNet_TermHighlight"],
    "ToC": ["WL_DNet_Edge_TocForCases"],
    "TrainingAndSupport": ["WL_DNet_Next_TrainingAndSupport"],
    "Tray": ["WL_DNet_Edge_Tray_Edge"],
    "TrdApi": ["WL_DNet_Edge_TrdApi_Edge"],
    "TrdFacets": ["WL_DNet_Edge_TrdFacets_Edge"],
    "TrdLegalAnalyticsUi": ["WL_DNet_Edge_TrdLegalAnalyticsUi"],
    "TrdSmoke": ["WL_DNet_Edge_TrdSmoke_Edge"],
    "Trillium": ["WL_DNet_CA_DocumentTrillium"],
    "TrilliumWebSite": ["WL_DNet_CA_Trillium"],
    "UIRefresh": ["WL_DNet_Edge_UiRefresh_Edge"],
    "UIRefresh1": ["WL_DNet_Edge_UiRefresh_1_Edge"],
    "VersionsCompare": ["WL_DNet_Edge_StatutesCompare"],
    "WLAnalytics": ["WL_DNet_Analytics_Regression_Next"],
    "WLAnalyticsIndigo": ["WL_DNet_Analytics_Edge"],
    "WLNCorrectional": ["WL_DNet_Next_Correctional"],
    "WLNTax": ["WL_DNet_Edge_Tax_Migration", "WL_DNet_Next_TaxMigration"],
    "WLNTaxLiveChat": ["WL_DNet_Edge_Tax_Migration_LiveChat"],
    "WLNTaxLiveChat_OffHours": ["WL_DNet_Edge_Tax_Migration_LiveChat_OffHours"],
    "WLPASmoke": ["WL_DNet_ANZ_AuPrecisionSmoke"],
    "WLPNZSmoke": ["WL_DNet_ANZ_NzPrecisionSmoke"],
    "WebsiteCore1": ["WL_DNet_Next_WebsiteCore1"],
    "WebsiteCore2": ["WL_DNet_Next_WebsiteCore2"],
    "WebsiteDelivery": ["WL_DNet_Edge_WebsiteDelivery", "WL_DNet_Next_Website_Delivery"],
    "WebsiteMisc": ["WL_DNet_CA_WebsiteMisc"],
    "WebsiteMobile": ["WL_DNet_Next_WebsiteMobile"],
    "WestKm": ["WL_DNet_Next_WestKM"],
    "WestlawEdgePreview": ["WL_DNet_Edge_WestlawEdgePreview"],
    "WestlawPrecision1": ["WL_DNet_Advantage_Part1", "WL_DNet_Precision_WestlawPrecision_Part1"],
    "WestlawPrecision2": ["WL_DNet_Advantage_Part2", "WL_DNet_Precision_WestlawPrecision_Part2"],
    "WestlawPrecision3": ["WL_DNet_Advantage_Part3", "WL_DNet_Precision_WestlawPrecision_Part3"],
    "WestlawPrecision4": ["WL_DNet_Advantage_Part4", "WL_DNet_Precision_WestlawPrecision_Part4"],
    "WestlawPrecision5": ["WL_DNet_Advantage_Part5", "WL_DNet_Precision_WestlawPrecision_Part5"],
    "WestlawPrecision6": ["WL_DNet_Advantage_Part6", "WL_DNet_Precision_WestlawPrecision_Part6"],
    "WestlawSessionTimeOuts": ["WL_DNet_Edge_Continue_Researching"],
    "WestlawTodayAlerts": ["WL_DNet_Edge_WLT_Edge"],
    "WlnCaliforniaOfficialReports_Regression": ["WL_DNet_Next_CaliforniaOfficialReports"],
    "WlnCustomPage": ["WL_DNet_Next_CustomPageSharing_Next"],
    "WlnCustomPageAdmin": ["WL_DNet_Next_CustomPagesSuperAdmin"],
    "WlnEdgeSearch": ["WL_DNet_Edge_WlnEdgeSearch_Edge"],
    "WlnPromotionBanner": ["WL_DNet_Next_PromotionBanner"],
    "WlnRetainDataAfterToggling": ["WL_DNet_Next_RetainDataAfterToggling"],
    "Wln_Enhancement_tests": ["WL_DNet_Next_WlnEnhancementsTests_Next"],
    "Wln_Enhancement_tests1": ["WL_DNet_Next_WlnEnhancementsTests1_Next"],
    "Wln_Enhancement_tests2": ["WL_DNet_Next_WlnEnhancementsTests2_Next"],
    "Wln_Enhancement_tests3": ["WL_DNet_Next_WlnEnhancementsTests3_Next"],
    "Wln_Enhancement_tests_indigo": ["WL_DNet_Edge_WlnEnhancementsTests_Indigo_Edge"],
}


# ---------------------------------------------------------------------------
# YAML loader from Seven-Kingdoms
# ---------------------------------------------------------------------------

def load_yaml_from_github(gh_token: str) -> dict:
    g = Github(gh_token)
    try:
        repo    = g.get_repo(TEST_MAP_REPO)
        content = repo.get_contents(TEST_MAP_PATH)
        raw     = content.decoded_content.decode("utf-8")
        if yaml:
            return yaml.safe_load(raw)
        raise RuntimeError("PyYAML not installed")
    except GithubException as e:
        local = Path(__file__).parent.parent / "feature-map-search.yml"
        if local.exists():
            print(f"Warning: Could not fetch from GitHub ({e}); using local copy", file=sys.stderr)
            return yaml.safe_load(local.read_text()) if yaml else {}
        raise


# ---------------------------------------------------------------------------
# Core resolution logic
# ---------------------------------------------------------------------------

def _test_categories(entry: dict) -> list:
    return entry.get("test_categories", [])


def resolve_suites(impact: dict, feature_map: dict) -> dict:
    test_categories = set()
    skip_all        = False
    reasons         = []

    change_type = impact.get("change_type", "chore")
    risk_level  = impact.get("risk_level",  "low")
    modules     = impact.get("modules_affected", [])
    file_paths  = impact.get("file_paths", [])
    title       = impact.get("pr_title", "")
    body        = impact.get("pr_body", "")

    fm_modules   = (feature_map.get("modules")            or {})
    fm_sub_paths = (feature_map.get("sub_paths")          or {})
    fm_keywords  = (feature_map.get("keywords")           or {})
    fm_ct_rules  = (feature_map.get("change_type_rules")  or {})
    fm_high_risk = (feature_map.get("high_risk_always_add") or {})

    # Change-type overrides
    ct_rule = fm_ct_rules.get(change_type, {})
    if ct_rule.get("skip_all"):
        return _build_result(impact, set(), True,
                             f"change_type={change_type} => skip_all")
    if ct_rule.get("test_categories_override"):
        test_categories.update(ct_rule["test_categories_override"])
        return _build_result(impact, test_categories, False,
                             f"change_type={change_type} override applied")

    # Module-level resolution
    for module in modules:
        entry = fm_modules.get(module)
        if not entry:
            continue
        cats = _test_categories(entry)
        if cats:
            test_categories.update(cats)
            reasons.append(f"module:{module}")
        if ct_rule.get("skip_integration"):
            test_categories = {c for c in test_categories if "Smoke" not in c}

    # Sub-path resolution
    for fp in file_paths:
        for prefix, entry in fm_sub_paths.items():
            if fp.startswith(prefix):
                cats = _test_categories(entry)
                if cats:
                    test_categories.update(cats)
                    reasons.append(f"sub_path:{prefix}")

    # Keyword resolution
    text = (title + " " + (body or "")).lower()
    for keyword, entry in fm_keywords.items():
        if keyword.lower() in text:
            cats = _test_categories(entry)
            if cats:
                test_categories.update(cats)
                reasons.append(f"keyword:{keyword}")

    # Risk escalation
    if risk_level == "high" and fm_high_risk:
        cats = _test_categories(fm_high_risk)
        if cats:
            test_categories.update(cats)
            reasons.append("high_risk_escalation")

    # Fallback
    if not test_categories:
        test_categories.add("CoreSearch")
        test_categories.add("EdgeSmokeFeatures")
        reasons.append("fallback:smoke_only")

    reason = " | ".join(dict.fromkeys(reasons))
    return _build_result(impact, test_categories, False, reason)


def _build_result(impact, test_categories, skip_all, reason) -> dict:
    # TestCategory names -> workflow names
    workflows = []
    for cat in sorted(test_categories):
        for wf in CAT_TO_WORKFLOW.get(cat, []):
            if wf not in workflows:
                workflows.append(wf)

    if not skip_all and not workflows:
        workflows = ["WL_DNet_Edge_CoreSearch", "WL_DNet_Edge_Smoke_Features"]

    return {
        "pr_number":        impact.get("pr_number"),
        "pr_title":         impact.get("pr_title"),
        "pr_url":           impact.get("pr_url"),
        "head_sha":         impact.get("head_sha"),
        "risk_level":       impact.get("risk_level"),
        "change_type":      impact.get("change_type"),
        "modules":          impact.get("modules_affected", []),
        "products":         impact.get("all_products", []),
        "test_categories":  sorted(test_categories),
        "dotnet_workflows": sorted(set(workflows)),
        "skip_all":         skip_all,
        "reason":           reason,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--impact",    required=True)
    parser.add_argument("--output",    required=True)
    parser.add_argument("--map-local", default=None)
    args = parser.parse_args()

    impact = json.loads(Path(args.impact).read_text())

    gh_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("SEVEN_KINGDOMS_TOKEN")

    if args.map_local:
        if not yaml:
            print("ERROR: PyYAML required.", file=sys.stderr)
            sys.exit(1)
        feature_map = yaml.safe_load(Path(args.map_local).read_text())
    else:
        if not gh_token:
            print("ERROR: GITHUB_TOKEN not set", file=sys.stderr)
            sys.exit(1)
        feature_map = load_yaml_from_github(gh_token)

    result = resolve_suites(impact, feature_map)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))

    print(f"PR #{result['pr_number']}: {len(result['dotnet_workflows'])} workflows [{result['risk_level'].upper()}]")
    print(f"  TestCategories : {', '.join(result['test_categories'])}")
    print(f"  Workflows      : {', '.join(result['dotnet_workflows'])}")
    print(f"  Reason         : {result['reason']}")


if __name__ == "__main__":
    main()
