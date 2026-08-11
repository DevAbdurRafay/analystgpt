import os
import hashlib
import datetime
import base64
from io import BytesIO
from flask import Blueprint, render_template, request, jsonify, session, current_app, send_file, redirect, url_for
import pandas as pd
import numpy as np

from services.data_cleaner import DataCleaner
from services.supabase_service import db_service

data_bp = Blueprint("data", __name__, url_prefix="/data")


def get_user_upload_dir():
    """Returns a unique directory path for the current user's uploads (Vercel-compatible)."""
    if "email" not in session:
        return None
    import tempfile
    email_hash = hashlib.sha256(session["email"].encode("utf-8")).hexdigest()
    base_folder = current_app.config.get("UPLOAD_FOLDER")
    if os.getenv("VERCEL") or not base_folder:
        base_folder = os.path.join(tempfile.gettempdir(), "analystgpt_uploads")
    try:
        os.makedirs(base_folder, exist_ok=True)
    except Exception:
        base_folder = os.path.join(tempfile.gettempdir(), "analystgpt_uploads")
        os.makedirs(base_folder, exist_ok=True)
    upload_dir = os.path.join(base_folder, email_hash)
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir

def get_dataset_path():
    """Returns the path to the user's active dataset."""
    upload_dir = get_user_upload_dir()
    if not upload_dir:
        return None
    return os.path.join(upload_dir, "active_dataset.csv")

