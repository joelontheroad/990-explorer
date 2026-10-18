# SPDX-FileCopyrightText: 2026 990-Explorer Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Data models for IRS 990 Nonprofit Explorer.

Architectural Purpose:
    Defines strongly typed dataclasses representing non-profit organizations,
    grants (Schedule I / 990-PF), corporate affiliations (Schedule R),
    functional expense allocations (Part IX), compensated contractors,
    officers/trustees, and aggregated social graph network structures.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Set


@dataclass
class OrganizationNode:
    """Represents a tax-exempt or non-profit organization node in the social graph."""
    ein: str
    name: str
    tax_status: str = "Unknown"  # e.g., "501(c)(3)", "501(c)(4)", "Private Foundation"
    total_revenue: float = 0.0
    total_assets: float = 0.0
    total_expenses: float = 0.0
    city: str = ""
    state: str = ""
    address: str = ""
    zipcode: str = ""
    ntee_code: str = ""
    is_target: bool = False
    depth: int = 0
    direction: str = "target"  # "target", "upstream", "downstream", "related"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __hash__(self):
        return hash(self.ein)

    def __eq__(self, other):
        if isinstance(other, OrganizationNode):
            return self.ein == other.ein
        return False

    @property
    def is_private_foundation(self) -> bool:
        ts = (self.tax_status or "").lower()
        meta_form = str(self.metadata.get("formtype") or "").lower()
        return "private foundation" in ts or "990-pf" in ts or "990pf" in ts or meta_form in ("990pf", "2")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OrganizationNode":
        clean_data = {k: v for k, v in data.items() if k != "is_private_foundation"}
        return cls(**clean_data)


    def to_dict(self) -> Dict[str, Any]:
        return {
            "ein": self.ein,
            "name": self.name,
            "tax_status": self.tax_status,
            "is_private_foundation": self.is_private_foundation,
            "total_revenue": self.total_revenue,
            "total_assets": self.total_assets,
            "total_expenses": self.total_expenses,
            "city": self.city,
            "state": self.state,
            "address": self.address,
            "zipcode": self.zipcode,
            "ntee_code": self.ntee_code,
            "is_target": self.is_target,
            "depth": self.depth,
            "direction": self.direction,
            "metadata": self.metadata
        }



@dataclass
class FundingGrant:
    """Represents a directed grant/funding edge from a grantor organization to a recipient organization."""
    grantor_ein: str
    grantor_name: str
    recipient_ein: str
    recipient_name: str
    amount: float
    tax_year: int
    purpose: str = ""
    source_schedule: str = "Schedule I"  # "Schedule I" or "Form 990-PF Part XV"

    def key(self) -> str:
        return f"{self.grantor_ein}->{self.recipient_ein}:{self.tax_year}:{int(self.amount)}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "grantor_ein": self.grantor_ein,
            "grantor_name": self.grantor_name,
            "recipient_ein": self.recipient_ein,
            "recipient_name": self.recipient_name,
            "amount": self.amount,
            "tax_year": self.tax_year,
            "purpose": self.purpose,
            "source_schedule": self.source_schedule
        }


@dataclass
class AggregatedGrantEdge:
    """Represents an aggregated funding link between two organizations across multiple years."""
    grantor_ein: str
    grantor_name: str
    recipient_ein: str
    recipient_name: str
    total_amount: float
    grant_count: int
    years: List[int] = field(default_factory=list)
    purposes: List[str] = field(default_factory=list)
    annual_breakdown: Dict[int, float] = field(default_factory=dict)
    source_schedules: Set[str] = field(default_factory=set)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "grantor_ein": self.grantor_ein,
            "grantor_name": self.grantor_name,
            "recipient_ein": self.recipient_ein,
            "recipient_name": self.recipient_name,
            "total_amount": self.total_amount,
            "grant_count": self.grant_count,
            "years": sorted(list(set(self.years))),
            "purposes": [p for p in self.purposes if p],
            "annual_breakdown": self.annual_breakdown,
            "source_schedules": list(self.source_schedules)
        }


@dataclass
class Relationship:
    """Represents a corporate/organizational relationship edge derived from Schedule R."""
    entity_ein: str
    entity_name: str
    related_ein: str
    related_name: str
    relationship_type: str  # "Parent", "Subsidiary", "Sibling", "Disregarded Entity"
    primary_activity: str = ""
    source_schedule: str = "Schedule R"

    def key(self) -> str:
        pair = sorted([self.entity_ein, self.related_ein])
        return f"{pair[0]}<->{pair[1]}:{self.relationship_type}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_ein": self.entity_ein,
            "entity_name": self.entity_name,
            "related_ein": self.related_ein,
            "related_name": self.related_name,
            "relationship_type": self.relationship_type,
            "primary_activity": self.primary_activity,
            "source_schedule": self.source_schedule
        }


