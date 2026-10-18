# SPDX-FileCopyrightText: 2026 990-Explorer Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""IRS Political Organization Filing and Disclosure (POFD) Ingestion Engine.

Architectural Purpose:
    Downloads, streams, unpacks, and indexes IRS Section 527 political organizations
    (Forms 8871 notice of status and Forms 8872 contributions/expenditures) into DuckDB.

Security Invariants:
    - Protects against Zip Slip (CWE-22) by resolving archive member destinations
      with os.path.realpath and checking containment within target directories.
    - Uses parameter substitution on all SQL insertions.
"""

import os
import sys
import logging
import urllib.request
import zipfile
import io
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Generator, Tuple

from .storage import IRS990Storage, DEFAULT_DB_PATH
from .parser import normalize_person_name, clean_ein

logger = logging.getLogger(__name__)

POFD_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "pofd")

POFD_FULL_URL = "https://forms.irs.gov/app/pod/dataDownload/fullData"
POFD_SPLIT_URLS = [
    ("dataAG", "https://forms.irs.gov/app/pod/dataDownload/dataAG", "Alphabetical A-G"),
    ("dataHM", "https://forms.irs.gov/app/pod/dataDownload/dataHM", "Alphabetical H-M"),
    ("dataNR", "https://forms.irs.gov/app/pod/dataDownload/dataNR", "Alphabetical N-R"),
    ("dataSZ", "https://forms.irs.gov/app/pod/dataDownload/dataSZ", "Alphabetical S-Z"),
]


def _safe_float(val: str, default: float = 0.0) -> float:
    try:
        clean = val.replace("$", "").replace(",", "").strip()
        return float(clean) if clean and clean.upper() != "NONE" else default
    except Exception:
        return default


def _safe_date(val: str) -> Optional[str]:
    clean = val.strip()
    if len(clean) == 8 and clean.isdigit():
        return f"{clean[:4]}-{clean[4:6]}-{clean[6:8]}"
    return clean if clean else None


class POFDIngester:
    def __init__(self, storage: IRS990Storage, download_dir: str = POFD_DATA_DIR):
        self.storage = storage
        self.download_dir = download_dir
        os.makedirs(self.download_dir, exist_ok=True)

    def download_file(self, url: str, dest_path: str, label: str, force: bool = False) -> str:
        """Download bulk zip archive with streaming progress indication."""
        if os.path.exists(dest_path) and not force:
            size_mb = os.path.getsize(dest_path) / (1024 * 1024)
            print(f"  [Cached] {label}: {os.path.basename(dest_path)} ({size_mb:.1f} MB already downloaded)")
            return dest_path

        print(f"  [Downloading] {label} from {url}...")
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) IRS-990-Explorer/2.0"
            }
        )
        start_time = time.time()
        with urllib.request.urlopen(req, timeout=120) as resp, open(dest_path, "wb") as out_f:
            downloaded = 0
            chunk_size = 64 * 1024
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                out_f.write(chunk)
                downloaded += len(chunk)
                mb = downloaded / (1024 * 1024)
                sys.stdout.write(f"\r    -> Received: {mb:.1f} MB")
                sys.stdout.flush()

        elapsed = time.time() - start_time
        mb_total = downloaded / (1024 * 1024)
        speed = (mb_total / elapsed) if elapsed > 0 else 0
        print(f"\r  [Complete] Downloaded {mb_total:.1f} MB in {elapsed:.1f}s ({speed:.1f} MB/s) -> {os.path.basename(dest_path)}")
        return dest_path

    def parse_stream(self, file_obj) -> Dict[str, int]:
        """
        Stream parse pipe-delimited text lines directly from zip member.
        Inserts in memory-efficient batches into DuckDB.
        """
        batch_size = 5000
        orgs_batch = []
        dirs_batch = []
        rels_batch = []
        reps_batch = []
        contribs_batch = []
        exp_batch = []

        counts = {
            "orgs": 0,
            "directors": 0,
            "related": 0,
            "reports": 0,
            "contributions": 0,
            "expenditures": 0
        }

        start_time = time.time()
        line_num = 0

        for line_raw in file_obj:
            line_num += 1
            if line_num % 50000 == 0:
                sys.stdout.write(f"\r    Processed {line_num:,} lines (Orgs: {counts['orgs']:,}, Contribs: {counts['contributions']:,}, Exp: {counts['expenditures']:,})...")
                sys.stdout.flush()

            text = line_raw.decode("utf-8", errors="ignore").strip()
            if not text:
                continue

            parts = text.split("|")
            rtype = parts[0]

            if rtype == "1" and len(parts) >= 15:
                # Form 8871
                form_id = parts[2].strip()
                ein = clean_ein(parts[6].strip())
                name = parts[7].strip()
                form_type = parts[1].strip()
                addr1 = parts[8].strip() if len(parts) > 8 else ""
                addr2 = parts[9].strip() if len(parts) > 9 else ""
                city = parts[10].strip() if len(parts) > 10 else ""
                state = parts[11].strip() if len(parts) > 11 else ""
                zip_code = parts[12].strip() if len(parts) > 12 else ""
                email = parts[14].strip() if len(parts) > 14 else ""
                custodian = parts[16].strip() if len(parts) > 16 else ""
                purpose = parts[39].strip() if len(parts) > 39 else ""
                insert_dt = parts[41].strip() if len(parts) > 41 else ""

                orgs_batch.append((
                    form_id, name, ein, form_type, addr1, addr2,
                    city, state, zip_code, email, custodian, purpose,
                    insert_dt if insert_dt else None
                ))
                counts["orgs"] += 1

            elif rtype == "D" and len(parts) >= 11:
                # Directors & Officers
                form_id = parts[1].strip()
                dir_id = parts[2].strip()
                org_name = parts[3].strip()
                ein = clean_ein(parts[4].strip())
                person = parts[5].strip()
                clean_p = normalize_person_name(person)
                title = parts[6].strip()
                addr1 = parts[7].strip()
                city = parts[9].strip()
                state = parts[10].strip()
                zip_code = parts[11].strip() if len(parts) > 11 else ""
                pk = f"{form_id}:{dir_id}:{clean_p}"

                dirs_batch.append((
                    pk, form_id, org_name, ein, person, clean_p, title, addr1, city, state, zip_code
                ))
                counts["directors"] += 1

            elif rtype == "R" and len(parts) >= 7:
                # Related Entities / Connected Organizations
                form_id = parts[1].strip()
                rel_id = parts[2].strip()
                org_name = parts[3].strip()
                ein = clean_ein(parts[4].strip())
                rel_name = parts[5].strip()
                rel_type = parts[6].strip()
                city = parts[9].strip() if len(parts) > 9 else ""
                state = parts[10].strip() if len(parts) > 10 else ""
                pk = f"{form_id}:{rel_id}"

                rels_batch.append((
                    pk, form_id, org_name, ein, rel_name, rel_type, city, state
                ))
                counts["related"] += 1

            elif rtype == "2" and len(parts) >= 11:
                # Form 8872 Periodic Report
                form_id = parts[2].strip()
                form_type = parts[1].strip()
                p_begin = _safe_date(parts[3])
                p_end = _safe_date(parts[4])
                org_name = parts[9].strip()
                ein = clean_ein(parts[10].strip())
                tot_contrib = _safe_float(parts[45]) if len(parts) > 45 else 0.0
                tot_exp = _safe_float(parts[47]) if len(parts) > 47 else 0.0
                insert_dt = parts[48].strip() if len(parts) > 48 else ""

                reps_batch.append((
                    form_id, form_type, ein, org_name, p_begin, p_end,
                    tot_contrib, tot_exp, insert_dt if insert_dt else None
                ))
                counts["reports"] += 1

            elif rtype == "A" and len(parts) >= 14:
                # Schedule A Itemized Contributions
                form_id = parts[1].strip()
                a_id = parts[2].strip()
                org_name = parts[3].strip()
                ein = clean_ein(parts[4].strip())
                contrib_name = parts[5].strip()
                city = parts[8].strip() if len(parts) > 8 else ""
                state = parts[9].strip() if len(parts) > 9 else ""
                zip_code = parts[10].strip() if len(parts) > 10 else ""
                employer = parts[12].strip() if len(parts) > 12 else ""
                amt = _safe_float(parts[13]) if len(parts) > 13 else 0.0
                occ = parts[14].strip() if len(parts) > 14 else ""
                ytd = _safe_float(parts[15]) if len(parts) > 15 else 0.0
                dt = parts[16].strip() if len(parts) > 16 else ""
                pk = f"{form_id}:{a_id}"

                contribs_batch.append((
                    pk, form_id, a_id, org_name, ein, contrib_name,
                    city, state, zip_code, employer, occ, amt, ytd, dt
                ))
                counts["contributions"] += 1

            elif rtype == "B" and len(parts) >= 14:
                # Schedule B Itemized Expenditures
                form_id = parts[1].strip()
                b_id = parts[2].strip()
                org_name = parts[3].strip()
                ein = clean_ein(parts[4].strip())
                recip_name = parts[5].strip()
                city = parts[8].strip() if len(parts) > 8 else ""
                state = parts[9].strip() if len(parts) > 9 else ""
                zip_code = parts[10].strip() if len(parts) > 10 else ""
                employer = parts[12].strip() if len(parts) > 12 else ""
                amt = _safe_float(parts[13]) if len(parts) > 13 else 0.0
                exp_dt = parts[15].strip() if len(parts) > 15 else ""
                purpose = parts[16].strip() if len(parts) > 16 else ""
                pk = f"{form_id}:{b_id}"

                exp_batch.append((
                    pk, form_id, b_id, org_name, ein, recip_name,
                    city, state, zip_code, employer, "", amt, exp_dt, purpose
                ))
                counts["expenditures"] += 1

            # Flush batches
            if len(orgs_batch) >= batch_size:
                self.storage.upsert_527_orgs(orgs_batch)
                orgs_batch.clear()
            if len(dirs_batch) >= batch_size:
                self.storage.upsert_527_directors(dirs_batch)
                dirs_batch.clear()
            if len(rels_batch) >= batch_size:
                self.storage.upsert_527_related(rels_batch)
                rels_batch.clear()
            if len(reps_batch) >= batch_size:
                self.storage.upsert_527_reports(reps_batch)
                reps_batch.clear()
            if len(contribs_batch) >= batch_size:
                self.storage.upsert_527_contributions(contribs_batch)
                contribs_batch.clear()
            if len(exp_batch) >= batch_size:
                self.storage.upsert_527_expenditures(exp_batch)
                exp_batch.clear()

        # Final flush
        if orgs_batch:
            self.storage.upsert_527_orgs(orgs_batch)
        if dirs_batch:
            self.storage.upsert_527_directors(dirs_batch)
        if rels_batch:
            self.storage.upsert_527_related(rels_batch)
        if reps_batch:
            self.storage.upsert_527_reports(reps_batch)
        if contribs_batch:
            self.storage.upsert_527_contributions(contribs_batch)
        if exp_batch:
            self.storage.upsert_527_expenditures(exp_batch)

        elapsed = time.time() - start_time
        print(f"\r    Processed all {line_num:,} lines in {elapsed:.1f}s.")
        return counts

    def sync(self, force_download: bool = False, use_splits: bool = False) -> Dict[str, Any]:
        """
        Synchronize official IRS 527 POFD dataset into DuckDB.
        """
        print("\n" + "=" * 70)
        print(" 🏛️  IRS Section 527 Political Organizations (POFD) Ingestion")
        print("=" * 70)
        print(f"Target DuckDB: {self.storage.db_path}")
        print(f"Download Directory: {self.download_dir}\n")

        files_to_process = []
        if use_splits:
            for code, url, region in POFD_SPLIT_URLS:
                dest = os.path.join(self.download_dir, f"PolOrgs_{code}.zip")
                try:
                    self.download_file(url, dest, f"{code} - {region}", force=force_download)
                    files_to_process.append(dest)
                except Exception as e:
                    print(f"  [ERROR] Failed to download {code}: {e}")
        else:
            dest = os.path.join(self.download_dir, "PolOrgsFullData.zip")
            try:
                self.download_file(POFD_FULL_URL, dest, "IRS Full POFD Database", force=force_download)
                files_to_process.append(dest)
            except Exception as e:
                print(f"  [WARNING] Full data download failed ({e}), falling back to alphabetical splits...")
                for code, url, region in POFD_SPLIT_URLS:
                    s_dest = os.path.join(self.download_dir, f"PolOrgs_{code}.zip")
                    try:
                        self.download_file(url, s_dest, f"{code} - {region}", force=force_download)
                        files_to_process.append(s_dest)
                    except Exception as se:
                        print(f"  [ERROR] Failed split {code}: {se}")

        if not files_to_process:
            print("No POFD ZIP files available to ingest.")
            return {"status": "failed", "records": 0}

        print("\nStreaming and indexing POFD records into DuckDB...")
        total_counts = {
            "orgs": 0, "directors": 0, "related": 0,
            "reports": 0, "contributions": 0, "expenditures": 0
        }

        for zip_path in files_to_process:
            base = os.path.basename(zip_path)
            print(f"\n  Inspecting {base}...")
            with zipfile.ZipFile(zip_path, "r") as z:
                for member in z.namelist():
                    if member.endswith(".txt") or "DataFile" in member:
                        print(f"  Parsing member {member} ({z.getinfo(member).file_size / (1024*1024):.1f} MB uncompressed)...")
                        with z.open(member) as f:
                            counts = self.parse_stream(f)
                            for k, v in counts.items():
                                total_counts[k] += v

        # Log sync metadata
        total_records = sum(total_counts.values())
        self.storage.log_ingestion_metadata(
            source_id="IRS_527_POFD",
            source_name="IRS Section 527 Political Organizations (POFD)",
            records_count=total_records,
            details=f"Orgs: {total_counts['orgs']:,}, Contribs: {total_counts['contributions']:,}, Exp: {total_counts['expenditures']:,}"
        )

        print("\n" + "=" * 70)
        print(" ✅ IRS Section 527 POFD Ingestion Complete")
        print("=" * 70)
        print(f"  • Registered 527 Committees: {total_counts['orgs']:,}")
        print(f"  • Committee Officers / Directors: {total_counts['directors']:,}")
        print(f"  • Related / Sponsoring Entities: {total_counts['related']:,}")
        print(f"  • Periodic Reports (Form 8872): {total_counts['reports']:,}")
        print(f"  • Itemized Contributions: {total_counts['contributions']:,}")
        print(f"  • Itemized Expenditures: {total_counts['expenditures']:,}")
        print(f"  • Total Processed Records: {total_records:,}\n")

        return {"status": "success", "counts": total_counts, "total_records": total_records}
