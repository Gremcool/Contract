import streamlit as st
import pandas as pd
import numpy as np
import io
import os
import smtplib
import warnings
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from datetime import datetime, timedelta
from st_aggrid import AgGrid, GridOptionsBuilder, DataReturnMode, GridUpdateMode, JsCode
from streamlit_quill import st_quill
import db

# --- INITIALIZATION & PAGE CONFIG ---
st.set_page_config(page_title="RMS Contract & Tender Tracker", layout="wide", initial_sidebar_state="expanded")
db.init_db()

# --- TIGHT CUSTOM CSS + AG-GRID HEADER STYLING (PREVENTS RE-RENDER FLASHES) ---
st.markdown("""
    <style>
        header {visibility: hidden;}
        #MainMenu {visibility: hidden;}
        .block-container { padding-top: 0.8rem !important; padding-bottom: 0.5rem !important; }
        div[data-testid="stVerticalBlock"] { gap: 0.35rem !important; }
        .custom-title {
            margin-top: 0px; font-size: 26px; font-weight: 800;
            background: -webkit-linear-gradient(45deg, #1e3c72, #2a5298);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
            margin-bottom: 0px; line-height: 1.1;
        }
        .custom-subtitle { color: #6c757d; font-size: 13px; margin-bottom: 2px; margin-top: 2px; }
        .stTabs { margin-top: 0px !important; padding-top: 0px !important; }
        .ag-header {
            background: linear-gradient(90deg, #1e3c72 0%, #2a5298 100%) !important;
            border-bottom: 2px solid #1e3c72 !important;
        }
        .ag-header-cell {
            background-color: transparent !important;
            color: #ffffff !important;
            font-weight: bold !important;
            font-size: 13px !important;
            border-right: 1px solid rgba(255, 255, 255, 0.15) !important;
        }
        .ag-header-cell-label {
            color: #ffffff !important;
            font-weight: bold !important;
        }
    </style>
""", unsafe_allow_html=True)

def create_kpi_card(title, value, bg_color, text_color, border_color, icon=""):
    return f"""
    <div style="background: {bg_color}; padding: 12px 8px; border-radius: 8px; text-align: center; border: 1px solid {border_color}; box-shadow: 0 2px 4px rgba(0,0,0,0.04); margin-bottom: 5px;">
        <p style="margin:0; color: {text_color}; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;">{icon} {title}</p>
        <h2 style="margin:0; color: {text_color}; font-size: 24px; font-weight: 800; padding-top: 2px;">{value}</h2>
    </div>
    """

def send_email_smtp(host, port, user, password, recipients, subject, body_html, attachment_list=None):
    try:
        msg = MIMEMultipart()
        msg['From'] = user
        msg['To'] = ", ".join(recipients)
        msg['Subject'] = subject
        msg.attach(MIMEText(body_html, 'html'))

        if attachment_list:
            for fname, fbytes in attachment_list:
                part = MIMEApplication(fbytes, Name=fname)
                part['Content-Disposition'] = f'attachment; filename="{fname}"'
                msg.attach(part)

        with smtplib.SMTP(host, int(port)) as server:
            server.starttls()
            server.login(user, password)
            server.sendmail(user, recipients, msg.as_string())
        return True, "Email sent successfully!"
    except Exception as e:
        return False, f"Failed to send email: {str(e)}"

# --- SAFE DATE PARSER ---
def safe_parse_dt(val):
    if pd.isna(val) or not str(val).strip():
        return pd.NaT
    s = str(val).strip()
    s_clean = re.sub(r'\s*/\s*', '/', s)
    s_clean = re.sub(r'\s*-\s*', '-', s_clean)
    
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            dt = pd.to_datetime(s_clean, errors='coerce', utc=True)
            if pd.notna(dt):
                return dt.tz_convert(None)
        except Exception:
            pass
        try:
            dt = pd.to_datetime(s_clean, errors='coerce', dayfirst=True)
            if pd.notna(dt):
                return dt.tz_localize(None) if dt.tz is not None else dt
        except Exception:
            pass
    return pd.NaT

