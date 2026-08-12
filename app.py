import streamlit as st
import pandas as pd
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

# --- TIGHT CUSTOM CSS (ELIMINATES BLANK GAP BELOW TITLE) ---
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

# --- SAFE DATE PARSER (HANDLES USER EDITS & SPACES CLEANLY) ---
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
    prod_desc = row_data.get('Product Description', row_data.get('Product description', 'N/A'))
    prod_code = str(row_data.get('Product code', 'N/A')).replace('.0', '')
    supplier = row_data.get('Supplier', 'N/A')
    framework_ref = row_data.get('Ref/N° of Framework Agreement', 'N/A')
    expiry_date = row_data.get('Contract End Date (Expiry)', 'N/A')
    days_past = row_data.get('Days Past Expiry', 'N/A')

    st.markdown(f"**Item #:** `{contract_id}` | **Code:** `{prod_code}` | **Expiry Date:** `{expiry_date}` | **Days Past Expiry:** `{days_past}`")
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
            <li><b>Days Past Expiry:</b> {days_past}</li>
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

        with st.expander("⚙️ SMTP Settings", expanded=False):
            smtp_host = st.text_input("SMTP Server", value="smtp.gmail.com")
            smtp_port = st.number_input("SMTP Port", value=587)
            smtp_user = st.text_input("Sender Email", value="alerts@rms.rw")
            smtp_pass = st.text_input("Sender Password", type="password")

        if st.button("✉️ Send Email Alert Now", type="primary", use_container_width=True):
            all_recipients = selected_recipients.copy()
            if custom_cc.strip():
                all_recipients.extend([e.strip() for e in custom_cc.split(",") if e.strip()])

            if not all_recipients: st.error("Please select at least one recipient email.")
            elif not smtp_user or not smtp_pass: st.error("Please enter SMTP credentials.")
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

