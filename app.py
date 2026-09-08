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
from st_aggrid import AgGrid, GridOptionsBuilder, DataReturnMode, JsCode
import db

# --- INITIALIZATION & PAGE CONFIG ---
st.set_page_config(page_title="RMS Contract Master", layout="wide", initial_sidebar_state="expanded")
db.init_db()

# --- TIGHT CUSTOM CSS + AG-GRID HEADER STYLING + ZERO-RUNNING SPINNER LOCK ---
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
        .ag-header-cell-label, .ag-header-cell-text, .ag-header-icon, .ag-icon {
            color: #ffffff !important;
            font-weight: bold !important;
        }
        
        /* HIDE ALL STREAMLIT RUNNING STATUS INDICATORS & SPINNERS */
        div[data-testid="stStatusWidget"],
        [data-testid="stStatusWidget"],
        .stStatusWidget,
        div[data-testid="stRunningWidget"],
        .stSpinner,
        div[class*="stStatusWidget"],
        div[class*="StatusWidget"],
        header [data-testid="stStatusWidget"],
        header .stStatusWidget {
            display: none !important;
            visibility: hidden !important;
            opacity: 0 !important;
            height: 0 !important;
            width: 0 !important;
            pointer-events: none !important;
        }
        
        /* DISABLE STREAMLIT OVERLAYS AND BLUR ON RERUNS */
        [data-stale="true"],
        div[data-stale="true"], 
        .stElementContainer[data-stale="true"],
        div[data-testid="stButton"][data-stale="true"],
        div[data-testid="stHorizontalBlock"][data-stale="true"],
        div[data-testid="stVerticalBlock"][data-stale="true"],
        [data-testid="stCustomComponentV1"][data-stale="true"],
        iframe[title="st_aggrid.agGrid"][data-stale="true"],
        .stAgGrid[data-stale="true"] {
            opacity: 1 !important;
            filter: none !important;
            -webkit-filter: none !important;
            transition: none !important;
            pointer-events: auto !important;
        }

        .ag-overlay-loading-wrapper, .ag-overlay-loading-center {
            display: none !important;
            visibility: hidden !important;
            opacity: 0 !important;
        }

        iframe[title="st_aggrid.agGrid"], .stAgGrid, div[data-testid="stCustomComponentV1"] {
            background-color: #ffffff !important;
            min-height: 580px !important;
            height: 580px !important;
            border-radius: 8px;
            overflow: hidden !important;
            display: block !important;
        }
    </style>
""", unsafe_allow_html=True)

# --- DATABASE CACHING & GRANULAR INVALIDATION ---
@st.cache_data(ttl=60)
def cached_get_rms_emails():
    return db.get_rms_emails()

@st.cache_data(ttl=300)
def cached_load_and_process_master():
    raw_df = db.load_contracts_direct()
    return process_vectorized_dataframe(raw_df)

@st.cache_data(ttl=300)
def cached_get_categories():
    return db.get_unique_categories()

def invalidate_master_cache():
    cached_load_and_process_master.clear()
    cached_get_categories.clear()
    if 'master_df' in st.session_state:
        del st.session_state['master_df']

def create_kpi_card(title, value, bg_color, text_color, border_color, icon=""):
    return f"""
    <div style="background: {bg_color}; padding: 12px 8px; border-radius: 8px; text-align: center; border: 1px solid {border_color}; box-shadow: 0 2px 4px rgba(0,0,0,0.04); margin-bottom: 12px;">
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

# --- SAFE DATE PARSER & VECTORIZED ENGINE ---
def safe_parse_dt(val):
    if pd.isna(val) or not str(val).strip(): return pd.NaT
    s = str(val).strip()
    s_clean = re.sub(r'\s*/\s*', '/', s)
    s_clean = re.sub(r'\s*-\s*', '-', s_clean)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            dt = pd.to_datetime(s_clean, errors='coerce', utc=True)
            if pd.notna(dt): return dt.tz_convert(None)
        except Exception: pass
        try:
            dt = pd.to_datetime(s_clean, errors='coerce', dayfirst=True)
            if pd.notna(dt): return dt.tz_localize(None) if dt.tz is not None else dt
        except Exception: pass
    return pd.NaT

def calc_contract_execution_year(start_date_str):
    if not start_date_str or pd.isna(start_date_str) or str(start_date_str).strip() in ['', 'nan', 'None', 'N/A']:
        return "First year"
    st_dt = safe_parse_dt(start_date_str)
    if pd.isna(st_dt): return "First year"
    today = datetime.now()
    if today < st_dt: return "First year"
    years_diff = today.year - st_dt.year - ((today.month, today.day) < (st_dt.month, st_dt.day))
    yr_num = years_diff + 1
    word_map = {1: "First year", 2: "Second year", 3: "Third year", 4: "Fourth year", 5: "Fifth year", 6: "Sixth year", 7: "Seventh year", 8: "Eighth year", 9: "Ninth year", 10: "Tenth year"}
    return word_map.get(yr_num, f"Year {yr_num}")

