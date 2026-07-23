"""Metfraa expense validators — ported from bsg-portal validators.js.

Each validator returns (ok, payload_or_error, total). Payload is the cleaned,
denormalised form data stored as the submission's source of truth.
"""
import re
from datetime import datetime

from .policy import PURPOSE_CATEGORIES, get_form, get_level_entitlement, get_rate

DTR_MODES = ["bus", "bike_taxi", "auto", "share_auto"]
DTR_MODES_NEEDING_BILL = {"bike_taxi", "auto", "share_auto"}


def _s(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def _is_date(v) -> bool:
    if not isinstance(v, str) or not v.strip():
        return False
    try:
        datetime.strptime(v.strip()[:10], "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _period_from_date(d: str) -> str:
    m = re.match(r"^(\d{4})-(\d{2})", (d or "").strip())
    return f"{m.group(1)}-{m.group(2)}" if m else ""


def _err(msg):
    return False, msg, 0.0


def _ok(payload, total):
    return True, payload, round(total, 2)


# ---------------------------------------------------------------- local

def validate_met_local(inp: dict, employee_level: str):
    if not _s(inp.get("period")):
        return _err("Period required")
    vt = _s(inp.get("vehicle_type"))
    rate = get_rate("local", vt)
    if not rate:
        return _err("Invalid vehicle type")
    trips_in = inp.get("trips") or []
    if not trips_in:
        return _err("At least one trip is required")
    total, trips = 0.0, []
    is_car = "car" in vt.lower() or "car" in rate["label"].lower()
    for t in trips_in:
        if not _is_date(t.get("date")):
            return _err("Each trip needs a date")
        if not _s(t.get("from")):
            return _err("Each trip needs a from location")
        if not _s(t.get("to")):
            return _err("Each trip needs a to location")
        km = _num(t.get("km"))
        if not km or km <= 0:
            return _err("Each trip needs a positive KM value")
        if km < 5:
            return _err("Trips under 5 km are not eligible per policy")
        if is_car and km < 80:
            return _err(f"Car travel is not applicable for trips under 80 km (this trip is {km:g} km). Use a two-wheeler for shorter distances.")
        amount = round(km * rate["rate_per_km"], 2)
        total += amount
        trips.append({"date": t["date"], "from": _s(t.get("from")), "to": _s(t.get("to")),
                      "purpose": _s(t.get("purpose")), "km": km, "amount": amount})
    return _ok({"period": inp["period"], "vehicle_type": vt, "vehicle_label": rate["label"],
                "rate_per_km": rate["rate_per_km"], "vehicle_reg": _s(inp.get("vehicle_reg")),
                "trips": trips}, total)


# ---------------------------------------------------------------- cab

def validate_met_cab(inp: dict, employee_level: str):
    meta = get_form("cab") or {}
    min_km = meta.get("min_km", 80)
    rides_in = inp.get("rides") or []
    if not rides_in:
        return _err("At least one cab trip is required")
    total, rides = 0.0, []
    for r in rides_in:
        if not _is_date(r.get("date")):
            return _err("Each cab trip needs a date")
        if not _s(r.get("pickup")):
            return _err("Each cab trip needs a pickup location")
        if not _s(r.get("drop")):
            return _err("Each cab trip needs a drop location")
        if not _s(r.get("purpose")):
            return _err("Each cab trip needs a purpose")
        km = _num(r.get("km"))
        if not km or km <= 0:
            return _err("Each cab trip needs a positive distance (km)")
        if km < min_km:
            return _err(f"Cab reimbursement is not applicable for trips under {min_km} km (this trip is {km:g} km).")
        fare = _num(r.get("fare"))
        if not fare or fare <= 0:
            return _err("Each cab trip needs the fare amount paid (₹)")
        total += fare
        rides.append({"date": r["date"], "time": _s(r.get("time")), "pickup": _s(r.get("pickup")),
                      "drop": _s(r.get("drop")), "km": km, "fare": round(fare, 2),
                      "passengers": _s(str(r.get("passengers") or "1")), "purpose": _s(r.get("purpose")),
                      "notes": _s(r.get("notes"))})
    period = _s(inp.get("period")) or _period_from_date(sorted(x["date"] for x in rides)[0])
    return _ok({"rides": rides, "period": period}, total)


# ---------------------------------------------------------------- accommodation

def validate_met_accommodation(inp: dict, employee_level: str):
    ent = get_level_entitlement("accommodation", employee_level)
    if not ent:
        return _err(f"No accommodation policy defined for level {employee_level}")
    if not _s(inp.get("period")):
        return _err("Period required")
    entries_in = inp.get("entries") or []
    if not entries_in:
        return _err("At least one accommodation entry is required")
    total, entries = 0.0, []
    for e in entries_in:
        if not _is_date(e.get("date")):
            return _err("Each entry needs a date")
        if not _s(e.get("location")):
            return _err("Each entry needs a location")
        amt = _num(e.get("amount"))
        if not amt or amt <= 0:
            return _err("Each entry needs a positive amount")
        total += amt
        entries.append({"date": e["date"], "location": _s(e.get("location")), "hotel": _s(e.get("hotel")),
                        "bill_no": _s(e.get("bill_no")), "amount": round(amt, 2)})
    return _ok({"period": inp["period"], "level": employee_level,
                "daily_limit": ent["daily_limit"], "entries": entries}, total)


# ---------------------------------------------------------------- outstation

def validate_met_outstation(inp: dict, employee_level: str):
    ent = get_level_entitlement("outstation", employee_level)
    if not ent:
        return _err(f"No outstation policy defined for level {employee_level}")
    if not _s(inp.get("period")):
        return _err("Period required")
    trips_in = inp.get("trips") or []
    if not trips_in:
        return _err("At least one trip is required")
    total, trips = 0.0, []
    for trip in trips_in:
        if not _s(trip.get("place")):
            return _err("Each trip needs a destination")
        if not _is_date(trip.get("from_date")):
            return _err("Each trip needs a from date")
        if not _is_date(trip.get("to_date")):
            return _err("Each trip needs a to date")
        if not _s(trip.get("purpose")):
            return _err("Each trip needs a purpose")
        cats = {"travel": [], "accommodation": [], "food": [], "local_conveyance": [], "others": []}
        for cat in cats:
            for it in (trip.get("categories") or {}).get(cat) or []:
                amt = _num(it.get("amount"))
                if not amt or amt <= 0:
                    continue
                if not _is_date(it.get("date")):
                    return _err(f"{cat} entry needs a valid date")
                cats[cat].append({"date": it["date"], "desc": _s(it.get("desc")), "amount": round(amt, 2)})
                total += amt
        trips.append({"place": _s(trip.get("place")), "from_date": trip["from_date"], "to_date": trip["to_date"],
                      "purpose": _s(trip.get("purpose")), "manager_approval": _s(trip.get("manager_approval")),
                      "categories": cats})
    return _ok({"period": inp["period"], "level": employee_level, "entitlement": ent, "trips": trips}, total)


# ---------------------------------------------------------------- misc

def validate_met_misc(inp: dict, employee_level: str):
    items_in = inp.get("items") or []
    if not items_in:
        return _err("At least one item is required")
    total, items = 0.0, []
    for it in items_in:
        if not _is_date(it.get("date")):
            return _err("Each item needs a date")
        if not _s(it.get("purpose")):
            return _err("Each item needs a purpose")
        amt = _num(it.get("amount"))
        if not amt or amt <= 0:
            return _err("Each item needs a positive amount (₹)")
        total += amt
        items.append({"date": it["date"], "purpose": _s(it.get("purpose")), "amount": round(amt, 2)})
    period = _s(inp.get("period")) or _period_from_date(sorted(x["date"] for x in items)[0])
    return _ok({"items": items, "period": period}, total)


# ---------------------------------------------------------------- advance

def validate_met_advance(inp: dict, employee_level: str):
    amt = _num(inp.get("amount"))
    if not amt or amt <= 0:
        return _err("Estimated advance amount (₹) is required and must be greater than zero.")
    if not _s(inp.get("destination")):
        return _err("Destination is required")
    if not _is_date(inp.get("travel_from")):
        return _err("Travel start date is required")
    if not _is_date(inp.get("travel_to")):
        return _err("Travel end date is required")
    if inp["travel_to"] < inp["travel_from"]:
        return _err("Travel end date must be on or after the start date")
    if not _s(inp.get("purpose")):
        return _err("Purpose / justification is required")
    return _ok({"destination": _s(inp.get("destination")), "travel_from": inp["travel_from"],
                "travel_to": inp["travel_to"], "purpose": _s(inp.get("purpose")),
                "mode": _s(inp.get("mode")) or None, "notes": _s(inp.get("notes")) or None,
                "amount": round(amt, 2), "period": _period_from_date(inp["travel_from"])}, amt)


# ---------------------------------------------------------------- dtr

def validate_met_dtr(inp: dict, employee_level: str):
    entries_in = inp.get("entries") or []
    if not entries_in:
        return _err("Add at least one daily travel entry.")
    if len(entries_in) > 200:
        return _err("Too many entries in a single submission (max 200).")
    total, clean = 0.0, []
    for i, e in enumerate(entries_in):
        lbl = f"Entry #{i + 1}"
        e = e or {}
        if not _is_date(e.get("date")):
            return _err(f"{lbl}: date is required.")
        mode = _s(e.get("mode"))
        if mode not in DTR_MODES:
            return _err(f"{lbl}: mode of commute must be Bus, Bike Taxi, Auto, or Share Auto.")
        if not _s(e.get("from")):
            return _err(f"{lbl}: From location is required.")
        if not _s(e.get("to")):
            return _err(f"{lbl}: To location is required.")
        fare = _num(e.get("fare"))
        if not fare or fare <= 0:
            return _err(f"{lbl}: fare must be greater than zero.")

        purpose = _s(e.get("purpose_category"))
        if not purpose:
            return _err(f"{lbl}: pick a Purpose.")
        if purpose not in PURPOSE_CATEGORIES:
            return _err(f"{lbl}: invalid Purpose.")

        project_id, client_name, other_reason = None, None, None
        raw_cli = _s(e.get("client_name"))
        raw_other = _s(e.get("purpose_other_reason"))
        if purpose == "project_visit":
            try:
                project_id = int(e.get("project_id"))
                assert project_id > 0
            except (TypeError, ValueError, AssertionError):
                return _err(f"{lbl}: select a Project.")
        elif purpose == "site_visit":
            if not raw_cli:
                return _err(f"{lbl}: please enter the site name or location.")
            client_name = raw_cli[:200]
        elif purpose == "purchase_visit":
            if not raw_cli:
                return _err(f"{lbl}: please enter the vendor / supplier name.")
            client_name = raw_cli[:200]
        elif purpose == "sales_visit":
            if not raw_cli:
                return _err(f"{lbl}: please enter the client / prospect name.")
            client_name = raw_cli[:200]
        elif purpose == "other":
            if not raw_other:
                return _err(f'{lbl}: please describe the reason for the "Other" purpose.')
            other_reason = raw_other[:500]

        needs_bill = mode in DTR_MODES_NEEDING_BILL
        if needs_bill and not e.get("has_bill"):
            return _err(f"{lbl}: a bill or receipt is required for {mode.replace('_', ' ')}.")

        clean.append({"date": e["date"], "mode": mode, "from": _s(e.get("from")), "to": _s(e.get("to")),
                      "fare": round(fare, 2), "remarks": (_s(e.get("remarks"))[:300] or None),
                      "purpose_category": purpose, "project_id": project_id,
                      "client_name": client_name, "purpose_other_reason": other_reason})
        total += fare
    period = _s(inp.get("period")) or _period_from_date(sorted(x["date"] for x in clean)[0])
    return _ok({"period": period, "entries": clean}, total)


VALIDATORS = {
    "met_local": validate_met_local,
    "met_cab": validate_met_cab,
    "met_accommodation": validate_met_accommodation,
    "met_outstation": validate_met_outstation,
    "met_misc": validate_met_misc,
    "met_advance": validate_met_advance,
    "met_dtr": validate_met_dtr,
}


def validate(form_type: str, inp: dict, employee_level: str):
    fn = VALIDATORS.get(form_type)
    if not fn:
        return False, "Unknown form type", 0.0
    return fn(inp or {}, employee_level or "L1")
