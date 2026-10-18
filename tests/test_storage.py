# SPDX-FileCopyrightText: 2026 990-Explorer Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for DuckDB Storage and Query Engine.

Architectural Purpose:
    Validates CRUD operations for organizations, grants, and relationships,
    as well as upstream filing ingestion caching in DuckDB.
"""

from irs990.storage import IRS990Storage
from irs990.models import OrganizationNode, FundingGrant, Relationship


def test_storage_crud():
    storage = IRS990Storage(":memory:")

    # 1. Organization Upsert & Retrieval
    org = OrganizationNode(
        ein="51-0198509",
        name="Tides Foundation",
        tax_status="501(c)(3)",
        total_revenue=367000000.0,
        city="San Francisco",
        state="CA"
    )
    storage.upsert_organization(org)
    fetched = storage.get_organization("51-0198509")
    assert fetched is not None
    assert fetched.name == "Tides Foundation"
    assert fetched.total_revenue == 367000000.0

    # 2. Grants Upsert & Inbound/Outbound Queries
    grant1 = FundingGrant(
        grantor_ein="13-1628106",
        grantor_name="Ford Foundation",
        recipient_ein="51-0198509",
        recipient_name="Tides Foundation",
        amount=1000000.0,
        tax_year=2021,
        purpose="General Support"
    )
    grant2 = FundingGrant(
        grantor_ein="51-0198509",
        grantor_name="Tides Foundation",
        recipient_ein="94-3213100",
        recipient_name="Tides Center",
        amount=25000000.0,
        tax_year=2021,
        purpose="Fiscal Sponsorship"
    )
    storage.upsert_grants([grant1, grant2])

    inbound = storage.get_inbound_grants("51-0198509")
    assert len(inbound) == 1
    assert inbound[0].grantor_name == "Ford Foundation"

    outbound = storage.get_outbound_grants("51-0198509")
    assert len(outbound) == 1
    assert outbound[0].recipient_name == "Tides Center"

    # 3. Schedule R Relationships
    rel = Relationship(
        entity_ein="51-0198509",
        entity_name="Tides Foundation",
        related_ein="94-3213100",
        related_name="Tides Center",
        relationship_type="Sibling",
        primary_activity="Fiscal Sponsorship"
    )
    storage.upsert_relationships([rel])
    rels = storage.get_relationships("51-0198509")
    assert len(rels) == 1
    assert rels[0].relationship_type == "Sibling"


def test_database_stats_and_metadata():
    storage = IRS990Storage(":memory:")

    # 1. Initially empty metadata
    meta = storage.get_ingestion_metadata()
    assert len(meta) == 0

    # 2. Record sync for BMF and seeds
    storage.record_sync("IRS_BMF", "IRS EO BMF", 1850000, "Extract eo1-eo4")
    storage.record_sync("SEEDS", "Curated Seeds", 50, "Top 25 foundations")

    meta = storage.get_ingestion_metadata()
    assert len(meta) == 2
    sources = {m["source_id"]: m for m in meta}
    assert "IRS_BMF" in sources
    assert sources["IRS_BMF"]["records_count"] == 1850000
    assert "SEEDS" in sources
    assert sources["SEEDS"]["records_count"] == 50

    # 3. Verify database stats
    stats = storage.get_database_stats()
    assert "sources" in stats
    assert len(stats["sources"]) == 2
    assert "grants" in stats
    assert "organizations" in stats
    assert "relationships" in stats