# --- DIALOG 1: TAKE ACTION & EMAIL WORKFLOW ---
@st.dialog("⚡ Take Action & Contract Workflow", width="large")
def take_action_dialog(row_data):
    contract_id = int(row_data.get('id'))
    prod_desc = str(row_data.get('Product Description', row_data.get('Product description', 'N/A'))).strip()
    prod_code = str(row_data.get('Product code', 'N/A')).replace('.0', '').strip()
    supplier = str(row_data.get('Supplier', 'N/A')).strip()
    framework_ref = str(row_data.get('Ref/N° of Framework Agreement', 'N/A')).strip()
    
    # RECOVER / RECALCULATE EXPIRY DATE & OVERDUE DAYS
    start_str = str(row_data.get('Starting date for contract execution (contact signature)', '')).strip()
    exp_str = str(row_data.get('Contract End Date (Expiry)', '')).strip()
    
    try: v_yrs = int(float(row_data.get('Validity Period (Years)', 1)))
    except: v_yrs = 1

    calc_exp_date = ""
    st_dt = safe_parse_dt(start_str)
    if pd.notna(st_dt):
        exp_dt = st_dt + pd.DateOffset(years=v_yrs) - pd.Timedelta(days=1)
        calc_exp_date = exp_dt.strftime('%Y-%m-%d')
    elif exp_str and exp_str.lower() != 'nan':
        calc_exp_date = exp_str

    expiry_date = calc_exp_date if calc_exp_date else "N/A"

    days_past = "N/A"
    if calc_exp_date and calc_exp_date != "N/A":
        exp_dt_parsed = pd.to_datetime(calc_exp_date, errors='coerce')
        if pd.notna(exp_dt_parsed):
            today_midnight = pd.Timestamp(datetime.now().date())
            diff_days = (today_midnight - exp_dt_parsed).days
            if diff_days > 0:
                days_past = f"+{diff_days} days overdue"
            elif diff_days == 0:
                days_past = "Expires today"
            else:
                days_past = f"{abs(diff_days)} days remaining"

    st.markdown(f"**Item #:** `{contract_id}` | **Code:** `{prod_code}` | **Expiry Date:** `{expiry_date}` | **Status:** `{days_past}`")
    st.markdown(f"**Product:** `{prod_desc}`")
    st.divider()

    action_tab1, action_tab2, action_tab3 = st.tabs(["✉️ Compose Email Alert", "📁 Upload & Document Trail", "📜 Change History Trail"])

    with action_tab1:
        st.subheader("✉️ Compose Email Alert to RMS Team")
        rms_df = db.get_rms_emails()
        email_options = rms_df['Email'].tolist() if not rms_df.empty else ["procurement@rms.rw", "logistics@rms.rw"]

        selected_recipients = st.multiselect("Select RMS Recipient(s)*", options=email_options, default=email_options[:1])
        custom_cc = st.text_input("Additional External CC Email(s) (comma separated)")
        email_subject = st.text_input("Email Subject*", value=f"[RMS Alert] Item #{contract_id}: {prod_desc[:35]}... (Expiry: {expiry_date})")

        default_body = f"""
        <p>Dear RMS Team,</p>
        <p>Please review the contract execution status for the following item:</p>
        <ul>
            <li><b>Product Code:</b> {prod_code}</li>
            <li><b>Product Description:</b> {prod_desc}</li>
            <li><b>Supplier:</b> {supplier}</li>
            <li><b>Framework Ref:</b> {framework_ref}</li>
            <li><b>Contract Expiry Date:</b> {expiry_date}</li>
            <li><b>Status:</b> {days_past}</li>
        </ul>
        <p>Best regards,<br><b>RMS Procurement System</b></p>
        """

        st.markdown("**Compose Email Message:**")
        email_body_html = st_quill(value=default_body, html=True, key=f"quill_email_{contract_id}")

        st.markdown("### 📎 Email Attachments")
        existing_docs_df = db.get_row_documents(contract_id)
        selected_doc_ids = []
        if not existing_docs_df.empty:
            for _, d_row in existing_docs_df.iterrows():
                if st.checkbox(f"Doc #{d_row['Doc #']}: {d_row['File Name']} ({d_row['Uploaded By']})", key=f"att_chk_{d_row['id']}"):
                    selected_doc_ids.append(d_row['id'])

        new_att_files = st.file_uploader("Or attach new document(s)", accept_multiple_files=True, key=f"new_email_att_{contract_id}")

        # SILENT SYSTEM NO-REPLY SMTP CREDENTIALS FROM ENVIRONMENT / RAILWAY VARIABLES
        smtp_host = os.getenv("SMTP_HOST", "smtp.office365.com")
        try:
            smtp_port = int(os.getenv("SMTP_PORT", 587))
        except Exception:
            smtp_port = 587
        smtp_user = os.getenv("SMTP_USER", "alerts@rms.rw")
        smtp_pass = os.getenv("SMTP_PASSWORD", "")

        if st.button("✉️ Send Email Alert Now", type="primary", use_container_width=True):
            all_recipients = selected_recipients.copy()
            if custom_cc.strip():
                all_recipients.extend([e.strip() for e in custom_cc.split(",") if e.strip()])

            if not all_recipients: 
                st.error("Please select at least one recipient email.")
            elif not smtp_user or not smtp_pass: 
                st.error("System email credentials (SMTP_USER / SMTP_PASSWORD) are not set in Railway environment variables.")
            else:
                attachments = []
                for d_id in selected_doc_ids:
                    fname, ftype, fdata = db.get_document_blob(d_id)
                    if fdata: attachments.append((fname, fdata))
                if new_att_files:
                    for nf in new_att_files: attachments.append((nf.name, nf.read()))

                with st.spinner("Sending Email..."):
                    success, msg = send_email_smtp(smtp_host, smtp_port, smtp_user, smtp_pass, all_recipients, email_subject, email_body_html, attachments)
                    if success:
                        db.log_action(f"📧 Email alert sent for Item #{contract_id} to {', '.join(all_recipients)}")
                        st.success(msg)
                    else: st.error(msg)

    # TAB 2: ATTACHED DOCUMENTS & UPLOAD/DELETE TRAIL
    with action_tab2:
        st.subheader("📁 Attached Documents & Upload Trail")
        uploader_name = st.text_input("Your Name / Officer Name*", value="Procurement Officer", key=f"uploader_name_field_{contract_id}")
        uploaded_files = st.file_uploader("Upload Document(s) for this line item", accept_multiple_files=True, key=f"tab_doc_uploader_{contract_id}")

        if st.button("⬆️ Upload & Assign Doc Numbers", key=f"btn_upload_doc_{contract_id}", type="primary"):
            if not uploader_name.strip(): st.error("Please enter your name to upload.")
            elif not uploaded_files: st.warning("Please select files first.")
            else:
                count = db.save_row_documents(contract_id, uploaded_files, uploader_name.strip())
                st.success(f"Successfully uploaded and numbered {count} document(s)!")
                st.rerun()

        st.divider()
        st.markdown("### 📋 Line Item Document Repository")
        docs_df = db.get_row_documents(contract_id)
        if docs_df.empty:
            st.info("No documents uploaded for this contract item yet.")
        else:
            for _, doc in docs_df.iterrows():
                c1, c2, c3, c4, c5 = st.columns([1, 4, 3, 2, 2])
                with c1: st.markdown(f"**Doc #{doc['Doc #']}**")
                with c2: st.markdown(f"📄 **{doc['File Name']}**")
                with c3: st.markdown(f"👤 {doc['Uploaded By']} | 🕒 {doc['Uploaded At']}")
                with c4:
                    fname, ftype, fdata = db.get_document_blob(doc['id'])
                    if fdata:
                        st.download_button("💾 Download", data=fdata, file_name=fname, mime=ftype, key=f"dl_btn_{doc['id']}")
                with c5:
                    if st.button("🗑️ Delete File", key=f"del_doc_{doc['id']}"):
                        db.delete_row_document(doc['id'], user_name=uploader_name)
                        st.success("Document deleted.")
                        st.rerun()

    with action_tab3:
        st.subheader("📜 Line Item Change History Trail")
        trail_df = db.get_row_change_trail(contract_id)
        if trail_df.empty: st.info("No cell modifications or document uploads recorded for this row yet.")
        else: st.dataframe(trail_df, use_container_width=True, hide_index=True)