def process_vectorized_dataframe(df):
    if df.empty: return df
    if 'Product code' in df.columns:
        df['Product code'] = df['Product code'].astype(str).str.replace(r'\.0$', '', regex=True).replace(['nan', 'None', '<NA>'], '')

    st_col = 'Starting date for contract execution (contact signature)'
    st_s = df.get(st_col, pd.Series('', index=df.index)).astype(str).str.replace(r'\s*[\/\-]\s*', '-', regex=True).str.strip()
    st_dts = pd.to_datetime(st_s, errors='coerce')
    df[st_col] = st_dts.dt.strftime('%Y-%m-%d').fillna('')

    v_yrs = pd.to_numeric(df.get('Validity Period (Years)', 1), errors='coerce').fillna(1).astype(int)
    df['Validity Period (Years)'] = v_yrs

    today = pd.Timestamp.now()
    st_valid = st_dts.notna() & (st_dts <= today)
    yrs = pd.Series(1, index=df.index)
    if st_valid.any():
        valid_starts = st_dts[st_valid]
        y_diff = today.year - valid_starts.dt.year
        m_adj = ((today.month < valid_starts.dt.month) | ((today.month == valid_starts.dt.month) & (today.day < valid_starts.dt.day))).astype(int)
        yrs.loc[st_valid] = (y_diff - m_adj + 1).clip(lower=1)

    word_map = {1: "First year", 2: "Second year", 3: "Third year", 4: "Fourth year", 5: "Fifth year", 6: "Sixth year", 7: "Seventh year", 8: "Eighth year", 9: "Ninth year", 10: "Tenth year"}
    df['Contract Execution Year'] = yrs.map(word_map).fillna("Year " + yrs.astype(str))
    df.loc[~st_valid, 'Contract Execution Year'] = "First year"

    calc_exp_list = [
        (s + pd.DateOffset(years=int(v))) - pd.Timedelta(days=1) if pd.notna(s) else pd.NaT 
        for s, v in zip(st_dts, v_yrs)
    ]
    exp_dts = pd.Series(calc_exp_list, index=df.index)
    df['Contract End Date (Expiry)'] = exp_dts.dt.strftime('%Y-%m-%d').fillna('')

    today_midnight = pd.Timestamp(today.date())
    days_to_exp = (exp_dts - today_midnight).dt.days
    days_past_exp = (today_midnight - exp_dts).dt.days

    df['Days_To_Expiry'] = days_to_exp
    df['Days_Past_Expiry'] = days_past_exp
    df['Days Expired'] = np.where(days_past_exp > 0, days_past_exp, np.where(exp_dts.notna(), 0, np.nan))

    df['Is_Red_Alert'] = (exp_dts.notna()) & (days_to_exp <= 90)
    df['Is_Yellow_Alert'] = (exp_dts.notna()) & (days_to_exp > 90) & (days_to_exp <= 180)

    conds = [exp_dts.isna(), days_to_exp < 0, days_to_exp <= 90, days_to_exp <= 180]
    choice_status = ["Missing Expiry Date", "Expired / Overdue", "Expiring in < 3 Months", "Expiring in 3–6 Months"]
    df['Expiry_Status_Cat'] = np.select(conds, choice_status, default="Valid (> 6 Months)")

    corpus = pd.Series("", index=df.index)
    for col in df.columns:
        if not col.startswith('_') and col not in ['id', 'Is_Red_Alert', 'Is_Yellow_Alert']:
            corpus = corpus + " " + df[col].fillna('').astype(str)
    df['_search_corpus'] = corpus.str.lower()
    df['_row_action'] = ""

    return df

# --- DIALOG 1: EMAIL ALERT WORKFLOW ---
@st.dialog("✉️ Compose & Send Email Alert", width="large")
def take_action_dialog(row_data):
    contract_id = int(row_data.get('id'))
    prod_desc = str(row_data.get('Product Description', row_data.get('Product description', 'N/A'))).strip()
    prod_code = str(row_data.get('Product code', 'N/A')).replace('.0', '').strip()
    supplier = str(row_data.get('Supplier', 'N/A')).strip()
    framework_ref = str(row_data.get('Ref/N° of Framework Agreement', 'N/A')).strip()
    
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
            if diff_days > 0: days_past = f"+{diff_days} days overdue"
            elif diff_days == 0: days_past = "Expires today"
            else: days_past = f"{abs(diff_days)} days remaining"

    st.markdown(f"**Item #:** `{contract_id}` | **Code:** `{prod_code}` | **Expiry Date:** `{expiry_date}` | **Status:** `{days_past}`")
    st.markdown(f"**Product:** `{prod_desc}`")
    st.divider()

    action_tab1, action_tab2, action_tab3 = st.tabs(["✉️ Compose Email Alert", "📁 Upload & Document Trail", "📜 Change History Trail"])

    with action_tab1:
        st.subheader("✉️ Compose Email Alert to RMS Team")
        rms_df = cached_get_rms_emails()
        email_options = rms_df['Email'].tolist() if not rms_df.empty else ["procurement@rms.rw", "logistics@rms.rw"]

        selected_recipients = st.multiselect("Select RMS Recipient(s)*", options=email_options, default=email_options[:1])
        custom_cc = st.text_input("Additional External CC Email(s) (comma separated)")
        email_subject = st.text_input("Email Subject*", value=f"[RMS Alert] Item #{contract_id}: {prod_desc[:35]}... (Expiry: {expiry_date})")

        default_body = f"""Dear RMS Team,

Please review the contract execution status for the following item:
- Product Code: {prod_code}
- Product Description: {prod_desc}
- Supplier: {supplier}
- Framework Ref: {framework_ref}
- Contract Expiry Date: {expiry_date}
- Status: {days_past}

Best regards,
RMS Procurement System"""

        email_body_text = st.text_area("Compose Email Message Body*", value=default_body, height=180, key=f"area_email_{contract_id}")

        st.markdown("### 📎 Email Attachments")
        existing_docs_df = db.get_row_documents(contract_id)
        selected_doc_ids = []
        if not existing_docs_df.empty:
            for _, d_row in existing_docs_df.iterrows():
                if st.checkbox(f"Doc #{d_row['Doc #']}: {d_row['File Name']} ({d_row['Uploaded By']})", key=f"att_chk_{d_row['id']}"):
                    selected_doc_ids.append(d_row['id'])

        new_att_files = st.file_uploader("Or attach new document(s)", accept_multiple_files=True, key=f"new_email_att_{contract_id}")

        smtp_host = os.getenv("SMTP_HOST", "smtp.office365.com")
        try: smtp_port = int(os.getenv("SMTP_PORT", 587))
        except: smtp_port = 587
        smtp_user = os.getenv("SMTP_USER", "alerts@rms.rw")
        smtp_pass = os.getenv("SMTP_PASSWORD", "")

        c_send, c_close = st.columns([3, 1])
        with c_send:
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

                    body_html = f"<pre style='font-family: sans-serif;'>{email_body_text}</pre>"
                    with st.spinner("Sending Email..."):
                        success, msg = send_email_smtp(smtp_host, smtp_port, smtp_user, smtp_pass, all_recipients, email_subject, body_html, attachments)
                        if success:
                            db.log_action(f"📧 Email alert sent for Item #{contract_id} to {', '.join(all_recipients)}")
                            st.session_state['_last_processed_signal'] = None
                            st.toast("Email sent successfully", icon="✅")
                            st.rerun()
                        else: st.error(msg)
        with c_close:
            if st.button("❌ Close", use_container_width=True, key=f"btn_close_email_{contract_id}"):
                st.session_state['_last_processed_signal'] = None
                st.rerun()

    with action_tab2:
        st.subheader("📁 Attached Documents & Upload Trail")
        uploader_name = st.text_input("Your Name / Officer Name*", value="Procurement Officer", key=f"uploader_name_field_{contract_id}")
        uploaded_files = st.file_uploader("Upload Document(s) for this line item", accept_multiple_files=True, key=f"tab_doc_uploader_{contract_id}")

        if st.button("⬆️ Upload & Assign Doc Numbers", key=f"btn_upload_doc_{contract_id}", type="primary"):
            if not uploader_name.strip(): st.error("Please enter your name to upload.")
            elif not uploaded_files: st.warning("Please select files first.")
            else:
                count = db.save_row_documents(contract_id, uploaded_files, uploader_name.strip())
                st.toast(f"✅ Successfully uploaded {count} document(s)!", icon="📁")
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
                        st.toast("🗑️ Document deleted successfully!", icon="🗑️")
                        st.rerun()

    with action_tab3:
        st.subheader("📜 Line Item Change History Trail")
        trail_df = db.get_row_change_trail(contract_id)
        if trail_df.empty: st.info("No cell modifications or document uploads recorded for this row yet.")
        else: st.dataframe(trail_df, use_container_width=True, hide_index=True)

