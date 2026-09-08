# 7-Day Trend + Pages-Per-Toner — Integration

Requires (in C:\Users\hassan.abdulmalik\PrinterAgent\):
  - page_counts.py        (SNMP counter reader - already provided)
  - page_counts_db.py     (history + yield - NEW, provided)

---

## STEP 1 — init the DB at startup (app.py)

Import near the top:

```python
import page_counts_db
```

In your existing @app.on_event("startup") on_startup(), add:

```python
    page_counts_db.init_db()
```

---

## STEP 2 — record counts each daily scan (toner_service.py)

In run_fleet_scan(), after `results = await get_all_toner_status(...)`
and any enrich step, add:

```python
    # --- record page counters for trend + yield ---
    try:
        from page_counts import get_page_counts
        import page_counts_db
        for r in results:
            if not r.get("online"):
                continue
            pc = await get_page_counts(r["ip"])
            # find current Black % from the toners list (for refill detection)
            black_pct = None
            for t in r.get("toners", []):
                if "black" in (t.get("name","").lower()):
                    black_pct = t.get("percentage"); break
            page_counts_db.record(
                r.get("key") or r.get("ip"), r.get("ip"),
                pc.get("total"), pc.get("mono"), pc.get("color"), black_pct
            )
    except Exception as exc:
        print(f"WARNING: page-count record failed: {exc}")
```

That's one reading per printer per day (upsert), which is exactly what the
trend + yield need.

---

## STEP 3 — endpoints (app.py)

```python
from page_counts import get_page_counts

@app.get("/api/page-counts/{printer_key}")
def page_counts_history(printer_key: str, days: int = 7):
    """7-day (default) pages-per-day trend for one printer."""
    try:
        return {"success": True,
                "data": page_counts_db.pages_per_day(printer_key, days),
                "yield": page_counts_db.pages_per_toner(printer_key)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}

@app.get("/api/page-counts-live")
async def page_counts_live(ip: str, community: str = "public"):
    """Live total/mono/colour for one printer IP (on-demand)."""
    try:
        return {"success": True, "data": await get_page_counts(ip, community)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
```

---

## STEP 4 — chart in the Toner Center detail panel

The detail panel is keyed by IP, but the trend is keyed by registry KEY.
Easiest: when you check a printer, also pass its key if known. For the
on-demand IP check we can still show the LIVE counts (Step 3 of the page-
counts guide) and, if the IP maps to a known key, the trend.

### 4a. Add Chart.js to toner_center.html <head>:

```html
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
```

### 4b. Add a canvas + yield line into renderDetail(d).
Inside the box.innerHTML template (after the counts tiles), add:

```html
      <div class="grp">
        <div class="grp-title"><span>7-Day Pages / Day</span>
          <span id="yieldLbl"></span></div>
        <canvas id="pagesChart" height="120"></canvas>
      </div>
```

### 4c. After setting box.innerHTML, fetch + draw (needs the printer KEY).
Add this helper and call it when you have a key:

```javascript
let pagesChartObj = null;

async function loadPagesTrend(key){
  if(!key) return;
  try{
    const res = await fetch(`/api/page-counts/${encodeURIComponent(key)}?days=7`);
    const j = await res.json();
    if(!j.success) return;

    const rows = j.data || [];
    const labels = rows.map(r => r.date.slice(5));           // MM-DD
    const mono   = rows.map(r => r.delta_mono ?? 0);
    const color  = rows.map(r => r.delta_color ?? 0);
    const total  = rows.map(r => r.delta_total ?? 0);

    // yield label
    const y = j.yield || {};
    const yl = document.getElementById("yieldLbl");
    if(yl && y.pages_on_current_toner != null){
      yl.textContent = `${Number(y.pages_on_current_toner).toLocaleString()} pages on current toner`;
    }

    const ctx = document.getElementById("pagesChart");
    if(!ctx) return;
    if(pagesChartObj) pagesChartObj.destroy();
    // Show mono+color stacked if we have them, else just total
    const haveSplit = mono.some(v=>v>0) || color.some(v=>v>0);
    pagesChartObj = new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: haveSplit ? [
          {label:"B&W", data:mono, backgroundColor:"#64748b"},
          {label:"Colour", data:color, backgroundColor:"#0087ff"},
        ] : [
          {label:"Pages", data:total, backgroundColor:"#0067b8"},
        ]
      },
      options:{
        plugins:{legend:{display:haveSplit}},
        scales:{
          x:{stacked:haveSplit, grid:{display:false}},
          y:{stacked:haveSplit, beginAtZero:true}
        }
      }
    });
  }catch(e){ console.error("pages trend failed", e); }
}
```

### 4d. Call it. Two easy ways:

- If you check via the "Details" button in the attention list, you already
  have the printer object with a key -> pass it:
      loadPagesTrend(a.key)   // when building that button's click

- For the manual IP box, resolve the key from /api/manage-printers by IP,
  then call loadPagesTrend(key). (Optional - the live counts still show
  without the trend.)

---

## RESULT

Checking a printer now shows:
  - Total / B&W / Colour tiles (page-counts guide)
  - A 7-day pages-per-day bar chart (mono vs colour stacked)
  - "N pages on current toner" yield label

---

## VALIDATED (self-test output)

  7-day pages/day deltas computed correctly (310, 320, ... /day)
  pages_per_toner detected a refill and counted 730 pages since it.

## CAVEATS
- Needs >= 2 daily readings before the first delta appears (so the chart
  fills in over the first couple of days).
- Yield refill detection uses Black toner % jumping up >= 20 points; if a
  printer never reports black %, yield falls back to "since monitoring
  began".
