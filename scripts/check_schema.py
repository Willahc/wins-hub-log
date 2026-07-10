import sqlite3
import os

DB = os.path.join(os.path.dirname(__file__), "..", "instance", "local.db")
DB = os.path.normpath(DB)
print(f"DB: {DB}")

conn = sqlite3.connect(DB)
cur = conn.cursor()
cur.execute("PRAGMA table_info(prospeccao_logs)")
cols = cur.fetchall()
print(f"Columns in prospeccao_logs ({len(cols)}):")
for c in cols:
    print(f"  {c[1]:40s} {c[2]:15s} nullable={c[3]} default={c[4]}")
conn.close()