def drop_empty_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Silently drops columns where all values are null, NaN, or whitespace-only strings."""
    cols_to_drop = []
    for col in df.columns:
        series = df[col]
        if series.isnull().all():
            cols_to_drop.append(col)
        else:
            non_nulls = series.dropna().astype(str).str.strip()
            if (non_nulls == "").all():
                cols_to_drop.append(col)
    if cols_to_drop:
        df = df.drop(columns=cols_to_drop)
    return df

@data_bp.route("/dashboard")
def dashboard():
    if "email" not in session:
        return redirect(url_for("auth.login"))
        
    # Check if user has an uploaded dataset already
    has_dataset = False
    diagnostics = None
    dataset_path = get_dataset_path()
    
    if dataset_path and os.path.exists(dataset_path):
        has_dataset = True
        try:
            df = pd.read_csv(dataset_path)
            diagnostics = DataCleaner.get_diagnostics(df)
        except Exception as e:
            has_dataset = False
            diagnostics = None
            
    return render_template(
        "dashboard.html", 
        has_dataset=has_dataset, 
        diagnostics=diagnostics,
        email=session.get("email"),
    )

@data_bp.route("/upload", methods=["POST"])
def upload():
    if "email" not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    if "file" not in request.files:
        return jsonify({"error": "No file part in the request"}), 400

    existing_path = get_dataset_path()
    if existing_path and os.path.exists(existing_path):
        return jsonify({"error": "A dataset is already loaded. Remove it first to upload a new file."}), 409
        
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400
        
    filename_lower = file.filename.lower()
    if not (filename_lower.endswith(".csv") or filename_lower.endswith(".xlsx") or filename_lower.endswith(".xls")):
        return jsonify({"error": "Only CSV and Excel (.xlsx, .xls) files are supported."}), 400

    try:
        # Read uploaded file depending on extension
        if filename_lower.endswith(".xlsx") or filename_lower.endswith(".xls"):
            df = pd.read_excel(file)
        else:
            df = pd.read_csv(file)

        if df.empty:
            return jsonify({"error": "The uploaded dataset is empty."}), 400

        # Automatically detect and drop entirely empty columns
        df = drop_empty_columns(df)

        if df.columns.empty:
            return jsonify({"error": "The uploaded dataset contains no valid data columns."}), 400

        # Save sanitized dataset to CSV format for active session
        dest_path = get_dataset_path()
        df.to_csv(dest_path, index=False)

        # Run diagnostics on sanitized dataset
        diagnostics = DataCleaner.get_diagnostics(df)

        # Save metadata to Supabase dataset_uploads table
        user_id = session.get("user_id")
        if not user_id and session.get("email"):
            u = db_service.get_user_by_email(session.get("email"))
            if u:
                user_id = u.get("id")
                session["user_id"] = user_id

        if user_id:
            file_size = os.path.getsize(dest_path) if os.path.exists(dest_path) else 0
            db_service.save_dataset_upload(
                user_id=user_id,
                original_name=file.filename,
                row_count=diagnostics.get("row_count", 0),
                col_count=diagnostics.get("col_count", 0),
                file_size_bytes=file_size,
                columns=diagnostics.get("columns", []),
                dtypes=diagnostics.get("dtypes", {})
            )

        return jsonify({
            "message": "File uploaded successfully",
            "diagnostics": diagnostics
        })
    except Exception as e:
        return jsonify({"error": f"Failed to parse dataset file: {str(e)}"}), 500


@data_bp.route("/clean", methods=["POST"])
def clean():
    if "email" not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    dataset_path = get_dataset_path()
    if not dataset_path or not os.path.exists(dataset_path):
        return jsonify({"error": "No active dataset found. Please upload a CSV first."}), 400

    options = request.json or {}
    
    try:
        df = pd.read_csv(dataset_path)
        cleaned_df = DataCleaner.clean_data(df, options)
        
        # Save cleaned file back
        cleaned_df.to_csv(dataset_path, index=False)
        
        diagnostics = DataCleaner.get_diagnostics(cleaned_df)
        return jsonify({
            "message": "Data cleaned successfully",
            "diagnostics": diagnostics
        })
    except Exception as e:
        return jsonify({"error": f"Cleaning failed: {str(e)}"}), 500

@data_bp.route("/remove-dataset", methods=["POST"])
def remove_dataset():
    if "email" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    dataset_path = get_dataset_path()
    if dataset_path and os.path.exists(dataset_path):
        try:
            os.remove(dataset_path)
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"error": f"Failed to delete file: {str(e)}"}), 500
    
    return jsonify({"success": True})


# ─── CSV Export ────────────────────────────────────────────────────────────────
@data_bp.route("/export-csv", methods=["GET"])
def export_csv():
    if "email" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    dataset_path = get_dataset_path()
    if not dataset_path or not os.path.exists(dataset_path):
        return jsonify({"error": "No active dataset found."}), 400

    try:
        df = pd.read_csv(dataset_path)
        buf = BytesIO()
        df.to_csv(buf, index=False, encoding="utf-8-sig")
        buf.seek(0)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"AnalystGPT_Cleaned_Dataset_{ts}.csv"
        return send_file(
            buf,
            as_attachment=True,
            download_name=filename,
            mimetype="text/csv"
        )
    except Exception as e:
        return jsonify({"error": f"CSV export failed: {str(e)}"}), 500


# ─── Excel Export ──────────────────────────────────────────────────────────────
@data_bp.route("/export-excel", methods=["GET"])
def export_excel():
    if "email" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    dataset_path = get_dataset_path()
    if not dataset_path or not os.path.exists(dataset_path):
        return jsonify({"error": "No active dataset found."}), 400

    try:
        df = pd.read_csv(dataset_path)
        buf = BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Cleaned_Dataset")
            # Auto-fit column widths
            ws = writer.sheets["Cleaned_Dataset"]
            for col_cells in ws.columns:
                max_len = max(
                    (len(str(cell.value)) if cell.value is not None else 0)
                    for cell in col_cells
                )
                ws.column_dimensions[col_cells[0].column_letter].width = min(max_len + 3, 50)
        buf.seek(0)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"AnalystGPT_Cleaned_Dataset_{ts}.xlsx"
        return send_file(
            buf,
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except Exception as e:
        return jsonify({"error": f"Excel export failed: {str(e)}"}), 500


@data_bp.route("/export-pdf", methods=["POST"])
def export_pdf():
    if "email" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    dataset_path = get_dataset_path()
    if not dataset_path or not os.path.exists(dataset_path):
        return jsonify({"error": "No dataset to report on."}), 400

    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
    except ImportError:
        return jsonify({"error": "PDF generation library (reportlab) not installed."}), 500

    # ── Safe text helper ─────────────────────────────────────────────────────
    import xml.sax.saxutils as saxutils
    import html as html_module

    def safe_para(text, style):
        """Escape special XML chars so ReportLab's Paragraph never crashes."""
        if not text:
            text = ""
        # Decode HTML entities first so &amp; in source does not become literal &amp;
        decoded = html_module.unescape(str(text))
        safe = saxutils.escape(decoded)
        # Restore basic allowed HTML tags ReportLab supports
        safe = safe.replace("&lt;br/&gt;", "<br/>").replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
        try:
            return Paragraph(safe, style)
        except Exception:
            return Paragraph(saxutils.escape(decoded), style)

    # Parse JSON body
    post_data = request.json or {}
    notes = post_data.get("notes", "")
    chat_history = post_data.get("chat_history", [])
    charts = post_data.get("charts", [])

    try:
        df = pd.read_csv(dataset_path)
        diagnostics = DataCleaner.get_diagnostics(df)
    except Exception as e:
        return jsonify({"error": f"Could not load data: {str(e)}"}), 500

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40, leftMargin=40,
        topMargin=45, bottomMargin=45
    )

    styles = getSampleStyleSheet()
    primary_color = colors.HexColor("#0B0F19")
    accent_color = colors.HexColor("#10B981")
    text_color = colors.HexColor("#1E293B")

    title_style = ParagraphStyle('DocTitle', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=24, textColor=primary_color, spaceAfter=15)
    subtitle_style = ParagraphStyle('DocSubtitle', parent=styles['Normal'], fontName='Helvetica', fontSize=10, textColor=colors.HexColor("#64748B"), spaceAfter=25)
    h2_style = ParagraphStyle('SectionHeader', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=14, textColor=colors.HexColor("#111827"), spaceBefore=15, spaceAfter=10, borderColor=accent_color, borderWidth=1, borderRadius=2, borderPadding=5, backColor=colors.HexColor("#F8FAFC"))
    body_style = ParagraphStyle('DocBody', parent=styles['BodyText'], fontName='Helvetica', fontSize=10, textColor=text_color, spaceAfter=8, leading=14)
    chat_user_style = ParagraphStyle('ChatUser', parent=styles['BodyText'], fontName='Helvetica-Bold', fontSize=10, textColor=colors.HexColor("#0284C7"), spaceBefore=8, spaceAfter=3)
    chat_ai_style = ParagraphStyle('ChatAI', parent=styles['BodyText'], fontName='Helvetica', fontSize=10, textColor=colors.HexColor("#0F172A"), spaceAfter=12, leading=14, backColor=colors.HexColor("#F1F5F9"), borderPadding=8, borderRadius=4)

    story = []

    story.append(safe_para("AI-Powered Data Analysis Report", title_style))
    story.append(safe_para(f"Generated for: {session['email']} | Date: {datetime.datetime.now().strftime('%B %d, %Y, %H:%M:%S')}", subtitle_style))
    story.append(Spacer(1, 10))

    if notes:
        story.append(safe_para("Executive Summary & Notes", h2_style))
        story.append(safe_para(notes, body_style))
        story.append(Spacer(1, 15))

    story.append(safe_para("Dataset Profile Diagnostics", h2_style))
    diag_data = [
        [safe_para("<b>Metric</b>", body_style), safe_para("<b>Value</b>", body_style)],
        [safe_para("Total Rows", body_style), safe_para(str(diagnostics["row_count"]), body_style)],
        [safe_para("Total Columns", body_style), safe_para(str(diagnostics["col_count"]), body_style)],
        [safe_para("Total Missing Cells", body_style), safe_para(str(sum(diagnostics["null_counts"].values())), body_style)]
    ]
    diag_table = Table(diag_data, colWidths=[200, 300])
    diag_table.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.HexColor("#E2E8F0")), ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E1")), ('BOTTOMPADDING', (0,0), (-1,-1), 6), ('TOPPADDING', (0,0), (-1,-1), 6)]))
    story.append(diag_table)
    story.append(Spacer(1, 15))

    story.append(safe_para("Dataset Columns Schema", body_style))
    col_headers = [safe_para("<b>Column Name</b>", body_style), safe_para("<b>Data Type</b>", body_style), safe_para("<b>Missing</b>", body_style), safe_para("<b>Unique</b>", body_style)]
    col_rows = []
    for col in diagnostics["columns"]:
        profile = diagnostics.get("column_profiles", {}).get(col, {})
        col_rows.append([
            safe_para(col, body_style),
            safe_para(diagnostics["dtypes"].get(col, "unknown"), body_style),
            safe_para(f"{profile.get('nulls', 0)} ({profile.get('null_pct', 0)}%)", body_style),
            safe_para(str(profile.get('unique', '—')), body_style)
        ])
    schema_table_data = [col_headers] + col_rows[:20]
    if len(col_rows) > 20:
        schema_table_data.append([safe_para("<i>... remaining columns omitted for brevity</i>", body_style), "", "", ""])
    schema_table = Table(schema_table_data, colWidths=[190, 110, 90, 70])
    schema_table.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.HexColor("#F1F5F9")), ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")), ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#F8FAFC")]), ('BOTTOMPADDING', (0,0), (-1,-1), 4), ('TOPPADDING', (0,0), (-1,-1), 4)]))
    story.append(schema_table)
    story.append(Spacer(1, 20))

    story.append(PageBreak())

    if charts:
        story.append(safe_para("Data Visualizations & Graphics", h2_style))
        for idx, chart in enumerate(charts):
            story.append(safe_para(f"<b>Figure {idx+1}: {chart.get('title', 'Analysis Chart')}</b>", body_style))
            img_data_b64 = chart.get("image", "")
            if img_data_b64 and "," in img_data_b64:
                try:
                    raw_data = base64.b64decode(img_data_b64.split(",")[1])
                    img_io = BytesIO(raw_data)
                    pdf_img = Image(img_io, width=500, height=280)
                    story.append(pdf_img)
                    story.append(Spacer(1, 10))
                except Exception as ex:
                    story.append(safe_para(f"<i>Could not render image: {str(ex)}</i>", body_style))
            explanation = chart.get("explanation", "")
            if explanation:
                story.append(safe_para(f"<b>AI Insight:</b> {explanation}", body_style))
                story.append(Spacer(1, 15))
            story.append(Spacer(1, 10))

    if chat_history:
        story.append(safe_para("AI Analytical Dialogue Transcript", h2_style))
        for msg in chat_history:
            sender = msg.get("sender", "user")
            text = msg.get("text", "")
            if sender == "user":
                story.append(safe_para(f"<b>Query:</b> {text}", chat_user_style))
            else:
                story.append(safe_para(f"<b>Response:</b><br/>{text}", chat_ai_style))
            story.append(Spacer(1, 4))

    doc.build(story)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"Data_Analysis_Report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf", mimetype="application/pdf")

