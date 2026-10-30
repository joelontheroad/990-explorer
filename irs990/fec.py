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
import requests
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple

from .storage import IRS990Storage, DEFAULT_DB_PATH
from .parser import normalize_person_name

logger = logging.getLogger(__name__)

FEC_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "fec")

# Default to 3 election cycles (current cycle + previous two cycles = 6 calendar years)
DEFAULT_FEC_CYCLES = [2022, 2024, 2026]

FEC_BULK_BASE_URL = "https://www.fec.gov/files/bulk-downloads"
FEC_API_BASE_URL = "https://api.open.fec.gov/v1"
OPEN_FEC_DEMO_KEY = "DEMO_KEY"

FEC_TYPE_LABELS: Dict[str, str] = {
    "O": "Super PAC (Independent Expenditure-Only Committee)",
    "V": "Hybrid PAC (With Non-Contribution Account)",
    "Q": "Qualified Traditional PAC",
    "N": "Nonqualified PAC",
    "H": "House Candidate Committee",
    "S": "Senate Candidate Committee",
    "P": "Presidential Candidate Committee",
    "X": "Party Committee",
    "Z": "National Party Non-Federal Account",
    "D": "Leadership PAC",
    "U": "Single Candidate Independent Expenditure",
    "C": "Communication Cost Filer"
}

