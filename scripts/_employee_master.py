"""
Metfraa KPI v2 — Final employee master.

37 users total: 34 KPI-tracked + 3 top-level admins.
Each entry maps to the OLD_seed_data (if applicable) to preserve KPI definitions.

Fields:
- code:  Employee code (login username; UNIQUE)
- name:  Full name
- phone: Contact number
- email: Company or personal email (nullable — admin can add later)
- designation
- department
- is_admin: Admin panel access
- can_submit_task_report: Whether the daily task-report screen is offered
- old_name: Name in the old seed to preserve KPI definitions (None = fresh add, no KPIs)
"""

EMPLOYEE_MASTER = [
    # ================== ADMINS ==================
    {"code": "MET-CEO",    "name": "Gourav Saraf",                 "phone": "9884696666",  "email": None,                          "designation": "CEO",                                   "department": "Executive",           "is_admin": True,  "can_submit_task_report": False, "old_name": None},
    {"code": "MET-MD",     "name": "Velarasu",                     "phone": "9787720731",  "email": None,                          "designation": "MD",                                    "department": "Executive",           "is_admin": True,  "can_submit_task_report": False, "old_name": None},
    {"code": "MET-ADMIN",  "name": "Jeeva",                        "phone": "739595956648","email": None,                          "designation": "Admin",                                 "department": "IT & Admin",          "is_admin": True,  "can_submit_task_report": False, "old_name": None},

    # ================== KPI-TRACKED EMPLOYEES (34) ==================
    # Design & Engineering (3)
    {"code": "MET51", "name": "KHAJA SHERIFF",              "phone": "7010507589", "email": "khajasheriff.m@metfraa.com", "designation": "GM - Designing and Engineering",       "department": "Design & Engineering", "is_admin": False, "can_submit_task_report": True,  "old_name": "Khaja Sheriff"},
    {"code": "MET94", "name": "GOPI MAHENDIRAN M",          "phone": "9094860619", "email": "m.gopi@metfraa.com",         "designation": "Detailer",                             "department": "Design & Engineering", "is_admin": False, "can_submit_task_report": True,  "old_name": "Gopi Mahendiran M"},
    {"code": "MET95", "name": "B MANSOOR",                  "phone": "9500179533", "email": "mansoor@metfraa.com",        "designation": "Senior Checker",                       "department": "Design & Engineering", "is_admin": False, "can_submit_task_report": True,  "old_name": "Mansoor"},

    # Projects (12)
    {"code": "MET01",  "name": "RAJASEKAR L",               "phone": "9841888301", "email": "lrajasekar1984@gmail.com",   "designation": "Site Supervisor",                      "department": "Projects", "is_admin": False, "can_submit_task_report": True,  "old_name": "Rajasekar L"},
    {"code": "MET23",  "name": "VELAYUTHAM P",              "phone": "9843283112", "email": "p.velu92@gmail.com",         "designation": "Site Manager",                         "department": "Projects", "is_admin": False, "can_submit_task_report": True,  "old_name": "VELAYUTHAM P"},
    {"code": "MET43",  "name": "M. MOHAN KUMAR",            "phone": "9043941800", "email": "mohan2681@gmail.com",        "designation": "Junior Engineer (Civil)",              "department": "Projects", "is_admin": False, "can_submit_task_report": True,  "old_name": "M. Mohan Kumar"},
    {"code": "MET44",  "name": "THANAVEL C",                "phone": "8124705318", "email": "thanavel@metfraa.com",       "designation": "Assistant Project Manager",            "department": "Projects", "is_admin": False, "can_submit_task_report": True,  "old_name": "Thanavel"},
    {"code": "MET69",  "name": "SALMA K",                   "phone": "9994862550", "email": "costing@metfraa.com",        "designation": "Costing & Estimation Engineer",        "department": "Projects", "is_admin": False, "can_submit_task_report": True,  "old_name": "Salma"},
    {"code": "MET74",  "name": "SUMANA S",                  "phone": "6385475983", "email": "sumana@metfraa.com",         "designation": "Project Coordinator",                  "department": "Projects", "is_admin": False, "can_submit_task_report": True,  "old_name": "Sumana"},
    {"code": "MET75",  "name": "NANDA KUMAR",               "phone": "9003010828", "email": "nandakumar250788@gmail.com", "designation": "Project Engineer",                     "department": "Projects", "is_admin": False, "can_submit_task_report": True,  "old_name": "Nanda Kumar"},
    {"code": "MET78",  "name": "NIRMAL KUMAR BALAKRISHNAN", "phone": "9840485801", "email": "nirmal@metfraa.com",         "designation": "Assistant General Manager - Projects", "department": "Projects", "is_admin": False, "can_submit_task_report": True,  "old_name": "Nirmal Kumar"},
    {"code": "MET80",  "name": "E. LOKESH",                 "phone": "9940107534", "email": "lokeshel79@gmail.com",       "designation": "Site Engineer",                        "department": "Projects", "is_admin": False, "can_submit_task_report": True,  "old_name": "Lokesh"},
    {"code": "MET105", "name": "NAVENDRA PRATAP SINGH",     "phone": "9911124384", "email": None,                          "designation": "Site Manager",                         "department": "Projects", "is_admin": False, "can_submit_task_report": True,  "old_name": None},
    {"code": "MET109", "name": "HIMANSHU SHARMA",           "phone": "9999256948", "email": None,                          "designation": "Junior Engineer",                      "department": "Projects", "is_admin": False, "can_submit_task_report": True,  "old_name": None},
    {"code": "MET110", "name": "KALAI BRINDHA M P",         "phone": "9600068189", "email": None,                          "designation": "Vice President (Operations & Projects)","department": "Projects", "is_admin": True,  "can_submit_task_report": False, "old_name": None},

    # Plant (8)
    {"code": "MET50",  "name": "SURESH S",                  "phone": "9790055831", "email": "qaqc@metfraa.com",           "designation": "Quality Control Engineer",             "department": "Plant", "is_admin": False, "can_submit_task_report": True,  "old_name": "Suresh"},
    {"code": "MET64",  "name": "P. THANGARAJ",              "phone": "9994086097", "email": "thangaraj@metfraa.com",      "designation": "Plant Head Operations",                "department": "Plant", "is_admin": False, "can_submit_task_report": True,  "old_name": "Thangaraj"},
    {"code": "MET72",  "name": "SANTHOSHRAJ A",             "phone": "8122664323", "email": "rajsathosh1@gmail.com",      "designation": "Production Engineer",                  "department": "Plant", "is_admin": False, "can_submit_task_report": True,  "old_name": "Santhosh Raj"},
    {"code": "MET73",  "name": "GOPI M",                    "phone": "9790040021", "email": "gopi@metfraa.com",           "designation": "Production Manager",                   "department": "Plant", "is_admin": False, "can_submit_task_report": True,  "old_name": "Gopi"},
    {"code": "MET79",  "name": "AJOY KUMAR KHATUA",         "phone": "9002039036", "email": "maintenance@metfraa.com",    "designation": "Assistant Manager (Maintenance)",      "department": "Plant", "is_admin": False, "can_submit_task_report": True,  "old_name": "Ajoy Kumar Khatua"},
    {"code": "MET84",  "name": "DEENADHAYALAN RAMESH",      "phone": "8220178469", "email": "stores@metfraa.com",         "designation": "Stores Executive",                     "department": "Plant", "is_admin": False, "can_submit_task_report": True,  "old_name": "Deena Dhayalan Ramesh"},
    {"code": "MET102", "name": "M POORNIMA",                "phone": "9094920264", "email": None,                          "designation": "Admin & Purchase Executive",           "department": "Plant", "is_admin": False, "can_submit_task_report": True,  "old_name": None},
    {"code": "MET103", "name": "GANESH RAJA P",             "phone": "9360585411", "email": "ppc@metfraa.com",             "designation": "PPC Executive",                        "department": "Plant", "is_admin": False, "can_submit_task_report": True,  "old_name": None},

    # EHS / Safety (5)
    {"code": "MET56",  "name": "C.V. THIRUMALAI",           "phone": "9176671705", "email": None,                          "designation": "Safety Officer - Executive",           "department": "EHS", "is_admin": False, "can_submit_task_report": True,  "old_name": None},
    {"code": "MET77",  "name": "RENJITH S A",               "phone": "8124081925", "email": "renjithrj970@gmail.com",     "designation": "Junior Safety Executive",              "department": "EHS", "is_admin": False, "can_submit_task_report": True,  "old_name": "Renjith Kumar"},
    {"code": "MET92",  "name": "VARATHARAJ NAVANEETHAN",    "phone": "9790249180", "email": "varadharaj@metfraa.com",     "designation": "Assistant Manager - EHS",              "department": "EHS", "is_admin": False, "can_submit_task_report": True,  "old_name": "Vardharaj Navaneethan"},
    {"code": "MET101", "name": "PRAWIN PAUL D",             "phone": "8525024547", "email": None,                          "designation": "Safety Officer",                       "department": "EHS", "is_admin": False, "can_submit_task_report": True,  "old_name": None},
    {"code": "MET107", "name": "BHARATHIRAJA R",            "phone": "9894056587", "email": None,                          "designation": "Safety Officer",                       "department": "EHS", "is_admin": False, "can_submit_task_report": True,  "old_name": None},

    # Purchase (1)
    {"code": "MET60",  "name": "R. SURESH KUMAR",           "phone": "9962035350", "email": "purchase@metfraa.com",       "designation": "Purchase Manager",                     "department": "Purchase", "is_admin": False, "can_submit_task_report": True,  "old_name": "Suresh Kumar"},

    # Finance & Accounts (2)
    {"code": "MET91",  "name": "SATHYA R",                  "phone": "7305176574", "email": "accounts@metfraa.com",       "designation": "Accounts Assistant",                   "department": "Finance & Accounts", "is_admin": False, "can_submit_task_report": True,  "old_name": "Sathya"},
    {"code": "MET106", "name": "BALAJI M",                  "phone": "8637466998", "email": None,                          "designation": "Accounts Manager",                     "department": "Finance & Accounts", "is_admin": False, "can_submit_task_report": True,  "old_name": None},

    # HR & Admin (3)
    {"code": "MET19",  "name": "THILAGAVATHY D",            "phone": "9677040429", "email": None,                          "designation": "Office Assistant",                     "department": "HR & Admin", "is_admin": False, "can_submit_task_report": True,  "old_name": None},
    {"code": "MET40",  "name": "SUDHA G",                   "phone": "9884883681", "email": "admin@metfraa.com",          "designation": "Admin",                                "department": "HR & Admin", "is_admin": False, "can_submit_task_report": True,  "old_name": "Sudha"},
    {"code": "MET66",  "name": "BODAPATI SHEELA HEPSIBAH GRACE", "phone": "9963315234", "email": "admin@metfraa.com",     "designation": "HR Assistant",                         "department": "HR & Admin", "is_admin": True,  "can_submit_task_report": True,  "old_name": "Sheela Hepsibah Grace"},
]


