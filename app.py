import os, sqlite3, uuid
from flask import Flask, g, render_template_string, request, redirect, url_for, session, flash
from datetime import datetime

# ============================================
# CONFIGURATION
# ============================================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "supersecret")

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "zakcrm.db")

COMPANY_NAME = "Hotgen Biotech Co., Ltd."
COMPANY_ADDRESS = "No. 55 Qingfeng West Road, Daxing District, Beijing, China"
COMPANY_EMAIL = "zakarea@hotgen.com.cn"
COMPANY_PHONE = ""
CURRENCY = "USD"

LOGO_URL = "/static/logo.png"
BANK_INFO = """Beneficiary: Beijing Hotgen Biotech Co.,Ltd
SWIFT: CMBCNBS
Bank Name: China Merchants Bank H.O. ShenZhen
Bank Address: China Merchants Bank Tower No.7088, Shennan Boulevard, Shenzhen, China.
A/C: USD: 110809296432802  EURO: 11080929645702"""

# ============================================
# DATABASE SETUP
# ============================================
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()
    db.executescript("""
    PRAGMA foreign_keys = ON;

    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT
    );

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

    CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contact_id INTEGER,
        invoice_no TEXT,
        issue_date TEXT,
        required_delivery_date TEXT,
        delivery_mode TEXT,
        trade_terms TEXT,
        payment_terms TEXT,
        shipping_date TEXT,
        currency TEXT,
        total_amount REAL,
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
        updated_at TEXT
    );

    CREATE TABLE IF NOT EXISTS invoice_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id INTEGER,
        line_no INTEGER,
        description TEXT,
        specification TEXT,
        package TEXT,
        form TEXT,
        quantity REAL,
        unit_price REAL,
        amount REAL
    );
    """)
    db.commit()

with app.app_context():
    init_db()

# ============================================
# HELPERS
# ============================================
def html_escape(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def money(v):
    try:
        return f"{float(v):,.2f}"
    except:
        return "0.00"

def login_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*a, **kw):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*a, **kw)
    return wrapper

# ============================================
# AUTHENTICATION
# ============================================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form["username"] == "admin" and request.form["password"] == "123":
            session["user"] = "admin"
            return redirect(url_for("dashboard"))
        flash("Invalid credentials.")
    return render_template_string("""
    <html><body style="font-family:Arial;margin:40px">
      <h2>Login</h2>
      <form method="POST">
        <input name="username" placeholder="Username"><br><br>
        <input type="password" name="password" placeholder="Password"><br><br>
        <button>Login</button>
      </form>
    </body></html>""")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ============================================
# DASHBOARD
# ============================================
@app.route("/")
@login_required
def dashboard():
    db = get_db()
    contacts = db.execute("SELECT COUNT(*) c FROM contacts").fetchone()["c"]
    invoices = db.execute("SELECT COUNT(*) c FROM invoices").fetchone()["c"]
    return render_template_string("""
    <html><body style="font-family:Arial;margin:40px">
      <h2>ZAK CRM Dashboard</h2>
      <p>Contacts: {{c}}</p>
      <p>Invoices: {{i}}</p>
      <a href="/contacts">Contacts</a> | 
      <a href="/invoices">Invoices</a> |
      <a href="/logout">Logout</a>
    </body></html>""", c=contacts, i=invoices)

# ============================================
# CONTACTS
# ============================================
@app.route("/contacts", methods=["GET", "POST"])
@login_required
def contacts():
    db = get_db()
    if request.method == "POST":
        db.execute("INSERT INTO contacts (name, company, email, phone, whatsapp, notes) VALUES (?,?,?,?,?,?)",
                   (request.form["name"], request.form["company"], request.form["email"], request.form["phone"], request.form["whatsapp"], request.form["notes"]))
        db.commit()
        return redirect(url_for("contacts"))

    rows = db.execute("SELECT * FROM contacts ORDER BY id DESC").fetchall()
    return render_template_string("""
    <html><body style="font-family:Arial;margin:40px">
      <h2>Contacts</h2>
      <form method="POST">
        <input name="name" placeholder="Name" required>
        <input name="company" placeholder="Company">
        <input name="email" placeholder="Email">
        <input name="phone" placeholder="Phone">
        <input name="whatsapp" placeholder="WhatsApp">
        <input name="notes" placeholder="Notes">
        <button>Add</button>
      </form><br>
      <table border="1" cellspacing="0" cellpadding="6">
        <tr><th>Name</th><th>Company</th><th>Email</th><th>Phone</th></tr>
        {% for r in rows %}
        <tr><td>{{r['name']}}</td><td>{{r['company']}}</td><td>{{r['email']}}</td><td>{{r['phone']}}</td></tr>
        {% endfor %}
      </table><br>
      <a href="/">Home</a>
    </body></html>""", rows=rows)

# ============================================
# INVOICES
# ============================================
@app.route("/invoices", methods=["GET", "POST"])
@login_required
def invoices():
    db = get_db()
    rows = db.execute("""
        SELECT i.id, i.invoice_no, i.issue_date, c.name AS contact_name, i.total_amount
        FROM invoices i LEFT JOIN contacts c ON c.id=i.contact_id
        ORDER BY i.id DESC
    """).fetchall()
    return render_template_string("""
    <html><body style="font-family:Arial;margin:40px">
      <h2>Invoices</h2>
      <a href="/invoices/new">+ New Invoice</a><br><br>
      <table border="1" cellspacing="0" cellpadding="6">
        <tr><th>No</th><th>Contact</th><th>Date</th><th>Total</th><th>Action</th></tr>
        {% for i in rows %}
          <tr>
            <td>{{i['invoice_no']}}</td>
            <td>{{i['contact_name']}}</td>
            <td>{{i['issue_date']}}</td>
            <td>{{i['total_amount']}}</td>
            <td><a href="/invoices/{{i['id']}}">View</a></td>
          </tr>
        {% endfor %}
      </table>
      <br><a href="/">Home</a>
    </body></html>""", rows=rows)

