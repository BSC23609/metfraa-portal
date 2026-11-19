"""Ensure the kWh-meter reading fields for CNC Plasma, PTW and Air Compressor.

These machines log a running energy meter. Each day the user enters the current
meter reading ("Present kWh"); the app then shows the Previous reading, the
Difference (today - previous) and a running Cumulative, matching the plant's
logbook sheet.

NON-DESTRUCTIVE + SELF-HEALING: existing reading fields are never removed. Any
field still present in a machine's stored readings is recovered (re-added) if it
is missing from the type, so PTW's and the compressors' earlier fields and data
come back; the kWh fields are then appended if absent. Idempotent.
"""
from .database import SessionLocal
from .models import MaintAsset, MaintMachineType, MaintReading

# The kWh fields to ensure: present (input) + derived previous / difference / cumulative.
ENERGY_PARAMS = [
    {"code": "present_kwh", "label": "Present kWh", "unit": "kWh"},
    {"code": "previous_kwh", "label": "Previous kWh", "unit": "kWh",
     "derived": True, "prev_of": "present_kwh"},
    {"code": "difference", "label": "Difference", "unit": "kWh",
     "derived": True, "delta_of": "present_kwh", "agg": "sum"},
    {"code": "cumulative", "label": "Cumulative", "unit": "kWh",
     "derived": True, "running_of": "present_kwh"},
]
METER_PARAM = "present_kwh"
ENERGY_CODES = {p["code"] for p in ENERGY_PARAMS}

TYPES = {
    "cnc_plasma": "CNC Plasma",
    "ptw_welder": "PTW",
    "screw_air_compressor": "Air Compressor",
}
ASSET_TYPE = {
    "M004": "cnc_plasma",            # CNC PLASMA
    "M007": "ptw_welder",            # PTW
    "M006": "screw_air_compressor",  # AIR COMPRESSOR-01
    "M061": "screw_air_compressor",  # AIR COMPRESSOR-02
    "M066": "screw_air_compressor",  # SCREW COMPRESSOR
}

# Nicer labels/units for recovered raw field codes.
KNOWN = {
    "kwh": ("kWh", "kWh"), "present_kwh": ("Present kWh", "kWh"),
    "hours": ("Hours", "hrs"), "run_hours": ("Run hours", "hrs"),
    "running_hours": ("Running hours", "hrs"), "hour_meter": ("Hour meter", "hrs"),
    "pressure": ("Pressure", "bar"), "amps": ("Amps", "A"),
    "voltage": ("Voltage", "V"), "temp": ("Temperature", "C"),
    "load": ("Load", "%"),
}


def _recovered_param(code):
    if code in KNOWN:
        lbl, unit = KNOWN[code]
        return {"code": code, "label": lbl, "unit": unit}
    return {"code": code, "label": code.replace("_", " ").strip().title() or code}


def seed_reading_types() -> int:
    db = SessionLocal()
    touched = 0
    try:
        type_by_key = {}
        for key, name in TYPES.items():
            t = (db.query(MaintMachineType)
                 .filter(MaintMachineType.key == key).first())
            if not t:
                t = MaintMachineType(key=key, name=name, reading_params=[], active=True)
                db.add(t)
                db.flush()
                touched += 1
            type_by_key[key] = t

        # Make sure the assets point at the right type first, so recovery can see
        # their stored readings.
        for code, key in ASSET_TYPE.items():
            a = db.query(MaintAsset).filter(MaintAsset.asset_code == code).first()
            if not a:
                continue
            want = type_by_key.get(key)
            cur_key = a.machine_type.key if a.machine_type else None
            if want and cur_key != key:
                a.type_id = want.id
                touched += 1
        db.flush()

        for key, t in type_by_key.items():
            params = list(t.reading_params or [])
            codes = {p.get("code") for p in params}

            # 1) recover any field codes still present in this type's readings
            asset_ids = [a.id for a in db.query(MaintAsset)
                         .filter(MaintAsset.type_id == t.id).all()]
            seen = []
            if asset_ids:
                for r in (db.query(MaintReading)
                          .filter(MaintReading.asset_id.in_(asset_ids)).all()):
                    for c in (r.values or {}):
                        if c and c not in codes and c not in ENERGY_CODES and c not in seen:
                            seen.append(c)
            recovered = [_recovered_param(c) for c in seen]

            # 2) append the kWh fields that are missing
            missing_energy = [p for p in ENERGY_PARAMS if p["code"] not in codes]

            new_params = params + recovered + missing_energy
            if new_params != params:
                t.reading_params = new_params
                touched += 1
            if not t.meter_param:
                t.meter_param = METER_PARAM
                touched += 1
            if not t.name:
                t.name = TYPES[key]

        db.commit()
        return touched
    finally:
        db.close()
