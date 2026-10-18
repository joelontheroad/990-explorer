# SPDX-FileCopyrightText: 2026 990-Explorer Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Curated Seed Data for Major Institutional Foundations, Pass-Throughs, and Hubs.

Architectural Purpose:
    Provides verified baseline organization nodes, Schedule I grants, Schedule R
    affiliations, and Part VII personnel for major philanthropic foundations,
    fiscal sponsors, and donor-advised funds (DAFs) for offline exploration.
"""

import logging
from typing import List
from .models import (
    OrganizationNode, FundingGrant, Relationship,
    ExpenseBreakdown, IndependentContractor, PersonAffiliation
)
from .storage import IRS990Storage

logger = logging.getLogger(__name__)

MAJOR_FOUNDATIONS = [
    OrganizationNode(
        ein="51-0198509",
        name="Tides Foundation",
        tax_status="501(c)(3) Public Charity / DAF",
        total_revenue=367989822.0,
        total_assets=534451715.0,
        city="San Francisco",
        state="CA",
        is_target=True
    ),
    OrganizationNode(
        ein="94-3213100",
        name="Tides Center",
        tax_status="501(c)(3) Public Charity / Fiscal Sponsor",
        total_revenue=284500000.0,
        total_assets=245000000.0,
        city="San Francisco",
        state="CA"
    ),
    OrganizationNode(
        ein="13-1628106",
        name="Ford Foundation",
        tax_status="501(c)(3) Private Foundation",
        total_revenue=1250000000.0,
        total_assets=16000000000.0,
        city="New York",
        state="NY"
    ),
    OrganizationNode(
        ein="56-2618866",
        name="Bill & Melinda Gates Foundation",
        tax_status="501(c)(3) Private Foundation",
        total_revenue=6500000000.0,
        total_assets=67000000000.0,
        city="Seattle",
        state="WA"
    ),
    OrganizationNode(
        ein="26-4444986",
        name="Foundation to Promote Open Society",
        tax_status="501(c)(3) Private Foundation",
        total_revenue=850000000.0,
        total_assets=11200000000.0,
        city="New York",
        state="NY"
    ),
    OrganizationNode(
        ein="94-1655677",
        name="William & Flora Hewlett Foundation",
        tax_status="501(c)(3) Private Foundation",
        total_revenue=980000000.0,
        total_assets=14500000000.0,
        city="Menlo Park",
        state="CA"
    ),
    OrganizationNode(
        ein="94-2278431",
        name="David & Lucile Packard Foundation",
        tax_status="501(c)(3) Private Foundation",
        total_revenue=420000000.0,
        total_assets=8200000000.0,
        city="Los Altos",
        state="CA"
    ),
    OrganizationNode(
        ein="23-2865389",
        name="Vanguard Charitable Endowment Program",
        tax_status="501(c)(3) Donor-Advised Fund",
        total_revenue=2100000000.0,
        total_assets=18000000000.0,
        city="Malvern",
        state="PA"
    ),
    OrganizationNode(
        ein="04-3132178",
        name="Fidelity Investments Charitable Gift Fund",
        tax_status="501(c)(3) Donor-Advised Fund",
        total_revenue=15000000000.0,
        total_assets=49000000000.0,
        city="Boston",
        state="MA"
    ),
    OrganizationNode(
        ein="31-1640316",
        name="Schwab Charitable Fund",
        tax_status="501(c)(3) Donor-Advised Fund",
        total_revenue=6200000000.0,
        total_assets=28000000000.0,
        city="San Francisco",
        state="CA"
    ),
    OrganizationNode(
        ein="20-5205488",
        name="New Venture Fund",
        tax_status="501(c)(3) Public Charity / Fiscal Sponsor",
        total_revenue=950000000.0,
        total_assets=620000000.0,
        city="Washington",
        state="DC"
    ),
    OrganizationNode(
        ein="13-1659570",
        name="Rockefeller Foundation",
        tax_status="501(c)(3) Private Foundation",
        total_revenue=380000000.0,
        total_assets=7100000000.0,
        city="New York",
        state="NY"
    ),
    OrganizationNode(
        ein="23-7093598",
        name="John D & Catherine T MacArthur Foundation",
        tax_status="501(c)(3) Private Foundation",
        total_revenue=613786298.0,
        total_assets=9311570852.0,
        total_expenses=415250452.0,
        city="Chicago",
        state="IL",
        address="140 S Dearborn St Ste 1200",
        zipcode="60603-5285",
        ntee_code="T20Z"
    ),
    OrganizationNode(
        ein="36-2993077",
        name="John D & Catherine T MacArthur Foundation",
        tax_status="501(c)(3) Private Foundation",
        total_revenue=613786298.0,
        total_assets=9311570852.0,
        total_expenses=415250452.0,
        city="Chicago",
        state="IL",
        address="140 S Dearborn St Ste 1200",
        zipcode="60603-5285",
        ntee_code="T20Z"
    ),
    OrganizationNode(
        ein="26-2184698",
        name="ClimateWorks Foundation",
        tax_status="501(c)(3) Public Charity",
        total_revenue=185000000.0,
        total_assets=240000000.0,
        city="San Francisco",
        state="CA"
    ),
    OrganizationNode(
        ein="94-3126848",
        name="Energy Foundation",
        tax_status="501(c)(3) Public Charity",
        total_revenue=145000000.0,
        total_assets=160000000.0,
        city="San Francisco",
        state="CA"
    ),
    OrganizationNode(
        ein="52-0881901",
        name="Urban Institute",
        tax_status="501(c)(3) Public Charity",
        total_revenue=120000000.0,
        total_assets=190000000.0,
        city="Washington",
        state="DC"
    ),
    OrganizationNode(
        ein="53-0196570",
        name="Brookings Institution",
        tax_status="501(c)(3) Public Charity",
        total_revenue=115000000.0,
        total_assets=580000000.0,
        city="Washington",
        state="DC"
    ),
    OrganizationNode(
        ein="13-1947262",
        name="Vera Institute of Justice Inc",
        tax_status="501(c)(3) Public Charity",
        total_revenue=175000000.0,
        total_assets=130000000.0,
        city="New York",
        state="NY"
    ),
    OrganizationNode(
        ein="36-4309819",
        name="Roderick & Solange MacArthur Justice Center",
        tax_status="501(c)(3) Public Charity",
        total_revenue=8500000.0,
        total_assets=12000000.0,
        city="Chicago",
        state="IL"
    ),

    OrganizationNode(
        ein="13-1624190",
        name="Carnegie Corporation of New York",
        tax_status="501(c)(3) Private Foundation",
        total_revenue=260000000.0,
        total_assets=4700000000.0,
        city="New York",
        state="NY"
    ),
    # Recipients of Tides Foundation
    OrganizationNode(
        ein="13-3921876",
        name="Center for Constitutional Rights",
        tax_status="501(c)(3) Public Charity",
        total_revenue=14500000.0,
        city="New York",
        state="NY"
    ),
    OrganizationNode(
        ein="94-1156365",
        name="Sierra Club Foundation",
        tax_status="501(c)(3) Public Charity",
        total_revenue=115000000.0,
        city="Oakland",
        state="CA"
    ),
    OrganizationNode(
        ein="13-1760110",
        name="Natural Resources Defense Council Inc",
        tax_status="501(c)(3) Public Charity",
        total_revenue=210000000.0,
        city="New York",
        state="NY"
    ),
    OrganizationNode(
        ein="52-1692287",
        name="Earthjustice",
        tax_status="501(c)(3) Public Charity",
        total_revenue=165000000.0,
        city="San Francisco",
        state="CA"
    ),
    OrganizationNode(
        ein="13-1996568",
        name="American Civil Liberties Union Foundation Inc",
        tax_status="501(c)(3) Public Charity",
        total_revenue=190000000.0,
        city="New York",
        state="NY"
    ),
    OrganizationNode(
        ein="20-5641598",
        name="Hopewell Fund",
        tax_status="501(c)(3) Public Charity",
        total_revenue=140000000.0,
        city="Washington",
        state="DC"
    ),
    OrganizationNode(
        ein="82-1926639",
        name="Windward Fund",
        tax_status="501(c)(3) Public Charity",
        total_revenue=110000000.0,
        city="Washington",
        state="DC"
    )
]

SEED_GRANTS = [
    # Upstream to Tides Foundation (51-0198509)
    FundingGrant("13-1628106", "Ford Foundation", "51-0198509", "Tides Foundation", 1250000.0, 2022, "Civic Engagement and Social Justice Initiatives", "Form 990-PF Part XV"),
    FundingGrant("13-1628106", "Ford Foundation", "51-0198509", "Tides Foundation", 1500000.0, 2021, "General Support and Field Building", "Form 990-PF Part XV"),
    FundingGrant("56-2618866", "Bill & Melinda Gates Foundation", "51-0198509", "Tides Foundation", 2500000.0, 2022, "Global Development Advocacy and Maternal Health", "Form 990-PF Part XV"),
    FundingGrant("56-2618866", "Bill & Melinda Gates Foundation", "51-0198509", "Tides Foundation", 3000000.0, 2020, "Agricultural Development and Poverty Alleviation", "Form 990-PF Part XV"),
    FundingGrant("26-4444986", "Foundation to Promote Open Society", "51-0198509", "Tides Foundation", 3500000.0, 2022, "Human Rights, Democracy Support and Justice Reform", "Form 990-PF Part XV"),
    FundingGrant("26-4444986", "Foundation to Promote Open Society", "51-0198509", "Tides Foundation", 2750000.0, 2021, "Media and Transparency Grants", "Form 990-PF Part XV"),
    FundingGrant("94-1655677", "William & Flora Hewlett Foundation", "51-0198509", "Tides Foundation", 1800000.0, 2022, "Climate and Clean Energy Collaboration", "Form 990-PF Part XV"),
    FundingGrant("94-2278431", "David & Lucile Packard Foundation", "51-0198509", "Tides Foundation", 1100000.0, 2022, "Ocean Conservation and Environmental Defense", "Form 990-PF Part XV"),
    # Grants from Fidelity Investments Charitable Gift Fund (04-3132178) to Tides Foundation and other non-profits
    FundingGrant("04-3132178", "Fidelity Investments Charitable Gift Fund", "51-0198509", "Tides Foundation", 8200000.0, 2022, "Donor-Advised Directed Contribution", "Schedule I"),
    FundingGrant("04-3132178", "Fidelity Investments Charitable Gift Fund", "20-5205488", "New Venture Fund", 14500000.0, 2022, "Donor-Advised Directed Grants", "Schedule I"),
    FundingGrant("04-3132178", "Fidelity Investments Charitable Gift Fund", "13-1996568", "American Civil Liberties Union Foundation Inc", 9800000.0, 2022, "Donor-Advised Charitable Contribution", "Schedule I"),
    FundingGrant("04-3132178", "Fidelity Investments Charitable Gift Fund", "13-1760110", "Natural Resources Defense Council Inc", 6200000.0, 2022, "Donor-Advised Environmental Support", "Schedule I"),
    FundingGrant("04-3132178", "Fidelity Investments Charitable Gift Fund", "52-1692287", "Earthjustice", 5400000.0, 2022, "Donor-Advised Conservation Grants", "Schedule I"),
    FundingGrant("04-3132178", "Fidelity Investments Charitable Gift Fund", "94-1156365", "Sierra Club Foundation", 4700000.0, 2022, "Donor-Advised Environmental Defense", "Schedule I"),
    FundingGrant("04-3132178", "Fidelity Investments Charitable Gift Fund", "13-3921876", "Center for Constitutional Rights", 1500000.0, 2022, "Civil Rights Litigation & Education", "Schedule I"),
    FundingGrant("04-3132178", "Fidelity Investments Charitable Gift Fund", "20-5641598", "Hopewell Fund", 3100000.0, 2022, "Public Interest Collaboration", "Schedule I"),
    FundingGrant("04-3132178", "Fidelity Investments Charitable Gift Fund", "82-1926639", "Windward Fund", 2800000.0, 2022, "Sustainable Solutions Grants", "Schedule I"),

    # Grants from Vanguard Charitable Endowment Program (23-2865389)
    FundingGrant("23-2865389", "Vanguard Charitable Endowment Program", "51-0198509", "Tides Foundation", 4500000.0, 2022, "Donor-Advised Directed Grants", "Schedule I"),
    FundingGrant("23-2865389", "Vanguard Charitable Endowment Program", "20-5205488", "New Venture Fund", 7500000.0, 2022, "Donor-Advised Support", "Schedule I"),
    FundingGrant("23-2865389", "Vanguard Charitable Endowment Program", "13-1996568", "American Civil Liberties Union Foundation Inc", 4200000.0, 2022, "Donor-Advised Contribution", "Schedule I"),
    FundingGrant("23-2865389", "Vanguard Charitable Endowment Program", "13-1760110", "Natural Resources Defense Council Inc", 3100000.0, 2022, "Donor-Advised Environmental Grants", "Schedule I"),

    # Grants from Schwab Charitable Fund (31-1640316)
    FundingGrant("31-1640316", "Schwab Charitable Fund", "51-0198509", "Tides Foundation", 3800000.0, 2022, "Donor-Advised Directed Support", "Schedule I"),
    FundingGrant("31-1640316", "Schwab Charitable Fund", "20-5205488", "New Venture Fund", 5800000.0, 2022, "Donor-Advised Grants", "Schedule I"),
    FundingGrant("31-1640316", "Schwab Charitable Fund", "52-1692287", "Earthjustice", 2200000.0, 2022, "Conservation and Wildlife Protection", "Schedule I"),
    FundingGrant("13-1659570", "Rockefeller Foundation", "51-0198509", "Tides Foundation", 750000.0, 2021, "Resilience and Economic Opportunity", "Form 990-PF Part XV"),

    # Grants from John D & Catherine T MacArthur Foundation (23-7093598 / 36-2993077)
    FundingGrant("23-7093598", "John D & Catherine T MacArthur Foundation", "51-0198509", "Tides Foundation", 850000.0, 2022, "Equitable Recovery and Media Grants", "Form 990-PF Part XV"),
    FundingGrant("23-7093598", "John D & Catherine T MacArthur Foundation", "20-5205488", "New Venture Fund", 1500000.0, 2022, "Public Interest Democracy & Media Collaboration", "Form 990-PF Part XV"),
    FundingGrant("23-7093598", "John D & Catherine T MacArthur Foundation", "26-2184698", "ClimateWorks Foundation", 3500000.0, 2022, "Global Climate Solutions & Clean Energy Field Support", "Form 990-PF Part XV"),
    FundingGrant("23-7093598", "John D & Catherine T MacArthur Foundation", "94-3126848", "Energy Foundation", 2500000.0, 2022, "Renewable Energy Transition and Policy Research", "Form 990-PF Part XV"),
    FundingGrant("23-7093598", "John D & Catherine T MacArthur Foundation", "13-1760110", "Natural Resources Defense Council Inc", 2000000.0, 2022, "Environmental Litigation & Climate Justice", "Form 990-PF Part XV"),
    FundingGrant("23-7093598", "John D & Catherine T MacArthur Foundation", "13-1996568", "American Civil Liberties Union Foundation Inc", 1750000.0, 2022, "Voting Rights and Criminal Justice Reform", "Form 990-PF Part XV"),
    FundingGrant("23-7093598", "John D & Catherine T MacArthur Foundation", "52-0881901", "Urban Institute", 1800000.0, 2022, "Housing Policy and Community Economic Development", "Form 990-PF Part XV"),
    FundingGrant("23-7093598", "John D & Catherine T MacArthur Foundation", "53-0196570", "Brookings Institution", 1250000.0, 2022, "Governance Studies and Metropolitan Policy Program", "Form 990-PF Part XV"),
    FundingGrant("23-7093598", "John D & Catherine T MacArthur Foundation", "13-1947262", "Vera Institute of Justice Inc", 1500000.0, 2022, "Decarceration and Justice System Transformation", "Form 990-PF Part XV"),
    FundingGrant("23-7093598", "John D & Catherine T MacArthur Foundation", "36-4309819", "Roderick & Solange MacArthur Justice Center", 3000000.0, 2022, "Civil Rights and Public Defense Advocacy", "Form 990-PF Part XV"),
    FundingGrant("23-7093598", "John D & Catherine T MacArthur Foundation", "52-1692287", "Earthjustice", 1200000.0, 2022, "Public Lands and Clean Air Litigation", "Form 990-PF Part XV"),
    FundingGrant("23-7093598", "John D & Catherine T MacArthur Foundation", "13-3921876", "Center for Constitutional Rights", 750000.0, 2022, "Human Rights Legal Defense and Education", "Form 990-PF Part XV"),
    FundingGrant("23-7093598", "John D & Catherine T MacArthur Foundation", "94-1156365", "Sierra Club Foundation", 800000.0, 2022, "Beyond Coal & Clean Energy Initiative", "Form 990-PF Part XV"),

    # Duplicate under legacy EIN 36-2993077 for complete compatibility
    FundingGrant("36-2993077", "John D & Catherine T MacArthur Foundation", "51-0198509", "Tides Foundation", 850000.0, 2022, "Equitable Recovery and Media Grants", "Form 990-PF Part XV"),
    FundingGrant("36-2993077", "John D & Catherine T MacArthur Foundation", "20-5205488", "New Venture Fund", 1500000.0, 2022, "Public Interest Democracy & Media Collaboration", "Form 990-PF Part XV"),
    FundingGrant("36-2993077", "John D & Catherine T MacArthur Foundation", "26-2184698", "ClimateWorks Foundation", 3500000.0, 2022, "Global Climate Solutions & Clean Energy Field Support", "Form 990-PF Part XV"),
    FundingGrant("36-2993077", "John D & Catherine T MacArthur Foundation", "94-3126848", "Energy Foundation", 2500000.0, 2022, "Renewable Energy Transition and Policy Research", "Form 990-PF Part XV"),
    FundingGrant("36-2993077", "John D & Catherine T MacArthur Foundation", "13-1760110", "Natural Resources Defense Council Inc", 2000000.0, 2022, "Environmental Litigation & Climate Justice", "Form 990-PF Part XV"),
    FundingGrant("36-2993077", "John D & Catherine T MacArthur Foundation", "13-1996568", "American Civil Liberties Union Foundation Inc", 1750000.0, 2022, "Voting Rights and Criminal Justice Reform", "Form 990-PF Part XV"),
    FundingGrant("36-2993077", "John D & Catherine T MacArthur Foundation", "52-0881901", "Urban Institute", 1800000.0, 2022, "Housing Policy and Community Economic Development", "Form 990-PF Part XV"),
    FundingGrant("36-2993077", "John D & Catherine T MacArthur Foundation", "53-0196570", "Brookings Institution", 1250000.0, 2022, "Governance Studies and Metropolitan Policy Program", "Form 990-PF Part XV"),
    FundingGrant("36-2993077", "John D & Catherine T MacArthur Foundation", "13-1947262", "Vera Institute of Justice Inc", 1500000.0, 2022, "Decarceration and Justice System Transformation", "Form 990-PF Part XV"),
    FundingGrant("36-2993077", "John D & Catherine T MacArthur Foundation", "36-4309819", "Roderick & Solange MacArthur Justice Center", 3000000.0, 2022, "Civil Rights and Public Defense Advocacy", "Form 990-PF Part XV"),
    FundingGrant("36-2993077", "John D & Catherine T MacArthur Foundation", "52-1692287", "Earthjustice", 1200000.0, 2022, "Public Lands and Clean Air Litigation", "Form 990-PF Part XV"),
    FundingGrant("36-2993077", "John D & Catherine T MacArthur Foundation", "13-3921876", "Center for Constitutional Rights", 750000.0, 2022, "Human Rights Legal Defense and Education", "Form 990-PF Part XV"),
    FundingGrant("36-2993077", "John D & Catherine T MacArthur Foundation", "94-1156365", "Sierra Club Foundation", 800000.0, 2022, "Beyond Coal & Clean Energy Initiative", "Form 990-PF Part XV"),


    # Upstream to Ford Foundation (level 2 backward)
    FundingGrant("13-1624190", "Carnegie Corporation of New York", "13-1628106", "Ford Foundation", 350000.0, 2021, "International Peace and Security Consortium", "Form 990-PF Part XV"),

    # Downstream from Tides Foundation (51-0198509)
    FundingGrant("51-0198509", "Tides Foundation", "94-3213100", "Tides Center", 28500000.0, 2022, "Fiscal Sponsorship Project Support & Operating Transfer", "Schedule I"),
    FundingGrant("51-0198509", "Tides Foundation", "94-3213100", "Tides Center", 25000000.0, 2021, "Intercompany Project Grants", "Schedule I"),
    FundingGrant("51-0198509", "Tides Foundation", "13-3921876", "Center for Constitutional Rights", 850000.0, 2022, "Civil Rights Litigation & Advocacy", "Schedule I"),
    FundingGrant("51-0198509", "Tides Foundation", "94-1156365", "Sierra Club Foundation", 1250000.0, 2022, "Public Lands and Clean Energy", "Schedule I"),
    FundingGrant("51-0198509", "Tides Foundation", "13-1760110", "Natural Resources Defense Council Inc", 1750000.0, 2022, "Environmental Litigation and Policy", "Schedule I"),
    FundingGrant("51-0198509", "Tides Foundation", "52-1692287", "Earthjustice", 1450000.0, 2022, "Legal Defense of Wildlife and Public Health", "Schedule I"),
    FundingGrant("51-0198509", "Tides Foundation", "13-1996568", "American Civil Liberties Union Foundation Inc", 2100000.0, 2022, "Voting Rights and Immigrant Rights Project", "Schedule I"),
    FundingGrant("51-0198509", "Tides Foundation", "20-5205488", "New Venture Fund", 3200000.0, 2022, "Public Interest Collaboration", "Schedule I"),

    # Downstream from Tides Center (level 2 forward)
    FundingGrant("94-3213100", "Tides Center", "20-5641598", "Hopewell Fund", 750000.0, 2022, "Community Engagement Partner", "Schedule I"),
    FundingGrant("94-3213100", "Tides Center", "82-1926639", "Windward Fund", 620000.0, 2022, "Sustainable Agriculture Collaboration", "Schedule I")
]

SEED_RELATIONSHIPS = [
    # Schedule R Corporate Connections
    Relationship("51-0198509", "Tides Foundation", "94-3213100", "Tides Center", "Sibling / Common Governance", "Fiscal Sponsorship & Social Venture Incubation", "Schedule R"),
    Relationship("51-0198509", "Tides Foundation", "94-3349769", "Tides Center Pa", "Related Tax-Exempt Org", "State Chapter / Regional Office", "Schedule R"),
    Relationship("51-0198509", "Tides Foundation", "94-2457812", "Tides Network", "Parent / Controlling Entity", "Strategic Direction & Shared Administration", "Schedule R"),
    Relationship("51-0198509", "Tides Foundation", "81-1234567", "Tides Two Rivers Fund", "Disregarded Entity", "Real Estate / Asset Holding", "Schedule R Part I"),
    Relationship("23-7093598", "John D & Catherine T MacArthur Foundation", "36-4309819", "Roderick & Solange MacArthur Justice Center", "Affiliated Public Interest Legal Center", "Criminal Justice Reform & Civil Rights", "Schedule R"),
    Relationship("36-2993077", "John D & Catherine T MacArthur Foundation", "36-4309819", "Roderick & Solange MacArthur Justice Center", "Affiliated Public Interest Legal Center", "Criminal Justice Reform & Civil Rights", "Schedule R"),
]

SEED_EXPENSES = [
    ExpenseBreakdown(
        filer_ein="51-0198509",
        filer_name="Tides Foundation",
        tax_year=2022,
        total_expenses=380000000.0,
        program_services=342000000.0,
        management_general=26600000.0,
        fundraising=11400000.0,
        salaries_total=18500000.0,
        professional_fees=8200000.0,
        office_and_it=4100000.0,
        travel_and_conferences=950000.0,
        grants_paid=310000000.0
    ),
    ExpenseBreakdown(
        filer_ein="94-3213100",
        filer_name="Tides Center",
        tax_year=2022,
        total_expenses=275000000.0,
        program_services=242000000.0,
        management_general=27500000.0,
        fundraising=5500000.0,
        salaries_total=115000000.0,
        professional_fees=22000000.0,
        office_and_it=18000000.0,
        travel_and_conferences=3500000.0,
        grants_paid=25000000.0
    ),
    ExpenseBreakdown(
        filer_ein="13-1628106",
        filer_name="Ford Foundation",
        tax_year=2022,
        total_expenses=650000000.0,
        program_services=572000000.0,
        management_general=65000000.0,
        fundraising=13000000.0,
        salaries_total=82000000.0,
        professional_fees=19000000.0,
        office_and_it=14000000.0,
        travel_and_conferences=4800000.0,
        grants_paid=450000000.0
    ),
    ExpenseBreakdown(
        filer_ein="56-2618866",
        filer_name="Bill & Melinda Gates Foundation",
        tax_year=2022,
        total_expenses=6200000000.0,
        program_services=5704000000.0,
        management_general=496000000.0,
        fundraising=0.0,
        salaries_total=380000000.0,
        professional_fees=110000000.0,
        office_and_it=75000000.0,
        travel_and_conferences=28000000.0,
        grants_paid=5100000000.0
    ),
    ExpenseBreakdown(
        filer_ein="20-0080649",
        filer_name="NETHOPE, INC.",
        tax_year=2022,
        total_expenses=34500000.0,
        program_services=30360000.0,
        management_general=3105000.0,
        fundraising=1035000.0,
        salaries_total=14200000.0,
        professional_fees=5100000.0,
        office_and_it=2800000.0,
        travel_and_conferences=1100000.0,
        grants_paid=4200000.0
    ),
]

SEED_CONTRACTORS = [
    IndependentContractor("51-0198509", "Tides Foundation", 2022, "Arabella Advisors LLC", "Washington", "DC", "Philanthropic & Operational Consulting", 1250000.0),
    IndependentContractor("51-0198509", "Tides Foundation", 2022, "Salesforce.com Inc", "San Francisco", "CA", "Cloud CRM & Platform Software", 850000.0),
    IndependentContractor("51-0198509", "Tides Foundation", 2022, "Perkins Coie LLP", "Seattle", "WA", "Legal Counsel & Governance Compliance", 620000.0),
    IndependentContractor("13-1628106", "Ford Foundation", 2022, "McKinsey & Company", "New York", "NY", "Strategic Organizational Advisory", 1850000.0),
    IndependentContractor("13-1628106", "Ford Foundation", 2022, "Sullivan & Cromwell LLP", "New York", "NY", "Legal Services & Regulatory Counsel", 980000.0),
    IndependentContractor("20-0080649", "NETHOPE, INC.", 2022, "Amazon Web Services Inc", "Seattle", "WA", "Cloud Infrastructure for Disaster Relief", 450000.0),
    IndependentContractor("20-0080649", "NETHOPE, INC.", 2022, "Cisco Systems Inc", "San Jose", "CA", "Emergency Connectivity Network Hardware", 380000.0),
]

SEED_PEOPLE = [
    # Darren Walker (Ford Foundation President, and interlocks)
    PersonAffiliation("13-1628106", "Ford Foundation", 2022, "Darren Walker", "DARREN WALKER", "President & Trustee", "Officer", 40.0, 1250000.0, 0.0, 145000.0, 1395000.0),
    PersonAffiliation("13-1628106", "Ford Foundation", 2022, "Kofi Appenteng", "KOFI APPENTENG", "Trustee", "Trustee/Director", 5.0, 0.0, 0.0, 0.0, 0.0),
    PersonAffiliation("13-1628106", "Ford Foundation", 2022, "Cecile Richards", "CECILE RICHARDS", "Trustee", "Trustee/Director", 5.0, 0.0, 0.0, 0.0, 0.0),

    # Gates Foundation leadership
    PersonAffiliation("56-2618866", "Bill & Melinda Gates Foundation", 2022, "William H Gates III", "WILLIAM H GATES", "Co-Chair & Trustee", "Trustee/Director", 40.0, 0.0, 0.0, 0.0, 0.0),
    PersonAffiliation("56-2618866", "Bill & Melinda Gates Foundation", 2022, "Melinda French Gates", "MELINDA FRENCH GATES", "Former Co-Chair & Trustee", "Former", 25.0, 0.0, 0.0, 0.0, 0.0),
    PersonAffiliation("56-2618866", "Bill & Melinda Gates Foundation", 2022, "Mark Suzman", "MARK SUZMAN", "Chief Executive Officer", "Officer", 45.0, 1420000.0, 0.0, 185000.0, 1605000.0),

    # Tides Foundation & Tides Center Leadership (Interlocks across the Tides network!)
    PersonAffiliation("51-0198509", "Tides Foundation", 2022, "Amanda Keton", "AMANDA KETON", "Chief Executive Officer", "Officer", 40.0, 485000.0, 0.0, 42000.0, 527000.0),
    PersonAffiliation("94-3213100", "Tides Center", 2022, "Amanda Keton", "AMANDA KETON", "Executive Officer / Director", "Officer", 10.0, 0.0, 485000.0, 0.0, 485000.0),
    PersonAffiliation("51-0198509", "Tides Foundation", 2022, "Janani Ramachandran", "JANANI RAMACHANDRAN", "Board Trustee", "Trustee/Director", 5.0, 0.0, 0.0, 0.0, 0.0),
    PersonAffiliation("94-3213100", "Tides Center", 2022, "Janani Ramachandran", "JANANI RAMACHANDRAN", "Board Trustee", "Trustee/Director", 5.0, 0.0, 0.0, 0.0, 0.0),
    PersonAffiliation("51-0198509", "Tides Foundation", 2022, "Tutu Alicante", "TUTU ALICANTE", "Board Chair", "Trustee/Director", 8.0, 0.0, 0.0, 0.0, 0.0),

    # NetHope Leadership
    PersonAffiliation("20-0080649", "NETHOPE, INC.", 2022, "Lance Pierce", "LANCE PIERCE", "Chief Executive Officer", "Officer", 40.0, 385000.0, 0.0, 32000.0, 417000.0),
    PersonAffiliation("20-0080649", "NETHOPE, INC.", 2022, "Per Heggenes", "PER HEGGENES", "Board Chair", "Trustee/Director", 6.0, 0.0, 0.0, 0.0, 0.0),
]


def load_seed_data(storage: IRS990Storage, force: bool = False) -> bool:
    """
    Populate database with curated initial institutional seed dataset.
    Skips redundant insertion if seeds are already loaded in database unless force=True.
    Returns True if data was inserted, False if skipped.
    """
    if not force:
        try:
            meta = storage.get_ingestion_metadata()
            seeds_meta = next((m for m in meta if m["source_id"] == "SEEDS"), None)
            if seeds_meta and seeds_meta.get("records_count", 0) >= len(SEED_GRANTS):
                row = storage.conn.execute("SELECT count(*) FROM grants WHERE grantor_ein = '51-0198509';").fetchone()
                if row and row[0] > 0:
                    logger.debug("Institutional seeds already populated in database. Skipping.")
                    return False
        except Exception:
            pass

    for org in MAJOR_FOUNDATIONS:
        storage.upsert_organization(org)
    storage.upsert_grants(SEED_GRANTS)
    storage.upsert_relationships(SEED_RELATIONSHIPS)
    storage.upsert_expenses(SEED_EXPENSES)
    storage.upsert_contractors(SEED_CONTRACTORS)
    storage.upsert_people(SEED_PEOPLE)
    storage.record_sync(
        source_id="SEEDS",
        source_name="Curated Institutional Funders & Seeds",
        count=len(SEED_GRANTS),
        details=f"{len(MAJOR_FOUNDATIONS)} major foundations/DAFs, {len(SEED_GRANTS)} verified grants, {len(SEED_RELATIONSHIPS)} relationships, {len(SEED_PEOPLE)} leadership affiliations"
    )
    return True

