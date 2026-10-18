# SPDX-FileCopyrightText: 2026 990-Explorer Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""DuckDB High-Performance Storage Engine for IRS 990 Data.

Architectural Purpose:
    Provides persistent local caching, indexing, and fast relational graph queries
    for nonprofit organizations, funding grants, corporate relationships, Part IX
    functional expenses, Form 8871/8872 Section 527 political organizations,
    and FEC political committee datasets.

Security Invariants:
    - All SQL queries use parameter substitution (? or $ placeholders) to prevent SQL injection.
    - Database directory paths are sanitized with os.path.abspath and exist within local workspace.
    - DuckDB connection lifecycle is managed cleanly with atomic commits and explicit closure.
"""

import duckdb
import os
import logging
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
from .models import (
    OrganizationNode, FundingGrant, Relationship, AggregatedGrantEdge,
    ExpenseBreakdown, IndependentContractor, PersonAffiliation
)
from .parser import clean_ein, EIN_ALIASES

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "irs990.duckdb")


class IRS990Storage:
    """DuckDB persistence and relational query engine for IRS 990 and campaign finance data."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        """Initialize DuckDB connection and ensure database schema is migrated.

        Args:
            db_path: Filesystem path to DuckDB database file.
        """
        self.db_path = db_path
        self.conn = None
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.conn = duckdb.connect(self.db_path)
        self._init_schema()

    def _init_schema(self):
        """Initialize database schema and indices."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS organizations (
                ein VARCHAR PRIMARY KEY,
                name VARCHAR,
                tax_status VARCHAR,
                total_revenue DOUBLE DEFAULT 0.0,
                total_assets DOUBLE DEFAULT 0.0,
                total_expenses DOUBLE DEFAULT 0.0,
                city VARCHAR,
                state VARCHAR,
                address VARCHAR,
                zipcode VARCHAR,
                ntee_code VARCHAR,
                last_updated TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS grants (
                id VARCHAR PRIMARY KEY,
                grantor_ein VARCHAR,
                grantor_name VARCHAR,
                recipient_ein VARCHAR,
                recipient_name VARCHAR,
                amount DOUBLE,
                tax_year INTEGER,
                purpose VARCHAR,
                source_schedule VARCHAR
            );

            CREATE INDEX IF NOT EXISTS idx_grants_grantor ON grants(grantor_ein);
            CREATE INDEX IF NOT EXISTS idx_grants_recipient ON grants(recipient_ein);
            CREATE INDEX IF NOT EXISTS idx_grants_amount ON grants(amount);
            CREATE INDEX IF NOT EXISTS idx_grants_year ON grants(tax_year);

            CREATE TABLE IF NOT EXISTS relationships (
                id VARCHAR PRIMARY KEY,
                entity_ein VARCHAR,
                entity_name VARCHAR,
                related_ein VARCHAR,
                related_name VARCHAR,
                relationship_type VARCHAR,
                primary_activity VARCHAR,
                source_schedule VARCHAR
            );

            CREATE INDEX IF NOT EXISTS idx_rel_entity ON relationships(entity_ein);
            CREATE INDEX IF NOT EXISTS idx_rel_related ON relationships(related_ein);

            CREATE TABLE IF NOT EXISTS filing_cache (
                key VARCHAR PRIMARY KEY,
                ein VARCHAR,
                tax_year INTEGER,
                payload_type VARCHAR,
                payload TEXT,
                fetched_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS filing_ingest_log (
                ein VARCHAR PRIMARY KEY,
                last_ingested TIMESTAMP,
                tax_year INTEGER,
                object_id VARCHAR,
                grants_count INTEGER,
                relationships_count INTEGER
            );

            CREATE TABLE IF NOT EXISTS ingestion_metadata (
                source_id VARCHAR PRIMARY KEY,
                source_name VARCHAR,
                last_synced_at TIMESTAMP,
                records_count BIGINT,
                details VARCHAR
            );

            CREATE TABLE IF NOT EXISTS expenses (
                id VARCHAR PRIMARY KEY,
                filer_ein VARCHAR,
                filer_name VARCHAR,
                tax_year INTEGER,
                total_expenses DOUBLE DEFAULT 0.0,
                program_services DOUBLE DEFAULT 0.0,
                management_general DOUBLE DEFAULT 0.0,
                fundraising DOUBLE DEFAULT 0.0,
                salaries_total DOUBLE DEFAULT 0.0,
                professional_fees DOUBLE DEFAULT 0.0,
                office_and_it DOUBLE DEFAULT 0.0,
                travel_and_conferences DOUBLE DEFAULT 0.0,
                grants_paid DOUBLE DEFAULT 0.0
            );
            CREATE INDEX IF NOT EXISTS idx_expenses_ein ON expenses(filer_ein);

            CREATE TABLE IF NOT EXISTS contractors (
                id VARCHAR PRIMARY KEY,
                filer_ein VARCHAR,
                filer_name VARCHAR,
                tax_year INTEGER,
                contractor_name VARCHAR,
                city VARCHAR,
                state VARCHAR,
                description_of_services VARCHAR,
                amount DOUBLE DEFAULT 0.0
            );
            CREATE INDEX IF NOT EXISTS idx_contractors_ein ON contractors(filer_ein);

            CREATE TABLE IF NOT EXISTS people (
                id VARCHAR PRIMARY KEY,
                filer_ein VARCHAR,
                filer_name VARCHAR,
                tax_year INTEGER,
                person_name VARCHAR,
                clean_name VARCHAR,
                title VARCHAR,
                role_type VARCHAR,
                hours_per_week DOUBLE DEFAULT 0.0,
                reportable_comp DOUBLE DEFAULT 0.0,
                related_org_comp DOUBLE DEFAULT 0.0,
                other_comp DOUBLE DEFAULT 0.0,
                total_comp DOUBLE DEFAULT 0.0
            );
            CREATE INDEX IF NOT EXISTS idx_people_clean_name ON people(clean_name);
            CREATE INDEX IF NOT EXISTS idx_people_ein ON people(filer_ein);

            CREATE TABLE IF NOT EXISTS irs_527_orgs (
                form_id_number VARCHAR PRIMARY KEY,
                org_name VARCHAR,
                ein VARCHAR,
                form_type VARCHAR,
                address_1 VARCHAR,
                address_2 VARCHAR,
                city VARCHAR,
                state VARCHAR,
                zip VARCHAR,
                email VARCHAR,
                custodian_name VARCHAR,
                purpose TEXT,
                insert_datetime TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_527_orgs_ein ON irs_527_orgs(ein);
            CREATE INDEX IF NOT EXISTS idx_527_orgs_name ON irs_527_orgs(org_name);

            CREATE TABLE IF NOT EXISTS irs_527_directors (
                id VARCHAR PRIMARY KEY,
                form_id_number VARCHAR,
                org_name VARCHAR,
                ein VARCHAR,
                person_name VARCHAR,
                clean_name VARCHAR,
                title VARCHAR,
                address_1 VARCHAR,
                city VARCHAR,
                state VARCHAR,
                zip VARCHAR
            );
            CREATE INDEX IF NOT EXISTS idx_527_dir_ein ON irs_527_directors(ein);
            CREATE INDEX IF NOT EXISTS idx_527_dir_clean ON irs_527_directors(clean_name);

            CREATE TABLE IF NOT EXISTS irs_527_related (
                id VARCHAR PRIMARY KEY,
                form_id_number VARCHAR,
                org_name VARCHAR,
                ein VARCHAR,
                related_org_name VARCHAR,
                relationship_type VARCHAR,
                city VARCHAR,
                state VARCHAR
            );
            CREATE INDEX IF NOT EXISTS idx_527_rel_ein ON irs_527_related(ein);
            CREATE INDEX IF NOT EXISTS idx_527_rel_name ON irs_527_related(related_org_name);

            CREATE TABLE IF NOT EXISTS irs_527_reports (
                form_id_number VARCHAR PRIMARY KEY,
                form_type VARCHAR,
                ein VARCHAR,
                org_name VARCHAR,
                period_begin DATE,
                period_end DATE,
                total_contributions DOUBLE DEFAULT 0.0,
                total_expenditures DOUBLE DEFAULT 0.0,
                insert_datetime TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_527_rep_ein ON irs_527_reports(ein);

            CREATE TABLE IF NOT EXISTS irs_527_contributions (
                id VARCHAR PRIMARY KEY,
                form_id_number VARCHAR,
                sched_a_id VARCHAR,
                org_name VARCHAR,
                ein VARCHAR,
                contributor_name VARCHAR,
                city VARCHAR,
                state VARCHAR,
                zip VARCHAR,
                employer VARCHAR,
                occupation VARCHAR,
                amount DOUBLE DEFAULT 0.0,
                aggregate_ytd DOUBLE DEFAULT 0.0,
                contribution_date VARCHAR
            );
            CREATE INDEX IF NOT EXISTS idx_527_contrib_ein ON irs_527_contributions(ein);
            CREATE INDEX IF NOT EXISTS idx_527_contrib_name ON irs_527_contributions(contributor_name);

            CREATE TABLE IF NOT EXISTS irs_527_expenditures (
                id VARCHAR PRIMARY KEY,
                form_id_number VARCHAR,
                sched_b_id VARCHAR,
                org_name VARCHAR,
                ein VARCHAR,
                recipient_name VARCHAR,
                city VARCHAR,
                state VARCHAR,
                zip VARCHAR,
                employer VARCHAR,
                occupation VARCHAR,
                amount DOUBLE DEFAULT 0.0,
                expenditure_date VARCHAR,
                purpose VARCHAR
            );
            CREATE INDEX IF NOT EXISTS idx_527_exp_ein ON irs_527_expenditures(ein);
            CREATE INDEX IF NOT EXISTS idx_527_exp_recip ON irs_527_expenditures(recipient_name);

            -- FEC Political Committees & Independent Expenditures
            CREATE TABLE IF NOT EXISTS fec_committees (
                cmte_id VARCHAR PRIMARY KEY,
                cmte_name VARCHAR,
                treasurer_name VARCHAR,
                clean_treasurer VARCHAR,
                city VARCHAR,
                state VARCHAR,
                zip VARCHAR,
                cmte_designation VARCHAR,
                cmte_type VARCHAR,
                party_affiliation VARCHAR,
                org_type VARCHAR,
                connected_org_name VARCHAR,
                clean_connected_org VARCHAR,
                candidate_id VARCHAR,
                cycle INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_fec_cmte_name ON fec_committees(cmte_name);
            CREATE INDEX IF NOT EXISTS idx_fec_connected ON fec_committees(connected_org_name);
            CREATE INDEX IF NOT EXISTS idx_fec_clean_connected ON fec_committees(clean_connected_org);
            CREATE INDEX IF NOT EXISTS idx_fec_clean_treasurer ON fec_committees(clean_treasurer);

            CREATE TABLE IF NOT EXISTS fec_candidates (
                candidate_id VARCHAR PRIMARY KEY,
                candidate_name VARCHAR,
                clean_candidate_name VARCHAR,
                party VARCHAR,
                election_year INTEGER,
                office_state VARCHAR,
                office VARCHAR,
                district VARCHAR,
                pcc_id VARCHAR,
                cycle INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_fec_cand_name ON fec_candidates(candidate_name);
            CREATE INDEX IF NOT EXISTS idx_fec_cand_clean ON fec_candidates(clean_candidate_name);

            CREATE TABLE IF NOT EXISTS fec_candidate_linkages (
                id VARCHAR PRIMARY KEY,
                candidate_id VARCHAR,
                candidate_election_year INTEGER,
                fec_election_year INTEGER,
                cmte_id VARCHAR,
                cmte_type VARCHAR,
                cmte_designation VARCHAR,
                linkage_id VARCHAR,
                cycle INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_fec_link_cmte ON fec_candidate_linkages(cmte_id);
            CREATE INDEX IF NOT EXISTS idx_fec_link_cand ON fec_candidate_linkages(candidate_id);

            CREATE TABLE IF NOT EXISTS fec_transactions (
                sub_id VARCHAR PRIMARY KEY,
                cmte_id VARCHAR,
                transaction_type VARCHAR,
                entity_type VARCHAR,
                recipient_name VARCHAR,
                city VARCHAR,
                state VARCHAR,
                zip VARCHAR,
                employer VARCHAR,
                occupation VARCHAR,
                transaction_date VARCHAR,
                amount DOUBLE DEFAULT 0.0,
                other_id VARCHAR,
                memo_text VARCHAR,
                cycle INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_fec_tx_cmte ON fec_transactions(cmte_id);
            CREATE INDEX IF NOT EXISTS idx_fec_tx_other ON fec_transactions(other_id);
            CREATE INDEX IF NOT EXISTS idx_fec_tx_recip ON fec_transactions(recipient_name);

            CREATE TABLE IF NOT EXISTS fec_operating_expenditures (
                sub_id VARCHAR PRIMARY KEY,
                cmte_id VARCHAR,
                payee_name VARCHAR,
                city VARCHAR,
                state VARCHAR,
                zip VARCHAR,
                transaction_date VARCHAR,
                amount DOUBLE DEFAULT 0.0,
                purpose VARCHAR,
                category_desc VARCHAR,
                cycle INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_fec_oppexp_cmte ON fec_operating_expenditures(cmte_id);
            CREATE INDEX IF NOT EXISTS idx_fec_oppexp_payee ON fec_operating_expenditures(payee_name);

            -- Cross-Entity Linkages bridging 501(c)s to PACs and 527s
            CREATE TABLE IF NOT EXISTS entity_linkages (
                id VARCHAR PRIMARY KEY,
                source_ein VARCHAR,
                source_name VARCHAR,
                target_type VARCHAR,
                target_id VARCHAR,
                target_name VARCHAR,
                link_type VARCHAR,
                confidence_score DOUBLE,
                evidence_json VARCHAR,
                description VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_linkage_source_ein ON entity_linkages(source_ein);
            CREATE INDEX IF NOT EXISTS idx_linkage_target_id ON entity_linkages(target_id);
            CREATE INDEX IF NOT EXISTS idx_linkage_type ON entity_linkages(link_type);
        """)

    def close(self):
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __del__(self):
        self.close()

    def upsert_organization(self, node: OrganizationNode):
        """Insert or update organization record."""
        now = datetime.now()
        self.conn.execute("""
            INSERT INTO organizations (
                ein, name, tax_status, total_revenue, total_assets, total_expenses,
                city, state, address, zipcode, ntee_code, last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (ein) DO UPDATE SET
                name = CASE WHEN excluded.name != 'Unknown Organization' THEN excluded.name ELSE organizations.name END,
                tax_status = CASE WHEN excluded.tax_status != 'Unknown' THEN excluded.tax_status ELSE organizations.tax_status END,
                total_revenue = CASE WHEN excluded.total_revenue > 0 THEN excluded.total_revenue ELSE organizations.total_revenue END,
                total_assets = CASE WHEN excluded.total_assets > 0 THEN excluded.total_assets ELSE organizations.total_assets END,
                city = CASE WHEN excluded.city != '' THEN excluded.city ELSE organizations.city END,
                state = CASE WHEN excluded.state != '' THEN excluded.state ELSE organizations.state END,
                address = CASE WHEN excluded.address != '' THEN excluded.address ELSE organizations.address END,
                zipcode = CASE WHEN excluded.zipcode != '' THEN excluded.zipcode ELSE organizations.zipcode END,
                ntee_code = CASE WHEN excluded.ntee_code != '' THEN excluded.ntee_code ELSE organizations.ntee_code END,
                last_updated = ?;
        """, (
            node.ein, node.name, node.tax_status, node.total_revenue, node.total_assets,
            node.total_expenses, node.city, node.state, node.address, node.zipcode,
            node.ntee_code, now, now
        ))

    def get_organization(self, ein: str) -> Optional[OrganizationNode]:
        """Fetch organization record by EIN, checking aliases if needed."""
        eins = [ein]
        if ein in EIN_ALIASES and EIN_ALIASES[ein] not in eins:
            eins.append(EIN_ALIASES[ein])

        for query_ein in eins:
            res = self.conn.execute("""
                SELECT ein, name, tax_status, total_revenue, total_assets, total_expenses,
                       city, state, address, zipcode, ntee_code
                FROM organizations WHERE ein = ?;
            """, (query_ein,)).fetchone()
            if res:
                return OrganizationNode(
                    ein=res[0],
                    name=res[1],
                    tax_status=res[2],
                    total_revenue=res[3] or 0.0,
                    total_assets=res[4] or 0.0,
                    total_expenses=res[5] or 0.0,
                    city=res[6] or "",
                    state=res[7] or "",
                    address=res[8] or "",
                    zipcode=res[9] or "",
                    ntee_code=res[10] or ""
                )
        return None


    def search_organizations(self, query: str, limit: int = 10) -> List[OrganizationNode]:
        """Search organizations by name or EIN."""
        pattern = f"%{query}%"
        rows = self.conn.execute("""
            SELECT ein, name, tax_status, total_revenue, total_assets, total_expenses,
                   city, state, address, zipcode, ntee_code
            FROM organizations
            WHERE name ILIKE ? OR ein LIKE ?
            ORDER BY total_revenue DESC
            LIMIT ?;
        """, (pattern, pattern, limit)).fetchall()
        
        nodes = []
        for res in rows:
            nodes.append(OrganizationNode(
                ein=res[0],
                name=res[1],
                tax_status=res[2],
                total_revenue=res[3] or 0.0,
                total_assets=res[4] or 0.0,
                total_expenses=res[5] or 0.0,
                city=res[6] or "",
                state=res[7] or "",
                address=res[8] or "",
                zipcode=res[9] or "",
                ntee_code=res[10] or ""
            ))
        return nodes

    def upsert_grants(self, grants: List[FundingGrant]):
        """Batch upsert grants into database."""
        if not grants:
            return
        
        data = [
            (
                g.key(),
                g.grantor_ein,
                g.grantor_name,
                g.recipient_ein,
                g.recipient_name,
                g.amount,
                g.tax_year,
                g.purpose,
                g.source_schedule
            )
            for g in grants
        ]

        self.conn.executemany("""
            INSERT INTO grants (
                id, grantor_ein, grantor_name, recipient_ein, recipient_name,
                amount, tax_year, purpose, source_schedule
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                amount = excluded.amount,
                purpose = CASE WHEN excluded.purpose != '' THEN excluded.purpose ELSE grants.purpose END;
        """, data)

    def get_outbound_grants(
        self,
        grantor_ein: str,
        min_amount: float = 0.0,
        start_year: Optional[int] = None,
        end_year: Optional[int] = None
    ) -> List[FundingGrant]:
        """Fetch all grants made BY grantor_ein, checking aliases."""
        eins = [grantor_ein]
        if grantor_ein in EIN_ALIASES and EIN_ALIASES[grantor_ein] not in eins:
            eins.append(EIN_ALIASES[grantor_ein])
        placeholders = ", ".join("?" for _ in eins)

        query = f"""
            SELECT grantor_ein, grantor_name, recipient_ein, recipient_name,
                   amount, tax_year, purpose, source_schedule
            FROM grants
            WHERE grantor_ein IN ({placeholders}) AND amount >= ?
        """
        params: List[Any] = list(eins) + [min_amount]
        if start_year is not None:
            query += " AND tax_year >= ?"
            params.append(start_year)
        if end_year is not None:
            query += " AND tax_year <= ?"
            params.append(end_year)
        query += " ORDER BY amount DESC;"

        rows = self.conn.execute(query, params).fetchall()
        return [
            FundingGrant(
                grantor_ein=r[0],
                grantor_name=r[1],
                recipient_ein=r[2],
                recipient_name=r[3],
                amount=r[4],
                tax_year=r[5],
                purpose=r[6] or "",
                source_schedule=r[7] or "Schedule I"
            )
            for r in rows
        ]

    def get_inbound_grants(
        self,
        recipient_ein: str,
        min_amount: float = 0.0,
        start_year: Optional[int] = None,
        end_year: Optional[int] = None
    ) -> List[FundingGrant]:
        """Fetch all grants made TO recipient_ein, checking aliases."""
        eins = [recipient_ein]
        if recipient_ein in EIN_ALIASES and EIN_ALIASES[recipient_ein] not in eins:
            eins.append(EIN_ALIASES[recipient_ein])
        placeholders = ", ".join("?" for _ in eins)

        query = f"""
            SELECT grantor_ein, grantor_name, recipient_ein, recipient_name,
                   amount, tax_year, purpose, source_schedule
            FROM grants
            WHERE recipient_ein IN ({placeholders}) AND amount >= ?
        """
        params: List[Any] = list(eins) + [min_amount]
        if start_year is not None:
            query += " AND tax_year >= ?"
            params.append(start_year)
        if end_year is not None:
            query += " AND tax_year <= ?"
            params.append(end_year)
        query += " ORDER BY amount DESC;"


        rows = self.conn.execute(query, params).fetchall()
        return [
            FundingGrant(
                grantor_ein=r[0],
                grantor_name=r[1],
                recipient_ein=r[2],
                recipient_name=r[3],
                amount=r[4],
                tax_year=r[5],
                purpose=r[6] or "",
                source_schedule=r[7] or "Schedule I"
            )
            for r in rows
        ]

    def upsert_relationships(self, relationships: List[Relationship]):
        """Batch upsert corporate relationships from Schedule R."""
        if not relationships:
            return
        
        data = [
            (
                r.key(),
                r.entity_ein,
                r.entity_name,
                r.related_ein,
                r.related_name,
                r.relationship_type,
                r.primary_activity,
                r.source_schedule
            )
            for r in relationships
        ]

        self.conn.executemany("""
            INSERT INTO relationships (
                id, entity_ein, entity_name, related_ein, related_name,
                relationship_type, primary_activity, source_schedule
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                relationship_type = excluded.relationship_type,
                primary_activity = excluded.primary_activity;
        """, data)

    def get_relationships(self, ein: str) -> List[Relationship]:
        """Fetch all Schedule R relationships for an EIN (either as entity or related)."""
        rows = self.conn.execute("""
            SELECT entity_ein, entity_name, related_ein, related_name,
                   relationship_type, primary_activity, source_schedule
            FROM relationships
            WHERE entity_ein = ? OR related_ein = ?;
        """, (ein, ein)).fetchall()

        return [
            Relationship(
                entity_ein=r[0],
                entity_name=r[1],
                related_ein=r[2],
                related_name=r[3],
                relationship_type=r[4],
                primary_activity=r[5] or "",
                source_schedule=r[6] or "Schedule R"
            )
            for r in rows
        ]

    def cache_filing(self, ein: str, tax_year: int, payload_type: str, payload: str):
        """Save raw filing payload (JSON or XML) in cache."""
        key = f"{ein}:{tax_year}:{payload_type}"
        self.conn.execute("""
            INSERT INTO filing_cache (key, ein, tax_year, payload_type, payload, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (key) DO UPDATE SET
                payload = excluded.payload,
                fetched_at = excluded.fetched_at;
        """, (key, ein, tax_year, payload_type, payload, datetime.now()))

    def get_cached_filing(self, ein: str, tax_year: int, payload_type: str) -> Optional[str]:
        """Retrieve cached filing payload if available."""
        key = f"{ein}:{tax_year}:{payload_type}"
        res = self.conn.execute("""
            SELECT payload FROM filing_cache WHERE key = ?;
        """, (key,)).fetchone()
        return res[0] if res else None

    def upsert_organizations(self, nodes: List[OrganizationNode]):
        """Batch upsert organizations in a single efficient query."""
        if not nodes:
            return
        now = datetime.now()
        seen = {}
        for n in nodes:
            if n.ein and n.ein not in seen:
                seen[n.ein] = n

        data = [
            (
                n.ein, n.name, n.tax_status, n.total_revenue, n.total_assets,
                n.total_expenses, n.city, n.state, n.address, n.zipcode,
                n.ntee_code, now, now
            )
            for n in seen.values()
        ]

        self.conn.executemany("""
            INSERT INTO organizations (
                ein, name, tax_status, total_revenue, total_assets, total_expenses,
                city, state, address, zipcode, ntee_code, last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (ein) DO UPDATE SET
                name = CASE WHEN excluded.name != 'Unknown Organization' AND excluded.name != '' THEN excluded.name ELSE organizations.name END,
                last_updated = ?;
        """, data)

    def is_filing_ingested(self, ein: str) -> bool:
        """Check whether an organization has already had electronic XML filings ingested."""
        res = self.conn.execute("SELECT 1 FROM filing_ingest_log WHERE ein = ?;", (ein,)).fetchone()
        return bool(res)

    def record_filing_ingested(self, ein: str, tax_year: int, object_id: str, grants_count: int, rels_count: int):
        """Record electronic filing ingestion completion."""
        now = datetime.now()
        self.conn.execute("""
            INSERT INTO filing_ingest_log (ein, last_ingested, tax_year, object_id, grants_count, relationships_count)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (ein) DO UPDATE SET
                last_ingested = excluded.last_ingested,
                tax_year = excluded.tax_year,
                object_id = excluded.object_id,
                grants_count = excluded.grants_count,
                relationships_count = excluded.relationships_count;
        """, (ein, now, tax_year, object_id, grants_count, rels_count))

    def record_sync(self, source_id: str, source_name: str, count: int, details: str = ""):
        """Record or update ingestion metadata for a specific data source."""
        now = datetime.now()
        self.conn.execute("""
            INSERT INTO ingestion_metadata (source_id, source_name, last_synced_at, records_count, details)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (source_id) DO UPDATE SET
                source_name = excluded.source_name,
                last_synced_at = excluded.last_synced_at,
                records_count = excluded.records_count,
                details = excluded.details;
        """, (source_id, source_name, now, count, details))

    def get_ingestion_metadata(self) -> List[Dict[str, Any]]:
        """Return all tracked ingestion metadata records ordered by sync time."""
        try:
            rows = self.conn.execute("""
                SELECT source_id, source_name, last_synced_at, records_count, details
                FROM ingestion_metadata
                ORDER BY last_synced_at DESC;
            """).fetchall()
            return [
                {
                    "source_id": r[0],
                    "source_name": r[1],
                    "last_synced_at": r[2],
                    "records_count": r[3],
                    "details": r[4] or ""
                }
                for r in rows
            ]
        except Exception as e:
            logger.warning(f"Error reading ingestion metadata: {e}")
            return []

    def get_database_stats(self) -> Dict[str, Any]:
        """
        Aggregate comprehensive statistics across all tables and ingested sources.
        Returns a structured dictionary organized by data source.
        """
        stats: Dict[str, Any] = {
            "db_path": self.db_path,
            "db_size_bytes": os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0,
            "timestamp": datetime.now(),
            "sources": self.get_ingestion_metadata(),
            "bmf": {},
            "organizations": {},
            "grants": {},
            "relationships": {},
            "filings": {}
        }
        stats["db_size_mb"] = stats["db_size_bytes"] / (1024 * 1024)

        # 1. BMF Stats (if table exists)
        try:
            table_check = self.conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'irs_bmf';"
            ).fetchone()
            if table_check and table_check[0] > 0:
                bmf_total = self.conn.execute("SELECT count(*) FROM irs_bmf;").fetchone()[0]
                c3_count = self.conn.execute("SELECT count(*) FROM irs_bmf WHERE subsection = '03';").fetchone()[0]
                pf_count = self.conn.execute("SELECT count(*) FROM irs_bmf WHERE foundation IN ('02', '03', '04');").fetchone()[0]
                financials = self.conn.execute("""
                    SELECT coalesce(sum(asset_amt), 0), coalesce(sum(revenue_amt), 0)
                    FROM irs_bmf;
                """).fetchone()
                stats["bmf"] = {
                    "table_present": True,
                    "total_organizations": bmf_total,
                    "501c3_count": c3_count,
                    "private_foundations_count": pf_count,
                    "total_assets": financials[0],
                    "total_revenue": financials[1]
                }
            else:
                stats["bmf"] = {"table_present": False}
        except Exception as e:
            stats["bmf"] = {"table_present": False, "error": str(e)}

        # 2. Organizations Table Stats
        try:
            org_count = self.conn.execute("SELECT count(*) FROM organizations;").fetchone()[0]
            with_fin = self.conn.execute(
                "SELECT count(*) FROM organizations WHERE total_revenue > 0 OR total_assets > 0;"
            ).fetchone()[0]
            stats["organizations"] = {
                "total_entities": org_count,
                "entities_with_financials": with_fin
            }
        except Exception as e:
            stats["organizations"] = {"error": str(e)}

        # 3. Grants Table Stats
        try:
            grant_agg = self.conn.execute("""
                SELECT count(*), coalesce(sum(amount), 0),
                       count(DISTINCT grantor_ein), count(DISTINCT recipient_ein),
                       min(tax_year), max(tax_year)
                FROM grants;
            """).fetchone()

            by_schedule = self.conn.execute("""
                SELECT coalesce(source_schedule, 'Schedule I'), count(*), coalesce(sum(amount), 0)
                FROM grants
                GROUP BY 1
                ORDER BY 2 DESC;
            """).fetchall()

            stats["grants"] = {
                "total_grants": grant_agg[0],
                "total_dollar_volume": grant_agg[1],
                "unique_grantors": grant_agg[2],
                "unique_recipients": grant_agg[3],
                "min_year": grant_agg[4],
                "max_year": grant_agg[5],
                "by_schedule": [
                    {"schedule": r[0], "count": r[1], "dollar_volume": r[2]}
                    for r in by_schedule
                ]
            }
        except Exception as e:
            stats["grants"] = {"error": str(e)}

        # 4. Relationships Table Stats
        try:
            rel_count = self.conn.execute("SELECT count(*) FROM relationships;").fetchone()[0]
            by_type = self.conn.execute("""
                SELECT coalesce(relationship_type, 'Related'), count(*)
                FROM relationships
                GROUP BY 1
                ORDER BY 2 DESC;
            """).fetchall()
            stats["relationships"] = {
                "total_relationships": rel_count,
                "by_type": [{"type": r[0], "count": r[1]} for r in by_type]
            }
        except Exception as e:
            stats["relationships"] = {"error": str(e)}

        # 5. Filings Ingest Log Stats
        try:
            filings_count = self.conn.execute("SELECT count(*) FROM filing_ingest_log;").fetchone()[0]
            cache_count = self.conn.execute("SELECT count(*) FROM filing_cache;").fetchone()[0]
            stats["filings"] = {
                "filings_ingested": filings_count,
                "cached_payloads": cache_count
            }
        except Exception as e:
            stats["filings"] = {"error": str(e)}

        # 6. Expenses, Contractors, and People Stats
        try:
            exp_count = self.conn.execute("SELECT count(*) FROM expenses;").fetchone()[0]
            contr_count = self.conn.execute("SELECT count(*) FROM contractors;").fetchone()[0]
            people_stats = self.conn.execute("""
                SELECT count(*), count(DISTINCT clean_name) FROM people;
            """).fetchone()

            # Find number of people on multiple boards
            interlocks_count = self.conn.execute("""
                SELECT count(*) FROM (
                    SELECT clean_name FROM people GROUP BY clean_name HAVING count(DISTINCT filer_ein) > 1
                );
            """).fetchone()[0]

            stats["spending_and_people"] = {
                "expenses_records": exp_count,
                "contractors_records": contr_count,
                "leadership_records": people_stats[0],
                "unique_people": people_stats[1],
                "multi_board_leaders": interlocks_count
            }
        except Exception as e:
            stats["spending_and_people"] = {"error": str(e)}

        # 7. IRS Section 527 Political Organizations Stats
        try:
            orgs_527 = self.conn.execute("SELECT count(*) FROM irs_527_orgs;").fetchone()[0]
            rep_527 = self.conn.execute("SELECT count(*) FROM irs_527_reports;").fetchone()[0]
            contrib_527 = self.conn.execute("""
                SELECT count(*), coalesce(sum(amount), 0.0) FROM irs_527_contributions;
            """).fetchone()
            exp_527 = self.conn.execute("""
                SELECT count(*), coalesce(sum(amount), 0.0) FROM irs_527_expenditures;
            """).fetchone()
            stats["pacs_527"] = {
                "table_present": True,
                "total_527_orgs": orgs_527,
                "total_reports": rep_527,
                "total_contributions": contrib_527[0],
                "contributions_volume": contrib_527[1],
                "total_expenditures": exp_527[0],
                "expenditures_volume": exp_527[1]
            }
        except Exception as e:
            stats["pacs_527"] = {"table_present": False, "error": str(e)}

        try:
            cmte_count = self.conn.execute("SELECT count(*) FROM fec_committees;").fetchone()[0]
            super_pacs = self.conn.execute("SELECT count(*) FROM fec_committees WHERE cmte_type = 'O';").fetchone()[0]
            cand_count = self.conn.execute("SELECT count(*) FROM fec_candidates;").fetchone()[0]
            tx_stats = self.conn.execute("SELECT count(*), coalesce(sum(amount), 0.0) FROM fec_transactions;").fetchone()
            opp_stats = self.conn.execute("SELECT count(*), coalesce(sum(amount), 0.0) FROM fec_operating_expenditures;").fetchone()
            cycles = self.conn.execute("SELECT DISTINCT cycle FROM fec_committees WHERE cycle IS NOT NULL ORDER BY cycle DESC;").fetchall()
            stats["fec_pacs"] = {
                "table_present": True,
                "total_committees": cmte_count,
                "total_super_pacs": super_pacs,
                "total_candidates": cand_count,
                "total_transactions": tx_stats[0],
                "transactions_volume": tx_stats[1],
                "total_operating_expenditures": opp_stats[0],
                "operating_expenditures_volume": opp_stats[1],
                "cycles": [c[0] for c in cycles]
            }
        except Exception as e:
            stats["fec_pacs"] = {"table_present": False, "error": str(e)}

        # 8. Cross-Entity Linkages Stats
        try:
            link_count = self.conn.execute("SELECT count(*) FROM entity_linkages;").fetchone()[0]
            by_link_type = self.conn.execute("""
                SELECT link_type, count(*) FROM entity_linkages GROUP BY 1 ORDER BY 2 DESC;
            """).fetchall()
            stats["linkages"] = {
                "table_present": True,
                "total_linkages": link_count,
                "by_type": {r[0]: r[1] for r in by_link_type}
            }
        except Exception as e:
            stats["linkages"] = {"table_present": False, "error": str(e)}

        return stats

    def upsert_expenses(self, expenses: List[ExpenseBreakdown]):
        """Batch upsert Part IX functional expenses."""
        if not expenses:
            return
        data = [
            (
                e.key(), e.filer_ein, e.filer_name, e.tax_year, e.total_expenses,
                e.program_services, e.management_general, e.fundraising,
                e.salaries_total, e.professional_fees, e.office_and_it,
                e.travel_and_conferences, e.grants_paid
            )
            for e in expenses
        ]
        self.conn.executemany("""
            INSERT INTO expenses (
                id, filer_ein, filer_name, tax_year, total_expenses,
                program_services, management_general, fundraising,
                salaries_total, professional_fees, office_and_it,
                travel_and_conferences, grants_paid
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                total_expenses = excluded.total_expenses,
                program_services = excluded.program_services,
                management_general = excluded.management_general,
                fundraising = excluded.fundraising,
                salaries_total = excluded.salaries_total,
                professional_fees = excluded.professional_fees,
                office_and_it = excluded.office_and_it,
                travel_and_conferences = excluded.travel_and_conferences,
                grants_paid = excluded.grants_paid;
        """, data)

    def get_expenses(self, ein: str, tax_year: Optional[int] = None) -> List[ExpenseBreakdown]:
        """Fetch functional expense records for an organization."""
        eins = [ein]
        if ein in EIN_ALIASES and EIN_ALIASES[ein] not in eins:
            eins.append(EIN_ALIASES[ein])
        placeholders = ", ".join("?" for _ in eins)

        query = f"""
            SELECT filer_ein, filer_name, tax_year, total_expenses, program_services,
                   management_general, fundraising, salaries_total, professional_fees,
                   office_and_it, travel_and_conferences, grants_paid
            FROM expenses
            WHERE filer_ein IN ({placeholders})
        """
        params: List[Any] = list(eins)
        if tax_year is not None:
            query += " AND tax_year = ?"
            params.append(tax_year)
        query += " ORDER BY tax_year DESC;"

        rows = self.conn.execute(query, params).fetchall()
        return [
            ExpenseBreakdown(
                filer_ein=r[0], filer_name=r[1], tax_year=r[2], total_expenses=r[3],
                program_services=r[4], management_general=r[5], fundraising=r[6],
                salaries_total=r[7], professional_fees=r[8], office_and_it=r[9],
                travel_and_conferences=r[10], grants_paid=r[11]
            )
            for r in rows
        ]

    def upsert_contractors(self, contractors: List[IndependentContractor]):
        """Batch upsert Part VII-B top independent contractors."""
        if not contractors:
            return
        data = [
            (
                c.key(), c.filer_ein, c.filer_name, c.tax_year,
                c.contractor_name, c.city, c.state, c.description_of_services, c.amount
            )
            for c in contractors
        ]
        self.conn.executemany("""
            INSERT INTO contractors (
                id, filer_ein, filer_name, tax_year,
                contractor_name, city, state, description_of_services, amount
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                description_of_services = excluded.description_of_services,
                amount = excluded.amount;
        """, data)

    def get_contractors(self, ein: str, tax_year: Optional[int] = None) -> List[IndependentContractor]:
        """Fetch top independent contractors for an organization."""
        eins = [ein]
        if ein in EIN_ALIASES and EIN_ALIASES[ein] not in eins:
            eins.append(EIN_ALIASES[ein])
        placeholders = ", ".join("?" for _ in eins)

        query = f"""
            SELECT filer_ein, filer_name, tax_year, contractor_name, city, state,
                   description_of_services, amount
            FROM contractors
            WHERE filer_ein IN ({placeholders})
        """
        params: List[Any] = list(eins)
        if tax_year is not None:
            query += " AND tax_year = ?"
            params.append(tax_year)
        query += " ORDER BY amount DESC;"

        rows = self.conn.execute(query, params).fetchall()
        return [
            IndependentContractor(
                filer_ein=r[0], filer_name=r[1], tax_year=r[2], contractor_name=r[3],
                city=r[4] or "", state=r[5] or "", description_of_services=r[6] or "", amount=r[7]
            )
            for r in rows
        ]
    # Convenience alias for contractor lookup by EIN
    get_contractors_by_ein = get_contractors

    def upsert_people(self, people: List[PersonAffiliation]):
        """Batch upsert Part VII officers, directors, trustees, and key employees."""
        if not people:
            return
        data = [
            (
                p.key(), p.filer_ein, p.filer_name, p.tax_year,
                p.person_name, p.clean_name, p.title, p.role_type,
                p.hours_per_week, p.reportable_comp, p.related_org_comp, p.other_comp, p.total_comp
            )
            for p in people
        ]
        self.conn.executemany("""
            INSERT INTO people (
                id, filer_ein, filer_name, tax_year,
                person_name, clean_name, title, role_type,
                hours_per_week, reportable_comp, related_org_comp, other_comp, total_comp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                title = excluded.title,
                role_type = excluded.role_type,
                hours_per_week = excluded.hours_per_week,
                reportable_comp = excluded.reportable_comp,
                related_org_comp = excluded.related_org_comp,
                other_comp = excluded.other_comp,
                total_comp = excluded.total_comp;
        """, data)

    def get_people_by_organization(self, ein: str, tax_year: Optional[int] = None) -> List[PersonAffiliation]:
        """Fetch officers, directors, and trustees for an organization."""
        eins = [ein]
        if ein in EIN_ALIASES and EIN_ALIASES[ein] not in eins:
            eins.append(EIN_ALIASES[ein])
        placeholders = ", ".join("?" for _ in eins)

        query = f"""
            SELECT filer_ein, filer_name, tax_year, person_name, clean_name, title,
                   role_type, hours_per_week, reportable_comp, related_org_comp, other_comp, total_comp
            FROM people
            WHERE filer_ein IN ({placeholders})
        """
        params: List[Any] = list(eins)
        if tax_year is not None:
            query += " AND tax_year = ?"
            params.append(tax_year)
        query += " ORDER BY total_comp DESC, hours_per_week DESC;"

        rows = self.conn.execute(query, params).fetchall()
        return [
            PersonAffiliation(
                filer_ein=r[0], filer_name=r[1], tax_year=r[2], person_name=r[3],
                clean_name=r[4], title=r[5], role_type=r[6], hours_per_week=r[7],
                reportable_comp=r[8], related_org_comp=r[9], other_comp=r[10], total_comp=r[11]
            )
            for r in rows
        ]
    # Convenience alias for people lookup by EIN
    get_people_by_ein = get_people_by_organization

    def search_people(self, query: str, limit: int = 25) -> List[PersonAffiliation]:
        """Search people across all nonprofit filings by name."""
        pattern = f"%{query.upper()}%"
        rows = self.conn.execute("""
            SELECT filer_ein, filer_name, tax_year, person_name, clean_name, title,
                   role_type, hours_per_week, reportable_comp, related_org_comp, other_comp, total_comp
            FROM people
            WHERE clean_name ILIKE ? OR person_name ILIKE ?
            ORDER BY total_comp DESC, tax_year DESC
            LIMIT ?;
        """, (pattern, pattern, limit)).fetchall()
        return [
            PersonAffiliation(
                filer_ein=r[0], filer_name=r[1], tax_year=r[2], person_name=r[3],
                clean_name=r[4], title=r[5], role_type=r[6], hours_per_week=r[7],
                reportable_comp=r[8], related_org_comp=r[9], other_comp=r[10], total_comp=r[11]
            )
            for r in rows
        ]

    def get_person_interlocks(self, clean_name: str) -> List[Dict[str, Any]]:
        """
        Find all distinct organizations and roles associated with a person.
        Reveals cross-board interlocks, dual executive positions, and compensation totals.
        """
        rows = self.conn.execute("""
            SELECT filer_ein, filer_name, title, role_type, hours_per_week,
                   total_comp, min(tax_year), max(tax_year)
            FROM people
            WHERE clean_name = ?
            GROUP BY 1, 2, 3, 4, 5, 6
            ORDER BY max(tax_year) DESC, total_comp DESC;
        """, (clean_name.upper(),)).fetchall()

        return [
            {
                "filer_ein": r[0],
                "filer_name": r[1],
                "title": r[2],
                "role_type": r[3],
                "hours_per_week": r[4],
                "total_comp": r[5],
                "start_year": r[6],
                "end_year": r[7]
            }
            for r in rows
        ]

    def get_interlocking_directorates(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Discover pairs of organizations that share one or more common board members or officers.
        """
        rows = self.conn.execute("""
            SELECT p1.filer_ein as ein_a, p1.filer_name as org_a,
                   p2.filer_ein as ein_b, p2.filer_name as org_b,
                   p1.clean_name as shared_person,
                   p1.title as role_a, p2.title as role_b,
                   max(p1.tax_year) as year_a, max(p2.tax_year) as year_b
            FROM people p1
            JOIN people p2 ON p1.clean_name = p2.clean_name AND p1.filer_ein < p2.filer_ein
            GROUP BY 1, 2, 3, 4, 5, 6, 7
            ORDER BY org_a, org_b
            LIMIT ?;
        """, (limit,)).fetchall()

        return [
            {
                "ein_a": r[0],
                "org_a": r[1],
                "ein_b": r[2],
                "org_b": r[3],
                "shared_person": r[4],
                "role_a": r[5],
                "role_b": r[6],
                "year_a": r[7],
                "year_b": r[8]
            }
            for r in rows
        ]

    def search_contractors(self, query: str, limit: int = 15) -> List[Dict[str, Any]]:
        """Search independent commercial contractors across all filings."""
        pattern = f"%{query.upper()}%"
        rows = self.conn.execute("""
            SELECT contractor_name,
                   count(DISTINCT filer_ein) as client_count,
                   sum(amount) as total_amount,
                   string_agg(DISTINCT description_of_services, '; ') as services,
                   max(tax_year) as latest_year
            FROM contractors
            WHERE contractor_name ILIKE ?
            GROUP BY contractor_name
            ORDER BY total_amount DESC
            LIMIT ?;
        """, (pattern, limit)).fetchall()

        return [
            {
                "contractor_name": r[0],
                "client_count": r[1],
                "total_amount": r[2] or 0.0,
                "services": r[3] or "",
                "latest_year": r[4]
            }
            for r in rows
        ]

    def get_contractor_dossier(self, contractor_name: str) -> Optional[Dict[str, Any]]:
        """
        Aggregate full commercial contractor profile across all nonprofit filings.
        Reveals which charities hired them, for what professional services, and total payments.
        """
        clean_target = contractor_name.strip()
        rows = self.conn.execute("""
            SELECT filer_ein, filer_name, tax_year, contractor_name, city, state, description_of_services, amount
            FROM contractors
            WHERE contractor_name ILIKE ?
            ORDER BY tax_year DESC, amount DESC;
        """, (f"%{clean_target}%",)).fetchall()

        if not rows:
            return None

        primary_name = rows[0][3]
        total_amount = sum(r[7] for r in rows)
        services_set = sorted(list(set(r[6] for r in rows if r[6])))
        locations_set = sorted(list(set(f"{r[4]}, {r[5]}".strip(", ") for r in rows if r[4] or r[5])))
        years = sorted(list(set(r[2] for r in rows if r[2])))

        # Client aggregation
        client_dict: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            ein = r[0]
            if ein not in client_dict:
                client_dict[ein] = {
                    "filer_ein": ein,
                    "filer_name": r[1],
                    "total_paid": 0.0,
                    "years": [],
                    "services": set(),
                    "contracts": []
                }
            cl = client_dict[ein]
            cl["total_paid"] += r[7]
            cl["years"].append(r[2])
            if r[6]:
                cl["services"].add(r[6])
            cl["contracts"].append({
                "tax_year": r[2],
                "amount": r[7],
                "description_of_services": r[6]
            })

        clients_list = []
        for cl in sorted(client_dict.values(), key=lambda x: x["total_paid"], reverse=True):
            clients_list.append({
                "filer_ein": cl["filer_ein"],
                "filer_name": cl["filer_name"],
                "total_paid": cl["total_paid"],
                "years": sorted(list(set(cl["years"]))),
                "services": sorted(list(cl["services"])),
                "contracts": cl["contracts"]
            })

        return {
            "contractor_name": primary_name,
            "total_amount": total_amount,
            "client_count": len(clients_list),
            "services": services_set,
            "locations": locations_set,
            "min_year": min(years) if years else None,
            "max_year": max(years) if years else None,
            "clients": clients_list
        }

    def search_omni(self, query: str, limit: int = 15) -> Dict[str, List[Dict[str, Any]]]:
        """
        Unified multi-entity search across organizations, board members/officers,
        independent contractors, Schedule R corporate affiliates, and 527 political committees.
        """
        q = query.strip()
        pattern = f"%{q}%"

        # 1. Organizations
        org_rows = self.conn.execute("""
            SELECT ein, name, tax_status, city, state, total_revenue, total_assets
            FROM organizations
            WHERE name ILIKE ? OR ein LIKE ?
            ORDER BY total_revenue DESC
            LIMIT ?;
        """, (pattern, pattern, limit)).fetchall()

        orgs = [
            {
                "ein": r[0],
                "name": r[1],
                "tax_status": r[2] or "501(c)(3)",
                "city": r[3] or "",
                "state": r[4] or "",
                "revenue": r[5] or 0.0,
                "assets": r[6] or 0.0,
                "type": "organization"
            }
            for r in org_rows
        ]

        # Check BMF if local orgs are sparse
        if len(orgs) < 5:
            try:
                bmf_check = self.conn.execute(
                    "SELECT count(*) FROM information_schema.tables WHERE table_name = 'irs_bmf';"
                ).fetchone()
                if bmf_check and bmf_check[0] > 0:
                    bmf_rows = self.conn.execute("""
                        SELECT ein, name, city, state, revenue_amt, asset_amt, subsection
                        FROM irs_bmf
                        WHERE name ILIKE ? OR ein LIKE ?
                        ORDER BY revenue_amt DESC
                        LIMIT ?;
                    """, (pattern, pattern, limit)).fetchall()
                    existing_eins = set(o["ein"] for o in orgs)
                    for br in bmf_rows:
                        if br[0] not in existing_eins:
                            orgs.append({
                                "ein": br[0],
                                "name": br[1],
                                "tax_status": f"501(c)({int(br[6]) if br[6].isdigit() else br[6]})",
                                "city": br[2] or "",
                                "state": br[3] or "",
                                "revenue": br[4] or 0.0,
                                "assets": br[5] or 0.0,
                                "type": "organization"
                            })
            except Exception:
                pass

        # 2. People (Board Members / Officers / Key Employees)
        people_rows = self.conn.execute("""
            SELECT clean_name, max(person_name) as display_name,
                   count(DISTINCT filer_ein) as org_count,
                   string_agg(DISTINCT title, ', ') as titles,
                   sum(total_comp) as total_comp,
                   max(tax_year) as latest_year
            FROM people
            WHERE clean_name ILIKE ? OR person_name ILIKE ?
            GROUP BY clean_name
            ORDER BY org_count DESC, total_comp DESC
            LIMIT ?;
        """, (pattern, pattern, limit)).fetchall()

        people = [
            {
                "clean_name": r[0],
                "name": r[1],
                "org_count": r[2],
                "titles": r[3] or "",
                "total_comp": r[4] or 0.0,
                "latest_year": r[5],
                "type": "person"
            }
            for r in people_rows
        ]

        # 3. Independent Contractors & Businesses
        contractors = self.search_contractors(q, limit=limit)
        for c in contractors:
            c["type"] = "contractor"

        # 4. Schedule R Corporate Affiliates
        affiliate_rows = self.conn.execute("""
            SELECT DISTINCT entity_ein, entity_name, related_ein, related_name, relationship_type, primary_activity
            FROM relationships
            WHERE related_name ILIKE ? OR entity_name ILIKE ?
            LIMIT ?;
        """, (pattern, pattern, limit)).fetchall()

        affiliates = [
            {
                "entity_ein": r[0],
                "entity_name": r[1],
                "related_ein": r[2],
                "related_name": r[3],
                "relationship_type": r[4] or "Affiliate",
                "primary_activity": r[5] or "",
                "type": "affiliate"
            }
            for r in affiliate_rows
        ]

        # 5. IRS 527 Political Organizations (if table populated)
        pacs_527 = []
        try:
            pac_rows = self.conn.execute("""
                SELECT form_id_number, ein, org_name, city, state, form_type, purpose
                FROM irs_527_orgs
                WHERE org_name ILIKE ? OR ein LIKE ?
                LIMIT ?;
            """, (pattern, pattern, limit)).fetchall()

            pacs_527 = [
                {
                    "form_id": r[0],
                    "ein": r[1] or "",
                    "name": r[2],
                    "city": r[3] or "",
                    "state": r[4] or "",
                    "form_type": r[5] or "8871",
                    "purpose": (r[6] or "")[:120],
                    "type": "pac_527"
                }
                for r in pac_rows
            ]
        except Exception:
            pass

        # 6. FEC Federal Political Committees (Super PACs, Traditional PACs, etc.)
        fec_pacs = []
        try:
            fec_rows = self.conn.execute("""
                SELECT cmte_id, cmte_name, cmte_type, connected_org_name, treasurer_name, state, party_affiliation, cycle
                FROM fec_committees
                WHERE cmte_name ILIKE ? OR connected_org_name ILIKE ? OR cmte_id LIKE ?
                ORDER BY cycle DESC
                LIMIT ?;
            """, (pattern, pattern, pattern, limit)).fetchall()

            type_labels = {
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

            fec_pacs = [
                {
                    "cmte_id": r[0],
                    "name": r[1],
                    "cmte_type": r[2] or "",
                    "type_label": type_labels.get(r[2], f"PAC ({r[2]})"),
                    "connected_org": r[3] or "",
                    "treasurer": r[4] or "",
                    "state": r[5] or "",
                    "party": r[6] or "",
                    "cycle": r[7],
                    "type": "fec_committee"
                }
                for r in fec_rows
            ]
        except Exception:
            pass

        return {
            "organizations": orgs[:limit],
            "people": people[:limit],
            "contractors": contractors[:limit],
            "affiliates": affiliates[:limit],
            "pacs_527": pacs_527[:limit],
            "fec_pacs": fec_pacs[:limit]
        }

    # =========================================================================
    # IRS 527 Political Organizations Ingestion & Query Methods
    # =========================================================================

    def upsert_527_orgs(self, records: List[Tuple]):
        """Batch upsert Form 8871 political organizations."""
        if not records:
            return
        self.conn.executemany("""
            INSERT INTO irs_527_orgs (
                form_id_number, org_name, ein, form_type, address_1, address_2,
                city, state, zip, email, custodian_name, purpose, insert_datetime
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (form_id_number) DO UPDATE SET
                org_name = excluded.org_name,
                ein = excluded.ein,
                form_type = excluded.form_type,
                address_1 = excluded.address_1,
                city = excluded.city,
                state = excluded.state,
                zip = excluded.zip,
                email = excluded.email,
                custodian_name = excluded.custodian_name,
                purpose = excluded.purpose,
                insert_datetime = excluded.insert_datetime;
        """, records)

    def upsert_527_directors(self, records: List[Tuple]):
        """Batch upsert Form 8871 political committee directors and officers."""
        if not records:
            return
        self.conn.executemany("""
            INSERT INTO irs_527_directors (
                id, form_id_number, org_name, ein, person_name, clean_name, title, address_1, city, state, zip
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO NOTHING;
        """, records)

    def upsert_527_related(self, records: List[Tuple]):
        """Batch upsert Form 8871 related entities and connected organizations."""
        if not records:
            return
        self.conn.executemany("""
            INSERT INTO irs_527_related (
                id, form_id_number, org_name, ein, related_org_name, relationship_type, city, state
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO NOTHING;
        """, records)

    def upsert_527_reports(self, records: List[Tuple]):
        """Batch upsert Form 8872 periodic reports."""
        if not records:
            return
        self.conn.executemany("""
            INSERT INTO irs_527_reports (
                form_id_number, form_type, ein, org_name, period_begin, period_end,
                total_contributions, total_expenditures, insert_datetime
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (form_id_number) DO UPDATE SET
                total_contributions = excluded.total_contributions,
                total_expenditures = excluded.total_expenditures,
                insert_datetime = excluded.insert_datetime;
        """, records)

    def upsert_527_contributions(self, records: List[Tuple]):
        """Batch upsert Form 8872 Schedule A itemized contributions."""
        if not records:
            return
        self.conn.executemany("""
            INSERT INTO irs_527_contributions (
                id, form_id_number, sched_a_id, org_name, ein, contributor_name,
                city, state, zip, employer, occupation, amount, aggregate_ytd, contribution_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO NOTHING;
        """, records)

    def upsert_527_expenditures(self, records: List[Tuple]):
        """Batch upsert Form 8872 Schedule B itemized expenditures."""
        if not records:
            return
        self.conn.executemany("""
            INSERT INTO irs_527_expenditures (
                id, form_id_number, sched_b_id, org_name, ein, recipient_name,
                city, state, zip, employer, occupation, amount, expenditure_date, purpose
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO NOTHING;
        """, records)

    def get_527_org(self, ein_or_id: str) -> Optional[Dict[str, Any]]:
        """Fetch 527 organization profile by EIN or Form ID."""
        clean = ein_or_id.replace("-", "").strip()
        row = self.conn.execute("""
            SELECT form_id_number, org_name, ein, form_type, address_1, city, state, zip, email, custodian_name, purpose
            FROM irs_527_orgs
            WHERE ein = ? OR replace(ein, '-', '') = ? OR form_id_number = ?
            ORDER BY insert_datetime DESC
            LIMIT 1;
        """, (ein_or_id, clean, ein_or_id)).fetchone()

        if not row:
            return None

        form_id = row[0]
        ein = row[2]

        # Get directors
        directors = self.conn.execute("""
            SELECT person_name, clean_name, title, city, state
            FROM irs_527_directors
            WHERE form_id_number = ? OR ein = ?;
        """, (form_id, ein)).fetchall()

        # Get related entities
        related = self.conn.execute("""
            SELECT related_org_name, relationship_type, city, state
            FROM irs_527_related
            WHERE form_id_number = ? OR ein = ?;
        """, (form_id, ein)).fetchall()

        # Get reports summary
        reports = self.conn.execute("""
            SELECT form_id_number, period_begin, period_end, total_contributions, total_expenditures
            FROM irs_527_reports
            WHERE ein = ?
            ORDER BY period_end DESC
            LIMIT 12;
        """, (ein,)).fetchall()

        return {
            "form_id": row[0],
            "name": row[1],
            "org_name": row[1],
            "ein": row[2],
            "form_type": row[3],
            "address": row[4],
            "city": row[5],
            "state": row[6],
            "zip": row[7],
            "email": row[8],
            "custodian_name": row[9],
            "purpose": row[10],
            "directors": [
                {"name": d[0], "clean_name": d[1], "title": d[2], "city": d[3], "state": d[4]}
                for d in directors
            ],
            "related_entities": [
                {"related_name": r[0], "relationship": r[1], "city": r[2], "state": r[3]}
                for r in related
            ],
            "reports": [
                {
                    "form_id": rep[0], "begin": str(rep[1]) if rep[1] else "",
                    "end": str(rep[2]) if rep[2] else "",
                    "contributions": rep[3] or 0.0, "expenditures": rep[4] or 0.0
                }
                for rep in reports
            ]
        }

    # =========================================================================
    # FEC Political Committees & Independent Expenditures Ingestion & Queries
    # =========================================================================

    def upsert_fec_committees(self, records: List[Tuple]):
        """Batch upsert FEC committee master records."""
        if not records:
            return
        self.conn.executemany("""
            INSERT INTO fec_committees (
                cmte_id, cmte_name, treasurer_name, clean_treasurer, city, state, zip,
                cmte_designation, cmte_type, party_affiliation, org_type, connected_org_name,
                clean_connected_org, candidate_id, cycle
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (cmte_id) DO UPDATE SET
                cmte_name = EXCLUDED.cmte_name,
                treasurer_name = EXCLUDED.treasurer_name,
                clean_treasurer = EXCLUDED.clean_treasurer,
                city = EXCLUDED.city,
                state = EXCLUDED.state,
                zip = EXCLUDED.zip,
                cmte_designation = EXCLUDED.cmte_designation,
                cmte_type = EXCLUDED.cmte_type,
                party_affiliation = EXCLUDED.party_affiliation,
                org_type = EXCLUDED.org_type,
                connected_org_name = EXCLUDED.connected_org_name,
                clean_connected_org = EXCLUDED.clean_connected_org,
                candidate_id = EXCLUDED.candidate_id,
                cycle = EXCLUDED.cycle;
        """, records)

    def upsert_fec_candidates(self, records: List[Tuple]):
        """Batch upsert FEC candidate master records."""
        if not records:
            return
        self.conn.executemany("""
            INSERT INTO fec_candidates (
                candidate_id, candidate_name, clean_candidate_name, party, election_year,
                office_state, office, district, pcc_id, cycle
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (candidate_id) DO UPDATE SET
                candidate_name = EXCLUDED.candidate_name,
                clean_candidate_name = EXCLUDED.clean_candidate_name,
                party = EXCLUDED.party,
                election_year = EXCLUDED.election_year,
                office_state = EXCLUDED.office_state,
                office = EXCLUDED.office,
                district = EXCLUDED.district,
                pcc_id = EXCLUDED.pcc_id,
                cycle = EXCLUDED.cycle;
        """, records)

    def upsert_fec_linkages(self, records: List[Tuple]):
        """Batch upsert Candidate-to-Committee linkages."""
        if not records:
            return
        self.conn.executemany("""
            INSERT INTO fec_candidate_linkages (
                id, candidate_id, candidate_election_year, fec_election_year,
                cmte_id, cmte_type, cmte_designation, linkage_id, cycle
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO NOTHING;
        """, records)

    def upsert_fec_transactions(self, records: List[Tuple]):
        """Batch upsert FEC committee transactions (PAS2)."""
        if not records:
            return
        self.conn.executemany("""
            INSERT INTO fec_transactions (
                sub_id, cmte_id, transaction_type, entity_type, recipient_name,
                city, state, zip, employer, occupation, transaction_date, amount,
                other_id, memo_text, cycle
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (sub_id) DO NOTHING;
        """, records)

    def upsert_fec_operating_expenditures(self, records: List[Tuple]):
        """Batch upsert FEC operating expenditures (OPPEXP)."""
        if not records:
            return
        self.conn.executemany("""
            INSERT INTO fec_operating_expenditures (
                sub_id, cmte_id, payee_name, city, state, zip,
                transaction_date, amount, purpose, category_desc, cycle
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (sub_id) DO NOTHING;
        """, records)

    def search_fec_committees(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Search FEC committees by name, ID, or connected sponsor."""
        q = query.strip()
        pattern = f"%{q}%"
        rows = self.conn.execute("""
            SELECT cmte_id, cmte_name, cmte_type, cmte_designation, connected_org_name,
                   treasurer_name, city, state, party_affiliation, cycle
            FROM fec_committees
            WHERE cmte_name ILIKE ? OR connected_org_name ILIKE ? OR cmte_id LIKE ?
            ORDER BY cycle DESC, cmte_name ASC
            LIMIT ?;
        """, (pattern, pattern, pattern, limit)).fetchall()

        type_labels = {
            "O": "Super PAC (Independent Expenditure-Only)",
            "V": "Hybrid PAC (Non-Contribution Account)",
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

        return [
            {
                "cmte_id": r[0],
                "cmte_name": r[1],
                "name": r[1],
                "cmte_type": r[2] or "",
                "type_label": type_labels.get(r[2], f"PAC ({r[2]})"),
                "cmte_designation": r[3] or "",
                "connected_org": r[4] or "",
                "treasurer": r[5] or "",
                "city": r[6] or "",
                "state": r[7] or "",
                "party": r[8] or "",
                "cycle": r[9]
            }
            for r in rows
        ]

    def get_fec_committee(self, cmte_id_or_name: str) -> Optional[Dict[str, Any]]:
        """Fetch full FEC political committee profile with candidates, independent expenditures, and vendors."""
        clean = cmte_id_or_name.strip()
        row = self.conn.execute("""
            SELECT cmte_id, cmte_name, treasurer_name, clean_treasurer, city, state, zip,
                   cmte_designation, cmte_type, party_affiliation, org_type, connected_org_name,
                   candidate_id, cycle
            FROM fec_committees
            WHERE cmte_id = ? OR cmte_name ILIKE ?
            ORDER BY cycle DESC
            LIMIT 1;
        """, (clean, clean)).fetchone()

        if not row:
            # Fallback to substring match
            row = self.conn.execute("""
                SELECT cmte_id, cmte_name, treasurer_name, clean_treasurer, city, state, zip,
                       cmte_designation, cmte_type, party_affiliation, org_type, connected_org_name,
                       candidate_id, cycle
                FROM fec_committees
                WHERE cmte_name ILIKE ?
                ORDER BY cycle DESC
                LIMIT 1;
            """, (f"%{clean}%",)).fetchone()

        if not row:
            return None

        cmte_id = row[0]

        # Candidates linked
        cand_rows = self.conn.execute("""
            SELECT DISTINCT c.candidate_id, c.candidate_name, c.party, c.office, c.office_state, c.district
            FROM fec_candidate_linkages l
            JOIN fec_candidates c ON l.candidate_id = c.candidate_id
            WHERE l.cmte_id = ?;
        """, (cmte_id,)).fetchall()

        # Top Independent Expenditures (Supporting vs Opposing)
        # 24E = Independent Expenditure Supporting, 24A = Independent Expenditure Opposing, 24K = Direct Contribution
        tx_rows = self.conn.execute("""
            SELECT transaction_type, recipient_name, other_id, sum(amount) as total_amt, count(*) as count_tx
            FROM fec_transactions
            WHERE cmte_id = ?
            GROUP BY transaction_type, recipient_name, other_id
            ORDER BY total_amt DESC
            LIMIT 20;
        """, (cmte_id,)).fetchall()

        tx_summary = {
            "supporting": [],
            "opposing": [],
            "contributions": []
        }
        for tr in tx_rows:
            entry = {
                "recipient_name": tr[1],
                "target_id": tr[2] or "",
                "total_amount": tr[3] or 0.0,
                "count": tr[4]
            }
            if tr[0] == "24E":
                tx_summary["supporting"].append(entry)
            elif tr[0] == "24A":
                tx_summary["opposing"].append(entry)
            else:
                tx_summary["contributions"].append(entry)

        # Top Operating Expenditures / Commercial Vendors
        opp_rows = self.conn.execute("""
            SELECT payee_name, city, state, sum(amount) as total_amt, count(*) as count_tx,
                   string_agg(DISTINCT purpose, '; ') as purposes
            FROM fec_operating_expenditures
            WHERE cmte_id = ?
            GROUP BY payee_name, city, state
            ORDER BY total_amt DESC
            LIMIT 15;
        """, (cmte_id,)).fetchall()

        top_vendors = [
            {
                "payee_name": o[0],
                "city": o[1] or "",
                "state": o[2] or "",
                "total_amount": o[3] or 0.0,
                "count": o[4],
                "purposes": o[5] or ""
            }
            for o in opp_rows
        ]

        type_labels = {
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

        return {
            "cmte_id": row[0],
            "name": row[1],
            "cmte_name": row[1],
            "treasurer_name": row[2] or "",
            "clean_treasurer": row[3] or "",
            "city": row[4] or "",
            "state": row[5] or "",
            "zip": row[6] or "",
            "cmte_designation": row[7] or "",
            "cmte_type": row[8] or "",
            "type_label": type_labels.get(row[8], f"PAC ({row[8]})"),
            "party": row[9] or "",
            "org_type": row[10] or "",
            "connected_org": row[11] or "",
            "cycle": row[13],
            "candidates": [
                {
                    "candidate_id": c[0],
                    "candidate_name": c[1],
                    "party": c[2] or "",
                    "office": c[3] or "",
                    "office_state": c[4] or "",
                    "district": c[5] or ""
                }
                for c in cand_rows
            ],
            "expenditures_summary": tx_summary,
            "top_vendors": top_vendors
        }

    # =========================================================================
    # Cross-Entity Linkages Storage & Query Methods
    # =========================================================================

    def upsert_entity_linkages(self, records: List[Tuple]):
        """Batch upsert cross-entity linkages between non-profits and PACs."""
        if not records:
            return
        self.conn.executemany("""
            INSERT INTO entity_linkages (
                id, source_ein, source_name, target_type, target_id, target_name,
                link_type, confidence_score, evidence_json, description
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                source_name = EXCLUDED.source_name,
                target_name = EXCLUDED.target_name,
                confidence_score = EXCLUDED.confidence_score,
                evidence_json = EXCLUDED.evidence_json,
                description = EXCLUDED.description;
        """, records)

    def get_entity_linkages(self, ein: str) -> List[Dict[str, Any]]:
        """Retrieve all resolved PAC and 527 linkages for a given organization EIN."""
        rows = self.conn.execute("""
            SELECT id, source_ein, source_name, target_type, target_id, target_name,
                   link_type, confidence_score, evidence_json, description, created_at
            FROM entity_linkages
            WHERE source_ein = ?
            ORDER BY confidence_score DESC, target_name ASC;
        """, (clean_ein(ein),)).fetchall()

        linkages = []
        for r in rows:
            evidence = {}
            if r[8]:
                try:
                    evidence = json.loads(r[8])
                except Exception:
                    pass
            linkages.append({
                "id": r[0],
                "source_ein": r[1],
                "source_name": r[2],
                "target_type": r[3],
                "target_id": r[4],
                "target_name": r[5],
                "link_type": r[6],
                "confidence_score": r[7],
                "evidence": evidence,
                "description": r[9] or "",
                "created_at": str(r[10]) if r[10] else ""
            })
        return linkages

    def get_all_entity_linkages(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve all cross-entity linkages across the database."""
        rows = self.conn.execute("""
            SELECT id, source_ein, source_name, target_type, target_id, target_name,
                   link_type, confidence_score, evidence_json, description, created_at
            FROM entity_linkages
            ORDER BY confidence_score DESC, source_name ASC
            LIMIT ?;
        """, (limit,)).fetchall()

        linkages = []
        for r in rows:
            evidence = {}
            if r[8]:
                try:
                    evidence = json.loads(r[8])
                except Exception:
                    pass
            linkages.append({
                "id": r[0],
                "source_ein": r[1],
                "source_name": r[2],
                "target_type": r[3],
                "target_id": r[4],
                "target_name": r[5],
                "link_type": r[6],
                "confidence_score": r[7],
                "evidence": evidence,
                "description": r[9] or "",
                "created_at": str(r[10]) if r[10] else ""
            })
        return linkages
