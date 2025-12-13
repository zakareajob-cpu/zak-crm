import os
import sqlite3
from functools import wraps
from datetime import datetime
from flask import Flask, g, render_template, request, redirect, url_for, session, flash, jsonify

APP_NAME = "ZAK CRM"
DB_PATH = os.path.join(os.path.dirname(__file__), "zakcrm.db")

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "zakarea.job@hotmail.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "ZAKCRM2026")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me")

COMPANY_NAME = os.getenv("COMPANY_NAME", "Hotgen")
COMPANY_EMAIL = os.getenv("COMPANY_EMAIL", "zakarea@hotgen.com.cn")
COMPANY_ADDRESS = os.getenv("COMPANY_ADDRESS", "No. 55 Qingfeng West Road, Daxing District, 102629, Beijing, China")
BANK_INFO = os.getenv("BANK_INFO", """Beneficiary: Beijing Hotgen Biotech Co.,Ltd
SWIFT: CMBCCNBS
Bank Name: China Merchants Bank H.O. ShenZhen
Bank Address: China Merchants Bank Tower NO.7088, Shennan Boulevard, Shenzhen, China.
A/C: USD: 110909296432802  EURO: 110909296435702""")

INVOICE_PREFIX = os.getenv("INVOICE_PREFIX", "HOTGEN")
INVOICE_SUFFIX = os.getenv("INVOICE_SUFFIX", "ZAK")

app = Flask(__name__)
app.secret_key = SECRET_KEY