# --- DIALOG 2: EDIT CONTRACT DETAILS ---
@st.dialog("✏️ Advanced Edit Contract Details", width="large")
def edit_contract_dialog(row_data):
    contract_id = int(row_data.get('id'))
    st.markdown(f"**Editing Contract Item #:** `{contract_id}`")
    
    raw_start = safe_parse_dt(row_data.get('Starting date for contract execution (contact signature)', ''))
    default_start = raw_start.date() if pd.notna(raw_start) else None

    try:
        current_validity = int(float(row_data.get('Validity Period (Years)', 1)))
    except Exception:
        current_validity = 1
    current_validity = max(1, min(50, current_validity))

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
            computed_year = calc_contract_execution_year(e_start.strftime('%Y-%m-%d') if e_start else "")
            st.text_input("Contract Execution Year (Auto)", value=computed_year, disabled=True)
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
        e_title = st.text_area("📝 Title of the Contract", value=val_title, height=70)

        val_desc = str(row_data.get('Product Description', row_data.get('Product description', '')))
        e_desc = st.text_area("📋 Product Description", value=val_desc, height=90)

        val_clean = str(row_data.get('CLEANING ACTION', ''))
        e_clean = st.text_area("💬 CLEANING ACTION / Notes", value=val_clean, height=70)

        f_save, f_close = st.columns([3, 1])
        with f_save:
            submit_clicked = st.form_submit_button("Save All Contract Changes", type="primary", use_container_width=True)
        with f_close:
            close_clicked = st.form_submit_button("❌ Close", use_container_width=True)

        if submit_clicked:
            start_date_formatted = e_start.strftime('%Y-%m-%d') if e_start else ""
            
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
                'Contract Execution Year': calc_contract_execution_year(start_date_formatted),
                'pack size': e_pack,
                'Incoterm': e_inco,
                'Category': e_cat,
                'Manufacturer and country of origin': e_morigin,
                'Delivey period': e_deliv,
                'Title of the contract': e_title,
                'Product Description': e_desc,
                'CLEANING ACTION': e_clean,
                'Starting date for contract execution (contact signature)': start_date_formatted,
                'Contract End Date (Expiry)': calc_new_exp
            }
            
            db.update_full_contract(contract_id, updated_fields, user_name="Admin Officer")
            
            if 'master_df' in st.session_state:
                m_df = st.session_state['master_df']
                mask = m_df['id'] == contract_id
                for k, v in updated_fields.items():
                    if k in m_df.columns:
                        m_df.loc[mask, k] = v
                
                if calc_new_exp:
                    exp_dt = pd.to_datetime(calc_new_exp)
                    today_midnight = pd.Timestamp(datetime.now().date())
                    days_to_exp = (exp_dt - today_midnight).days
                    days_past_exp = (today_midnight - exp_dt).days
                    
                    m_df.loc[mask, 'Days_To_Expiry'] = days_to_exp
                    m_df.loc[mask, 'Days_Past_Expiry'] = days_past_exp
                    m_df.loc[mask, 'Days Expired'] = days_past_exp if days_past_exp > 0 else 0
                    m_df.loc[mask, 'Is_Red_Alert'] = days_to_exp <= 90
                    m_df.loc[mask, 'Is_Yellow_Alert'] = (days_to_exp > 90) and (days_to_exp <= 180)
                    
                    if days_to_exp < 0: cat_val = "Expired / Overdue"
                    elif days_to_exp <= 90: cat_val = "Expiring in < 3 Months"
                    elif days_to_exp <= 180: cat_val = "Expiring in 3–6 Months"
                    else: cat_val = "Valid (> 6 Months)"
                    m_df.loc[mask, 'Expiry_Status_Cat'] = cat_val

            st.session_state['_last_processed_signal'] = None
            invalidate_master_cache()
            st.toast("Contract details updated", icon="✅")
            st.rerun()

        if close_clicked:
            st.session_state['_last_processed_signal'] = None
            st.rerun()

