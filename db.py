import sqlite3
import pandas as pd
from datetime import datetime
import os
import re

# PERSISTENT DB PATH: Uses Railway volume path if defined, falls back to tender_tracker.db[cite: 4]
DB_FILE = os.getenv("DB_PATH", "tender_tracker.db")

# Automatically create target directory if DB_PATH includes subfolders[cite: 4]
if os.path.dirname(DB_FILE):
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)

def get_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA cache_size = -64000;")  # 64MB RAM Cache
    conn.execute("PRAGMA temp_store = MEMORY;")
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS contracts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            [Product code] TEXT,
            [Product Description] TEXT,
            [Unit price] TEXT,
            [Currency] TEXT,
            [pack size] TEXT,
            [Incoterm] TEXT,
            [Supplier] TEXT,
            [Manufacturer and country of origin] TEXT,
            [Starting date for contract execution (contact signature)] TEXT,
            [Validity Period (Years)] TEXT,
            [Contract End Date (Expiry)] TEXT,
            [Contract Execution Year] TEXT,
            [Delivey period] TEXT,
            [Ref/N° of Framework Agreement] TEXT,
            [Title of the contract] TEXT,
            [Manufacturer's addresses] TEXT,
            [Category] TEXT,
            [PROCUREMENT OFFICER] TEXT,
            [CLEANING ACTION] TEXT
        )
    """)

    # Inspect existing columns to upgrade older database schemas
    cursor.execute("PRAGMA table_info(contracts);")
    existing_cols = [row[1] for row in cursor.fetchall()]

    required_cols = [
        'Product code', 'Product Description', 'Unit price', 'Currency',
        'pack size', 'Incoterm', 'Supplier', 'Manufacturer and country of origin',
        'Starting date for contract execution (contact signature)',
        'Validity Period (Years)', 'Contract End Date (Expiry)',
        'Contract Execution Year', 'Delivey period',
        'Ref/N° of Framework Agreement', 'Title of the contract',
        "Manufacturer's addresses", 'Category', 'PROCUREMENT OFFICER',
        'CLEANING ACTION'
    ]

    for col in required_cols:
        if col not in existing_cols:
            try:
                cursor.execute(f"ALTER TABLE contracts ADD COLUMN [{col}] TEXT;")
            except Exception:
                pass

    # Safely build database indexes
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_contracts_prodcode ON contracts([Product code]);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_contracts_supplier ON contracts([Supplier]);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_contracts_category ON contracts([Category]);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_contracts_officer ON contracts([PROCUREMENT OFFICER]);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_contracts_fw_ref ON contracts([Ref/N° of Framework Agreement]);")
    except Exception as e:
        print("Index creation skipped:", e)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS row_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contract_id INTEGER,
            doc_number INTEGER,
            file_name TEXT,
            file_type TEXT,
            file_data BLOB,
            uploaded_by TEXT,
            uploaded_at TEXT
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_docs_contract_id ON row_documents(contract_id);")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS row_change_trail (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contract_id INTEGER,
            field_name TEXT,
            old_value TEXT,
            new_value TEXT,
            updated_by TEXT,
            updated_at TEXT
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_trail_contract_id ON row_change_trail(contract_id);")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rms_emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            department TEXT,
            role TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS global_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT,
            timestamp TEXT
        )
    """)

    conn.commit()
    conn.close()

def load_contracts_direct():
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM contracts ORDER BY id ASC", conn)
    conn.close()
    return df

def get_unique_categories():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT Category FROM contracts WHERE Category IS NOT NULL AND Category != ''")
    rows = cursor.fetchall()
    conn.close()
    cats = [r[0] for r in rows]
    return ["All"] + sorted(cats)

def get_db_col_name(ui_col_name):
    return ui_col_name

def add_custom_column(col_name):
    col_clean = col_name.strip()
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"ALTER TABLE contracts ADD COLUMN [{col_clean}] TEXT;")
        conn.commit()
        log_action(f"➕ Added custom column: {col_clean}")
        return True, f"Column '{col_clean}' added successfully!"
    except sqlite3.OperationalError as e:
        return False, f"Column error: {str(e)}"
    finally:
        conn.close()

