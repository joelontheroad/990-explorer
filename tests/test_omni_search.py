# SPDX-FileCopyrightText: 2026 990-Explorer Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit Tests for Unified Omni-Search & Commercial Contractor Dossier Engine.

Architectural Purpose:
    Validates multi-entity full-text queries across non-profits, board members,
    commercial contractors, corporate affiliates, 527 political committees,
    and FEC PACs in DuckDB.
"""

import pytest
from irs990.storage import IRS990Storage
from irs990.models import (
    OrganizationNode,
    Relationship,
    IndependentContractor,
    PersonAffiliation
)


@pytest.fixture
def storage():
    """Create an in-memory DuckDB storage instance with rich test data."""
    store = IRS990Storage(":memory:")

    # 1. Add sample organizations
    org1 = OrganizationNode(
        ein="51-0198509",
        name="Tides Foundation",
        tax_status="501(c)(3)",
        total_revenue=367000000.0,
        city="San Francisco",
        state="CA"
    )
    org2 = OrganizationNode(
        ein="94-3213100",
        name="Tides Center",
        tax_status="501(c)(3)",
        total_revenue=210000000.0,
        city="San Francisco",
        state="CA"
    )
    store.upsert_organization(org1)
    store.upsert_organization(org2)

    # 2. Add sample people
    p1 = PersonAffiliation(
        filer_ein="51-0198509",
        filer_name="Tides Foundation",
        tax_year=2021,
        person_name="Amanda Keton",
        clean_name="AMANDA KETON",
        title="Secretary & General Counsel",
        role_type="Officer",
        hours_per_week=40.0,
        reportable_comp=285000.0,
        related_org_comp=0.0,
        other_comp=35000.0,
        total_comp=320000.0
    )
    p2 = PersonAffiliation(
        filer_ein="94-3213100",
        filer_name="Tides Center",
        tax_year=2021,
        person_name="Amanda Keton",
        clean_name="AMANDA KETON",
        title="Secretary",
        role_type="Officer",
        hours_per_week=20.0,
        reportable_comp=150000.0,
        related_org_comp=0.0,
        other_comp=15000.0,
        total_comp=165000.0
    )
    store.upsert_people([p1, p2])

    # 3. Add sample contractors
    c1 = IndependentContractor(
        filer_ein="51-0198509",
        filer_name="Tides Foundation",
        tax_year=2021,
        contractor_name="Arabella Advisors",
        city="Washington",
        state="DC",
        description_of_services="Consulting & Management",
        amount=1250000.0
    )
    c2 = IndependentContractor(
        filer_ein="94-3213100",
        filer_name="Tides Center",
        tax_year=2021,
        contractor_name="Arabella Advisors",
        city="Washington",
        state="DC",
        description_of_services="Philanthropic Advisory",
        amount=850000.0
    )
    store.upsert_contractors([c1, c2])

    # 4. Add sample Schedule R affiliate
    rel = Relationship(
        entity_ein="51-0198509",
        entity_name="Tides Foundation",
        related_ein="94-3213100",
        related_name="Tides Center",
        relationship_type="Affiliate",
        primary_activity="Fiscal Sponsorship"
    )
    store.upsert_relationships([rel])

    # 5. Add sample 527 political org
    store.upsert_527_orgs([(
        "1001", "Arabella Action Fund", "82-1234567", "8871", "100 K St NW", "",
        "Washington", "DC", "20005", "info@arabellaaction.org", "Jane Doe",
        "Advancing policy initiatives", "2024-01-15"
    )])

    return store


def test_search_omni_organizations(storage):
    results = storage.search_omni("Tides")
    assert "organizations" in results
    assert len(results["organizations"]) >= 2
    names = [o["name"] for o in results["organizations"]]
    assert "Tides Foundation" in names
    assert "Tides Center" in names


def test_search_omni_people(storage):
    results = storage.search_omni("Amanda")
    assert "people" in results
    assert len(results["people"]) == 1
    person = results["people"][0]
    assert person["clean_name"] == "AMANDA KETON"
    assert person["org_count"] == 2
    assert person["total_comp"] == 485000.0


def test_search_omni_contractors(storage):
    results = storage.search_omni("Arabella")
    assert "contractors" in results
    assert len(results["contractors"]) >= 1
    contractor = results["contractors"][0]
    assert "Arabella Advisors" in contractor["contractor_name"]
    assert contractor["client_count"] == 2
    assert contractor["total_amount"] == 2100000.0


def test_search_omni_affiliates(storage):
    results = storage.search_omni("Center")
    assert "affiliates" in results
    assert len(results["affiliates"]) >= 1
    affiliate = results["affiliates"][0]
    assert affiliate["related_name"] == "Tides Center"


def test_search_omni_527s(storage):
    results = storage.search_omni("Arabella Action")
    assert "pacs_527" in results
    assert len(results["pacs_527"]) == 1
    pac = results["pacs_527"][0]
    assert pac["name"] == "Arabella Action Fund"
    assert pac["ein"] == "82-1234567"


def test_get_contractor_dossier(storage):
    dossier = storage.get_contractor_dossier("Arabella Advisors")
    assert dossier is not None
    assert "Arabella Advisors" in dossier["contractor_name"]
    assert dossier["client_count"] == 2
    assert dossier["total_amount"] == 2100000.0
    assert "Consulting & Management" in dossier["services"]
    assert "Philanthropic Advisory" in dossier["services"]
    assert len(dossier["clients"]) == 2

    client_names = [c["filer_name"] for c in dossier["clients"]]
    assert "Tides Foundation" in client_names
    assert "Tides Center" in client_names
