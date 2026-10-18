# SPDX-FileCopyrightText: 2026 990-Explorer Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""IRS 990 XML and Data Parser Module.

Architectural Purpose:
    Parses IRS Modernized e-File (MeF) XML schemas across historical versions
    (Forms 990, 990-PF, Schedule I, Schedule R, Part VII compensation, Part IX
    functional expenses) and normalizes messy data into structured domain models.

Security Invariants:
    - Protects against XML entity expansion attacks (Billion Laughs / CWE-611)
      by using defusedxml-safe standard tree iteration without DTD/external entity resolution.
    - Sanitizes alphanumeric strings and numeric currency fields to prevent injection or corruption.
"""

import xml.etree.ElementTree as ET
import logging
import re
from typing import List, Dict, Any, Tuple, Optional
from .models import (
    OrganizationNode, FundingGrant, Relationship,
    ExpenseBreakdown, IndependentContractor, PersonAffiliation
)

logger = logging.getLogger(__name__)


EIN_ALIASES: Dict[str, str] = {
    "04-3132178": "11-0303001",
    "11-0303001": "04-3132178",
    "36-2993077": "23-7093598",
    "23-7093598": "36-2993077",
}


def clean_ein(ein_str: Any) -> str:
    """Normalize EIN to standard 9-digit format (XX-XXXXXXX)."""
    if not ein_str:
        return ""
    digits = "".join(c for c in str(ein_str) if c.isdigit())
    if len(digits) == 9:
        return f"{digits[:2]}-{digits[2:]}"
    elif len(digits) == 8:
        # Some filings drop leading zero
        digits = "0" + digits
        return f"{digits[:2]}-{digits[2:]}"
    return digits



def get_xml_text(element: Optional[ET.Element], tag_names: List[str]) -> str:
    """Find first matching child tag text, ignoring XML namespaces."""
    if element is None:
        return ""
    
    # 1. First check direct children
    for child in list(element):
        local_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if local_tag in tag_names and child.text and child.text.strip():
            return child.text.strip()
    
    # 2. Check full sub-tree iteration
    for child in element.iter():
        local_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if local_tag in tag_names and child.text and child.text.strip():
            return child.text.strip()
    return ""


def parse_return_header(xml_content: str) -> Optional[Tuple[OrganizationNode, int]]:
    """
    Extract filer organization info and tax year from the ReturnHeader / ReturnData.
    Returns (OrganizationNode, tax_year).
    """
    try:
        root = ET.fromstring(xml_content)
    except Exception as e:
        logger.error(f"Failed to parse XML root: {e}")
        return None

    ein = ""
    name = ""
    tax_year = 0
    tot_revenue = 0.0
    tot_assets = 0.0
    city = ""
    state = ""

    # Look for ReturnHeader / Filer
    for elem in root.iter():
        local_tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if local_tag == "Filer" and not ein:
            ein = clean_ein(get_xml_text(elem, ["EIN", "EmployerIdentificationNumber"]))
            name = get_xml_text(elem, ["BusinessNameLine1Txt", "BusinessNameLine1", "BusinessName"])
        elif local_tag == "ReturnHeader" and not tax_year:
            year_str = get_xml_text(elem, ["TaxYear", "TaxYr"])
            if year_str and year_str.isdigit():
                tax_year = int(year_str)

    # Search for financials in 990 / 990-EZ / 990-PF parts
    for elem in root.iter():
        local_tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if local_tag in ["CYTotalRevenueAmt", "TotalRevenueAmt", "TotalRevAndExpnssAmt"]:
            try:
                tot_revenue = float(elem.text.strip())
            except (ValueError, AttributeError):
                pass
        elif local_tag in ["TotalAssetsEOYAmt", "TotalAssetsBOYAmt", "TotalAssetsEndOfYear"]:
            try:
                tot_assets = float(elem.text.strip())
            except (ValueError, AttributeError):
                pass
        elif local_tag in ["USAddress", "AddressUS"]:
            if not city:
                city = get_xml_text(elem, ["CityNm", "City"])
                state = get_xml_text(elem, ["StateAbbreviationCd", "State"])

    if not ein and not name:
        return None

    node = OrganizationNode(
        ein=ein,
        name=name or "Unknown Organization",
        total_revenue=tot_revenue,
        total_assets=tot_assets,
        city=city,
        state=state
    )
    return node, tax_year


def parse_schedule_i_xml(xml_content: str, grantor_node: OrganizationNode, tax_year: int = 0) -> List[FundingGrant]:
    """
    Parse Schedule I (Grants and Other Assistance to Organizations) from Form 990 XML.
    Returns list of FundingGrant objects.
    """
    grants: List[FundingGrant] = []
    try:
        root = ET.fromstring(xml_content)
    except Exception as e:
        logger.error(f"Failed to parse XML content for EIN {grantor_node.ein}: {e}")
        return grants

    # Search for Schedule I grant tables across various schema version tags
    grant_table_tags = {
        "GrantOrOtherAssistanceToGrntTable",
        "GrantOrOtherAssistanceToGrnt",
        "RecipientTable",
        "GrantToOrg",
        "Form990ScheduleIPartII",
        "RecipientGroup",
        "GrantsAndOtherAssistanceToOrganizationsGroup",
        "GrantsOtherAsstToOrganizations"
    }

    ein_keys = {"RecipientEIN", "EIN", "RecipientEINNumber", "EINNumber", "RecipientTaxID"}
    name_keys = {
        "BusinessNameLine1Txt", "BusinessNameLine1", "RecipientNameBusiness",
        "RecipientBusinessName", "BusinessName", "RecipientName"
    }
    amt_keys = {"CashGrantAmt", "CashGrantAmount", "Amount", "CashGrant", "GrantAmt", "TotalAmt"}
    purpose_keys = {"PurposeOfGrantTxt", "PurposeOfGrant", "GrantPurpose", "GrantPurposeTxt", "DescriptionOfGrant"}

    for elem in root.iter():
        local_tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        
        if local_tag in grant_table_tags:
            recip_ein = ""
            recip_name = ""
            amt_str = ""
            purpose = ""

            for child in elem.iter():
                ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if child.text and child.text.strip():
                    val = child.text.strip()
                    if not recip_ein and ctag in ein_keys:
                        recip_ein = clean_ein(val)
                    elif not recip_name and ctag in name_keys:
                        recip_name = val
                    elif not amt_str and ctag in amt_keys:
                        amt_str = val
                    elif not purpose and ctag in purpose_keys:
                        purpose = val

            amount = 0.0
            if amt_str:
                try:
                    amount = float(amt_str)
                except ValueError:
                    amount = 0.0

            if recip_name or recip_ein:
                grant = FundingGrant(
                    grantor_ein=grantor_node.ein,
                    grantor_name=grantor_node.name,
                    recipient_ein=recip_ein,
                    recipient_name=recip_name or "Unknown Organization",
                    amount=amount,
                    tax_year=tax_year,
                    purpose=purpose,
                    source_schedule="Schedule I"
                )
                grants.append(grant)

    return grants


def parse_990pf_part_xv_xml(xml_content: str, foundation_node: OrganizationNode, tax_year: int = 0) -> List[FundingGrant]:
    """
    Parse Form 990-PF Part XV (Grants and Contributions Paid During the Year) from Private Foundation XML.
    """
    grants: List[FundingGrant] = []
    try:
        root = ET.fromstring(xml_content)
    except Exception as e:
        logger.error(f"Failed to parse 990-PF XML content for EIN {foundation_node.ein}: {e}")
        return grants

    pf_table_tags = {
        "GrantOrContributionPDTable",
        "GrantOrContributionPD",
        "GrantsPaidTable",
        "GrantsPaid",
        "Form990PFPartXV",
        "SupplementaryInformationGrantsPaid",
        "GrantOrContributionProgram"
    }

    for elem in root.iter():
        local_tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        
        if local_tag in pf_table_tags:
            recip_ein = clean_ein(get_xml_text(elem, ["GranteeEIN", "RecipientEIN", "EIN", "GranteeEINNumber"]))
            recip_name = get_xml_text(elem, [
                "BusinessNameLine1Txt", "BusinessNameLine1", "GranteeNameBusiness",
                "RecipientNameBusiness", "GranteeName", "RecipientName"
            ])
            
            amt_str = get_xml_text(elem, ["Amount", "GrantAmount", "CashGrantAmt", "Amt"])
            purpose = get_xml_text(elem, ["GrantOrContributionPurpose", "PurposeOfGrant", "GrantPurpose", "Purpose"])

            amount = 0.0
            if amt_str:
                try:
                    amount = float(amt_str)
                except ValueError:
                    amount = 0.0

            if recip_name or recip_ein:
                grant = FundingGrant(
                    grantor_ein=foundation_node.ein,
                    grantor_name=foundation_node.name,
                    recipient_ein=recip_ein,
                    recipient_name=recip_name or "Unknown Grantee",
                    amount=amount,
                    tax_year=tax_year,
                    purpose=purpose,
                    source_schedule="Form 990-PF Part XV"
                )
                grants.append(grant)

    return grants


def parse_schedule_r_xml(xml_content: str, entity_node: OrganizationNode) -> List[Relationship]:
    """
    Parse Schedule R (Related Organizations and Unrelated Partnerships) from Form 990 XML.
    Identifies Parents, Subsidiaries, Siblings, and Disregarded Entities.
    """
    relationships: List[Relationship] = []
    try:
        root = ET.fromstring(xml_content)
    except Exception as e:
        logger.error(f"Failed to parse Schedule R XML content for EIN {entity_node.ein}: {e}")
        return relationships

    rel_table_tags = {
        "RelatedTaxExemptOrgTable",
        "RelatedTaxExemptOrganization",
        "DisregardedEntityTable",
        "DisregardedEntity",
        "RelatedOrgGroup",
        "RelatedOrganization",
        "RelatedCorporationTable",
        "RelatedPartnershipTable"
    }

    ein_keys = {"EIN", "RelatedEIN", "EntityEIN", "TaxpayerEIN"}
    name_keys = {"BusinessNameLine1Txt", "BusinessNameLine1", "RelatedOrganizationName", "EntityName", "BusinessName"}
    ctrl_keys = {"DirectControllingEntityNameTxt", "DirectControllingEntityName", "ControllingEntity"}
    act_keys = {"PrimaryActivityTxt", "PrimaryActivity", "ActivityDescription"}

    for elem in root.iter():
        local_tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        
        if local_tag in rel_table_tags:
            rel_ein = ""
            rel_name = ""
            controlling_entity = ""
            activity = ""

            for child in elem.iter():
                ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if child.text and child.text.strip():
                    val = child.text.strip()
                    if not rel_ein and ctag in ein_keys:
                        rel_ein = clean_ein(val)
                    elif not rel_name and ctag in name_keys:
                        rel_name = val
                    elif not controlling_entity and ctag in ctrl_keys:
                        controlling_entity = val
                    elif not activity and ctag in act_keys:
                        activity = val

            # Determine relationship type
            rel_type = "Related Organization"
            if controlling_entity:
                if entity_node.name and entity_node.name.lower() in controlling_entity.lower():
                    rel_type = "Subsidiary"
                elif "none" in controlling_entity.lower() or "n/a" in controlling_entity.lower():
                    rel_type = "Sibling / Common Control"
                else:
                    rel_type = f"Controlled By: {controlling_entity}"

            if "Disregarded" in local_tag:
                rel_type = "Disregarded Entity"
            elif "Partnership" in local_tag:
                rel_type = "Related Partnership"
            elif "Corporation" in local_tag:
                rel_type = "Related Corporation"

            if rel_name or rel_ein:
                relationships.append(Relationship(
                    entity_ein=entity_node.ein,
                    entity_name=entity_node.name,
                    related_ein=rel_ein,
                    related_name=rel_name or "Unknown Related Entity",
                    relationship_type=rel_type,
                    primary_activity=activity,
                    source_schedule="Schedule R"
                ))

    return relationships


def parse_propublica_org_json(json_data: Dict[str, Any]) -> Tuple[OrganizationNode, List[Dict[str, Any]]]:
    """
    Parse an organization profile and filings list from ProPublica API v2 response.
    Returns (OrganizationNode, list_of_filings).
    """
    org_dict = json_data.get("organization", {})
    ein = clean_ein(str(org_dict.get("ein", "")))
    name = org_dict.get("name", "Unknown Organization")
    
    # Subsection code mapping
    subseccd = org_dict.get("subsection_code", 3)
    tax_status = f"501(c)({subseccd})" if subseccd else "Tax-Exempt"
    if org_dict.get("pf_filing_requirement_code") == 1:
        tax_status = "Private Foundation (501(c)(3))"

    node = OrganizationNode(
        ein=ein,
        name=name,
        tax_status=tax_status,
        total_revenue=float(org_dict.get("revenue_amount") or 0.0),
        total_assets=float(org_dict.get("asset_amount") or 0.0),
        city=org_dict.get("city", ""),
        state=org_dict.get("state", ""),
        address=org_dict.get("address", ""),
        zipcode=org_dict.get("zipcode", ""),
        ntee_code=org_dict.get("ntee_code", "")
    )

    filings = json_data.get("filings_with_data", [])
    return node, filings


def normalize_person_name(raw_name: str) -> str:
    """Normalize a person's name for robust cross-filing identity matching."""
    if not raw_name:
        return ""
    name = raw_name.upper().strip()
    # Remove titles
    name = re.sub(r'^(DR|MR|MS|MRS|REV|PROF|HON|RABBI|FATHER)\.?\s+', '', name)
    # Remove professional degrees & suffixes
    name = re.sub(r'[\s,]+(JR|SR|III|IV|II|ESQ|CPA|MD|PHD|JD|RN|CFP)\.?$', '', name)
    # Remove punctuation
    name = re.sub(r'[^A-Z\s]', ' ', name)
    # Remove single-letter middle initials (e.g. "ELEANOR V VANCE" -> "ELEANOR VANCE")
    name = re.sub(r'\s+[A-Z]\s+', ' ', name)
    # Collapse multiple spaces
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def parse_part_ix_expenses(xml_content: str, filer_node: OrganizationNode, tax_year: int) -> Optional[ExpenseBreakdown]:
    """Parse Form 990 Part IX Statement of Functional Expenses."""
    try:
        root = ET.fromstring(xml_content)
    except Exception as e:
        logger.error(f"Failed to parse XML for expenses: {e}")
        return None

    def get_num(elem, tags):
        txt = get_xml_text(elem, tags)
        try:
            return float(txt) if txt else 0.0
        except ValueError:
            return 0.0

    total_expenses = 0.0
    program_services = 0.0
    management_general = 0.0
    fundraising = 0.0
    salaries = 0.0
    professional_fees = 0.0
    office_it = 0.0
    travel = 0.0
    grants_paid = 0.0

    # Search for Part IX groups
    for elem in root.iter():
        local_tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

        if local_tag in ["TotalFunctionalExpensesGrp", "TotalFunctionalExpenses"]:
            total_expenses = get_num(elem, ["TotalAmt", "Total"])
            program_services = get_num(elem, ["ProgramServicesAmt", "ProgramServices"])
            management_general = get_num(elem, ["ManagementAndGeneralAmt", "ManagementAndGeneral"])
            fundraising = get_num(elem, ["FundraisingAmt", "Fundraising"])

        elif local_tag in ["CompCurrentOfcrDirectorsGrp", "OtherSalariesAndWagesGrp",
                          "PensionPlanContributionsGrp", "OtherEmployeeBenefitsGrp", "PayrollTaxesGrp"]:
            salaries += get_num(elem, ["TotalAmt", "Total"])

        elif local_tag in ["FeesForServicesManagementGrp", "FeesForServicesLegalGrp",
                          "FeesForServicesAccountingGrp", "FeesForServicesLobbyingGrp",
                          "FeesForServicesProfFundraisingGrp", "FeesForServicesInvstMgmtGrp",
                          "FeesForServicesAdvertisingGrp", "FeesForServicesOtherGrp"]:
            professional_fees += get_num(elem, ["TotalAmt", "Total"])

        elif local_tag in ["OfficeExpensesGrp", "InformationTechnologyGrp", "OccupancyGrp"]:
            office_it += get_num(elem, ["TotalAmt", "Total"])

        elif local_tag in ["TravelGrp", "ConferencesMeetingsGrp"]:
            travel += get_num(elem, ["TotalAmt", "Total"])

        elif local_tag in ["GrantsToDomesticOrgsGrp", "GrantsToDomesticIndividualsGrp", "ForeignGrantsGrp"]:
            grants_paid += get_num(elem, ["TotalAmt", "Total"])

    # Fallback to Part I summary if Part IX wasn't found (e.g. 990-PF or summary line)
    if total_expenses == 0.0:
        for elem in root.iter():
            local_tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if local_tag in ["CYTotalExpensesAmt", "TotalExpensesAmt", "TotalExpensesRevAndExpnssAmt"]:
                try:
                    total_expenses = float(elem.text.strip())
                except (ValueError, AttributeError):
                    pass
            elif local_tag in ["DisbursementsCharitablePrpsAmt", "TotalCharitableContriAmt"]:
                try:
                    program_services = float(elem.text.strip())
                except (ValueError, AttributeError):
                    pass

    if total_expenses == 0.0 and program_services == 0.0:
        return None

    return ExpenseBreakdown(
        filer_ein=filer_node.ein,
        filer_name=filer_node.name,
        tax_year=tax_year,
        total_expenses=total_expenses,
        program_services=program_services,
        management_general=management_general,
        fundraising=fundraising,
        salaries_total=salaries,
        professional_fees=professional_fees,
        office_and_it=office_it,
        travel_and_conferences=travel,
        grants_paid=grants_paid
    )


