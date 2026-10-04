"""Generate a seeded ~2,000-SKU catalog: the real 21 synthetic SKUs plus realistic look-alikes and the rest of a
plausible HR-software vendor's price book.

Look-alikes are hard on purpose but decidable: each differs from a real SKU by something an order form would
print if it were sold (an edition, add-on vs base product, a region or deployment, a unit, a bundle), never by
spelling alone. Near-name siblings ("Premium Success Support" next to "Premium Support") are included too, but
none that the forms' own abbreviations can't tell apart from a real SKU (checked against every printed row).

  python scripts/make_big_catalog.py          # -> edge_cases/big_catalog/generated/catalog_2000.json
"""
from __future__ import annotations

import argparse
import json
import random
import re
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REAL = ROOT / "synthetic_order_form_dataset_50" / "sku_catalog.json"
OUT = ROOT / "edge_cases" / "big_catalog" / "generated" / "catalog_2000.json"

EDITIONS = ["Standard Edition", "Professional Edition", "Enterprise Edition", "Premium Edition", "Essentials",
            "Plus", "Lite", "Unlimited Edition"]
REGIONS = ["EMEA", "APAC", "Americas", "LATAM", "ANZ", "UK", "DACH", "Japan", "India", "Canada"]
DEPLOYMENTS = ["EU Data Residency", "US Data Residency", "Government Cloud", "Private Cloud", "FedRAMP"]
UNITS = ["Per User", "Per Employee", "Per Recruiter", "Per Hiring Manager", "Per 1,000 Employees", "Per Location"]
TERMS = ["Multi-Year", "Annual Prepaid", "Monthly", "Usage-Based"]

# Hand-written look-alikes of the real SKUs: near-name siblings and component variants a form could print.
SIBLINGS = {
    "TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON": [
        "Talent Intelligence Platform Premium Edition", "Talent Intelligence Platform Standard Edition (Add-on)",
        "Talent Intelligence Platform Enterprise Edition (Add-on)", "Talent Intelligence Premium Analytics (Add-on)",
        "Talent Intelligence Platform Premium Edition (Add-on) - Renewal Uplift"],
    "TALENT_INTELLIGENCE_PLATFORM": [
        "Talent Intelligence Platform Starter", "Talent Intelligence Hub", "Talent Insights Platform",
        "Talent Intelligence Platform Sandbox", "Talent Intelligence Platform Implementation"],
    "TALENT_ACQUISITION": [
        "Talent Acquisition Suite", "Talent Acquisition Starter", "Talent Acquisition Analytics",
        "Talent Acquisition Implementation", "Talent Acquisition Agency Portal", "Talent Attraction"],
    "TALENT_ACQUISITION_CORE": ["Talent Acquisition Core Plus", "Talent Acquisition Core Lite",
                                "Talent Acquisition Core Implementation"],
    "TALENT_ACQUISITION_CRM": ["Talent Acquisition CRM Plus", "Talent Acquisition CRM Events",
                               "Talent Acquisition CRM Campaigns (Add-on)", "Talent Relationship CRM"],
    "TALENT_ACQUISITION_CANDIDATE_EXPERIENCE": [
        "Talent Acquisition Candidate Experience Plus", "Talent Acquisition Candidate Engagement",
        "Talent Acquisition Candidate Experience Chatbot (Add-on)", "Candidate Experience Career Site"],
    "TALENT_ACQUISITION_AI_INTERVIEWER_AGENT_ADDON": [
        "Talent Acquisition AI Scheduling Agent Add-on", "Talent Acquisition AI Sourcing Agent Add-on",
        "Talent Acquisition AI Screening Agent Add-on"],
    "OVERAGES_TALENT_ACQUISITION_AI_INTERVIEWER_AGENT_ADDON": [
        "Overages - Talent Acquisition AI Scheduling Agent Add-on",
        "Overages - Talent Acquisition AI Sourcing Agent Add-on", "Overages - WhatsApp / SMS Credits"],
    "TALENT_ACQUISITION_TALENT_TRACKING_ADDON": ["Talent Acquisition Talent Pipeline Add-on",
                                                 "Talent Acquisition Talent Tracking Add-on Plus"],
    "TALENT_MANAGEMENT_ENTERPRISE": ["Talent Management Enterprise Plus", "Talent Management Enterprise Lite",
                                     "Talent Management Professional", "Talent Management Standard"],
    "TALENT_MANAGEMENT_CORE": ["Talent Management Core Plus", "Talent Management Core Lite",
                               "Talent Management Essentials"],
    "TALENT_MANAGEMENT_LEADER_EXPERIENCE": ["Talent Management Manager Experience",
                                            "Talent Management Leader Experience Plus",
                                            "Talent Management Employee Experience"],
    # No "Premier Support": forms print "Prem. Support", which can't tell Premier from Premium, so that sibling
    # would make the expected answer undecidable from the document.
    "PREMIUM_SUPPORT": ["Premium Support Plus", "Premium Support - 24x7", "Premium Success Support",
                        "Standard Support", "Enhanced Support"],
    "PROFESSIONAL_SERVICE": ["Professional Services - Fixed Fee", "Professional Service Hours (Prepaid)",
                             "Professional Services Bundle", "Professional Service - Advisory"],
    "SIGNATURE_SUCCESS": ["Signature Success Plus", "Signature Success Essentials", "Signature Services"],
    "SANDBOX": ["Sandbox - Full Copy", "Sandbox - Partial Copy", "Developer Sandbox", "Sandbox Refresh"],
    "ELEVATE_SUCCESS_PLAN": ["Elevate Success Plan Plus", "Elevate Success Plan Lite", "Accelerate Success Plan",
                             "Elevate Success Program"],
    "WHATSAPP_SMS_CREDITS": ["WhatsApp Credits", "SMS Credits", "Voice / SMS Credits", "WhatsApp / SMS Credits Bundle"],
    "TALENT_DESIGN": ["Talent Design Studio", "Talent Design Plus", "Talent Development"],
    "COPILOT": ["Copilot for Recruiters", "Copilot for Managers", "Copilot Plus"],
    "SKILLS_PORTFOLIO": ["Skills Portfolio Plus", "Skills Library", "Skills Portfolio Analytics"],
}