# --- DIALOG 2: EDIT CONTRACT DETAILS (NATIVE 100% FLICKER-FREE EDITOR) ---
@st.dialog("✏️ Advanced Edit Contract Details", width="large")
def edit_contract_dialog(row_data):
    contract_id = int(row_data.get('id'))
    st.markdown(f"**Editing Contract Item #:** `{contract_id}`")
    
    raw_start = safe_parse_dt(row_data.get('Starting date for contract execution (contact signature)', ''))
    default_start = raw_start.date() if pd.notna(raw_start) else None

    # SAFE VALIDITY PARSING & BOUNDARY CAPPING (UP TO 50 YEARS)
    try:
        current_validity = int(float(row_data.get('Validity Period (Years)', 1)))
    except Exception:
        current_validity = 1
    current_validity = max(1, min(50, current_validity))

    # DYNAMIC EXPIRY RECALCULATION: Start Date + Validity Period Years - 1 Day
    if pd.notna(raw_start):
        default_exp = (raw_start + pd.DateOffset(years=current_validity) - pd.Timedelta(days=1)).date()
    else:
        raw_exp = safe_parse_dt(row_data.get('Contract End Date (Expiry)', ''))
        default_exp = raw_exp.date() if pd.notna(raw_exp) else None

    with st.form(f"edit_form_{contract_id}"):
        c1, c2, c3 = st.columns(3)
        with c1:
            raw_pcode = str(row_data.get('Product code', '')).replace('.0', '')
            e_code = st.text_input("Product Code", value=raw_pcode)
            e_supp = st.text_input("Supplier", value=str(row_data.get('Supplier', '')))
            e_start = st.date_input("Starting Date", value=default_start)
        with c2:
            e_fw = st.text_input("Ref/N° of Framework Agreement", value=str(row_data.get('Ref/N° of Framework Agreement', '')))
            e_off = st.text_input("PROCUREMENT OFFICER", value=str(row_data.get('PROCUREMENT OFFICER', '')))
            e_exp = st.date_input("Contract End Date (Expiry)", value=default_exp)
        with c3:
            e_uprice = st.text_input("Unit Price", value=str(row_data.get('Unit price', '')))
            e_curr = st.text_input("Currency", value=str(row_data.get('Currency', '')))
            e_pack = st.text_input("Pack Size", value=str(row_data.get('pack size', '')))

        c_extra1, c_extra2, c_extra3, c_extra4 = st.columns(4)
        with c_extra1:
            e_validity = st.number_input("Validity Period (Years)", min_value=1, max_value=50, value=current_validity, step=1)
        with c_extra2:
            current_year_val = str(row_data.get('Contract Execution Year', 'First year'))
            e_year = st.text_input("Contract Execution Year", value=current_year_val)
        with c_extra3:
            e_inco = st.text_input("Incoterm", value=str(row_data.get('Incoterm', '')))
        with c_extra4:
            e_cat = st.text_input("Category", value=str(row_data.get('Category', '')))

        c_m1, c_m2 = st.columns(2)
        with c_m1:
            e_morigin = st.text_input("Manufacturer and country of origin", value=str(row_data.get('Manufacturer and country of origin', '')))
        with c_m2:
            e_deliv = st.text_input("Delivery Period", value=str(row_data.get('Delivey period', '')))

        val_title = str(row_data.get('Title of the contract', ''))
        e_title = st.text_area("📝 Title of the Contract", value=val_title, height=70, key=f"txt_edit_title_{contract_id}")

        val_desc = str(row_data.get('Product Description', row_data.get('Product description', '')))
        e_desc = st.text_area("📋 Product Description", value=val_desc, height=90, key=f"txt_edit_desc_{contract_id}")

        val_clean = str(row_data.get('CLEANING ACTION', ''))
        e_clean = st.text_area("💬 CLEANING ACTION / Notes", value=val_clean, height=70, key=f"txt_edit_clean_{contract_id}")

        if st.form_submit_button("Save All Contract Changes", type="primary", use_container_width=True):
            with st.spinner("💾 Saving contract updates to database..."):
                # Recalculate end date based on updated validity period & start date
                if e_start and e_validity:
                    calc_new_exp = (pd.to_datetime(e_start) + pd.DateOffset(years=int(e_validity)) - pd.Timedelta(days=1)).strftime('%Y-%m-%d')
                else:
                    calc_new_exp = e_exp.strftime('%Y-%m-%d') if e_exp else ""

                updated_fields = {
                    'Product code': e_code,
                    'Supplier': e_supp,
                    'Ref/N° of Framework Agreement': e_fw,
                    'PROCUREMENT OFFICER': e_off,
                    'Unit price': e_uprice,
                    'Currency': e_curr,
                    'Validity Period (Years)': e_validity,
                    'Contract Execution Year': e_year,
                    'pack size': e_pack,
                    'Incoterm': e_inco,
                    'Category': e_cat,
                    'Manufacturer and country of origin': e_morigin,
                    'Delivey period': e_deliv,
                    'Title of the contract': e_title,
                    'Product Description': e_desc,
                    'CLEANING ACTION': e_clean,
                    'Starting date for contract execution (contact signature)': e_start.strftime('%Y-%m-%d') if e_start else "",
                    'Contract End Date (Expiry)': calc_new_exp
                }
                db.update_full_contract(contract_id, updated_fields, user_name="Admin Officer")
                
                # INCREMENT GRID VERSION TO UNCHECK CHECKBOX & RESET SELECTION
                st.session_state['grid_version'] = st.session_state.get('grid_version', 0) + 1
                st.success("Contract details successfully updated!")
                st.rerun()