# --- DIALOG 3: CONFIRM DELETE CONTRACT ITEM ---
@st.dialog("🗑️ Confirm Delete Contract Item", width="medium")
def delete_contract_dialog(row_data):
    contract_id = int(row_data.get('id'))
    prod_desc = str(row_data.get('Product Description', row_data.get('Product description', 'N/A'))).strip()
    prod_code = str(row_data.get('Product code', 'N/A')).replace('.0', '').strip()
    supplier = str(row_data.get('Supplier', 'N/A')).strip()

    st.warning(f"⚠️ Are you sure you want to permanently delete Contract Item #{contract_id}?")
    st.markdown(f"**Product Code:** `{prod_code}` | **Supplier:** `{supplier}`")
    st.markdown(f"**Description:** {prod_desc}")

    deleter_name = st.text_input("Your Name / Officer Name*", value="Admin Officer", key=f"deleter_name_field_{contract_id}")

    c_del, c_close = st.columns([2, 1])
    with c_del:
        if st.button("🚨 Yes, Delete Permanently", type="primary", use_container_width=True, key=f"btn_confirm_del_{contract_id}"):
            if not deleter_name.strip():
                st.error("Please enter your name to confirm deletion.")
            else:
                db.delete_contract(contract_id, user_name=deleter_name.strip())
                st.session_state['_last_processed_signal'] = None
                invalidate_master_cache()
                st.toast(f"Contract Item #{contract_id} deleted", icon="🗑️")
                st.rerun()
    with c_close:
        if st.button("Cancel", use_container_width=True, key=f"btn_cancel_del_{contract_id}"):
            st.session_state['_last_processed_signal'] = None
            st.rerun()

# --- HEADER & BRANDING ---
c_logo, c_title = st.columns([1, 12])
with c_logo:
    if os.path.exists("logo.jpg"): st.image("logo.jpg", width=75)
    else: st.markdown("<h2 style='margin:0;'>🏢</h2>", unsafe_allow_html=True)
with c_title:
    st.markdown("<div class='custom-title'>RMS CONTRACT MASTER</div>", unsafe_allow_html=True)
    st.markdown("<div class='custom-subtitle'>Rwanda Medical Supply Ltd - Contract Execution, Document Trail & Expiry Portal</div>", unsafe_allow_html=True)

# --- NAVIGATION TABS ---
tab_tracker, tab_emails, tab_import, tab_logs = st.tabs([
    "📊 Master Contract Tracker", 
    "📧 RMS Email Directory", 
    "📂 Import Excel Master", 
    "📝 System Audit Trail"
])

