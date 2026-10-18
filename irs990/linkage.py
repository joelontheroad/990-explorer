# SPDX-FileCopyrightText: 2026 990-Explorer Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Cross-Entity Resolution and Linkage Engine.

Identifies, scores, and verifies the legal, governance, and operational bridges
connecting IRS 501(c)(3) charities and 501(c)(4) social welfare organizations to
IRS Section 527 political organizations and Federal Election Commission (FEC)
political action committees (Super PACs, Hybrid PACs, and Traditional PACs).

Bridges Discovered:
1. Connected Organizations: FEC CONNECTED_ORG_NM and Form 8871 Part IV related entities.
2. Leadership Interlocks: Shared board officers, trustees, and PAC treasurers.
3. Shared Vendors: Commercial political consultants and legal firms shared across entities.
4. Schedule R Conduits: Multi-hop sister entity pipelines (501(c)(3) -> 501(c)(4) -> PAC).
"""

import re
import json
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set, Tuple
from .parser import normalize_person_name, clean_ein

logger = logging.getLogger(__name__)


def normalize_org_name(raw_name: str) -> str:
    """Normalize organization name for cross-entity matching.

    Removes common legal entity suffixes, leading articles, and special
    characters to enable fuzzy matching between IRS returns and FEC filings.

    Args:
        raw_name: Raw organization name string.

    Returns:
        Normalized uppercase name string without punctuation or entity noise.
    """
    if not raw_name:
        return ""
    name = raw_name.upper().strip()

    # Strip leading "THE "
    if name.startswith("THE "):
        name = name[4:].strip()

    # Replace punctuation and symbols with spaces
    name = re.sub(r"[^A-Z0-9\s]", " ", name)

    # Common corporate & non-profit entity suffixes
    suffixes = [
        r"\bINCORPORATED\b", r"\bINC\b",
        r"\bCORPORATION\b", r"\bCORP\b",
        r"\bLIMITED LIABILITY COMPANY\b", r"\bLLC\b", r"\bLC\b",
        r"\bLIMITED\b", r"\bLTD\b",
        r"\bCOMPANY\b", r"\bCO\b",
        r"\bNON PROFIT\b", r"\bNONPROFIT\b", r"\bNFP\b",
        r"\bFOUNDATION\b", r"\bFNDN\b",
        r"\bACTION FUND\b", r"\bACTION\b",
        r"\bASSOCIATION\b", r"\bASSN\b",
    ]
    for suf in suffixes:
        name = re.sub(suf, " ", name)

    # Collapse multiple whitespaces
    name = re.sub(r"\s+", " ", name).strip()
    return name


@dataclass
class EntityLinkage:
    """Represents an evidence-backed bridge between a 501(c) entity and a political committee."""
    source_ein: str
    source_name: str
    target_type: str             # "fec_pac" or "irs_527"
    target_id: str               # FEC Committee ID (e.g. C00495028) or 527 Form ID / EIN
    target_name: str             # PAC / Committee Name
    link_type: str               # "connected_org", "shared_leadership", "shared_contractor", "schedule_r_conduit"
    confidence_score: float      # 0.0 to 1.0 (e.g. 1.0 = direct connected org match)
    evidence: Dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def key(self) -> str:
        """Deterministic primary key for caching and deduplication."""
        return f"{self.source_ein}:{self.target_type}:{self.target_id}:{self.link_type}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert linkage record to dictionary format."""
        return {
            "source_ein": self.source_ein,
            "source_name": self.source_name,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "target_name": self.target_name,
            "link_type": self.link_type,
            "confidence_score": round(self.confidence_score, 2),
            "evidence": self.evidence,
            "description": self.description,
        }


