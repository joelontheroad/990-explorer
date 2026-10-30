# SPDX-FileCopyrightText: 2026 990-Explorer Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Data Freshness & Upstream Update Checker for IRS 990 Explorer.

Architectural Purpose:
    Probes official IRS and FEC upstream endpoints via lightweight HTTP HEAD requests
    to compare remote Last-Modified release dates against local DuckDB sync timestamps.

Security Invariants:
    - Uses zero-body HEAD requests with strict socket timeouts to prevent hanging or resource drain.
    - Zero telemetry: only contacts official public IRS and FEC government distribution portals.
"""

import os
import sys
import logging
import urllib.request
import email.utils
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

from .storage import IRS990Storage

logger = logging.getLogger(__name__)

IRS_BMF_URL = "https://www.irs.gov/pub/irs-soi/eo1.csv"
IRS_TEOS_INDEX_URL = "https://apps.irs.gov/pub/epostcard/990/xml/2024/index_2024.csv"
IRS_POFD_URL = "https://forms.irs.gov/app/pod/dataDownload/dataLayout"
FEC_BULK_PROBE_URL = "https://www.fec.gov/files/bulk-downloads/2026/cm26.zip"

# Recommended update cycles (in days)
BMF_MAX_AGE_DAYS = 35       # IRS updates BMF monthly (~every 30 days)
FILINGS_MAX_AGE_DAYS = 90   # Quarterly recommendation for comprehensive filing updates
POFD_MAX_AGE_DAYS = 14      # IRS updates 527 POFD weekly (every Saturday)
FEC_MAX_AGE_DAYS = 14       # FEC publishes regular updates during election cycles


class DataFreshnessChecker:
    """Inspector checking remote government endpoints for upstream data updates."""

    def __init__(self, storage: IRS990Storage, timeout_sec: int = 5) -> None:
        """Initialize data freshness checker with local storage and network timeout.

        Args:
            storage: Active DuckDB storage interface instance.
            timeout_sec: Maximum timeout in seconds for upstream HTTP HEAD probes.
        """
        self.storage = storage
        self.timeout_sec = timeout_sec

    def probe_remote_last_modified(self, url: str) -> Optional[datetime]:
        """Send a zero-bandwidth HTTP HEAD probe to retrieve upstream Last-Modified timestamp.

        Args:
            url: Upstream government endpoint URL.

        Returns:
            UTC datetime object if available; None if unreachable or unsupported.
        """
        req = urllib.request.Request(
            url,
            method="HEAD",
            headers={"User-Agent": "IRS-990-Explorer/2.0 (Data-Freshness-Check)"}
        )
        try:
            # SECURITY: Enforce strict socket timeout on upstream HTTP HEAD probes
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                lm_header = resp.headers.get("Last-Modified")
                if lm_header:
                    parsed_tuple = email.utils.parsedate_to_datetime(lm_header)
                    # Ensure timezone-aware UTC datetime
                    if parsed_tuple.tzinfo is None:
                        parsed_tuple = parsed_tuple.replace(tzinfo=timezone.utc)
                    else:
                        parsed_tuple = parsed_tuple.astimezone(timezone.utc)
                    return parsed_tuple
        except Exception as e:
            logger.debug(f"HTTP HEAD request to {url} failed: {e}")
        return None

    def check_bmf_freshness(self) -> Dict[str, Any]:
        """Evaluate whether local IRS Business Master File (BMF) data is out of date.

        Returns:
            Dictionary containing freshness status, timestamps, and age in days.
        """
        meta_list = self.storage.get_ingestion_metadata()
        bmf_meta = next((m for m in meta_list if m["source_id"] == "IRS_BMF"), None)

        # Check if table exists in DuckDB
        db_stats = self.storage.get_database_stats()
        bmf_stats = db_stats.get("bmf", {})
        table_present = bmf_stats.get("table_present", False)

        remote_date = self.probe_remote_last_modified(IRS_BMF_URL)
        now_utc = datetime.now(timezone.utc)

        if not table_present or not bmf_meta:
            return {
                "source_id": "IRS_BMF",
                "source_name": "IRS Business Master File (EO BMF)",
                "status": "NOT_INGESTED",
                "status_label": "❌ NOT INGESTED",
                "local_date": None,
                "remote_date": remote_date,
                "days_behind": None,
                "message": "Dataset has not been downloaded yet (~1.85M charities).",
                "action": "Run 'python main.py --sync-bmf' to download and index."
            }

        local_date = bmf_meta["last_synced_at"]
        if local_date and local_date.tzinfo is None:
            local_date = local_date.replace(tzinfo=timezone.utc)
        else:
            local_date = local_date.astimezone(timezone.utc)

        # 1. Online check against IRS Last-Modified
        if remote_date:
            if remote_date > local_date:
                days_diff = (remote_date - local_date).days
                return {
                    "source_id": "IRS_BMF",
                    "source_name": "IRS Business Master File (EO BMF)",
                    "status": "OUT_OF_DATE",
                    "status_label": "⚠️  OUT OF DATE",
                    "local_date": local_date,
                    "remote_date": remote_date,
                    "days_behind": max(1, days_diff),
                    "message": f"IRS published a newer monthly extract on {remote_date.strftime('%Y-%m-%d')}.",
                    "action": "Run 'python main.py --sync-bmf' to update."
                }
            else:
                return {
                    "source_id": "IRS_BMF",
                    "source_name": "IRS Business Master File (EO BMF)",
                    "status": "UP_TO_DATE",
                    "status_label": "✅ UP TO DATE",
                    "local_date": local_date,
                    "remote_date": remote_date,
                    "days_behind": 0,
                    "message": f"Matches latest IRS release ({remote_date.strftime('%Y-%m-%d')}).",
                    "action": "None (Current)."
                }

        # 2. Offline fallback (age-based)
        age_days = (now_utc - local_date).days
        if age_days > BMF_MAX_AGE_DAYS:
            return {
                "source_id": "IRS_BMF",
                "source_name": "IRS Business Master File (EO BMF)",
                "status": "POSSIBLY_STALE",
                "status_label": "⚠️  POSSIBLY STALE",
                "local_date": local_date,
                "remote_date": None,
                "days_behind": age_days,
                "message": f"Local copy is {age_days} days old (IRS publishes updates monthly).",
                "action": "Run 'python main.py --sync-bmf' to refresh."
            }
        else:
            return {
                "source_id": "IRS_BMF",
                "source_name": "IRS Business Master File (EO BMF)",
                "status": "UP_TO_DATE",
                "status_label": "✅ UP TO DATE",
                "local_date": local_date,
                "remote_date": None,
                "days_behind": 0,
                "message": f"Ingested {age_days} days ago (within 35-day monthly freshness window).",
                "action": "None (Current)."
            }

    def check_seeds_freshness(self) -> Dict[str, Any]:
        """Check status of curated institutional foundation seeds."""
        meta_list = self.storage.get_ingestion_metadata()
        seeds_meta = next((m for m in meta_list if m["source_id"] == "SEEDS"), None)

        if not seeds_meta:
            return {
                "source_id": "SEEDS",
                "source_name": "Curated Institutional Funders & Seeds",
                "status": "NOT_LOADED",
                "status_label": "ℹ️  NOT LOADED",
                "local_date": None,
                "remote_date": None,
                "days_behind": 0,
                "message": "Institutional seed foundations not yet seeded into database.",
                "action": "Run 'python main.py' to automatically verify and load seeds."
            }

        return {
            "source_id": "SEEDS",
            "source_name": "Curated Institutional Funders & Seeds",
            "status": "UP_TO_DATE",
            "status_label": "✅ UP TO DATE",
            "local_date": seeds_meta["last_synced_at"],
            "remote_date": None,
            "days_behind": 0,
            "message": f"Active with {seeds_meta['records_count']} verified institutional grants.",
            "action": "None (Current)."
        }

    def check_teos_freshness(self) -> Dict[str, Any]:
        """
        Check electronic 990 e-file filings and TEOS batch status.
        """
        db_stats = self.storage.get_database_stats()
        grants = db_stats.get("grants", {})
        filings = db_stats.get("filings", {})
        total_grants = grants.get("total_grants", 0)
        filings_count = filings.get("filings_ingested", 0)

        meta_list = self.storage.get_ingestion_metadata()
        bulk_meta = [m for m in meta_list if m["source_id"].startswith("ZIP_") or m["source_id"] == "BULK_DIR_INGEST"]
        latest_bulk = bulk_meta[0] if bulk_meta else None

        remote_date = self.probe_remote_last_modified(IRS_TEOS_INDEX_URL)
        now_utc = datetime.now(timezone.utc)

        if total_grants == 0:
            return {
                "source_id": "TEOS_FILINGS",
                "source_name": "Electronic 990 Schedules (Schedule I & R)",
                "status": "EMPTY",
                "status_label": "ℹ️  NO BULK FILINGS",
                "local_date": None,
                "remote_date": remote_date,
                "days_behind": None,
                "message": "No bulk 990 return archives loaded yet.",
                "action": "Load via 'python main.py --ingest-zip <FILE.zip>' or explore entities in web UI."
            }

        local_date = latest_bulk["last_synced_at"] if latest_bulk else None
        if local_date and local_date.tzinfo is None:
            local_date = local_date.replace(tzinfo=timezone.utc)

        if remote_date and local_date and remote_date > local_date:
            days_diff = (remote_date - local_date).days
            return {
                "source_id": "TEOS_FILINGS",
                "source_name": "Electronic 990 Schedules (Schedule I & R)",
                "status": "NEW_BATCH_AVAILABLE",
                "status_label": "ℹ️  NEW BATCH AVAILABLE",
                "local_date": local_date,
                "remote_date": remote_date,
                "days_behind": days_diff,
                "message": f"IRS published new return batches since local ingestion ({days_diff} days ago).",
                "action": "Download the latest monthly TEOS ZIP from IRS or query entities on-demand."
            }

        return {
            "source_id": "TEOS_FILINGS",
            "source_name": "Electronic 990 Schedules (Schedule I & R)",
            "status": "UP_TO_DATE",
            "status_label": "✅ ACTIVE",
            "local_date": local_date,
            "remote_date": remote_date,
            "days_behind": 0,
            "message": f"{total_grants:,} grants indexed across {filings_count:,} dynamic returns.",
            "action": "None (Active)."
        }

    def check_pofd_freshness(self) -> Dict[str, Any]:
        """
        Check if local IRS Section 527 Political Organizations (POFD) dataset is out of date.
        """
        meta_list = self.storage.get_ingestion_metadata()
        pofd_meta = next((m for m in meta_list if m["source_id"] == "IRS_527_POFD"), None)

        db_stats = self.storage.get_database_stats()
        pacs_stats = db_stats.get("pacs_527", {})
        total_527 = pacs_stats.get("total_527_orgs", 0)

        now_utc = datetime.now(timezone.utc)

        if not pofd_meta or total_527 == 0:
            return {
                "source_id": "IRS_527_POFD",
                "source_name": "IRS Section 527 Political Organizations (POFD)",
                "status": "NOT_INGESTED",
                "status_label": "❌ NOT INGESTED",
                "local_date": None,
                "remote_date": None,
                "days_behind": None,
                "message": "Section 527 political organizations dataset has not been synchronized yet.",
                "action": "Run 'python main.py --sync-527' to download and index."
            }

        local_date = pofd_meta["last_synced_at"]
        if local_date and local_date.tzinfo is None:
            local_date = local_date.replace(tzinfo=timezone.utc)
        elif local_date:
            local_date = local_date.astimezone(timezone.utc)

        age_days = (now_utc - local_date).days if local_date else 999

        if age_days > POFD_MAX_AGE_DAYS:
            return {
                "source_id": "IRS_527_POFD",
                "source_name": "IRS Section 527 Political Organizations (POFD)",
                "status": "OUT_OF_DATE",
                "status_label": "⚠️  OUT OF DATE",
                "local_date": local_date,
                "remote_date": None,
                "days_behind": age_days,
                "message": f"Local copy is {age_days} days old (IRS publishes updates weekly on Saturdays).",
                "action": "Run 'python main.py --sync-527' to refresh with latest weekly extract."
            }

        return {
            "source_id": "IRS_527_POFD",
            "source_name": "IRS Section 527 Political Organizations (POFD)",
            "status": "UP_TO_DATE",
            "status_label": "✅ UP TO DATE",
            "local_date": local_date,
            "remote_date": None,
            "days_behind": age_days,
            "message": f"Matches recent IRS weekly release ({total_527:,} political committees indexed).",
            "action": "None (Current)."
        }

    def check_fec_freshness(self) -> Dict[str, Any]:
        """
        Check if local Federal Election Commission (FEC) PAC & Super PAC data is out of date.
        """
        meta_list = self.storage.get_ingestion_metadata()
        fec_meta = [m for m in meta_list if m["source_id"].startswith("FEC_")]

        db_stats = self.storage.get_database_stats()
        fec_stats = db_stats.get("fec_pacs", {})
        total_cmte = fec_stats.get("total_committees", 0)

        remote_date = self.probe_remote_last_modified(FEC_BULK_PROBE_URL)
        now_utc = datetime.now(timezone.utc)

        if total_cmte == 0 or not fec_meta:
            return {
                "source_id": "FEC_BULK",
                "source_name": "FEC Political Committees & PACs",
                "status": "NOT_INGESTED",
                "status_label": "❌ NOT INGESTED",
                "local_date": None,
                "remote_date": remote_date,
                "days_behind": None,
                "message": "Federal PACs and political committees have not been ingested yet.",
                "action": "Run 'python main.py --sync-fec' to download and index (default: 3 cycles: 2022, 2024, 2026)."
            }

        local_date = max(m["last_synced_at"] for m in fec_meta)
        if local_date and local_date.tzinfo is None:
            local_date = local_date.replace(tzinfo=timezone.utc)

        age_days = (now_utc - local_date).days if local_date else 999

        if age_days > FEC_MAX_AGE_DAYS:
            return {
                "source_id": "FEC_BULK",
                "source_name": "FEC Political Committees & PACs",
                "status": "OUT_OF_DATE",
                "status_label": "⚠️  OUT OF DATE",
                "local_date": local_date,
                "remote_date": remote_date,
                "days_behind": age_days,
                "message": f"Local copy is {age_days} days old (FEC publishes regular nightly/weekly updates).",
                "action": "Run 'python main.py --sync-fec' to refresh."
            }

        cycles_str = ", ".join(str(c) for c in fec_stats.get("cycles", []))
        return {
            "source_id": "FEC_BULK",
            "source_name": "FEC Political Committees & PACs",
            "status": "UP_TO_DATE",
            "status_label": "✅ UP TO DATE",
            "local_date": local_date,
            "remote_date": remote_date,
            "days_behind": age_days,
            "message": f"{total_cmte:,} federal committees indexed across cycle(s) {cycles_str}.",
            "action": "None (Current)."
        }

    def run_full_check(self) -> Dict[str, Any]:
        """
        Run checks across all data sources and print formatted report to console.
        """
        print("\n" + "=" * 76)
        print("           IRS 990 EXPLORER — UPSTREAM FRESHNESS & UPDATE CHECK")
        print("=" * 76)
        print(f" Database: {self.storage.db_path}")
        print(" Probing official IRS & FEC upstream servers...")

        bmf_res = self.check_bmf_freshness()
        seeds_res = self.check_seeds_freshness()
        teos_res = self.check_teos_freshness()
        pofd_res = self.check_pofd_freshness()
        fec_res = self.check_fec_freshness()

        results = [bmf_res, seeds_res, teos_res, pofd_res, fec_res]
        has_out_of_date = any(r["status"] in ("OUT_OF_DATE", "POSSIBLY_STALE", "NOT_INGESTED") for r in results)

        print("\n" + "-" * 76)
        print(" DATA SOURCE FRESHNESS AUDIT")
        print("-" * 76)

        for i, res in enumerate(results, 1):
            print(f"[{i}] {res['source_name']}")
            print(f"    Status:          {res['status_label']}")
            if res.get("local_date"):
                loc_str = res['local_date'].strftime('%Y-%m-%d %H:%M:%S UTC')
                print(f"    Local Ingestion: {loc_str}")
            else:
                print("    Local Ingestion: None")

            if res.get("remote_date"):
                rem_str = res['remote_date'].strftime('%Y-%m-%d %H:%M:%S UTC')
                print(f"    Upstream Latest: {rem_str}")

            print(f"    Analysis:        {res['message']}")
            print(f"    Action:          {res['action']}")
            print()

        print("-" * 76)
        if has_out_of_date:
            out_names = [r["source_name"] for r in results if r["status"] in ("OUT_OF_DATE", "POSSIBLY_STALE", "NOT_INGESTED")]
            print(f" SUMMARY: {len(out_names)} data source(s) require attention ({', '.join(out_names)}).")
            if any(r["source_id"] == "IRS_BMF" and r["status"] in ("OUT_OF_DATE", "NOT_INGESTED", "POSSIBLY_STALE") for r in results):
                print(" Quick Update Command: python main.py --sync-bmf")
            if any(r["source_id"] == "IRS_527_POFD" and r["status"] in ("OUT_OF_DATE", "NOT_INGESTED") for r in results):
                print(" Quick Update Command: python main.py --sync-527")
            if any(r["source_id"] == "FEC_BULK" and r["status"] in ("OUT_OF_DATE", "NOT_INGESTED") for r in results):
                print(" Quick Update Command: python main.py --sync-fec")
        else:
            print(" SUMMARY: All local data sources are up to date!")
        print("=" * 76 + "\n")

        return {
            "has_updates": has_out_of_date,
            "results": results,
            "checked_at": datetime.now(timezone.utc)
        }