# --- HEADER & BRANDING ---
c_logo, c_title = st.columns([1, 12])
with c_logo:
    if os.path.exists("logo.jpg"): st.image("logo.jpg", width=75)
    else: st.markdown("<h2 style='margin:0;'>🏢</h2>", unsafe_allow_html=True)
with c_title:
    st.markdown("<div class='custom-title'>RMS CONTRACT MASTER & TENDER TRACKER</div>", unsafe_allow_html=True)
    st.markdown("<div class='custom-subtitle'>Rwanda Medical Supply Ltd - Contract Execution, Document Trail & Expiry Portal</div>", unsafe_allow_html=True)

# --- NAVIGATION TABS ---
tab_tracker, tab_emails, tab_import, tab_logs = st.tabs([
    "📊 Master Contract Tracker", 
    "📧 RMS Email Directory", 
    "📂 Import Excel Master", 
    "📝 System Audit Trail"
])

# ==========================================
# FRAGMENT: ISOLATED FLICKER-FREE GRID RENDERER
# ==========================================
@st.fragment
def render_tracker_grid(df, category_filter, status_filter, search_query):
    # FAST VECTORIZED PROCESSING & CUSTOM SORTING (A-Z LETTERS -> NUMBERS -> SYMBOLS/SPACES)
    if not df.empty:
        # 1. Clean Product code vectorized
        if 'Product code' in df.columns:
            df['Product code'] = df['Product code'].astype(str).str.replace(r'\.0$', '', regex=True).replace(['nan', 'None', '<NA>'], '')

        # 2. Clean Start Date vectorized
        if 'Starting date for contract execution (contact signature)' in df.columns:
            clean_start = df['Starting date for contract execution (contact signature)'].astype(str).str.replace(r'\s*[\/\-]\s*', '-', regex=True).str.strip()
            parsed_start = pd.to_datetime(clean_start, errors='coerce', format='mixed')
            df['Starting date for contract execution (contact signature)'] = parsed_start.dt.strftime('%Y-%m-%d').fillna('')
        else:
            parsed_start = pd.Series([pd.NaT]*len(df))

        # 3. Validity Period (Years)
        if 'Validity Period (Years)' not in df.columns:
            df['Validity Period (Years)'] = 1
        validity_years = pd.to_numeric(df['Validity Period (Years)'], errors='coerce').fillna(1).astype(int)
        df['Validity Period (Years)'] = validity_years

        # 4. Expiry Date: DYNAMIC RECALCULATION = Start Date + Validity Period Years - 1 Day
        today_midnight = pd.Timestamp(datetime.now().date())
        
        calc_exp_list = []
        for s_dt, v_yrs in zip(parsed_start, validity_years):
            if pd.notna(s_dt):
                calc_exp_list.append(s_dt + pd.DateOffset(years=int(v_yrs)) - pd.Timedelta(days=1))
            else:
                calc_exp_list.append(pd.NaT)

        final_exp = pd.Series(calc_exp_list, index=df.index)
        df['Contract End Date (Expiry)'] = final_exp.dt.strftime('%Y-%m-%d').fillna('')

        days_to_exp = (final_exp - today_midnight).dt.days
        days_past_exp = (today_midnight - final_exp).dt.days

        df['Days_To_Expiry'] = days_to_exp
        df['Days_Past_Expiry'] = days_past_exp

        # Days Expired: positive integer if expired (>0), 0 if active/valid
        df['Days Expired'] = np.where(days_past_exp > 0, days_past_exp, np.where(final_exp.notna(), 0, np.nan))

        # Alert flags
        df['Is_Red_Alert'] = (final_exp.notna()) & (days_to_exp <= 90)
        df['Is_Yellow_Alert'] = (final_exp.notna()) & (days_to_exp > 90) & (days_to_exp <= 180)

        # Expiry status category vectorized for instant filtering
        conds = [
            final_exp.isna(),
            days_to_exp < 0,
            days_to_exp <= 90,
            days_to_exp <= 180
        ]
        choices = [
            "Missing Expiry Date",
            "Expired / Overdue",
            "Expiring in < 3 Months",
            "Expiring in 3–6 Months"
        ]
        df['Expiry_Status_Cat'] = np.select(conds, choices, default="Valid (> 6 Months)")

        # CUSTOM SORTING: 1) Letters A-Z, 2) Digits 0-9, 3) Symbols & Empty spaces
        if 'Product Description' in df.columns:
            s_clean = df['Product Description'].astype(str).str.strip()
            first_char = s_clean.str[0].str.lower()
            
            is_alpha = first_char.str.contains(r'^[a-z]$', regex=True, na=False)
            is_digit = first_char.str.contains(r'^[0-9]$', regex=True, na=False)
            
            df['_sort_priority'] = np.where(is_alpha, 1, np.where(is_digit, 2, 3))
            df['_sort_key'] = s_clean.str.lower()
            
            df.sort_values(by=['_sort_priority', '_sort_key'], ascending=[True, True], inplace=True)
            df.drop(columns=['_sort_priority', '_sort_key'], inplace=True)
            df.reset_index(drop=True, inplace=True)
    else:
        df['Days_To_Expiry'] = None
        df['Days_Past_Expiry'] = None
        df['Days Expired'] = None
        df['Is_Red_Alert'] = False
        df['Is_Yellow_Alert'] = False
        df['Expiry_Status_Cat'] = "Missing Expiry Date"

    # APPLY STATUS FILTER DROPDOWN
    if status_filter == "🚨 Expired / Overdue":
        df = df[df['Expiry_Status_Cat'] == "Expired / Overdue"]
    elif status_filter == "🚨 Expiring in < 3 Months":
        df = df[df['Expiry_Status_Cat'] == "Expiring in < 3 Months"]
    elif status_filter == "⚠️ Expiring in 3–6 Months":
        df = df[df['Expiry_Status_Cat'] == "Expiring in 3–6 Months"]
    elif status_filter == "✅ Valid (> 6 Months)":
        df = df[df['Expiry_Status_Cat'] == "Valid (> 6 Months)"]
    elif status_filter == "⏳ Missing Expiry Date":
        df = df[df['Expiry_Status_Cat'] == "Missing Expiry Date"]

    total_count = len(df)
    red_count = int(df['Is_Red_Alert'].sum()) if not df.empty else 0
    yellow_count = int(df['Is_Yellow_Alert'].sum()) if not df.empty else 0
    valid_count = total_count - red_count - yellow_count

    k1, k2, k3, k4 = st.columns(4)
    with k1: st.markdown(create_kpi_card("Total Line Items", total_count, "#f1f5f9", "#1e293b", "#cbd5e1", "📊"), unsafe_allow_html=True)
    with k2: st.markdown(create_kpi_card("Valid (> 6 Months)", valid_count, "#dcfce7", "#166534", "#86efac", "✅"), unsafe_allow_html=True)
    with k3: st.markdown(create_kpi_card("Expiring in 3–6 Months", yellow_count, "#fef3c7", "#854d0e", "#fde047", "⚠️"), unsafe_allow_html=True)
    with k4: st.markdown(create_kpi_card("Expiring < 3 Months / Expired", red_count, "#fee2e2", "#991b1b", "#fca5a5", "🚨"), unsafe_allow_html=True)

    ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([3, 3, 6])

    # EXACT REORDERED COLUMN SEQUENCE DISPLAY (DROPPED CLASSIFICATION, DEMANDOR, BUDGET HOLDER)
    preferred_col_order = [
        'Product code',
        'Product Description',
        'Unit price',
        'Currency',
        'pack size',
        'Incoterm',
        'Supplier',
        'Manufacturer and country of origin',
        'Starting date for contract execution (contact signature)',
        'Validity Period (Years)',
        'Contract End Date (Expiry)',
        'Days Expired',
        'Delivey period',
        'Ref/N° of Framework Agreement',
        'Title of the contract',
        "Manufacturer's addresses",
        'Category',
        'PROCUREMENT OFFICER',
        'CLEANING ACTION'
    ]

    existing_cols = [c for c in preferred_col_order if c in df.columns]
    extra_cols = [c for c in df.columns if c not in preferred_col_order and c not in ['id', 'NO', 'no', 'item_no', 'classification', 'Classification', 'end_user', 'Demandor (End user)', 'budget_holder', 'Budget Holder', 'Days_To_Expiry', 'Days_Past_Expiry', 'Is_Red_Alert', 'Is_Yellow_Alert', 'Expiry_Status_Cat', 'contract_title', 'Answer', 'answer']]
    all_available_cols = existing_cols + extra_cols
    
    with ctrl_col1:
        with st.popover("👁️ Select Columns to Display", use_container_width=True):
            st.markdown("**Check/Uncheck Columns to Show in Table:**")
            selected_display_cols = st.multiselect(
                "Visible Columns:",
                options=all_available_cols,
                default=all_available_cols
            )

    with ctrl_col2:
        with st.popover("➕ Add Custom Column", use_container_width=True):
            st.markdown("**Add a New Column to the Database:**")
            new_col_name = st.text_input("New Column Header (e.g. Delivery Status)")
            if st.button("Save New Column", type="primary", use_container_width=True):
                if new_col_name.strip():
                    ok, msg = db.add_custom_column(new_col_name.strip())
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

    with ctrl_col3:
        # EXCEL EXPORT BUTTON
        if not df.empty:
            export_df = df[[c for c in selected_display_cols if c in df.columns]].copy()
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                export_df.to_excel(writer, index=False, sheet_name='Contracts')
            
            st.download_button(
                label="📥 Export View to Excel (.xlsx)",
                data=excel_buffer.getvalue(),
                file_name=f"RMS_Contracts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=False
            )

    # LEGEND BAR
    st.markdown("""
        <div style="background-color: #ffffff; padding: 8px 12px; border-radius: 8px; border: 1px solid #e2e8f0; margin-top: 4px; margin-bottom: 6px; display: flex; align-items: center; gap: 15px; font-size: 13px; flex-wrap: wrap;">
            <strong>🎨 Legend:</strong>
            <span><span style="background-color: #fee2e2; color: #991b1b; padding: 3px 8px; border-radius: 4px; font-weight: bold; border: 1px solid #fca5a5;">🚨 Soft Red Row</span> Expiring in &lt; 3 Months or Expired</span>
            <span><span style="background-color: #fef3c7; color: #854d0e; padding: 3px 8px; border-radius: 4px; font-weight: bold; border: 1px solid #fde047;">⚠️ Soft Yellow Row</span> Expiring in 3 to 6 Months</span>
            <span><span style="background-color: #ffffff; color: #334155; padding: 3px 8px; border-radius: 4px; border: 1px solid #cbd5e1;">⚪ White / 🩶 Light Gray</span> Active / Valid (&gt; 6 Months)</span>
        </div>
    """, unsafe_allow_html=True)

    action_bar_top = st.empty()

    if df.empty:
        st.warning("No contract items found matching your search query or filter.")
    else:
        cols_to_render = ['id', 'Days_To_Expiry', 'Days_Past_Expiry', 'Is_Red_Alert', 'Is_Yellow_Alert'] + [c for c in selected_display_cols if c in df.columns]
        df_display = df[cols_to_render].copy()

        gb = GridOptionsBuilder.from_dataframe(df_display)
        
        gb.configure_column('id', hide=True)
        gb.configure_column('Days_To_Expiry', hide=True)
        gb.configure_column('Days_Past_Expiry', hide=True)
        gb.configure_column('Is_Red_Alert', hide=True)
        gb.configure_column('Is_Yellow_Alert', hide=True)

        gb.configure_default_column(
            wrapText=False,
            autoHeight=False,
            resizable=True,
            filter=True,
            sortable=True,
            editable=True,
            minWidth=140
        )

        # TEXT CLAMP RENDERER
        two_line_clamp_renderer = JsCode("""
        class TwoLineClampRenderer {
            init(params) {
                this.eGui = document.createElement('div');
                this.eGui.style.display = '-webkit-box';
                this.eGui.style.webkitLineClamp = '2';
                this.eGui.style.webkitBoxOrient = 'vertical';
                this.eGui.style.overflow = 'hidden';
                this.eGui.style.textOverflow = 'ellipsis';
                this.eGui.style.lineHeight = '1.25em';
                this.eGui.style.maxHeight = '2.5em';
                this.eGui.style.wordBreak = 'break-word';
                this.eGui.style.fontSize = '12px';
                let val = params.value ? params.value : '';
                this.eGui.innerHTML = val;
                this.eGui.title = val;
            }
            getGui() {
                return this.eGui;
            }
        }
        """)

        if 'Product code' in df_display.columns:
            gb.configure_column('Product code', width=160, minWidth=130, type=['stringColumn'], cellDataType='text')

        if 'Product Description' in df_display.columns:
            gb.configure_column('Product Description', width=450, minWidth=300, cellRenderer=two_line_clamp_renderer)
        
        if 'Title of the contract' in df_display.columns:
            gb.configure_column('Title of the contract', width=450, minWidth=300, cellRenderer=two_line_clamp_renderer)

        if 'Ref/N° of Framework Agreement' in df_display.columns:
            gb.configure_column('Ref/N° of Framework Agreement', width=260, minWidth=180)

        if 'Supplier' in df_display.columns:
            gb.configure_column('Supplier', width=220, minWidth=160)

        if 'Validity Period (Years)' in df_display.columns:
            gb.configure_column('Validity Period (Years)', header_name='Validity Period (Years)', width=150, minWidth=130, editable=True, type=['numericColumn'])

        # REAL-TIME CLIENT-SIDE VALUE GETTERS FOR EXPIRY & DAYS EXPIRED
        js_expiry_date_getter = JsCode("""
        function(params) {
            if (!params.data) return '';
            let startStr = params.data['Starting date for contract execution (contact signature)'];
            let vYrs = parseInt(params.data['Validity Period (Years)'], 10) || 1;
            
            if (startStr && startStr.trim() !== '') {
                let sDate = new Date(startStr);
                if (!isNaN(sDate.getTime())) {
                    let expDate = new Date(sDate);
                    expDate.setFullYear(expDate.getFullYear() + vYrs);
                    expDate.setDate(expDate.getDate() - 1);
                    
                    let yyyy = expDate.getFullYear();
                    let mm = String(expDate.getMonth() + 1).padStart(2, '0');
                    let dd = String(expDate.getDate()).padStart(2, '0');
                    return yyyy + '-' + mm + '-' + dd;
                }
            }
            return params.data['Contract End Date (Expiry)'] || '';
        }
        """)

        if 'Contract End Date (Expiry)' in df_display.columns:
            gb.configure_column('Contract End Date (Expiry)', header_name='Contract End Date (Expiry)', width=180, minWidth=160, valueGetter=js_expiry_date_getter)

        js_days_expired_getter = JsCode("""
        function(params) {
            if (!params.data) return null;
            let startStr = params.data['Starting date for contract execution (contact signature)'];
            let vYrs = parseInt(params.data['Validity Period (Years)'], 10) || 1;
            let expStr = params.data['Contract End Date (Expiry)'];
            
            let expDate = null;
            if (startStr && startStr.trim() !== '') {
                let sDate = new Date(startStr);
                if (!isNaN(sDate.getTime())) {
                    expDate = new Date(sDate);
                    expDate.setFullYear(expDate.getFullYear() + vYrs);
                    expDate.setDate(expDate.getDate() - 1);
                }
            } else if (expStr && expStr.trim() !== '') {
                expDate = new Date(expStr);
            }
            
            if (!expDate || isNaN(expDate.getTime())) return null;
            
            let today = new Date();
            today.setHours(0, 0, 0, 0);
            expDate.setHours(0, 0, 0, 0);
            
            let diffTime = today.getTime() - expDate.getTime();
            let diffDays = Math.round(diffTime / (1000 * 3600 * 24));
            
            return diffDays > 0 ? diffDays : 0;
        }
        """)

        # EXPLICIT COLUMN: DAYS EXPIRED
        if 'Days Expired' in df_display.columns:
            gb.configure_column('Days Expired', header_name='Days Expired', width=140, minWidth=120, editable=False, valueGetter=js_days_expired_getter, type=['numericColumn'])
        
        # REAL-TIME CLIENT-SIDE BADGE CELL RENDERER FOR "DAYS PAST EXPIRY" / DAYS REMAINING
        days_past_renderer = JsCode("""
        class DaysPastRenderer {
            init(params) {
                this.eGui = document.createElement('div');
                this.update(params);
            }
            refresh(params) {
                this.update(params);
                return true;
            }
            update(params) {
                if (!params.data) {
                    this.eGui.innerHTML = '<span style="color: #a0aec0;">-</span>';
                    return;
                }
                let startStr = params.data['Starting date for contract execution (contact signature)'];
                let vYrs = parseInt(params.data['Validity Period (Years)'], 10) || 1;
                let expStr = params.data['Contract End Date (Expiry)'];
                
                let expDate = null;
                if (startStr && startStr.trim() !== '') {
                    let sDate = new Date(startStr);
                    if (!isNaN(sDate.getTime())) {
                        expDate = new Date(sDate);
                        expDate.setFullYear(expDate.getFullYear() + vYrs);
                        expDate.setDate(expDate.getDate() - 1);
                    }
                } else if (expStr && expStr.trim() !== '') {
                    expDate = new Date(expStr);
                }
                
                if (!expDate || isNaN(expDate.getTime())) {
                    this.eGui.innerHTML = '<span style="color: #a0aec0;">-</span>';
                    return;
                }
                
                let today = new Date();
                today.setHours(0, 0, 0, 0);
                expDate.setHours(0, 0, 0, 0);
                
                let diffTime = expDate.getTime() - today.getTime();
                let daysToExpiry = Math.round(diffTime / (1000 * 3600 * 24));
                let daysPast = -daysToExpiry;
                
                let bgColor, textColor, borderColor, label;
                
                if (daysToExpiry < 0) {
                    bgColor = '#fee2e2'; textColor = '#991b1b'; borderColor = '#fca5a5';
                    label = '+' + daysPast + ' days overdue';
                } else if (daysToExpiry === 0) {
                    bgColor = '#fee2e2'; textColor = '#991b1b'; borderColor = '#fca5a5';
                    label = 'Expires today';
                } else if (daysToExpiry === 1) {
                    bgColor = '#fee2e2'; textColor = '#991b1b'; borderColor = '#fca5a5';
                    label = '1 day left';
                } else if (daysToExpiry <= 90) {
                    bgColor = '#fee2e2'; textColor = '#991b1b'; borderColor = '#fca5a5';
                    label = daysToExpiry + ' days left';
                } else if (daysToExpiry <= 180) {
                    bgColor = '#fef3c7'; textColor = '#854d0e'; borderColor = '#fde047';
                    label = daysToExpiry + ' days left';
                } else {
                    bgColor = '#dcfce7'; textColor = '#166534'; borderColor = '#86efac';
                    label = daysToExpiry + ' days left';
                }
                
                this.eGui.innerHTML = `<span style="background-color: ${bgColor}; color: ${textColor}; border: 1px solid ${borderColor}; padding: 3px 10px; border-radius: 6px; font-weight: bold; font-size: 11px; display: inline-block; text-align: center; white-space: nowrap;">${label}</span>`;
            }
            getGui() {
                return this.eGui;
            }
        }
        """)

        if 'Days Past Expiry' in df_display.columns:
            gb.configure_column('Days Past Expiry', header_name='Days Past Expiry', width=170, minWidth=150, editable=False, cellRenderer=days_past_renderer)

        custom_date_editor = JsCode("class DatePickerEditor { init(params) { this.eInput = document.createElement('input'); this.eInput.type = 'date'; this.eInput.value = params.value || ''; this.eInput.style.width = '100%'; this.eInput.style.height = '100%'; } getGui() { return this.eInput; } afterGuiAttached() { this.eInput.focus(); } getValue() { return this.eInput.value; } }")
        
        if 'Starting date for contract execution (contact signature)' in df_display.columns:
            gb.configure_column('Starting date for contract execution (contact signature)', width=180, minWidth=150, cellEditor=custom_date_editor)

        # CONFIGURE CHECKBOX SELECTION ON FIRST VISIBLE COLUMN
        gb.configure_selection(selection_mode="single", use_checkbox=True)
        if existing_cols:
            gb.configure_column(existing_cols[0], checkboxSelection=True)

        # AG-GRID STYLING: ROW HEIGHT 48PX (DOUBLE-LINE HEIGHT), REAL-TIME CLIENT-SIDE ROW COLORING
        gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=100)
        
        gb.configure_grid_options(
            rowHeight=48,
            singleClickEdit=True,
            rowBuffer=10,
            getRowStyle=JsCode("""
            function(params) {
                if (!params.data) return null;
                let startStr = params.data['Starting date for contract execution (contact signature)'];
                let vYrs = parseInt(params.data['Validity Period (Years)'], 10) || 1;
                let expStr = params.data['Contract End Date (Expiry)'];
                
                let expDate = null;
                if (startStr && startStr.trim() !== '') {
                    let sDate = new Date(startStr);
                    if (!isNaN(sDate.getTime())) {
                        expDate = new Date(sDate);
                        expDate.setFullYear(expDate.getFullYear() + vYrs);
                        expDate.setDate(expDate.getDate() - 1);
                    }
                } else if (expStr && expStr.trim() !== '') {
                    expDate = new Date(expStr);
                }
                
                if (!expDate || isNaN(expDate.getTime())) {
                    return params.node.rowIndex % 2 === 0 ? {'backgroundColor': '#ffffff'} : {'backgroundColor': '#f8fafc'};
                }
                
                let today = new Date();
                today.setHours(0, 0, 0, 0);
                expDate.setHours(0, 0, 0, 0);
                
                let diffTime = expDate.getTime() - today.getTime();
                let daysToExpiry = Math.round(diffTime / (1000 * 3600 * 24));
                
                if (daysToExpiry <= 90) {
                    return {'backgroundColor': '#fee2e2', 'color': '#991b1b', 'fontWeight': 'bold'};
                }
                if (daysToExpiry <= 180) {
                    return {'backgroundColor': '#fef3c7', 'color': '#854d0e', 'fontWeight': 'bold'};
                }
                return params.node.rowIndex % 2 === 0 ? {'backgroundColor': '#ffffff'} : {'backgroundColor': '#f8fafc'};
            }
            """)
        )

        grid_version = st.session_state.get('grid_version', 0)
        grid_options = gb.build()
        grid_response = AgGrid(
            df_display,
            gridOptions=grid_options,
            update_mode=GridUpdateMode.SELECTION_CHANGED | GridUpdateMode.VALUE_CHANGED,
            data_return_mode=DataReturnMode.AS_INPUT,
            theme='streamlit',
            height=580,
            allow_unsafe_jscode=True,
            key=f"rms_aggrid_master_table_{grid_version}"
        )

        selected_rows = grid_response.get("selected_rows")
        selected_data = None
        
        if isinstance(selected_rows, pd.DataFrame) and not selected_rows.empty:
            selected_data = selected_rows.iloc[0].to_dict()
        elif isinstance(selected_rows, list) and len(selected_rows) > 0:
            selected_data = selected_rows[0]

        # ACTION BUTTON BAR WHEN A ROW CHECKBOX IS CHECKED
        if selected_data:
            with action_bar_top.container():
                b1, b2, b3, _ = st.columns([2.5, 3.2, 2, 4.3])
                with b1:
                    if st.button("⚡ Take Action (Email & Files)", type="primary", use_container_width=True):
                        take_action_dialog(selected_data)
                with b2:
                    if st.button("✏️ Edit Selected Row (Advanced Editor)", use_container_width=True):
                        edit_contract_dialog(selected_data)
                with b3:
                    if st.button("🗑️ Delete Row", use_container_width=True):
                        db.delete_contract(selected_data['id'], "Admin User")
                        st.session_state['grid_version'] = st.session_state.get('grid_version', 0) + 1
                        st.success("Item deleted.")
                        st.rerun()

        # Sync Inline Cell Edits back to SQLite
        edited_df = grid_response['data']
        any_cell_updated = False
        
        for index, new_row in edited_df.iterrows():
            if 'id' not in new_row or pd.isna(new_row['id']): continue
            db_id = int(new_row['id'])
            
            old_row_match = df[df['id'] == db_id]
            if old_row_match.empty: continue
            old_row = old_row_match.iloc[0]

            for ui_col in edited_df.columns:
                if ui_col in ['id', 'Days_To_Expiry', 'Days_Past_Expiry', 'Days Expired', 'Is_Red_Alert', 'Is_Yellow_Alert', 'Expiry_Status_Cat', '_selectedRowNodeInfo']: continue
                
                db_col = db.get_db_col_name(ui_col)
                old_val = str(old_row.get(ui_col, "")).strip() if pd.notna(old_row.get(ui_col, "")) else ""
                new_val = str(new_row.get(ui_col, "")).strip() if pd.notna(new_row.get(ui_col, "")) else ""

                if old_val != new_val:
                    db.update_single_cell(db_id, db_col, new_val, user_name="Admin Officer")
                    any_cell_updated = True

        if any_cell_updated:
            st.session_state['grid_version'] = st.session_state.get('grid_version', 0) + 1
            st.rerun()

