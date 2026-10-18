# SPDX-FileCopyrightText: 2026 990-Explorer Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for DataFreshnessChecker in irs990/freshness.py.

Architectural Purpose:
    Validates upstream HTTP HEAD timestamp probing, freshness evaluation,
    status classification, and maintenance recommendation workflows.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from irs990.storage import IRS990Storage
from irs990.bmf import BMF_SCHEMA_SQL
from irs990.freshness import DataFreshnessChecker


def test_freshness_not_ingested():
    storage = IRS990Storage(":memory:")
    checker = DataFreshnessChecker(storage)

    with patch.object(checker, "probe_remote_last_modified", return_value=datetime(2026, 9, 7, tzinfo=timezone.utc)):
        res = checker.check_bmf_freshness()
        assert res["status"] == "NOT_INGESTED"
        assert "NOT INGESTED" in res["status_label"]
        assert "sync-bmf" in res["action"]


def test_freshness_up_to_date():
    storage = IRS990Storage(":memory:")
    storage.conn.execute(BMF_SCHEMA_SQL)
    now_utc = datetime.now(timezone.utc)
    storage.record_sync("IRS_BMF", "IRS EO BMF", 1850000, "Extract")

    checker = DataFreshnessChecker(storage)
    remote_date = now_utc - timedelta(days=5)

    with patch.object(checker, "probe_remote_last_modified", return_value=remote_date):
        res = checker.check_bmf_freshness()
        assert res["status"] == "UP_TO_DATE"
        assert "UP TO DATE" in res["status_label"]


def test_freshness_out_of_date():
    storage = IRS990Storage(":memory:")
    storage.conn.execute(BMF_SCHEMA_SQL)
    past_date = datetime(2026, 7, 1, tzinfo=timezone.utc)
    storage.conn.execute("""
        INSERT INTO ingestion_metadata (source_id, source_name, last_synced_at, records_count)
        VALUES ('IRS_BMF', 'IRS EO BMF', ?, 1850000);
    """, (past_date,))

    checker = DataFreshnessChecker(storage)
    newer_remote_date = datetime(2026, 9, 7, tzinfo=timezone.utc)

    with patch.object(checker, "probe_remote_last_modified", return_value=newer_remote_date):
        res = checker.check_bmf_freshness()
        assert res["status"] == "OUT_OF_DATE"
        assert "OUT OF DATE" in res["status_label"]
        assert res["days_behind"] > 0
        assert "sync-bmf" in res["action"]


def test_freshness_offline_fallback():
    storage = IRS990Storage(":memory:")
    storage.conn.execute(BMF_SCHEMA_SQL)
    # Ingested 50 days ago
    stale_date = datetime.now(timezone.utc) - timedelta(days=50)
    storage.conn.execute("""
        INSERT INTO ingestion_metadata (source_id, source_name, last_synced_at, records_count)
        VALUES ('IRS_BMF', 'IRS EO BMF', ?, 1850000);
    """, (stale_date,))

    checker = DataFreshnessChecker(storage)

    # Remote probe fails (None returned)
    with patch.object(checker, "probe_remote_last_modified", return_value=None):
        res = checker.check_bmf_freshness()
        assert res["status"] == "POSSIBLY_STALE"
        assert "POSSIBLY STALE" in res["status_label"]
        assert res["days_behind"] >= 50


def test_bmf_sync_skips_when_up_to_date():
    storage = IRS990Storage(":memory:")
    storage.conn.execute(BMF_SCHEMA_SQL)
    storage.record_sync("IRS_BMF", "IRS EO BMF", 1850000, "Extract")

    from irs990.bmf import BMFIngester
    ingester = BMFIngester(storage)

    with patch.object(DataFreshnessChecker, "probe_remote_last_modified", return_value=datetime(2026, 1, 1, tzinfo=timezone.utc)):
        with patch.object(ingester, "download_file") as mock_download:
            res = ingester.sync(force_download=False)
            assert res["status"] == "skipped"
            assert res["reason"] == "up_to_date"
            mock_download.assert_not_called()


def test_bmf_sync_force_download_overrides():
    storage = IRS990Storage(":memory:")
    storage.conn.execute(BMF_SCHEMA_SQL)
    storage.record_sync("IRS_BMF", "IRS EO BMF", 1850000, "Extract")

    import os
    import tempfile
    from irs990.bmf import BMFIngester
    ingester = BMFIngester(storage)

    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as f:
        f.write("EIN,NAME,ICO,STREET,CITY,STATE,ZIP,GROUP,SUBSECTION,AFFILIATION,CLASSIFICATION,RULING,DEDUCTIBILITY,FOUNDATION,ACTIVITY,ORGANIZATION,STATUS,TAX_PERIOD,ASSET_CD,INCOME_CD,FILING_REQ_CD,PF_FILING_REQ_CD,ACCT_PD,ASSET_AMT,INCOME_AMT,REVENUE_AMT,NTEE_CD,SORT_NAME\n")
        f.write("112233445,TEST CHARITY,,123 ST,CITY,CA,94105,,03,,,,,01,,,,,,,,,,0,0,0,,\n")
        dummy_csv = f.name

    try:
        with patch.object(ingester, "download_file", return_value=dummy_csv) as mock_download:
            res = ingester.sync(force_download=True, max_files=1)
            assert mock_download.called
            assert res.get("status") != "skipped"
            assert res.get("total_records", 0) >= 1
    finally:
        if os.path.exists(dummy_csv):
            os.remove(dummy_csv)


def test_seeds_skip_when_already_loaded():
    from irs990.seeds import load_seed_data
    storage = IRS990Storage(":memory:")

    # First time: seeds should be inserted
    loaded_1 = load_seed_data(storage, force=False)
    assert loaded_1 is True

    # Second time: should skip redundant insertion
    loaded_2 = load_seed_data(storage, force=False)
    assert loaded_2 is False

    # Force: should re-insert
    loaded_3 = load_seed_data(storage, force=True)
    assert loaded_3 is True