# --- DIALOG 2: EDIT CONTRACT DETAILS (ADVANCED RICH-TEXT EDITOR FOR ALL TEXT FIELDS) ---
@st.dialog("✏️ Advanced Edit Contract Details", width="large")
def edit_contract_dialog(row_data):
    contract_id = int(row_data.get('id'))
    st.markdown(f"**Editing Contract Item #:** `{contract_id}`")
    
    raw_start = safe_parse_dt(row_data.get('Starting date for contract execution (contact signature)', ''))
    default_start = raw_start.date() if pd.notna(raw_start) else None

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
            e_enduser = st.text_input("Demandor (End user)", value=str(row_data.get('Demandor (End user)', '')))

        c_extra1, c_extra2, c_extra3 = st.columns(3)
        with c_extra1:
            e_pack = st.text_input("Pack Size", value=str(row_data.get('pack size', '')))
        with c_extra2:
            e_class = st.text_input("General medicines/Specialised/Oncology", value=str(row_data.get('General medicines/Specialised/Oncology', '')))
        with c_extra3:
            e_inco = st.text_input("Incoterm", value=str(row_data.get('Incoterm', '')))

        st.markdown("### 📝 Title of the Contract (Rich-Text Editor)")
        val_title = str(row_data.get('Title of the contract', ''))
        e_title = st_quill(value=val_title, placeholder="Write contract title...", html=True, key=f"quill_edit_title_{contract_id}")

        st.markdown("### 📋 Product Description (Rich-Text Editor)")
        val_desc = str(row_data.get('Product Description', row_data.get('Product description', '')))
        e_desc = st_quill(value=val_desc, placeholder="Write product description...", html=True, key=f"quill_edit_desc_{contract_id}")

        st.markdown("### 💬 CLEANING ACTION / Notes (Rich-Text Editor)")
        val_clean = str(row_data.get('CLEANING ACTION', ''))
        e_clean = st_quill(value=val_clean, placeholder="Write notes / cleaning action...", html=True, key=f"quill_edit_clean_{contract_id}")

        if st.form_submit_button("Save All Contract Changes", type="primary", use_container_width=True):
            updated_fields = {
                'Product code': e_code,
                'Supplier': e_supp,
                'Ref/N° of Framework Agreement': e_fw,
                'PROCUREMENT OFFICER': e_off,
                'Unit price': e_uprice,
                'Currency': e_curr,
                'Demandor (End user)': e_enduser,
                'pack size': e_pack,
                'General medicines/Specialised/Oncology': e_class,
                'Incoterm': e_inco,
                'Title of the contract': e_title,
                'Product Description': e_desc,
                'CLEANING ACTION': e_clean,
                'Starting date for contract execution (contact signature)': e_start.strftime('%Y-%m-%d') if e_start else "",
                'Contract End Date (Expiry)': e_exp.strftime('%Y-%m-%d') if e_exp else ""
            }
            db.update_full_contract(contract_id, updated_fields, user_name="Admin Officer")
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
# TAB 1: MASTER CONTRACT TRACKER
# ==========================================
with tab_tracker:
    s_col1, s_col2, s_col3 = st.columns([3, 1.2, 1.5])
    with s_col1:
        search_query = st.text_input("🔍 Search Product Description, Code, Supplier, Framework Ref, or Title...", placeholder="e.g. Paracetamol, Needles, Hetero, 144/G/IRT...")
    with s_col2:
        category_filter = st.selectbox("Filter Sheet / Category", ["All", "Medicines", "Consumables", "Laboratory", "IMPLANTS_"])
    with s_col3:
        status_filter = st.selectbox("Filter Expiry Status", [
            "All Expiry Statuses",
            "🚨 Expired / Overdue",
            "🚨 Expiring in < 3 Months",
            "⚠️ Expiring in 3–6 Months",
            "✅ Valid (> 6 Months)",
            "⏳ Missing Expiry Date"
        ])

    # Load Database Records
    df = db.load_contracts(category_filter=category_filter, search_query=search_query)

    # 1. CLEAN PRODUCT CODE TO TEXT (NO DECIMALS)
    if not df.empty and 'Product code' in df.columns:
        df['Product code'] = df['Product code'].astype(str).str.replace(r'\.0$', '', regex=True).replace(['nan', 'None', '<NA>'], '')

    # 2. CLEAN START DATE (REMOVE TIME COMPONENT)
    if not df.empty and 'Starting date for contract execution (contact signature)' in df.columns:
        start_dt_series = df['Starting date for contract execution (contact signature)'].apply(safe_parse_dt)
        df['Starting date for contract execution (contact signature)'] = start_dt_series.dt.strftime('%Y-%m-%d').fillna('')

    # 3. EXPIRY METRICS, DAYS EXPIRED & FILTERING CALCULATIONS
    today_midnight = pd.Timestamp(datetime.now().date())
    ninety_days_later = today_midnight + timedelta(days=90)
    six_months_later = today_midnight + timedelta(days=180)

    if not df.empty and 'Contract End Date (Expiry)' in df.columns:
        parsed_exp = df['Contract End Date (Expiry)'].apply(safe_parse_dt)
        df['Contract End Date (Expiry)'] = parsed_exp.dt.strftime('%Y-%m-%d').fillna(df['Contract End Date (Expiry)'].fillna(''))
        
        days_to_exp = (parsed_exp - today_midnight).dt.days
        days_past_exp = (today_midnight - parsed_exp).dt.days
        
        df['Days_To_Expiry'] = days_to_exp.apply(lambda x: int(x) if pd.notna(x) else None)
        df['Days_Past_Expiry'] = days_past_exp.apply(lambda x: int(x) if pd.notna(x) else None)

        # Explicit "Days Expired" Column requested: positive integer if expired, 0 if active
        df['Days Expired'] = days_past_exp.apply(lambda x: int(x) if pd.notna(x) and x > 0 else (0 if pd.notna(x) else None))

        # Thresholds: Red <= 90 days (< 3 months or expired), Yellow <= 180 days (3 to 6 months)
        df['Is_Red_Alert'] = (parsed_exp.notna()) & (days_to_exp <= 90)
        df['Is_Yellow_Alert'] = (parsed_exp.notna()) & (days_to_exp > 90) & (days_to_exp <= 180)

        # Categorize status for filtering
        def get_expiry_status_cat(row):
            if pd.isna(row['Days_To_Expiry']): return "Missing Expiry Date"
            days = row['Days_To_Expiry']
            if days < 0: return "Expired / Overdue"
            elif days <= 90: return "Expiring in < 3 Months"
            elif days <= 180: return "Expiring in 3–6 Months"
            else: return "Valid (> 6 Months)"

        df['Expiry_Status_Cat'] = df.apply(get_expiry_status_cat, axis=1)
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

    ctrl_col1, ctrl_col2, _ = st.columns([3, 3, 6])

    # EXACT ORIGINAL EXCEL COLUMN SEQUENCE (REF & CONTRACT TITLE TO FRONT, DATES TOGETHER)
    preferred_col_order = [
        'NO',
        'Product code',
        'Ref/N° of Framework Agreement',
        'Title of the contract',
        'Product Description',
        'Supplier',
        'Starting date for contract execution (contact signature)',
        'Contract End Date (Expiry)',
        'Days Expired',
        'Days Past Expiry',
        'pack size',
        'General medicines/Specialised/Oncology',
        'Currency',
        'Unit price',
        'Incoterm',
        'Manufacturer and country of origin',
        "Manufacturer's addresses",
        'Delivey period',
        'Demandor (End user)',
        'Budget Holder',
        'PROCUREMENT OFFICER',
        'CLEANING ACTION',
        'Category / Sheet'
    ]

    existing_cols = [c for c in preferred_col_order if c in df.columns]
    extra_cols = [c for c in df.columns if c not in preferred_col_order and c not in ['id', 'Days_To_Expiry', 'Days_Past_Expiry', 'Is_Red_Alert', 'Is_Yellow_Alert', 'Expiry_Status_Cat']]
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

        # TEXT CLAMP RENDERER (WRAP UP TO MAX 2 COMPACT LINES FOR DOUBLE-LINE ROW HEIGHT)
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

        # EXPLICIT COLUMN: DAYS EXPIRED
        if 'Days Expired' in df_display.columns:
            gb.configure_column('Days Expired', header_name='Days Expired', width=140, minWidth=120, editable=False, type=['numericColumn'])
        
        # BADGE CELL RENDERER FOR "DAYS PAST EXPIRY" / DAYS REMAINING
        days_past_renderer = JsCode("""
        class DaysPastRenderer {
            init(params) {
                this.eGui = document.createElement('div');
                if (!params.data || params.data.Days_To_Expiry === null || params.data.Days_To_Expiry === undefined || isNaN(params.data.Days_To_Expiry)) {
                    this.eGui.innerHTML = '<span style="color: #a0aec0;">-</span>';
                    return;
                }
                let daysToExpiry = parseInt(params.data.Days_To_Expiry, 10);
                let daysPast = parseInt(params.data.Days_Past_Expiry, 10);
                
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
        if 'Contract End Date (Expiry)' in df_display.columns:
            gb.configure_column('Contract End Date (Expiry)', width=180, minWidth=160, cellEditor=custom_date_editor)

        # CONFIGURE CHECKBOX SELECTION ON FIRST VISIBLE COLUMN
        gb.configure_selection(selection_mode="single", use_checkbox=True)
        if existing_cols:
            gb.configure_column(existing_cols[0], checkboxSelection=True)

        # AG-GRID STYLING: ROW HEIGHT 48PX (DOUBLE-LINE HEIGHT), VIRTUALIZATION & CHECKBOX SELECTION
        gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=100)
        
        gb.configure_grid_options(
            rowHeight=48,
            singleClickEdit=True,
            rowBuffer=10,
            getRowStyle=JsCode("""
            function(params) {
                if (!params.data) return null;
                let daysToExpiry = params.data.Days_To_Expiry;
                
                if (daysToExpiry === null || daysToExpiry === undefined || isNaN(daysToExpiry)) {
                    return params.node.rowIndex % 2 === 0 ? {'backgroundColor': '#ffffff'} : {'backgroundColor': '#f8fafc'};
                }
                let days = parseInt(daysToExpiry, 10);
                
                if (days <= 90) {
                    return {'backgroundColor': '#fee2e2', 'color': '#991b1b', 'fontWeight': 'bold'};
                }
                if (days <= 180) {
                    return {'backgroundColor': '#fef3c7', 'color': '#854d0e', 'fontWeight': 'bold'};
                }
                return params.node.rowIndex % 2 === 0 ? {'backgroundColor': '#ffffff'} : {'backgroundColor': '#f8fafc'};
            }
            """)
        )

        # RICH COLORED HEADER CSS
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
            ".ag-header-cell-label": {
                "color": "#ffffff !important",
                "font-weight": "bold !important"
            }
        }

        grid_options = gb.build()
        grid_response = AgGrid(
            df_display,
            gridOptions=grid_options,
            update_mode=GridUpdateMode.SELECTION_CHANGED | GridUpdateMode.VALUE_CHANGED,
            data_return_mode=DataReturnMode.AS_INPUT,
            theme='streamlit',
            height=580,
            custom_css=custom_header_css,
            allow_unsafe_jscode=True
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
                        st.success("Item deleted.")
                        st.rerun()

        # Sync Inline Cell Edits back to SQLite
        edited_df = grid_response['data']
        for index, new_row in edited_df.iterrows():
            if 'id' not in new_row or pd.isna(new_row['id']): continue
            db_id = int(new_row['id'])
            
            old_row_match = df[df['id'] == db_id]
            if old_row_match.empty: continue
            old_row = old_row_match.iloc[0]

            for ui_col in edited_df.columns:
                if ui_col in ['id', 'Days_To_Expiry', 'Days_Past_Expiry', 'Days Expired', 'Is_Red_Alert', 'Is_Yellow_Alert', 'Expiry_Status_Cat', '_selectedRowNodeInfo']: continue
                
                db_col = db.REVERSE_MAPPING.get(ui_col, ui_col)
                old_val = str(old_row.get(ui_col, "")).strip() if pd.notna(old_row.get(ui_col, "")) else ""
                new_val = str(new_row.get(ui_col, "")).strip() if pd.notna(new_row.get(ui_col, "")) else ""

                if old_val != new_val:
                    db.update_single_cell(db_id, db_col, new_val, user_name="Admin Officer")
                    st.rerun()

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