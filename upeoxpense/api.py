import frappe
import datetime as dt
from frappe import _
from datetime import timedelta
from upeoxpense.utils.periods import period_bounds  # keep your helper import


# ----------------------------- Categories -----------------------------

@frappe.whitelist()
def list_categories():
    """Active categories with id/title/color/icon."""
    return frappe.get_all(
        "Expense Category",
        filters={"is_active": 1},
        fields=["name as id", "category_name as title", "color", "icon"],
    )


@frappe.whitelist()
def upsert_category(title, color="#4F46E5", icon="💸", id=None):
    """Create or update an Expense Category."""
    doc = frappe.get_doc(
        {"doctype": "Expense Category", "name": id}
        if id
        else {"doctype": "Expense Category"}
    )
    doc.category_name = title
    doc.color = color
    doc.icon = icon
    doc.is_active = 1
    doc.save(ignore_permissions=True)
    return {"id": doc.name}


# ------------------------------- Budgets ------------------------------

@frappe.whitelist()
def create_budget(category, period_type, amount: float, start_date=None, is_recurring=1):
    """Create a Budget entry (not submittable by default)."""
    b = frappe.get_doc(
        {
            "doctype": "Budget",
            "category": category,           # Link to Expense Category (name)
            "period_type": period_type,     # 'Weekly' | 'Monthly' | 'Yearly'
            "amount": amount,
            "start_date": start_date,
            "is_recurring": is_recurring,
        }
    )
    b.insert(ignore_permissions=True)
    return {"id": b.name}


# ------------------------------ Expenses -----------------------------

@frappe.whitelist()
def add_expense(
    amount: float,
    category: str,
    date: str = None,
    merchant: str = None,
    note: str = None,
    payment_method: str = None,
    wallet: str = None,
):
    """
    Create + SUBMIT an Expense, then commit.
    Returns {"name": <docname>, "docstatus": 1} on success.
    """
    if amount is None:
        frappe.throw(_("Amount is required"))
    try:
        amount = float(amount)
    except Exception:
        frappe.throw(_("Amount must be a number"))

    if not category:
        frappe.throw(_("Category is required"))
    if not date:
        frappe.throw(_("Date is required"))
    if not merchant:
        frappe.throw(_("Merchant is required"))
    if not note:
        frappe.throw(_("Notes are required"))

    try:
        doc = frappe.get_doc(
            {
                "doctype": "Expense",
                "amount": amount,
                "category": category,
                "date": date or frappe.utils.nowdate(),
                "merchant": merchant,
                "note": note,
                "payment_method": payment_method,
                "wallet": wallet,
            }
        )
        doc.insert(ignore_permissions=True)
        doc.submit()  # docstatus: 0 -> 1
        frappe.db.commit()
        return {"name": doc.name, "docstatus": doc.docstatus}
    except Exception as e:
        frappe.db.rollback()
        frappe.throw(_("Failed to save/submit expense: {0}").format(frappe.utils.cstr(e)))


# ---------------------------- Dashboard data -------------------------

def _monday(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())  # Monday


def _week_label(start: dt.date) -> str:
    end = start + timedelta(days=6)
    return f"{start.strftime('%b')} {start.day}\u2013{end.day}"


def _parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


import frappe
import datetime as dt
from frappe import _
from datetime import timedelta

# --- helpers -----------------------------------------------------------

def _parse_date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)

def _current_month_range(today: dt.date | None = None) -> tuple[dt.date, dt.date]:
    today = today or dt.date.today()
    first = today.replace(day=1)
    nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    last = nxt - timedelta(days=1)
    return first, last

def _normalize_bounds(d: dict, default_start: dt.date, default_end: dt.date) -> tuple[dt.date, dt.date]:
    """
    Handle nullable start_date / end_date on Budget by widening to defaults.
    """
    s = d.get("start_date")
    e = d.get("end_date")
    s = _parse_date(s) if isinstance(s, str) else (s or default_start)
    e = _parse_date(e) if isinstance(e, str) else (e or default_end)
    return s, e

def _overlaps(a1: dt.date, a2: dt.date, b1: dt.date, b2: dt.date) -> bool:
    """Inclusive overlap."""
    return a1 <= b2 and b1 <= a2


# --- main endpoints ----------------------------------------------------