def update_single_cell(contract_id, col_name, new_val, user_name="Admin Officer"):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(f"SELECT [{col_name}] FROM contracts WHERE id = ?", (contract_id,))
    row = cursor.fetchone()
    old_val = row[0] if row else ""

    cursor.execute(f"UPDATE contracts SET [{col_name}] = ? WHERE id = ?", (str(new_val), contract_id))
    
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("""
        INSERT INTO row_change_trail (contract_id, field_name, old_value, new_value, updated_by, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (contract_id, col_name, str(old_val), str(new_val), user_name, now_str))
    
    conn.commit()
    conn.close()
    log_action(f"✏️ Updated Item #{contract_id} field [{col_name}] to '{new_val}'", user_name)

def update_full_contract(contract_id, updated_fields, user_name="Admin Officer"):
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    for col_name, new_val in updated_fields.items():
        cursor.execute(f"SELECT [{col_name}] FROM contracts WHERE id = ?", (contract_id,))
        row = cursor.fetchone()
        old_val = row[0] if row else ""

        if str(old_val).strip() != str(new_val).strip():
            cursor.execute(f"UPDATE contracts SET [{col_name}] = ? WHERE id = ?", (str(new_val), contract_id))
            cursor.execute("""
                INSERT INTO row_change_trail (contract_id, field_name, old_value, new_value, updated_by, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (contract_id, col_name, str(old_val), str(new_val), user_name, now_str))

    conn.commit()
    conn.close()
    log_action(f"📝 Full edit saved for Contract Item #{contract_id}", user_name)

def delete_contract(contract_id, user_name="Admin Officer"):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM contracts WHERE id = ?", (contract_id,))
    cursor.execute("DELETE FROM row_documents WHERE contract_id = ?", (contract_id,))
    cursor.execute("DELETE FROM row_change_trail WHERE contract_id = ?", (contract_id,))
    conn.commit()
    conn.close()
    log_action(f"🗑️ Deleted Contract Item #{contract_id}", user_name)

def get_rms_emails():
    conn = get_connection()
    df = pd.read_sql_query("SELECT id as ID, name as Name, email as Email, department as Department, role as Role FROM rms_emails", conn)
    conn.close()
    return df

def add_rms_email(name, email, department="Procurement", role="Officer"):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO rms_emails (name, email, department, role) VALUES (?, ?, ?, ?)", (name, email, department, role))
        conn.commit()
        log_action(f"📧 Registered RMS email: {email}")
        return True, "Email registered successfully!"
    except sqlite3.IntegrityError:
        return False, "This email address is already registered."
    finally:
        conn.close()

def delete_rms_email(email_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM rms_emails WHERE id = ?", (email_id,))
    conn.commit()
    conn.close()
    log_action(f"🗑️ Deleted RMS email ID: {email_id}")

def get_row_documents(contract_id):
    conn = get_connection()
    query = """
        SELECT id, doc_number as [Doc #], file_name as [File Name], 
               uploaded_by as [Uploaded By], uploaded_at as [Uploaded At]
        FROM row_documents 
        WHERE contract_id = ? 
        ORDER BY doc_number ASC
    """
    df = pd.read_sql_query(query, conn, params=(contract_id,))
    conn.close()
    return df

def save_row_documents(contract_id, uploaded_files, uploader_name="Procurement Officer"):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COALESCE(MAX(doc_number), 0) FROM row_documents WHERE contract_id = ?", (contract_id,))
    current_max_doc = cursor.fetchone()[0]
    
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    uploaded_count = 0

    for file in uploaded_files:
        current_max_doc += 1
        file_bytes = file.read()
        cursor.execute("""
            INSERT INTO row_documents (contract_id, doc_number, file_name, file_type, file_data, uploaded_by, uploaded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (contract_id, current_max_doc, file.name, file.type, file_bytes, uploader_name, now_str))
        
        cursor.execute("""
            INSERT INTO row_change_trail (contract_id, field_name, old_value, new_value, updated_by, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (contract_id, "Document Uploaded", "-", f"Doc #{current_max_doc}: {file.name}", uploader_name, now_str))
        
        uploaded_count += 1

    conn.commit()
    conn.close()
    log_action(f"📁 Attached {uploaded_count} file(s) to Item #{contract_id}", uploader_name)
    return uploaded_count

def get_document_blob(doc_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT file_name, file_type, file_data FROM row_documents WHERE id = ?", (doc_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0], row[1], row[2]
    return None, None, None

def delete_row_document(doc_id, user_name="Procurement Officer"):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT contract_id, doc_number, file_name FROM row_documents WHERE id = ?", (doc_id,))
    row = cursor.fetchone()
    if row:
        contract_id, doc_num, fname = row[0], row[1], row[2]
        cursor.execute("DELETE FROM row_documents WHERE id = ?", (doc_id,))
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute("""
            INSERT INTO row_change_trail (contract_id, field_name, old_value, new_value, updated_by, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (contract_id, "Document Deleted", f"Doc #{doc_num}: {fname}", "Deleted", user_name, now_str))
        conn.commit()
        log_action(f"🗑️ Deleted Doc #{doc_num} ({fname}) from Item #{contract_id}", user_name)
    conn.close()

def get_row_change_trail(contract_id):
    conn = get_connection()
    query = """
        SELECT field_name as [Field Changed], old_value as [Old Value], 
               new_value as [New Value], updated_by as [Updated By], updated_at as [Date & Time]
        FROM row_change_trail 
        WHERE contract_id = ? 
        ORDER BY id DESC
    """
    df = pd.read_sql_query(query, conn, params=(contract_id,))
    conn.close()
    return df

def log_action(action_desc, user_name=None):
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    full_desc = f"{action_desc} (By: {user_name})" if user_name else action_desc
    cursor.execute("INSERT INTO global_logs (action, timestamp) VALUES (?, ?)", (full_desc, now_str))
    conn.commit()
    conn.close()

def get_global_logs():
    conn = get_connection()
    df = pd.read_sql_query("SELECT id as [Log ID], action as [Action Description], timestamp as [Timestamp] FROM global_logs ORDER BY id DESC LIMIT 500", conn)
    conn.close()
    return df

def import_excel_master(file_obj):
    try:
        excel_file = pd.ExcelFile(file_obj)
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM contracts;")
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='contracts';")
        conn.commit()

        imported_total = 0
        target_sheets = ['Medicines', 'Consumables', 'Laboratory', 'IMPLANTS_']
        valid_sheets = [s for s in excel_file.sheet_names if any(ts.lower() in s.lower() for ts in target_sheets)]
        sheets_to_process = valid_sheets if valid_sheets else excel_file.sheet_names

        for sheet in sheets_to_process:
            sdf = pd.read_excel(file_obj, sheet_name=sheet)
            sdf.columns = [str(c).strip() for c in sdf.columns]

            for col in sdf.columns:
                if re.match(r'(?i)^product\s*description$|^description$|^item\s*description$', str(col)):
                    sdf.rename(columns={col: 'Product Description'}, inplace=True)
                    break

            sdf = sdf.replace(r'^\s*$', pd.NA, regex=True).dropna(how='all')

            sdf['Category'] = sheet

            cols_in_db = [
                'Product code', 'Product Description', 'Unit price', 'Currency',
                'pack size', 'Incoterm', 'Supplier', 'Manufacturer and country of origin',
                'Starting date for contract execution (contact signature)',
                'Validity Period (Years)', 'Contract End Date (Expiry)',
                'Contract Execution Year', 'Delivey period',
                'Ref/N° of Framework Agreement', 'Title of the contract',
                "Manufacturer's addresses", 'Category', 'PROCUREMENT OFFICER',
                'CLEANING ACTION'
            ]

            insert_cols = [c for c in cols_in_db if c in sdf.columns]
            if insert_cols:
                sub_df = sdf[insert_cols].copy()
                sub_df.to_sql('contracts', conn, if_exists='append', index=False)
                imported_total += len(sub_df)

        conn.commit()
        conn.close()
        log_action(f"📂 Imported {imported_total} contract rows across {len(sheets_to_process)} sheet(s)")
        return True, imported_total
    except Exception as e:
        return False, str(e)