# SPDX-FileCopyrightText: 2026 990-Explorer Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit and integration tests for Form 990 Part IX Functional Expenses, Part VII Contractors, and Leadership.

Architectural Purpose:
    Validates parsing, storage, and retrieval of Part IX functional expenses,
    top-compensated commercial independent contractors, and interlocking directorates.
"""

import os
import tempfile
import pytest
from irs990.models import OrganizationNode, ExpenseBreakdown, IndependentContractor, PersonAffiliation
from irs990.parser import (
    normalize_person_name,
    parse_part_ix_expenses,
    parse_part_vii_contractors,
    parse_part_vii_people,
)
from irs990.storage import IRS990Storage
from irs990.seeds import load_seed_data


SAMPLE_FORM_990_XML = """<?xml version="1.0" encoding="utf-8"?>
<Return xmlns="http://www.irs.gov/efile">
  <ReturnHeader>
    <TaxYr>2023</TaxYr>
    <Filer>
      <EIN>112233445</EIN>
      <BusinessName><BusinessNameLine1Txt>SAMPLE CHARITY FOUNDATION INC</BusinessNameLine1Txt></BusinessName>
    </Filer>
  </ReturnHeader>
  <ReturnData>
    <IRS990>
      <!-- Part IX Functional Expenses -->
      <TotalFunctionalExpensesGrp>
        <TotalAmt>1000000</TotalAmt>
        <ProgramServicesAmt>850000</ProgramServicesAmt>
        <ManagementAndGeneralAmt>100000</ManagementAndGeneralAmt>
        <FundraisingAmt>50000</FundraisingAmt>
      </TotalFunctionalExpensesGrp>
      <CompCurrentOfcrDirectorsGrp>
        <TotalAmt>200000</TotalAmt>
      </CompCurrentOfcrDirectorsGrp>
      <FeesForServicesLegalGrp>
        <TotalAmt>45000</TotalAmt>
      </FeesForServicesLegalGrp>
      <GrantsToDomesticOrgsGrp>
        <TotalAmt>500000</TotalAmt>
      </GrantsToDomesticOrgsGrp>

      <!-- Part VII Section B Independent Contractors -->
      <CompOf5HighestPaidContrctGrp>
        <PersonNm>TECH STRATEGY PARTNERS LLC</PersonNm>
        <CityNm>San Francisco</CityNm>
        <StateAbbreviationCd>CA</StateAbbreviationCd>
        <DescOfServicesTxt>IT Infrastructure and Architecture</DescOfServicesTxt>
        <CompensationAmt>175000</CompensationAmt>
      </CompOf5HighestPaidContrctGrp>

      <!-- Part VII Section A Officers, Directors, Trustees -->
      <Form990PartVIISectionAGrp>
        <PersonNm>DR. ELEANOR V. VANCE, ESQ.</PersonNm>
        <TitleTxt>President &amp; CEO</TitleTxt>
        <AverageHoursPerWeekRt>40.0</AverageHoursPerWeekRt>
        <OfficerInd>1</OfficerInd>
        <ReportableCompFromOrgAmt>180000</ReportableCompFromOrgAmt>
        <OtherCompensationAmt>20000</OtherCompensationAmt>
      </Form990PartVIISectionAGrp>
      <Form990PartVIISectionAGrp>
        <PersonNm>MARCUS AURELIUS JR.</PersonNm>
        <TitleTxt>Board Trustee</TitleTxt>
        <AverageHoursPerWeekRt>5.0</AverageHoursPerWeekRt>
        <IndividualTrusteeOrDirectorInd>1</IndividualTrusteeOrDirectorInd>
        <ReportableCompFromOrgAmt>0</ReportableCompFromOrgAmt>
        <OtherCompensationAmt>0</OtherCompensationAmt>
      </Form990PartVIISectionAGrp>
    </IRS990>
  </ReturnData>
