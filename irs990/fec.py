# SPDX-FileCopyrightText: 2026 990-Explorer Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Federal Election Commission (FEC) Bulk Data Ingestion Engine.

Architectural Purpose:
    Downloads, streams, unpacks, and indexes Federal Election Commission (FEC) bulk data
    including PACs, Super PACs, candidate linkages, independent expenditures (Schedule E),
    and operating expenditures (Schedule B) across multi-year election cycles into DuckDB.

Security Invariants:
    - Protects against Zip Slip path traversal (CWE-22) when extracting bulk zip archives.
    - Uses parameterized batch insertion queries on DuckDB.
"""

import os
import sys
import logging
import urllib.request
import zipfile
import io
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple

from .storage import IRS990Storage, DEFAULT_DB_PATH
from .parser import normalize_person_name

logger = logging.getLogger(__name__)

FEC_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "fec")

# Default to 3 election cycles (current cycle + previous two cycles = 6 calendar years)
DEFAULT_FEC_CYCLES = [2022, 2024, 2026]

FEC_BULK_BASE_URL = "https://www.fec.gov/files/bulk-downloads"


def _safe_float(val: str, default: float = 0.0) -> float:
    try:
        clean = val.replace("$", "").replace(",", "").strip()
        return float(clean) if clean and clean.upper() != "NONE" else default
    except Exception:
        return default


def _safe_fec_date(val: str) -> Optional[str]:
    """Parse FEC date format MMDDYYYY to YYYY-MM-DD."""
    clean = val.strip()
    if len(clean) == 8 and clean.isdigit():
        month = clean[:2]
        day = clean[2:4]
        year = clean[4:]
        return f"{year}-{month}-{day}"
    return clean if clean else None


class FECIngester:
    def __init__(self, storage: IRS990Storage, download_dir: str = FEC_DATA_DIR):
        self.storage = storage
        self.download_dir = download_dir
        os.makedirs(self.download_dir, exist_ok=True)

    def download_file(self, url: str, dest_path: str, label: str, force: bool = False) -> str:
        """Download bulk FEC zip archive with streaming progress indication."""
        if os.path.exists(dest_path) and not force:
            size_mb = os.path.getsize(dest_path) / (1024 * 1024)
            print(f"  [Cached] {label}: {os.path.basename(dest_path)} ({size_mb:.1f} MB already downloaded)")
            return dest_path

        print(f"  [Downloading] {label} from {url}...")
        headers = {
            "User-Agent": "IRS-990-Explorer/2.0 (Nonprofit & Political Network Research; contact: researcher@example.org)"
        }
        req = urllib.request.Request(url, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                total_size = resp.getheader("Content-Length")
                total_bytes = int(total_size) if total_size else 0

                downloaded = 0
                block_size = 65536
                start_time = time.time()

                with open(dest_path, "wb") as f_out:
                    while True:
                        chunk = resp.read(block_size)
                        if not chunk:
                            break
                        f_out.write(chunk)
                        downloaded += len(chunk)

                        if total_bytes > 0:
                            pct = (downloaded / total_bytes) * 100
                            mb = downloaded / (1024 * 1024)
                            total_mb = total_bytes / (1024 * 1024)
                            sys.stdout.write(f"\r    {mb:.1f} MB / {total_mb:.1f} MB ({pct:.1f}%)...")
                        else:
                            mb = downloaded / (1024 * 1024)
                            sys.stdout.write(f"\r    {mb:.1f} MB downloaded...")
                        sys.stdout.flush()

                elapsed = time.time() - start_time
                mb = downloaded / (1024 * 1024)
                rate = mb / elapsed if elapsed > 0 else 0
                print(f"\r    Successfully downloaded {mb:.1f} MB in {elapsed:.1f}s ({rate:.1f} MB/s)")
                return dest_path

        except Exception as e:
            if os.path.exists(dest_path):
                os.remove(dest_path)
            raise RuntimeError(f"Failed downloading {label} from {url}: {e}")

    def parse_cm_stream(self, file_obj, cycle: int) -> int:
        """
        Parse Committee Master (cm.txt) line by line.
        Fields:
        0: CMTE_ID
        1: CMTE_NM
        2: TRES_NM
        3: CMTE_ST1
        4: CMTE_ST2
        5: CMTE_CITY
        6: CMTE_ST
        7: CMTE_ZIP
        8: CMTE_DSG
        9: CMTE_TP
        10: CMTE_PTY_AFFILIATION
        11: FILING_FREQ
        12: ORG_TP
        13: CONNECTED_ORG_NM
        14: CAND_ID
        """
        batch = []
        count = 0
        batch_size = 5000

        for line_raw in file_obj:
            text = line_raw.decode("latin-1", errors="ignore").strip()
            if not text:
                continue
            parts = text.split("|")
            if len(parts) < 10:
                continue

            cmte_id = parts[0].strip()
            cmte_name = parts[1].strip()
            tres_name = parts[2].strip() if len(parts) > 2 else ""
            clean_tres = normalize_person_name(tres_name)
            city = parts[5].strip() if len(parts) > 5 else ""
            state = parts[6].strip() if len(parts) > 6 else ""
            zip_code = parts[7].strip() if len(parts) > 7 else ""
            cmte_dsg = parts[8].strip() if len(parts) > 8 else ""
            cmte_tp = parts[9].strip() if len(parts) > 9 else ""
            pty = parts[10].strip() if len(parts) > 10 else ""
            org_tp = parts[12].strip() if len(parts) > 12 else ""
            conn_org = parts[13].strip() if len(parts) > 13 else ""
            clean_conn = normalize_person_name(conn_org)
            cand_id = parts[14].strip() if len(parts) > 14 else ""

            batch.append((
                cmte_id, cmte_name, tres_name, clean_tres, city, state, zip_code,
                cmte_dsg, cmte_tp, pty, org_tp, conn_org, clean_conn, cand_id, cycle
            ))
            count += 1

            if len(batch) >= batch_size:
                self.storage.upsert_fec_committees(batch)
                batch.clear()

        if batch:
            self.storage.upsert_fec_committees(batch)
            batch.clear()

        return count

    def parse_cn_stream(self, file_obj, cycle: int) -> int:
        """
        Parse Candidate Master (cn.txt) line by line.
        Fields:
        0: CAND_ID
        1: CAND_NAME
        2: CAND_PTY_AFFILIATION
        3: CAND_ELECTION_YR
        4: CAND_OFFICE_ST
        5: CAND_OFFICE
        6: CAND_OFFICE_DISTRICT
        7: CAND_ICI
        8: CAND_STATUS
        9: CAND_PCC
        """
        batch = []
        count = 0
        batch_size = 5000

        for line_raw in file_obj:
            text = line_raw.decode("latin-1", errors="ignore").strip()
            if not text:
                continue
            parts = text.split("|")
            if len(parts) < 6:
                continue

            cand_id = parts[0].strip()
            cand_name = parts[1].strip()
            clean_cand = normalize_person_name(cand_name)
            pty = parts[2].strip() if len(parts) > 2 else ""
            try:
                eyr = int(parts[3].strip()) if len(parts) > 3 and parts[3].strip().isdigit() else cycle
            except Exception:
                eyr = cycle
            st = parts[4].strip() if len(parts) > 4 else ""
            office = parts[5].strip() if len(parts) > 5 else ""
            district = parts[6].strip() if len(parts) > 6 else ""
            pcc = parts[9].strip() if len(parts) > 9 else ""

            batch.append((
                cand_id, cand_name, clean_cand, pty, eyr, st, office, district, pcc, cycle
            ))
            count += 1

            if len(batch) >= batch_size:
                self.storage.upsert_fec_candidates(batch)
                batch.clear()

        if batch:
            self.storage.upsert_fec_candidates(batch)
            batch.clear()

        return count

    def parse_ccl_stream(self, file_obj, cycle: int) -> int:
        """
        Parse Candidate Linkages (ccl.txt) line by line.
        Fields:
        0: CAND_ID
        1: CAND_ELECTION_YR
        2: FEC_ELECTION_YR
        3: CMTE_ID
        4: CMTE_TP
        5: CMTE_DSG
        6: LINKAGE_ID
        """
        batch = []
        count = 0
        batch_size = 5000

        for line_raw in file_obj:
            text = line_raw.decode("latin-1", errors="ignore").strip()
            if not text:
                continue
            parts = text.split("|")
            if len(parts) < 4:
                continue

            cand_id = parts[0].strip()
            try:
                c_eyr = int(parts[1].strip()) if parts[1].strip().isdigit() else cycle
            except Exception:
                c_eyr = cycle
            try:
                f_eyr = int(parts[2].strip()) if parts[2].strip().isdigit() else cycle
            except Exception:
                f_eyr = cycle
            cmte_id = parts[3].strip()
            cmte_tp = parts[4].strip() if len(parts) > 4 else ""
            cmte_dsg = parts[5].strip() if len(parts) > 5 else ""
            link_id = parts[6].strip() if len(parts) > 6 else f"{cand_id}:{cmte_id}:{cycle}"
            pk = f"{cand_id}:{cmte_id}:{link_id}:{cycle}"

            batch.append((
                pk, cand_id, c_eyr, f_eyr, cmte_id, cmte_tp, cmte_dsg, link_id, cycle
            ))
            count += 1

            if len(batch) >= batch_size:
                self.storage.upsert_fec_linkages(batch)
                batch.clear()

        if batch:
            self.storage.upsert_fec_linkages(batch)
            batch.clear()

        return count

    def parse_pas2_stream(self, file_obj, cycle: int) -> int:
        """
        Parse Contributions to Candidates and Independent Expenditures (itpas2.txt).
        Fields:
        0: CMTE_ID
        5: TRANSACTION_TP (24A, 24E, 24K, etc.)
        6: ENTITY_TP
        7: NAME
        8: CITY
        9: STATE
        10: ZIP_CODE
        11: EMPLOYER
        12: OCCUPATION
        13: TRANSACTION_DT
        14: TRANSACTION_AMT
        15: OTHER_ID (Candidate or Committee ID)
        19: MEMO_TEXT
        20: SUB_ID
        """
        batch = []
        count = 0
        batch_size = 5000

        for line_raw in file_obj:
            text = line_raw.decode("latin-1", errors="ignore").strip()
            if not text:
                continue
            parts = text.split("|")
            if len(parts) < 15:
                continue

            cmte_id = parts[0].strip()
            tx_type = parts[5].strip() if len(parts) > 5 else ""
            entity_type = parts[6].strip() if len(parts) > 6 else ""
            recip_name = parts[7].strip() if len(parts) > 7 else ""
            city = parts[8].strip() if len(parts) > 8 else ""
            state = parts[9].strip() if len(parts) > 9 else ""
            zip_code = parts[10].strip() if len(parts) > 10 else ""
            employer = parts[11].strip() if len(parts) > 11 else ""
            occ = parts[12].strip() if len(parts) > 12 else ""
            tx_date = _safe_fec_date(parts[13]) if len(parts) > 13 else None
            amount = _safe_float(parts[14]) if len(parts) > 14 else 0.0
            other_id = parts[15].strip() if len(parts) > 15 else ""
            memo = parts[19].strip() if len(parts) > 19 else ""
            sub_id = parts[20].strip() if len(parts) > 20 else f"{cmte_id}:{tx_type}:{count}"

            batch.append((
                sub_id, cmte_id, tx_type, entity_type, recip_name,
                city, state, zip_code, employer, occ, tx_date,
                amount, other_id, memo, cycle
            ))
            count += 1

            if len(batch) >= batch_size:
                self.storage.upsert_fec_transactions(batch)
                batch.clear()

        if batch:
            self.storage.upsert_fec_transactions(batch)
            batch.clear()

        return count

    def parse_oppexp_stream(self, file_obj, cycle: int) -> int:
        """
        Parse Operating Expenditures / Vendor Disbursements (oppexp.txt).
        Fields:
        0: CMTE_ID
        8: NAME (Payee)
        9: CITY
        10: STATE
        11: ZIP_CODE
        12: TRANSACTION_DT
        13: TRANSACTION_AMT
        15: PURPOSE
        17: CATEGORY_DESC
        21: SUB_ID
        """
        batch = []
        count = 0
        batch_size = 5000

        for line_raw in file_obj:
            text = line_raw.decode("latin-1", errors="ignore").strip()
            if not text:
                continue
            parts = text.split("|")
            if len(parts) < 14:
                continue

            cmte_id = parts[0].strip()
            payee = parts[8].strip() if len(parts) > 8 else ""
            city = parts[9].strip() if len(parts) > 9 else ""
            state = parts[10].strip() if len(parts) > 10 else ""
            zip_code = parts[11].strip() if len(parts) > 11 else ""
            tx_date = _safe_fec_date(parts[12]) if len(parts) > 12 else None
            amount = _safe_float(parts[13]) if len(parts) > 13 else 0.0
            purpose = parts[15].strip() if len(parts) > 15 else ""
            cat_desc = parts[17].strip() if len(parts) > 17 else ""
            sub_id = parts[21].strip() if len(parts) > 21 else f"{cmte_id}:{payee}:{count}"

            batch.append((
                sub_id, cmte_id, payee, city, state, zip_code,
                tx_date, amount, purpose, cat_desc, cycle
            ))
            count += 1

            if len(batch) >= batch_size:
                self.storage.upsert_fec_operating_expenditures(batch)
                batch.clear()

        if batch:
            self.storage.upsert_fec_operating_expenditures(batch)
            batch.clear()

        return count

    def sync_cycle(self, cycle: int, include_expenditures: bool = True, force: bool = False) -> Dict[str, int]:
        """Download and ingest complete dataset for a specific 2-year election cycle."""
        yy = str(cycle)[-2:]
        counts = {"committees": 0, "candidates": 0, "linkages": 0, "transactions": 0, "operating_expenditures": 0}

        print(f"\n============================================================================")
        print(f"  🗳️  INGESTING FEC ELECTION CYCLE {cycle} (cm{yy}, cn{yy}, ccl{yy})")
        print(f"============================================================================")

        # 1. Committee Master (cm.zip)
        cm_url = f"{FEC_BULK_BASE_URL}/{cycle}/cm{yy}.zip"
        cm_dest = os.path.join(self.download_dir, f"cm{yy}.zip")
        try:
            self.download_file(cm_url, cm_dest, f"Committee Master {cycle}", force=force)
            with zipfile.ZipFile(cm_dest, "r") as zf:
                fname = zf.namelist()[0]
                with zf.open(fname) as f_obj:
                    counts["committees"] = self.parse_cm_stream(f_obj, cycle)
            print(f"    ✅ Ingested {counts['committees']:,} political committees (Super PACs, PACs, campaigns)")
        except Exception as e:
            print(f"    ⚠️  Could not ingest Committee Master for {cycle}: {e}")

        # 2. Candidate Master (cn.zip)
        cn_url = f"{FEC_BULK_BASE_URL}/{cycle}/cn{yy}.zip"
        cn_dest = os.path.join(self.download_dir, f"cn{yy}.zip")
        try:
            self.download_file(cn_url, cn_dest, f"Candidate Master {cycle}", force=force)
            with zipfile.ZipFile(cn_dest, "r") as zf:
                fname = zf.namelist()[0]
                with zf.open(fname) as f_obj:
                    counts["candidates"] = self.parse_cn_stream(f_obj, cycle)
            print(f"    ✅ Ingested {counts['candidates']:,} federal candidates")
        except Exception as e:
            print(f"    ⚠️  Could not ingest Candidate Master for {cycle}: {e}")

        # 3. Candidate-to-Committee Linkages (ccl.zip)
        ccl_url = f"{FEC_BULK_BASE_URL}/{cycle}/ccl{yy}.zip"
        ccl_dest = os.path.join(self.download_dir, f"ccl{yy}.zip")
        try:
            self.download_file(ccl_url, ccl_dest, f"Candidate Linkages {cycle}", force=force)
            with zipfile.ZipFile(ccl_dest, "r") as zf:
                fname = zf.namelist()[0]
                with zf.open(fname) as f_obj:
                    counts["linkages"] = self.parse_ccl_stream(f_obj, cycle)
            print(f"    ✅ Ingested {counts['linkages']:,} candidate linkages")
        except Exception as e:
            print(f"    ⚠️  Could not ingest Candidate Linkages for {cycle}: {e}")

        # 4. Committee Contributions to Candidates & Indep Expenditures (pas2.zip)
        if include_expenditures:
            pas2_url = f"{FEC_BULK_BASE_URL}/{cycle}/pas2{yy}.zip"
            pas2_dest = os.path.join(self.download_dir, f"pas2{yy}.zip")
            try:
                self.download_file(pas2_url, pas2_dest, f"Independent Expenditures & Contributions {cycle}", force=force)
                with zipfile.ZipFile(pas2_dest, "r") as zf:
                    fname = zf.namelist()[0]
                    with zf.open(fname) as f_obj:
                        counts["transactions"] = self.parse_pas2_stream(f_obj, cycle)
                print(f"    ✅ Ingested {counts['transactions']:,} transactions / independent expenditures")
            except Exception as e:
                print(f"    ⚠️  Could not ingest Transactions for {cycle}: {e}")

            # 5. Operating Expenditures / Payees (oppexp.zip)
            opp_url = f"{FEC_BULK_BASE_URL}/{cycle}/oppexp{yy}.zip"
            opp_dest = os.path.join(self.download_dir, f"oppexp{yy}.zip")
            try:
                self.download_file(opp_url, opp_dest, f"Operating Expenditures & Vendors {cycle}", force=force)
                with zipfile.ZipFile(opp_dest, "r") as zf:
                    fname = zf.namelist()[0]
                    with zf.open(fname) as f_obj:
                        counts["operating_expenditures"] = self.parse_oppexp_stream(f_obj, cycle)
                print(f"    ✅ Ingested {counts['operating_expenditures']:,} operating expenditures & vendor payments")
            except Exception as e:
                print(f"    ⚠️  Could not ingest Operating Expenditures for {cycle}: {e}")

        # Record metadata
        total_records = sum(counts.values())
        self.storage.record_sync(
            f"FEC_{cycle}",
            f"FEC Bulk Data Cycle {cycle}",
            total_records,
            f"Committees: {counts['committees']}, Cand: {counts['candidates']}, Links: {counts['linkages']}, Tx: {counts['transactions']}, OppExp: {counts['operating_expenditures']}"
        )

        return counts

    def sync_all_cycles(self, cycles: Optional[List[int]] = None, include_expenditures: bool = True, force: bool = False) -> Dict[int, Dict[str, int]]:
        """Synchronize election cycles (defaults to 3 cycles: 2022, 2024, 2026)."""
        target_cycles = cycles or DEFAULT_FEC_CYCLES
        results = {}
        for c in target_cycles:
            results[c] = self.sync_cycle(c, include_expenditures=include_expenditures, force=force)
        return results
