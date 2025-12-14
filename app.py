import os
import sqlite3
from functools import wraps
from datetime import datetime
from flask import (
    Flask, request, redirect, url_for, session, flash,
    jsonify, render_template_string, abort
)

# ============================================================
# Config
# ============================================================

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-please")

# Admin login (set these in Render Environment)
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "zakarea.job@hotmail.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "ZAKCRM2026")

# Company info shown on invoice
COMPANY_NAME = os.environ.get("COMPANY_NAME", "Hotgen")
COMPANY_ADDRESS = os.environ.get(
    "COMPANY_ADDRESS",
    "No. 55 Qingfeng West Road, Daxing District, 102629, Beijing, China"
)
COMPANY_EMAIL = os.environ.get("COMPANY_EMAIL", "zakarea@hotgen.com.cn")
COMPANY_PHONE = os.environ.get("COMPANY_PHONE", "")

# Bank info shown on invoice (edit as you like)
BANK_INFO = os.environ.get("BANK_INFO", """Beneficiary: Beijing Hotgen Biotech Co.,Ltd
SWIFT: CMBCCNBS
Bank Name: China Merchants Bank H.Q. Shenzhen
Bank Address: China Merchants Bank Tower NO.7088, Shennan Boulevard, Shenzhen, China.
A/C USD: 11090929643280
EURO: 110909296435702
""")

CURRENCY_DEFAULT = os.environ.get("CURRENCY_DEFAULT", "USD")

# Logo (you said: static/hotgen_logo.png)
LOGO_STATIC_FILENAME = os.environ.get("LOGO_FILE", "hotgen_logo.png")

# SQLite path (Render Persistent Disk best practice: /var/data)
def resolve_db_path() -> str:
    # If user explicitly sets DATABASE_PATH, use it.
    explicit = os.environ.get("DATABASE_PATH")
    if explicit:
        return explicit

    # If Render Persistent Disk mounted at /var/data, use it.
    if os.path.isdir("/var/data"):
        return "/var/data/zakcrm.db"

    # Fallback: local file beside app.py (may reset on Render restarts/deploys)
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "zakcrm.db")


DB_PATH = resolve_db_path()


# ============================================================
# Helpers
# ============================================================

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper


def html_escape(s: str) -> str:
    if s is None:
        return ""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;"))


def money(x) -> str:
    try:
        return f"{float(x):,.2f}"
    except Exception:
        return "0.00"


def now_date_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def table_has_column(db, table: str, col: str) -> bool:
    rows = db.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == col for r in rows)


def ensure_schema():
    db = get_db()
    try:
        db.executescript("""
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
          form TEXT,
          unit_price REAL DEFAULT 0,
          currency TEXT DEFAULT 'USD',
          active INTEGER DEFAULT 1,
          created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS invoices (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          contact_id INTEGER NOT NULL,
          invoice_no TEXT,
          issue_date TEXT,
          required_delivery_date TEXT,
          delivery_mode TEXT,
          trade_terms TEXT,
          payment_terms TEXT,
          shipping_date TEXT,
          currency TEXT DEFAULT 'USD',
          total_amount REAL DEFAULT 0,
          internal_shipping_fee REAL DEFAULT 0,
          previous_balance_note TEXT,

          bill_name TEXT,
          bill_company TEXT,
          bill_address TEXT,
          bill_city TEXT,
          bill_country TEXT,
          bill_phone TEXT,
          bill_email TEXT,

          ship_name TEXT,
          ship_company TEXT,
          ship_address TEXT,
          ship_city TEXT,
          ship_country TEXT,
          ship_phone TEXT,
          ship_email TEXT,

          created_at TEXT DEFAULT (datetime('now')),
          updated_at TEXT,

          FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS invoice_items (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          invoice_id INTEGER NOT NULL,
          line_no INTEGER NOT NULL,
          product_id INTEGER,
          description TEXT NOT NULL,
          specification TEXT,
          package TEXT,
          form TEXT,
          quantity REAL DEFAULT 0,
          unit_price REAL DEFAULT 0,
          amount REAL DEFAULT 0,

          FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE,
          FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL
        );
        """)

        # ---- Simple migration safety (adds missing columns if you had an older DB) ----
        # invoices columns
        invoice_cols = [
            ("previous_balance_note", "TEXT"),
            ("internal_shipping_fee", "REAL DEFAULT 0"),
            ("bill_name", "TEXT"),
            ("bill_company", "TEXT"),
            ("bill_address", "TEXT"),
            ("bill_city", "TEXT"),
            ("bill_country", "TEXT"),
            ("bill_phone", "TEXT"),
            ("bill_email", "TEXT"),
            ("ship_name", "TEXT"),
            ("ship_company", "TEXT"),
            ("ship_address", "TEXT"),
            ("ship_city", "TEXT"),
            ("ship_country", "TEXT"),
            ("ship_phone", "TEXT"),
            ("ship_email", "TEXT"),
        ]
        for col, typ in invoice_cols:
            if not table_has_column(db, "invoices", col):
                db.execute(f"ALTER TABLE invoices ADD COLUMN {col} {typ};")

        # products columns
        product_cols = [
            ("short_name", "TEXT"),
            ("full_name", "TEXT"),
            ("specification", "TEXT"),
            ("package", "TEXT"),
            ("form", "TEXT"),
            ("unit_price", "REAL DEFAULT 0"),
            ("currency", "TEXT DEFAULT 'USD'"),
            ("active", "INTEGER DEFAULT 1"),
        ]
        for col, typ in product_cols:
            if not table_has_column(db, "products", col):
                db.execute(f"ALTER TABLE products ADD COLUMN {col} {typ};")

        db.commit()
    finally:
        db.close()


@app.before_request
def _init():
    ensure_schema()


# ============================================================
# UI Shell + CSS (includes print invoice styling)
# ============================================================

