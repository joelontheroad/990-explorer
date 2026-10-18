# SPDX-FileCopyrightText: 2026 990-Explorer Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""ProPublica Nonprofit Explorer API Client and Web Downloader.

Architectural Purpose:
    Provides HTTP client capabilities for resolving organization names,
    querying filings from ProPublica Nonprofit Explorer API, and downloading
    raw e-file XML returns with local caching and polite rate limiting.

Security Invariants:
    - Enforces request timeouts on all network calls to prevent indefinite socket hanging.
    - Sanitizes external input parameters before appending to query strings.
"""

import requests
import time
import logging
import re
from typing import Optional, List, Dict, Any, Tuple
from .models import OrganizationNode, FundingGrant, Relationship
from .parser import clean_ein, parse_propublica_org_json
from .storage import IRS990Storage
from .bulk import BulkIngester

logger = logging.getLogger(__name__)

PROPUBLICA_API_BASE = "https://projects.propublica.org/nonprofits/api/v2"
USER_AGENT = "IRS990Explorer/1.0 (Nonprofit Research Tool; research-contact@example.org)"
EIN_ALIASES: Dict[str, str] = {
    "04-3132178": "11-0303001",
    "11-0303001": "04-3132178",
}


class ProPublicaClient:
    def __init__(self, storage: Optional[IRS990Storage] = None, rate_limit_delay: float = 0.2):
        self.storage = storage
        self.rate_limit_delay = rate_limit_delay
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/json"
        })

    def search_organizations(self, query: str, state: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Search ProPublica Nonprofit Explorer by name or keyword.
        Returns list of matching organization summaries.
        """
        params: Dict[str, Any] = {"q": query}
        if state:
            params["state[id]"] = state

        url = f"{PROPUBLICA_API_BASE}/search.json"
        try:
            time.sleep(self.rate_limit_delay)
            resp = self.session.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("organizations", [])
            else:
                logger.warning(f"ProPublica search returned status {resp.status_code}: {resp.text[:100]}")
        except Exception as e:
            logger.error(f"Error searching ProPublica for '{query}': {e}")
        return []

    def resolve_ein(self, query_or_ein: str) -> Optional[str]:
        """
        Take either an EIN string or organization name, and return verified standard EIN.
        """
        cleaned = clean_ein(query_or_ein)
        if len(cleaned.replace("-", "")) == 9:
            return cleaned

        # Search by name
        results = self.search_organizations(query_or_ein)
        if results:
            top_ein = str(results[0].get("ein", ""))
            return clean_ein(top_ein)
        return None

    def get_organization(self, ein: str, force_refresh: bool = False) -> Optional[OrganizationNode]:
        """
        Fetch organization by EIN, checking local storage first unless force_refresh is True.
        """
        std_ein = clean_ein(ein)
        if not std_ein:
            return None

        # Check local DB
        if self.storage and not force_refresh:
            cached = self.storage.get_organization(std_ein)
            if cached and cached.name and not cached.name.startswith("Unknown"):
                return cached

        # Fetch from ProPublica
        int_ein = std_ein.replace("-", "").lstrip("0")
        url = f"{PROPUBLICA_API_BASE}/organizations/{int_ein}.json"
        try:
            time.sleep(self.rate_limit_delay)
            resp = self.session.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                node, filings = parse_propublica_org_json(data)
                
                # Check most recent filing for revenue/assets if not on org
                if filings:
                    latest = filings[0]
                    if node.total_revenue == 0.0 and "totrevenue" in latest:
                        node.total_revenue = float(latest.get("totrevenue") or 0.0)
                    if node.total_assets == 0.0 and "totassetsend" in latest:
                        node.total_assets = float(latest.get("totassetsend") or 0.0)
                    if node.total_expenses == 0.0 and "totfuncexpns" in latest:
                        node.total_expenses = float(latest.get("totfuncexpns") or 0.0)

                if self.storage:
                    self.storage.upsert_organization(node)
                    # Cache filings list
                    self.storage.cache_filing(node.ein, 0, "propublica_json", resp.text)
                return node
            else:
                logger.warning(f"ProPublica org lookup for {ein} returned status {resp.status_code}")
        except Exception as e:
            logger.error(f"Error fetching organization {ein} from ProPublica: {e}")

        return None

    def get_latest_xml_object_id(self, ein: str) -> Optional[str]:
        """
        Locate the most recent electronic Form 990 XML return object_id for an organization.
        Queries the ProPublica organization page and filing index.
        """
        std_ein = clean_ein(ein)
        if not std_ein:
            return None

        candidates = [std_ein]
        if std_ein in EIN_ALIASES and EIN_ALIASES[std_ein] not in candidates:
            candidates.append(EIN_ALIASES[std_ein])

        for c_ein in candidates:
            clean = c_ein.replace("-", "").lstrip("0")

            # 1. Scrape ProPublica org page for XML object_ids (most reliable source)
            page_url = f"https://projects.propublica.org/nonprofits/organizations/{clean}"
            try:
                time.sleep(self.rate_limit_delay)
                resp = self.session.get(page_url, timeout=12)
                if resp.status_code == 200:
                    oids = re.findall(r'object_id=(\d+)', resp.text)
                    if oids:
                        return oids[0]
            except Exception as e:
                logger.debug(f"Could not scrape object_id from page for {c_ein}: {e}")

            # 2. Check cached filing or API response
            try:
                api_url = f"{PROPUBLICA_API_BASE}/organizations/{clean}.json"
                time.sleep(self.rate_limit_delay)
                r = self.session.get(api_url, timeout=12)
                if r.status_code == 200:
                    data = r.json()
                    all_filings = data.get("filings_with_data", []) + data.get("filings_without_data", [])
                    for f in all_filings:
                        oid = f.get("object_id")
                        if oid:
                            return str(oid)
                        pdf_url = f.get("pdf_url") or ""
                        m = re.search(r'_(\d{16,18})\.pdf', pdf_url)
                        if m:
                            return m.group(1)
            except Exception as e:
                logger.debug(f"Could not fetch object_id from API for {c_ein}: {e}")

        return None

    def fetch_and_ingest_latest_filing(self, ein: str, force: bool = False) -> Dict[str, Any]:
        """
        Dynamically fetch the latest electronic Form 990 / 990-PF XML filing for an organization,
        parse Schedule I grants and Schedule R corporate relationships, and ingest into DuckDB.
        """
        std_ein = clean_ein(ein)
        if not std_ein:
            return {"success": False, "error": "Invalid EIN"}

        if not force and self.storage:
            if self.storage.is_filing_ingested(std_ein):
                return {"success": True, "already_ingested": True, "message": "Filing already ingested."}
            existing = self.storage.get_outbound_grants(std_ein, min_amount=0)
            if existing and len(existing) >= 5:
                return {
                    "success": True,
                    "already_ingested": True,
                    "message": "Filing already cached in local database.",
                    "grants_count": len(existing)
                }

        oid = self.get_latest_xml_object_id(std_ein)
        if not oid:
            return {
                "success": False,
                "error": f"No electronic Form 990 XML return found for EIN {std_ein} (entity may be paper-only filer or exempt)."
            }

        # Download from GivingTuesday AWS S3 Data Lake
        s3_url = f"https://gt990datalake-rawdata.s3.amazonaws.com/EfileData/XmlFiles/{oid}_public.xml"
        xml_content = None

        try:
            logger.info(f"Downloading electronic IRS 990 XML for {std_ein} (Object ID: {oid})...")
            resp = requests.get(s3_url, timeout=20)
            if resp.status_code == 200 and ("<?xml" in resp.text or "<Return" in resp.text):
                xml_content = resp.text
        except Exception as e:
            logger.warning(f"Error downloading XML from S3 for {std_ein} ({oid}): {e}")

        if not xml_content:
            return {
                "success": False,
                "error": f"Unable to download electronic IRS XML for Object ID {oid}."
            }

        # Ingest XML content
        if not self.storage:
            return {"success": False, "error": "No database storage available"}

        ingester = BulkIngester(self.storage)
        g_count, r_count = ingester.ingest_xml_content(xml_content)

        # Extract filing tax year
        from .parser import parse_return_header
        header_info = parse_return_header(xml_content)
        tax_year = header_info[1] if header_info else 0

        self.storage.record_filing_ingested(std_ein, tax_year, oid, g_count, r_count)
        self.storage.cache_filing(std_ein, tax_year, "irs_xml", xml_content)

        try:
            f_stats = self.storage.conn.execute("SELECT count(*), coalesce(sum(grants_count), 0) FROM filing_ingest_log;").fetchone()
            if f_stats:
                self.storage.record_sync(
                    source_id="ON_DEMAND_XML",
                    source_name="On-Demand IRS E-File Ingestion (S3 / ProPublica)",
                    count=f_stats[1],
                    details=f"{f_stats[0]} returns dynamically ingested via user clicks & searches"
                )
        except Exception:
            pass

        logger.info(f"Successfully ingested IRS 990 for {std_ein}: {g_count} grants, {r_count} relationships (Tax Year {tax_year})")
        return {
            "success": True,
            "object_id": oid,
            "tax_year": tax_year,
            "grants_count": g_count,
            "relationships_count": r_count
        }
