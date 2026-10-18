# SPDX-FileCopyrightText: 2026 990-Explorer Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for XML and Data Parsers.

Architectural Purpose:
    Validates parsing of IRS 990 Schedule I grant tables, Form 990-PF Part XV,
    Schedule R corporate relationships, return headers, and EIN normalization.
"""

from irs990.parser import (
    clean_ein,
    parse_schedule_i_xml,
    parse_990pf_part_xv_xml,
    parse_schedule_r_xml,
    parse_return_header
)
from irs990.models import OrganizationNode

SAMPLE_SCHEDULE_I_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Return xmlns="http://www.irs.gov/efile">
  <ReturnHeader>
    <TaxYear>2022</TaxYear>
    <Filer>
      <EIN>510198509</EIN>
      <BusinessName>
        <BusinessNameLine1Txt>Tides Foundation</BusinessNameLine1Txt>
      </BusinessName>
    </Filer>
  </ReturnHeader>
  <ReturnData>
    <IRS990ScheduleI>
      <RecipientTable>
        <RecipientEIN>943213100</RecipientEIN>
        <RecipientNameBusiness>
          <BusinessNameLine1Txt>Tides Center</BusinessNameLine1Txt>
        </RecipientNameBusiness>
        <CashGrantAmt>28500000</CashGrantAmt>
        <PurposeOfGrantTxt>Fiscal Sponsorship Project Support</PurposeOfGrantTxt>
      </RecipientTable>
      <RecipientTable>
        <RecipientEIN>133921876</RecipientEIN>
        <RecipientNameBusiness>
          <BusinessNameLine1Txt>Center for Constitutional Rights</BusinessNameLine1Txt>
        </RecipientNameBusiness>
        <CashGrantAmt>850000</CashGrantAmt>
        <PurposeOfGrantTxt>Civil Rights Defense</PurposeOfGrantTxt>
      </RecipientTable>
    </IRS990ScheduleI>
  </ReturnData>
</Return>
"""

SAMPLE_990PF_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Return xmlns="http://www.irs.gov/efile">
  <ReturnHeader>
    <TaxYear>2022</TaxYear>
    <Filer>
      <EIN>131628106</EIN>
      <BusinessName>
        <BusinessNameLine1Txt>Ford Foundation</BusinessNameLine1Txt>
      </BusinessName>
    </Filer>
  </ReturnHeader>
  <ReturnData>
    <IRS990PF>
      <GrantOrContributionPDTable>
        <GranteeEIN>510198509</GranteeEIN>
        <GranteeNameBusiness>
          <BusinessNameLine1Txt>Tides Foundation</BusinessNameLine1Txt>
        </GranteeNameBusiness>
        <Amount>1250000</Amount>
        <GrantOrContributionPurpose>Civic Engagement Program</GrantOrContributionPurpose>
      </GrantOrContributionPDTable>
    </IRS990PF>
  </ReturnData>
</Return>
"""

SAMPLE_SCHEDULE_R_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Return xmlns="http://www.irs.gov/efile">
  <ReturnData>
    <IRS990ScheduleR>
      <RelatedTaxExemptOrgTable>
        <EIN>943213100</EIN>
        <BusinessNameLine1Txt>Tides Center</BusinessNameLine1Txt>
        <DirectControllingEntityNameTxt>None</DirectControllingEntityNameTxt>
        <PrimaryActivityTxt>Fiscal Sponsorship</PrimaryActivityTxt>
      </RelatedTaxExemptOrgTable>
      <DisregardedEntityTable>
        <EIN>811234567</EIN>
        <BusinessNameLine1Txt>Tides Two Rivers Fund</BusinessNameLine1Txt>
        <DirectControllingEntityNameTxt>Tides Foundation</DirectControllingEntityNameTxt>
      </DisregardedEntityTable>
    </IRS990ScheduleR>
  </ReturnData>
</Return>
"""


def test_clean_ein():
    assert clean_ein("510198509") == "51-0198509"
    assert clean_ein("51-0198509") == "51-0198509"
    assert clean_ein("16046843") == "01-6046843"
    assert clean_ein("") == ""


def test_parse_return_header():
    header_res = parse_return_header(SAMPLE_SCHEDULE_I_XML)
    assert header_res is not None
    node, tax_year = header_res
    assert node.ein == "51-0198509"
    assert node.name == "Tides Foundation"
    assert tax_year == 2022


def test_parse_schedule_i():
    grantor = OrganizationNode(ein="51-0198509", name="Tides Foundation")
    grants = parse_schedule_i_xml(SAMPLE_SCHEDULE_I_XML, grantor, 2022)
    assert len(grants) == 2
    assert grants[0].recipient_ein == "94-3213100"
    assert grants[0].amount == 28500000.0
    assert grants[0].tax_year == 2022
    assert "Fiscal Sponsorship" in grants[0].purpose


def test_parse_990pf():
    grantor = OrganizationNode(ein="13-1628106", name="Ford Foundation")
    grants = parse_990pf_part_xv_xml(SAMPLE_990PF_XML, grantor, 2022)
    assert len(grants) == 1
    assert grants[0].recipient_ein == "51-0198509"
    assert grants[0].amount == 1250000.0
    assert grants[0].source_schedule == "Form 990-PF Part XV"


def test_parse_schedule_r():
    entity = OrganizationNode(ein="51-0198509", name="Tides Foundation")
    rels = parse_schedule_r_xml(SAMPLE_SCHEDULE_R_XML, entity)
    assert len(rels) == 2
    assert rels[0].related_ein == "94-3213100"
    assert rels[1].relationship_type == "Disregarded Entity"
