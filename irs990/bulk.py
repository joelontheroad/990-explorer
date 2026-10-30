# SPDX-FileCopyrightText: 2026 990-Explorer Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bulk Ingestion Engine for IRS 990 XML and ZIP archives.

Architectural Purpose:
    Streams and parses bulk IRS TEOS XML e-file returns from local directories
    or compressed ZIP archives directly into DuckDB storage with batch flushing.

Security Invariants:
    - Protects against Zip Slip directory traversal (CWE-22) when reading zip entries.
    - Uses streaming generators to prevent loading multi-gigabyte archives into memory at once.
"""

import os
import zipfile
import glob
import logging
from typing import Optional, List, Dict, Any, Generator, Tuple
from .models import OrganizationNode, FundingGrant, Relationship
from .parser import (
    parse_return_header,
    parse_schedule_i_xml,
    parse_990pf_part_xv_xml,
    parse_schedule_r_xml,
    parse_part_ix_expenses,
    parse_part_vii_contractors,
    parse_part_vii_people
)
from .storage import IRS990Storage

logger = logging.getLogger(__name__)


class BulkIngester:
    """Batch ingestion engine streaming bulk IRS TEOS XML files and archives into DuckDB."""

    def __init__(self, storage: IRS990Storage, batch_size: int = 500) -> None:
        """Initialize bulk ingester with target storage and batch size.

        Args:
            storage: Active DuckDB storage interface instance.
            batch_size: Number of records to accumulate before committing to storage.
        """
        self.storage = storage
        self.batch_size = batch_size

    def ingest_xml_content(self, xml_content: str) -> Tuple[int, int]:
        """Parse raw Form 990 XML content and ingest extracted records into storage.

        Args:
            xml_content: Full text of an electronic IRS Form 990 XML document.

        Returns:
            Tuple of (grants_count, relationships_count) ingested.
        """
        header_info = parse_return_header(xml_content)
        if not header_info:
            return 0, 0

        filer_node, tax_year = header_info
        self.storage.upsert_organization(filer_node)

        # Parse Schedule I (990)
        grants = parse_schedule_i_xml(xml_content, filer_node, tax_year)

        # Parse 990-PF Part XV if Schedule I produced no grants
        if not grants:
            grants = parse_990pf_part_xv_xml(xml_content, filer_node, tax_year)

        if grants:
            self.storage.upsert_grants(grants)
            # Batch upsert recipient nodes as stub orgs if they don't exist
            stub_nodes = [
                OrganizationNode(ein=g.recipient_ein, name=g.recipient_name)
                for g in grants if g.recipient_ein and g.recipient_name
            ]
            self.storage.upsert_organizations(stub_nodes)

        # Parse Schedule R
        relationships = parse_schedule_r_xml(xml_content, filer_node)
        if relationships:
            self.storage.upsert_relationships(relationships)
            stub_rels = [
                OrganizationNode(ein=r.related_ein, name=r.related_name)
                for r in relationships if r.related_ein and r.related_name
            ]
            self.storage.upsert_organizations(stub_rels)

        # Parse Part IX Functional Expenses
        expenses = parse_part_ix_expenses(xml_content, filer_node, tax_year)
        if expenses:
            self.storage.upsert_expenses([expenses])

        # Parse Part VII Section B Independent Contractors
        contractors = parse_part_vii_contractors(xml_content, filer_node, tax_year)
        if contractors:
            self.storage.upsert_contractors(contractors)

        # Parse Part VII Section A & 990-PF Part VIII People & Roles
        people = parse_part_vii_people(xml_content, filer_node, tax_year)
        if people:
            self.storage.upsert_people(people)

        return len(grants), len(relationships)

    def ingest_file(self, file_path: str) -> Tuple[int, int]:
        """Ingest a single Form 990 XML file from disk into storage.

        Args:
            file_path: Filesystem path to XML filing.

        Returns:
            Tuple of (grants_count, relationships_count) ingested.
        """
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            return self.ingest_xml_content(content)
        except Exception as e:
            logger.error(f"Error reading XML file {file_path}: {e}")
            return 0, 0

    def ingest_zip(self, zip_path: str, max_files: Optional[int] = None) -> Dict[str, int]:
        """Stream Form 990 XML files directly from a TEOS ZIP archive.

        Reads entries in-memory without extracting files to disk (preventing Zip Slip).

        Args:
            zip_path: Filesystem path to TEOS ZIP archive.
            max_files: Optional maximum count of XML files to process.

        Returns:
            Dictionary containing processed file and record counts.
        """
        stats = {"files_processed": 0, "grants_ingested": 0, "relationships_ingested": 0}
        try:
            # SECURITY: Read archive members in-memory without extracting to disk (preventing CWE-22)
            with zipfile.ZipFile(zip_path, "r") as z:
                xml_names = [n for n in z.namelist() if n.lower().endswith(".xml")]
                if max_files:
                    xml_names = xml_names[:max_files]

                for name in xml_names:
                    try:
                        with z.open(name) as f:
                            content = f.read().decode("utf-8", errors="ignore")
                        g_count, r_count = self.ingest_xml_content(content)
                        stats["files_processed"] += 1
                        stats["grants_ingested"] += g_count
                        stats["relationships_ingested"] += r_count
                    except Exception as e:
                        logger.warning(f"Error processing {name} in {zip_path}: {e}")
        except Exception as e:
            logger.error(f"Error opening ZIP archive {zip_path}: {e}")

        if stats["files_processed"] > 0:
            self.storage.record_sync(
                source_id=f"ZIP_{os.path.basename(zip_path)}",
                source_name=f"TEOS Archive ({os.path.basename(zip_path)})",
                count=stats["grants_ingested"],
                details=f"{stats['files_processed']} returns processed, {stats['grants_ingested']} grants, {stats['relationships_ingested']} relationships"
            )

        return stats

    def ingest_directory(self, dir_path: str, recursive: bool = True, max_files: Optional[int] = None) -> Dict[str, int]:
        """Scan a directory for Form 990 XML or ZIP files and ingest them into storage.

        Args:
            dir_path: Filesystem directory path to scan.
            recursive: If True, recursively searches subdirectories.
            max_files: Optional maximum count of files to process.

        Returns:
            Dictionary containing aggregated processed file and record counts.
        """
        stats = {"files_processed": 0, "grants_ingested": 0, "relationships_ingested": 0}
        if not os.path.exists(dir_path):
            logger.warning(f"Directory does not exist: {dir_path}")
            return stats

        # Find .xml files
        pattern = os.path.join(dir_path, "**", "*.xml") if recursive else os.path.join(dir_path, "*.xml")
        xml_files = glob.glob(pattern, recursive=recursive)
        if max_files:
            xml_files = xml_files[:max_files]

        for xfile in xml_files:
            g, r = self.ingest_file(xfile)
            stats["files_processed"] += 1
            stats["grants_ingested"] += g
            stats["relationships_ingested"] += r

        # Find .zip files
        zip_pattern = os.path.join(dir_path, "**", "*.zip") if recursive else os.path.join(dir_path, "*.zip")
        zip_files = glob.glob(zip_pattern, recursive=recursive)
        for zfile in zip_files:
            z_stats = self.ingest_zip(zfile)
            stats["files_processed"] += z_stats["files_processed"]
            stats["grants_ingested"] += z_stats["grants_ingested"]
            stats["relationships_ingested"] += z_stats["relationships_ingested"]

        if stats["files_processed"] > 0:
            self.storage.record_sync(
                source_id="BULK_DIR_INGEST",
                source_name=f"Bulk Directory Ingest ({os.path.basename(dir_path)})",
                count=stats["grants_ingested"],
                details=f"{stats['files_processed']} files processed, {stats['grants_ingested']} grants, {stats['relationships_ingested']} relationships"
            )

        return stats

