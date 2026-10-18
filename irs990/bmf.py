# SPDX-FileCopyrightText: 2026 990-Explorer Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""IRS Business Master File (EO BMF) Ingestion & Query Engine.

Architectural Purpose:
    Handles streaming ingestion, schema migration, and fast indexing of ~1.85M+
    official IRS exempt organizations from IRS Statistics of Income (SOI) bulk CSV extracts.

Security Invariants:
    - Streams chunked HTTP downloads to prevent memory exhaustion (DoS).
    - Uses local file staging under local workspace paths without path traversal (CWE-22).
"""

import os
import sys
import logging
import urllib.request
import time
from typing import Optional, Dict, Any, List
from datetime import datetime

from .storage import IRS990Storage, DEFAULT_DB_PATH
from .models import OrganizationNode
from .parser import clean_ein

logger = logging.getLogger(__name__)

BMF_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "bmf")

BMF_URLS = [
    ("eo1", "https://www.irs.gov/pub/irs-soi/eo1.csv", "Region 1 (Northeast)"),
    ("eo2", "https://www.irs.gov/pub/irs-soi/eo2.csv", "Region 2 (Mid-Atlantic / Great Lakes)"),
    ("eo3", "https://www.irs.gov/pub/irs-soi/eo3.csv", "Region 3 (Gulf Coast / Mid-Continent)"),
    ("eo4", "https://www.irs.gov/pub/irs-soi/eo4.csv", "Region 4 (Pacific Rim / Western)"),
]

BMF_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS irs_bmf (
    ein VARCHAR PRIMARY KEY,
    name VARCHAR,
    ico VARCHAR,
    street VARCHAR,
    city VARCHAR,
    state VARCHAR,
    zip VARCHAR,
    group_num VARCHAR,
    subsection VARCHAR,
    affiliation VARCHAR,
    classification VARCHAR,
    ruling VARCHAR,
    deductibility VARCHAR,
    foundation VARCHAR,
    activity VARCHAR,
    organization VARCHAR,
    status VARCHAR,
    tax_period VARCHAR,
    asset_cd VARCHAR,
    income_cd VARCHAR,
    filing_req_cd VARCHAR,
    pf_filing_req_cd VARCHAR,
    acct_pd VARCHAR,
    asset_amt DOUBLE DEFAULT 0.0,
    income_amt DOUBLE DEFAULT 0.0,
    revenue_amt DOUBLE DEFAULT 0.0,
    ntee_code VARCHAR,
    sort_name VARCHAR
);

CREATE INDEX IF NOT EXISTS idx_bmf_name ON irs_bmf(name);
CREATE INDEX IF NOT EXISTS idx_bmf_state ON irs_bmf(state);
CREATE INDEX IF NOT EXISTS idx_bmf_sub ON irs_bmf(subsection);
CREATE INDEX IF NOT EXISTS idx_bmf_fnd ON irs_bmf(foundation);
"""


