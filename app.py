import os
import sqlite3
import json
from datetime import datetime
from functools import wraps
from html import escape as html_escape

from flask import Flask, g, request, redirect, url_for, session, flash, render_template_string


# ===============================
# Configuration (Render env vars)
# ===============================
APP_NAME = os.getenv("APP_NAME", "ZAK CRM")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-please")

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "zakarea.job@hotmail.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "ZAKCRM2026")

CURRENCY = os.getenv("CURRENCY", "USD")

COMPANY_NAME = os.getenv("COMPANY_NAME", "Hotgen")
COMPANY_EMAIL = os.getenv("COMPANY_EMAIL", "zakarea@hotgen.com.cn")
COMPANY_ADDRESS = os.getenv("COMPANY_ADDRESS", "No. 55 Qingfeng West Road, Daxing District, 102629, Beijing, China")
COMPANY_PHONE = os.getenv("COMPANY_PHONE", "")

BANK_INFO = os.getenv(
    "BANK_INFO",
    """Beneficiary: Beijing Hotgen Biotech Co.,Ltd
SWIFT: CMBCCNBS
Bank Name: China Merchants Bank H.O. ShenZhen
Bank Address: China Merchants Bank Tower NO.7088, Shennan Boulevard, Shenzhen, China.
A/C: USD: 110909296432802  EURO: 110909296435702"""
)

INVOICE_PREFIX = os.getenv("INVOICE_PREFIX", "HOTGEN")
INVOICE_SUFFIX = os.getenv("INVOICE_SUFFIX", "ZAK")

# IMPORTANT:
# - For persistent "cloud" storage on Render, create a Disk mounted to /var/data
#   then set DATABASE_PATH=/var/data/zakcrm.db
# - If DATABASE_PATH not set, it falls back to /tmp (not persistent).
DEFAULT_DB = "/var/data/zakcrm.db" if os.path.isdir("/var/data") else "/tmp/zakcrm.db"
DATABASE = os.getenv("DATABASE_PATH", DEFAULT_DB)

LOGO_URL = os.getenv("LOGO_URL", "/static/hotgen_logo.png")


# ===============================
# App
# ===============================
app = Flask(__name__)
app.secret_key = SECRET_KEY