# Employees in old seed who are NOT in the new master and will be deactivated
DEACTIVATE_OLD = [
    "Sathiyaseelan",       # GM Sales - not in new master
    "Vijay",               # Project Manager Civil - not in new master
    "Nainar",              # Project Manager PEB - not in new master
    "Rajakumaran",         # Project Manager PEB - not in new master
    "C. Saraneeswari",     # Sr Design Engineer - not in new master
    "Robin James",         # Site Engineer - not in new master
]


def stats():
    kpi_users = [e for e in EMPLOYEE_MASTER if e["can_submit_task_report"] or not e["is_admin"]]
    task_reporters = [e for e in EMPLOYEE_MASTER if e["can_submit_task_report"]]
    admins = [e for e in EMPLOYEE_MASTER if e["is_admin"]]
    fresh = [e for e in EMPLOYEE_MASTER if e["old_name"] is None]
    return {
        "total": len(EMPLOYEE_MASTER),
        "kpi_tracked": len([e for e in EMPLOYEE_MASTER if not e["is_admin"] or e["can_submit_task_report"]]),
        "task_reporters": len(task_reporters),
        "admins": len(admins),
        "fresh_new_users": len(fresh),
        "deactivations": len(DEACTIVATE_OLD),
    }


if __name__ == "__main__":
    from pprint import pprint
    s = stats()
    print("=" * 50)
    pprint(s)
    print("=" * 50)
    print("\nDepartments breakdown:")
    depts = {}
    for e in EMPLOYEE_MASTER:
        depts.setdefault(e["department"], []).append(e["name"])
    for d, names in depts.items():
        print(f"  {d}: {len(names)}")
        for n in names:
            print(f"    - {n}")