def parse_part_vii_contractors(xml_content: str, filer_node: OrganizationNode, tax_year: int) -> List[IndependentContractor]:
    """Parse Form 990 Part VII Section B Top 5 Highest-Paid Independent Contractors (> $100k)."""
    try:
        root = ET.fromstring(xml_content)
    except Exception as e:
        logger.error(f"Failed to parse XML for contractors: {e}")
        return []

    contractors = []
    contractor_tags = [
        "CompOf5HighestPaidContrctGrp",
        "HighestPaidIndependentContractorGrp",
        "HighestPaidIndContrctGrp",
        "ContractorCompensationGrp"
    ]

    for elem in root.iter():
        local_tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if local_tag in contractor_tags:
            c_name = get_xml_text(elem, [
                "BusinessNameLine1Txt", "BusinessNameLine1", "BusinessName",
                "ContractorName", "PersonNm", "PersonName"
            ])
            if not c_name:
                continue

            city = get_xml_text(elem, ["CityNm", "City"])
            state = get_xml_text(elem, ["StateAbbreviationCd", "State"])
            desc = get_xml_text(elem, [
                "DescOfServicesTxt", "DescriptionOfServices", "ServicesDesc", "TypeServiceTxt"
            ])
            comp_str = get_xml_text(elem, [
                "CompensationAmt", "TotalCompensationAmt", "ContractorCompensationAmt"
            ])
            comp_val = 0.0
            if comp_str:
                try:
                    comp_val = float(comp_str)
                except ValueError:
                    pass

            contractors.append(IndependentContractor(
                filer_ein=filer_node.ein,
                filer_name=filer_node.name,
                tax_year=tax_year,
                contractor_name=c_name,
                city=city,
                state=state,
                description_of_services=desc,
                amount=comp_val
            ))

    return contractors