# ===============================
# DB / Schema
# ===============================
SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS contacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  company TEXT,
  country TEXT,
  city TEXT,
  address TEXT,
  email TEXT,
  phone TEXT,
  whatsapp TEXT,
  status TEXT DEFAULT 'Prospect',
  source TEXT,
  next_followup_date TEXT,
  last_contact_date TEXT,
  notes TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  short_name TEXT,
  full_name TEXT NOT NULL,
  specification TEXT,
  package TEXT,
  unit_price REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS invoices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_no TEXT UNIQUE NOT NULL,
  contact_id INTEGER NOT NULL,
  issue_date TEXT NOT NULL,
  required_delivery_date TEXT,
  delivery_mode TEXT,
  trade_terms TEXT,
  payment_terms TEXT,
  shipping_date TEXT,
  internal_shipping_fee REAL DEFAULT 0,
  previous_balance_note TEXT,
  currency TEXT DEFAULT 'USD',
  total_amount REAL DEFAULT 0,
  notes TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS invoice_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id INTEGER NOT NULL,
  line_no INTEGER NOT NULL,
  description TEXT NOT NULL,
  specification TEXT,
  package TEXT,
  form TEXT,
  quantity REAL NOT NULL,
  unit_price REAL NOT NULL,
  amount REAL NOT NULL,
  FOREIGN KEY(invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_contacts_country ON contacts(country);
CREATE INDEX IF NOT EXISTS idx_invoices_issue_date ON invoices(issue_date);
CREATE INDEX IF NOT EXISTS idx_products_full_name ON products(full_name);
CREATE INDEX IF NOT EXISTS idx_products_short_name ON products(short_name);
"""


def ensure_db_dir():
    db_dir = os.path.dirname(DATABASE)
    if db_dir and not os.path.exists(db_dir):
        try:
            os.makedirs(db_dir, exist_ok=True)
        except Exception:
            pass


def get_db():
    db = getattr(g, "_db", None)
    if db is None:
        ensure_db_dir()
        db = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        db.executescript(SCHEMA_SQL)
        db.commit()

        # ---- safe migrations ----

        # Ensure products.unit_price exists (older DBs)
        try:
            db.execute("ALTER TABLE products ADD COLUMN unit_price REAL DEFAULT 0")
            db.commit()
        except Exception:
            pass

        # Add Bill To / Ship To fields to invoices
        cols = [
            ("bill_name", "TEXT"), ("bill_company", "TEXT"), ("bill_address", "TEXT"),
            ("bill_city", "TEXT"), ("bill_country", "TEXT"), ("bill_phone", "TEXT"), ("bill_email", "TEXT"),
            ("ship_name", "TEXT"), ("ship_company", "TEXT"), ("ship_address", "TEXT"),
            ("ship_city", "TEXT"), ("ship_country", "TEXT"), ("ship_phone", "TEXT"), ("ship_email", "TEXT"),
        ]
        for col, typ in cols:
            try:
                db.execute(f"ALTER TABLE invoices ADD COLUMN {col} {typ}")
                db.commit()
            except Exception:
                pass

        g._db = db
    return db


@app.teardown_appcontext
def close_db(exception=None):
    db = getattr(g, "_db", None)
    if db is not None:
        db.close()


# ===============================
# Auth
# ===============================
def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("logged_in") is not True:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


# ===============================
# Helpers
# ===============================
def money(x):
    try:
        return f"{float(x):,.2f}"
    except Exception:
        return "0.00"


def generate_invoice_no():
    today = datetime.now().strftime("%Y%m%d")
    db = get_db()
    like = f"{INVOICE_PREFIX}-{today}-{INVOICE_SUFFIX}-%"
    row = db.execute(
        "SELECT invoice_no FROM invoices WHERE invoice_no LIKE ? ORDER BY invoice_no DESC LIMIT 1",
        (like,)
    ).fetchone()

    last = 0
    if row:
        try:
            last = int(row["invoice_no"].split("-")[-1])
        except Exception:
            last = 0

    return f"{INVOICE_PREFIX}-{today}-{INVOICE_SUFFIX}-{last+1:03d}"


def product_label(short_name: str, full_name: str) -> str:
    short_name = (short_name or "").strip()
    full_name = (full_name or "").strip()
    if short_name:
        return f"{short_name} - {full_name}"
    return full_name


def first_non_empty(*vals):
    for v in vals:
        if v is not None and str(v).strip() != "":
            return str(v)
    return ""


# ===============================
# UI Template (inline)
# ===============================
BASE_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1"/>
  <title>{{ title }}</title>
  <style>
    body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial; margin:0; background:#f6f7fb; color:#111;}
    .top{position:sticky; top:0; background:#111; color:#fff; padding:12px 14px; display:flex; justify-content:space-between; align-items:center; z-index:10;}
    .brand{font-weight:900;}
    a{color:inherit; text-decoration:none;}
    .nav a{margin-left:10px; background:rgba(255,255,255,.08); padding:10px 12px; border-radius:12px; display:inline-block;}
    .container{max-width:1100px; margin:0 auto; padding:16px;}
    .card{background:#fff; border:1px solid #eee; border-radius:16px; padding:14px; margin-bottom:12px;}
    .row{display:flex; gap:10px; flex-wrap:wrap; align-items:center; justify-content:space-between;}
    .btn{border:1px solid #ddd; background:#fff; padding:12px 14px; border-radius:14px; font-weight:800; cursor:pointer;}
    .btn.primary{background:#111; color:#fff; border-color:#111;}
    input, select, textarea{padding:12px; border-radius:14px; border:1px solid #ddd; width:100%;}
    label{font-weight:900; display:block; margin:10px 0 6px;}
    .grid2{display:grid; grid-template-columns:repeat(2,1fr); gap:12px;}
    .span2{grid-column:span 2;}
    table{width:100%; border-collapse:collapse;}
    th,td{padding:10px; border-bottom:1px solid #f0f0f0; text-align:left; vertical-align:top;}
    th{background:#fafafa; font-size:13px;}
    .table{overflow:auto; border:1px solid #eee; border-radius:14px;}
    .flash{padding:12px; border-radius:14px; background:#ffe3e3; border:1px solid #ffb5b5; margin-bottom:12px;}
    .kpi{font-size:26px; font-weight:950;}
    .pill{padding:6px 10px; border-radius:999px; background:#f2f2f2; font-weight:800; font-size:12px;}
    @media(max-width:820px){ .grid2{grid-template-columns:1fr;} }

    /* PRINT / PDF */
    @media print{
      @page { size: A4; margin: 10mm; }
      .top,.no-print{display:none !important;}
      body{background:#fff;}
      .card{border:none;}
      .container{padding:0;}
      .table{overflow:visible !important; border:none !important;}
      table{width:100% !important; min-width:0 !important; table-layout:fixed;}
      th,td{font-size:11px !important; padding:6px !important; word-break:break-word;}
      a:link{ text-decoration:none; color:#000;}
    }
  </style>
</head>
<body>
  <div class="top">
    <div class="brand">{{ app_name }}</div>
    {% if logged_in %}
      <div class="nav">
        <a href="{{ url_for('dashboard') }}">Dashboard</a>
        <a href="{{ url_for('contacts') }}">Contacts</a>
        <a href="{{ url_for('products') }}">Products</a>
        <a href="{{ url_for('invoices') }}">Invoices</a>
        <a href="{{ url_for('logout') }}">Logout</a>
      </div>
    {% endif %}
  </div>
  <div class="container">
    {% with msgs = get_flashed_messages() %}
      {% if msgs %}
        <div class="flash">{{ msgs[0] }}</div>
      {% endif %}
    {% endwith %}
    {{ body|safe }}
  </div>
</body>
</html>
"""


def page(title, body_html):
    return render_template_string(
        BASE_HTML,
        title=title,
        body=body_html,
        app_name=APP_NAME,
        logged_in=session.get("logged_in") is True,
    )


# ===============================
# Routes
# ===============================
@app.get("/health")
def health():
    get_db()
    return "ok"


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        password = (request.form.get("password") or "").strip()
        if email == ADMIN_EMAIL and password == ADMIN_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        flash("Invalid login.")
    body = """
    <div class="card" style="max-width:420px;margin:30px auto;">
      <h2>Login</h2>
      <form method="post">
        <label>Email</label>
        <input name="email" type="email" required>
        <label>Password</label>
        <input name="password" type="password" required>
        <div class="row" style="justify-content:flex-end;margin-top:12px;">
          <button class="btn primary" type="submit">Login</button>
        </div>
      </form>
    </div>
    """
    return page("Login", body)


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
@login_required
def dashboard():
    db = get_db()
    total_contacts = db.execute("SELECT COUNT(*) c FROM contacts").fetchone()["c"]
    prospects = db.execute("SELECT COUNT(*) c FROM contacts WHERE status='Prospect'").fetchone()["c"]
    invoices_count = db.execute("SELECT COUNT(*) c FROM invoices").fetchone()["c"]

    year = datetime.now().strftime("%Y")
    ytd = db.execute("SELECT COALESCE(SUM(total_amount),0) s FROM invoices WHERE substr(issue_date,1,4)=?", (year,)).fetchone()["s"]

    top = db.execute("""
      SELECT COALESCE(c.country,'') country, COALESCE(SUM(i.total_amount),0) total
      FROM invoices i JOIN contacts c ON c.id=i.contact_id
      GROUP BY c.country
      ORDER BY total DESC
      LIMIT 8
    """).fetchall()

    body = f"""
    <div class="row">
      <div class="card" style="flex:1;min-width:220px;"><div class="kpi">{total_contacts}</div><div>Contacts</div></div>
      <div class="card" style="flex:1;min-width:220px;"><div class="kpi">{prospects}</div><div>Prospects</div></div>
      <div class="card" style="flex:1;min-width:220px;"><div class="kpi">{invoices_count}</div><div>Invoices</div></div>
      <div class="card" style="flex:2;min-width:260px;"><div class="kpi">{CURRENCY} {money(ytd)}</div><div>Sales {year}</div></div>
    </div>

    <div class="card">
      <div class="row">
        <h3 style="margin:0;">Top Countries</h3>
        <div class="no-print">
          <a class="btn primary" href="{url_for('invoice_new')}">+ Create Invoice</a>
          <a class="btn" href="{url_for('contact_new')}">+ Add Contact</a>
          <a class="btn" href="{url_for('products')}">Products</a>
        </div>
      </div>
      <div class="table">
        <table>
          <thead><tr><th>Country</th><th>Total ({CURRENCY})</th></tr></thead>
          <tbody>
    """
    if top:
        for r in top:
            body += f"<tr><td>{html_escape(r['country'] or '-')}</td><td>{money(r['total'])}</td></tr>"
    else:
        body += "<tr><td colspan='2'>No invoices yet.</td></tr>"
    body += """
          </tbody>
        </table>
      </div>
    </div>
    """
    return page("Dashboard", body)


# ---------------- Contacts ----------------
@app.get("/contacts")
@login_required
def contacts():
    q = (request.args.get("q") or "").strip()
    db = get_db()
    params = []
    sql = "SELECT * FROM contacts"
    if q:
        like = f"%{q}%"
        sql += " WHERE name LIKE ? OR company LIKE ? OR country LIKE ? OR phone LIKE ? OR email LIKE ? OR whatsapp LIKE ?"
        params = [like, like, like, like, like, like]
    sql += " ORDER BY created_at DESC LIMIT 500"
    rows = db.execute(sql, params).fetchall()

    body = f"""
    <div class="row">
      <h2 style="margin:0;">Contacts</h2>
      <div class="no-print">
        <a class="btn primary" href="{url_for('contact_new')}">+ New Contact</a>
      </div>
    </div>

    <div class="card no-print">
      <form method="get" class="row" style="justify-content:flex-start;">
        <div style="flex:1;min-width:260px;">
          <input name="q" placeholder="Search..." value="{html_escape(q)}">
        </div>
        <button class="btn" type="submit">Search</button>
      </form>
    </div>

    <div class="card">
      <div class="table">
        <table>
          <thead><tr>
            <th>Name</th><th>Company</th><th>Country</th><th>Phone/WhatsApp</th><th>Email</th><th>Status</th><th class="no-print"></th>
          </tr></thead>
          <tbody>
    """
    if rows:
        for r in rows:
            body += f"""
            <tr>
              <td>{html_escape(r['name'])}</td>
              <td>{html_escape(r['company'] or '')}</td>
              <td>{html_escape(r['country'] or '')}</td>
              <td>{html_escape((r['phone'] or '') + ' ' + (r['whatsapp'] or ''))}</td>
              <td>{html_escape(r['email'] or '')}</td>
              <td><span class="pill">{html_escape(r['status'] or '')}</span></td>
              <td class="no-print"><a class="btn" href="{url_for('contact_edit', contact_id=r['id'])}">Edit</a></td>
            </tr>
            """
    else:
        body += "<tr><td colspan='7'>No contacts.</td></tr>"

    body += """
          </tbody>
        </table>
      </div>
    </div>
    """
    return page("Contacts", body)


@app.route("/contacts/new", methods=["GET", "POST"])
@login_required
def contact_new():
    if request.method == "POST":
        f = request.form
        db = get_db()
        db.execute("""
          INSERT INTO contacts(name, company, country, city, address, email, phone, whatsapp, status, source, next_followup_date, last_contact_date, notes)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            (f.get("name") or "").strip(),
            (f.get("company") or "").strip(),
            (f.get("country") or "").strip(),
            (f.get("city") or "").strip(),
            (f.get("address") or "").strip(),
            (f.get("email") or "").strip(),
            (f.get("phone") or "").strip(),
            (f.get("whatsapp") or "").strip(),
            (f.get("status") or "Prospect").strip(),
            (f.get("source") or "").strip(),
            (f.get("next_followup_date") or "").strip(),
            (f.get("last_contact_date") or "").strip(),
            (f.get("notes") or "").strip(),
        ))
        db.commit()
        return redirect(url_for("contacts"))

    body = f"""
    <div class="card">
      <h2>New Contact</h2>
      <form method="post">
        <div class="grid2">
          <div><label>Name *</label><input name="name" required></div>
          <div><label>Company</label><input name="company"></div>
          <div><label>Country</label><input name="country"></div>
          <div><label>City</label><input name="city"></div>
          <div class="span2"><label>Address</label><input name="address"></div>
          <div><label>Email</label><input name="email"></div>
          <div><label>Phone</label><input name="phone"></div>
          <div><label>WhatsApp</label><input name="whatsapp"></div>
          <div>
            <label>Status</label>
            <select name="status">
              <option>Prospect</option>
              <option>Active Customer</option>
              <option>Dormant</option>
              <option>Lost</option>
            </select>
          </div>
          <div><label>Source</label><input name="source" placeholder="LinkedIn / Exhibition / WhatsApp"></div>
          <div><label>Next follow-up</label><input type="date" name="next_followup_date"></div>
          <div><label>Last contact</label><input type="date" name="last_contact_date"></div>
          <div class="span2"><label>Notes</label><textarea name="notes" rows="4"></textarea></div>
        </div>
        <div class="row no-print" style="justify-content:flex-end;margin-top:12px;">
          <button class="btn primary" type="submit">Save</button>
          <a class="btn" href="{url_for('contacts')}">Cancel</a>
        </div>
      </form>
    </div>
    """
    return page("New Contact", body)


@app.route("/contacts/<int:contact_id>/edit", methods=["GET", "POST"])
@login_required
def contact_edit(contact_id):
    db = get_db()
    row = db.execute("SELECT * FROM contacts WHERE id=?", (contact_id,)).fetchone()
    if not row:
        flash("Contact not found.")
        return redirect(url_for("contacts"))

    if request.method == "POST":
        f = request.form
        db.execute("""
          UPDATE contacts
          SET name=?, company=?, country=?, city=?, address=?, email=?, phone=?, whatsapp=?, status=?, source=?, next_followup_date=?, last_contact_date=?, notes=?
          WHERE id=?
        """, (
            (f.get("name") or "").strip(),
            (f.get("company") or "").strip(),
            (f.get("country") or "").strip(),
            (f.get("city") or "").strip(),
            (f.get("address") or "").strip(),
            (f.get("email") or "").strip(),
            (f.get("phone") or "").strip(),
            (f.get("whatsapp") or "").strip(),
            (f.get("status") or "Prospect").strip(),
            (f.get("source") or "").strip(),
            (f.get("next_followup_date") or "").strip(),
            (f.get("last_contact_date") or "").strip(),
            (f.get("notes") or "").strip(),
            contact_id
        ))
        db.commit()
        return redirect(url_for("contacts"))

    def v(k):
        try:
            return row[k] or ""
        except Exception:
            return ""

    body = f"""
    <div class="card">
      <h2>Edit Contact</h2>
      <form method="post">
        <div class="grid2">
          <div><label>Name *</label><input name="name" required value="{html_escape(v('name'))}"></div>
          <div><label>Company</label><input name="company" value="{html_escape(v('company'))}"></div>
          <div><label>Country</label><input name="country" value="{html_escape(v('country'))}"></div>
          <div><label>City</label><input name="city" value="{html_escape(v('city'))}"></div>
          <div class="span2"><label>Address</label><input name="address" value="{html_escape(v('address'))}"></div>
          <div><label>Email</label><input name="email" value="{html_escape(v('email'))}"></div>
          <div><label>Phone</label><input name="phone" value="{html_escape(v('phone'))}"></div>
          <div><label>WhatsApp</label><input name="whatsapp" value="{html_escape(v('whatsapp'))}"></div>
          <div>
            <label>Status</label>
            <select name="status">
              <option {"selected" if v('status')=="Prospect" else ""}>Prospect</option>
              <option {"selected" if v('status')=="Active Customer" else ""}>Active Customer</option>
              <option {"selected" if v('status')=="Dormant" else ""}>Dormant</option>
              <option {"selected" if v('status')=="Lost" else ""}>Lost</option>
            </select>
          </div>
          <div><label>Source</label><input name="source" value="{html_escape(v('source'))}"></div>
          <div><label>Next follow-up</label><input type="date" name="next_followup_date" value="{html_escape(v('next_followup_date'))}"></div>
          <div><label>Last contact</label><input type="date" name="last_contact_date" value="{html_escape(v('last_contact_date'))}"></div>
          <div class="span2"><label>Notes</label><textarea name="notes" rows="4">{html_escape(v('notes'))}</textarea></div>
        </div>
        <div class="row no-print" style="justify-content:flex-end;margin-top:12px;">
          <button class="btn primary" type="submit">Save</button>
          <a class="btn" href="{url_for('contacts')}">Cancel</a>
        </div>
      </form>
    </div>
    """
    return page("Edit Contact", body)


# ---------------- Products ----------------
@app.get("/products")
@login_required
def products():
    db = get_db()
    q = (request.args.get("q") or "").strip()

    if q:
        like = f"%{q}%"
        rows = db.execute(
            "SELECT * FROM products WHERE full_name LIKE ? OR short_name LIKE ? ORDER BY id DESC LIMIT 1000",
            (like, like)
        ).fetchall()
    else:
        rows = db.execute("SELECT * FROM products ORDER BY id DESC LIMIT 1000").fetchall()

    body = f"""
    <div class="row">
      <h2 style="margin:0;">Products</h2>
    </div>

    <div class="card">
      <form method="post" action="{url_for('product_add')}">
        <div class="grid2">
          <div><label>Short name</label><input name="short_name" placeholder="TSH"></div>
          <div><label>Full name *</label><input name="full_name" required placeholder="TSH (Thyroid Stimulating Hormone)"></div>
          <div><label>Specification</label><input name="specification"></div>
          <div><label>Package</label><input name="package"></div>
          <div><label>Unit Price ({CURRENCY})</label><input name="unit_price" type="number" step="0.01" value="0"></div>
        </div>
        <div class="row" style="justify-content:flex-end;margin-top:12px;">
          <button class="btn primary" type="submit">Add Product</button>
        </div>
      </form>
    </div>

    <div class="card no-print">
      <form method="get" class="row" style="justify-content:flex-start;">
        <div style="flex:1;min-width:260px;">
          <input name="q" placeholder="Search products..." value="{html_escape(q)}">
        </div>
        <button class="btn" type="submit">Search</button>
      </form>
    </div>

    <div class="card">
      <div class="table">
        <table>
          <thead><tr>
            <th>Short</th><th>Full name</th><th>Spec</th><th>Package</th><th>Unit Price</th><th class="no-print">Actions</th>
          </tr></thead>
          <tbody>
    """
    if rows:
        for r in rows:
            body += f"""
            <tr>
              <td>{html_escape(r['short_name'] or '')}</td>
              <td>{html_escape(r['full_name'])}</td>
              <td>{html_escape(r['specification'] or '')}</td>
              <td>{html_escape(r['package'] or '')}</td>
              <td>{money(r['unit_price'] or 0)}</td>
              <td class="no-print">
                <a class="btn" href="{url_for('product_edit', product_id=r['id'])}">Edit</a>
                <form method="post" action="{url_for('product_delete', product_id=r['id'])}" style="display:inline;" onsubmit="return confirm('Delete this product?');">
                  <button class="btn" type="submit">Delete</button>
                </form>
              </td>
            </tr>
            """
    else:
        body += "<tr><td colspan='6'>No products yet.</td></tr>"

    body += """
          </tbody>
        </table>
      </div>
    </div>
    """
    return page("Products", body)


@app.post("/products/add")
@login_required
def product_add():
    db = get_db()
    short_name = (request.form.get("short_name") or "").strip()
    full_name = (request.form.get("full_name") or "").strip()
    specification = (request.form.get("specification") or "").strip()
    package = (request.form.get("package") or "").strip()
    unit_price = float(request.form.get("unit_price") or 0)

    db.execute(
        "INSERT INTO products(short_name, full_name, specification, package, unit_price) VALUES(?,?,?,?,?)",
        (short_name, full_name, specification, package, unit_price)
    )
    db.commit()
    return redirect(url_for("products"))


@app.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@login_required
def product_edit(product_id):
    db = get_db()
    p = db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    if not p:
        flash("Product not found.")
        return redirect(url_for("products"))

    if request.method == "POST":
        db.execute("""
          UPDATE products
          SET short_name=?, full_name=?, specification=?, package=?, unit_price=?
          WHERE id=?
        """, (
            (request.form.get("short_name") or "").strip(),
            (request.form.get("full_name") or "").strip(),
            (request.form.get("specification") or "").strip(),
            (request.form.get("package") or "").strip(),
            float(request.form.get("unit_price") or 0),
            product_id
        ))
        db.commit()
        return redirect(url_for("products"))

    body = f"""
    <div class="card">
      <h2>Edit Product</h2>
      <form method="post">
        <div class="grid2">
          <div><label>Short name</label><input name="short_name" value="{html_escape(p['short_name'] or '')}"></div>
          <div><label>Full name *</label><input name="full_name" required value="{html_escape(p['full_name'])}"></div>
          <div><label>Specification</label><input name="specification" value="{html_escape(p['specification'] or '')}"></div>
          <div><label>Package</label><input name="package" value="{html_escape(p['package'] or '')}"></div>
          <div><label>Unit Price ({CURRENCY})</label><input name="unit_price" type="number" step="0.01" value="{p['unit_price'] or 0}"></div>
        </div>
        <div class="row" style="justify-content:flex-end;margin-top:12px;">
          <button class="btn primary" type="submit">Save</button>
          <a class="btn" href="{url_for('products')}">Cancel</a>
        </div>
      </form>
    </div>
    """
    return page("Edit Product", body)


@app.post("/products/<int:product_id>/delete")
@login_required
def product_delete(product_id):
    db = get_db()
    db.execute("DELETE FROM products WHERE id=?", (product_id,))
    db.commit()
    return redirect(url_for("products"))


# ---------------- Invoices ----------------
@app.get("/invoices")
@login_required
def invoices():
    db = get_db()
    rows = db.execute("""
      SELECT i.*, c.name AS contact_name, c.company AS contact_company, c.country AS contact_country
      FROM invoices i JOIN contacts c ON c.id=i.contact_id
      ORDER BY i.issue_date DESC, i.id DESC
      LIMIT 500
    """).fetchall()

    body = f"""
    <div class="row">
      <h2 style="margin:0;">Invoices</h2>
      <div class="no-print">
        <a class="btn primary" href="{url_for('invoice_new')}">+ Create Invoice</a>
      </div>
    </div>
    <div class="card">
      <div class="table">
        <table>
          <thead><tr><th>Invoice No</th><th>Date</th><th>Customer</th><th>Country</th><th>Total ({CURRENCY})</th><th class="no-print"></th></tr></thead>
          <tbody>
    """
    if rows:
        for r in rows:
            cust = r["contact_name"]
            if r["contact_company"]:
                cust += " — " + r["contact_company"]
            body += f"""
              <tr>
                <td>{html_escape(r['invoice_no'])}</td>
                <td>{html_escape(r['issue_date'])}</td>
                <td>{html_escape(cust)}</td>
                <td>{html_escape(r['contact_country'] or '')}</td>
                <td>{money(r['total_amount'])}</td>
                <td class="no-print"><a class="btn" href="{url_for('invoice_view', invoice_id=r['id'])}">View</a></td>
              </tr>
            """
    else:
        body += "<tr><td colspan='6'>No invoices yet.</td></tr>"

    body += """
          </tbody>
        </table>
      </div>
    </div>
    """
    return page("Invoices", body)


@app.route("/invoices/new", methods=["GET", "POST"])
@login_required
def invoice_new():
    db = get_db()

    contacts_list = db.execute("""
      SELECT id, name, company, address, city, country, phone, whatsapp, email
      FROM contacts
      ORDER BY created_at DESC
      LIMIT 3000
    """).fetchall()

    prows = db.execute("SELECT short_name, full_name, specification, package, unit_price FROM products ORDER BY full_name LIMIT 8000").fetchall()

    # Products for autocomplete
    labels = []
    meta = {}
    for p in prows:
        label = product_label(p["short_name"], p["full_name"])
        labels.append(label)
        meta[label] = {
            "unit_price": float(p["unit_price"] or 0),
            "specification": p["specification"] or "",
            "package": p["package"] or ""
        }
    meta_json = json.dumps(meta)

    # Contacts for Bill/Ship autofill
    contact_map = {}
    for c in contacts_list:
        phone = (c["phone"] or "").strip()
        wa = (c["whatsapp"] or "").strip()
        phone_combo = (phone + (" " + wa if wa else "")).strip()
        contact_map[str(c["id"])] = {
            "name": c["name"] or "",
            "company": c["company"] or "",
            "address": c["address"] or "",
            "city": c["city"] or "",
            "country": c["country"] or "",
            "phone": phone_combo,
            "email": c["email"] or ""
        }
    contact_map_json = json.dumps(contact_map)

    if request.method == "POST":
        f = request.form
        contact_id = int(f.get("contact_id"))

        invoice_no = generate_invoice_no()
        issue_date = (f.get("issue_date") or datetime.now().strftime("%Y-%m-%d")).strip()

        required_delivery_date = (f.get("required_delivery_date") or "").strip()
        delivery_mode = (f.get("delivery_mode") or "").strip()
        trade_terms = (f.get("trade_terms") or "").strip()
        payment_terms = (f.get("payment_terms") or "100% before shipping").strip()
        shipping_date = (f.get("shipping_date") or "").strip()
        internal_shipping_fee = float(f.get("internal_shipping_fee") or 0)
        previous_balance_note = (f.get("previous_balance_note") or "").strip()
        notes = (f.get("notes") or "").strip()

        bill_name = (f.get("bill_name") or "").strip()
        bill_company = (f.get("bill_company") or "").strip()
        bill_address = (f.get("bill_address") or "").strip()
        bill_city = (f.get("bill_city") or "").strip()
        bill_country = (f.get("bill_country") or "").strip()
        bill_phone = (f.get("bill_phone") or "").strip()
        bill_email = (f.get("bill_email") or "").strip()

        ship_name = (f.get("ship_name") or "").strip()
        ship_company = (f.get("ship_company") or "").strip()
        ship_address = (f.get("ship_address") or "").strip()
        ship_city = (f.get("ship_city") or "").strip()
        ship_country = (f.get("ship_country") or "").strip()
        ship_phone = (f.get("ship_phone") or "").strip()
        ship_email = (f.get("ship_email") or "").strip()

        # Safety: if Bill empty, fill from contact
        c = db.execute("SELECT name, company, address, city, country, phone, whatsapp, email FROM contacts WHERE id=?", (contact_id,)).fetchone()
        if c:
            if not bill_name: bill_name = c["name"] or ""
            if not bill_company: bill_company = c["company"] or ""
            if not bill_address: bill_address = c["address"] or ""
            if not bill_city: bill_city = c["city"] or ""
            if not bill_country: bill_country = c["country"] or ""
            combo = ((c["phone"] or "") + (" " + (c["whatsapp"] or "") if (c["whatsapp"] or "") else "")).strip()
            if not bill_phone: bill_phone = combo
            if not bill_email: bill_email = c["email"] or ""

        # If Ship empty, copy from Bill
        if (not ship_name and not ship_company and not ship_address and not ship_city and not ship_country and not ship_phone and not ship_email):
            ship_name, ship_company, ship_address, ship_city, ship_country, ship_phone, ship_email = (
                bill_name, bill_company, bill_address, bill_city, bill_country, bill_phone, bill_email
            )

        cur = db.execute("""
          INSERT INTO invoices(
            invoice_no, contact_id, issue_date, required_delivery_date, delivery_mode, trade_terms, payment_terms, shipping_date,
            internal_shipping_fee, previous_balance_note, currency, notes,
            bill_name, bill_company, bill_address, bill_city, bill_country, bill_phone, bill_email,
            ship_name, ship_company, ship_address, ship_city, ship_country, ship_phone, ship_email
          )
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            invoice_no, contact_id, issue_date, required_delivery_date, delivery_mode, trade_terms, payment_terms, shipping_date,
            internal_shipping_fee, previous_balance_note, CURRENCY, notes,
            bill_name, bill_company, bill_address, bill_city, bill_country, bill_phone, bill_email,
            ship_name, ship_company, ship_address, ship_city, ship_country, ship_phone, ship_email
        ))
        invoice_id = cur.lastrowid

        descriptions = request.form.getlist("description[]")
        specs = request.form.getlist("specification[]")
        packs = request.form.getlist("package[]")
        forms = request.form.getlist("form[]")
        qtys = request.form.getlist("quantity[]")
        ups = request.form.getlist("unit_price[]")

        total = 0.0
        line = 1
        for i in range(len(descriptions)):
            desc = (descriptions[i] or "").strip()
            if not desc:
                continue
            qty = float(qtys[i] or 0)
            up = float(ups[i] or 0)
            amt = qty * up
            total += amt

            db.execute("""
              INSERT INTO invoice_items(invoice_id, line_no, description, specification, package, form, quantity, unit_price, amount)
              VALUES(?,?,?,?,?,?,?,?,?)
            """, (
                invoice_id, line, desc,
                (specs[i] or "").strip(),
                (packs[i] or "").strip(),
                (forms[i] or "").strip(),
                qty, up, amt
            ))
            line += 1

        total += internal_shipping_fee
        db.execute("UPDATE invoices SET total_amount=? WHERE id=?", (total, invoice_id))
        db.commit()
        return redirect(url_for("invoice_view", invoice_id=invoice_id))

    options = ""
    for c in contacts_list:
        label = c["name"]
        if c["company"]:
            label += " — " + c["company"]
        if c["country"]:
            label += f" ({c['country']})"
        options += f"<option value='{c['id']}'>{html_escape(label)}</option>"

    datalist = "".join([f"<option value='{html_escape(x)}'></option>" for x in labels])
    today = datetime.now().strftime("%Y-%m-%d")

    body = f"""
    <div class="card">
      <h2>Create Invoice</h2>
      <form method="post">
        <div class="grid2">
          <div class="span2">
            <label>Customer *</label>
            <select name="contact_id" required>
              <option value="">Select...</option>
              {options}
            </select>
          </div>
          <div><label>Issue date</label><input type="date" name="issue_date" value="{today}"></div>
          <div><label>Required delivery date</label><input type="date" name="required_delivery_date"></div>
          <div><label>Delivery mode</label><input name="delivery_mode" placeholder="by air / by sea"></div>
          <div><label>Trade terms</label><input name="trade_terms" placeholder="FOB / CIF / ..."></div>
          <div><label>Payment terms</label><input name="payment_terms" value="100% before shipping"></div>
          <div><label>Shipping date</label><input type="date" name="shipping_date"></div>
          <div><label>Internal shipping fee ({CURRENCY})</label><input name="internal_shipping_fee" type="number" step="0.01" value="0"></div>
          <div><label>Previous balance note</label><input name="previous_balance_note" placeholder="Remaining payment for last order..."></div>
          <div class="span2"><label>Notes</label><textarea name="notes" rows="2"></textarea></div>
        </div>

        <h3>Bill To (Left) / Ship To (Right)</h3>

        <div class="grid2" style="gap:18px; align-items:start;">
          <div class="card" style="border:1px solid #eee;">
            <div class="row" style="justify-content:space-between;">
              <h4 style="margin:0;">Bill To</h4>
              <label style="display:flex;gap:8px;align-items:center;font-weight:900;">
                <input type="checkbox" id="lock_bill">
                Lock
              </label>
            </div>

            <div class="row no-print" style="justify-content:flex-start;margin-top:10px;">
              <button class="btn" type="button" onclick="fillBillFromCustomer()">Autofill from Customer</button>
              <button class="btn" type="button" onclick="clearBill()">Clear</button>
            </div>

            <label>Name</label><input name="bill_name">
            <label>Company</label><input name="bill_company">
            <label>Address</label><input name="bill_address">
            <label>City</label><input name="bill_city">
            <label>Country</label><input name="bill_country">
            <label>Phone</label><input name="bill_phone">
            <label>Email</label><input name="bill_email">
          </div>

          <div class="card" style="border:1px solid #eee;">
            <div class="row" style="justify-content:space-between;">
              <h4 style="margin:0;">Ship To</h4>
              <label style="display:flex;gap:8px;align-items:center;font-weight:900;">
                <input type="checkbox" id="ship_same" checked>
                Same as Bill To
              </label>
            </div>

            <div class="row no-print" style="justify-content:flex-start;margin-top:10px;">
              <button class="btn" type="button" onclick="copyBillToShip()">Copy Bill → Ship</button>
              <button class="btn" type="button" onclick="clearShip()">Clear</button>
            </div>

            <label>Name</label><input name="ship_name">
            <label>Company</label><input name="ship_company">
            <label>Address</label><input name="ship_address">
            <label>City</label><input name="ship_city">
            <label>Country</label><input name="ship_country">
            <label>Phone</label><input name="ship_phone">
            <label>Email</label><input name="ship_email">
          </div>
        </div>

        <datalist id="products_list">{datalist}</datalist>

        <h3>Items</h3>
        <div class="table">
          <table id="t">
            <thead>
              <tr>
                <th style="width:26%">Description</th>
                <th style="width:18%">Specification</th>
                <th style="width:14%">Package</th>
                <th style="width:10%">Form</th>
                <th style="width:10%">Qty</th>
                <th style="width:12%">Unit Price</th>
                <th style="width:10%">Amount</th>
                <th class="no-print"></th>
              </tr>
            </thead>
            <tbody></tbody>
          </table>
        </div>

        <div class="row no-print" style="justify-content:flex-start;margin-top:10px;">
          <button class="btn" type="button" onclick="addRow()">+ Add line</button>
        </div>

        <div class="row" style="margin-top:10px;">
          <div></div>
          <div class="kpi">{CURRENCY} <span id="total">0.00</span></div>
        </div>

        <div class="row no-print" style="justify-content:flex-end;margin-top:12px;">
          <button class="btn primary" type="submit">Save Invoice</button>
          <a class="btn" href="{url_for('invoices')}">Cancel</a>
        </div>
      </form>
    </div>

    <script>
      const PRODUCT_META = {meta_json};
      const CONTACTS = {contact_map_json};

      function money(x){{ return (Math.round((x+Number.EPSILON)*100)/100).toFixed(2); }}

      function setVal(name, val){{
        const el = document.querySelector(`[name="${{name}}"]`);
        if(el) el.value = val || "";
      }}
      function getVal(name){{
        const el = document.querySelector(`[name="${{name}}"]`);
        return el ? (el.value || "") : "";
      }}

      function fillBillFromCustomer(){{
        const id = document.querySelector(`[name="contact_id"]`).value;
        if(!id) return;
        if(document.getElementById("lock_bill").checked) return;

        const c = CONTACTS[id];
        if(!c) return;

        setVal("bill_name", c.name);
        setVal("bill_company", c.company);
        setVal("bill_address", c.address);
        setVal("bill_city", c.city);
        setVal("bill_country", c.country);
        setVal("bill_phone", c.phone);
        setVal("bill_email", c.email);

        if(document.getElementById("ship_same").checked){{
          copyBillToShip();
        }}
      }}

      function copyBillToShip(){{
        setVal("ship_name", getVal("bill_name"));
        setVal("ship_company", getVal("bill_company"));
        setVal("ship_address", getVal("bill_address"));
        setVal("ship_city", getVal("bill_city"));
        setVal("ship_country", getVal("bill_country"));
        setVal("ship_phone", getVal("bill_phone"));
        setVal("ship_email", getVal("bill_email"));
      }}

      function clearBill(){{
        ["bill_name","bill_company","bill_address","bill_city","bill_country","bill_phone","bill_email"].forEach(x=>setVal(x,""));
      }}
      function clearShip(){{
        ["ship_name","ship_company","ship_address","ship_city","ship_country","ship_phone","ship_email"].forEach(x=>setVal(x,""));
      }}

      // Customer change -> autofill Bill
      document.querySelector(`[name="contact_id"]`).addEventListener("change", () => {{
        fillBillFromCustomer();
      }});

      // If Ship Same is ON, keep ship updated while editing Bill
      ["bill_name","bill_company","bill_address","bill_city","bill_country","bill_phone","bill_email"].forEach(n=>{{
        const el = document.querySelector(`[name="${{n}}"]`);
        if(!el) return;
        el.addEventListener("input", ()=>{{
          if(document.getElementById("ship_same").checked) copyBillToShip();
        }});
      }});

      function applyMeta(descInput) {{
        const key = (descInput.value || "").trim();
        const meta = PRODUCT_META[key];
        if (!meta) return;

        const tr = descInput.closest("tr");
        const spec = tr.querySelector("input[name='specification[]']");
        const pack = tr.querySelector("input[name='package[]']");
        const up   = tr.querySelector("input[name='unit_price[]']");

        if (spec && (!spec.value)) spec.value = meta.specification || "";
        if (pack && (!pack.value)) pack.value = meta.package || "";
        if (up && (!up.value || parseFloat(up.value) === 0)) up.value = meta.unit_price || 0;

        recalc();
      }}

      function recalc(){{
        let total = 0;
        document.querySelectorAll("tr[data-row]").forEach(tr => {{
          const qty = parseFloat(tr.querySelector("input[name='quantity[]']").value || "0");
          const up  = parseFloat(tr.querySelector("input[name='unit_price[]']").value || "0");
          const amt = qty * up;
          tr.querySelector(".amt").textContent = money(amt);
          total += amt;
        }});
        const fee = parseFloat(document.querySelector("input[name='internal_shipping_fee']").value || "0");
        total += fee;
        document.getElementById("total").textContent = money(total);
      }}

      function addRow(){{
        const tb = document.querySelector("#t tbody");
        const tr = document.createElement("tr");
        tr.setAttribute("data-row","1");
        tr.innerHTML = `
          <td><input name="description[]" list="products_list" placeholder="Start typing product..." onblur="applyMeta(this)"></td>
          <td><input name="specification[]" placeholder="Spec"></td>
          <td><input name="package[]" placeholder="Package"></td>
          <td><input name="form[]" value="CE type"></td>
          <td><input name="quantity[]" type="number" step="1" value="1" oninput="recalc()"></td>
          <td><input name="unit_price[]" type="number" step="0.01" value="0" oninput="recalc()"></td>
          <td class="amt">0.00</td>
          <td class="no-print"><button class="btn" type="button" onclick="this.closest('tr').remove();recalc();">X</button></td>
        `;
        tb.appendChild(tr);
        recalc();
      }}

      document.addEventListener("input", function(e){{
        if(e.target && e.target.name==="internal_shipping_fee") recalc();
      }});

      addRow();
    </script>
    """
    return page("Create Invoice", body)


