"""
toner_detail.py
PrinterAgent - Full consumables detail + categorisation

Two things this module adds on top of toner_monitor:

  1. categorise_supplies(items)
       Splits ALL SNMP supply rows (from a printer's full walk) into
       meaningful groups so the on-demand check can show everything:
         Toner, Drum, Developer, Fuser, Transfer, Waste, Maintenance/Other

  2. build_full_detail(result)
       Takes a get_toner_levels() result and returns a rich, grouped
       structure ready for the "check one printer" UI, including a
       per-group summary and the single lowest consumable.

  3. attention_list(fleet)
       From a fleet scan, returns printers sorted by their most urgent
       (lowest) toner - powers the "Needs Attention" highlight panel.

Pure functions, no I/O, no external deps - trivially testable.
"""


# Order matters: more specific keywords first (e.g. "waste toner" before "toner")
_CATEGORY_RULES = [
    ("Waste",       ["waste"]),
    ("Drum",        ["drum", "photoconduct", "opc", "imaging unit", "image drum"]),
    ("Developer",   ["developer", "develop"]),
    ("Fuser",       ["fuser", "fusing", "pressure roller", "fixing"]),
    ("Transfer",    ["transfer", "belt", "itb", "secondary transfer"]),
    ("Charger",     ["charger", "corona", "main charge"]),
    ("Maintenance", ["maintenance", "maint", "kit", "blade", "cleaner", "roller"]),
    ("Toner",       ["toner", "cartridge", "ink", "cyan", "magenta", "yellow", "black"]),
]

# Colour tag for UI (matches your CMYK bar colours)
def _colour_tag(name):
    n = (name or "").lower()
    if "cyan" in n:
        return "c"
    if "magenta" in n:
        return "m"
    if "yellow" in n:
        return "y"
    if "black" in n:
        return "k"
    return ""


def categorise(name):
    """Return the category label for a single supply description."""
    n = (name or "").lower()
    for label, keywords in _CATEGORY_RULES:
        if any(kw in n for kw in keywords):
            return label
    return "Other"


def categorise_supplies(items):
    """
    Group a flat list of supply dicts (each has name/percentage/status)
    into {category: [items...]} preserving order within each group.
    """
    groups = {}
    for it in items or []:
        cat = categorise(it.get("name"))
        item = dict(it)
        item["category"] = cat
        item["colour"] = _colour_tag(it.get("name"))
        groups.setdefault(cat, []).append(item)
    return groups


def _valid_pct_items(items):
    """Items that actually report a numeric percentage."""
    out = []
    for it in items or []:
        p = it.get("percentage")
        if isinstance(p, (int, float)):
            out.append(it)
    return out


def build_full_detail(result):
    """
    Turn a get_toner_levels() result into a grouped, UI-ready structure.

    Input `result` has: display_name, ip, printer_name, online,
    overall_status, toners[], maintenance[], last_checked, error.

    Output adds:
      groups        : {category: [items]}
      group_summary : [{category, count, lowest_pct, worst_status}]
      lowest        : the single lowest-% consumable across everything
    """
    # All supplies = toners + maintenance (the SNMP walk captured both)
    all_items = list(result.get("toners") or []) + list(result.get("maintenance") or [])

    groups = categorise_supplies(all_items)

    # Per-group summary
    group_summary = []
    for cat, items in groups.items():
        valid = _valid_pct_items(items)
        lowest_pct = min((i["percentage"] for i in valid), default=None)
        # worst status by severity
        sev = {"Critical": 0, "Low": 1, "Moderate": 2, "Healthy": 3, "Unknown": 4}
        worst = None
        for i in items:
            s = i.get("status", "Unknown")
            if worst is None or sev.get(s, 4) < sev.get(worst, 4):
                worst = s
        group_summary.append({
            "category": cat,
            "count": len(items),
            "lowest_pct": lowest_pct,
            "worst_status": worst or "Unknown",
        })

    # Sort groups Toner first, then by worst status
    cat_order = {"Toner": 0, "Drum": 1, "Developer": 2, "Fuser": 3,
                 "Transfer": 4, "Charger": 5, "Waste": 6, "Maintenance": 7, "Other": 8}
    group_summary.sort(key=lambda g: cat_order.get(g["category"], 9))

    # Single lowest consumable across everything (for the headline)
    valid_all = _valid_pct_items(all_items)
    lowest = None
    if valid_all:
        lowest = min(valid_all, key=lambda i: i["percentage"])
        lowest = {
            "name": lowest.get("name"),
            "percentage": lowest.get("percentage"),
            "status": lowest.get("status"),
            "category": categorise(lowest.get("name")),
        }

    return {
        "display_name": result.get("display_name"),
        "ip": result.get("ip"),
        "printer_name": result.get("printer_name"),
        "online": result.get("online"),
        "overall_status": result.get("overall_status"),
        "last_checked": result.get("last_checked"),
        "error": result.get("error"),
        "groups": groups,
        "group_summary": group_summary,
        "lowest": lowest,
        "total_supplies": len(all_items),
    }


