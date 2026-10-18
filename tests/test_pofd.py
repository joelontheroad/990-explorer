# SPDX-FileCopyrightText: 2026 990-Explorer Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit Tests for IRS Section 527 Political Organization Filing & Disclosure (POFD) Ingestion Engine.

Architectural Purpose:
    Validates Forms 8871 and 8872 file streaming, pipe-delimited data decoding,
    contribution/expenditure tabulation, and entity retrieval in DuckDB.
"""

import io
import pytest

from irs990.storage import IRS990Storage
from irs990.pofd import POFDIngester, _safe_float, _safe_date


@pytest.fixture
def storage():
    """Create in-memory DuckDB storage instance with 527 schema initialized."""
    return IRS990Storage(":memory:")


def test_safe_helpers():
    assert _safe_float("$1,234.56") == 1234.56
    assert _safe_float("NONE") == 0.0
    assert _safe_float("invalid") == 0.0
    assert _safe_date("20240315") == "2024-03-15"
    assert _safe_date("2024-03-15") == "2024-03-15"
    assert _safe_date("") is None


def test_pofd_stream_ingestion(storage):
    ingester = POFDIngester(storage)

    # Build synthetic pipe-delimited data for all record types
    # 1: Form 8871 (needs >= 42 fields)
    p1 = [""] * 45
    p1[0] = "1"
    p1[1] = "8871"
    p1[2] = "10001"
    p1[6] = "821234567"
    p1[7] = "Civic Action 527 Fund"
    p1[8] = "100 Constitution Ave"
    p1[9] = "Suite 200"
    p1[10] = "Washington"
    p1[11] = "DC"
    p1[12] = "20001"
    p1[14] = "info@civicaction.org"
    p1[16] = "John Custodian"
    p1[39] = "Advancing civic engagement and issue advocacy"
    p1[41] = "2024-01-01"
    line_1 = "|".join(p1)

    # D: Directors (needs >= 12 fields)
    p_d = [""] * 15
    p_d[0] = "D"
    p_d[1] = "10001"
    p_d[2] = "1"
    p_d[3] = "Civic Action 527 Fund"
    p_d[4] = "821234567"
    p_d[5] = "Jane Director"
    p_d[6] = "President & Treasurer"
    p_d[7] = "100 Constitution Ave"
    p_d[9] = "Washington"
    p_d[10] = "DC"
    p_d[11] = "20001"
    line_d = "|".join(p_d)

    # R: Related Organizations (needs >= 11 fields)
    p_r = [""] * 12
    p_r[0] = "R"
    p_r[1] = "10001"
    p_r[2] = "1"
    p_r[3] = "Civic Action 527 Fund"
    p_r[4] = "821234567"
    p_r[5] = "Civic Action Alliance"
    p_r[6] = "Connected Organization"
    p_r[9] = "Washington"
    p_r[10] = "DC"
    line_r = "|".join(p_r)

    # 2: Form 8872 Periodic Report (needs >= 49 fields)
    p2 = [""] * 52
    p2[0] = "2"
    p2[1] = "8872"
    p2[2] = "20001"
    p2[3] = "20240101"
    p2[4] = "20240331"
    p2[9] = "Civic Action 527 Fund"
    p2[10] = "821234567"
    p2[45] = "500000.00"
    p2[47] = "350000.00"
    p2[48] = "2024-04-15"
    line_2 = "|".join(p2)

    # A: Itemized Contributions (needs >= 17 fields)
    p_a = [""] * 20
    p_a[0] = "A"
    p_a[1] = "20001"
    p_a[2] = "1"
    p_a[3] = "Civic Action 527 Fund"
    p_a[4] = "821234567"
    p_a[5] = "Alice Philanthropist"
    p_a[8] = "New York"
    p_a[9] = "NY"
    p_a[10] = "10021"
    p_a[12] = "Self"
    p_a[13] = "250000.00"
    p_a[14] = "Investor"
    p_a[15] = "250000.00"
    p_a[16] = "2024-02-10"
    line_a = "|".join(p_a)

    # B: Itemized Expenditures (needs >= 17 fields)
    p_b = [""] * 20
    p_b[0] = "B"
    p_b[1] = "20001"
    p_b[2] = "1"
    p_b[3] = "Civic Action 527 Fund"
    p_b[4] = "821234567"
    p_b[5] = "Vanguard Media Group"
    p_b[8] = "Alexandria"
    p_b[9] = "VA"
    p_b[10] = "22314"
    p_b[13] = "150000.00"
    p_b[15] = "2024-03-01"
    p_b[16] = "Digital Voter Education Ads"
    line_b = "|".join(p_b)

    payload = f"{line_1}\n{line_d}\n{line_r}\n{line_2}\n{line_a}\n{line_b}\n".encode("utf-8")
    stream = io.BytesIO(payload)

    # Ingest synthetic stream
    counts = ingester.parse_stream(stream)

    assert counts["orgs"] == 1
    assert counts["directors"] == 1
    assert counts["related"] == 1
    assert counts["reports"] == 1
    assert counts["contributions"] == 1
    assert counts["expenditures"] == 1

    # Verify retrieval via get_527_org
    org = storage.get_527_org("82-1234567")
    assert org is not None
    assert org["name"] == "Civic Action 527 Fund"
    assert org["ein"] == "82-1234567"
    assert org["city"] == "Washington"
    assert org["state"] == "DC"
    assert len(org["directors"]) == 1
    assert org["directors"][0]["name"] == "Jane Director"
    assert len(org["related_entities"]) == 1
    assert org["related_entities"][0]["related_name"] == "Civic Action Alliance"
    assert len(org["reports"]) == 1
    assert org["reports"][0]["contributions"] == 500000.0
    assert org["reports"][0]["expenditures"] == 350000.0

    # Verify omni-search retrieves the 527 org
    omni = storage.search_omni("Civic Action")
    assert "pacs_527" in omni
    assert len(omni["pacs_527"]) == 1
    assert omni["pacs_527"][0]["name"] == "Civic Action 527 Fund"

    # Verify database stats reflects 527 POFD
    stats = storage.get_database_stats()
    assert "pacs_527" in stats
    s527 = stats["pacs_527"]
    assert s527["table_present"] is True
    assert s527["total_527_orgs"] == 1
    assert s527["total_reports"] == 1
    assert s527["total_contributions"] == 1
    assert s527["contributions_volume"] == 250000.0
    assert s527["total_expenditures"] == 1
    assert s527["expenditures_volume"] == 150000.0
