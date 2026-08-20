import sqlite3
import pandas as pd
import numpy as np
import os
import warnings
from datetime import datetime
import streamlit as st

DB_FILE = os.getenv("DATABASE_PATH", "tender_tracker.db")

# Exact 1:1 mapping matching original Excel headers
COLUMN_MAPPING = {
    'category': 'Category',
    'product_code': 'Product code',
    'product_description': 'Product Description',
    'pack_size': 'pack size',
    'currency': 'Currency',
    'unit_price': 'Unit price',
    'incoterm': 'Incoterm',
    'manufacturer_origin': 'Manufacturer and country of origin',
    'manufacturer_address': "Manufacturer's addresses",
    'supplier': 'Supplier',
    'ref_framework': 'Ref/N° of Framework Agreement',
    'title_contract': 'Title of the contract',
    'delivery_period': 'Delivey period',
    'starting_date': 'Starting date for contract execution (contact signature)',
    'expiry_date': 'Contract End Date (Expiry)',
    'validity_period': 'Validity Period (Years)',
    'contract_year': 'Contract Execution Year',
    'procurement_officer': 'PROCUREMENT OFFICER',
    'cleaning_action': 'CLEANING ACTION'
}

REVERSE_MAPPING = {v: k for k, v in COLUMN_MAPPING.items()}

def get_db_col_name(ui_col):
    """Robustly maps any UI column name (case & whitespace insensitive) to SQLite DB column name."""
    if ui_col in REVERSE_MAPPING:
        return REVERSE_MAPPING[ui_col]
    
    ui_clean = str(ui_col).strip().lower()
    for k, v in REVERSE_MAPPING.items():
        if k.strip().lower() == ui_clean:
            return v
            
    for db_col in COLUMN_MAPPING.keys():
        if db_col.lower() == ui_clean:
            return db_col
            
    alias_map = {
        'delivery period': 'delivery_period',
        'delivey period': 'delivery_period',
        'procurement officer': 'procurement_officer',
        'title of contract': 'title_contract',
        'title of the contract': 'title_contract',
        'product description': 'product_description',
        'product code': 'product_code',
        'validity period': 'validity_period',
        'validity period (years)': 'validity_period',
        'contract execution year': 'contract_year',
        'manufacturer address': 'manufacturer_address',
        "manufacturer's addresses": 'manufacturer_address',
        'manufacturer and country of origin': 'manufacturer_origin',
        'category': 'category',
        'sheet': 'category',
        'incoterm': 'incoterm',
        'supplier': 'supplier',
        'end_user': 'end_user',
        'demandor': 'end_user',
        'demandor (end user)': 'end_user',
        'budget_holder': 'budget_holder',
        'budget holder': 'budget_holder',
        'classification': 'classification'
    }
    return alias_map.get(ui_clean, ui_col)

def get_conn():
    db_dir = os.path.dirname(DB_FILE)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_FILE, timeout=60, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA mmap_size = 30000000000;")
    conn.execute("PRAGMA cache_size = -64000;")
    conn.execute("PRAGMA busy_timeout=60000;")
    return conn

def clear_cache():
    try:
        st.cache_data.clear()
    except Exception:
        pass