# The rest of the price book.
PRODUCT_LINES = [
    "Workforce Analytics", "Learning Experience", "Employee Engagement Surveys", "Performance Reviews",
    "Compensation Planning", "Succession Planning", "Onboarding", "Offboarding", "Internal Mobility",
    "Career Pathing", "Goals and OKRs", "Continuous Feedback", "Workforce Planning", "Headcount Planning",
    "Diversity Analytics", "Pay Equity Analytics", "People Analytics", "Employee Directory", "Org Charts",
    "Contingent Workforce", "Vendor Management", "Background Screening", "Reference Checking",
    "Video Interviewing", "Interview Scheduling", "Assessment Center", "Coding Assessments", "Job Distribution",
    "Programmatic Job Ads", "Referral Program", "Alumni Network", "Campus Recruiting", "Events Management",
    "Offer Management", "E-Signature", "Document Management", "Policy Management", "Case Management",
    "Knowledge Base", "Employee Help Desk", "Time and Attendance", "Absence Management", "Scheduling",
    "Payroll Connector", "Benefits Administration", "Expense Management", "Learning Content Library",
    "Mentoring", "Coaching", "Recognition and Rewards", "Wellbeing", "Pulse Surveys", "Exit Surveys",
    "Skills Inference", "Job Architecture", "Role Library", "Labor Market Data", "Compensation Benchmarks",
    "Data Warehouse Connector", "Reporting Studio", "Open API Access", "Single Sign-On", "Audit Log",
    "Bring Your Own Key", "Data Retention Controls", "Sandbox Environment", "Test Tenant",
]
SERVICES = ["Implementation", "Configuration Workshop", "Admin Training (Virtual)", "Admin Training (Onsite)",
            "Integration Build", "Data Migration", "Health Check", "Change Management", "Technical Account Manager",
            "Dedicated Success Manager", "Solution Architect Hours", "Custom Report Build"]