BASE_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1"/>
  <title>{{ title }}</title>
  <style>
    :root{
      --bg:#f6f7fb;
      --card:#fff;
      --text:#111;
      --muted:#666;
      --line:#e7e7e7;
      --brand:#111;
      --btn:#111;
      --btn2:#fff;
      --radius:16px;
    }
    body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;background:var(--bg);color:var(--text);}
    .topbar{position:sticky;top:0;z-index:9;background:#111;color:#fff;padding:12px 16px;display:flex;align-items:center;justify-content:space-between;}
    .brand{font-weight:900;letter-spacing:.5px;}
    .nav a{color:#fff;text-decoration:none;margin-left:10px;background:rgba(255,255,255,.12);padding:8px 12px;border-radius:14px;display:inline-block;}
    .wrap{max-width:1100px;margin:18px auto;padding:0 12px;}
    .card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:16px;box-shadow:0 6px 20px rgba(0,0,0,.04);}
    h1,h2,h3{margin:0 0 10px 0;}
    .muted{color:var(--muted);}
    .row{display:flex;gap:12px;flex-wrap:wrap;align-items:center;justify-content:space-between;}
    .grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px;}
    @media (max-width: 820px){ .grid2{grid-template-columns:1fr;} }
    .btn{border:1px solid var(--line);background:var(--btn2);color:var(--text);padding:10px 14px;border-radius:14px;cursor:pointer;text-decoration:none;display:inline-block;}
    .btn.primary{background:var(--btn);color:#fff;border-color:#111;}
    .btn.danger{background:#b00020;color:#fff;border-color:#b00020;}
    input,select,textarea{
      width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid var(--line);
      border-radius:14px;font-size:15px;background:#fff;
    }
    textarea{min-height:90px;}
    label{font-size:13px;color:#444;margin-bottom:6px;display:block;}
    .field{margin-bottom:12px;}
    .table{overflow:auto;border:1px solid var(--line);border-radius:16px;}
    table{width:100%;border-collapse:collapse;min-width:900px;}
    th,td{padding:10px;border-bottom:1px solid var(--line);text-align:left;font-size:14px;vertical-align:top;}
    th{background:#fafafa;}
    .right{text-align:right;}
    .pill{display:inline-block;padding:4px 10px;border:1px solid var(--line);border-radius:999px;font-size:12px;color:#333;background:#fff;}
    .flash{margin:10px 0;padding:10px 12px;border-radius:14px;background:#fff3cd;border:1px solid #ffeeba;color:#664d03;}
    .small{font-size:12px;}
    .actions{display:flex;gap:8px;flex-wrap:wrap;}
    .hr{height:1px;background:var(--line);margin:14px 0;}
    .kpi{display:flex;gap:12px;flex-wrap:wrap}
    .kpi .box{flex:1;min-width:220px;background:#fff;border:1px solid var(--line);border-radius:16px;padding:12px;}
    .print-note{display:none;}

    /* ================= PRINT ================= */
    @media print{
      body{background:#fff;}
      .topbar,.no-print{display:none !important;}
      .wrap{max-width:100%;margin:0;padding:0;}
      .card{border:0;box-shadow:none;border-radius:0;padding:0;}
      .table{border:0;}
      table{min-width:0;width:100%;table-layout:fixed;}
      th,td{font-size:12px;padding:6px;word-wrap:break-word;}
      .print-note{display:block;margin:8px 0;color:#444;font-size:12px;}
    }
  </style>
</head>
<body>
  <div class="topbar">
    <div class="brand">ZAK CRM</div>
    <div class="nav">
      {% if logged_in %}
        <a href="{{ url_for('dashboard') }}">Dashboard</a>
        <a href="{{ url_for('contacts') }}">Contacts</a>
        <a href="{{ url_for('products') }}">Products</a>
        <a href="{{ url_for('invoices') }}">Invoices</a>
        <a href="{{ url_for('logout') }}">Logout</a>
      {% else %}
        <a href="{{ url_for('login') }}">Login</a>
      {% endif %}
    </div>
  </div>

  <div class="wrap">
    {% for m in messages %}
      <div class="flash">{{ m }}</div>
    {% endfor %}
    {{ body|safe }}
  </div>
</body>
</html>
"""


def page(title: str, body_html: str):
    messages = list(session.pop("_flashes", []))
    return render_template_string(
        BASE_HTML,
        title=title,
        body=body_html,
        logged_in=bool(session.get("logged_in")),
        messages=messages
    )


def flash_msg(msg: str):
    session.setdefault("_flashes", []).append(msg)


# ============================================================
# Auth
# ============================================================

@app.get("/login")
def login():
    nxt = request.args.get("next", "/dashboard")
    body = f"""
      <div class="card" style="max-width:520px;margin:40px auto;">
        <h2>Login</h2>
        <p class="muted small">Admin only.</p>
        <form method="post" action="{url_for('login_post')}">
          <input type="hidden" name="next" value="{html_escape(nxt)}"/>
          <div class="field">
            <label>Email</label>
            <input name="email" type="email" required value="{html_escape(ADMIN_EMAIL)}"/>
          </div>
          <div class="field">
            <label>Password</label>
            <input name="password" type="password" required />
          </div>
          <button class="btn primary" type="submit">Login</button>
        </form>
        <div class="hr"></div>
        <div class="small muted">
          If you see time/date + URL in PDF: in Chrome Print dialog, disable <b>Headers and footers</b>.
        </div>
      </div>
    """
    return page("Login", body)


@app.post("/login")
def login_post():
    email = request.form.get("email", "").strip()
    pw = request.form.get("password", "").strip()
    nxt = request.form.get("next", "/dashboard")

    if email == ADMIN_EMAIL and pw == ADMIN_PASSWORD:
        session["logged_in"] = True
        return redirect(nxt)
    flash_msg("Invalid login.")
    return redirect(url_for("login"))


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ============================================================
# Dashboard
# ============================================================

@app.get("/")
def home():
    return redirect(url_for("dashboard"))


@app.get("/dashboard")
@login_required
def dashboard():
    db = get_db()
    try:
        c_contacts = db.execute("SELECT COUNT(*) AS n FROM contacts").fetchone()["n"]
        c_products = db.execute("SELECT COUNT(*) AS n FROM products WHERE active=1").fetchone()["n"]
        c_invoices = db.execute("SELECT COUNT(*) AS n FROM invoices").fetchone()["n"]
        total_sales = db.execute("SELECT COALESCE(SUM(total_amount),0) AS s FROM invoices").fetchone()["s"]

        body = f"""
        <div class="card">
          <div class="row">
            <div>
              <h2>Dashboard</h2>
              <div class="muted">Simple CRM for contacts, products, invoices.</div>
            </div>
            <div class="actions">
              <a class="btn primary" href="{url_for('invoice_new')}">+ New Invoice</a>
              <a class="btn" href="{url_for('contact_new')}">+ New Contact</a>
              <a class="btn" href="{url_for('product_new')}">+ New Product</a>
            </div>
          </div>

          <div class="hr"></div>

          <div class="kpi">
            <div class="box"><div class="muted small">Contacts</div><div style="font-size:28px;font-weight:900;">{c_contacts}</div></div>
            <div class="box"><div class="muted small">Active Products</div><div style="font-size:28px;font-weight:900;">{c_products}</div></div>
            <div class="box"><div class="muted small">Invoices</div><div style="font-size:28px;font-weight:900;">{c_invoices}</div></div>
            <div class="box"><div class="muted small">Total Sales</div><div style="font-size:28px;font-weight:900;">{money(total_sales)} {html_escape(CURRENCY_DEFAULT)}</div></div>
          </div>
        </div>
        """
        return page("Dashboard", body)
    finally:
        db.close()


# ============================================================
# Contacts
# ============================================================

@app.get("/contacts")
@login_required
def contacts():
    q = request.args.get("q", "").strip()
    db = get_db()
    try:
        if q:
            rows = db.execute("""
              SELECT * FROM contacts
              WHERE name LIKE ? OR company LIKE ? OR country LIKE ? OR email LIKE ?
              ORDER BY created_at DESC
            """, (f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%")).fetchall()
        else:
            rows = db.execute("SELECT * FROM contacts ORDER BY created_at DESC").fetchall()

        trs = ""
        for r in rows:
            trs += f"""
            <tr>
              <td><b>{html_escape(r['name'])}</b><div class="muted small">{html_escape(r['company'] or '')}</div></td>
              <td>{html_escape(r['country'] or '')}<div class="muted small">{html_escape(r['city'] or '')}</div></td>
              <td>{html_escape(r['email'] or '')}<div class="muted small">{html_escape(r['phone'] or '')} {html_escape(r['whatsapp'] or '')}</div></td>
              <td><span class="pill">{html_escape(r['status'] or 'Prospect')}</span></td>
              <td class="right">
                <a class="btn" href="{url_for('contact_edit', contact_id=r['id'])}">Edit</a>
                <a class="btn danger" href="{url_for('contact_delete', contact_id=r['id'])}" onclick="return confirm('Delete this contact?')">Delete</a>
              </td>
            </tr>
            """

        body = f"""
        <div class="card">
          <div class="row">
            <div>
              <h2>Contacts</h2>
              <div class="muted small">Save prospects too (future database).</div>
            </div>
            <div class="actions">
              <a class="btn primary" href="{url_for('contact_new')}">+ New Contact</a>
            </div>
          </div>

          <div class="hr"></div>

          <form class="row no-print" method="get" action="{url_for('contacts')}" style="justify-content:flex-start;">
            <div style="flex:1;min-width:240px;">
              <input name="q" placeholder="Search name/company/country/email" value="{html_escape(q)}"/>
            </div>
            <button class="btn" type="submit">Search</button>
            <a class="btn" href="{url_for('contacts')}">Reset</a>
          </form>

          <div class="hr"></div>

          <div class="table">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Country / City</th>
                  <th>Contact</th>
                  <th>Status</th>
                  <th class="right">Actions</th>
                </tr>
              </thead>
              <tbody>{trs or "<tr><td colspan='5' class='muted'>No contacts yet.</td></tr>"}</tbody>
            </table>
          </div>
        </div>
        """
        return page("Contacts", body)
    finally:
        db.close()


def contact_form(title, action_url, c=None):
    c = c or {}
    def gv(k): return html_escape(c.get(k) or "")
    return f"""
    <div class="card">
      <div class="row">
        <h2 style="margin:0;">{html_escape(title)}</h2>
        <a class="btn" href="{url_for('contacts')}">Back</a>
      </div>
      <div class="hr"></div>

      <form method="post" action="{action_url}">
        <div class="grid2">
          <div class="field"><label>Name *</label><input name="name" required value="{gv('name')}"/></div>
          <div class="field"><label>Company</label><input name="company" value="{gv('company')}"/></div>
        </div>

        <div class="grid2">
          <div class="field"><label>Country</label><input name="country" value="{gv('country')}"/></div>
          <div class="field"><label>City</label><input name="city" value="{gv('city')}"/></div>
        </div>

        <div class="field"><label>Address</label><input name="address" value="{gv('address')}"/></div>

        <div class="grid2">
          <div class="field"><label>Email</label><input name="email" value="{gv('email')}"/></div>
          <div class="field"><label>Phone</label><input name="phone" value="{gv('phone')}"/></div>
        </div>

        <div class="grid2">
          <div class="field"><label>WhatsApp</label><input name="whatsapp" value="{gv('whatsapp')}"/></div>
          <div class="field"><label>Status</label>
            <select name="status">
              {''.join([f"<option {'selected' if gv('status')==s else ''}>{s}</option>" for s in ['Prospect','Active','VIP','Closed']])}
            </select>
          </div>
        </div>

        <div class="grid2">
          <div class="field"><label>Source</label><input name="source" value="{gv('source')}"/></div>
          <div class="field"><label>Next Follow-up Date</label><input name="next_followup_date" value="{gv('next_followup_date')}" placeholder="YYYY-MM-DD"/></div>
        </div>

        <div class="grid2">
          <div class="field"><label>Last Contact Date</label><input name="last_contact_date" value="{gv('last_contact_date')}" placeholder="YYYY-MM-DD"/></div>
          <div class="field"><label>Notes</label><textarea name="notes">{gv('notes')}</textarea></div>
        </div>

        <button class="btn primary" type="submit">Save</button>
      </form>
    </div>
    """


@app.get("/contacts/new")
@login_required
def contact_new():
    return page("New Contact", contact_form("New Contact", url_for("contact_new_post"), {"status":"Prospect"}))


@app.post("/contacts/new")
@login_required
def contact_new_post():
    f = request.form
    db = get_db()
    try:
        db.execute("""
          INSERT INTO contacts(name,company,country,city,address,email,phone,whatsapp,status,source,next_followup_date,last_contact_date,notes)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            f.get("name"), f.get("company"), f.get("country"), f.get("city"), f.get("address"),
            f.get("email"), f.get("phone"), f.get("whatsapp"), f.get("status"), f.get("source"),
            f.get("next_followup_date"), f.get("last_contact_date"), f.get("notes")
        ))
        db.commit()
        flash_msg("Contact saved.")
        return redirect(url_for("contacts"))
    finally:
        db.close()


@app.get("/contacts/<int:contact_id>/edit")
@login_required
def contact_edit(contact_id):
    db = get_db()
    try:
        c = db.execute("SELECT * FROM contacts WHERE id=?", (contact_id,)).fetchone()
        if not c:
            abort(404)
        return page("Edit Contact", contact_form("Edit Contact", url_for("contact_edit_post", contact_id=contact_id), dict(c)))
    finally:
        db.close()


@app.post("/contacts/<int:contact_id>/edit")
@login_required
def contact_edit_post(contact_id):
    f = request.form
    db = get_db()
    try:
        db.execute("""
          UPDATE contacts SET
            name=?, company=?, country=?, city=?, address=?, email=?, phone=?, whatsapp=?,
            status=?, source=?, next_followup_date=?, last_contact_date=?, notes=?
          WHERE id=?
        """, (
            f.get("name"), f.get("company"), f.get("country"), f.get("city"), f.get("address"),
            f.get("email"), f.get("phone"), f.get("whatsapp"),
            f.get("status"), f.get("source"), f.get("next_followup_date"), f.get("last_contact_date"), f.get("notes"),
            contact_id
        ))
        db.commit()
        flash_msg("Contact updated.")
        return redirect(url_for("contacts"))
    finally:
        db.close()


@app.get("/contacts/<int:contact_id>/delete")
@login_required
def contact_delete(contact_id):
    db = get_db()
    try:
        db.execute("DELETE FROM contacts WHERE id=?", (contact_id,))
        db.commit()
        flash_msg("Contact deleted.")
        return redirect(url_for("contacts"))
    finally:
        db.close()


# ============================================================
# Products
# ============================================================

@app.get("/products")
@login_required
def products():
    q = request.args.get("q","").strip()
    db = get_db()
    try:
        if q:
            rows = db.execute("""
              SELECT * FROM products
              WHERE (full_name LIKE ? OR short_name LIKE ?)
              ORDER BY active DESC, full_name ASC
            """,(f"%{q}%", f"%{q}%")).fetchall()
        else:
            rows = db.execute("SELECT * FROM products ORDER BY active DESC, full_name ASC").fetchall()

        trs = ""
        for r in rows:
            status = "Active" if (r["active"] or 0) == 1 else "Inactive"
            trs += f"""
            <tr>
              <td><b>{html_escape(r['full_name'])}</b><div class="muted small">{html_escape(r['short_name'] or '')}</div></td>
              <td>{html_escape(r['specification'] or '')}</td>
              <td>{html_escape(r['package'] or '')}</td>
              <td>{html_escape(r['form'] or '')}</td>
              <td>{money(r['unit_price'])} {html_escape(r['currency'] or CURRENCY_DEFAULT)}</td>
              <td><span class="pill">{status}</span></td>
              <td class="right">
                <a class="btn" href="{url_for('product_edit', product_id=r['id'])}">Edit</a>
                <a class="btn danger" href="{url_for('product_delete', product_id=r['id'])}" onclick="return confirm('Delete this product?')">Delete</a>
              </td>
            </tr>
            """

        body = f"""
        <div class="card">
          <div class="row">
            <div>
              <h2>Products</h2>
              <div class="muted small">This is your product database (add / edit / delete / prices).</div>
            </div>
            <div class="actions">
              <a class="btn primary" href="{url_for('product_new')}">+ New Product</a>
            </div>
          </div>

          <div class="hr"></div>

          <form class="row" method="get" action="{url_for('products')}" style="justify-content:flex-start;">
            <div style="flex:1;min-width:240px;">
              <input name="q" placeholder="Search product name" value="{html_escape(q)}"/>
            </div>
            <button class="btn" type="submit">Search</button>
            <a class="btn" href="{url_for('products')}">Reset</a>
          </form>

          <div class="hr"></div>

          <div class="table">
            <table>
              <thead>
                <tr>
                  <th>Product</th>
                  <th>Specification</th>
                  <th>Package</th>
                  <th>Form</th>
                  <th>Price</th>
                  <th>Status</th>
                  <th class="right">Actions</th>
                </tr>
              </thead>
              <tbody>{trs or "<tr><td colspan='7' class='muted'>No products yet.</td></tr>"}</tbody>
            </table>
          </div>
        </div>
        """
        return page("Products", body)
    finally:
        db.close()


def product_form(title, action_url, p=None):
    p = p or {}
    def gv(k): return html_escape(p.get(k) or "")
    active = int(p.get("active", 1) or 1)
    cur = gv("currency") or CURRENCY_DEFAULT
    return f"""
    <div class="card">
      <div class="row">
        <h2 style="margin:0;">{html_escape(title)}</h2>
        <a class="btn" href="{url_for('products')}">Back</a>
      </div>
      <div class="hr"></div>

      <form method="post" action="{action_url}">
        <div class="grid2">
          <div class="field"><label>Full Name *</label><input name="full_name" required value="{gv('full_name')}"/></div>
          <div class="field"><label>Short Name</label><input name="short_name" value="{gv('short_name')}"/></div>
        </div>
        <div class="grid2">
          <div class="field"><label>Specification</label><input name="specification" value="{gv('specification')}"/></div>
          <div class="field"><label>Package</label><input name="package" value="{gv('package')}"/></div>
        </div>
        <div class="grid2">
          <div class="field"><label>Form</label><input name="form" value="{gv('form')}"/></div>
          <div class="field"><label>Unit Price</label><input name="unit_price" value="{gv('unit_price') or '0'}"/></div>
        </div>
        <div class="grid2">
          <div class="field"><label>Currency</label><input name="currency" value="{cur}"/></div>
          <div class="field"><label>Status</label>
            <select name="active">
              <option value="1" {"selected" if active==1 else ""}>Active</option>
              <option value="0" {"selected" if active==0 else ""}>Inactive</option>
            </select>
          </div>
        </div>
        <button class="btn primary" type="submit">Save</button>
      </form>
    </div>
    """


@app.get("/products/new")
@login_required
def product_new():
    return page("New Product", product_form("New Product", url_for("product_new_post"), {"currency":CURRENCY_DEFAULT,"active":1,"unit_price":0}))


@app.post("/products/new")
@login_required
def product_new_post():
    f = request.form
    db = get_db()
    try:
        db.execute("""
          INSERT INTO products(short_name,full_name,specification,package,form,unit_price,currency,active)
          VALUES(?,?,?,?,?,?,?,?)
        """, (
            f.get("short_name"), f.get("full_name"), f.get("specification"), f.get("package"),
            f.get("form"), float(f.get("unit_price") or 0), f.get("currency") or CURRENCY_DEFAULT, int(f.get("active") or 1)
        ))
        db.commit()
        flash_msg("Product saved.")
        return redirect(url_for("products"))
    finally:
        db.close()


@app.get("/products/<int:product_id>/edit")
@login_required
def product_edit(product_id):
    db = get_db()
    try:
        p = db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        if not p:
            abort(404)
        return page("Edit Product", product_form("Edit Product", url_for("product_edit_post", product_id=product_id), dict(p)))
    finally:
        db.close()


@app.post("/products/<int:product_id>/edit")
@login_required
def product_edit_post(product_id):
    f = request.form
    db = get_db()
    try:
        db.execute("""
          UPDATE products SET
            short_name=?, full_name=?, specification=?, package=?, form=?,
            unit_price=?, currency=?, active=?
          WHERE id=?
        """, (
            f.get("short_name"), f.get("full_name"), f.get("specification"), f.get("package"),
            f.get("form"), float(f.get("unit_price") or 0), f.get("currency") or CURRENCY_DEFAULT, int(f.get("active") or 1),
            product_id
        ))
        db.commit()
        flash_msg("Product updated.")
        return redirect(url_for("products"))
    finally:
        db.close()


@app.get("/products/<int:product_id>/delete")
@login_required
def product_delete(product_id):
    db = get_db()
    try:
        db.execute("DELETE FROM products WHERE id=?", (product_id,))
        db.commit()
        flash_msg("Product deleted.")
        return redirect(url_for("products"))
    finally:
        db.close()


# Product search API (autocomplete)
@app.get("/api/products")
@login_required
def api_products():
    q = (request.args.get("q") or "").strip()
    db = get_db()
    try:
        if not q:
            rows = db.execute("""
              SELECT id, full_name, short_name, specification, package, form, unit_price, currency
              FROM products WHERE active=1
              ORDER BY full_name ASC LIMIT 30
            """).fetchall()
        else:
            rows = db.execute("""
              SELECT id, full_name, short_name, specification, package, form, unit_price, currency
              FROM products
              WHERE active=1 AND (full_name LIKE ? OR short_name LIKE ?)
              ORDER BY full_name ASC LIMIT 30
            """, (f"%{q}%", f"%{q}%")).fetchall()

        out = []
        for r in rows:
            out.append({
                "id": r["id"],
                "label": r["full_name"],
                "short_name": r["short_name"] or "",
                "full_name": r["full_name"],
                "specification": r["specification"] or "",
                "package": r["package"] or "",
                "form": r["form"] or "",
                "unit_price": float(r["unit_price"] or 0),
                "currency": r["currency"] or CURRENCY_DEFAULT,
            })
        return jsonify(out)
    finally:
        db.close()


# ============================================================
# Invoices
# ============================================================

@app.get("/invoices")
@login_required
def invoices():
    db = get_db()
    try:
        rows = db.execute("""
          SELECT i.*, c.name AS contact_name, c.company AS contact_company, c.country AS contact_country
          FROM invoices i
          JOIN contacts c ON c.id=i.contact_id
          ORDER BY i.created_at DESC
        """).fetchall()

        trs = ""
        for r in rows:
            trs += f"""
            <tr>
              <td><b>{html_escape(r['invoice_no'] or '')}</b><div class="muted small">{html_escape(r['issue_date'] or '')}</div></td>
              <td>{html_escape(r['contact_name'])}<div class="muted small">{html_escape(r['contact_company'] or '')}</div></td>
              <td>{html_escape(r['contact_country'] or '')}</td>
              <td>{money(r['total_amount'])} {html_escape(r['currency'] or CURRENCY_DEFAULT)}</td>
              <td class="right">
                <a class="btn" href="{url_for('invoice_view', invoice_id=r['id'])}">Open</a>
                <a class="btn danger" href="{url_for('invoice_delete', invoice_id=r['id'])}" onclick="return confirm('Delete this invoice?')">Delete</a>
              </td>
            </tr>
            """

        body = f"""
        <div class="card">
          <div class="row">
            <div>
              <h2>Invoices</h2>
              <div class="muted small">Create invoice with products + Bill To / Ship To.</div>
            </div>
            <div class="actions">
              <a class="btn primary" href="{url_for('invoice_new')}">+ New Invoice</a>
            </div>
          </div>

          <div class="hr"></div>

          <div class="table">
            <table>
              <thead>
                <tr>
                  <th>Invoice</th>
                  <th>Contact</th>
                  <th>Country</th>
                  <th>Total</th>
                  <th class="right">Actions</th>
                </tr>
              </thead>
              <tbody>{trs or "<tr><td colspan='5' class='muted'>No invoices yet.</td></tr>"}</tbody>
            </table>
          </div>
        </div>
        """
        return page("Invoices", body)
    finally:
        db.close()


@app.get("/invoices/new")
@login_required
def invoice_new():
    db = get_db()
    try:
        contacts = db.execute("SELECT id, name, company, address, city, country, phone, whatsapp, email FROM contacts ORDER BY name").fetchall()
    finally:
        db.close()

    # Invoice creation form (Bill To / Ship To side by side + autofill)
    body = f"""
    <div class="card">
      <div class="row">
        <h2 style="margin:0;">New Invoice</h2>
        <a class="btn" href="{url_for('invoices')}">Back</a>
      </div>

      <div class="hr"></div>

      <form method="post" action="{url_for('invoice_new_post')}" id="invForm">

        <div class="grid2">
          <div class="field">
            <label>Contact *</label>
            <select name="contact_id" id="contactSelect" required>
              <option value="">-- select --</option>
              {''.join([f"<option value='{c['id']}' data-name='{html_escape(c['name'])}' data-company='{html_escape(c['company'] or '')}' data-address='{html_escape(c['address'] or '')}' data-city='{html_escape(c['city'] or '')}' data-country='{html_escape(c['country'] or '')}' data-phone='{html_escape(c['phone'] or '')}' data-whatsapp='{html_escape(c['whatsapp'] or '')}' data-email='{html_escape(c['email'] or '')}'>{html_escape(c['name'])}</option>" for c in contacts])}
            </select>
            <div class="muted small">Bill To will autofill from selected contact. You can edit any field.</div>
          </div>

          <div class="field">
            <label>Invoice No.</label>
            <input name="invoice_no" value="HOTGEN-{datetime.now().strftime('%Y%m%d')}-ZAK-001"/>
          </div>
        </div>

        <div class="grid2">
          <div class="field"><label>Issue Date</label><input name="issue_date" value="{now_date_str()}"/></div>
          <div class="field"><label>Currency</label><input name="currency" value="{html_escape(CURRENCY_DEFAULT)}"/></div>
        </div>

        <div class="grid2">
          <div class="field"><label>Required Delivery Date</label><input name="required_delivery_date" placeholder="YYYY-MM-DD"/></div>
          <div class="field"><label>Shipping Date</label><input name="shipping_date" placeholder="YYYY-MM-DD"/></div>
        </div>

        <div class="grid2">
          <div class="field"><label>Delivery Mode</label><input name="delivery_mode" value="by Air"/></div>
          <div class="field"><label>Trade Terms</label><input name="trade_terms" value="FOB"/></div>
        </div>

        <div class="grid2">
          <div class="field"><label>Payment Terms</label><input name="payment_terms" value="100% before shipping"/></div>
          <div class="field"><label>Internal Shipping Fee</label><input name="internal_shipping_fee" value="0"/></div>
        </div>

        <div class="field">
          <label>Previous Balance Note (optional)</label>
          <input name="previous_balance_note" placeholder="e.g. Remaining payment from last order..."/>
        </div>

        <div class="hr"></div>

        <div class="grid2">
          <div>
            <div class="row" style="justify-content:space-between;">
              <h3 style="margin:0;">Bill To</h3>
              <span class="pill">Auto from contact</span>
            </div>
            <div class="field"><label>Name</label><input name="bill_name" id="bill_name"/></div>
            <div class="field"><label>Company</label><input name="bill_company" id="bill_company"/></div>
            <div class="field"><label>Address</label><input name="bill_address" id="bill_address"/></div>
            <div class="grid2">
              <div class="field"><label>City</label><input name="bill_city" id="bill_city"/></div>
              <div class="field"><label>Country</label><input name="bill_country" id="bill_country"/></div>
            </div>
            <div class="grid2">
              <div class="field"><label>Phone</label><input name="bill_phone" id="bill_phone"/></div>
              <div class="field"><label>Email</label><input name="bill_email" id="bill_email"/></div>
            </div>
          </div>

          <div>
            <div class="row" style="justify-content:space-between;">
              <h3 style="margin:0;">Ship To</h3>
              <label style="display:flex;align-items:center;gap:8px;margin:0;">
                <input type="checkbox" id="shipSame" checked />
                <span class="small">Same as Bill To</span>
              </label>
            </div>
            <div class="muted small" style="margin:6px 0 10px 0;">
              You can uncheck and enter shipping company details manually (changes every time).
            </div>

            <div class="field"><label>Name</label><input name="ship_name" id="ship_name"/></div>
            <div class="field"><label>Company</label><input name="ship_company" id="ship_company"/></div>
            <div class="field"><label>Address</label><input name="ship_address" id="ship_address"/></div>
            <div class="grid2">
              <div class="field"><label>City</label><input name="ship_city" id="ship_city"/></div>
              <div class="field"><label>Country</label><input name="ship_country" id="ship_country"/></div>
            </div>
            <div class="grid2">
              <div class="field"><label>Phone</label><input name="ship_phone" id="ship_phone"/></div>
              <div class="field"><label>Email</label><input name="ship_email" id="ship_email"/></div>
            </div>
          </div>
        </div>

        <div class="hr"></div>

        <h3>Items</h3>
        <div class="muted small">Type product name; system will search products database and autofill spec/package/form/price.</div>

        <div id="itemsWrap"></div>
        <div class="row" style="justify-content:flex-start;">
          <button type="button" class="btn" onclick="addLine()">+ Add line</button>
        </div>

        <div class="hr"></div>

        <div class="row">
          <div></div>
          <div style="text-align:right;">
            <div style="font-size:26px;font-weight:950;"><span id="totalBox">0.00</span> {html_escape(CURRENCY_DEFAULT)}</div>
          </div>
        </div>

        <button class="btn primary" type="submit">Save Invoice</button>
      </form>
    </div>

    <script>
      let lineNo = 0;

      function num(v) {{
        const x = parseFloat(v);
        return isNaN(x) ? 0 : x;
      }}

      function money2(x) {{
        return (Math.round(x*100)/100).toFixed(2);
      }}

      function calcTotal() {{
        let total = 0;
        document.querySelectorAll(".lineRow").forEach(row => {{
          const qty = num(row.querySelector("[name='qty']").value);
          const up = num(row.querySelector("[name='unit_price']").value);
          const amt = qty * up;
          row.querySelector(".amountCell").innerText = money2(amt);
          row.querySelector("[name='amount']").value = amt;
          total += amt;
        }});
        const shipFee = num(document.querySelector("[name='internal_shipping_fee']").value);
        total += shipFee;
        document.getElementById("totalBox").innerText = money2(total);
      }}

      async function searchProducts(q) {{
        const r = await fetch(`/api/products?q=${{encodeURIComponent(q)}}`);
        return await r.json();
      }}

      function makeLine() {{
        lineNo += 1;
        const id = "line_" + lineNo;
        const html = `
          <div class="table" style="margin-top:10px;">
            <table>
              <thead>
                <tr>
                  <th style="width:6%;">Line</th>
                  <th style="width:24%;">Description</th>
                  <th style="width:16%;">Specification</th>
                  <th style="width:12%;">Package</th>
                  <th style="width:10%;">Form</th>
                  <th style="width:8%;">Qty</th>
                  <th style="width:10%;">Unit Price</th>
                  <th style="width:10%;">Amount</th>
                  <th style="width:4%;"></th>
                </tr>
              </thead>
              <tbody>
                <tr class="lineRow" data-line="${{lineNo}}">
                  <td>${{lineNo}}<input type="hidden" name="line_no" value="${{lineNo}}"/></td>
                  <td>
                    <input name="description" placeholder="Product name" oninput="onDescType(this)" />
                    <input type="hidden" name="product_id" value=""/>
                  </td>
                  <td><input name="specification" placeholder="Spec"/></td>
                  <td><input name="package" placeholder="Package"/></td>
                  <td><input name="form" placeholder="Form"/></td>
                  <td><input name="qty" value="1" type="number" step="0.01" oninput="calcTotal()"/></td>
                  <td><input name="unit_price" value="0" type="number" step="0.01" oninput="calcTotal()"/></td>
                  <td class="amountCell">0.00<input type="hidden" name="amount" value="0"/></td>
                  <td><button type="button" class="btn danger" onclick="removeLine(this)">x</button></td>
                </tr>
              </tbody>
            </table>
          </div>
        `;
        return html;
      }}

      function addLine() {{
        document.getElementById("itemsWrap").insertAdjacentHTML("beforeend", makeLine());
        calcTotal();
      }}

      function removeLine(btn) {{
        const wrap = btn.closest(".table");
        wrap.remove();
        calcTotal();
      }}

      let typingTimer = null;
      async function onDescType(inp) {{
        const q = inp.value.trim();
        if (!q) return;
        clearTimeout(typingTimer);
        typingTimer = setTimeout(async () => {{
          const res = await searchProducts(q);
          if (!res || res.length === 0) return;

          // take best match (first)
          const best = res[0];
          const row = inp.closest(".lineRow");
          row.querySelector("[name='product_id']").value = best.id;
          row.querySelector("[name='description']").value = best.full_name;
          row.querySelector("[name='specification']").value = best.specification || "";
          row.querySelector("[name='package']").value = best.package || "";
          row.querySelector("[name='form']").value = best.form || "";
          row.querySelector("[name='unit_price']").value = best.unit_price || 0;
          calcTotal();
        }}, 250);
      }}

      // Auto fill Bill To from selected contact
      function setBillFromContact(opt) {{
        const name = opt.dataset.name || "";
        const company = opt.dataset.company || "";
        const address = opt.dataset.address || "";
        const city = opt.dataset.city || "";
        const country = opt.dataset.country || "";
        const phone = ((opt.dataset.phone || "") + " " + (opt.dataset.whatsapp || "")).trim();
        const email = opt.dataset.email || "";

        document.getElementById("bill_name").value = name;
        document.getElementById("bill_company").value = company;
        document.getElementById("bill_address").value = address;
        document.getElementById("bill_city").value = city;
        document.getElementById("bill_country").value = country;
        document.getElementById("bill_phone").value = phone;
        document.getElementById("bill_email").value = email;

        if (document.getElementById("shipSame").checked) {{
          copyBillToShip();
        }}
      }}

      function copyBillToShip() {{
        document.getElementById("ship_name").value = document.getElementById("bill_name").value;
        document.getElementById("ship_company").value = document.getElementById("bill_company").value;
        document.getElementById("ship_address").value = document.getElementById("bill_address").value;
        document.getElementById("ship_city").value = document.getElementById("bill_city").value;
        document.getElementById("ship_country").value = document.getElementById("bill_country").value;
        document.getElementById("ship_phone").value = document.getElementById("bill_phone").value;
        document.getElementById("ship_email").value = document.getElementById("bill_email").value;
      }}

      document.getElementById("contactSelect").addEventListener("change", (e) => {{
        const opt = e.target.selectedOptions[0];
        if (opt && opt.value) setBillFromContact(opt);
      }});

      document.getElementById("shipSame").addEventListener("change", (e) => {{
        if (e.target.checked) {{
          copyBillToShip();
        }}
      }});

      // keep total updated if shipping fee changes
      document.querySelector("[name='internal_shipping_fee']").addEventListener("input", calcTotal);

      // start with 2 lines
      addLine(); addLine();
    </script>
    """
    return page("New Invoice", body)


@app.post("/invoices/new")
@login_required
def invoice_new_post():
    f = request.form
    db = get_db()
    try:
        # Basic invoice insert
        cur = f.get("currency") or CURRENCY_DEFAULT

        # Create invoice
        db.execute("""
          INSERT INTO invoices(
            contact_id, invoice_no, issue_date, required_delivery_date,
            delivery_mode, trade_terms, payment_terms, shipping_date,
            currency, total_amount, internal_shipping_fee, previous_balance_note,
            bill_name, bill_company, bill_address, bill_city, bill_country, bill_phone, bill_email,
            ship_name, ship_company, ship_address, ship_city, ship_country, ship_phone, ship_email,
            updated_at
          ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
        """, (
            int(f.get("contact_id")),
            f.get("invoice_no"),
            f.get("issue_date"),
            f.get("required_delivery_date"),
            f.get("delivery_mode"),
            f.get("trade_terms"),
            f.get("payment_terms"),
            f.get("shipping_date"),
            cur,
            0,
            float(f.get("internal_shipping_fee") or 0),
            f.get("previous_balance_note"),

            f.get("bill_name"),
            f.get("bill_company"),
            f.get("bill_address"),
            f.get("bill_city"),
            f.get("bill_country"),
            f.get("bill_phone"),
            f.get("bill_email"),

            f.get("ship_name"),
            f.get("ship_company"),
            f.get("ship_address"),
            f.get("ship_city"),
            f.get("ship_country"),
            f.get("ship_phone"),
            f.get("ship_email"),
        ))
        invoice_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

        # Items: multiple rows in form (we used repeating names, so use getlist)
        line_nos = request.form.getlist("line_no")
        descs = request.form.getlist("description")
        specs = request.form.getlist("specification")
        packs = request.form.getlist("package")
        forms = request.form.getlist("form")
        qtys = request.form.getlist("qty")
        ups = request.form.getlist("unit_price")
        pids = request.form.getlist("product_id")

        total = 0.0
        for i in range(len(line_nos)):
            ln = int(float(line_nos[i] or (i+1)))
            desc = (descs[i] or "").strip()
            if not desc:
                continue
            spec = specs[i] if i < len(specs) else ""
            pack = packs[i] if i < len(packs) else ""
            frm = forms[i] if i < len(forms) else ""
            qty = float(qtys[i] or 0)
            up = float(ups[i] or 0)
            amt = qty * up
            total += amt

            pid = pids[i] if i < len(pids) else ""
            pid_val = int(pid) if pid and pid.isdigit() else None

            db.execute("""
              INSERT INTO invoice_items(invoice_id,line_no,product_id,description,specification,package,form,quantity,unit_price,amount)
              VALUES(?,?,?,?,?,?,?,?,?,?)
            """, (invoice_id, ln, pid_val, desc, spec, pack, frm, qty, up, amt))

        # add shipping fee
        ship_fee = float(f.get("internal_shipping_fee") or 0)
        total_all = total + ship_fee

        db.execute("UPDATE invoices SET total_amount=?, updated_at=datetime('now') WHERE id=?",
                   (total_all, invoice_id))

        db.commit()
        flash_msg("Invoice created.")
        return redirect(url_for("invoice_view", invoice_id=invoice_id))
    except Exception as e:
        db.rollback()
        # show real error in Render logs
        print("Invoice create error:", e)
        flash_msg(f"Invoice error: {e}")
        return redirect(url_for("invoices"))
    finally:
        db.close()


@app.get("/invoices/<int:invoice_id>")
@login_required
def invoice_view(invoice_id):
    db = get_db()
    try:
        inv = db.execute("""
          SELECT i.*, c.name AS c_name, c.company AS c_company, c.address AS c_address, c.city AS c_city, c.country AS c_country,
                 c.phone AS c_phone, c.whatsapp AS c_whatsapp, c.email AS c_email
          FROM invoices i JOIN contacts c ON c.id=i.contact_id
          WHERE i.id=?
        """, (invoice_id,)).fetchone()

        if not inv:
            abort(404)

        items = db.execute("SELECT * FROM invoice_items WHERE invoice_id=? ORDER BY line_no", (invoice_id,)).fetchall()

        def rget(row, key, default=""):
            try:
                v = row[key]
                return default if v is None else v
            except Exception:
                return default

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

        rows_html = ""
        for it in items:
            rows_html += f"""
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

        inv_currency = rget(inv, "currency") or CURRENCY_DEFAULT
        internal_fee = float(rget(inv, "internal_shipping_fee") or 0)
        prev_note = html_escape(rget(inv, "previous_balance_note") or "")

        logo_url = url_for("static", filename=LOGO_STATIC_FILENAME)

        body = f"""
        <div class="row no-print">
          <h2 style="margin:0;">Invoice</h2>
          <div class="actions">
            <button class="btn primary" onclick="window.print()">Print / Save PDF</button>
            <a class="btn" href="{url_for('invoices')}">Back</a>
          </div>
        </div>

        <div class="print-note">
          If Chrome prints time/date + URL, disable <b>Headers and footers</b> in Print settings.
        </div>

        <div class="card">
          <div class="row" style="align-items:flex-start;">
            <div>
              <img src="{logo_url}" style="max-height:120px;margin-bottom:8px;" alt="Logo">
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

          <div class="hr"></div>

          <div class="grid2" style="gap:24px;align-items:start;">
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
            <div><b>Currency:</b> {html_escape(inv_currency)}</div>
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
                  <th style="width:10%;">Unit Price</th>
                  <th style="width:10%;">Amount</th>
                </tr>
              </thead>
              <tbody>
                {rows_html or "<tr><td colspan='8' class='muted'>No items</td></tr>"}
              </tbody>
            </table>
          </div>

          <div style="text-align:right;margin-top:10px;">
            {f"<div>{prev_note}</div>" if prev_note else ""}
            {f"<div><b>Internal shipping fee:</b> {money(internal_fee)}</div>" if internal_fee != 0 else ""}
            <div style="font-size:18px;"><b>Total Payment:</b> {money(rget(inv,'total_amount'))} {html_escape(inv_currency)}</div>
          </div>

          <div style="margin-top:14px;">
            <h3>BANK INFORMATIONS FOR T/T PAYMENT:</h3>
            <pre style="white-space:pre-wrap;background:#fafafa;border:1px solid #eee;padding:12px;border-radius:14px;">{html_escape(BANK_INFO)}</pre>
          </div>
        </div>
        """
        return page("Invoice", body)
    finally:
        db.close()


@app.get("/invoices/<int:invoice_id>/delete")
@login_required
def invoice_delete(invoice_id):
    db = get_db()
    try:
        db.execute("DELETE FROM invoices WHERE id=?", (invoice_id,))
        db.commit()
        flash_msg("Invoice deleted.")
        return redirect(url_for("invoices"))
    finally:
        db.close()


# ============================================================
# Health
# ============================================================

@app.get("/health")
def health():
    return {"ok": True, "db": DB_PATH}


# ============================================================
# Run locally
# ============================================================

if __name__ == "__main__":
    # local dev
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)
