import os, sqlite3, pandas as pd

DB_PATH = os.path.join(os.path.dirname(__file__), "zakcrm.db")
XLSX = os.path.join(os.path.dirname(__file__), "data", "products.xlsx")

def import_products():
    if not os.path.exists(XLSX):
        print("No products.xlsx found")
        return
    xl = pd.ExcelFile(XLSX)
    sheet = None
    for s in xl.sheet_names:
        if "product" in s.lower():
            sheet = s
            break
    if sheet is None:
        sheet = xl.sheet_names[0]
    df = xl.parse(sheet)

    cols = {c.lower().strip(): c for c in df.columns}
    def pick(*names):
        for n in names:
            if n in cols:
                return cols[n]
        return None

    abbr = pick("product abbreviation", "abbreviation", "abbr", "short name")
    full = pick("product full name", "full name", "product name", "name")
    spec = pick("specification", "spec")
    pkg  = pick("package", "pack")
    price= pick("unit price", "price", "unit price (usd)")

    rows=[]
    for _, r in df.iterrows():
        a = str(r[abbr]).strip() if abbr and pd.notna(r[abbr]) else ""
        f = str(r[full]).strip() if full and pd.notna(r[full]) else ""
        s = str(r[spec]).strip() if spec and pd.notna(r[spec]) else ""
        p = str(r[pkg]).strip() if pkg and pd.notna(r[pkg]) else ""
        try:
            pr = float(r[price]) if price and pd.notna(r[price]) else 0.0
        except:
            pr = 0.0
        if not a and not f:
            continue
        rows.append((a,f,s,p,pr,"USD"))

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] > 0:
        print("Products already exist, skipping.")
        conn.close()
        return

    conn.executemany("INSERT INTO products(abbreviation, full_name, specification, package, default_price, currency) VALUES(?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    print(f"Imported {len(rows)} products from sheet {sheet}")

if __name__ == "__main__":
    import_products()