def db():
    conn = getattr(g, "_db", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        g._db = conn
    return conn

@app.teardown_appcontext
def close_db(exc):
    conn = getattr(g, "_db", None)
    if conn:
        conn.close()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS contacts(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      company TEXT, country TEXT, city TEXT, address TEXT,
      email TEXT, phone TEXT, whatsapp TEXT,
      status TEXT DEFAULT 'Prospect',
      source TEXT, next_followup_date TEXT, last_contact_date TEXT, notes TEXT,
      created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS products(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      abbreviation TEXT, full_name TEXT, specification TEXT, package TEXT,
      default_price REAL DEFAULT 0, currency TEXT DEFAULT 'USD'
    );
    CREATE TABLE IF NOT EXISTS customer_prices(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      contact_id INTEGER NOT NULL,
      product_id INTEGER NOT NULL,
      special_price REAL NOT NULL,
      currency TEXT DEFAULT 'USD',
      UNIQUE(contact_id, product_id),
      FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE CASCADE,
      FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS invoices(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      invoice_no TEXT UNIQUE NOT NULL,
      contact_id INTEGER NOT NULL,
      issue_date TEXT NOT NULL,
      required_delivery_date TEXT,
      delivery_mode TEXT, trade_terms TEXT,
      payment_terms TEXT, shipping_date TEXT,
      internal_shipping_fee REAL DEFAULT 0,
      previous_balance_note TEXT,
      currency TEXT DEFAULT 'USD',
      total_amount REAL DEFAULT 0,
      notes TEXT,
      created_at TEXT DEFAULT (datetime('now')),
      FOREIGN KEY(contact_id) REFERENCES contacts(id)
    );
    CREATE TABLE IF NOT EXISTS invoice_items(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      invoice_id INTEGER NOT NULL,
      line_no INTEGER NOT NULL,
      product_id INTEGER,
      product_abbreviation TEXT,
      description TEXT,
      specification TEXT,
      package TEXT,
      form TEXT,
      quantity REAL NOT NULL,
      unit_price REAL NOT NULL,
      amount REAL NOT NULL,
      FOREIGN KEY(invoice_id) REFERENCES invoices(id) ON DELETE CASCADE,
      FOREIGN KEY(product_id) REFERENCES products(id)
    );
    CREATE INDEX IF NOT EXISTS idx_contacts_country ON contacts(country);
    CREATE INDEX IF NOT EXISTS idx_invoices_issue_date ON invoices(issue_date);
    """)
    conn.commit()
    conn.close()

def login_required(fn):
    @wraps(fn)
    def w(*a, **k):
        if session.get("logged_in") is not True:
            return redirect(url_for("login"))
        return fn(*a, **k)
    return w

def generate_invoice_no():
    today = datetime.now().strftime("%Y%m%d")
    row = db().execute(
        "SELECT invoice_no FROM invoices WHERE invoice_no LIKE ? ORDER BY invoice_no DESC LIMIT 1",
        (f"{INVOICE_PREFIX}-{today}-{INVOICE_SUFFIX}-%",)
    ).fetchone()
    last = 0
    if row:
        try:
            last = int(row["invoice_no"].split("-")[-1])
        except:
            last = 0
    return f"{INVOICE_PREFIX}-{today}-{INVOICE_SUFFIX}-{last+1:03d}"

@app.context_processor
def inject():
    return dict(APP_NAME=APP_NAME, COMPANY_NAME=COMPANY_NAME, COMPANY_EMAIL=COMPANY_EMAIL,
                COMPANY_ADDRESS=COMPANY_ADDRESS, BANK_INFO=BANK_INFO)

@app.get("/health")
def health():
    return "ok"

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        password = (request.form.get("password") or "").strip()
        if email == ADMIN_EMAIL and password == ADMIN_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        flash("Invalid credentials", "error")
    return render_template("login.html")

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.get("/")
@login_required
def dashboard():
    conn = db()
    total_contacts = conn.execute("SELECT COUNT(*) c FROM contacts").fetchone()["c"]
    prospects = conn.execute("SELECT COUNT(*) c FROM contacts WHERE status='Prospect'").fetchone()["c"]
    total_invoices = conn.execute("SELECT COUNT(*) c FROM invoices").fetchone()["c"]
    year = datetime.now().strftime("%Y")
    ytd_sales = conn.execute("SELECT COALESCE(SUM(total_amount),0) s FROM invoices WHERE substr(issue_date,1,4)=?", (year,)).fetchone()["s"]
    top_countries = conn.execute("""
        SELECT c.country country, COALESCE(SUM(i.total_amount),0) total
        FROM invoices i JOIN contacts c ON c.id=i.contact_id
        GROUP BY c.country ORDER BY total DESC LIMIT 8
    """).fetchall()
    return render_template("dashboard.html", total_contacts=total_contacts, prospects=prospects,
                           total_invoices=total_invoices, year=year, ytd_sales=ytd_sales, top_countries=top_countries)

@app.get("/contacts")
@login_required
def contacts():
    q = (request.args.get("q") or "").strip()
    conn = db()
    if q:
        like = f"%{q}%"
        rows = conn.execute("""SELECT * FROM contacts
            WHERE name LIKE ? OR company LIKE ? OR email LIKE ? OR phone LIKE ? OR whatsapp LIKE ?
            ORDER BY created_at DESC LIMIT 500""", (like, like, like, like, like)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM contacts ORDER BY created_at DESC LIMIT 500").fetchall()
    return render_template("contacts.html", rows=rows, q=q)

@app.route("/contacts/new", methods=["GET","POST"])
@login_required
def contact_new():
    if request.method == "POST":
        f = request.form
        db().execute("""INSERT INTO contacts(name, company, country, city, address, email, phone, whatsapp, status, source, notes)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                     ((f.get("name") or "").strip(),
                      (f.get("company") or "").strip(),
                      (f.get("country") or "").strip(),
                      (f.get("city") or "").strip(),
                      (f.get("address") or "").strip(),
                      (f.get("email") or "").strip(),
                      (f.get("phone") or "").strip(),
                      (f.get("whatsapp") or "").strip(),
                      (f.get("status") or "Prospect").strip(),
                      (f.get("source") or "").strip(),
                      (f.get("notes") or "").strip()))
        db().commit()
        return redirect(url_for("contacts"))
    return render_template("contact_form.html", mode="new")

@app.route("/invoices")
@login_required
def invoices():
    conn = db()
    rows = conn.execute("""
        SELECT i.id, i.invoice_no, i.issue_date, i.total_amount, c.name contact_name, c.country contact_country
        FROM invoices i JOIN contacts c ON c.id=i.contact_id
        ORDER BY i.issue_date DESC, i.id DESC LIMIT 500
    """).fetchall()
    return render_template("invoices.html", rows=rows)

@app.route("/invoices/new", methods=["GET","POST"])
@login_required
def invoice_new():
    conn = db()
    contacts = conn.execute("SELECT id, name, company FROM contacts ORDER BY created_at DESC LIMIT 2000").fetchall()
    if request.method == "POST":
        f = request.form
        contact_id = int(f.get("contact_id"))
        invoice_no = generate_invoice_no()
        issue_date = (f.get("issue_date") or datetime.now().strftime("%Y-%m-%d")).strip()

        cur = conn.execute("""INSERT INTO invoices(invoice_no, contact_id, issue_date, payment_terms, trade_terms, delivery_mode, shipping_date, internal_shipping_fee, previous_balance_note, notes)
                              VALUES(?,?,?,?,?,?,?,?,?,?)""",
                           (invoice_no, contact_id, issue_date,
                            (f.get("payment_terms") or "100% before shipping").strip(),
                            (f.get("trade_terms") or "").strip(),
                            (f.get("delivery_mode") or "").strip(),
                            (f.get("shipping_date") or "").strip(),
                            float(f.get("internal_shipping_fee") or 0),
                            (f.get("previous_balance_note") or "").strip(),
                            (f.get("notes") or "").strip()))
        invoice_id = cur.lastrowid

        product_ids = request.form.getlist("product_id[]")
        abbreviations = request.form.getlist("product_abbreviation[]")
        descriptions = request.form.getlist("description[]")
        specifications = request.form.getlist("specification[]")
        packages = request.form.getlist("package[]")
        forms = request.form.getlist("form[]")
        quantities = request.form.getlist("quantity[]")
        unit_prices = request.form.getlist("unit_price[]")

        total = 0.0
        line_no = 1
        for i in range(len(quantities)):
            if not (quantities[i] or "").strip():
                continue
            qty = float(quantities[i] or 0)
            up = float(unit_prices[i] or 0)
            amt = qty * up
            total += amt
            pid = (product_ids[i] or "").strip()
            pid_val = int(pid) if pid.isdigit() else None
            conn.execute("""INSERT INTO invoice_items(invoice_id, line_no, product_id, product_abbreviation, description, specification, package, form, quantity, unit_price, amount)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                         (invoice_id, line_no, pid_val, (abbreviations[i] or "").strip(), (descriptions[i] or "").strip(),
                          (specifications[i] or "").strip(), (packages[i] or "").strip(), (forms[i] or "").strip(),
                          qty, up, amt))
            line_no += 1

        fee = float(f.get("internal_shipping_fee") or 0)
        total += fee
        conn.execute("UPDATE invoices SET total_amount=? WHERE id=?", (total, invoice_id))
        conn.commit()
        return redirect(url_for("invoice_view", invoice_id=invoice_id))

    return render_template("invoice_form.html", contacts=contacts, today=datetime.now().strftime("%Y-%m-%d"))

@app.get("/invoices/<int:invoice_id>")
@login_required
def invoice_view(invoice_id):
    conn = db()
    inv = conn.execute("""SELECT i.*, c.* FROM invoices i JOIN contacts c ON c.id=i.contact_id WHERE i.id=?""", (invoice_id,)).fetchone()
    items = conn.execute("SELECT * FROM invoice_items WHERE invoice_id=? ORDER BY line_no", (invoice_id,)).fetchall()
    return render_template("invoice_view.html", inv=inv, items=items)

@app.get("/api/products")
@login_required
def api_products():
    q = (request.args.get("q") or "").strip()
    conn = db()
    if not q:
        rows = conn.execute("SELECT id, abbreviation, full_name, specification, package, default_price FROM products LIMIT 20").fetchall()
    else:
        like = f"%{q}%"
        rows = conn.execute("""SELECT id, abbreviation, full_name, specification, package, default_price
                               FROM products WHERE abbreviation LIKE ? OR full_name LIKE ? LIMIT 30""",
                            (like, like)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.get("/api/price")
@login_required
def api_price():
    try:
        contact_id = int(request.args.get("contact_id") or 0)
        product_id = int(request.args.get("product_id") or 0)
    except:
        return jsonify({"ok": False})
    if not contact_id or not product_id:
        return jsonify({"ok": False})
    r = db().execute("SELECT special_price FROM customer_prices WHERE contact_id=? AND product_id=?", (contact_id, product_id)).fetchone()
    if r:
        return jsonify({"ok": True, "unit_price": float(r["special_price"])})
    r2 = db().execute("SELECT default_price FROM products WHERE id=?", (product_id,)).fetchone()
    return jsonify({"ok": True, "unit_price": float(r2["default_price"] or 0)})

if __name__ == "__main__":
    init_db()
    port = int(os.getenv("PORT","5000"))
    app.run(host="0.0.0.0", port=port)
