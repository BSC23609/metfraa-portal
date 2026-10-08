"""Seed the maintenance module: machine types + asset master.

Idempotent — safe to re-run. Upserts by machine-type key and asset_code.
Run once against Neon (new tables are created by create_all / INIT_DB):

    DATABASE_URL="postgresql://..." python scripts/seed_maint.py
"""
import csv, os
from datetime import date
from app.database import engine, SessionLocal, Base
from app import models  # noqa: F401 — register all tables
from app.models import MaintMachineType, MaintAsset

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(HERE, "app", "data", "maint_assets_seed.csv")

TYPES = [
    {"key": "breakdown_only", "name": "Breakdown only (no readings)", "reading_params": [], "meter_param": None},
    {"key": "screw_air_compressor", "name": "Screw / air compressor", "meter_param": "running_hrs",
     "reading_params": [
        {"code": "running_hrs", "label": "Running hours", "unit": "hrs", "cumulative": True},
        {"code": "pressure", "label": "Pressure", "unit": "bar"},
        {"code": "temp", "label": "Temperature", "unit": "C"},
        {"code": "voltage", "label": "Voltage", "unit": "V"},
        {"code": "current", "label": "Current", "unit": "A"},
        {"code": "load_hrs", "label": "Load hours", "unit": "hrs", "cumulative": True}]},
    {"key": "airless_spray", "name": "Airless spray", "meter_param": "meter_gallons",
     "reading_params": [
        {"code": "meter_gallons", "label": "Meter (gallons)", "unit": "gal", "cumulative": True},
        {"code": "ltr", "label": "Litres (from gallons)", "unit": "L", "derived": True, "scale_of": "meter_gallons", "factor": 3.785412, "agg": "sum"},
        {"code": "working_pressure", "label": "Working pressure", "unit": "psi"}]},
    {"key": "dg_set", "name": "DG set", "meter_param": "engine_hrs_end",
     "reading_params": [
        {"code": "engine_hrs_start", "label": "Engine hrs (start)", "unit": "hrs"},
        {"code": "engine_hrs_end", "label": "Engine hrs (end)", "unit": "hrs"},
        {"code": "run_time", "label": "Run time", "unit": "h", "derived": True, "diff_of": ["engine_hrs_end", "engine_hrs_start"], "agg": "sum"},
        {"code": "diesel_used", "label": "Diesel used", "unit": "L", "agg": "sum"},
        {"code": "kwh_start", "label": "kWh (start)", "unit": "kWh"},
        {"code": "kwh_end", "label": "kWh (end)", "unit": "kWh"},
        {"code": "energy_kwh", "label": "Energy", "unit": "kWh", "derived": True, "diff_of": ["kwh_end", "kwh_start"], "agg": "sum"}]},
    {"key": "ptw_welder", "name": "PTW welder (weld length)", "meter_param": None,
     "reading_params": [
        {"code": "lh_mtr", "label": "LH weld length", "unit": "m", "cumulative": True},
        {"code": "rh_mtr", "label": "RH weld length", "unit": "m", "cumulative": True},
        {"code": "lh_time", "label": "LH weld time", "unit": "min", "cumulative": True},
        {"code": "rh_time", "label": "RH weld time", "unit": "min", "cumulative": True},
        {"code": "avg_length", "label": "Avg weld length", "unit": "m", "derived": True, "avg_of": ["lh_mtr", "rh_mtr"]},
        {"code": "avg_time", "label": "Avg weld time", "unit": "min", "derived": True, "avg_of": ["lh_time", "rh_time"]}]},
    {"key": "cnc_plasma", "name": "CNC plasma (event-only)", "reading_params": [], "meter_param": None},
]


def _f(v):
    return float(v) if str(v).strip() != "" else None

def _i(v):
    return int(float(v)) if str(v).strip() != "" else None

def _d(v):
    return date.fromisoformat(v) if str(v).strip() != "" else None


def run():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # types
        tmap = {}
        for t in TYPES:
            row = db.query(MaintMachineType).filter_by(key=t["key"]).first()
            if not row:
                row = MaintMachineType(key=t["key"])
                db.add(row)
            row.name = t["name"]
            row.reading_params = t["reading_params"]
            row.meter_param = t["meter_param"]
            row.active = True
            db.flush()
            tmap[t["key"]] = row.id
        # assets
        ins = upd = 0
        with open(CSV_PATH, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                a = db.query(MaintAsset).filter_by(asset_code=r["asset_code"]).first()
                if not a:
                    a = MaintAsset(asset_code=r["asset_code"]); db.add(a); ins += 1
                else:
                    upd += 1
                a.description = r["description"]
                a.category = r["category"] or None
                a.type_id = tmap.get(r["machine_type"], tmap["breakdown_only"])
                a.serial_model_no = r["serial_model_no"] or None
                a.manufacturer = r["manufacturer"] or None
                a.location = r["location"] or None
                a.acquisition_date = _d(r["acquisition_date"])
                a.acquisition_value = _f(r["acquisition_value"])
                a.capacity = _f(r["capacity"])
                a.capacity_unit = r["capacity_unit"] or None
                a.mfg_year = _i(r["mfg_year"])
                a.active = (r["active"] == "true")
        db.commit()
        total = db.query(MaintAsset).count()
        print(f"machine types: {db.query(MaintMachineType).count()}")
        print(f"assets inserted: {ins}, updated: {upd}, total now: {total}")
    finally:
        db.close()


if __name__ == "__main__":
    run()
