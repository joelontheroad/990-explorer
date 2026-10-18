# SPDX-FileCopyrightText: 2026 990-Explorer Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Unit and Integration Tests for Cross-Entity Resolution & Linkage Engine (Phase 4).
Tests detection of connected organizations, leadership interlocks, shared commercial vendors,
and traversal integration bridging 501(c) non-profits to FEC PACs and IRS 527 organizations.
"""

import pytest
from irs990.storage import IRS990Storage
from irs990.models import OrganizationNode, PersonAffiliation, IndependentContractor
from irs990.linkage import LinkageResolver, normalize_org_name
from irs990.traversal import FundingTraversalEngine


@pytest.fixture
def storage():
    """Create in-memory DuckDB storage instance with all tables initialized."""
    return IRS990Storage(":memory:")


def test_normalize_org_name():
    """Verify robust entity name normalization for fuzzy matching."""
    assert normalize_org_name("The Tides Foundation, Inc.") == "TIDES"
    assert normalize_org_name("Majority Forward LLC") == "MAJORITY FORWARD"
    assert normalize_org_name("League of Conservation Voters Action Fund") == "LEAGUE OF CONSERVATION VOTERS"
    assert normalize_org_name("Perkins Coie LLP") == "PERKINS COIE LLP"  # LLP preserved unless in rule
    assert normalize_org_name("Natural Resources Defense Council, Inc.") == "NATURAL RESOURCES DEFENSE COUNCIL"


def test_fec_connected_org_linkage(storage):
    """Test Bridge 1: Matching FEC CONNECTED_ORG_NM to non-profit organizations."""
    # 1. Insert target non-profit
    storage.upsert_organizations([
        OrganizationNode(ein="81-1234567", name="Majority Forward", tax_status="501(c)(4)")
    ])

    # 2. Insert FEC Committee with connected_org_name pointing to Majority Forward
    # (cmte_id, cmte_name, treasurer_name, clean_treasurer, city, state, zip, cmte_dsg, cmte_tp, pty, org_tp, conn_org, clean_conn, cand_id, cycle)
    storage.upsert_fec_committees([
        (
            "C00495028", "SENATE MAJORITY PAC", "J.B. POPP", "JB POPP",
            "WASHINGTON", "DC", "20003", "U", "O", "DEM", "W",
            "MAJORITY FORWARD", "MAJORITY FORWARD", "", 2024
        )
    ])

    resolver = LinkageResolver(storage)
    linkages = resolver.resolve_organization_linkages("81-1234567")

    assert len(linkages) == 1
    link = linkages[0]
    assert link.target_type == "fec_pac"
    assert link.target_id == "C00495028"
    assert link.target_name == "SENATE MAJORITY PAC"
    assert link.link_type == "connected_org"
    assert link.confidence_score >= 0.90
    assert "Official Connected Organization" in link.description


def test_fec_treasurer_interlock(storage):
    """Test Bridge 2: Shared leadership between nonprofit officer and FEC treasurer."""
    # 1. Insert target organization and officer
    storage.upsert_organizations([
        OrganizationNode(ein="51-0198509", name="Tides Foundation", tax_status="501(c)(3)")
    ])
    storage.upsert_people([
        PersonAffiliation(
            filer_ein="51-0198509",
            filer_name="Tides Foundation",
            tax_year=2023,
            person_name="Amanda Keton",
            clean_name="AMANDA KETON",
            title="Secretary & General Counsel",
            role_type="Officer",
            hours_per_week=40.0,
            reportable_comp=250000.0,
            total_comp=280000.0
        )
    ])

    # 2. Insert FEC Committee where treasurer is Amanda Keton
    storage.upsert_fec_committees([
        (
            "C00999888", "PROGRESSIVE ACTION SUPER PAC", "Amanda Keton", "AMANDA KETON",
            "SAN FRANCISCO", "CA", "94105", "U", "O", "DEM", "",
            "", "", "", 2024
        )
    ])

    resolver = LinkageResolver(storage)
    linkages = resolver.resolve_organization_linkages("51-0198509")

    assert len(linkages) == 1
    link = linkages[0]
    assert link.target_type == "fec_pac"
    assert link.target_id == "C00999888"
    assert link.link_type == "shared_leadership"
    assert link.confidence_score == 0.85
    assert link.evidence["shared_person"] == "Amanda Keton"
    assert "serves as Treasurer" in link.description


def test_527_related_org_and_director_linkages(storage):
    """Test Bridge 1 & 2 for IRS Section 527 organizations."""
    storage.upsert_organizations([
        OrganizationNode(ein="13-1234567", name="Environmental Action Network", tax_status="501(c)(4)")
    ])
    storage.upsert_people([
        PersonAffiliation(
            filer_ein="13-1234567",
            filer_name="Environmental Action Network",
            tax_year=2023,
            person_name="Robert Green",
            clean_name="ROBERT GREEN",
            title="Executive Director",
            role_type="Officer",
            hours_per_week=35.0,
            reportable_comp=180000.0,
            total_comp=200000.0
        )
    ])

    # Form 8871 Related Organization
    # pk, form_id, org_name, ein, rel_name, rel_type, city, state
    storage.upsert_527_related([
        (
            "8871-1:R1", "8871-1", "CLEAN ENERGY VICTORY FUND", "99-9999999",
            "Environmental Action Network", "Connected Organization", "WASHINGTON", "DC"
        )
    ])

    # Form 8871 Director
    # pk, form_id, org_name, ein, person_name, clean_name, title, addr1, city, state, zip_code
    storage.upsert_527_directors([
        (
            "8871-2:D1", "8871-2", "GREEN FUTURE PAC", "88-8888888",
            "Robert Green", "ROBERT GREEN", "Treasurer & Custodian", "100 MAIN", "DENVER", "CO", "80202"
        )
    ])

    resolver = LinkageResolver(storage)
    linkages = resolver.resolve_organization_linkages("13-1234567")

    assert len(linkages) == 2
    types = {l.link_type for l in linkages}
    assert "connected_org" in types
    assert "shared_leadership" in types

    rel_link = next(l for l in linkages if l.link_type == "connected_org")
    assert rel_link.target_type == "irs_527"
    assert rel_link.target_id == "8871-1"

    dir_link = next(l for l in linkages if l.link_type == "shared_leadership")
    assert dir_link.target_type == "irs_527"
    assert dir_link.target_id == "8871-2"
    assert dir_link.evidence["shared_person"] == "Robert Green"


def test_shared_commercial_contractor_linkage(storage):
    """Test Bridge 3: Shared commercial vendors between non-profit and PAC."""
    storage.upsert_organizations([
        OrganizationNode(ein="51-0198509", name="Tides Foundation", tax_status="501(c)(3)")
    ])

    # Nonprofit contractor > $100k
    storage.upsert_contractors([
        IndependentContractor(
            filer_ein="51-0198509",
            filer_name="Tides Foundation",
            tax_year=2023,
            contractor_name="Arabella Advisors LLC",
            city="Washington",
            state="DC",
            description_of_services="Management Consulting & Operations",
            amount=1250000.0
        )
    ])

    # FEC Committee operating expenditures to the same vendor
    storage.upsert_fec_committees([
        (
            "C00495028", "SENATE MAJORITY PAC", "TREASURER", "TREASURER",
            "WASHINGTON", "DC", "20003", "U", "O", "DEM", "", "", "", "", 2024
        )
    ])
    # sub_id, cmte_id, payee_name, city, state, zip, date, amount, purpose, category, cycle
    storage.upsert_fec_operating_expenditures([
        (
            "OPP-1", "C00495028", "ARABELLA ADVISORS LLC", "WASHINGTON", "DC", "20003",
            "2024-04-10", 350000.0, "STRATEGIC CONSULTING", "MANAGEMENT", 2024
        )
    ])

    resolver = LinkageResolver(storage)
    linkages = resolver.resolve_organization_linkages("51-0198509")

    assert len(linkages) == 1
    link = linkages[0]
    assert link.link_type == "shared_contractor"
    assert link.confidence_score == 0.75
    assert link.evidence["contractor_name"] == "Arabella Advisors LLC"
    assert link.evidence["nonprofit_billing"] == 1250000.0
    assert link.evidence["pac_disbursement_total"] == 350000.0


def test_database_wide_cross_linkages_scan(storage):
    """Test batch scan across all non-profits in the database."""
    storage.upsert_organizations([
        OrganizationNode(ein="81-1234567", name="Majority Forward", tax_status="501(c)(4)")
    ])
    storage.upsert_fec_committees([
        (
            "C00495028", "SENATE MAJORITY PAC", "J.B. POPP", "JB POPP",
            "WASHINGTON", "DC", "20003", "U", "O", "DEM", "W",
            "MAJORITY FORWARD", "MAJORITY FORWARD", "", 2024
        )
    ])

    resolver = LinkageResolver(storage)
    all_links = resolver.resolve_all_database_linkages(limit=10)

    assert len(all_links) >= 1
    assert any(l.target_id == "C00495028" for l in all_links)

    # Verify storage cached records
    cached = storage.get_all_entity_linkages()
    assert len(cached) >= 1
    assert cached[0]["target_id"] == "C00495028"


def test_traversal_engine_pac_expansion(storage):
    """Verify FundingTraversalEngine traverses and attaches PAC nodes and edges."""
    storage.upsert_organizations([
        OrganizationNode(ein="81-1234567", name="Majority Forward", tax_status="501(c)(4)")
    ])
    storage.upsert_fec_committees([
        (
            "C00495028", "SENATE MAJORITY PAC", "J.B. POPP", "JB POPP",
            "WASHINGTON", "DC", "20003", "U", "O", "DEM", "W",
            "MAJORITY FORWARD", "MAJORITY FORWARD", "", 2024
        )
    ])

    engine = FundingTraversalEngine(storage)
    graph = engine.traverse(target_ein="81-1234567", include_pacs=True)

    # Assert PAC node is in graph.nodes
    assert "C00495028" in graph.nodes
    pac_node = graph.nodes["C00495028"]
    assert pac_node.direction == "pac"
    assert pac_node.tax_status == "Super PAC"
    assert pac_node.metadata["is_pac"] is True

    # Assert PAC relationship edge is in graph.relationship_edges
    assert len(graph.relationship_edges) >= 1
    edge = list(graph.relationship_edges.values())[0]
    assert edge.source_schedule == "PAC Linkage"
    assert edge.related_ein == "C00495028"
    assert edge.relationship_type == "Connected PAC"