@app.get("/invoices/<int:invoice_id>")
@login_required
def invoice_view(invoice_id):
    db = get_db()

    def rget(row, key, default=""):
        try:
            v = row[key]
            return default if v is None else v
        except Exception:
            return default

    inv = db.execute("""
      SELECT i.*, c.name AS c_name, c.company AS c_company, c.address AS c_address, c.city AS c_city, c.country AS c_country,
             c.phone AS c_phone, c.whatsapp AS c_whatsapp, c.email AS c_email
      FROM invoices i JOIN contacts c ON c.id=i.contact_id
      WHERE i.id=?
    """, (invoice_id,)).fetchone()

    if not inv:
        flash("Invoice not found.")
        return redirect(url_for("invoices"))

    items = db.execute(
        "SELECT * FROM invoice_items WHERE invoice_id=? ORDER BY line_no",
        (invoice_id,)
    ).fetchall()

    contact_phone_combo = ((rget(inv, "c_phone") or "") + (" " + (rget(inv, "c_whatsapp") or "") if (rget(inv, "c_whatsapp") or "") else "")).strip()

    def first_non_empty(*vals):
        for v in vals:
            if v is not None and str(v).strip() != "":
                return str(v)
        return ""

    bill_name = first_non_empty(rget(inv, "bill_name"), rget(inv, "c_name"))
    bill_company = first_non_empty(rget(inv, "bill_company"), rget(inv, "c_company"))
    bill_address = first_non_empty(rget(inv, "bill_address"), rget(inv, "c_address"))
    bill_city = first_non_empty(rget(inv, "bill_city"), rget(inv, "c_city"))
    bill_country = first_non_empty(rget(inv, "bill_country"), rget(inv, "c_country"))
    bill_phone = first_non_empty(rget(inv, "bill_phone"), contact_phone_combo)
    bill_email = first_non_empty(rget(inv, "bill_email"), rget(inv, "c_email"))

    ship_name = first_non_empty(rget(inv, "ship_name"), bill_name)
    ship_company = first_non_empty(rget(inv, "ship_company"), bill_company)
    ship_address = first_non_empty(rget(inv, "ship_address"), bill_address)
    ship_city = first_non_empty(rget(inv, "ship_city"), bill_city)
    ship_country = first_non_empty(rget(inv, "ship_country"), bill_country)
    ship_phone = first_non_empty(rget(inv, "ship_phone"), bill_phone)
    ship_email = first_non_empty(rget(inv, "ship_email"), bill_email)

    rows = ""
    for it in items:
        rows += f"""
        <tr>
          <td>{it['line_no']}</td>
          <td>{html_escape(it['description'])}</td>
          <td>{html_escape(it['specification'] or '')}</td>
          <td>{html_escape(it['package'] or '')}</td>
          <td>{html_escape(it['form'] or '')}</td>
          <td>{it['quantity']}</td>
          <td>{money(it['unit_price'])}</td>
          <td>{money(it['amount'])}</td>
        </tr>
        """

    prev_note = html_escape(rget(inv, "previous_balance_note") or "")
    internal_fee = float(rget(inv, "internal_shipping_fee") or 0)

    body = f"""
    <div class="row no-print">
      <h2 style="margin:0;">Invoice</h2>
      <div>
        <button class="btn primary" onclick="window.print()">Print / Save PDF</button>
        <a class="btn" href="{url_for('invoices')}">Back</a>
      </div>
    </div>

    <div class="card">
      <div class="row" style="align-items:flex-start;">
        <div>
          <img src="{LOGO_URL}" style="max-height:90px;margin-bottom:8px;" alt="Logo">
          <div style="font-size:20px;font-weight:950;">{html_escape(COMPANY_NAME)}</div>
          <div>{html_escape(COMPANY_ADDRESS)}</div>
          <div>{html_escape(COMPANY_EMAIL)}</div>
          {"<div>"+html_escape(COMPANY_PHONE)+"</div>" if COMPANY_PHONE else ""}
        </div>
        <div style="text-align:right;">
          <div style="font-size:22px;font-weight:950;">Proforma Invoice</div>
          <div><b>No.:</b> {html_escape(rget(inv,'invoice_no'))}</div>
          <div><b>Date:</b> {html_escape(rget(inv,'issue_date'))}</div>
        </div>
      </div>

      <hr>

      <div class="grid2" style="gap:24px; align-items:start;">
        <div>
          <h3>Bill To</h3>
          <div><b>{html_escape(bill_name)}</b></div>
          <div>{html_escape(bill_company)}</div>
          <div>{html_escape(bill_address)}</div>
          <div>{html_escape((bill_city + " " + bill_country).strip())}</div>
          <div>{html_escape(bill_phone)}</div>
          <div>{html_escape(bill_email)}</div>
        </div>

        <div>
          <h3>Ship To</h3>
          <div><b>{html_escape(ship_name)}</b></div>
          <div>{html_escape(ship_company)}</div>
          <div>{html_escape(ship_address)}</div>
          <div>{html_escape((ship_city + " " + ship_country).strip())}</div>
          <div>{html_escape(ship_phone)}</div>
          <div>{html_escape(ship_email)}</div>
        </div>
      </div>

      <div style="margin-top:14px;">
        <div><b>Required Delivery Date:</b> {html_escape(rget(inv,'required_delivery_date') or '')}</div>
        <div><b>Delivery Mode:</b> {html_escape(rget(inv,'delivery_mode') or '')}</div>
        <div><b>Trade Terms:</b> {html_escape(rget(inv,'trade_terms') or '')}</div>
        <div><b>Payment Terms:</b> {html_escape(rget(inv,'payment_terms') or '')}</div>
        <div><b>Shipping Date:</b> {html_escape(rget(inv,'shipping_date') or '')}</div>
        <div><b>Currency:</b> {html_escape(rget(inv,'currency') or CURRENCY)}</div>
      </div>

      <div class="table" style="margin-top:12px;">
        <table>
          <thead>
            <tr>
              <th style="width:6%;">Line</th>
              <th style="width:28%;">Description</th>
              <th style="width:16%;">Specification</th>
              <th style="width:12%;">Package</th>
              <th style="width:10%;">Form</th>
              <th style="width:8%;">Qty</th>
              <th style="width:10%;">Unit Price ({CURRENCY})</th>
              <th style="width:10%;">Amount ({CURRENCY})</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
      </div>

      <div style="text-align:right; margin-top:10px;">
        {f"<div>{prev_note}</div>" if prev_note else ""}
        {f"<div><b>Internal shipping fee:</b> {money(internal_fee)}</div>" if internal_fee != 0 else ""}
        <div style="font-size:18px;"><b>Total Payment:</b> {money(rget(inv,'total_amount'))} {html_escape(rget(inv,'currency') or CURRENCY)}</div>
      </div>

      <div style="margin-top:14px;">
        <h3>BANK INFORMATIONS FOR T/T PAYMENT:</h3>
        <pre style="white-space:pre-wrap;background:#fafafa;border:1px solid #eee;padding:12px;border-radius:14px;">{html_escape(BANK_INFO)}</pre>
      </div>
    </div>
    """
    return page("Invoice", body)




@app.errorhandler(500)
def internal_error(e):
    return page("Error", """
      <div class="card">
        <h2>Internal Server Error</h2>
        <p>Open Render Logs to see the traceback.</p>
        <p class="no-print"><a class="btn" href="/">Go Home</a></p>
      </div>
    """), 500
