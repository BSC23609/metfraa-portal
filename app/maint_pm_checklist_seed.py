"""Preventive Maintenance check-sheet templates (from the plant's PM check sheets).
Seeded idempotently; one row per check point per machine."""
from .database import SessionLocal
from .models import MaintPmChecklistItem

PM_CHECKLISTS = {
    'ARC WELDING': [
        (1, 'Cleaning of electrical panel', 'CLEAN', 'M'),
        (2, 'Check tightness of all electrical connection & Treminals', 'TIGHT', 'M'),
        (3, 'Check electrode Holder', 'Ok condition', 'M'),
        (4, 'Check MCB switch', 'Ok condition', 'M'),
        (5, 'Check Industrial Plug & Top', 'Fit to tight', 'M'),
        (6, 'Check Positive & negative terminal', 'Ok condition', 'M'),
        (7, 'Check & clean the machine transformer', 'CLEAN', 'M'),
    ],
    'CNC PLASMA': [
        (1, 'Cleaning of Controller (Inside)', 'CLEAN', 'M'),
        (2, 'Check Tightness of all connection', 'TIGHT', 'M'),
        (3, 'Check Pipe (air pipe)', 'NO LEAKAGE', 'M'),
        (4, 'Check Power & Earthing Connections', 'TIGHT', 'M'),
        (5, 'Check Torch body', 'OK CONDITION', 'M'),
        (6, 'Clean Nozzle Head', 'CLEAN', 'M'),
        (7, 'Check Servo Motor & Gear', 'OK CONDITION', 'M'),
    ],
    'MIG WELDING': [
        (1, 'Cleaning of electrical panel', 'Clean', 'M'),
        (2, 'Check tightness of all electrical connection & Treminals', 'Tight', 'M'),
        (3, 'Check Wire feeder control termination', 'Ok condition', 'M'),
        (4, 'Check MCB switch', 'Ok condition', 'M'),
        (5, 'Check Industrial Plug & Top', 'Fit to tight', 'M'),
        (6, 'Check positive & negative terminal lug', 'Ok condition', 'M'),
        (7, 'Check Main contactor & Semi conductors', 'Ok condition', 'M'),
        (8, 'Check & clean the machine transformer', 'Clean', 'M'),
    ],
    'PTW': [
        (1, 'Clean Electrical Panel', 'Clean', 'M'),
        (2, 'Clean Solenoid Valve', 'Clean', 'M'),
        (3, 'Power Source & Contactor connection', 'Tight', 'M'),
        (4, 'Check Wire Feeders Condition', 'Ok Condition', 'M'),
        (5, 'Check oil leakage', 'No Leakage', 'M'),
        (6, 'Check Conveyor Alignment Setting', 'Properly Align', 'M'),
        (7, 'Check Hydraulic Oil Level', 'UP TO 75 %', 'M'),
        (8, 'Check Bearing Conditions', 'Ok Condition', 'M'),
        (9, 'Check Roller Chain Greasing', 'Greasing', 'M'),
        (10, 'Changed Hydraulic Oil', 'Fill new oil', 'Y'),
    ],
    'COMPRESSOR': [
        (1, 'Cleaning of electrical panel', 'Clean', 'M'),
        (2, 'Check tightness of all electrical connection & Treminals', 'Tight', 'M'),
        (3, 'Check compressor motor coupling condition', 'Ok condition', 'M'),
        (4, 'check thermal Limit Switch /Emergency switch', 'Ok condition', 'M'),
        (5, 'Check Synthetic Oil level & Top up', 'Maintain 80%', 'M'),
        (6, 'Check controller condition', 'Ok condition', 'M'),
        (7, 'Check Load & Unload Relay', 'Ok condition', 'M'),
        (8, 'Check Air-fillter condition', 'Clean', 'M'),
        (9, 'Check the Radiator condition', 'Clean', 'M'),
    ],
    'UPS': [
        (1, 'Cleaning of electrical panel', 'Clean', 'M'),
        (2, 'Check tightness of all electrical connection & Terminals', 'Tight', 'M'),
        (3, 'Check battery voltage & terminal condition', 'Ok condition', 'M'),
        (4, 'Check input/output MCB switch', 'Ok condition', 'M'),
        (5, 'Check Industrial Plug & Top', 'Fit to tight', 'M'),
        (6, 'Check earthing connection', 'Ok condition', 'M'),
        (7, 'Check cooling fan & ventilation', 'Ok condition', 'M'),
    ],
    'EOT CRANE': [
        (1, 'Greasing Of Rope', 'GREASING', 'M'),
        (2, 'Greasing Of Snatch Block', 'GREASING', 'M'),
        (3, 'Greasing Of Wheel Bearing', 'GREASING', 'M'),
        (4, 'Check Electrical Wiring & Motor Terminal', 'TIGHT', 'M'),
        (5, 'Check all Limit S/W (CT, LT, HOIST)', 'Working', 'M'),
        (6, 'Check Emergency Switch', 'Working', 'M'),
        (7, 'Check Abnormality Sounds', 'No', 'M'),
    ],
    'SHOT BLASTING': [
        (1, 'Check nozzle and hose', 'Ok condition', 'M'),
        (2, 'Check tightness of all Air line connector', 'Tight', 'M'),
        (3, "Check O'ring & pop-up valve condition", 'Ok condition', 'M'),
        (5, 'Check Emergency Presure Relif Valve', 'Ok condition', 'M'),
        (6, 'Check valve condition', 'Ok condition', 'M'),
        (7, 'Check Air-Leakage', 'No leak', 'M'),
        (8, 'Check the Machine Moving wheel condition', 'Ok condition', 'M'),
    ],
    'AIRLESS SPRAY': [
        (1, 'Cleaning of Filter', 'CLEAN', 'M'),
        (2, 'Check tightness of all points (Connector)', 'TIGHT', 'M'),
        (3, 'Check motor Piston coupling condition', 'Ok condition', 'M'),
        (4, 'check Lubrication of Displacement Rod', 'Fully Lube', 'M'),
        (5, 'Check Lower Pump condition', 'Ok condition', 'M'),
        (6, 'Check Floting Ball condition', 'Ok condition', 'M'),
        (7, 'Overhauling the Pump Assy', 'TIGHT', 'M'),
    ],
}


def seed_pm_checklists() -> int:
    """Insert check-point templates for any machine that has none yet."""
    db = SessionLocal()
    n = 0
    try:
        existing = {m for (m,) in db.query(MaintPmChecklistItem.machine).distinct().all()}
        for machine, items in PM_CHECKLISTS.items():
            if machine in existing:
                continue
            for order, (sn, cp, std, frq) in enumerate(items):
                db.add(MaintPmChecklistItem(
                    machine=machine, sn=sn, check_point=cp, standard=std,
                    frequency=frq, sort_order=order, active=True))
                n += 1
        db.commit()
        return n
    finally:
        db.close()

