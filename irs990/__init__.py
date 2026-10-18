# SPDX-FileCopyrightText: 2026 990-Explorer Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""IRS 990 Ultimate Funding & Social Graph Explorer Package.

Architectural Purpose:
    Core package exposing public domain models for nonprofit organizations,
    grant funding flows, and relational cross-linkages.
"""

__version__ = "1.0.0"

from .models import OrganizationNode, FundingGrant, Relationship

__all__ = ["__version__", "OrganizationNode", "FundingGrant", "Relationship"]