def log_action_cursor(cursor, message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("INSERT INTO logs (timestamp, message) VALUES (?, ?)", (timestamp, message))

def init_db():
    conn = get_conn()
    try:
        c = conn.cursor()
        
        # 1. Master Contracts Table
        c.execute('''
            CREATE TABLE IF NOT EXISTS contracts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT,
                no TEXT,
                product_code TEXT,
                product_description TEXT,
                pack_size TEXT,
                classification TEXT,
                currency TEXT,
                unit_price REAL,
                incoterm TEXT,
                manufacturer_origin TEXT,
                manufacturer_address TEXT,
                supplier TEXT,
                ref_framework TEXT,
                framework_ref TEXT,
                title_contract TEXT,
                contract_title TEXT,
                delivery_period TEXT,
                starting_date TEXT,
                expiry_date TEXT,
                validity_period INTEGER DEFAULT 1,
                contract_year TEXT,
                end_user TEXT,
                budget_holder TEXT,
                procurement_officer TEXT,
                cleaning_action TEXT,
                is_deleted INTEGER DEFAULT 0,
                deleted_by TEXT,
                deleted_at TEXT
            )
        ''')

        # 2. AUTOMATIC SCHEMA MIGRATION FOR EXISTING DB FILES
        c.execute("PRAGMA table_info(contracts)")
        existing_cols = [r[1] for r in c.fetchall()]

        required_cols = {
            'category': 'TEXT', 'no': 'TEXT', 'product_code': 'TEXT',
            'product_description': 'TEXT', 'pack_size': 'TEXT', 'classification': 'TEXT',
            'currency': 'TEXT', 'unit_price': 'REAL', 'incoterm': 'TEXT',
            'manufacturer_origin': 'TEXT', 'manufacturer_address': 'TEXT',
            'supplier': 'TEXT', 'ref_framework': 'TEXT', 'framework_ref': 'TEXT',
            'title_contract': 'TEXT', 'contract_title': 'TEXT', 'delivery_period': 'TEXT',
            'starting_date': 'TEXT', 'expiry_date': 'TEXT', 'validity_period': 'INTEGER DEFAULT 1',
            'contract_year': 'TEXT', 'end_user': 'TEXT', 'budget_holder': 'TEXT',
            'procurement_officer': 'TEXT', 'cleaning_action': 'TEXT',
            'is_deleted': 'INTEGER DEFAULT 0', 'deleted_by': 'TEXT', 'deleted_at': 'TEXT'
        }

        for col, col_type in required_cols.items():
            if col not in existing_cols:
                try:
                    c.execute(f'ALTER TABLE contracts ADD COLUMN {col} {col_type}')
                except sqlite3.OperationalError:
                    pass

        # Sync framework_ref / ref_framework
        if 'framework_ref' in existing_cols and 'ref_framework' in existing_cols:
            try:
                c.execute("UPDATE contracts SET ref_framework = framework_ref WHERE (ref_framework IS NULL OR ref_framework = '') AND framework_ref IS NOT NULL AND framework_ref != ''")
                c.execute("UPDATE contracts SET framework_ref = ref_framework WHERE (framework_ref IS NULL OR framework_ref = '') AND ref_framework IS NOT NULL AND ref_framework != ''")
            except sqlite3.OperationalError:
                pass

        # Sync contract_title into title_contract
        if 'contract_title' in existing_cols and 'title_contract' in existing_cols:
            try:
                c.execute("UPDATE contracts SET title_contract = contract_title WHERE (title_contract IS NULL OR title_contract = '') AND contract_title IS NOT NULL AND contract_title != ''")
            except sqlite3.OperationalError:
                pass

        # 3. RMS Emails Directory
        c.execute('''
            CREATE TABLE IF NOT EXISTS rms_emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                email TEXT UNIQUE,
                department TEXT,
                role TEXT,
                created_at TEXT
            )
        ''')

        c.execute("SELECT COUNT(*) FROM rms_emails")
        if c.fetchone()[0] == 0:
            c.executemany('''
                INSERT INTO rms_emails (name, email, department, role, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', [
                ('RMS Logistics & Inventory', 'logistics@rms.rw', 'Logistics', 'Officer', datetime.now().strftime("%Y-%m-%d")),
                ('RMS Pharmacy Division', 'pharmacy@rms.rw', 'Pharmacy', 'Head', datetime.now().strftime("%Y-%m-%d")),
                ('RMS Procurement Office', 'procurement@rms.rw', 'Procurement', 'Manager', datetime.now().strftime("%Y-%m-%d")),
                ('RMS Quality Control', 'qa@rms.rw', 'Quality Assurance', 'Inspector', datetime.now().strftime("%Y-%m-%d"))
            ])

        # 4. Documents attached to contract rows
        c.execute('''
            CREATE TABLE IF NOT EXISTS row_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contract_id INTEGER,
                doc_number INTEGER,
                file_name TEXT,
                file_type TEXT,
                file_size INTEGER,
                file_data BLOB,
                uploaded_by TEXT,
                uploaded_at TEXT
            )
        ''')

        # 5. Audit Trail
        c.execute('''
            CREATE TABLE IF NOT EXISTS row_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contract_id INTEGER,
                user_name TEXT,
                field_changed TEXT,
                old_value TEXT,
                new_value TEXT,
                timestamp TEXT
            )
        ''')

        # 6. Global System logs
        c.execute('''
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                message TEXT
            )
        ''')

        # 7. PERFORMANCE INDEXES
        c.execute("CREATE INDEX IF NOT EXISTS idx_contracts_active ON contracts(is_deleted, category);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_contracts_pdesc ON contracts(product_description);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_row_docs_cid ON row_documents(contract_id);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_row_logs_cid ON row_logs(contract_id);")

        conn.commit()
    finally:
        conn.close()

def add_custom_column(col_name):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(f'ALTER TABLE contracts ADD COLUMN "{col_name}" TEXT')
        log_action_cursor(c, f"➕ Added custom column: '{col_name}'")
        conn.commit()
        clear_cache()
        return True, f"Column '{col_name}' added successfully!"
    except sqlite3.OperationalError:
        return False, f"Column '{col_name}' already exists or name is invalid."
    finally:
        conn.close()

@st.cache_data(ttl=600)
def load_contracts(category_filter="All", search_query=""):
    conn = get_conn()
    try:
        c = conn.cursor()
        query = "SELECT * FROM contracts WHERE (is_deleted = 0 OR is_deleted IS NULL)"
        params = []

        if category_filter and category_filter != "All":
            query += " AND category = ?"
            params.append(category_filter)

        if search_query and search_query.strip():
            query += " AND (LOWER(product_description) LIKE ? OR LOWER(product_code) LIKE ? OR LOWER(supplier) LIKE ? OR LOWER(manufacturer_origin) LIKE ? OR LOWER(manufacturer_address) LIKE ? OR LOWER(ref_framework) LIKE ? OR LOWER(framework_ref) LIKE ? OR LOWER(title_contract) LIKE ? OR LOWER(contract_title) LIKE ? OR LOWER(procurement_officer) LIKE ? OR LOWER(category) LIKE ?)"
            term = f"%{search_query.strip().lower()}%"
            params.extend([term]*11)

        # SORT BY PRODUCT DESCRIPTION (A-Z LETTERS FIRST, THEN DIGITS, THEN SYMBOLS/SPACES)
        query += """ ORDER BY 
            CASE 
                WHEN TRIM(product_description) = '' OR product_description IS NULL THEN 3
                WHEN LOWER(SUBSTR(TRIM(product_description), 1, 1)) BETWEEN 'a' AND 'z' THEN 1
                WHEN SUBSTR(TRIM(product_description), 1, 1) BETWEEN '0' AND '9' THEN 2
                ELSE 3
            END ASC,
            LOWER(TRIM(product_description)) ASC,
            id ASC"""
        
        c.execute(query, params)
        data = c.fetchall()
        columns = [desc[0] for desc in c.description] if c.description else []
    finally:
        conn.close()

    df = pd.DataFrame(data, columns=columns)
    if not df.empty:
        df.rename(columns=COLUMN_MAPPING, inplace=True)
        # Drop NO, item_no, classification and duplicate columns
        df.drop(columns=['no', 'NO', 'item_no', 'classification', 'Classification', 'end_user', 'Demandor (End user)', 'budget_holder', 'Budget Holder', 'is_deleted', 'deleted_by', 'deleted_at', 'framework_ref', 'contract_title', 'Answer', 'answer'], errors='ignore', inplace=True)
        
        if 'Product code' in df.columns:
            df['Product code'] = df['Product code'].astype(str).str.replace(r'\.0$', '', regex=True).replace(['nan', 'None', '<NA>'], '')
            
    return df

@st.cache_data(ttl=600)
def get_unique_categories():
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("SELECT DISTINCT category FROM contracts WHERE (is_deleted = 0 OR is_deleted IS NULL) AND category IS NOT NULL AND TRIM(category) != '' ORDER BY category ASC")
        rows = c.fetchall()
        cats = [r[0].strip() for r in rows if r[0] and r[0].strip()]
        defaults = ["All", "Medicines", "Consumables", "Laboratory", "IMPLANTS_"]
        for d in defaults:
            if d not in cats: cats.append(d)
        return cats
    finally:
        conn.close()

def update_single_cell(contract_id, ui_col_name, new_val, user_name="Admin"):
    conn = get_conn()
    try:
        c = conn.cursor()
        
        c.execute("PRAGMA table_info(contracts)")
        valid_db_cols = set(r[1] for r in c.fetchall())
        
        db_col_name = get_db_col_name(ui_col_name)
        if db_col_name not in valid_db_cols:
            return
        
        c.execute(f'SELECT "{db_col_name}", starting_date, validity_period, expiry_date FROM contracts WHERE id = ?', (contract_id,))
        res = c.fetchone()
        old_val = str(res[0]) if res and res[0] is not None else ""
        cur_start = res[1] if res else ""
        cur_val = res[2] if res and res[2] else 1

        clean_val = str(new_val).strip() if pd.notna(new_val) else ""
        if old_val != clean_val:
            query = f'UPDATE contracts SET "{db_col_name}" = ? WHERE id = ?'
            c.execute(query, (clean_val, contract_id))
            
            # AUTOMATICALLY RECALCULATE EXPIRY DATE IF VALIDITY PERIOD OR START DATE CHANGED
            if db_col_name in ['starting_date', 'validity_period']:
                st_date = clean_val if db_col_name == 'starting_date' else cur_start
                try: val_yrs = int(clean_val) if db_col_name == 'validity_period' else int(cur_val)
                except: val_yrs = 1

                st_dt = pd.to_datetime(st_date, errors='coerce')
                if pd.notna(st_dt):
                    calc_exp = (st_dt + pd.DateOffset(years=val_yrs) - pd.Timedelta(days=1)).strftime('%Y-%m-%d')
                    c.execute('UPDATE contracts SET expiry_date = ? WHERE id = ?', (calc_exp, contract_id))

            if db_col_name == 'ref_framework':
                c.execute('UPDATE contracts SET framework_ref = ? WHERE id = ?', (clean_val, contract_id))
            elif db_col_name == 'title_contract':
                c.execute('UPDATE contracts SET contract_title = ? WHERE id = ?', (clean_val, contract_id))
                
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute('''
                INSERT INTO row_logs (contract_id, user_name, field_changed, old_value, new_value, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (contract_id, user_name, COLUMN_MAPPING.get(db_col_name, ui_col_name), old_val, clean_val, timestamp))
            
            log_action_cursor(c, f"✏️ Cell '{db_col_name}' updated on Item #{contract_id} by {user_name}")
            
        conn.commit()
        clear_cache()
    finally:
        conn.close()