CREDITS = ["Background Check Credits", "Assessment Credits", "Job Posting Credits", "Translation Credits",
           "AI Token Credits", "Video Interview Minutes", "Text Message Credits", "Email Send Credits"]
CONNECTORS = ["Workday", "SAP SuccessFactors", "Oracle HCM", "ADP", "UKG", "BambooHR", "Microsoft Teams", "Slack",
              "Google Workspace", "Okta", "ServiceNow", "Salesforce", "LinkedIn", "Indeed", "Greenhouse"]

DESCRIPTIONS = ["Subscription to {n}", "Recurring subscription to {n}", "{n} capability for enterprise customers",
                "Access to {n} for the subscription term", "{n}, billed per the order form"]
INSTRUCTIONS = [
    "- Use Order Form Start Date for service start.\n- Revenue recognition for the mapped POB is straight-line by days.",
    "- Use Order Form Start Date for service start.",
    "- Capture delivery period and progress inputs for percentage-of-completion.",
    "- If the line is marked usage-based, capture the committed quantity.",
    "- Use the line's own dates if stated; otherwise the Order Form term.",
    "",
]


def code_of(name: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^A-Z0-9]+", "_", name.upper())).strip("_")


def build(n_total: int = 2000, seed: int = 11) -> list:
    rng = random.Random(seed)
    real = json.loads(REAL.read_text())
    real_codes = {e["sku_code"] for e in real}
    entries, names = [], {e["name"].lower() for e in real}

    def add(name: str, description: str = None):
        key = name.lower()
        code = code_of(name)
        if key in names or code in real_codes or any(e["sku_code"] == code for e in entries):
            return
        names.add(key)
        entries.append({
            "id": str(uuid.UUID(int=rng.getrandbits(128), version=4)),
            "sku_code": code,
            "name": name,
            "description": description or rng.choice(DESCRIPTIONS).format(n=name),
            "parsing_instructions": rng.choice(INSTRUCTIONS),
            "usage_count": rng.choice([0, 0, 0, 1, 2, 3, 5, 8, 13]),
        })

    # 1. look-alikes of the real SKUs
    for r in real:
        base = r["name"]
        for sib in SIBLINGS.get(r["sku_code"], []):
            add(sib)
        for region in rng.sample(REGIONS, 3):
            add(f"{base} - {region}")
        for dep in rng.sample(DEPLOYMENTS, 2):
            add(f"{base} ({dep})")
        if not base.endswith("Add-on") and "(Add-on)" not in base:
            add(f"{base} (Add-on)")
        for unit in rng.sample(UNITS, 2):
            add(f"{base} - {unit}")
        add(f"{base} - {rng.choice(TERMS)}")
    # 2. the rest of the price book
    while len(entries) + len(real) < n_total:
        kind = rng.random()
        if kind < 0.55:
            line = rng.choice(PRODUCT_LINES)
            parts = [line]
            if rng.random() < 0.7:
                parts.append(rng.choice(EDITIONS))
            name = " ".join(parts)
            if rng.random() < 0.25:
                name += f" - {rng.choice(REGIONS)}"
            elif rng.random() < 0.15:
                name += f" ({rng.choice(DEPLOYMENTS)})"
            elif rng.random() < 0.2:
                name += " (Add-on)"
        elif kind < 0.75:
            name = f"{rng.choice(SERVICES)} - {rng.choice(PRODUCT_LINES)}"
        elif kind < 0.88:
            name = f"{rng.choice(CREDITS)} - {rng.choice(['1,000 Pack', '10,000 Pack', '50,000 Pack', 'Overage'])}"
        else:
            name = f"{rng.choice(CONNECTORS)} Connector for {rng.choice(PRODUCT_LINES)}"
        add(name)
    catalog = entries + real
    rng.shuffle(catalog)
    return catalog


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()
    catalog = build(args.size, args.seed)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(catalog, indent=1) + "\n")
    print(f"{OUT.relative_to(ROOT)}: {len(catalog)} SKUs")


if __name__ == "__main__":
    main()