FEC_SHORT_TYPE_LABELS: Dict[str, str] = {
    "O": "Super PAC",
    "V": "Hybrid PAC",
    "Q": "Qualified PAC",
    "N": "Nonqualified PAC",
    "H": "House Candidate Comm",
    "S": "Senate Candidate Comm",
    "P": "Presidential Candidate Comm",
    "X": "Party Committee",
    "Z": "National Party Non-Federal",
    "D": "Leadership PAC"
}


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

            if count % 5000 == 0:
                print(f"      [Ingesting Committees] {count:,} records processed...", end="\r", flush=True)

            if len(batch) >= batch_size:
                self.storage.upsert_fec_committees(batch)
                batch.clear()

        if batch:
            self.storage.upsert_fec_committees(batch)
            batch.clear()

        if count >= 5000:
            print(f"      [Ingesting Committees] {count:,} records processed. Done!    ")
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

            if count % 5000 == 0:
                print(f"      [Ingesting Candidates] {count:,} records processed...", end="\r", flush=True)

            if len(batch) >= batch_size:
                self.storage.upsert_fec_candidates(batch)
                batch.clear()

        if batch:
            self.storage.upsert_fec_candidates(batch)
            batch.clear()

        if count >= 5000:
            print(f"      [Ingesting Candidates] {count:,} records processed. Done!    ")
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

            if count % 5000 == 0:
                print(f"      [Ingesting Linkages] {count:,} records processed...", end="\r", flush=True)

            if len(batch) >= batch_size:
                self.storage.upsert_fec_linkages(batch)
                batch.clear()

        if batch:
            self.storage.upsert_fec_linkages(batch)
            batch.clear()

        if count >= 5000:
            print(f"      [Ingesting Linkages] {count:,} records processed. Done!      ")
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

            if count % 10000 == 0:
                print(f"      [Ingesting Independent Exp] {count:,} records processed...", end="\r", flush=True)

            if len(batch) >= batch_size:
                self.storage.upsert_fec_transactions(batch)
                batch.clear()

        if batch:
            self.storage.upsert_fec_transactions(batch)
            batch.clear()

        if count >= 10000:
            print(f"      [Ingesting Independent Exp] {count:,} records processed. Done!  ")
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

            if count % 10000 == 0:
                print(f"      [Ingesting Vendor Disbursements] {count:,} records processed...", end="\r", flush=True)

            if len(batch) >= batch_size:
                self.storage.upsert_fec_operating_expenditures(batch)
                batch.clear()

        if batch:
            self.storage.upsert_fec_operating_expenditures(batch)
            batch.clear()

        if count >= 10000:
            print(f"      [Ingesting Vendor Disbursements] {count:,} records processed. Done! ")
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

    def _ingest_cm_native_duckdb(self, zip_path: str, cycle: int) -> Optional[int]:
        """Fast-path native DuckDB vectorized bulk ingestion of Committee Master zip file.

        Extracts cm.txt to temporary file and loads via DuckDB's C++ read_csv scanner
        in milliseconds.

        Args:
            zip_path: Path to cm{yy}.zip file on disk.
            cycle: 2-year election cycle year.

        Returns:
            Number of committees inserted/updated, or None on error.
        """
        import tempfile
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                target_name = None
                for n in zf.namelist():
                    if n.endswith(".txt"):
                        target_name = n
                        break
                if not target_name:
                    target_name = zf.namelist()[0]

                with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp_f:
                    tmp_path = tmp_f.name
                    with zf.open(target_name) as src:
                        while True:
                            buf = src.read(1024 * 1024)
                            if not buf:
                                break
                            tmp_f.write(buf)

            try:
                conn = self.storage.conn
                conn.execute("""
                    INSERT OR REPLACE INTO fec_committees
                    SELECT
                        trim(cmte_id) as cmte_id,
                        trim(cmte_name) as cmte_name,
                        coalesce(trim(tres_name), '') as treasurer_name,
                        coalesce(upper(regexp_replace(trim(tres_name), '[^a-zA-Z0-9 ]', ' ', 'g')), '') as clean_treasurer,
                        coalesce(trim(city), '') as city,
                        coalesce(trim(state), '') as state,
                        coalesce(trim(zip), '') as zip,
                        coalesce(trim(cmte_dsg), '') as cmte_designation,
                        coalesce(trim(cmte_tp), '') as cmte_type,
                        coalesce(trim(pty), '') as party_affiliation,
                        coalesce(trim(org_tp), '') as org_type,
                        coalesce(trim(conn_org), '') as connected_org_name,
                        coalesce(upper(regexp_replace(trim(conn_org), '[^a-zA-Z0-9 ]', ' ', 'g')), '') as clean_connected_org,
                        coalesce(trim(cand_id), '') as candidate_id,
                        ? as cycle
                    FROM read_csv(?,
                        delim='|',
                        header=false,
                        quote='',
                        escape='',
                        columns={
                            'cmte_id': 'VARCHAR',
                            'cmte_name': 'VARCHAR',
                            'tres_name': 'VARCHAR',
                            'street_1': 'VARCHAR',
                            'street_2': 'VARCHAR',
                            'city': 'VARCHAR',
                            'state': 'VARCHAR',
                            'zip': 'VARCHAR',
                            'cmte_dsg': 'VARCHAR',
                            'cmte_tp': 'VARCHAR',
                            'pty': 'VARCHAR',
                            'filing_freq': 'VARCHAR',
                            'org_tp': 'VARCHAR',
                            'conn_org': 'VARCHAR',
                            'cand_id': 'VARCHAR'
                        },
                        null_padding=true,
                        ignore_errors=true
                    );
                """, (cycle, tmp_path))

                row = conn.execute("SELECT count(*) FROM fec_committees WHERE cycle = ?", (cycle,)).fetchone()
                return row[0] if row else 0
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
        except Exception as e:
            logger.debug(f"Native DuckDB bulk ingestion failed, falling back to stream parsing: {e}")
            return None

    def sync_committees_only(self, cycles: Optional[List[int]] = None, force: bool = False) -> Dict[int, int]:
        """Rapid synchronization of Committee Master records only (~870 KB per cycle).

        Downloads and parses cm{yy}.zip for specified cycles without downloading
        multi-gigabyte transaction or expenditure archives.

        Args:
            cycles: List of 2-year election cycles (defaults to DEFAULT_FEC_CYCLES).
            force: Whether to re-download if cached archive exists.

        Returns:
            Dictionary mapping cycle year to number of committees ingested.
        """
        target_cycles = cycles or DEFAULT_FEC_CYCLES
        results = {}
        total_ingested = 0
        t_start = time.time()
        print("\n" + "=" * 76)
        print(" 🏛️  RAPID FEC COMMITTEE MASTER SYNCHRONIZATION")
        print("=" * 76)
        print(f"Target DuckDB: {self.storage.db_path}")
        print(f"Election Cycles: {', '.join(str(c) for c in target_cycles)}\n")

        for idx, cycle in enumerate(target_cycles, 1):
            yy = str(cycle)[-2:]
            cm_url = f"{FEC_BULK_BASE_URL}/{cycle}/cm{yy}.zip"
            cm_dest = os.path.join(self.download_dir, f"cm{yy}.zip")
            print(f"[{idx}/{len(target_cycles)}] Cycle {cycle} Committee Master:")
            try:
                self.download_file(cm_url, cm_dest, f"Committee Master {cycle}", force=force)
                t0 = time.time()

                # Fast path: vectorized DuckDB C++ scanner
                count = self._ingest_cm_native_duckdb(cm_dest, cycle)
                if count is None:
                    # Fallback to stream parsing
                    with zipfile.ZipFile(cm_dest, "r") as zf:
                        fname = zf.namelist()[0]
                        with zf.open(fname) as f_obj:
                            count = self.parse_cm_stream(f_obj, cycle)

                results[cycle] = count
                total_ingested += count
                elapsed = time.time() - t0
                print(f"    ✅ Ingested {count:,} political committees for cycle {cycle} in {elapsed:.2f}s")
            except Exception as e:
                print(f"    ⚠️  Could not ingest Committee Master for {cycle}: {e}")
                results[cycle] = 0

            self.storage.record_sync(
                f"FEC_CM_{cycle}",
                f"FEC Committee Master Cycle {cycle}",
                results.get(cycle, 0),
                f"Committees: {results.get(cycle, 0)}"
            )

        total_elapsed = time.time() - t_start
        print("\n" + "=" * 76)
        print(f" ✅ FEC Committee Master Sync Complete ({total_elapsed:.2f}s total)")
        print(f"    • Total Ingested / Updated: {total_ingested:,} committees across {len(target_cycles)} cycles")
        print("=" * 76 + "\n")
        return results

    def sync_all_cycles(self, cycles: Optional[List[int]] = None, include_expenditures: bool = True, force: bool = False) -> Dict[int, Dict[str, int]]:
        """Synchronize election cycles (defaults to 3 cycles: 2022, 2024, 2026)."""
        target_cycles = cycles or DEFAULT_FEC_CYCLES
        results = {}
        for c in target_cycles:
            results[c] = self.sync_cycle(c, include_expenditures=include_expenditures, force=force)
        return results