</Return>
"""


def test_normalize_person_name():
    assert normalize_person_name("DR. ELEANOR V. VANCE, ESQ.") == "ELEANOR VANCE"
    assert normalize_person_name("MARCUS AURELIUS JR.") == "MARCUS AURELIUS"
    assert normalize_person_name("HON. JANE DOE, III") == "JANE DOE"
    assert normalize_person_name("  John   Smith  ") == "JOHN SMITH"


def test_parse_part_ix_expenses():
    node = OrganizationNode(ein="11-2233445", name="Sample Charity Foundation Inc")
    breakdown = parse_part_ix_expenses(SAMPLE_FORM_990_XML, node, 2023)

    assert breakdown is not None
    assert breakdown.filer_ein == "11-2233445"
    assert breakdown.total_expenses == 1_000_000.0
    assert breakdown.program_services == 850_000.0
    assert breakdown.management_general == 100_000.0
    assert breakdown.fundraising == 50_000.0
    assert breakdown.program_percentage == 85.0
    assert breakdown.admin_percentage == 10.0
    assert breakdown.fundraising_percentage == 5.0
    assert breakdown.salaries_total == 200_000.0
    assert breakdown.professional_fees == 45_000.0
    assert breakdown.grants_paid == 500_000.0


def test_parse_part_vii_contractors():
    node = OrganizationNode(ein="11-2233445", name="Sample Charity Foundation Inc")
    contractors = parse_part_vii_contractors(SAMPLE_FORM_990_XML, node, 2023)

    assert len(contractors) == 1
    c = contractors[0]
    assert "TECH STRATEGY" in c.contractor_name
    assert c.city == "San Francisco"
    assert c.state == "CA"
    assert c.amount == 175_000.0
    assert "IT Infrastructure" in c.description_of_services


def test_parse_part_vii_people():
    node = OrganizationNode(ein="11-2233445", name="Sample Charity Foundation Inc")
    people = parse_part_vii_people(SAMPLE_FORM_990_XML, node, 2023)

    assert len(people) == 2

    p1 = next(p for p in people if "ELEANOR" in p.clean_name)
    assert p1.clean_name == "ELEANOR VANCE"
    assert p1.role_type == "Officer"
    assert p1.hours_per_week == 40.0
    assert p1.reportable_comp == 180_000.0
    assert p1.other_comp == 20_000.0
    assert p1.total_comp == 200_000.0

    p2 = next(p for p in people if "MARCUS" in p.clean_name)
    assert p2.clean_name == "MARCUS AURELIUS"
    assert p2.hours_per_week == 5.0
    assert p2.total_comp == 0.0


def test_storage_spending_and_people():
    with tempfile.NamedTemporaryFile(suffix=".duckdb", delete=False) as tf:
        db_path = tf.name
    if os.path.exists(db_path):
        os.remove(db_path)

    try:
        storage = IRS990Storage(db_path)
        load_seed_data(storage)

        # 1. Test Seed Expenses
        tides_exp = storage.get_expenses("51-0198509")
        assert len(tides_exp) >= 1
        assert tides_exp[0].program_percentage == 90.0
        assert tides_exp[0].total_expenses == 380_000_000.0

        # 2. Test Seed Contractors
        tides_contractors = storage.get_contractors("51-0198509")
        assert len(tides_contractors) >= 1
        assert any("Arabella" in c.contractor_name for c in tides_contractors)

        # 3. Test Seed People & Interlocks
        tides_people = storage.get_people_by_organization("51-0198509")
        assert len(tides_people) >= 3

        # Amanda Keton sits on Tides Foundation & Tides Center
        keton_interlocks = storage.get_person_interlocks("AMANDA KETON")
        assert len(keton_interlocks) == 2
        eins = {i["filer_ein"] for i in keton_interlocks}
        assert "51-0198509" in eins
        assert "94-3213100" in eins

        # 4. Test Interlocking Directorates query
        interlocks = storage.get_interlocking_directorates()
        assert len(interlocks) >= 2
        shared_leaders = {i["shared_person"] for i in interlocks}
        assert "AMANDA KETON" in shared_leaders
        assert "JANANI RAMACHANDRAN" in shared_leaders

        # 5. Database Stats reflects leadership and spending
        stats = storage.get_database_stats()
        sp = stats["spending_and_people"]
        assert sp["leadership_records"] >= 10
        assert sp["unique_people"] >= 8
        assert sp["multi_board_leaders"] >= 2
        assert sp["expenses_records"] >= 3
        assert sp["contractors_records"] >= 3

        storage.close()
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)