# ==========================================
# FRAGMENT: ISOLATED HIGH-SPEED GRID RENDERER
# ==========================================
@st.fragment
def render_tracker_grid(category_filter, status_filter, search_query):
    
    # 1. SINGLE-USE POP TRIGGER: Invokes dialog and immediately removes trigger from session memory
    if st.session_state.get('pending_dialog'):
        cmd, target_row = st.session_state.pop('pending_dialog')
        if cmd == 'EMAIL':
            take_action_dialog(target_row)
        elif cmd == 'EDIT':
            edit_contract_dialog(target_row)
        elif cmd == 'DELETE':
            delete_contract_dialog(target_row)

    if 'master_df' not in st.session_state or st.session_state.get('needs_db_reload', False):
        st.session_state['master_df'] = cached_load_and_process_master()
        st.session_state['needs_db_reload'] = False

    df = st.session_state['master_df']

    # 2. CHEAPER SINGLE-MASK MULTI-KEYWORD SEARCH
    search_clean = str(search_query).strip().lower() if search_query else ""
    if search_clean and '_search_corpus' in df.columns:
        terms = [t.strip() for t in search_clean.split() if t.strip()]
        if terms:
            mask = pd.Series(True, index=df.index)
            for term in terms:
                mask &= df['_search_corpus'].str.contains(term, regex=False, na=False)
            df = df[mask]

    if category_filter and category_filter != "All":
        df = df[df['Category'] == category_filter]

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

    # KPI SUMMARY CARDS
    k1, k2, k3, k4 = st.columns(4)
    with k1: st.markdown(create_kpi_card("Total Line Items", total_count, "#f1f5f9", "#1e293b", "#cbd5e1", "📊"), unsafe_allow_html=True)
    with k2: st.markdown(create_kpi_card("Valid (> 6 Months)", valid_count, "#dcfce7", "#166534", "#86efac", "✅"), unsafe_allow_html=True)
    with k3: st.markdown(create_kpi_card("Expiring in 3–6 Months", yellow_count, "#fef3c7", "#854d0e", "#fde047", "⚠️"), unsafe_allow_html=True)
    with k4: st.markdown(create_kpi_card("Expiring < 3 Months / Expired", red_count, "#fee2e2", "#991b1b", "#fca5a5", "🚨"), unsafe_allow_html=True)

    # AMPLE VERTICAL SPACE BETWEEN KPI CARDS AND CONTROL BUTTON BAR
    st.markdown("<div style='height: 24px; width: 100%; clear: both;'></div>", unsafe_allow_html=True)

    # CONTROL BUTTON BAR ALIGNED ON A SINGLE HORIZONTAL BASELINE
    ctrl_col1, ctrl_col2, ctrl_col3, ctrl_col4 = st.columns([2.5, 2.5, 3.5, 3.5], vertical_alignment="center")

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
        'Contract Execution Year',
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
    extra_cols = [c for c in df.columns if c not in preferred_col_order and not c.startswith('_') and c not in ['id', 'NO', 'no', 'item_no', 'classification', 'Classification', 'end_user', 'Demandor (End user)', 'budget_holder', 'Budget Holder', 'Days_To_Expiry', 'Days_Past_Expiry', 'Is_Red_Alert', 'Is_Yellow_Alert', 'Expiry_Status_Cat', 'contract_title', 'Answer', 'answer']]
    all_available_cols = existing_cols + extra_cols
    
    with ctrl_col1:
        with st.popover("👁️ Select Columns", use_container_width=True):
            st.markdown("**Check/Uncheck Columns to Show in Table:**")
            selected_display_cols = st.multiselect(
                "Visible Columns:",
                options=all_available_cols,
                default=all_available_cols
            )

    with ctrl_col2:
        with st.popover("➕ Add Custom Column", use_container_width=True):
            st.markdown("**Add a New Column to the Database:**")
            new_col_name = st.text_input("New Column Header")
            if st.button("Save New Column", type="primary", use_container_width=True):
                if new_col_name.strip():
                    ok, msg = db.add_custom_column(new_col_name.strip())
                    if ok:
                        st.success(msg)
                        invalidate_master_cache()
                        st.rerun()
                    else:
                        st.error(msg)

    with ctrl_col3:
        save_grid_btn = st.button("💾 Save All Grid Changes", type="primary", use_container_width=True)

    with ctrl_col4:
        if not df.empty:
            export_df = df[[c for c in selected_display_cols if c in df.columns]].copy()
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                export_df.to_excel(writer, index=False, sheet_name='Contracts')
            
            st.download_button(
                label="📥 Export View to Excel",
                data=excel_buffer.getvalue(),
                file_name=f"RMS_Contracts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

    st.markdown("""
        <div style="background-color: #ffffff; padding: 8px 12px; border-radius: 8px; border: 1px solid #e2e8f0; margin-top: 4px; margin-bottom: 6px; display: flex; align-items: center; gap: 15px; font-size: 13px; flex-wrap: wrap;">
            <strong>🎨 Legend:</strong>
            <span><span style="background-color: #fee2e2; color: #991b1b; padding: 3px 8px; border-radius: 4px; font-weight: bold; border: 1px solid #fca5a5;">🚨 Soft Red Row</span> Expiring in &lt; 3 Months or Expired</span>
            <span><span style="background-color: #fef3c7; color: #854d0e; padding: 3px 8px; border-radius: 4px; font-weight: bold; border: 1px solid #fde047;">⚠️ Soft Yellow Row</span> Expiring in 3 to 6 Months</span>
            <span><span style="background-color: #ffffff; color: #334155; padding: 3px 8px; border-radius: 4px; border: 1px solid #cbd5e1;">⚪ White / 🩶 Light Gray</span> Active / Valid (&gt; 6 Months)</span>
        </div>
    """, unsafe_allow_html=True)

    if df.empty:
        st.warning("No contract items found matching your search query or filter.")
    else:
        df['_row_num'] = 0
        
        metadata_cols = ['_row_action', '_row_num', 'id', 'Days_To_Expiry', 'Days_Past_Expiry', 'Is_Red_Alert', 'Is_Yellow_Alert']
        user_cols = [c for c in selected_display_cols if c in df.columns and c not in metadata_cols]
        cols_to_render = metadata_cols + user_cols
        
        df_display = df[cols_to_render].copy()
        df_display = df_display.loc[:, ~df_display.columns.duplicated()]

        gb = GridOptionsBuilder.from_dataframe(df_display)
        
        gb.configure_column('id', hide=True)
        gb.configure_column('Days_To_Expiry', hide=True)
        gb.configure_column('Days_Past_Expiry', hide=True)
        gb.configure_column('Is_Red_Alert', hide=True)
        gb.configure_column('Is_Yellow_Alert', hide=True)

        # COMPACT ROW NUMBER COLUMN (COMPACT WIDTH FIT UP TO 10000 ROWS)
        gb.configure_column('_row_num', header_name='#', headerTooltip='Row Number', width=48, minWidth=45, maxWidth=55, pinned='left', editable=False, valueGetter="node.rowIndex + 1", type=['numericColumn'])

        # BULLETPROOF JS EVENT DISPATCHER WITH FORCED cellValueChanged EVENT
        js_quick_actions_renderer = JsCode("""
        class QuickActionsRenderer {
            init(params) {
                this.eGui = document.createElement('div');
                this.eGui.style.display = 'flex';
                this.eGui.style.gap = '6px';
                this.eGui.style.alignItems = 'center';
                this.eGui.style.height = '100%';
                this.eGui.style.width = '100%';

                this.eGui.innerHTML = `
                    <button class="act-btn" style="background:#1e3c72;color:white;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:11px;font-weight:bold;white-space:nowrap;">✉️ Email</button>
                    <button class="edt-btn" style="background:#2a5298;color:white;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:11px;font-weight:bold;white-space:nowrap;">✏️ Edit</button>
                    <button class="del-btn" style="background:#dc2626;color:white;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:11px;font-weight:bold;white-space:nowrap;">🗑️ Delete</button>
                `;

                const fireSignal = (cmd, id) => {
                    let sig = cmd + ':' + id + ':' + Date.now();
                    params.node.setDataValue('_row_action', sig);
                    params.api.dispatchEvent({
                        type: 'cellValueChanged',
                        node: params.node,
                        column: params.column,
                        colDef: params.colDef,
                        oldValue: '',
                        newValue: sig
                    });
                };

                this.eGui.querySelector('.act-btn').addEventListener('click', (e) => {
                    e.stopPropagation();
                    fireSignal('EMAIL', params.data.id);
                });

                this.eGui.querySelector('.edt-btn').addEventListener('click', (e) => {
                    e.stopPropagation();
                    fireSignal('EDIT', params.data.id);
                });

                this.eGui.querySelector('.del-btn').addEventListener('click', (e) => {
                    e.stopPropagation();
                    fireSignal('DELETE', params.data.id);
                });
            }
            getGui() { return this.eGui; }
        }
        """)

        gb.configure_column('_row_action', header_name='⚡ Row Actions', headerTooltip='Row Actions (Email, Edit, Delete)', width=250, minWidth=240, pinned='left', editable=True, cellRenderer=js_quick_actions_renderer)

        gb.configure_default_column(
            wrapText=False,
            autoHeight=False,
            resizable=True,
            filter=True,
            sortable=True,
            editable=True,
            minWidth=140
        )

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
            getGui() { return this.eGui; }
        }
        """)

        for col in df_display.columns:
            if col not in ['_row_action', '_row_num', 'id', 'Days_To_Expiry', 'Days_Past_Expiry', 'Is_Red_Alert', 'Is_Yellow_Alert']:
                gb.configure_column(col, headerTooltip=str(col))

        if 'Product code' in df_display.columns:
            gb.configure_column('Product code', headerTooltip='Product code', width=160, minWidth=130, type=['stringColumn'], cellDataType='text')

        if 'Product Description' in df_display.columns:
            gb.configure_column('Product Description', headerTooltip='Product Description', width=450, minWidth=300, cellRenderer=two_line_clamp_renderer)
        
        if 'Title of the contract' in df_display.columns:
            gb.configure_column('Title of the contract', headerTooltip='Title of the contract', width=450, minWidth=300, cellRenderer=two_line_clamp_renderer)

        if 'Ref/N° of Framework Agreement' in df_display.columns:
            gb.configure_column('Ref/N° of Framework Agreement', headerTooltip='Ref/N° of Framework Agreement', width=260, minWidth=180)

        if 'Supplier' in df_display.columns:
            gb.configure_column('Supplier', headerTooltip='Supplier', width=220, minWidth=160)

        # STRICT NUMERIC VALIDATION: ONLY NUMBERS ALLOWED
        if 'Validity Period (Years)' in df_display.columns:
            gb.configure_column(
                'Validity Period (Years)', 
                header_name='Validity Period (Years)', 
                headerTooltip='Validity Period (Years)', 
                width=150, 
                minWidth=130, 
                editable=True, 
                type=['numericColumn'], 
                cellEditor='agNumberCellEditor', 
                cellEditorParams={'min': 1, 'max': 50, 'precision': 0}
            )

        if 'Unit price' in df_display.columns:
            gb.configure_column(
                'Unit price', 
                header_name='Unit price', 
                headerTooltip='Unit price', 
                width=140, 
                minWidth=110, 
                editable=True, 
                type=['numericColumn'], 
                cellEditor='agNumberCellEditor', 
                cellEditorParams={'min': 0, 'precision': 2}
            )

        # STRICT DATE VALIDATION VIA HTML5 DATE PICKER
        custom_date_editor = JsCode("class DatePickerEditor { init(params) { this.eInput = document.createElement('input'); this.eInput.type = 'date'; this.eInput.value = params.value || ''; this.eInput.style.width = '100%'; this.eInput.style.height = '100%'; } getGui() { return this.eInput; } afterGuiAttached() { this.eInput.focus(); } getValue() { return this.eInput.value; } }")

        if 'Starting date for contract execution (contact signature)' in df_display.columns:
            gb.configure_column('Starting date for contract execution (contact signature)', width=180, minWidth=150, editable=True, cellEditor=custom_date_editor)

        if 'Contract End Date (Expiry)' in df_display.columns:
            gb.configure_column('Contract End Date (Expiry)', header_name='Contract End Date (Expiry)', headerTooltip='Contract End Date (Expiry)', width=180, minWidth=160, editable=True, cellEditor=custom_date_editor)

        if 'Contract Execution Year' in df_display.columns:
            gb.configure_column('Contract Execution Year', header_name='Contract Execution Year', headerTooltip='Contract Execution Year', width=180, minWidth=150, editable=True)

        if 'Days Expired' in df_display.columns:
            gb.configure_column('Days Expired', header_name='Days Expired', headerTooltip='Days Expired', width=140, minWidth=120, editable=False, type=['numericColumn'])
        
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
                if (!params.data || params.data.Days_To_Expiry === undefined || params.data.Days_To_Expiry === null) {
                    this.eGui.innerHTML = '<span style="color: #a0aec0;">-</span>';
                    return;
                }
                let daysToExpiry = params.data.Days_To_Expiry;
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
            getGui() { return this.eGui; }
        }
        """)

        if 'Days Past Expiry' in df_display.columns:
            gb.configure_column('Days Past Expiry', header_name='Days Past Expiry', headerTooltip='Days Past Expiry Status', width=170, minWidth=150, editable=False, cellRenderer=days_past_renderer)

        # INSTANT CLIENT-SIDE JS AUTO-CALCULATION UPON CELL CHANGE (0ms RECOMPUTE)
        js_cell_value_changed_handler = JsCode("""
        function(params) {
            if (!params.data) return;
            let colId = params.column.getColId();
            
            if (colId === 'Starting date for contract execution (contact signature)' || colId === 'Validity Period (Years)') {
                let startStr = params.data['Starting date for contract execution (contact signature)'];
                let vYrs = parseInt(params.data['Validity Period (Years)'], 10);
                if (isNaN(vYrs) || vYrs < 1) vYrs = 1;
                
                if (startStr && startStr.trim() !== '' && startStr.toLowerCase() !== 'nan') {
                    let parts = startStr.split('-');
                    let sDate = null;
                    if (parts.length === 3) {
                        sDate = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
                    } else {
                        sDate = new Date(startStr);
                    }
                    
                    if (sDate && !isNaN(sDate.getTime())) {
                        let expDate = new Date(sDate);
                        expDate.setFullYear(expDate.getFullYear() + vYrs);
                        expDate.setDate(expDate.getDate() - 1);
                        
                        let yyyy = expDate.getFullYear();
                        let mm = String(expDate.getMonth() + 1).padStart(2, '0');
                        let dd = String(expDate.getDate()).padStart(2, '0');
                        let expStr = yyyy + '-' + mm + '-' + dd;
                        
                        params.node.setDataValue('Contract End Date (Expiry)', expStr);
                        
                        let today = new Date();
                        today.setHours(0,0,0,0);
                        let yrText = 'First year';
                        if (today >= sDate) {
                            let yearsDiff = today.getFullYear() - sDate.getFullYear();
                            let mDiff = today.getMonth() - sDate.getMonth();
                            if (mDiff < 0 || (mDiff === 0 && today.getDate() < sDate.getDate())) {
                                yearsDiff--;
                            }
                            let yrNum = yearsDiff + 1;
                            let wordMap = {1:'First year', 2:'Second year', 3:'Third year', 4:'Fourth year', 5:'Fifth year', 6:'Sixth year', 7:'Seventh year', 8:'Eighth year', 9:'Ninth year', 10:'Tenth year'};
                            yrText = wordMap[yrNum] || ('Year ' + yrNum);
                        }
                        params.node.setDataValue('Contract Execution Year', yrText);
                        
                        let diffTime = expDate.getTime() - today.getTime();
                        let diffDays = Math.round(diffTime / (1000 * 3600 * 24));
                        
                        params.node.setDataValue('Days_To_Expiry', diffDays);
                        params.node.setDataValue('Days_Past_Expiry', -diffDays);
                        params.node.setDataValue('Days Expired', diffDays < 0 ? -diffDays : 0);
                        params.node.setDataValue('Is_Red_Alert', diffDays <= 90);
                        params.node.setDataValue('Is_Yellow_Alert', diffDays > 90 && diffDays <= 180);
                    }
                }
            }
            if (params.api) {
                params.api.redrawRows({ rowNodes: [params.node] });
            }
        }
        """)

        gb.configure_grid_options(
            suppressLoadingOverlay=True,
            rowHeight=48,
            singleClickEdit=True,
            rowBuffer=10,
            onCellValueChanged=js_cell_value_changed_handler,
            getRowStyle=JsCode("""
            function(params) {
                if (!params.data) return null;
                if (params.data.Is_Red_Alert) {
                    return {'backgroundColor': '#fee2e2', 'color': '#991b1b', 'fontWeight': 'bold'};
                }
                if (params.data.Is_Yellow_Alert) {
                    return {'backgroundColor': '#fef3c7', 'color': '#854d0e', 'fontWeight': 'bold'};
                }
                return params.node.rowIndex % 2 === 0 ? {'backgroundColor': '#ffffff'} : {'backgroundColor': '#f8fafc'};
            }
            """)
        )

        custom_header_css = {
            ".ag-header": {
                "background": "linear-gradient(90deg, #1e3c72 0%, #2a5298 100%) !important",
                "border-bottom": "2px solid #1e3c72 !important"
            },
            ".ag-header-cell": {
                "background-color": "transparent !important",
                "color": "#ffffff !important",
                "font-weight": "bold !important",
                "font-size": "13px !important",
                "border-right": "1px solid rgba(255, 255, 255, 0.15) !important"
            },
            ".ag-header-cell-label, .ag-header-cell-text, .ag-header-icon, .ag-icon": {
                "color": "#ffffff !important",
                "font-weight": "bold !important"
            }
        }

        grid_key = "rms_contract_master_aggrid_static_table"

        grid_options = gb.build()
        grid_response = AgGrid(
            df_display,
            gridOptions=grid_options,
            update_on=['cellValueChanged'],
            data_return_mode=DataReturnMode.AS_INPUT,
            theme='streamlit',
            height=580,
            custom_css=custom_header_css,
            allow_unsafe_jscode=True,
            key=grid_key
        )

        button_action_triggered = False

        if '_last_processed_signal' not in st.session_state:
            st.session_state['_last_processed_signal'] = None

        if 'data' in grid_response and grid_response['data'] is not None:
            edited_df = grid_response['data']
            if isinstance(edited_df, pd.DataFrame) and not edited_df.empty and '_row_action' in edited_df.columns:
                act_vals = edited_df['_row_action'].values
                valid_signals = [s for s in act_vals if s and isinstance(s, str) and ':' in s]
                
                if valid_signals:
                    latest_signal = max(
                        valid_signals, 
                        key=lambda s: int(s.split(':')[2]) if len(s.split(':')) > 2 and s.split(':')[2].isdigit() else 0
                    )
                    
                    if st.session_state['_last_processed_signal'] != latest_signal:
                        st.session_state['_last_processed_signal'] = latest_signal
                        
                        parts = str(latest_signal).split(':')
                        cmd = parts[0].upper()
                        target_id = int(parts[1]) if len(parts) > 1 else None

                        if target_id is not None:
                            target_matches = df[df['id'] == target_id]
                            if not target_matches.empty:
                                target_row = target_matches.iloc[0].to_dict()
                                target_row['id'] = target_id
                                button_action_triggered = True
                                
                                if 'master_df' in st.session_state:
                                    st.session_state['master_df']['_row_action'] = ""
                                
                                st.session_state['pending_dialog'] = (cmd, target_row)
                                st.rerun()

        # AUTOMATIC INSTANT SQLITE SYNC IN BACKGROUND (PERMANENT SAVE ON EVERY CELL EDIT)
        if not button_action_triggered and 'data' in grid_response and grid_response['data'] is not None:
            edited_df = grid_response['data']
            if isinstance(edited_df, pd.DataFrame) and not edited_df.empty and 'id' in edited_df.columns:
                valid_edited = edited_df[edited_df['id'].notna()].copy()
                valid_edited['id'] = valid_edited['id'].astype(int)
                
                skip_cols = {'id', '_row_action', '_row_num', 'Days_To_Expiry', 'Days_Past_Expiry', 'Days Expired', 'Is_Red_Alert', 'Is_Yellow_Alert', 'Expiry_Status_Cat', '_selectedRowNodeInfo', '_search_corpus'}
                compare_cols = [c for c in valid_edited.columns if c in df.columns and c not in skip_cols]
                
                if compare_cols:
                    master_ref = st.session_state['master_df']
                    old_indexed = master_ref.set_index('id')[compare_cols].fillna('').astype(str)
                    new_indexed = valid_edited.set_index('id')[compare_cols].fillna('').astype(str)
                    
                    common_ids = old_indexed.index.intersection(new_indexed.index)
                    if not common_ids.empty:
                        old_sub = old_indexed.loc[common_ids]
                        new_sub = new_indexed.loc[common_ids]
                        
                        diff_matrix = (old_sub != new_sub)
                        if diff_matrix.values.any():
                            changed_rows = diff_matrix.any(axis=1)
                            changed_ids = common_ids[changed_rows]
                            
                            for db_id in changed_ids:
                                row_diff = diff_matrix.loc[db_id]
                                changed_col_names = row_diff[row_diff].index
                                for ui_col in changed_col_names:
                                    db_col = db.get_db_col_name(ui_col)
                                    old_val = old_sub.loc[db_id, ui_col].strip()
                                    new_val = new_sub.loc[db_id, ui_col].strip()
                                    if old_val != new_val:
                                        db.update_single_cell(int(db_id), db_col, new_val, user_name="Admin Officer")
                                        mask_id = master_ref['id'] == int(db_id)
                                        
                                        try:
                                            if pd.api.types.is_integer_dtype(master_ref[ui_col]):
                                                master_ref.loc[mask_id, ui_col] = int(float(new_val)) if new_val.strip() else 0
                                            elif pd.api.types.is_float_dtype(master_ref[ui_col]):
                                                master_ref.loc[mask_id, ui_col] = float(new_val) if new_val.strip() else 0.0
                                            else:
                                                master_ref.loc[mask_id, ui_col] = str(new_val)
                                        except Exception:
                                            master_ref.loc[mask_id, ui_col] = str(new_val)

                                        if ui_col in ['Starting date for contract execution (contact signature)', 'Validity Period (Years)', 'Contract End Date (Expiry)']:
                                            row_st = str(master_ref.loc[mask_id, 'Starting date for contract execution (contact signature)'].values[0])
                                            row_v = str(master_ref.loc[mask_id, 'Validity Period (Years)'].values[0])
                                            try: v_num = int(float(row_v))
                                            except: v_num = 1
                                            
                                            st_dt_parsed = safe_parse_dt(row_st)
                                            if pd.notna(st_dt_parsed):
                                                new_exp_dt = (st_dt_parsed + pd.DateOffset(years=v_num) - pd.Timedelta(days=1))
                                                new_exp_str = new_exp_dt.strftime('%Y-%m-%d')
                                                master_ref.loc[mask_id, 'Contract End Date (Expiry)'] = new_exp_str
                                                db.update_single_cell(int(db_id), 'Contract End Date (Expiry)', new_exp_str, user_name="System Auto")
                                            
                                            new_exec_yr = calc_contract_execution_year(row_st)
                                            master_ref.loc[mask_id, 'Contract Execution Year'] = new_exec_yr
                                            db.update_single_cell(int(db_id), 'Contract Execution Year', new_exec_yr, user_name="System Auto")
                                            
                                            exp_str_val = str(master_ref.loc[mask_id, 'Contract End Date (Expiry)'].values[0])
                                            exp_dt_p = safe_parse_dt(exp_str_val)
                                            if pd.notna(exp_dt_p):
                                                today_m = pd.Timestamp(datetime.now().date())
                                                days_to = (exp_dt_p - today_m).days
                                                days_past = (today_m - exp_dt_p).days
                                                master_ref.loc[mask_id, 'Days_To_Expiry'] = days_to
                                                master_ref.loc[mask_id, 'Days_Past_Expiry'] = days_past
                                                master_ref.loc[mask_id, 'Days Expired'] = days_past if days_past > 0 else 0
                                                master_ref.loc[mask_id, 'Is_Red_Alert'] = days_to <= 90
                                                master_ref.loc[mask_id, 'Is_Yellow_Alert'] = (days_to > 90) and (days_to <= 180)
                                                
                                                if days_to < 0: cat_val = "Expired / Overdue"
                                                elif days_to <= 90: cat_val = "Expiring in < 3 Months"
                                                elif days_to <= 180: cat_val = "Expiring in 3–6 Months"
                                                else: cat_val = "Valid (> 6 Months)"
                                                master_ref.loc[mask_id, 'Expiry_Status_Cat'] = cat_val

                            cached_load_and_process_master.clear()

        # EXPLICIT BULK SAVE BACKUP BUTTON HANDLER
        if save_grid_btn:
            invalidate_master_cache()
            st.toast("✅ All grid changes committed to database!", icon="💾")

