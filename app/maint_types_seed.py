"""Ensure the kWh-meter reading fields for CNC Plasma, PTW and Air Compressor.

These machines log a running energy meter. Each day the user enters the current
meter reading ("Present kWh"); the app then shows the Previous reading, the
Difference (today - previous) and a running Cumulative. Idempotent: safe to run
on every startup — it only writes when something differs.
"""
from .database import SessionLocal
from .models import MaintAsset, MaintMachineType

# One shared field set: present (input) + derived previous / difference / cumulative.
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

# machine-type key -> friendly name
TYPES = {
    "cnc_plasma": "CNC Plasma",
    "ptw_welder": "PTW",
    "screw_air_compressor": "Air Compressor",
}
# asset_code -> machine-type key (link these assets to the metered type)
ASSET_TYPE = {
    "M004": "cnc_plasma",            # CNC PLASMA
    "M007": "ptw_welder",            # PTW
    "M006": "screw_air_compressor",  # AIR COMPRESSOR-01
    "M061": "screw_air_compressor",  # AIR COMPRESSOR-02
    "M066": "screw_air_compressor",  # SCREW COMPRESSOR
}


def seed_reading_types() -> int:
    """Returns the number of types/assets touched."""
    db = SessionLocal()
    touched = 0
    try:
        type_by_key = {}
        for key, name in TYPES.items():
            t = db.query(MaintMachineType).filter(MaintMachineType.key == key).first()
            if not t:
                t = MaintMachineType(key=key, name=name, reading_params=[], active=True)
                db.add(t)
                db.flush()
                touched += 1
            if t.reading_params != ENERGY_PARAMS or t.meter_param != METER_PARAM:
                t.reading_params = ENERGY_PARAMS
                t.meter_param = METER_PARAM
                if not t.name:
                    t.name = name
                touched += 1
            type_by_key[key] = t

        for code, key in ASSET_TYPE.items():
            a = db.query(MaintAsset).filter(MaintAsset.asset_code == code).first()
            if not a:
                continue
            want = type_by_key.get(key)
            cur_key = a.machine_type.key if a.machine_type else None
            if want and cur_key != key:
                a.type_id = want.id
                touched += 1

        db.commit()
        return touched
    finally:
        db.close()