@dataclass
class NetworkGraph:
    """Complete network graph ready for analysis and visualization."""
    target_node: OrganizationNode
    nodes: Dict[str, OrganizationNode] = field(default_factory=dict)
    grant_edges: Dict[str, AggregatedGrantEdge] = field(default_factory=dict)
    relationship_edges: Dict[str, Relationship] = field(default_factory=dict)

    def add_node(self, node: OrganizationNode):
        if node.ein not in self.nodes:
            self.nodes[node.ein] = node
        else:
            # Merge fields if missing
            existing = self.nodes[node.ein]
            if not existing.name or existing.name.startswith("Unknown"):
                existing.name = node.name
            if not existing.tax_status or existing.tax_status == "Unknown":
                existing.tax_status = node.tax_status
            if not existing.city and node.city:
                existing.city = node.city
                existing.state = node.state
            if existing.total_revenue == 0.0 and node.total_revenue > 0.0:
                existing.total_revenue = node.total_revenue
            if existing.total_assets == 0.0 and node.total_assets > 0.0:
                existing.total_assets = node.total_assets

    def add_grant(self, grant: FundingGrant):
        key = f"{grant.grantor_ein}->{grant.recipient_ein}"
        if key not in self.grant_edges:
            self.grant_edges[key] = AggregatedGrantEdge(
                grantor_ein=grant.grantor_ein,
                grantor_name=grant.grantor_name,
                recipient_ein=grant.recipient_ein,
                recipient_name=grant.recipient_name,
                total_amount=grant.amount,
                grant_count=1,
                years=[grant.tax_year] if grant.tax_year else [],
                purposes=[grant.purpose] if grant.purpose else [],
                annual_breakdown={grant.tax_year: grant.amount} if grant.tax_year else {},
                source_schedules={grant.source_schedule}
            )
        else:
            edge = self.grant_edges[key]
            edge.total_amount += grant.amount
            edge.grant_count += 1
            if grant.tax_year:
                edge.years.append(grant.tax_year)
                edge.annual_breakdown[grant.tax_year] = edge.annual_breakdown.get(grant.tax_year, 0.0) + grant.amount
            if grant.purpose and grant.purpose not in edge.purposes:
                edge.purposes.append(grant.purpose)
            edge.source_schedules.add(grant.source_schedule)

    def add_relationship(self, rel: Relationship):
        key = rel.key()
        if key not in self.relationship_edges:
            self.relationship_edges[key] = rel


@dataclass
class ExpenseBreakdown:
    """Represents Form 990 Part IX Statement of Functional Expenses."""
    filer_ein: str
    filer_name: str
    tax_year: int
    total_expenses: float = 0.0
    program_services: float = 0.0        # Part IX Line 25 Col (B)
    management_general: float = 0.0      # Part IX Line 25 Col (C)
    fundraising: float = 0.0             # Part IX Line 25 Col (D)
    salaries_total: float = 0.0          # Part IX Lines 5-10
    professional_fees: float = 0.0       # Part IX Lines 11a-11g (legal, lobbying, etc.)
    office_and_it: float = 0.0           # Part IX Lines 12-14
    travel_and_conferences: float = 0.0  # Part IX Lines 17-19
    grants_paid: float = 0.0             # Part IX Lines 1-3

    @property
    def program_percentage(self) -> float:
        return (self.program_services / self.total_expenses * 100.0) if self.total_expenses > 0 else 0.0

    @property
    def admin_percentage(self) -> float:
        return (self.management_general / self.total_expenses * 100.0) if self.total_expenses > 0 else 0.0

    @property
    def fundraising_percentage(self) -> float:
        return (self.fundraising / self.total_expenses * 100.0) if self.total_expenses > 0 else 0.0

    def key(self) -> str:
        return f"{self.filer_ein}:{self.tax_year}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "filer_ein": self.filer_ein,
            "filer_name": self.filer_name,
            "tax_year": self.tax_year,
            "total_expenses": self.total_expenses,
            "program_services": self.program_services,
            "management_general": self.management_general,
            "fundraising": self.fundraising,
            "program_percentage": round(self.program_percentage, 1),
            "admin_percentage": round(self.admin_percentage, 1),
            "fundraising_percentage": round(self.fundraising_percentage, 1),
            "salaries_total": self.salaries_total,
            "professional_fees": self.professional_fees,
            "office_and_it": self.office_and_it,
            "travel_and_conferences": self.travel_and_conferences,
            "grants_paid": self.grants_paid
        }


@dataclass
class IndependentContractor:
    """Represents a top-compensated independent contractor from Part VII Section B (> $100k)."""
    filer_ein: str
    filer_name: str
    tax_year: int
    contractor_name: str
    city: str = ""
    state: str = ""
    description_of_services: str = ""
    amount: float = 0.0

    def key(self) -> str:
        clean_cname = "".join(e for e in self.contractor_name if e.isalnum()).upper()
        return f"{self.filer_ein}:{self.tax_year}:{clean_cname}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "filer_ein": self.filer_ein,
            "filer_name": self.filer_name,
            "tax_year": self.tax_year,
            "contractor_name": self.contractor_name,
            "city": self.city,
            "state": self.state,
            "description_of_services": self.description_of_services,
            "amount": self.amount
        }


@dataclass
class PersonAffiliation:
    """Represents an officer, director, trustee, or key employee from Form 990 Part VII or 990-PF Part VIII."""
    filer_ein: str
    filer_name: str
    tax_year: int
    person_name: str
    clean_name: str
    title: str = ""
    role_type: str = "Trustee"          # "Trustee/Director", "Officer", "Key Employee", "High Earner"
    hours_per_week: float = 0.0
    reportable_comp: float = 0.0        # W-2 / 1099 from filer
    related_org_comp: float = 0.0       # Comp from Schedule R related orgs
    other_comp: float = 0.0             # Retirement/health/benefits
    total_comp: float = 0.0

    def key(self) -> str:
        clean_t = "".join(e for e in self.title if e.isalnum()).upper()[:16]
        return f"{self.filer_ein}:{self.tax_year}:{self.clean_name}:{clean_t}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "filer_ein": self.filer_ein,
            "filer_name": self.filer_name,
            "tax_year": self.tax_year,
            "person_name": self.person_name,
            "clean_name": self.clean_name,
            "title": self.title,
            "role_type": self.role_type,
            "hours_per_week": self.hours_per_week,
            "reportable_comp": self.reportable_comp,
            "related_org_comp": self.related_org_comp,
            "other_comp": self.other_comp,
            "total_comp": self.total_comp
        }