def update_full_contract(contract_id, row_dict, user_name="Admin"):
    conn = get_conn()
    try:
        c = conn.cursor()
        
        c.execute("PRAGMA table_info(contracts)")
        valid_db_cols = set(r[1] for r in c.fetchall())
        
        # Recalculate expiry date if starting date or validity period updated
        st_date_input = row_dict.get('Starting date for contract execution (contact signature)', None)
        val_yrs_input = row_dict.get('Validity Period (Years)', None)

        if st_date_input is not None and val_yrs_input is not None:
            try:
                v_yrs = int(val_yrs_input)
                st_dt = pd.to_datetime(st_date_input, errors='coerce')
                if pd.notna(st_dt):
                    row_dict['Contract End Date (Expiry)'] = (st_dt + pd.DateOffset(years=v_yrs) - pd.Timedelta(days=1)).strftime('%Y-%m-%d')
            except Exception:
                pass

        for ui_col, new_val in row_dict.items():
            db_col = get_db_col_name(ui_col)
            if db_col not in valid_db_cols or db_col in ['id', 'is_deleted', 'deleted_by', 'deleted_at']: 
                continue
            
            c.execute(f'SELECT "{db_col}" FROM contracts WHERE id = ?', (contract_id,))
            res = c.fetchone()
            old_val = str(res[0]) if res and res[0] is not None else ""
            
            clean_new_val = str(new_val).strip() if pd.notna(new_val) else ""
            if old_val != clean_new_val:
                query = f'UPDATE contracts SET "{db_col}" = ? WHERE id = ?'
                c.execute(query, (clean_new_val, contract_id))
                
                if db_col == 'ref_framework':
                    c.execute('UPDATE contracts SET framework_ref = ? WHERE id = ?', (clean_new_val, contract_id))
                elif db_col == 'title_contract':
                    c.execute('UPDATE contracts SET contract_title = ? WHERE id = ?', (clean_new_val, contract_id))

                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                c.execute('''
                    INSERT INTO row_logs (contract_id, user_name, field_changed, old_value, new_value, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (contract_id, user_name, COLUMN_MAPPING.get(db_col, ui_col), old_val, clean_new_val, timestamp))

        log_action_cursor(c, f"✏️ Full updates saved for Contract Item #{contract_id} by {user_name}")
        conn.commit()
        clear_cache()
    finally:
        conn.close()

def delete_contract(contract_id, user_name):
    conn = get_conn()
    try:
        c = conn.cursor()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("UPDATE contracts SET is_deleted = 1, deleted_by = ?, deleted_at = ? WHERE id = ?", (user_name, timestamp, contract_id))
        log_action_cursor(c, f"🗑️ Contract Item #{contract_id} deleted by {user_name}")
        conn.commit()
        clear_cache()
    finally:
        conn.close()

def get_field_val(row, *aliases):
    for alias in aliases:
        for col in row.index:
            if str(col).strip().lower() == str(alias).strip().lower():
                val = row[col]
                if pd.notna(val):
                    if isinstance(val, (pd.Timestamp, datetime)):
                        return val.strftime('%Y-%m-%d')
                    return str(val).strip()
    return ""

def import_excel_master(file_or_path):
    # Strictly validate Excel extension
    filename = str(getattr(file_or_path, 'name', file_or_path)).lower()
    if not (filename.endswith('.xlsx') or filename.endswith('.xls')):
        return False, "Unsupported file format. Please upload a valid Microsoft Excel file (.xlsx or .xls)."

    conn = get_conn()
    try:
        xls = pd.ExcelFile(file_or_path)
        c = conn.cursor()
        total_imported = 0
        for sheet in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name=sheet)
            df.dropna(how='all', inplace=True)
            
            rows_to_insert = []
            for idx, row in df.iterrows():
                item_no = get_field_val(row, 'NO', '#')
                
                p_code = get_field_val(row, 'Product code', 'Code')
                if p_code.endswith('.0'): p_code = p_code[:-2]

                desc = get_field_val(row, 'Product Description', 'Product description', 'Description')
                pack_size = get_field_val(row, 'pack size', 'Pack Size')
                classif = get_field_val(row, 'General medicines/Specialised/Oncology', 'Classification')
                currency = get_field_val(row, 'Currency')
                
                u_price_raw = get_field_val(row, 'Unit price', 'Unit Price')
                try: u_price = float(u_price_raw) if u_price_raw else None
                except: u_price = None

                incoterm = get_field_val(row, 'Incoterm')
                m_origin = get_field_val(row, 'Manufacturer and country of origin')
                m_addr = get_field_val(row, "Manufacturer's addresses", "Manufacturer address")
                supplier = get_field_val(row, 'Supplier', 'os')
                fw_ref = get_field_val(row, 'Ref/N° of Framework Agreement', 'Framework Agreement Ref')
                contract_title = get_field_val(row, 'Title of the contract', 'Contract Title')
                deliv = get_field_val(row, 'Delivey period', 'Delivery period')
                
                start_date_raw = get_field_val(row, 'Starting date for contract execution (contact signature)')
                start_dt = pd.to_datetime(start_date_raw, errors='coerce', format='mixed')
                start_date = start_dt.strftime('%Y-%m-%d') if pd.notna(start_dt) else start_date_raw

                expiry_date_raw = get_field_val(row, 'Contract End Date (Expiry)', 'Contract end date', 'Expiry date', 'End date', 'Expiry')
                exp_dt = pd.to_datetime(expiry_date_raw, errors='coerce', format='mixed')
                expiry_date = exp_dt.strftime('%Y-%m-%d') if pd.notna(exp_dt) else expiry_date_raw

                contract_year = get_field_val(row, 'Contract Execution Year', 'Contract Year', 'Execution Year', 'Unnamed: 18', 'Unnamed: 17')

                end_user = get_field_val(row, 'Demandor (End user)', 'End user', 'Demandor')
                budget = get_field_val(row, 'Budget Holder')
                officer = get_field_val(row, 'PROCUREMENT OFFICER', 'Procurement Officer')
                clean_act = get_field_val(row, 'CLEANING ACTION')

                row_tuple = (
                    str(sheet).strip(), item_no, p_code, desc, pack_size, classif, currency, u_price,
                    incoterm, m_origin, m_addr, supplier, fw_ref, fw_ref, contract_title, contract_title, deliv, start_date,
                    expiry_date, 1, contract_year, end_user, budget, officer, clean_act, 0, None, None
                )
                rows_to_insert.append(row_tuple)

            c.executemany('''
                INSERT INTO contracts (
                    category, no, product_code, product_description, pack_size,
                    classification, currency, unit_price, incoterm, manufacturer_origin,
                    manufacturer_address, supplier, ref_framework, framework_ref, title_contract, contract_title,
                    delivery_period, starting_date, expiry_date, validity_period, contract_year, end_user, budget_holder, procurement_officer,
                    cleaning_action, is_deleted, deleted_by, deleted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', rows_to_insert)
            total_imported += len(rows_to_insert)

        log_action_cursor(c, f"📁 Master Excel Imported: {total_imported} records across {len(xls.sheet_names)} sheets.")
        conn.commit()
        clear_cache()
        return True, total_imported
    except Exception as e:
        return False, f"Error processing Excel file: {str(e)}"
    finally:
        conn.close()

@st.cache_data(ttl=600)
def get_rms_emails():
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("SELECT id, name, email, department, role FROM rms_emails ORDER BY name ASC")
        rows = c.fetchall()
    finally:
        conn.close()
    return pd.DataFrame(rows, columns=['ID', 'Name', 'Email', 'Department', 'Role'])

def add_rms_email(name, email, department, role):
    conn = get_conn()
    try:
        c = conn.cursor()
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("INSERT INTO rms_emails (name, email, department, role, created_at) VALUES (?, ?, ?, ?, ?)",
                  (name, email, department, role, created_at))
        log_action_cursor(c, f"📧 Added RMS Email recipient: {email} ({name})")
        conn.commit()
        clear_cache()
        return True, "Email successfully registered!"
    except sqlite3.IntegrityError:
        return False, "This email address is already registered."
    finally:
        conn.close()

def delete_rms_email(email_id):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM rms_emails WHERE id = ?", (email_id,))
        log_action_cursor(c, f"📧 Deleted RMS Email ID: {email_id}")
        conn.commit()
        clear_cache()
    finally:
        conn.close()

def save_row_documents(contract_id, uploaded_files, uploader_name):
    conn = get_conn()
    try:
        c = conn.cursor()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        saved_count = 0
        
        for f in uploaded_files:
            c.execute("SELECT MAX(doc_number) FROM row_documents WHERE contract_id = ?", (contract_id,))
            res = c.fetchone()
            max_num = res[0] if res else None
            next_doc_num = 1 if max_num is None else max_num + 1

            file_bytes = f.getvalue() if hasattr(f, 'getvalue') else f.read()
            
            c.execute('''
                INSERT INTO row_documents (contract_id, doc_number, file_name, file_type, file_size, file_data, uploaded_by, uploaded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (contract_id, next_doc_num, f.name, f.type, len(file_bytes), file_bytes, uploader_name, timestamp))
            
            # ALSO LOG TO ROW_LOGS SO ATTACHED DOCUMENTS SHOW UP IN THE TRAIL
            c.execute('''
                INSERT INTO row_logs (contract_id, user_name, field_changed, old_value, new_value, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (contract_id, uploader_name, "Document Attached", "-", f"Doc #{next_doc_num}: {f.name}", timestamp))

            log_action_cursor(c, f"📁 Doc #{next_doc_num} ('{f.name}') uploaded by '{uploader_name}' for Item #{contract_id}")
            saved_count += 1
        
        conn.commit()
        clear_cache()
        return saved_count
    finally:
        conn.close()

def get_row_documents(contract_id):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute('''
            SELECT id, doc_number, file_name, file_type, file_size, uploaded_by, uploaded_at
            FROM row_documents WHERE contract_id = ? ORDER BY doc_number ASC
        ''', (contract_id,))
        rows = c.fetchall()
    finally:
        conn.close()
    return pd.DataFrame(rows, columns=['id', 'Doc #', 'File Name', 'Type', 'Size (Bytes)', 'Uploaded By', 'Uploaded At'])

def delete_row_document(doc_id, user_name="Admin"):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("SELECT contract_id, doc_number, file_name FROM row_documents WHERE id = ?", (doc_id,))
        res = c.fetchone()
        if res:
            contract_id, doc_num, fname = res
            c.execute("DELETE FROM row_documents WHERE id = ?", (doc_id,))
            
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute('''
                INSERT INTO row_logs (contract_id, user_name, field_changed, old_value, new_value, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (contract_id, user_name, "Document Deleted", f"Doc #{doc_num}: {fname}", "-", timestamp))

            log_action_cursor(c, f"🗑️ Doc #{doc_num} ('{fname}') deleted for Item #{contract_id} by {user_name}")
            conn.commit()
            clear_cache()
    finally:
        conn.close()

def get_document_blob(doc_id):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("SELECT file_name, file_type, file_data FROM row_documents WHERE id = ?", (doc_id,))
        res = c.fetchone()
    finally:
        conn.close()
    return res if res else (None, None, None)

def get_row_change_trail(contract_id):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute('''
            SELECT user_name, field_changed, old_value, new_value, timestamp
            FROM row_logs WHERE contract_id = ? ORDER BY id DESC
        ''', (contract_id,))
        rows = c.fetchall()
    finally:
        conn.close()
    return pd.DataFrame(rows, columns=['Changed By', 'Field Modified', 'Previous Value', 'New Value', 'Timestamp'])

def log_action(message):
    conn = get_conn()
    try:
        c = conn.cursor()
        log_action_cursor(c, message)
        conn.commit()
    finally:
        conn.close()

def get_global_logs():
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("SELECT timestamp, message FROM logs ORDER BY id DESC LIMIT 150")
        rows = c.fetchall()
    finally:
        conn.close()
    return pd.DataFrame(rows, columns=['Timestamp', 'Action / Event Log'])