def attention_list(fleet, limit=None):
    """
    From a fleet scan (list of results), return printers that need
    attention, sorted MOST URGENT FIRST by their lowest toner %.

    Only considers actual TONER supplies (not drums/fuser) for urgency,
    since toner is what runs out and stops printing.
    Offline / no-data printers are excluded from ranking but returned
    separately so the UI can still surface them.
    """
    ranked = []
    offline = []

    for p in fleet or []:
        if not p.get("online"):
            offline.append({
                "key": p.get("key"), "ip": p.get("ip"),
                "display_name": p.get("display_name"),
                "location": p.get("location"),
                "overall_status": p.get("overall_status", "Offline"),
                "error": p.get("error"),
            })
            continue

        toners = _valid_pct_items(p.get("toners"))
        if not toners:
            continue

        lowest = min(toners, key=lambda t: t["percentage"])
        ranked.append({
            "key": p.get("key"), "ip": p.get("ip"),
            "display_name": p.get("display_name"),
            "location": p.get("location"),
            "overall_status": p.get("overall_status"),
            "lowest_toner": lowest.get("name"),
            "lowest_pct": lowest.get("percentage"),
            "lowest_status": lowest.get("status"),
            "last_checked": p.get("last_checked"),
        })

    ranked.sort(key=lambda r: r["lowest_pct"])
    if limit:
        ranked = ranked[:limit]

    return {"attention": ranked, "offline": offline}


if __name__ == "__main__":
    # Self-test with a realistic PROCUREMENT-style result
    sample = {
        "display_name": "PROCUREMENT PRINTER", "ip": "172.20.231.74",
        "printer_name": "PROCUREMENT", "online": True, "overall_status": "Critical",
        "last_checked": "2026-08-24 10:00:00", "error": None,
        "toners": [
            {"name": "Cyan Toner", "percentage": 18.0, "status": "Low"},
            {"name": "Magenta Toner", "percentage": 21.0, "status": "Low"},
            {"name": "Yellow Toner", "percentage": 32.0, "status": "Moderate"},
            {"name": "Black Toner", "percentage": 1.0, "status": "Critical"},
            {"name": "Waste Toner", "percentage": None, "status": "Unknown"},
        ],
        "maintenance": [
            {"name": "Black Photoconductive Drum (DK)", "percentage": 83.0, "status": "Healthy"},
            {"name": "Cyan Developer", "percentage": 67.0, "status": "Healthy"},
            {"name": "Fusing Belt/Roller (FK1)", "percentage": 94.0, "status": "Healthy"},
            {"name": "Transfer Belt (TK1)", "percentage": 94.0, "status": "Healthy"},
            {"name": "Black Main Charger (MCK)", "percentage": 84.0, "status": "Healthy"},
        ],
    }
    detail = build_full_detail(sample)
    print("Groups:", {k: len(v) for k, v in detail["groups"].items()})
    print("Lowest overall:", detail["lowest"])
    print("Group summary:")
    for g in detail["group_summary"]:
        print(f"  {g['category']:12s} count={g['count']} lowest={g['lowest_pct']} worst={g['worst_status']}")

    fleet = [sample, {"display_name": "GED", "ip": "172.16.16.47", "online": True,
                      "overall_status": "Low",
                      "toners": [{"name": "Black Toner", "percentage": 22.0, "status": "Low"}]},
             {"display_name": "Dead", "ip": "1.1.1.1", "online": False, "overall_status": "Offline"}]
    att = attention_list(fleet)
    print("\nAttention ranking:")
    for a in att["attention"]:
        print(f"  {a['display_name']:22s} {a['lowest_toner']} {a['lowest_pct']}% ({a['lowest_status']})")
    print("Offline:", [o["display_name"] for o in att["offline"]])