class FECClient:
    """HTTP client interface for querying the official Federal Election Commission (OpenFEC) API."""

    def __init__(self, storage: Optional[IRS990Storage] = None, api_key: Optional[str] = None, rate_limit_delay: float = 0.2) -> None:
        """Initialize OpenFEC client session and rate limiter.

        Args:
            storage: Optional DuckDB storage engine instance for caching query results.
            api_key: Optional OpenFEC API key. Defaults to FEC_API_KEY environment variable or DEMO_KEY.
            rate_limit_delay: Delay in seconds between API queries.
        """
        self.storage = storage
        self.api_key = api_key or os.environ.get("FEC_API_KEY", OPEN_FEC_DEMO_KEY)
        self.rate_limit_delay = rate_limit_delay
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "IRS-990-Explorer/2.0 (FEC Political Network Research; contact: researcher@example.org)",
            "Accept": "application/json"
        })

    def search_committees(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search Federal Election Commission political committees live via OpenFEC API.

        Args:
            query: Committee name, acronym, or FEC Committee ID (e.g. 'Defend US PAC', 'C00634261').
            limit: Maximum number of committee records to return.

        Returns:
            List of normalized committee summary dictionaries.
        """
        clean_q = query.strip()
        if not clean_q:
            return []

        url = f"{FEC_API_BASE_URL}/committees/"
        params: Dict[str, Any] = {
            "api_key": self.api_key,
            "q": clean_q,
            "per_page": min(limit, 20)
        }

        try:
            time.sleep(self.rate_limit_delay)
            # SECURITY: Enforce request timeout to avoid hung network connections
            resp = self.session.get(url, params=params, timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                raw_results = data.get("results", [])
                normalized = []
                cache_batch = []

                for r in raw_results:
                    cmte_id = r.get("committee_id") or ""
                    cmte_name = r.get("name") or ""
                    cmte_tp = r.get("committee_type") or ""
                    type_label = FEC_SHORT_TYPE_LABELS.get(cmte_tp, r.get("committee_type_full") or f"PAC ({cmte_tp})")
                    conn_org = r.get("affiliated_committee_name") or ""
                    if conn_org == "NONE":
                        conn_org = ""
                    tres_name = r.get("treasurer_name") or ""
                    state = r.get("state") or ""
                    party = r.get("party") or ""
                    cycles = r.get("cycles") or []
                    cycle = max(cycles) if cycles else 2026

                    item = {
                        "cmte_id": cmte_id,
                        "name": cmte_name,
                        "cmte_type": cmte_tp,
                        "type_label": type_label,
                        "connected_org": conn_org,
                        "treasurer": tres_name,
                        "state": state,
                        "party": party,
                        "cycle": cycle,
                        "type": "fec_committee"
                    }
                    normalized.append(item)

                    if self.storage and cmte_id and cmte_name:
                        clean_tres = normalize_person_name(tres_name)
                        clean_conn = normalize_person_name(conn_org)
                        city = r.get("city") or ""
                        zip_code = r.get("zip") or ""
                        cmte_dsg = r.get("designation") or ""
                        org_tp = r.get("organization_type") or ""
                        cache_batch.append((
                            cmte_id, cmte_name, tres_name, clean_tres, city, state, zip_code,
                            cmte_dsg, cmte_tp, party, org_tp, conn_org, clean_conn, "", cycle
                        ))

                if self.storage and cache_batch:
                    try:
                        self.storage.upsert_fec_committees(cache_batch)
                    except Exception as e:
                        logger.debug(f"Could not cache live FEC search results into DuckDB: {e}")

                return normalized[:limit]
            else:
                logger.warning(f"OpenFEC committee search returned status {resp.status_code}: {resp.text[:120]}")
        except Exception as e:
            logger.error(f"Error querying OpenFEC API for '{clean_q}': {e}")

        return []

    def get_committee_profile(self, cmte_id_or_name: str) -> Optional[Dict[str, Any]]:
        """Fetch detailed FEC committee profile live from OpenFEC API or local cache.

        Args:
            cmte_id_or_name: FEC Committee ID (e.g. 'C00634261') or committee name (e.g. 'Defend US PAC').

        Returns:
            Dictionary formatted to match storage.get_fec_committee() schema, or None if not found.
        """
        clean_input = cmte_id_or_name.strip()
        if not clean_input:
            return None

        # 1. Check local DB first if storage is present
        if self.storage:
            cached = self.storage.get_fec_committee(clean_input)
            if cached and cached.get("name"):
                return cached

        # 2. Check if clean_input is an FEC ID (C + 8 digits) or a name
        import re
        is_id = bool(re.match(r"^C\d{8}$", clean_input, re.IGNORECASE))
        target_id = clean_input.upper() if is_id else None

        if not target_id:
            # Query live OpenFEC search to resolve committee name into committee ID
            search_results = self.search_committees(clean_input, limit=5)
            if search_results:
                target_id = search_results[0].get("cmte_id")

        if not target_id:
            return None

        # Re-check local storage with resolved target_id
        if self.storage:
            cached = self.storage.get_fec_committee(target_id)
            if cached and cached.get("name"):
                return cached

        url = f"{FEC_API_BASE_URL}/committee/{target_id}/"
        params: Dict[str, Any] = {"api_key": self.api_key}

        try:
            time.sleep(self.rate_limit_delay)
            # SECURITY: Enforce request timeout to avoid hung network connections
            resp = self.session.get(url, params=params, timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                if not results:
                    return None
                r = results[0]
                cmte_name = r.get("name") or ""
                cmte_tp = r.get("committee_type") or ""
                type_label = FEC_TYPE_LABELS.get(cmte_tp, r.get("committee_type_full") or f"PAC ({cmte_tp})")
                tres_name = r.get("treasurer_name") or ""
                conn_org = r.get("affiliated_committee_name") or ""
                if conn_org == "NONE":
                    conn_org = ""
                city = r.get("city") or ""
                state = r.get("state") or ""
                zip_code = r.get("zip") or ""
                cmte_dsg = r.get("designation") or ""
                party = r.get("party") or ""
                org_tp = r.get("organization_type") or ""
                cycles = r.get("cycles") or []
                cycle = max(cycles) if cycles else 2026

                clean_tres = normalize_person_name(tres_name)
                clean_conn = normalize_person_name(conn_org)

                # Upsert into storage so local lookups succeed immediately
                if self.storage:
                    try:
                        self.storage.upsert_fec_committees([(
                            target_id, cmte_name, tres_name, clean_tres, city, state, zip_code,
                            cmte_dsg, cmte_tp, party, org_tp, conn_org, clean_conn, "", cycle
                        )])
                    except Exception as e:
                        logger.debug(f"Could not cache live committee {target_id} into DuckDB: {e}")

                profile = {
                    "cmte_id": target_id,
                    "name": cmte_name,
                    "cmte_name": cmte_name,
                    "treasurer": tres_name,
                    "treasurer_name": tres_name,
                    "clean_treasurer": clean_tres,
                    "city": city,
                    "state": state,
                    "zip": zip_code,
                    "cmte_designation": cmte_dsg,
                    "cmte_type": cmte_tp,
                    "type_label": type_label,
                    "party": party,
                    "org_type": org_tp,
                    "connected_org": conn_org,
                    "candidate_id": "",
                    "cycle": cycle,
                    "candidates": [],
                    "expenditures_summary": {
                        "supporting": [],
                        "opposing": [],
                        "contributions": []
                    },
                    "top_vendors": []
                }
                return profile
            else:
                logger.warning(f"OpenFEC committee lookup for {target_id} returned status {resp.status_code}")
        except Exception as e:
            logger.error(f"Error fetching committee {target_id} from OpenFEC: {e}")

        return None