class LinkageResolver:
    """Discovers and resolves cross-entity connections between 501(c) nonprofits and PACs."""

    def __init__(self, storage):
        """Initialize resolver with database storage instance.

        Args:
            storage: Active IRS990Storage instance.
        """
        self.storage = storage

    def resolve_organization_linkages(self, ein: str, save_to_db: bool = True) -> List[EntityLinkage]:
        """Resolve all PAC and 527 linkages for a specific non-profit organization.

        Evaluates connected organization declarations, leadership overlaps,
        and shared vendor contracts across both the target entity and its
        Schedule R affiliated sister organizations.

        Args:
            ein: Target organization Employer Identification Number.
            save_to_db: Whether to cache discovered linkages in the database.

        Returns:
            List of scored EntityLinkage objects.
        """
        c_ein = clean_ein(ein)
        org = self.storage.get_organization(c_ein)
        if not org:
            return []

        linkages: List[EntityLinkage] = []
        seen_keys: Set[str] = set()

        # Step 1: Collect target organization names and Schedule R related entities
        # This captures the classic 501(c)(3) -> 501(c)(4) -> PAC pipeline
        entities_to_check: List[Tuple[str, str, str]] = [
            (c_ein, org.name, "Direct Target")
        ]
        rels = self.storage.get_relationships(c_ein)
        for r in rels:
            other_ein = r.related_ein if r.entity_ein == c_ein else r.entity_ein
            other_name = r.related_name if r.entity_ein == c_ein else r.entity_name
            if other_ein and other_name:
                entities_to_check.append((other_ein, other_name, f"Schedule R {r.relationship_type}"))

        # Step 2: Bridge 1 - Connected Organizations in FEC
        self._resolve_fec_connected_orgs(entities_to_check, linkages, seen_keys)

        # Step 3: Bridge 1 - Related Organizations in IRS 527 POFD
        self._resolve_527_related_orgs(entities_to_check, linkages, seen_keys)

        # Step 4: Bridge 2 - Leadership Overlaps (FEC Treasurers & 527 Officers)
        self._resolve_leadership_interlocks(c_ein, org.name, linkages, seen_keys)

        # Step 5: Bridge 3 - Shared Commercial Political Vendors & Consultants
        self._resolve_shared_contractors(c_ein, org.name, linkages, seen_keys)

        # Sort linkages by confidence score descending
        linkages.sort(key=lambda l: l.confidence_score, reverse=True)

        # Optional caching to storage
        if save_to_db and linkages:
            self._save_linkages_to_storage(linkages)

        return linkages

    def _resolve_fec_connected_orgs(
        self,
        entities: List[Tuple[str, str, str]],
        linkages: List[EntityLinkage],
        seen_keys: Set[str]
    ):
        """Match organization and affiliate names against FEC connected organization filings."""
        for ent_ein, ent_name, relation_role in entities:
            norm_name = normalize_org_name(ent_name)
            if len(norm_name) < 4:
                continue

            # Query FEC committees whose connected_org_name matches this entity
            # We check both exact clean match and SQL ILIKE substring
            cur = self.storage.conn.cursor()
            rows = cur.execute("""
                SELECT cmte_id, cmte_name, cmte_type, connected_org_name, treasurer_name
                FROM fec_committees
                WHERE clean_connected_org = ?
                   OR connected_org_name ILIKE ?
                   OR clean_connected_org ILIKE ?
                LIMIT 50;
            """, (norm_name, f"%{ent_name}%", f"%{norm_name}%")).fetchall()

            for r in rows:
                cmte_id, cmte_name, cmte_type, conn_name, tres_name = r
                is_direct = (relation_role == "Direct Target")
                confidence = 0.95 if is_direct else 0.88
                link_type = "connected_org" if is_direct else "schedule_r_conduit"

                desc = (
                    f"Official Connected Organization: {cmte_name} registered '{conn_name}' "
                    f"as its sponsoring organization with the FEC."
                ) if is_direct else (
                    f"Conduit Bridge via {relation_role}: {cmte_name} lists '{conn_name}' "
                    f"as its connected sponsor in FEC filings."
                )

                link = EntityLinkage(
                    source_ein=entities[0][0],  # Always root to target EIN
                    source_name=entities[0][1],
                    target_type="fec_pac",
                    target_id=cmte_id,
                    target_name=cmte_name,
                    link_type=link_type,
                    confidence_score=confidence,
                    evidence={
                        "fec_committee_id": cmte_id,
                        "fec_committee_type": cmte_type,
                        "connected_org_filed": conn_name,
                        "matched_entity": ent_name,
                        "relation_role": relation_role,
                        "treasurer": tres_name,
                    },
                    description=desc,
                )
                if link.key() not in seen_keys:
                    seen_keys.add(link.key())
                    linkages.append(link)

    def _resolve_527_related_orgs(
        self,
        entities: List[Tuple[str, str, str]],
        linkages: List[EntityLinkage],
        seen_keys: Set[str]
    ):
        """Match organization and affiliate names against Form 8871 Part IV related entity records."""
        for ent_ein, ent_name, relation_role in entities:
            norm_name = normalize_org_name(ent_name)
            if len(norm_name) < 4:
                continue

            cur = self.storage.conn.cursor()
            rows = cur.execute("""
                SELECT r.form_id_number, r.org_name, r.relationship_type, r.ein, o.org_name
                FROM irs_527_related r
                LEFT JOIN irs_527_orgs o ON r.form_id_number = o.form_id_number
                WHERE r.ein = ?
                   OR r.related_org_name ILIKE ?
                LIMIT 50;
            """, (ent_ein, f"%{ent_name}%")).fetchall()

            for row in rows:
                form_id, pac_name, rel_type, rel_ein, canonical_pac_name = row
                final_pac_name = canonical_pac_name or pac_name or f"527 Org Form #{form_id}"
                is_direct = (relation_role == "Direct Target")
                confidence = 0.95 if is_direct else 0.88
                link_type = "connected_org" if is_direct else "schedule_r_conduit"

                desc = (
                    f"Form 8871 Related Organization: {final_pac_name} disclosed '{ent_name}' "
                    f"as a related entity ({rel_type}) in its IRS Section 527 registration."
                )

                link = EntityLinkage(
                    source_ein=entities[0][0],
                    source_name=entities[0][1],
                    target_type="irs_527",
                    target_id=form_id,
                    target_name=final_pac_name,
                    link_type=link_type,
                    confidence_score=confidence,
                    evidence={
                        "form_id_number": form_id,
                        "relationship_type": rel_type,
                        "matched_entity": ent_name,
                        "relation_role": relation_role,
                    },
                    description=desc,
                )
                if link.key() not in seen_keys:
                    seen_keys.add(link.key())
                    linkages.append(link)

    def _resolve_leadership_interlocks(
        self,
        target_ein: str,
        target_name: str,
        linkages: List[EntityLinkage],
        seen_keys: Set[str]
    ):
        """Cross-reference organization officers against FEC treasurers and 527 directors."""
        people = self.storage.get_people_by_ein(target_ein)
        if not people:
            return

        cur = self.storage.conn.cursor()
        for p in people:
            clean_name = p.clean_name
            if not clean_name or len(clean_name) < 4:
                continue

            # Check FEC committee treasurers
            fec_rows = cur.execute("""
                SELECT cmte_id, cmte_name, cmte_type, treasurer_name
                FROM fec_committees
                WHERE clean_treasurer = ?
                LIMIT 20;
            """, (clean_name,)).fetchall()

            for fr in fec_rows:
                cmte_id, cmte_name, cmte_type, tres_name = fr
                desc = (
                    f"Leadership Overlap: {p.person_name} ({p.title} at {target_name}) "
                    f"serves as Treasurer of federal committee '{cmte_name}'."
                )
                link = EntityLinkage(
                    source_ein=target_ein,
                    source_name=target_name,
                    target_type="fec_pac",
                    target_id=cmte_id,
                    target_name=cmte_name,
                    link_type="shared_leadership",
                    confidence_score=0.85,
                    evidence={
                        "shared_person": p.person_name,
                        "clean_name": p.clean_name,
                        "nonprofit_title": p.title,
                        "nonprofit_role": p.role_type,
                        "pac_role": "Treasurer",
                        "fec_committee_type": cmte_type,
                    },
                    description=desc,
                )
                if link.key() not in seen_keys:
                    seen_keys.add(link.key())
                    linkages.append(link)

            # Check IRS 527 directors and officers
            sec527_rows = cur.execute("""
                SELECT d.form_id_number, d.org_name, d.title, d.person_name, o.org_name
                FROM irs_527_directors d
                LEFT JOIN irs_527_orgs o ON d.form_id_number = o.form_id_number
                WHERE d.clean_name = ?
                LIMIT 20;
            """, (clean_name,)).fetchall()

            for sr in sec527_rows:
                form_id, raw_org_name, s_title, s_person, canon_name = sr
                pac_name = canon_name or raw_org_name or f"527 Org #{form_id}"
                desc = (
                    f"Leadership Overlap: {p.person_name} ({p.title} at {target_name}) "
                    f"serves as {s_title or 'Director'} of 527 political org '{pac_name}'."
                )
                link = EntityLinkage(
                    source_ein=target_ein,
                    source_name=target_name,
                    target_type="irs_527",
                    target_id=form_id,
                    target_name=pac_name,
                    link_type="shared_leadership",
                    confidence_score=0.85,
                    evidence={
                        "shared_person": p.person_name,
                        "clean_name": p.clean_name,
                        "nonprofit_title": p.title,
                        "pac_title": s_title,
                        "form_id_number": form_id,
                    },
                    description=desc,
                )
                if link.key() not in seen_keys:
                    seen_keys.add(link.key())
                    linkages.append(link)

    def _resolve_shared_contractors(
        self,
        target_ein: str,
        target_name: str,
        linkages: List[EntityLinkage],
        seen_keys: Set[str]
    ):
        """Cross-reference independent commercial contractors against political disbursements."""
        contractors = self.storage.get_contractors_by_ein(target_ein)
        if not contractors:
            return

        cur = self.storage.conn.cursor()
        for c in contractors:
            raw_cname = c.contractor_name
            norm_cname = normalize_org_name(raw_cname)
            if len(norm_cname) < 4:
                continue

            # Check FEC operating expenditures paid to this vendor
            fec_exp_rows = cur.execute("""
                SELECT e.cmte_id, c.cmte_name, sum(e.amount) as total_disbursed, count(*) as tx_count, max(e.purpose)
                FROM fec_operating_expenditures e
                JOIN fec_committees c ON e.cmte_id = c.cmte_id
                WHERE e.payee_name ILIKE ?
                GROUP BY e.cmte_id, c.cmte_name
                HAVING sum(e.amount) >= 10000.0
                ORDER BY total_disbursed DESC
                LIMIT 10;
            """, (f"%{raw_cname}%",)).fetchall()

            for fe in fec_exp_rows:
                cmte_id, cmte_name, total_paid, tx_count, sample_purpose = fe
                desc = (
                    f"Shared Commercial Vendor: '{raw_cname}' received ${c.amount:,.0f} from {target_name} "
                    f"({c.description_of_services}) and ${total_paid:,.0f} across {tx_count} disbursement(s) "
                    f"from federal committee '{cmte_name}'."
                )
                link = EntityLinkage(
                    source_ein=target_ein,
                    source_name=target_name,
                    target_type="fec_pac",
                    target_id=cmte_id,
                    target_name=cmte_name,
                    link_type="shared_contractor",
                    confidence_score=0.75,
                    evidence={
                        "contractor_name": raw_cname,
                        "nonprofit_services": c.description_of_services,
                        "nonprofit_billing": c.amount,
                        "pac_disbursement_total": total_paid,
                        "pac_transaction_count": tx_count,
                        "pac_purpose_sample": sample_purpose,
                    },
                    description=desc,
                )
                if link.key() not in seen_keys:
                    seen_keys.add(link.key())
                    linkages.append(link)

            # Check IRS 527 expenditures paid to this vendor
            sec527_exp_rows = cur.execute("""
                SELECT e.form_id_number, e.org_name, sum(e.amount) as total_disbursed, count(*) as tx_count, max(e.purpose)
                FROM irs_527_expenditures e
                WHERE e.recipient_name ILIKE ?
                GROUP BY e.form_id_number, e.org_name
                HAVING sum(e.amount) >= 5000.0
                ORDER BY total_disbursed DESC
                LIMIT 10;
            """, (f"%{raw_cname}%",)).fetchall()

            for se in sec527_exp_rows:
                form_id, pac_name, total_paid, tx_count, sample_purpose = se
                desc = (
                    f"Shared Commercial Vendor: '{raw_cname}' received ${c.amount:,.0f} from {target_name} "
                    f"and ${total_paid:,.0f} from 527 committee '{pac_name}'."
                )
                link = EntityLinkage(
                    source_ein=target_ein,
                    source_name=target_name,
                    target_type="irs_527",
                    target_id=form_id,
                    target_name=pac_name,
                    link_type="shared_contractor",
                    confidence_score=0.75,
                    evidence={
                        "contractor_name": raw_cname,
                        "nonprofit_services": c.description_of_services,
                        "nonprofit_billing": c.amount,
                        "pac_disbursement_total": total_paid,
                        "pac_purpose_sample": sample_purpose,
                    },
                    description=desc,
                )
                if link.key() not in seen_keys:
                    seen_keys.add(link.key())
                    linkages.append(link)

    def _save_linkages_to_storage(self, linkages: List[EntityLinkage]):
        """Persist linkages in the database entity_linkages table."""
        records = [
            (
                l.key(),
                l.source_ein,
                l.source_name,
                l.target_type,
                l.target_id,
                l.target_name,
                l.link_type,
                l.confidence_score,
                json.dumps(l.evidence),
                l.description,
            )
            for l in linkages
        ]
        self.storage.upsert_entity_linkages(records)

    def resolve_all_database_linkages(self, limit: int = 500, save_to_db: bool = True) -> List[EntityLinkage]:
        """Perform a database-wide scan across all non-profits to discover charity-to-PAC linkages.

        Executes optimized SQL joins across people, contractors, FEC committees,
        and 527 registrations.

        Args:
            limit: Maximum number of linkages to return.
            save_to_db: Whether to cache discovered linkages in the database.

        Returns:
            List of detected EntityLinkage records.
        """
        linkages: List[EntityLinkage] = []
        seen_keys: Set[str] = set()
        cur = self.storage.conn.cursor()

        # 1. Connected Organizations: FEC committees with clean_connected_org matching non-profits
        fec_conn_rows = cur.execute("""
            SELECT o.ein, o.name, c.cmte_id, c.cmte_name, c.connected_org_name, c.cmte_type
            FROM fec_committees c
            JOIN organizations o ON c.clean_connected_org = o.name
               OR c.connected_org_name ILIKE ('%' || o.name || '%')
            WHERE length(c.clean_connected_org) >= 4
            LIMIT ?;
        """, (limit,)).fetchall()

        for r in fec_conn_rows:
            ein, org_name, cmte_id, cmte_name, conn_filed, cmte_type = r
            link = EntityLinkage(
                source_ein=ein,
                source_name=org_name,
                target_type="fec_pac",
                target_id=cmte_id,
                target_name=cmte_name,
                link_type="connected_org",
                confidence_score=0.95,
                evidence={
                    "fec_committee_id": cmte_id,
                    "fec_committee_type": cmte_type,
                    "connected_org_filed": conn_filed,
                },
                description=f"Official Connected Sponsor: {cmte_name} is sponsored by {org_name} (FEC filing: '{conn_filed}').",
            )
            if link.key() not in seen_keys:
                seen_keys.add(link.key())
                linkages.append(link)

        # 2. Leadership Interlocks: Non-profit officers who are FEC treasurers
        fec_tres_rows = cur.execute("""
            SELECT p.filer_ein, p.filer_name, p.person_name, p.clean_name, p.title,
                   c.cmte_id, c.cmte_name, c.cmte_type
            FROM people p
            JOIN fec_committees c ON p.clean_name = c.clean_treasurer
            WHERE length(p.clean_name) >= 4
            LIMIT ?;
        """, (limit,)).fetchall()

        for r in fec_tres_rows:
            ein, org_name, p_name, clean_name, p_title, cmte_id, cmte_name, cmte_type = r
            link = EntityLinkage(
                source_ein=ein,
                source_name=org_name,
                target_type="fec_pac",
                target_id=cmte_id,
                target_name=cmte_name,
                link_type="shared_leadership",
                confidence_score=0.85,
                evidence={
                    "shared_person": p_name,
                    "clean_name": clean_name,
                    "nonprofit_title": p_title,
                    "pac_role": "Treasurer",
                    "fec_committee_type": cmte_type,
                },
                description=f"Leadership Overlap: {p_name} ({p_title} at {org_name}) is Treasurer of federal PAC '{cmte_name}'.",
            )
            if link.key() not in seen_keys:
                seen_keys.add(link.key())
                linkages.append(link)

        # 3. Leadership Interlocks: Non-profit officers who are 527 directors/officers
        sec527_dir_rows = cur.execute("""
            SELECT p.filer_ein, p.filer_name, p.person_name, p.clean_name, p.title,
                   d.form_id_number, d.org_name, d.title as dir_title
            FROM people p
            JOIN irs_527_directors d ON p.clean_name = d.clean_name
            WHERE length(p.clean_name) >= 4
            LIMIT ?;
        """, (limit,)).fetchall()

        for r in sec527_dir_rows:
            ein, org_name, p_name, clean_name, p_title, form_id, pac_name, dir_title = r
            link = EntityLinkage(
                source_ein=ein,
                source_name=org_name,
                target_type="irs_527",
                target_id=form_id,
                target_name=pac_name,
                link_type="shared_leadership",
                confidence_score=0.85,
                evidence={
                    "shared_person": p_name,
                    "clean_name": clean_name,
                    "nonprofit_title": p_title,
                    "pac_title": dir_title,
                    "form_id_number": form_id,
                },
                description=f"Leadership Overlap: {p_name} ({p_title} at {org_name}) is {dir_title or 'Officer'} of 527 org '{pac_name}'.",
            )
            if link.key() not in seen_keys:
                seen_keys.add(link.key())
                linkages.append(link)

        # 4. Connected Organizations: Form 8871 Part IV related entities
        sec527_rel_rows = cur.execute("""
            SELECT o.ein, o.name, r.form_id_number, r.org_name, r.relationship_type
            FROM irs_527_related r
            JOIN organizations o ON r.ein = o.ein OR r.related_org_name ILIKE ('%' || o.name || '%')
            LIMIT ?;
        """, (limit,)).fetchall()

        for r in sec527_rel_rows:
            ein, org_name, form_id, pac_name, rel_type = r
            link = EntityLinkage(
                source_ein=ein,
                source_name=org_name,
                target_type="irs_527",
                target_id=form_id,
                target_name=pac_name,
                link_type="connected_org",
                confidence_score=0.95,
                evidence={
                    "form_id_number": form_id,
                    "relationship_type": rel_type,
                },
                description=f"Form 8871 Related Entity: {pac_name} registered {org_name} as a related entity ({rel_type}).",
            )
            if link.key() not in seen_keys:
                seen_keys.add(link.key())
                linkages.append(link)

        linkages.sort(key=lambda l: l.confidence_score, reverse=True)

        if save_to_db and linkages:
            self._save_linkages_to_storage(linkages)

        return linkages[:limit]