# ============================================
# NEW INVOICE (updated)
# ============================================
@app.route("/invoices/new", methods=["GET", "POST"])
@login_required
def invoice_new():
    db = get_db()
    if request.method == "POST":
        f = request.form
        try:
            db.execute("""
                INSERT INTO invoices (
                    contact_id, invoice_no, issue_date, required_delivery_date,
                    delivery_mode, trade_terms, payment_terms, shipping_date,
                    currency, total_amount, internal_shipping_fee, previous_balance_note,
                    bill_name, bill_company, bill_address, bill_city, bill_country, bill_phone, bill_email,
                    ship_name, ship_company, ship_address, ship_city, ship_country, ship_phone, ship_email
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                f.get("contact_id"), f.get("invoice_no"), f.get("issue_date"), f.get("required_delivery_date"),
                f.get("delivery_mode"), f.get("trade_terms"), f.get("payment_terms"), f.get("shipping_date"),
                f.get("currency"), f.get("total_amount"), f.get("internal_shipping_fee"), f.get("previous_balance_note"),
                f.get("bill_name"), f.get("bill_company"), f.get("bill_address"), f.get("bill_city"),
                f.get("bill_country"), f.get("bill_phone"), f.get("bill_email"),
                f.get("ship_name"), f.get("ship_company"), f.get("ship_address"), f.get("ship_city"),
                f.get("ship_country"), f.get("ship_phone"), f.get("ship_email")
            ))
            db.commit()
            flash("Invoice created successfully!")
            return redirect(url_for("invoices"))
        except Exception as e:
            db.rollback()
            flash(f"Error: {e}")
            return redirect(url_for("invoices"))
    contacts = db.execute("SELECT id, name FROM contacts ORDER BY name").fetchall()
    return render_template_string("""
    <html><body style="font-family:Arial;margin:40px">
      <h2>New Invoice</h2>
      <form method="POST">
        Contact: <select name="contact_id">
          {% for c in contacts %}
            <option value="{{c['id']}}">{{c['name']}}</option>
          {% endfor %}
        </select><br><br>
        Invoice No: <input name="invoice_no"><br>
        Issue Date: <input name="issue_date" type="date"><br>
        Required Delivery: <input name="required_delivery_date" type="date"><br>
        Currency: <input name="currency" value="USD"><br>
        Total: <input name="total_amount"><br><br>

        <b>Bill To:</b><br>
        <input name="bill_name" placeholder="Name"><br>
        <input name="bill_company" placeholder="Company"><br>
        <input name="bill_address" placeholder="Address"><br>
        <input name="bill_city" placeholder="City"><br>
        <input name="bill_country" placeholder="Country"><br>
        <input name="bill_phone" placeholder="Phone"><br>
        <input name="bill_email" placeholder="Email"><br><br>

        <b>Ship To:</b> (leave blank to copy from Bill To)<br>
        <input name="ship_name" placeholder="Name"><br>
        <input name="ship_company" placeholder="Company"><br>
        <input name="ship_address" placeholder="Address"><br>
        <input name="ship_city" placeholder="City"><br>
        <input name="ship_country" placeholder="Country"><br>
        <input name="ship_phone" placeholder="Phone"><br>
        <input name="ship_email" placeholder="Email"><br><br>

        <button>Save Invoice</button>
      </form>
    </body></html>""", contacts=contacts)

# ============================================
# VIEW INVOICE (fixed)
# ============================================
@app.route("/invoices/<int:invoice_id>")
@login_required
def invoice_view(invoice_id):
    db = get_db()
    inv = db.execute("""
      SELECT i.*, c.name AS c_name, c.company AS c_company, c.address AS c_address,
             c.city AS c_city, c.country AS c_country, c.phone AS c_phone,
             c.email AS c_email
      FROM invoices i LEFT JOIN contacts c ON c.id=i.contact_id
      WHERE i.id=?
    """, (invoice_id,)).fetchone()
    if not inv:
        return "Invoice not found"

    return render_template_string(f"""
    <html><body style="font-family:Arial;margin:40px">
      <img src="{LOGO_URL}" style="max-height:90px"><br>
      <h2>{COMPANY_NAME}</h2>
      <p>{COMPANY_ADDRESS}<br>{COMPANY_EMAIL}</p><hr>
      <h3>Proforma Invoice</h3>
      <p><b>No:</b> {inv['invoice_no']}<br><b>Date:</b> {inv['issue_date']}</p>
      <table width="100%">
        <tr>
          <td valign="top">
            <b>Bill To:</b><br>{inv['bill_name']}<br>{inv['bill_company']}<br>{inv['bill_address']}<br>{inv['bill_city']} {inv['bill_country']}<br>{inv['bill_phone']}<br>{inv['bill_email']}
          </td>
          <td valign="top">
            <b>Ship To:</b><br>{inv['ship_name']}<br>{inv['ship_company']}<br>{inv['ship_address']}<br>{inv['ship_city']} {inv['ship_country']}<br>{inv['ship_phone']}<br>{inv['ship_email']}
          </td>
        </tr>
      </table><hr>
      <b>Total:</b> {money(inv['total_amount'])} {inv['currency']}
      <p>{BANK_INFO}</p>
      <br><a href="/invoices">Back</a>
    </body></html>""")

# ============================================
if __name__ == "__main__":
    app.run(debug=True)