# ==========================================
# TAB 1: MASTER CONTRACT TRACKER
# ==========================================
with tab_tracker:
    s_col1, s_col2, s_col3 = st.columns([3, 1.2, 1.5])
    with s_col1:
        search_query = st.text_input("🔍 Search Description, Code, Supplier, Manufacturer, Ref #, Officer, Category, or Title...", placeholder="e.g. Paracetamol, Hetero, AUROLAB, 144/G/IRT, Cecile...")
    with s_col2:
        cat_options = cached_get_categories()
        category_filter = st.selectbox("Filter Sheet / Category", cat_options, index=0)
    with s_col3:
        status_filter = st.selectbox("Filter Expiry Status", [
            "All Expiry Statuses",
            "🚨 Expired / Overdue",
            "🚨 Expiring in < 3 Months",
            "⚠️ Expiring in 3–6 Months",
            "✅ Valid (> 6 Months)",
            "⏳ Missing Expiry Date"
        ], index=0)

    if 'master_df' not in st.session_state or st.session_state.get('needs_db_reload', True):
        st.session_state['master_df'] = cached_load_and_process_master()
        st.session_state['needs_db_reload'] = False

    render_tracker_grid(category_filter, status_filter, search_query)

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
                    if ok:
                        cached_get_rms_emails.clear()
                        st.success(msg)
                    else: st.error(msg)
                    st.rerun()

    with c2:
        st.markdown("### 📋 Registered RMS Directory")
        rms_emails_df = cached_get_rms_emails()
        if rms_emails_df.empty: st.info("No RMS emails registered yet.")
        else:
            for _, erow in rms_emails_df.iterrows():
                ec1, ec2, ec3 = st.columns([3, 3, 1])
                with ec1: st.markdown(f"**{erow['Name']}** ({erow['Department']})")
                with ec2: st.markdown(f"`{erow['Email']}`")
                with ec3:
                    if st.button("🗑️", key=f"del_email_{erow['ID']}"):
                        db.delete_rms_email(erow['ID'])
                        cached_get_rms_emails.clear()
                        st.rerun()