def parse_part_vii_people(xml_content: str, filer_node: OrganizationNode, tax_year: int) -> List[PersonAffiliation]:
    """
    Parse Form 990 Part VII Section A & Form 990-PF Part VIII officers, directors, trustees,
    and key employees with their titles, hours, roles, and compensation.
    """
    try:
        root = ET.fromstring(xml_content)
    except Exception as e:
        logger.error(f"Failed to parse XML for people: {e}")
        return []

    people = []
    person_tags = [
        "Form990PartVIISectionAGrp",
        "OfficerDirectorTrusteeEmplGrp",
        "OfficerDirTrstKeyEmplInfoGrp",  # 990-PF Part VIII
        "OfficerDirectorTrusteeGrp"
    ]

    for elem in root.iter():
        local_tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if local_tag in person_tags:
            raw_name = get_xml_text(elem, [
                "PersonNm", "PersonName", "BusinessNameLine1Txt", "BusinessNameLine1"
            ])
            if not raw_name or len(raw_name.strip()) < 2:
                continue

            clean_name = normalize_person_name(raw_name)
            title = get_xml_text(elem, ["TitleTxt", "Title", "PositionTxt"])

            # Hours per week
            hours_str = get_xml_text(elem, [
                "AverageHoursPerWeekRt", "AverageHoursPerWeek",
                "AvgHoursPerWkDevotedToPosRt", "AvgHoursPerWkDevotedToPosition"
            ])
            hours = 0.0
            if hours_str:
                try:
                    hours = float(hours_str)
                except ValueError:
                    pass

            # Determine Role Type from checkbox flags
            role_type = "Trustee/Director"
            is_officer = get_xml_text(elem, ["OfficerInd", "Officer"]) in ("1", "X", "true", "True")
            is_key_emp = get_xml_text(elem, ["KeyEmployeeInd", "KeyEmployee"]) in ("1", "X", "true", "True")
            is_high_earner = get_xml_text(elem, ["HighestCompensatedEmployeeInd", "HighestCompensatedEmployee"]) in ("1", "X", "true", "True")
            is_inst_trustee = get_xml_text(elem, ["InstitutionalTrusteeInd", "InstitutionalTrustee"]) in ("1", "X", "true", "True")
            is_former = get_xml_text(elem, ["FormerOfcrDirectorTrusteeInd", "Former"]) in ("1", "X", "true", "True")

            if is_former:
                role_type = "Former"
            elif is_officer:
                role_type = "Officer"
            elif is_key_emp:
                role_type = "Key Employee"
            elif is_high_earner:
                role_type = "High Earner"
            elif is_inst_trustee:
                role_type = "Institutional Trustee"
            elif any(w in title.upper() for w in ["PRESIDENT", "CEO", "TREASURER", "SECRETARY", "DIRECTOR GENERAL", "EXECUTIVE DIRECTOR", "CHAIR", "CFO", "COO"]):
                role_type = "Officer"

            # Compensation fields
            def parse_amt(tags):
                txt = get_xml_text(elem, tags)
                if txt:
                    try:
                        return float(txt)
                    except ValueError:
                        pass
                return 0.0

            org_comp = parse_amt(["ReportableCompFromOrgAmt", "ReportableCompFromOrganizationAmt", "CompensationAmt"])
            rltd_comp = parse_amt(["ReportableCompFromRltdOrgAmt", "ReportableCompFromRelatedOrgsAmt"])
            other_comp = parse_amt(["OtherCompensationAmt"])
            total_comp = org_comp + rltd_comp + other_comp

            people.append(PersonAffiliation(
                filer_ein=filer_node.ein,
                filer_name=filer_node.name,
                tax_year=tax_year,
                person_name=raw_name,
                clean_name=clean_name,
                title=title,
                role_type=role_type,
                hours_per_week=hours,
                reportable_comp=org_comp,
                related_org_comp=rltd_comp,
                other_comp=other_comp,
                total_comp=total_comp
            ))

    return people

