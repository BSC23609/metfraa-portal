"""Metfraa expense policy — rates, caps & rules. Ported from bsg-portal policy.js.

Single source of truth: update this file when HR revises the policy.
(BSC forms stripped — portal is Metfraa-only per scope decision.)
"""

POLICY = {
    "name": "Metfraa Steel Buildings Pvt. Ltd.",
    "short": "Metfraa",
    "hr_email": "admin@metfraa.com",
    "levels": {
        "L1": "L1 — Junior Level",
        "L2": "L2 — Senior Level",
        "L3": "L3 — Managerial Level",
    },
    "forms": {
        "local": {
            "title": "Local Travel Allowance",
            "rates": {
                "bike": {"rate_per_km": 4, "label": "Bike / 2-Wheeler"},
                "car": {"rate_per_km": 10, "label": "Car / 4-Wheeler"},
            },
            "rules": [
                "Includes fuel, maintenance and service costs — no additional vehicle expenses reimbursed.",
                "Car / 4-Wheeler applies only to journeys of 80 km or more (up and down combined).",
                "Travel plan form and manager approval mandatory 1–2 days in advance.",
                "Travel under 5 km when reporting directly to a different location is NOT eligible.",
            ],
        },
        "cab": {
            "title": "Cab Reimbursement",
            "min_km": 80,
            "rules": [
                "Applicable only for journeys of 80 km or more (up and down combined).",
                "Attach the cab/taxi bill or receipt for the fare claimed.",
                "For emergencies / late-night travel, document the reason clearly.",
            ],
        },
        "accommodation": {
            "title": "Monthly Accommodation Reimbursement",
            "per_level": {"L1": {"daily_limit": 1000}, "L2": {"daily_limit": 1250}, "L3": {"daily_limit": 1500}},
            "rules": [
                "Economical accommodation is mandatory.",
                "Itemised bills / hotel invoices required for every claim.",
                "Submit on or before the 28th of every month.",
            ],
        },
        "outstation": {
            "title": "Outstation Travel Reimbursement",
            "per_level": {
                "L1": {"train": "Sleeper", "bus": "Sleeper", "food_per_day": 250},
                "L2": {"train": "Sleeper", "bus": "Sleeper", "food_per_day": 350},
                "L3": {"train": "3rd AC", "bus": "AC Class", "food_per_day": 500},
            },
            "rules": [
                "All reimbursements must be approved by the Reporting Manager prior to submission.",
                "Submit valid bills — tickets, hotel bills, other invoices.",
                "Submit all claims to HR on or before the 28th of every month.",
            ],
        },
        "misc": {
            "title": "Miscellaneous Reimbursements",
            "rules": [
                "Each item needs a date, purpose and amount.",
                "Attach the bill / receipt for every item.",
            ],
        },
        "advance": {
            "title": "Travel Advance Request",
            "rules": [
                "For upcoming trips only — submit before the travel date.",
                "State the estimated amount and clear justification.",
                "Settle after the trip with actual bills.",
            ],
        },
        "dtr": {
            "title": "Daily Travel Reimbursement",
            "rules": [
                "One entry per commute trip; bills required for Bike Taxi / Auto / Share Auto.",
                "Bus travel needs no bill.",
            ],
        },
    },
}

FORM_META = {
    "met_local": {"policy": "local", "title": "Local Travel Allowance", "code": "LTA", "icon": "🛵"},
    "met_cab": {"policy": "cab", "title": "Cab Reimbursement", "code": "CAB", "icon": "🚕"},
    "met_accommodation": {"policy": "accommodation", "title": "Monthly Accommodation", "code": "ACC", "icon": "🏨"},
    "met_outstation": {"policy": "outstation", "title": "Outstation Travel", "code": "OUT", "icon": "🚆"},
    "met_dtr": {"policy": "dtr", "title": "Daily Travel Reimbursement", "code": "DTR", "icon": "🚌"},
    "met_misc": {"policy": "misc", "title": "Miscellaneous", "code": "MISC", "icon": "🧾"},
    "met_advance": {"policy": "advance", "title": "Travel Advance", "code": "ADV", "icon": "💵"},
}

PURPOSE_CATEGORIES = [
    "project_visit", "site_visit", "sales_visit", "metfraa_office",
    "metfraa_factory", "purchase_visit", "other",
]


def get_form(policy_key: str) -> dict | None:
    return POLICY["forms"].get(policy_key)


def get_rate(policy_key: str, vehicle_type: str) -> dict | None:
    f = get_form(policy_key)
    return (f or {}).get("rates", {}).get(vehicle_type)


def get_level_entitlement(policy_key: str, level: str) -> dict | None:
    f = get_form(policy_key)
    return (f or {}).get("per_level", {}).get(level)
