"""Spare parts starter data — loaded into maint_spare_parts once, when the
table is empty (see seed_spare_parts). Edit/add parts in the Spare Parts
screen afterwards; re-seeding never touches existing rows.

Generated from the group's Machine Spare Parts Inventory workbook.
"""
from datetime import date, datetime

from .database import SessionLocal
from .models import MaintSparePart


SEED_SPARE_PARTS = [
    {'part_code': None, 'part_name': 'Ball Bearing 6001', 'machine': 'Magnetic drill m/c', 'manufacturer': None, 'unit': 'No', 'opening_qty': 2.0, 'qty_in': 0.0, 'qty_out': 1.0, 'min_stock_level': 1.0, 'unit_price': 250.0, 'supplier': 'Golul Enterprises', 'last_purchase_date': None},
    {'part_code': None, 'part_name': 'wire feeder roller', 'machine': 'mig welding m/c', 'manufacturer': 'RILLON', 'unit': 'No', 'opening_qty': 5.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 2.0, 'unit_price': 390.0, 'supplier': 'KMS', 'last_purchase_date': '2026-06-20'},
    {'part_code': 'N489912', 'part_name': 'carbon brush set', 'machine': 'AG-4', 'manufacturer': 'DEWALT', 'unit': 'No', 'opening_qty': 5.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 2.0, 'unit_price': 85.0, 'supplier': 'KMS', 'last_purchase_date': '2026-07-23'},
    {'part_code': 'N422682', 'part_name': 'carbon brush set', 'machine': 'AG-5', 'manufacturer': 'DEWALT', 'unit': 'No', 'opening_qty': 9.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 2.0, 'unit_price': 140.0, 'supplier': 'KMS', 'last_purchase_date': '2026-07-24'},
    {'part_code': '1607014171', 'part_name': 'carbon brush set', 'machine': 'AG-7', 'manufacturer': 'BOSCH', 'unit': 'No', 'opening_qty': 10.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 2.0, 'unit_price': 245.0, 'supplier': 'KMS', 'last_purchase_date': '2026-07-25'},
    {'part_code': '1607014171', 'part_name': 'carbon brush set', 'machine': 'cut off m/c', 'manufacturer': 'BOSCH', 'unit': 'No', 'opening_qty': 10.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 2.0, 'unit_price': 245.0, 'supplier': 'KMS', 'last_purchase_date': '2026-07-26'},
    {'part_code': '1607014176', 'part_name': 'carbon brush set', 'machine': 'straight grinder', 'manufacturer': 'BOSCH', 'unit': 'No', 'opening_qty': 10.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 2.0, 'unit_price': 260.0, 'supplier': 'KMS', 'last_purchase_date': '2026-07-27'},
    {'part_code': '580700013', 'part_name': 'carbon brush set', 'machine': 'Magnetic drill m/c', 'manufacturer': 'EIBENSTOCK', 'unit': 'No', 'opening_qty': 4.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 2.0, 'unit_price': 325.0, 'supplier': 'KMS', 'last_purchase_date': '2026-07-28'},
    {'part_code': '561243-02', 'part_name': 'armature', 'machine': 'AG-4', 'manufacturer': 'DEWALT', 'unit': 'No', 'opening_qty': 2.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 1.0, 'unit_price': 560.0, 'supplier': 'KMS', 'last_purchase_date': '2026-08-22'},
    {'part_code': 'N489911', 'part_name': 'field coil', 'machine': 'AG-4', 'manufacturer': 'DEWALT', 'unit': 'No', 'opening_qty': 2.0, 'qty_in': 0.0, 'qty_out': 1.0, 'min_stock_level': 1.0, 'unit_price': 550.0, 'supplier': 'KMS', 'last_purchase_date': '2026-08-22'},
    {'part_code': 'NA146600', 'part_name': 'armature', 'machine': 'AG-5', 'manufacturer': 'DEWALT', 'unit': 'No', 'opening_qty': 2.0, 'qty_in': 0.0, 'qty_out': 1.0, 'min_stock_level': 1.0, 'unit_price': 1550.0, 'supplier': 'KMS', 'last_purchase_date': '2026-08-22'},
    {'part_code': 'NA12148', 'part_name': 'field coil', 'machine': 'AG-5', 'manufacturer': 'DEWALT', 'unit': 'No', 'opening_qty': 2.0, 'qty_in': 0.0, 'qty_out': 1.0, 'min_stock_level': 1.0, 'unit_price': 2090.0, 'supplier': 'KMS', 'last_purchase_date': '2026-08-22'},
    {'part_code': '1619P15749', 'part_name': 'armature', 'machine': 'AG-7', 'manufacturer': 'BOSCH', 'unit': 'No', 'opening_qty': 2.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 1.0, 'unit_price': 1265.0, 'supplier': 'KMS', 'last_purchase_date': '2026-08-22'},
    {'part_code': '1619P15702', 'part_name': 'field coil', 'machine': 'AG-7', 'manufacturer': 'BOSCH', 'unit': 'No', 'opening_qty': 2.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 1.0, 'unit_price': 1810.0, 'supplier': 'KMS', 'last_purchase_date': '2026-08-22'},
    {'part_code': '1609B03639', 'part_name': 'armature', 'machine': 'cut off m/c', 'manufacturer': 'BOSCH', 'unit': 'No', 'opening_qty': 2.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 1.0, 'unit_price': 1754.0, 'supplier': 'KMS', 'last_purchase_date': '2026-08-22'},
    {'part_code': '1609B00135', 'part_name': 'field coil', 'machine': 'cut off m/c', 'manufacturer': 'BOSCH', 'unit': 'No', 'opening_qty': 2.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 1.0, 'unit_price': 2876.0, 'supplier': 'KMS', 'last_purchase_date': '2026-08-22'},
    {'part_code': None, 'part_name': '286213 rac tip', 'machine': 'airless spray', 'manufacturer': 'GRACO', 'unit': 'No', 'opening_qty': 2.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 1.0, 'unit_price': 2400.0, 'supplier': 'VVM TEC', 'last_purchase_date': '2026-08-24'},
    {'part_code': None, 'part_name': '286217 rac tip', 'machine': 'airless spray', 'manufacturer': 'GRACO', 'unit': 'No', 'opening_qty': 2.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 1.0, 'unit_price': 2400.0, 'supplier': 'VVM TEC', 'last_purchase_date': '2026-08-24'},
    {'part_code': None, 'part_name': '243161 tip guard', 'machine': 'airless spray', 'manufacturer': 'GRACO', 'unit': 'No', 'opening_qty': 2.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 1.0, 'unit_price': 2600.0, 'supplier': 'VVM TEC', 'last_purchase_date': '2026-08-24'},
    {'part_code': None, 'part_name': 'tip washer', 'machine': 'airless spray', 'manufacturer': 'GRACO', 'unit': 'No', 'opening_qty': 10.0, 'qty_in': 0.0, 'qty_out': 1.0, 'min_stock_level': 1.0, 'unit_price': 60.0, 'supplier': 'VVM TEC', 'last_purchase_date': '2026-08-24'},
    {'part_code': None, 'part_name': '189920 strainer', 'machine': 'airless spray', 'manufacturer': 'GRACO', 'unit': 'No', 'opening_qty': 2.0, 'qty_in': 0.0, 'qty_out': 1.0, 'min_stock_level': 1.0, 'unit_price': 1967.0, 'supplier': 'VVM TEC', 'last_purchase_date': '2026-08-24'},
    {'part_code': None, 'part_name': '244067 filter 60 mesh', 'machine': 'airless spray', 'manufacturer': 'GRACO', 'unit': 'No', 'opening_qty': 2.0, 'qty_in': 0.0, 'qty_out': 1.0, 'min_stock_level': 1.0, 'unit_price': 1230.0, 'supplier': 'VVM TEC', 'last_purchase_date': '2026-08-24'},
    {'part_code': None, 'part_name': '35-50 male cable connector', 'machine': 'mig welding m/c', 'manufacturer': 'RILLON', 'unit': 'No', 'opening_qty': 20.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 1.0, 'unit_price': 40.0, 'supplier': 'GB KORE ARC', 'last_purchase_date': '2026-07-07'},
    {'part_code': None, 'part_name': '35-50 female cable connector', 'machine': 'mig welding m/c', 'manufacturer': 'RILLON', 'unit': 'No', 'opening_qty': 20.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 1.0, 'unit_price': 40.0, 'supplier': 'GB KORE ARC', 'last_purchase_date': '2026-07-08'},
    {'part_code': 'ABW-CSP-001', 'part_name': 'twin wire contact tip', 'machine': 'ptw m/c', 'manufacturer': 'PRIMO', 'unit': 'No', 'opening_qty': 30.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 1.0, 'unit_price': 442.0, 'supplier': 'primo automation', 'last_purchase_date': '2026-08-24'},
    {'part_code': 'ABW-LST-CSP-002', 'part_name': 'tip holder', 'machine': 'ptw m/c', 'manufacturer': 'PRIMO', 'unit': 'No', 'opening_qty': 4.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 1.0, 'unit_price': 1328.0, 'supplier': 'primo automation', 'last_purchase_date': '2026-08-24'},
    {'part_code': 'ABW-CSP-003', 'part_name': 'brass nut', 'machine': 'ptw m/c', 'manufacturer': 'PRIMO', 'unit': 'mtr', 'opening_qty': 10.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 1.0, 'unit_price': 282.0, 'supplier': 'primo automation', 'last_purchase_date': '2026-08-24'},
    {'part_code': 'ABW-LST-CSP-003', 'part_name': 'tip holder clamp', 'machine': 'ptw m/c', 'manufacturer': 'PRIMO', 'unit': 'No', 'opening_qty': 2.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 1.0, 'unit_price': 3938.0, 'supplier': 'primo automation', 'last_purchase_date': '2026-08-24'},
    {'part_code': 'ABW-BSP-035', 'part_name': 'filter bag', 'machine': 'ptw m/c', 'manufacturer': 'PRIMO', 'unit': 'No', 'opening_qty': 1.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 1.0, 'unit_price': 2667.0, 'supplier': 'primo automation', 'last_purchase_date': '2026-08-24'},
    {'part_code': 'ABW-BSP-062', 'part_name': 'rubber beading', 'machine': 'ptw m/c', 'manufacturer': 'PRIMO', 'unit': 'No', 'opening_qty': 10.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 1.0, 'unit_price': 171.0, 'supplier': 'primo automation', 'last_purchase_date': '2026-08-24'},
    {'part_code': 'ABW-BSP-840', 'part_name': 'v-belt', 'machine': 'ptw m/c', 'manufacturer': 'PRIMO', 'unit': 'No', 'opening_qty': 2.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 1.0, 'unit_price': 586.0, 'supplier': 'primo automation', 'last_purchase_date': '2026-08-24'},
    {'part_code': 'ABW-BSP-043', 'part_name': 'drive roller for wire feeder', 'machine': 'ptw m/c', 'manufacturer': 'PRIMO', 'unit': 'set', 'opening_qty': 2.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 1.0, 'unit_price': 2066.0, 'supplier': 'primo automation', 'last_purchase_date': '2026-08-24'},
    {'part_code': 'ABW-BSP-044', 'part_name': 'gear for drive roll', 'machine': 'ptw m/c', 'manufacturer': 'PRIMO', 'unit': 'No', 'opening_qty': 2.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 1.0, 'unit_price': 2036.0, 'supplier': 'primo automation', 'last_purchase_date': '2026-08-24'},
    {'part_code': '220487', 'part_name': 'ELECTRODE 130A', 'machine': 'PLASMA MaxPro200', 'manufacturer': 'MESSER', 'unit': 'No', 'opening_qty': 20.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 5.0, 'unit_price': 1822.0, 'supplier': 'HYSPEED SOLUTION', 'last_purchase_date': '2026-04-15'},
    {'part_code': '220892', 'part_name': 'NOZZLE 130A', 'machine': 'PLASMA MaxPro201', 'manufacturer': 'MESSER', 'unit': 'No', 'opening_qty': 20.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 5.0, 'unit_price': 1179.0, 'supplier': 'HYSPEED SOLUTION', 'last_purchase_date': '2026-04-15'},
    {'part_code': '220536', 'part_name': 'SHIELD 130A', 'machine': 'PLASMA MaxPro202', 'manufacturer': 'MESSER', 'unit': 'No', 'opening_qty': 20.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 5.0, 'unit_price': 3804.0, 'supplier': 'HYSPEED SOLUTION', 'last_purchase_date': '2026-04-15'},
    {'part_code': '220937', 'part_name': 'ELECTRODE 200A', 'machine': 'PLASMA MaxPro203', 'manufacturer': 'MESSER', 'unit': 'No', 'opening_qty': 20.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 5.0, 'unit_price': 1853.0, 'supplier': 'HYSPEED SOLUTION', 'last_purchase_date': '2026-04-15'},
    {'part_code': '420044', 'part_name': 'NOZZLE 200A', 'machine': 'PLASMA MaxPro204', 'manufacturer': 'MESSER', 'unit': 'No', 'opening_qty': 20.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 5.0, 'unit_price': 1975.0, 'supplier': 'HYSPEED SOLUTION', 'last_purchase_date': '2026-04-15'},
    {'part_code': '420045', 'part_name': 'SHIELD 200A', 'machine': 'PLASMA MaxPro205', 'manufacturer': 'MESSER', 'unit': 'No', 'opening_qty': 20.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 5.0, 'unit_price': 3384.0, 'supplier': 'HYSPEED SOLUTION', 'last_purchase_date': '2026-04-15'},
    {'part_code': '28872', 'part_name': 'TORCH COOLANT', 'machine': 'PLASMA MaxPro206', 'manufacturer': 'MESSER', 'unit': 'ltr', 'opening_qty': 37.8, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 5.0, 'unit_price': 1155.82, 'supplier': 'HYSPEED SOLUTION', 'last_purchase_date': '2026-04-15'},
    {'part_code': None, 'part_name': '8*30 mm grub screw', 'machine': 'Magnetic drill m/c', 'manufacturer': 'EIBENSTOCK', 'unit': 'No', 'opening_qty': 50.0, 'qty_in': 0.0, 'qty_out': 4.0, 'min_stock_level': 5.0, 'unit_price': 40.0, 'supplier': 'KMS', 'last_purchase_date': '2026-08-05'},
    {'part_code': '224457', 'part_name': 'STRIAGHT SWIVEL', 'machine': 'airless spray', 'manufacturer': 'GRACO', 'unit': 'No', 'opening_qty': 1.0, 'qty_in': 0.0, 'qty_out': 1.0, 'min_stock_level': 1.0, 'unit_price': 4998.0, 'supplier': 'VVM TEC', 'last_purchase_date': '2026-09-09'},
    {'part_code': None, 'part_name': '3/8" PAINT HOSE 15 MTR LONG', 'machine': 'airless spray', 'manufacturer': 'GRACO', 'unit': 'No', 'opening_qty': 1.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 0.0, 'unit_price': 7500.0, 'supplier': 'VVM TEC', 'last_purchase_date': '2026-09-09'},
    {'part_code': None, 'part_name': '1/4" WHIP HOSE 1 MTR LONG', 'machine': 'airless spray', 'manufacturer': 'GRACO', 'unit': 'No', 'opening_qty': 1.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 0.0, 'unit_price': 1000.0, 'supplier': 'VVM TEC', 'last_purchase_date': '2026-09-09'},
    {'part_code': '235457', 'part_name': 'FLEX PLUS GUN', 'machine': 'airless spray', 'manufacturer': 'GRACO', 'unit': 'No', 'opening_qty': 1.0, 'qty_in': 0.0, 'qty_out': 0.0, 'min_stock_level': 0.0, 'unit_price': 21000.0, 'supplier': 'VVM TEC', 'last_purchase_date': '2026-09-09'},
]


def _pdate(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def seed_spare_parts() -> int:
    """Insert the starter parts once, only when the table is empty.

    Idempotent: returns 0 on every run after the first. Safe to call on
    every startup. Never overwrites rows edited in the portal.
    """
    db = SessionLocal()
    try:
        if db.query(MaintSparePart).first() is not None:
            return 0
        n = 0
        for row in SEED_SPARE_PARTS:
            db.add(MaintSparePart(
                part_code=row.get("part_code"), part_name=row["part_name"],
                machine=row.get("machine"), manufacturer=row.get("manufacturer"),
                unit=row.get("unit"), opening_qty=row.get("opening_qty") or 0,
                qty_in=row.get("qty_in") or 0, qty_out=row.get("qty_out") or 0,
                min_stock_level=row.get("min_stock_level") or 0,
                unit_price=row.get("unit_price") or 0, supplier=row.get("supplier"),
                last_purchase_date=_pdate(row.get("last_purchase_date")),
            ))
            n += 1
        db.commit()
        return n
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