@frappe.whitelist()
def period_summary(from_date: str | None = None, to_date: str | None = None):
    """
    Return one record per *overlapping* Budget within the selected window.
    If no range is provided, default to the current month.

    Each record:
      budget_id, category, category_title, color, period_type, amount,
      period_start, period_end, spent, remaining, pct
    """
    # 1) decide the window
    if not (from_date and to_date):
        f, t = _current_month_range()
    else:
        try:
            f, t = _parse_date(from_date), _parse_date(to_date)
        except Exception:
            frappe.throw(_("Invalid from_date/to_date. Use YYYY-MM-DD."))
        if f > t:
            frappe.throw(_("from_date cannot be after to_date."))

    # 2) get budgets that might overlap (we’ll still guard in Python)
    #    handle NULL start/end by widening to extremes when comparing
    budgets = frappe.get_all(
        "Budget",
        filters={"docstatus": ["<", 2]},
        fields=["name", "category", "period_type", "amount", "start_date", "end_date"],
        order_by="start_date asc",
    )
    if not budgets:
        return []

    # 3) categories meta
    cat_names = [b["category"] for b in budgets if b.get("category")]
    cat_meta = {
        c["name"]: c
        for c in frappe.get_all(
            "Expense Category",
            filters={"name": ["in", cat_names]} if cat_names else {},
            fields=["name", "category_name", "color"],
        )
    }

    # 4) spend within the selected window (submitted only), grouped by category
    spent_rows = frappe.db.sql(
        """
        SELECT e.category AS category, COALESCE(SUM(e.amount), 0) AS spent
        FROM `tabExpense` e
        WHERE e.docstatus = 1
          AND DATE(e.date) BETWEEN %s AND %s
        GROUP BY e.category
        """,
        (f, t),
        as_dict=True,
    )
    spent_by_cat = {r["category"]: float(r["spent"] or 0) for r in spent_rows}

    # 5) build response for budgets that overlap the range
    #    treat NULL budget start/end as open-ended on the missing side
    out = []
    # widen defaults for nulls well beyond user ranges
    very_early = dt.date(1900, 1, 1)
    very_late  = dt.date(2999, 12, 31)

    for b in budgets:
        b_start, b_end = _normalize_bounds(b, very_early, very_late)
        if not _overlaps(b_start, b_end, f, t):
            continue  # skip non-overlapping budgets

        amount = float(b.get("amount") or 0)
        spent  = spent_by_cat.get(b["category"], 0.0)

        # (Optional) If you want to restrict spend per-budget to the intersection only,
        # add a per-budget query here on max(f,b_start)..min(t,b_end).
        remaining = amount - spent
        pct = (spent / amount) if amount > 0 else 0.0

        meta = cat_meta.get(b["category"], {})
        out.append({
            "budget_id": b["name"],
            "category": b["category"],
            "category_title": meta.get("category_name", b["category"]),
            "color": meta.get("color", "#64748b"),
            "period_type": b.get("period_type"),
            "amount": amount,
            "period_start": b_start,
            "period_end": b_end,
            "spent": spent,
            "remaining": remaining,
            "pct": pct,
        })

    return out


@frappe.whitelist()
def period_totals(from_date: str | None = None, to_date: str | None = None):
    """
    Top cards:
      - totalBudget: sum of amounts for budgets whose (start_date..end_date) overlap the range
      - totalSpent:  sum of submitted expenses within the range
      - balance:     totalBudget - totalSpent

    If no range provided → current month by default.
    """
    # window
    if not (from_date and to_date):
        f, t = _current_month_range()
    else:
        try:
            f, t = _parse_date(from_date), _parse_date(to_date)
        except Exception:
            frappe.throw(_("Invalid from_date/to_date. Use YYYY-MM-DD."))
        if f > t:
            frappe.throw(_("from_date cannot be after to_date."))

    # budgets that overlap the range
    rows = frappe.get_all(
        "Budget",
        filters={"docstatus": ["<", 2]},
        fields=["amount", "start_date", "end_date"],
    )
    very_early = dt.date(1900, 1, 1)
    very_late  = dt.date(2999, 12, 31)

    total_budget = 0.0
    for r in rows:
        b_start = r.get("start_date") or very_early
        b_end   = r.get("end_date")   or very_late
        if isinstance(b_start, str): b_start = _parse_date(b_start)
        if isinstance(b_end, str):   b_end   = _parse_date(b_end)
        if _overlaps(b_start, b_end, f, t):
            total_budget += float(r.get("amount") or 0)

    # spend in the selected range
    spent_row = frappe.db.sql(
        """
        SELECT COALESCE(SUM(e.amount), 0) AS spent
        FROM `tabExpense` e
        WHERE e.docstatus = 1
          AND DATE(e.date) BETWEEN %s AND %s
        """,
        (f, t),
        as_dict=True,
    )[0]
    total_spent = float(spent_row["spent"] or 0)

    return {
        "totalBudget": total_budget,
        "totalSpent": total_spent,
        "balance": total_budget - total_spent,
    }



@frappe.whitelist()
def spend_trend(weeks: int = 8, category: str | None = None):
    """
    Weekly trend (submitted expenses only), oldest → newest.
    """
    weeks = int(weeks or 8)
    today = dt.date.today()
    this_mon = _monday(today)
    week_starts = [this_mon - timedelta(weeks=i) for i in range(weeks - 1, -1, -1)]
    overall_start = week_starts[0]
    overall_end = week_starts[-1] + timedelta(days=6)

    params = [overall_start, overall_end]
    category_filter = ""
    if category:
        category_filter = "AND e.category = %s"
        params.append(category)

    rows = frappe.db.sql(
        f"""
        SELECT YEARWEEK(e.date, 3) AS yw, COALESCE(SUM(e.amount), 0) AS spent
        FROM `tabExpense` e
        WHERE e.docstatus = 1
          AND DATE(e.date) BETWEEN %s AND %s
          {category_filter}
        GROUP BY YEARWEEK(e.date, 3)
        """,
        tuple(params),
        as_dict=True,
    )
    by_yw = {r["yw"]: float(r["spent"] or 0) for r in rows}

    labels, data = [], []
    for start in week_starts:
        iso_year, iso_week, _ = start.isocalendar()
        yw_key = iso_year * 100 + iso_week
        labels.append(_week_label(start))
        data.append(by_yw.get(yw_key, 0.0))

    return {"labels": labels, "series": [{"name": "Spent", "data": data}]}