# ==========================================
# TAB 3: IMPORT EXCEL MASTER
# ==========================================
with tab_import:
    st.subheader("📂 Import / Reload Master Excel Workbook")
    st.markdown("Upload your **CONTRACT MASTER LIST.xlsx** file containing sheets: `Medicines`, `Consumables`, `Laboratory`, `IMPLANTS_`.")

    uploaded_excel = st.file_uploader("Upload Contract Master Excel File", type=["xlsx", "xls"])
    if uploaded_excel and st.button("Process & Import Workbook", type="primary"):
        filename = str(uploaded_excel.name).lower()
        if not (filename.endswith('.xlsx') or filename.endswith('.xls')):
            st.error("Invalid file type. Please upload a valid Microsoft Excel file (.xlsx or .xls).")
        else:
            with st.spinner("Processing sheets and updating SQLite database..."):
                try:
                    success, result = db.import_excel_master(uploaded_excel)
                    if success:
                        invalidate_master_cache()
                        st.success(f"Successfully imported {result} items across all sheets!")
                        st.rerun()
                    else:
                        st.error(f"Import Failed: {result}")
                except Exception as e:
                    st.error("Failed to process file. Please ensure you are uploading a valid, uncorrupted Excel (.xlsx or .xls) workbook.")

# ==========================================
# TAB 4: SYSTEM AUDIT TRAIL
# ==========================================
with tab_logs:
    st.subheader("📝 Global System Logs & Activity History")
    global_logs_df = db.get_global_logs()
    st.dataframe(global_logs_df, use_container_width=True, hide_index=True)