# ==========================================
# TAB 1: MASTER CONTRACT TRACKER
# ==========================================
with tab_tracker:
    s_col1, s_col2, s_col3 = st.columns([3, 1.2, 1.5])
    with s_col1:
        search_query = st.text_input("🔍 Search Description, Code, Supplier, Manufacturer, Ref #, Officer, Category, or Title...", placeholder="e.g. Paracetamol, Hetero, AUROLAB, 144/G/IRT, Cecile...")
    with s_col2:
        cat_options = db.get_unique_categories()
        category_filter = st.selectbox("Filter Sheet / Category", cat_options)
    with s_col3:
        status_filter = st.selectbox("Filter Expiry Status", [
            "All Expiry Statuses",
            "🚨 Expired / Overdue",
            "🚨 Expiring in < 3 Months",
            "⚠️ Expiring in 3–6 Months",
            "✅ Valid (> 6 Months)",
            "⏳ Missing Expiry Date"
        ])

    # Load Database Records (Cached & Fast)
    df = db.load_contracts(category_filter=category_filter, search_query=search_query)

    # RENDER FRAGMENT ISOLATED GRID (PREVENTS PAGE WHITE FLASHES)
    render_tracker_grid(df, category_filter, status_filter, search_query)

# ==========================================
# TAB 2: RMS EMAIL DIRECTORY
# ==========================================
with tab_emails:
    st.subheader("📧 RMS Team Email Directory Manager")
    st.markdown("Register RMS department emails that will appear when composing email alerts in the **Take Action** modal.")

    c1, c2 = st.columns([1, 2])
    with c1:
        st.markdown("### ➕ Add New RMS Email")
        with st.form("add_email_form", clear_on_submit=True):
            e_name = st.text_input("Name / Officer Title*")
            e_email = st.text_input("Email Address*")
            e_dept = st.text_input("Department", value="Procurement")
            e_role = st.text_input("Role / Designation", value="Officer")
            
            if st.form_submit_button("Register Email", type="primary"):
                if not e_name or not e_email: st.error("Name and Email are required.")
                else:
                    ok, msg = db.add_rms_email(e_name, e_email, e_dept, e_role)
                    if ok: st.success(msg)
                    else: st.error(msg)
                    st.rerun()

    with c2:
        st.markdown("### 📋 Registered RMS Directory")
        rms_emails_df = db.get_rms_emails()
        if rms_emails_df.empty: st.info("No RMS emails registered yet.")
        else:
            for _, erow in rms_emails_df.iterrows():
                ec1, ec2, ec3 = st.columns([3, 3, 1])
                with ec1: st.markdown(f"**{erow['Name']}** ({erow['Department']})")
                with ec2: st.markdown(f"`{erow['Email']}`")
                with ec3:
                    if st.button("🗑️", key=f"del_email_{erow['ID']}"):
                        db.delete_rms_email(erow['ID'])
                        st.rerun()

# ==========================================
# TAB 3: IMPORT EXCEL MASTER
# ==========================================
with tab_import:
    st.subheader("📂 Import / Reload Master Excel Workbook")
    st.markdown("Upload your **CONTRACT MASTER LIST.xlsx** file containing sheets: `Medicines`, `Consumables`, `Laboratory`, `IMPLANTS_`.")

    uploaded_excel = st.file_uploader("Upload Contract Master Excel File", type=["xlsx", "xls", "ods"])
    if uploaded_excel and st.button("Process & Import Workbook", type="primary"):
        with st.spinner("Processing sheets and updating SQLite database..."):
            count = db.import_excel_master(uploaded_excel)
            st.success(f"Successfully imported {count} items across all sheets!")
            st.rerun()

# ==========================================
# TAB 4: SYSTEM AUDIT TRAIL
# ==========================================
with tab_logs:
    st.subheader("📝 Global System Logs & Activity History")
    global_logs_df = db.get_global_logs()
    st.dataframe(global_logs_df, use_container_width=True, hide_index=True)