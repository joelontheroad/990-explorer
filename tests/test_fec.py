# SPDX-FileCopyrightText: 2026 990-Explorer Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit and Integration Tests for Federal Election Commission (FEC) Bulk Data Ingestion Engine.

Architectural Purpose:
    Validates CSV parsing, schema migration, committee profiling, candidate linkage,
    and expenditure aggregation across federal election cycles in DuckDB.
"""

import io
import zipfile
import pytest
from unittest.mock import MagicMock

from irs990.storage import IRS990Storage
from irs990.fec import FECIngester, FECClient, _safe_float, _safe_fec_date


@pytest.fixture
def storage():
    """Create in-memory DuckDB storage instance with FEC schema initialized."""
    return IRS990Storage(":memory:")


def test_fec_helpers():
    assert _safe_float("$10,500.50") == 10500.50
    assert _safe_float("NONE") == 0.0
    assert _safe_float("bad") == 0.0
    assert _safe_fec_date("03152024") == "2024-03-15"
    assert _safe_fec_date("11052024") == "2024-11-05"
    assert _safe_fec_date("") is None


def test_fec_stream_parsers(storage):
    ingester = FECIngester(storage)

    # 1. Test Committee Master (cm.txt)
    # Fields: CMTE_ID|CMTE_NM|TRES_NM|CMTE_ST1|CMTE_ST2|CMTE_CITY|CMTE_ST|CMTE_ZIP|CMTE_DSG|CMTE_TP|CMTE_PTY|FILING_FREQ|ORG_TP|CONNECTED_ORG_NM|CAND_ID
    cm_line = "C00580100|MAJORITY FORWARD|JANE DOE|||WASHINGTON|DC|20003|U|O|DEM|M|W|SENATE MAJORITY PAC|P00000001\n"
    cm_stream = io.BytesIO(cm_line.encode("latin-1"))
    count_cm = ingester.parse_cm_stream(cm_stream, cycle=2024)
    assert count_cm == 1

    # 2. Test Candidate Master (cn.txt)
    # Fields: CAND_ID|CAND_NAME|CAND_PTY_AFFILIATION|CAND_ELECTION_YR|CAND_OFFICE_ST|CAND_OFFICE|CAND_OFFICE_DISTRICT|CAND_ICI|CAND_STATUS|CAND_PCC
    cn_line = "P00000001|BIDEN, JOSEPH R JR|DEM|2024|US|P|00|I|C|C00703975\n"
    cn_stream = io.BytesIO(cn_line.encode("latin-1"))
    count_cn = ingester.parse_cn_stream(cn_stream, cycle=2024)
    assert count_cn == 1

    # 3. Test Candidate Linkages (ccl.txt)
    # Fields: CAND_ID|CAND_ELECTION_YR|FEC_ELECTION_YR|CMTE_ID|CMTE_TP|CMTE_DSG|LINKAGE_ID
    ccl_line = "P00000001|2024|2024|C00580100|O|U|10001\n"
    ccl_stream = io.BytesIO(ccl_line.encode("latin-1"))
    count_ccl = ingester.parse_ccl_stream(ccl_stream, cycle=2024)
    assert count_ccl == 1

    # 4. Test Transactions (itpas2.txt)
    # Fields: CMTE_ID|AMNDT_IND|RPT_TP|TRANSACTION_PGI|IMAGE_NUM|TRANSACTION_TP|ENTITY_TP|NAME|CITY|STATE|ZIP_CODE|EMPLOYER|OCCUPATION|TRANSACTION_DT|TRANSACTION_AMT|OTHER_ID|TRAN_ID|FILE_NUM|MEMO_CD|MEMO_TEXT|SUB_ID
    # Line 1: 24E = Independent Expenditure Supporting
    p_tx1 = [""] * 22
    p_tx1[0] = "C00580100"
    p_tx1[5] = "24E"
    p_tx1[6] = "CAN"
    p_tx1[7] = "BIDEN, JOSEPH R JR"
    p_tx1[8] = "PHILADELPHIA"
    p_tx1[9] = "PA"
    p_tx1[10] = "19102"
    p_tx1[13] = "10152024"
    p_tx1[14] = "5000000.00"
    p_tx1[15] = "P00000001"
    p_tx1[19] = "Digital TV ad campaign supporting candidate"
    p_tx1[20] = "SUB_TX_001"
    tx_line1 = "|".join(p_tx1)

    # Line 2: 24A = Independent Expenditure Opposing
    p_tx2 = [""] * 22
    p_tx2[0] = "C00580100"
    p_tx2[5] = "24A"
    p_tx2[6] = "CAN"
    p_tx2[7] = "TRUMP, DONALD J"
    p_tx2[8] = "PALM BEACH"
    p_tx2[9] = "FL"
    p_tx2[10] = "33480"
    p_tx2[13] = "10182024"
    p_tx2[14] = "7500000.00"
    p_tx2[15] = "P00000002"
    p_tx2[19] = "Digital TV ad campaign opposing candidate"
    p_tx2[20] = "SUB_TX_002"
    tx_line2 = "|".join(p_tx2)

    tx_payload = f"{tx_line1}\n{tx_line2}\n".encode("latin-1")
    count_tx = ingester.parse_pas2_stream(io.BytesIO(tx_payload), cycle=2024)
    assert count_tx == 2

    # 5. Test Operating Expenditures (oppexp.txt)
    # Fields: CMTE_ID|AMNDT_IND|RPT_YR|RPT_TP|IMAGE_NUM|LINE_NUM|FORM_TP_CD|SCHED_TP_CD|NAME|CITY|STATE|ZIP_CODE|TRANSACTION_DT|TRANSACTION_AMT|TRANSACTION_PGI|PURPOSE|CATEGORY|CATEGORY_DESC|MEMO_CD|MEMO_TEXT|ENTITY_TP|SUB_ID
    p_opp = [""] * 23
    p_opp[0] = "C00580100"
    p_opp[8] = "WATERFRONT STRATEGIES"
    p_opp[9] = "WASHINGTON"
    p_opp[10] = "DC"
    p_opp[11] = "20005"
    p_opp[12] = "09152024"
    p_opp[13] = "2500000.00"
    p_opp[15] = "MEDIA PRODUCTION AND AD BUYING"
    p_opp[17] = "MEDIA"
    p_opp[21] = "SUB_OPP_001"
    opp_line = "|".join(p_opp)
    count_opp = ingester.parse_oppexp_stream(io.BytesIO(opp_line.encode("latin-1")), cycle=2024)
    assert count_opp == 1

    # Verify retrieval via get_fec_committee
    cmte = storage.get_fec_committee("C00580100")
    assert cmte is not None
    assert cmte["cmte_id"] == "C00580100"
    assert cmte["name"] == "MAJORITY FORWARD"
    assert "Super PAC" in cmte["type_label"]
    assert cmte["connected_org"] == "SENATE MAJORITY PAC"
    assert cmte["cycle"] == 2024

    # Verify linked candidates
    assert len(cmte["candidates"]) == 1
    assert "BIDEN" in cmte["candidates"][0]["candidate_name"]

    # Verify independent expenditures
    tx_sum = cmte["expenditures_summary"]
    assert len(tx_sum["supporting"]) == 1
    assert tx_sum["supporting"][0]["total_amount"] == 5000000.0
    assert "BIDEN" in tx_sum["supporting"][0]["recipient_name"]

    assert len(tx_sum["opposing"]) == 1
    assert tx_sum["opposing"][0]["total_amount"] == 7500000.0
    assert "TRUMP" in tx_sum["opposing"][0]["recipient_name"]

    # Verify vendor disbursements
    assert len(cmte["top_vendors"]) == 1
    assert cmte["top_vendors"][0]["payee_name"] == "WATERFRONT STRATEGIES"
    assert cmte["top_vendors"][0]["total_amount"] == 2500000.0

    # Verify search_fec_committees
    search_res = storage.search_fec_committees("Majority")
    assert len(search_res) >= 1
    assert search_res[0]["cmte_id"] == "C00580100"

    # Verify omni-search returns the FEC committee
    omni = storage.search_omni("Majority Forward")
    assert "fec_pacs" in omni
    assert len(omni["fec_pacs"]) == 1
    assert omni["fec_pacs"][0]["cmte_id"] == "C00580100"

    # Verify database stats reflects FEC bulk
    stats = storage.get_database_stats()
    assert "fec_pacs" in stats
    fstats = stats["fec_pacs"]
    assert fstats["table_present"] is True
    assert fstats["total_committees"] == 1
    assert fstats["total_super_pacs"] == 1
    assert fstats["total_candidates"] == 1
    assert fstats["total_transactions"] == 2
    assert fstats["transactions_volume"] == 12500000.0
    assert fstats["total_operating_expenditures"] == 1
    assert fstats["operating_expenditures_volume"] == 2500000.0
    assert 2024 in fstats["cycles"]


def test_fec_client_search_committees_mocked(storage, monkeypatch):
    """Verify FECClient live search queries OpenFEC, parses results, and caches into DuckDB."""
    client = FECClient(storage=storage)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": [
            {
                "committee_id": "C00634261",
                "name": "DEFEND US PAC",
                "committee_type": "O",
                "committee_type_full": "Super PAC (Independent Expenditure-Only)",
                "treasurer_name": "MCINTYRE, DUSTIN",
                "state": "VA",
                "city": "ARLINGTON",
                "zip": "22307",
                "designation": "U",
                "cycles": [2022, 2024, 2026],
                "affiliated_committee_name": "NONE"
            }
        ]
    }

    monkeypatch.setattr(client.session, "get", lambda *args, **kwargs: mock_resp)

    results = client.search_committees("Defend US PAC")
    assert len(results) == 1
    pac = results[0]
    assert pac["cmte_id"] == "C00634261"
    assert pac["name"] == "DEFEND US PAC"
    assert pac["type_label"] == "Super PAC"
    assert pac["treasurer"] == "MCINTYRE, DUSTIN"

    # Verify auto-cached into DuckDB
    cached = storage.get_fec_committee("C00634261")
    assert cached is not None
    assert cached["name"] == "DEFEND US PAC"
    assert cached["treasurer"] == "MCINTYRE, DUSTIN"


def test_fec_client_get_committee_profile_mocked(storage, monkeypatch):
    """Verify FECClient fetches single committee profile and normalizes into storage format."""
    client = FECClient(storage=storage)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": [
            {
                "committee_id": "C00634261",
                "name": "DEFEND US PAC",
                "committee_type": "O",
                "committee_type_full": "Super PAC (Independent Expenditure-Only)",
                "treasurer_name": "MCINTYRE, DUSTIN",
                "state": "VA",
                "city": "ARLINGTON",
                "zip": "22307",
                "designation": "U",
                "cycles": [2022, 2024, 2026],
                "affiliated_committee_name": "NONE"
            }
        ]
    }

    monkeypatch.setattr(client.session, "get", lambda *args, **kwargs: mock_resp)

    profile = client.get_committee_profile("C00634261")
    assert profile is not None
    assert profile["cmte_id"] == "C00634261"
    assert profile["clean_treasurer"] == "MCINTYRE DUSTIN"


def test_fec_ingester_sync_committees_only(storage, tmp_path):
    """Verify sync_committees_only rapidly downloads and ingests cm.zip archive."""
    fec_dir = tmp_path / "fec"
    fec_dir.mkdir()
    ingester = FECIngester(storage, download_dir=str(fec_dir))

    # Create dummy cm26.zip with 1 committee line
    cm_zip_path = fec_dir / "cm26.zip"
    cm_line = "C00634261|DEFEND US PAC|MCINTYRE, DUSTIN|||ARLINGTON|VA|22307|U|O||Q|||\n"
    with zipfile.ZipFile(str(cm_zip_path), "w") as zf:
        zf.writestr("cm.txt", cm_line.encode("latin-1"))

    counts = ingester.sync_committees_only(cycles=[2026], force=False)
    assert 2026 in counts
    assert counts[2026] == 1

    cmte = storage.get_fec_committee("C00634261")
    assert cmte is not None
    assert cmte["name"] == "DEFEND US PAC"
    assert cmte["cmte_type"] == "O"


def test_fec_client_get_committee_profile_by_name_mocked(storage, monkeypatch):
    """Verify FECClient resolves committee name to ID and then fetches committee profile."""
    client = FECClient(storage=storage)

    # Mock search_committees returning C00634261 for query "Defend US PAC"
    search_mock = MagicMock()
    search_mock.status_code = 200
    search_mock.json.return_value = {
        "results": [
            {
                "committee_id": "C00634261",
                "name": "DEFEND US PAC",
                "committee_type": "O",
                "treasurer_name": "MCINTYRE, DUSTIN",
                "state": "VA",
                "city": "ARLINGTON",
                "zip": "22307"
            }
        ]
    }

    profile_mock = MagicMock()
    profile_mock.status_code = 200
    profile_mock.json.return_value = {
        "results": [
            {
                "committee_id": "C00634261",
                "name": "DEFEND US PAC",
                "committee_type": "O",
                "committee_type_full": "Super PAC (Independent Expenditure-Only)",
                "treasurer_name": "MCINTYRE, DUSTIN",
                "state": "VA",
                "city": "ARLINGTON",
                "zip": "22307",
                "designation": "U",
                "cycles": [2026],
                "affiliated_committee_name": "NONE"
            }
        ]
    }

    def mock_get(url, *args, **kwargs):
        if "/committees" in url and "committee/" not in url:
            return search_mock
        return profile_mock

    monkeypatch.setattr(client.session, "get", mock_get)

    profile = client.get_committee_profile("Defend US PAC")
    assert profile is not None
    assert profile["cmte_id"] == "C00634261"
    assert profile["name"] == "DEFEND US PAC"
    assert profile["cmte_type"] == "O"


def test_fec_classification_distinction():
    """Verify that FEC labels clearly distinguish between traditional PACs and Super PACs."""
    from irs990.fec import FEC_TYPE_LABELS, FEC_SHORT_TYPE_LABELS

    # Super PAC (Independent Expenditure-Only)
    assert "Super PAC" in FEC_TYPE_LABELS["O"]
    assert FEC_SHORT_TYPE_LABELS["O"] == "Super PAC"

    # Qualified Traditional PAC
    assert "Traditional PAC" in FEC_TYPE_LABELS["Q"]
    assert FEC_SHORT_TYPE_LABELS["Q"] == "Qualified PAC"

    # Hybrid PAC
    assert "Hybrid PAC" in FEC_TYPE_LABELS["V"]