class BMFIngester:
    def __init__(self, storage: IRS990Storage, download_dir: str = BMF_DATA_DIR):
        self.storage = storage
        self.download_dir = download_dir
        os.makedirs(self.download_dir, exist_ok=True)
        self._init_table()

    def _init_table(self):
        """Ensure irs_bmf table exists in storage DuckDB."""
        self.storage.conn.execute(BMF_SCHEMA_SQL)

    def download_file(self, url: str, dest_path: str, label: str, force: bool = False) -> str:
        """Download a file with streaming progress display."""
        if os.path.exists(dest_path) and not force:
            file_size_mb = os.path.getsize(dest_path) / (1024 * 1024)
            print(f"  [Cached] {label}: {os.path.basename(dest_path)} ({file_size_mb:.1f} MB already downloaded)")
            return dest_path

        print(f"  [Downloading] {label} from {url}...")
        req = urllib.request.Request(url, headers={"User-Agent": "IRS-990-Explorer/2.0"})
        start_time = time.time()

        with urllib.request.urlopen(req) as resp, open(dest_path, "wb") as out_f:
            total_size = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 64 * 1024

            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                out_f.write(chunk)
                downloaded += len(chunk)
                if total_size > 0:
                    pct = (downloaded / total_size) * 100
                    mb = downloaded / (1024 * 1024)
                    sys.stdout.write(f"\r    -> {mb:.1f} MB / {total_size/(1024*1024):.1f} MB ({pct:.1f}%)")
                    sys.stdout.flush()
                else:
                    mb = downloaded / (1024 * 1024)
                    sys.stdout.write(f"\r    -> {mb:.1f} MB downloaded")
                    sys.stdout.flush()

        duration = time.time() - start_time
        print(f"\n    Completed in {duration:.1f}s ({os.path.getsize(dest_path)/(1024*1024):.1f} MB)")
        return dest_path

    def sync(self, force_download: bool = False, max_files: Optional[int] = None) -> Dict[str, Any]:
        """
        Download and ingest all BMF regional CSV files directly into DuckDB.
        Performs pre-flight freshness check against official IRS servers to skip
        redundant downloading and re-indexing when local data is already up to date.
        """
        # Pre-flight Freshness & Status Check
        if not force_download:
            from .freshness import DataFreshnessChecker
            checker = DataFreshnessChecker(self.storage)
            freshness = checker.check_bmf_freshness()
            status = freshness.get("status")

            if status == "UP_TO_DATE":
                print("\n" + "=" * 70)
                print(" 🏛️  IRS Exempt Organizations Business Master File (EO BMF)")
                print("=" * 70)
                print(f"  ✅ [UP TO DATE] {freshness['message']}")
                print(f"     Target Database: {self.storage.db_path}")
                local_dt = freshness.get("local_date")
                if local_dt:
                    print(f"     Last Synced:     {local_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
                print("     Action:          Skipping download and database re-indexing.")
                print("     Tip:             Pass --force-download to force re-download & re-index.\n")

                row = self.storage.conn.execute("SELECT count(*) FROM irs_bmf;").fetchone()
                total_records = row[0] if row else 0
                return {
                    "total_records": total_records,
                    "status": "skipped",
                    "reason": "up_to_date",
                    "details": freshness.get("message")
                }
            elif status == "OUT_OF_DATE":
                print("\n" + "=" * 70)
                print(" 🏛️  IRS Exempt Organizations Business Master File (EO BMF)")
                print("=" * 70)
                print(f"  ⚠️  [OUT OF DATE] {freshness['message']}")
                print(f"     Newer monthly extract published on IRS servers.")
                print("     Downloading latest release and synchronizing DuckDB...\n")
                force_download = True

        print("\n" + "=" * 70)
        print(" IRS Exempt Organizations Business Master File (EO BMF) Ingestion")
        print("=" * 70)
        print(f"Target DuckDB: {self.storage.db_path}")
        print(f"Download Directory: {self.download_dir}\n")

        files_to_sync = BMF_URLS[:max_files] if max_files else BMF_URLS
        downloaded_paths = []

        # 1. Download files
        for code, url, region in files_to_sync:
            dest = os.path.join(self.download_dir, f"{code}.csv")
            try:
                self.download_file(url, dest, f"{code}.csv - {region}", force=force_download)
                downloaded_paths.append(dest)
            except Exception as e:
                logger.error(f"Failed to download {url}: {e}")
                print(f"  [ERROR] Failed to download {code}.csv: {e}")

        if not downloaded_paths:
            print("No BMF CSV files available to ingest.")
            return {"total_records": 0, "status": "failed"}

        # 2. Ingest into DuckDB
        print("\nIngesting CSV files into DuckDB table 'irs_bmf'...")
        start_ingest = time.time()
        total_ingested = 0

        for path in downloaded_paths:
            base = os.path.basename(path)
            print(f"  Loading {base} into DuckDB...")
            # Use DuckDB native read_csv to parse and upsert/insert
            try:
                self.storage.conn.execute(f"""
                    INSERT OR REPLACE INTO irs_bmf
                    SELECT
                        lpad(trim(EIN::VARCHAR), 9, '0') as ein,
                        trim(NAME::VARCHAR) as name,
                        coalesce(trim(ICO::VARCHAR), '') as ico,
                        coalesce(trim(STREET::VARCHAR), '') as street,
                        coalesce(trim(CITY::VARCHAR), '') as city,
                        coalesce(trim(STATE::VARCHAR), '') as state,
                        coalesce(trim(ZIP::VARCHAR), '') as zip,
                        coalesce(trim("GROUP"::VARCHAR), '') as group_num,
                        coalesce(trim(SUBSECTION::VARCHAR), '') as subsection,
                        coalesce(trim(AFFILIATION::VARCHAR), '') as affiliation,
                        coalesce(trim(CLASSIFICATION::VARCHAR), '') as classification,
                        coalesce(trim(RULING::VARCHAR), '') as ruling,
                        coalesce(trim(DEDUCTIBILITY::VARCHAR), '') as deductibility,
                        coalesce(trim(FOUNDATION::VARCHAR), '') as foundation,
                        coalesce(trim(ACTIVITY::VARCHAR), '') as activity,
                        coalesce(trim(ORGANIZATION::VARCHAR), '') as organization,
                        coalesce(trim(STATUS::VARCHAR), '') as status,
                        coalesce(trim(TAX_PERIOD::VARCHAR), '') as tax_period,
                        coalesce(trim(ASSET_CD::VARCHAR), '') as asset_cd,
                        coalesce(trim(INCOME_CD::VARCHAR), '') as income_cd,
                        coalesce(trim(FILING_REQ_CD::VARCHAR), '') as filing_req_cd,
                        coalesce(trim(PF_FILING_REQ_CD::VARCHAR), '') as pf_filing_req_cd,
                        coalesce(trim(ACCT_PD::VARCHAR), '') as acct_pd,
                        coalesce(try_cast(ASSET_AMT as DOUBLE), 0.0) as asset_amt,
                        coalesce(try_cast(INCOME_AMT as DOUBLE), 0.0) as income_amt,
                        coalesce(try_cast(REVENUE_AMT as DOUBLE), 0.0) as revenue_amt,
                        coalesce(trim(NTEE_CD::VARCHAR), '') as ntee_code,
                        coalesce(trim(SORT_NAME::VARCHAR), '') as sort_name
                    FROM read_csv('{path}', all_varchar=true, header=true, ignore_errors=true);
                """)
                count_res = self.storage.conn.execute("SELECT count(*) FROM irs_bmf;").fetchone()
                total_ingested = count_res[0] if count_res else 0
                print(f"    -> Done. Current total BMF records in DuckDB: {total_ingested:,}")
            except Exception as e:
                logger.error(f"Error loading {path} into DuckDB: {e}")
                print(f"    [ERROR] Failed to load {path}: {e}")

        duration = time.time() - start_ingest

        # 3. Record sync metadata
        self.storage.record_sync(
            source_id="IRS_BMF",
            source_name="IRS Business Master File (EO BMF)",
            count=total_ingested,
            details=f"Official IRS Exempt Organization Master File ({len(downloaded_paths)} regional extracts)"
        )

        print("\n" + "-" * 70)
        print(f" Ingestion Complete! Total Records: {total_ingested:,} in {duration:.1f}s")
        print("-" * 70 + "\n")

        return {
            "total_records": total_ingested,
            "duration_sec": duration,
            "status": "success"
        }

    def get_organization_by_ein(self, ein: str) -> Optional[OrganizationNode]:
        """Lookup an organization in the BMF table by EIN."""
        raw_ein = clean_ein(ein)
        row = self.storage.conn.execute("""
            SELECT ein, name, subsection, foundation, revenue_amt, asset_amt,
                   city, state, street, zip, ntee_code
            FROM irs_bmf
            WHERE ein = ?;
        """, (raw_ein,)).fetchone()

        if not row:
            return None

        # Determine tax status label
        sub = row[2]
        fnd = row[3]
        if sub == "03":
            if fnd in ("02", "03", "04"):
                tax_status = "501(c)(3) Private Foundation"
            else:
                tax_status = "501(c)(3) Public Charity"
        elif sub:
            tax_status = f"501(c)({int(sub) if sub.isdigit() else sub})"
        else:
            tax_status = "Tax-Exempt Organization"

        formatted_ein = f"{row[0][:2]}-{row[0][2:]}" if len(row[0]) == 9 else row[0]
        return OrganizationNode(
            ein=formatted_ein,
            name=row[1],
            tax_status=tax_status,
            total_revenue=row[4] or 0.0,
            total_assets=row[5] or 0.0,
            city=row[6] or "",
            state=row[7] or "",
            address=row[8] or "",
            zipcode=row[9] or "",
            ntee_code=row[10] or ""
        )

    def search_bmf(self, query: str, limit: int = 10) -> List[OrganizationNode]:
        """Search the 1.85M BMF charities by Name or EIN."""
        raw_ein = clean_ein(query)
        pattern = f"%{query}%"

        rows = self.storage.conn.execute("""
            SELECT ein, name, subsection, foundation, revenue_amt, asset_amt,
                   city, state, street, zip, ntee_code
            FROM irs_bmf
            WHERE name ILIKE ? OR ein LIKE ?
            ORDER BY revenue_amt DESC
            LIMIT ?;
        """, (pattern, f"%{raw_ein}%", limit)).fetchall()

        results = []
        for row in rows:
            sub = row[2]
            fnd = row[3]
            if sub == "03":
                tax_status = "501(c)(3) Private Foundation" if fnd in ("02", "03", "04") else "501(c)(3) Public Charity"
            elif sub:
                tax_status = f"501(c)({int(sub) if sub.isdigit() else sub})"
            else:
                tax_status = "Tax-Exempt Organization"

            formatted_ein = f"{row[0][:2]}-{row[0][2:]}" if len(row[0]) == 9 else row[0]
            results.append(OrganizationNode(
                ein=formatted_ein,
                name=row[1],
                tax_status=tax_status,
                total_revenue=row[4] or 0.0,
                total_assets=row[5] or 0.0,
                city=row[6] or "",
                state=row[7] or "",
                address=row[8] or "",
                zipcode=row[9] or "",
                ntee_code=row[10] or ""
            ))
        return results
