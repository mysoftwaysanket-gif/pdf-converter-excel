from flask import Flask, request, jsonify, send_file,Response
from flask_cors import CORS
from rembg import remove
from PIL import Image
import io
import csv
import re
from hashlib import md5
import pdfplumber
import PyPDF2

import pandas as pd
import os
import traceback

app = Flask(__name__)
CORS(app)


@app.route("/remove-bg", methods=["POST"])
def remove_bg_api():
    try:
        # Check file
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400
        
        file = request.files["file"]
        input_image = Image.open(file.stream)

        # Remove background
        output_image = remove(input_image)

        # Convert to in-memory file
        img_io = io.BytesIO()
        output_image.save(img_io, "PNG")
        img_io.seek(0)

        # Return image file
        return send_file(img_io, mimetype="image/png")

    except Exception as e:
        print("ERROR:", e)
        return jsonify({"error": str(e)}), 500

# ======================================================
# =============== ALL CATEGORY CONVERTERS ==============
# ======================================================

# ---------------- EXISTING (UNCHANGED) ----------------

def consolidated_mcc_admitted_converter(pdf_bytes):
    import pdfplumber
    import pandas as pd
    import io

    headers = [
        "RollNo",
        "Name",
        "QuotaName",
        "AIR",
        "Institute",
        "Admitted_Round"
    ]

    rows = []

    pdf_stream = io.BytesIO(pdf_bytes)
    with pdfplumber.open(pdf_stream) as pdf:
        for page in pdf.pages:

            # Use table extraction (best for grid PDFs like MCC)
            tables = page.extract_tables()

            if not tables:
                continue

            for table in tables:
                for row in table:

                    # Skip empty or header rows
                    if not row:
                        continue

                    joined = " ".join([str(x) for x in row if x])

                    if "Rollno" in joined or "Name" in joined or "QuotaName" in joined:
                        continue

                    # Expected 6 columns exactly
                    # Some rows may shift, so normalize length
                    clean = [cell.strip() if cell else "" for cell in row]

                    # Remove extra columns if any
                    if len(clean) > 6:
                        clean = clean[:6]

                    # Pad missing columns
                    while len(clean) < 6:
                        clean.append("")

                    rollno, name, quota, air, institute, round_no = clean

                    # Validate row
                    if rollno.isdigit() and air.isdigit():
                        rows.append([
                            rollno,
                            name,
                            quota,
                            air,
                            institute,
                            round_no
                        ])

    if not rows:
        raise Exception("No valid data extracted from MCC Admitted List PDF")

    df = pd.DataFrame(rows, columns=headers)

    # Final cleanup
    df = df.apply(
        lambda col: col.str.replace(r"\s+", " ", regex=True).str.strip()
        if col.dtype == "object" else col
    )

    output = io.StringIO()
    df.to_csv(output, index=False, encoding="utf-8-sig")
    output.seek(0)

    return output





def mbbs_bds_converter(pdf_bytes):

    headers = [
        "Sr No",
        "AIR",
        "NEET Roll No",
        "CET Form No",
        "Name",
        "Gender",
        "Category",
        "Quota",
        "College Code & Name"
    ]

    rows = []

    pdf_stream = io.BytesIO(pdf_bytes)
    with pdfplumber.open(pdf_stream) as pdf:

        for page in pdf.pages:

            table = page.extract_table()

            if table and len(table) > 1:

                for row in table[1:]:   # skip header

                    row = [cell.replace("\n", " ").strip() if cell else "" for cell in row]

                    if len(row) > 9:
                        fixed = row[:8]
                        college = " ".join(row[8:])
                        row = fixed + [college]

                    while len(row) < 9:
                        row.append("")

                    if not (
                        row[0].isdigit()
                        and row[1].isdigit()
                        and row[2].isdigit()
                        and row[3].isdigit()
                    ):
                        continue

                    rows.append(row[:9])

                continue

            words = page.extract_words(use_text_flow=True)
            if not words:
                continue

            lines = {}
            for w in words:
                y = round(w["top"], 1)
                lines.setdefault(y, []).append(w)

            for y in sorted(lines.keys()):

                line_words = sorted(lines[y], key=lambda w: w["x0"])
                tokens = [w["text"] for w in line_words]

                if len(tokens) < 8:
                    continue

                if not (
                    tokens[0].isdigit()
                    and tokens[1].isdigit()
                    and tokens[2].isdigit()
                    and tokens[3].isdigit()
                ):
                    continue

                try:
                    sr_no, air, neet, cet = tokens[:4]
                    rest = tokens[4:]

                    gender_idx = next(i for i, t in enumerate(rest) if t in ["M", "F"])

                    name = " ".join(rest[:gender_idx])
                    gender = rest[gender_idx]
                    after_gender = rest[gender_idx + 1:]

                    college_idx = next(i for i, t in enumerate(after_gender) if ":" in t)

                    middle = after_gender[:college_idx]
                    college = " ".join(after_gender[college_idx:])

                    category = middle[0] if len(middle) >= 1 else ""
                    quota = " ".join(middle[1:]) if len(middle) > 1 else ""

                    rows.append([
                        sr_no,
                        air,
                        neet,
                        cet,
                        name,
                        gender,
                        category,
                        quota,
                        college
                    ])

                except:
                    continue

    if not rows:
        raise Exception("No valid MBBS–BDS data rows found in PDF")

    df = pd.DataFrame(rows, columns=headers)

    df = df.replace("\n", " ", regex=True)
    df = df.apply(lambda col: col.str.strip() if col.dtype == "object" else col)

    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False, encoding="utf-8-sig")
    csv_buffer.seek(0)

    return csv_buffer


def medical_fee_converter(pdf_bytes):
    all_rows = []
    header = None

    pdf_stream = io.BytesIO(pdf_bytes)
    with pdfplumber.open(pdf_stream) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if table and len(table) > 1:
                if header is None:
                    header = table[0]
                for row in table[1:]:
                    if any(row):
                        all_rows.append(row)

    if not all_rows:
        raise Exception("No table data found in Medical Fee PDF")

    df = pd.DataFrame(all_rows, columns=header)

    df = df.replace("\n", " ", regex=True)
    df = df.apply(lambda col: col.str.strip() if col.dtype == "object" else col)

    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False, encoding="utf-8-sig")
    csv_buffer.seek(0)

    return csv_buffer


def pg_mcc_converter_1(pdf_bytes):
    import pdfplumber
    import pandas as pd
    import io

    rows = []

    pdf_stream = io.BytesIO(pdf_bytes)
    with pdfplumber.open(pdf_stream) as pdf:

        for page in pdf.pages:

            # Extract all tables from page (grid based)
            tables = page.extract_tables({
                "vertical_strategy": "lines",
                "horizontal_strategy": "lines",
                "snap_tolerance": 3,
                "intersection_tolerance": 5,
            })

            if not tables:
                continue

            for table in tables:

                # Skip header row
                for row in table[1:]:

                    # Clean cells
                    cleaned = []
                    for cell in row:
                        if cell:
                            cleaned.append(cell.replace("\n", " ").strip())
                        else:
                            cleaned.append("")

                    # We expect exactly 8 columns in PG MCC format:
                    # SNo | Rank | Quota | Institute | Course | Allotted Cat | Candidate Cat | Remarks
                    if len(cleaned) < 8:
                        continue

                    # First real column should be SNo (number)
                    if not cleaned[0].isdigit():
                        continue

                    sno = cleaned[0]
                    rank = cleaned[1]
                    quota = cleaned[2]
                    institute = cleaned[3]
                    course = cleaned[4]
                    allotted_cat = cleaned[5]
                    candidate_cat = cleaned[6]
                    remarks = cleaned[7]

                    rows.append([
                        rank,
                        quota,
                        institute,
                        course,
                        allotted_cat,
                        candidate_cat,
                        remarks
                    ])

    if not rows:
        raise Exception("No PG MCC data extracted – PDF format not detected")

    df = pd.DataFrame(rows, columns=[
        "Rank",
        "Allotted_Quota",
        "Allotted_Institute",
        "Course",
        "Allotted_Category",
        "Candidate_Category",
        "Remarks"
    ])

    # Final cleanup
    df = df.applymap(lambda x: x.replace("  ", " ").strip() if isinstance(x, str) else x)

    output = io.StringIO()
    df.to_csv(output, index=False, encoding="utf-8-sig")
    output.seek(0)
    return output


def pg_mcc_converter_2(pdf_bytes):
    import pdfplumber
    import pandas as pd
    import io

    rows = []

    pdf_stream = io.BytesIO(pdf_bytes)
    with pdfplumber.open(pdf_stream) as pdf:

        for page in pdf.pages:
            tables = page.extract_tables() or []

            for table in tables:
                for row in table:

                    # Clean cells
                    cleaned = []
                    for cell in row:
                        if cell:
                            cleaned.append(cell.replace("\n", " ").strip())
                        else:
                            cleaned.append("")

                    if not cleaned:
                        continue

                    first_cell = cleaned[0].lower()

                    # Skip headers
                    if (
                        first_cell in {"rank", "sr no", "sno"} or
                        not first_cell.isdigit()
                    ):
                        continue

                    # ===== THE ONLY REAL FIX =====
                    # First 15 rows case: length = 11 and last is remark
                    if len(cleaned) == 11:
                        last_remark = cleaned[-1]
                        cleaned = cleaned[:5] + ["-","-","-","-","-","-"] + [last_remark]
                    # =============================

                    # Ensure exactly 12 columns
                    while len(cleaned) < 12:
                        cleaned.append("-")

                    # Mapping (unchanged)
                    rank = cleaned[0]

                    # Round 1
                    r1_quota = cleaned[1]
                    r1_institute = cleaned[2]
                    r1_course = cleaned[3]
                    r1_remarks = cleaned[4]

                    # Round 2
                    r2_quota = cleaned[5]
                    r2_institute = cleaned[6]
                    r2_course = cleaned[7]
                    r2_allotted_cat = cleaned[8]
                    r2_candidate_cat = cleaned[9]
                    r2_option_no = cleaned[10]
                    r2_remarks = cleaned[11]

                    rows.append([
                        rank,
                        r1_quota,
                        r1_institute,
                        r1_course,
                        r1_remarks,
                        r2_quota,
                        r2_institute,
                        r2_course,
                        r2_allotted_cat,
                        r2_candidate_cat,
                        r2_option_no,
                        r2_remarks
                    ])

    df = pd.DataFrame(rows, columns=[
        "Rank",
        "R1_Allotted_Quota",
        "R1_Allotted_Institute",
        "R1_Course",
        "R1_Remarks",
        "R2_Allotted_Quota",
        "R2_Allotted_Institute",
        "R2_Course",
        "R2_Allotted_Category",
        "R2_Candidate_Category",
        "R2_Option_No",
        "R2_Remarks"
    ])

    output = io.StringIO()
    df.to_csv(output, index=False, encoding="utf-8-sig")
    output.seek(0)
    return output


def bpht_converter(pdf_bytes):

    headers = [
        "Sr No",
        "AIR",
        "NEET Roll No",
        "CET Form No",
        "Name",
        "Gender",
        "Category",
        "Quota / Status",
        "College Code & Name"
    ]

    rows = []

    pdf_stream = io.BytesIO(pdf_bytes)
    with pdfplumber.open(pdf_stream) as pdf:

        for page in pdf.pages:

            text = page.extract_text()
            if not text:
                continue

            lines = text.split("\n")

            for line in lines:

                line = line.strip()

                if not line:
                    continue
                if line.startswith("Sr.") or "Current Selection Details" in line:
                    continue
                if "Printed On" in line or "This provisional seat allotment" in line:
                    continue
                if line.startswith("-"):
                    continue

                match = re.match(
                    r"""
                    ^\s*(\d+)\s+
                    (\d+)\s+
                    (\d+)\s+
                    (\d+)\s+
                    ([A-Z\s]+?)\s+
                    ([MF])\s+
                    ([A-Z]*)\s*
                    ([A-Z\(\)\s]*)\s+
                    (.*\d+:.+)$
                    """,
                    line,
                    re.VERBOSE
                )

                if not match:
                    match2 = re.match(
                        r"""
                        ^\s*(\d+)\s+
                        (\d+)\s+
                        (\d+)\s+
                        (\d+)\s+
                        ([A-Z\s]+?)\s+
                        ([MF])\s+
                        ([A-Z]*)\s*
                        (Choice\s+Not\s+Available)
                        """,
                        line,
                        re.VERBOSE
                    )

                    if not match2:
                        continue

                    rows.append([
                        match2.group(1),
                        match2.group(2),
                        match2.group(3),
                        match2.group(4),
                        match2.group(5).strip(),
                        match2.group(6),
                        match2.group(7).strip(),
                        match2.group(8).strip(),
                        ""
                    ])
                    continue

                rows.append([
                    match.group(1),
                    match.group(2),
                    match.group(3),
                    match.group(4),
                    match.group(5).strip(),
                    match.group(6),
                    match.group(7).strip(),
                    match.group(8).strip(),
                    match.group(9).strip()
                ])

    if not rows:
        raise Exception("No valid BPTH data rows found in PDF")

    df = pd.DataFrame(rows, columns=headers)

    df = df.replace("\n", " ", regex=True)
    df = df.apply(lambda col: col.str.strip() if col.dtype == "object" else col)

    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False, encoding="utf-8-sig")
    csv_buffer.seek(0)

    return csv_buffer


def bams_bhms_converter(pdf_bytes):
    import pdfplumber
    import pandas as pd
    import re
    import io

    headers = [
        "Sr No",
        "AIR",
        "NEET Roll No",
        "CET Form No",
        "Name",
        "Gender",
        "Category",
        "Quota",
        "College Code",
        "College Name"
    ]

    rows = []

    # This regex matches the exact structure seen in your screenshot
    ROW_RE = re.compile(
        r"^\s*(\d+)\s+"                 # Sr No
        r"(\d+)\s+"                     # AIR
        r"(\d+)\s+"                     # NEET Roll
        r"(\d+)\s+"                     # CET Form
        r"([A-Z\s\.]+?)\s+"             # Name (lazy, stops before gender)
        r"([MF])\s+"                    # Gender
        r"([A-Z]+)\s+"                  # Category (OBC, OPEN, SEBC, etc.)
        r"(.*?)\s+"                     # Quota (OPEN, OPEN (EMD), EMR, etc.)
        r"(\d{4})\:?\s*(.+)$"           # College code + College name
    )

    pdf_stream = io.BytesIO(pdf_bytes)
    with pdfplumber.open(pdf_stream) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue

            lines = [ln.rstrip() for ln in text.split("\n")]

            for line in lines:

                # Skip headers / separators
                if (
                    "Sr." in line
                    or "Printed On" in line
                    or "----" in line
                    or "Current Selection" in line
                ):
                    continue

                # Special case: "Choice Not Available" rows
                if "Choice Not Available" in line:
                    parts = line.split()
                    try:
                        sr = parts[0]
                        air = parts[1]
                        neet = parts[2]
                        cet = parts[3]
                        gender = parts[-3]
                        category = parts[-2]

                        name = " ".join(parts[4:-3])

                        rows.append([
                            sr, air, neet, cet,
                            name, gender, category,
                            "Choice Not Available",
                            "", ""
                        ])
                    except:
                        continue

                    continue

                # Normal rows
                m = ROW_RE.match(line)
                if m:
                    rows.append([
                        m.group(1),   # Sr
                        m.group(2),   # AIR
                        m.group(3),   # NEET Roll
                        m.group(4),   # CET Form
                        m.group(5).strip(),  # Name
                        m.group(6),   # Gender
                        m.group(7),   # Category
                        m.group(8).strip(),  # Quota
                        m.group(9),   # College Code
                        m.group(10).strip()  # College Name
                    ])

    if not rows:
        raise Exception("No BAMS/BHMS data extracted from PDF")

    df = pd.DataFrame(rows, columns=headers)

    # Clean whitespace
    df = df.apply(
        lambda col: col.str.replace(r"\s+", " ", regex=True).str.strip()
        if col.dtype == "object" else col
    )

    output = io.StringIO()
    df.to_csv(output, index=False, encoding="utf-8-sig")
    output.seek(0)
    return output


def bams_srv_converter(pdf_bytes):
    all_rows = []
    header = None

    pdf_stream = io.BytesIO(pdf_bytes)
    with pdfplumber.open(pdf_stream) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if table and len(table) > 1:

                if header is None:
                    header = table[0]

                for row in table[1:]:
                    if any(row):
                        all_rows.append(row)

    if not all_rows:
        raise Exception("No table data found in BAMS SRV PDF")

    df = pd.DataFrame(all_rows, columns=header)
    df = df.replace("\n", " ", regex=True)
    df = df.apply(lambda col: col.str.strip() if col.dtype == "object" else col)

    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False, encoding="utf-8-sig")
    csv_buffer.seek(0)

    return csv_buffer


def bds_converter(pdf_bytes):
    all_rows = []
    header = None

    pdf_stream = io.BytesIO(pdf_bytes)
    with pdfplumber.open(pdf_stream) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if table and len(table) > 1:

                if header is None:
                    header = table[0]

                for row in table[1:]:
                    if any(row):
                        all_rows.append(row)

    if not all_rows:
        raise Exception("No table data found in BDS PDF")

    df = pd.DataFrame(all_rows, columns=header)
    df = df.replace("\n", " ", regex=True)
    df = df.apply(lambda col: col.str.strip() if col.dtype == "object" else col)

    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False, encoding="utf-8-sig")
    csv_buffer.seek(0)

    return csv_buffer


def mbbs_converter(pdf_bytes):
    all_rows = []
    header = None

    pdf_stream = io.BytesIO(pdf_bytes)
    with pdfplumber.open(pdf_stream) as pdf:
        for page in pdf.pages:

            table = page.extract_table()

            if table and len(table) > 1:

                if header is None:
                    header = table[0]

                for row in table[1:]:
                    if any(row):
                        all_rows.append(row)

    if not all_rows:
        raise Exception("No table data found in MBBS PDF")

    df = pd.DataFrame(all_rows, columns=header)
    df = df.replace("\n", " ", regex=True)
    df = df.apply(lambda col: col.str.strip() if col.dtype == "object" else col)

    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False, encoding="utf-8-sig")
    csv_buffer.seek(0)

    return csv_buffer


def selection_list_converter(pdf_bytes):

    rows = []

    pdf_stream = io.BytesIO(pdf_bytes)
    with pdfplumber.open(pdf_stream) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue

            for line in text.split("\n"):

                if not line.strip():
                    continue
                if line.strip().startswith("-"):
                    continue
                if "Sr." in line and "CET" in line:
                    continue

                match = re.match(
                    r"\s*(\d+)\s+(\d+)\s+(\d+)\s+([A-Z\s]+?)\s+([MF])\s+([A-Z0-9\s]+?)\s+(OPEN.*?|NTD|DEF2|PWD-OPEN|PWD|OPEN)\s+(\d+:.+)",
                    line
                )

                if not match:
                    continue

                rows.append([
                    match.group(1),
                    match.group(2),
                    match.group(3),
                    match.group(4).strip(),
                    match.group(5),
                    match.group(6).strip(),
                    match.group(7).strip(),
                    match.group(8).strip()
                ])

    if not rows:
        raise Exception("No data rows found in Selection List PDF")

    headers = [
        "Sr No",
        "SML",
        "CET Form No",
        "Name",
        "Gender",
        "Category",
        "Quota / Status",
        "College Code & Name"
    ]

    df = pd.DataFrame(rows, columns=headers)
    df = df.replace("\n", " ", regex=True)
    df = df.apply(lambda col: col.str.strip() if col.dtype == "object" else col)

    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False, encoding="utf-8-sig")
    csv_buffer.seek(0)

    return csv_buffer


def provisional_merit_list_converter(pdf_bytes):
    all_rows = []
    header = None

    pdf_stream = io.BytesIO(pdf_bytes)
    with pdfplumber.open(pdf_stream) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if table and len(table) > 1:

                if header is None:
                    header = table[0]

                for row in table[1:]:
                    if any(row):
                        all_rows.append(row)

    if not all_rows:
        raise Exception("No table data found in Provisional Merit List PDF")

    df = pd.DataFrame(all_rows, columns=header)
    df = df.replace("\n", " ", regex=True)
    df = df.apply(lambda col: col.str.strip() if col.dtype == "object" else col)

    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False, encoding="utf-8-sig")
    csv_buffer.seek(0)

    return csv_buffer


# ---------------- 🔹 NEW CATEGORIES (PLACEHOLDERS) ----------------
def mh_ai_converter(pdf_bytes):

    all_rows = []
    header = None

    pdf_stream = io.BytesIO(pdf_bytes)
    with pdfplumber.open(pdf_stream) as pdf:

        for page in pdf.pages:

            table = page.extract_table()

            if not table or len(table) < 2:
                continue

            # Take header only once
            if header is None:
                header = table[0]

            for row in table[1:]:

                # Skip empty rows
                if not any(row):
                    continue

                clean_row = []
                for cell in row:
                    if cell is None:
                        clean_row.append("")
                    else:
                        clean_row.append(re.sub(r"\s+", " ", cell).strip())

                # Skip repeated header rows in between pages
                if clean_row[0].lower().startswith("sr"):
                    continue

                all_rows.append(clean_row)

    if not all_rows:
        raise Exception("No valid data extracted from MH AI PDF")

    df = pd.DataFrame(all_rows, columns=header)

    # Final cleanup
    df = df.replace("\n", " ", regex=True)
    df = df.apply(lambda col: col.str.strip() if col.dtype == "object" else col)

    output = io.StringIO()
    df.to_csv(output, index=False, encoding="utf-8-sig")
    output.seek(0)

    return output


def mht_cet_converter(pdf_bytes):

    import pdfplumber
    import pandas as pd
    import re
    import io

    headers = [
        "College Code & Name",
        "Branch Code & Name",
        "Seat Type",
        "Stage",
        "Category",
        "Rank",
        "Percentile"
    ]

    rows = []

    COLLEGE_RE = re.compile(r"^\d{5}\s*-\s*(.+)$")
    BRANCH_RE  = re.compile(r"^\d{10}\s*-\s*(.+)$")

    pdf_stream = io.BytesIO(pdf_bytes)
    with pdfplumber.open(pdf_stream) as pdf:

        college = ""
        branch = ""
        seat_type = ""

        for page in pdf.pages:

            text = page.extract_text()
            if not text:
                continue

            lines = [l.strip() for l in text.split("\n") if l.strip()]
            i = 0

            while i < len(lines):

                line = lines[i]

                # -------- College --------
                m = COLLEGE_RE.match(line)
                if m:
                    college = m.group(0)   # keep full "01002 - College Name"
                    i += 1
                    continue

                # -------- Branch --------
                m = BRANCH_RE.match(line)
                if m:
                    branch = m.group(0)    # keep full "0100219110 - Branch"
                    i += 1
                    continue

                # -------- Seat Type --------
                if "Home University" in line:
                    seat_type = "Home University"
                    i += 1
                    continue
                if "Other Than Home University" in line:
                    seat_type = "Other Than Home University"
                    i += 1
                    continue
                if "State Level" in line:
                    seat_type = "State Level"
                    i += 1
                    continue

                # -------- Category header row --------
                # Example: GOPENS GSCS GVJS GSEBCS LOPEN ...
                if line.startswith("GOPENS") or "OPENS" in line:

                    categories = line.split()

                    # Next line must be STAGE + RANKS
                    i += 1
                    if i >= len(lines):
                        break

                    rank_line = lines[i]
                    parts = rank_line.split()

                    # First value = Stage (I / I-Non / VII etc.)
                    stage = parts[0]
                    ranks = parts[1:]

                    # Next line must be Percentiles
                    i += 1
                    if i >= len(lines):
                        break

                    perc_line = lines[i]
                    percentiles = re.findall(r"\(([\d\.]+)\)", perc_line)

                    # Now map column by column correctly
                    count = min(len(categories), len(ranks), len(percentiles))

                    for idx in range(count):

                        rows.append([
                            college,
                            branch,
                            seat_type,
                            stage,
                            categories[idx],
                            ranks[idx],
                            percentiles[idx]
                        ])

                    i += 1
                    continue

                i += 1

    if not rows:
        raise Exception("No valid MHT CET data extracted from PDF")

    df = pd.DataFrame(rows, columns=headers)

    # Cleanup
    df = df.replace("\n", " ", regex=True)
    df = df.apply(
        lambda col: col.str.replace(r"\s+", " ", regex=True).str.strip()
        if col.dtype == "object" else col
    )

    output = io.StringIO()
    df.to_csv(output, index=False, encoding="utf-8-sig")
    output.seek(0)

    return output


def mh_cet_converter(pdf_bytes):

    import pdfplumber
    import pandas as pd
    import re
    import io

    headers = [
        "College Code & Name",
        "Branch Code & Name",
        "Seat Type",
        "Stage",
        "Category",
        "Rank",
        "Percentile"
    ]

    rows = []

    COLLEGE_RE = re.compile(r"^\d{5}\s*-\s*(.+)$")
    BRANCH_RE  = re.compile(r"^\d{10}\s*-\s*(.+)$")

    pdf_stream = io.BytesIO(pdf_bytes)
    with pdfplumber.open(pdf_stream) as pdf:

        college = ""
        branch = ""
        seat_type = ""

        for page in pdf.pages:

            text = page.extract_text()
            if not text:
                continue

            lines = [l.strip() for l in text.split("\n") if l.strip()]
            i = 0

            while i < len(lines):

                line = lines[i]

                # -------- College --------
                m = COLLEGE_RE.match(line)
                if m:
                    college = m.group(0)   # keep full "01002 - College Name"
                    i += 1
                    continue

                # -------- Branch --------
                m = BRANCH_RE.match(line)
                if m:
                    branch = m.group(0)    # keep full "0100219110 - Branch"
                    i += 1
                    continue

                # -------- Seat Type --------
                if "Home University" in line:
                    seat_type = "Home University"
                    i += 1
                    continue
                if "Other Than Home University" in line:
                    seat_type = "Other Than Home University"
                    i += 1
                    continue
                if "State Level" in line:
                    seat_type = "State Level"
                    i += 1
                    continue

                # -------- Category header row --------
                # Example: GOPENS GSCS GVJS GSEBCS LOPEN ...
                if line.startswith("GOPENS") or "OPENS" in line:

                    categories = line.split()

                    # Next line must be STAGE + RANKS
                    i += 1
                    if i >= len(lines):
                        break

                    rank_line = lines[i]
                    parts = rank_line.split()

                    # First value = Stage (I / I-Non / VII etc.)
                    stage = parts[0]
                    ranks = parts[1:]

                    # Next line must be Percentiles
                    i += 1
                    if i >= len(lines):
                        break

                    perc_line = lines[i]
                    percentiles = re.findall(r"\(([\d\.]+)\)", perc_line)

                    # Now map column by column correctly
                    count = min(len(categories), len(ranks), len(percentiles))

                    for idx in range(count):

                        rows.append([
                            college,
                            branch,
                            seat_type,
                            stage,
                            categories[idx],
                            ranks[idx],
                            percentiles[idx]
                        ])

                    i += 1
                    continue

                i += 1

    if not rows:
        raise Exception("No valid MHT CET data extracted from PDF")

    df = pd.DataFrame(rows, columns=headers)

    # Cleanup
    df = df.replace("\n", " ", regex=True)
    df = df.apply(
        lambda col: col.str.replace(r"\s+", " ", regex=True).str.strip()
        if col.dtype == "object" else col
    )

    output = io.StringIO()
    df.to_csv(output, index=False, encoding="utf-8-sig")
    output.seek(0)

    return output


def bams_aiq_converter(pdf_bytes):

    headers = [
        "Sr No",
        "AIR",
        "NEET Roll No",
        "CET Form No",
        "Name",
        "Gender",
        "Category",
        "Quota / Status",
        "College Code & Name"
    ]

    rows = []

    pdf_stream = io.BytesIO(pdf_bytes)
    with pdfplumber.open(pdf_stream) as pdf:

        for page in pdf.pages:

            text = page.extract_text()
            if not text:
                continue

            lines = text.split("\n")

            for line in lines:

                line = line.rstrip()

                # Skip headers / junk
                if not line.strip():
                    continue
                if line.startswith("Sr.") or "Current Selection Details" in line:
                    continue
                if "Printed On" in line or "Legends" in line:
                    continue
                if line.startswith("-"):
                    continue
                if "Admissions to Health Science" in line:
                    continue

                # 🔥 Main row with college
                match = re.match(
                    r"""
                    ^\s*(\d+)\s+                 # Sr No
                    (\d+)\s+                     # AIR
                    (\d+)\s+                     # NEET Roll No
                    (\d+)\s+                     # CET Form No
                    ([A-Z\s]+?)\s+               # Name
                    ([MF])\s+                    # Gender
                    ([A-Z]*)\s*                  # Category
                    (AIQ)\s+                     # Quota
                    (.*\d+:.+)$                  # College (must contain code:)
                    """,
                    line,
                    re.VERBOSE
                )

                if match:
                    rows.append([
                        match.group(1),
                        match.group(2),
                        match.group(3),
                        match.group(4),
                        match.group(5).strip(),
                        match.group(6),
                        match.group(7).strip(),
                        match.group(8).strip(),
                        match.group(9).strip()
                    ])
                    continue

                # 🔥 "Choice Not Available" rows
                match2 = re.match(
                    r"""
                    ^\s*(\d+)\s+                 # Sr No
                    (\d+)\s+                     # AIR
                    (\d+)\s+                     # NEET Roll No
                    (\d+)\s+                     # CET Form No
                    ([A-Z\s]+?)\s+               # Name
                    ([MF])\s+                    # Gender
                    ([A-Z]*)\s*
                    (Choice\s+Not\s+Available\.)$
                    """,
                    line,
                    re.VERBOSE
                )

                if match2:
                    rows.append([
                        match2.group(1),
                        match2.group(2),
                        match2.group(3),
                        match2.group(4),
                        match2.group(5).strip(),
                        match2.group(6),
                        match2.group(7).strip(),
                        match2.group(8).strip(),
                        ""
                    ])
                    continue

    if not rows:
        raise Exception("No valid BAMS AIQ data rows found in PDF")

    df = pd.DataFrame(rows, columns=headers)

    # Final cleanup — no extra spaces
    df = df.replace("\n", " ", regex=True)
    df = df.apply(lambda col: col.str.replace(r"\s+", " ", regex=True).str.strip()
                  if col.dtype == "object" else col)

    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False, encoding="utf-8-sig")
    csv_buffer.seek(0)

    return csv_buffer


def merit_list_aiq_converter(pdf_bytes):

    headers = [
        "Sr No",
        "All India Rank",
        "NEET Roll No",
        "CET Form No",
        "Name",
        "Gender",
        "Category",
        "PWD",
        "Remarks"
    ]

    rows = []

    # Words that always indicate start of REMARKS
    REMARK_WORDS = ["ELIGIBLE", "NOT", "QUALIFIED", "DISQUALIFIED"]

    pdf_stream = io.BytesIO(pdf_bytes)
    with pdfplumber.open(pdf_stream) as pdf:

        buffer = []
        current = None

        for page in pdf.pages:

            text = page.extract_text()
            if not text:
                continue

            lines = [l.strip() for l in text.split("\n") if l.strip()]

            for line in lines:

                # Skip headers / junk
                if "MERIT LIST" in line or "STATE COMMON" in line or "Page" in line:
                    continue
                if line.lower().startswith("sr.no"):
                    continue

                # 🔥 New row starts with 4 numbers
                match = re.match(r"^(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(.*)", line)

                if match:

                    # Save previous row
                    if current:
                        buffer.append(current)

                    current = {
                        "sr": match.group(1),
                        "rank": match.group(2),
                        "roll": match.group(3),
                        "form": match.group(4),
                        "text": match.group(5)
                    }

                else:
                    # Continuation line (broken name etc.)
                    if current:
                        current["text"] += " " + line

        # Save last row
        if current:
            buffer.append(current)

        # 🔥 Parse each full row safely
        for item in buffer:

            text = " ".join(item["text"].split())
            tokens = text.split()

            # Find Gender
            try:
                gender_idx = next(i for i, t in enumerate(tokens) if t in ["M", "F"])
            except:
                continue

            name = " ".join(tokens[:gender_idx])
            gender = tokens[gender_idx]
            after_gender = tokens[gender_idx + 1:]

            if not after_gender:
                continue

            category_tokens = []
            pwd = ""
            remarks_tokens = []

            i = 0
            while i < len(after_gender):
                tok = after_gender[i]

                # Detect PWD
                if tok.upper() == "PWD":
                    pwd = "PWD"
                    i += 1
                    continue

                # Detect start of Remarks
                if tok.upper() in REMARK_WORDS:
                    remarks_tokens = after_gender[i:]
                    break

                # Otherwise still Category (supports multi-word like OBC NCL)
                category_tokens.append(tok)
                i += 1

            category = " ".join(category_tokens)
            remarks = " ".join(remarks_tokens)

            rows.append([
                item["sr"],
                item["rank"],
                item["roll"],
                item["form"],
                name,
                gender,
                category,
                pwd,
                remarks
            ])

    if not rows:
        raise Exception("No valid Merit List AIQ data found in PDF")

    df = pd.DataFrame(rows, columns=headers)

    # Final cleanup — NO EXTRA SPACES, NO MIXING
    df = df.replace("\n", " ", regex=True)
    df = df.apply(lambda col: col.str.replace(r"\s+", " ", regex=True).str.strip()
                  if col.dtype == "object" else col)

    output = io.StringIO()
    df.to_csv(output, index=False, encoding="utf-8-sig")
    output.seek(0)

    return output


def bams_converter(pdf_bytes):

    headers = [
        "Sl No",
        "All India Rank",
        "Course Code",
        "College Name",
        "Course Name",
        "Category",
        "Course Fees",
        "Status"
    ]

    rows = []

    pdf_stream = io.BytesIO(pdf_bytes)
    with pdfplumber.open(pdf_stream) as pdf:

        for page in pdf.pages:

            tables = page.extract_tables()

            if not tables:
                continue

            for table in tables:

                for row in table:

                    # Skip empty or header rows
                    if not row:
                        continue
                    if row[0] and "SL.NO" in row[0]:
                        continue

                    # Expect exactly 8 columns
                    if len(row) < 8:
                        continue

                    sl = row[0]
                    rank = row[1]
                    code = row[2]
                    college = row[3]
                    course = row[4]
                    category = row[5]
                    fees = row[6]
                    status = row[7]

                    # Clean each field (remove line breaks, extra spaces)
                    def clean(x):
                        if not x:
                            return ""
                        return " ".join(x.replace("\n", " ").split())

                    rows.append([
                        clean(sl),
                        clean(rank),
                        clean(code),
                        clean(college),
                        clean(course),
                        clean(category),
                        clean(fees),
                        clean(status)
                    ])

    if not rows:
        raise Exception("No valid BAMS table data found in PDF")

    df = pd.DataFrame(rows, columns=headers)

    output = io.StringIO()
    df.to_csv(output, index=False, encoding="utf-8-sig")
    output.seek(0)

    return output


def bds_fee_structure_converter(pdf_bytes):
    import pdfplumber
    import pandas as pd
    import io
    import re

    headers = [
        "SL.NO",
        "College Code",
        "College Code & College Name",
        "College Type",
        "Govt (G) Fees",
        "Private (P) Fees",
        "OTHER(Q) Fees",
        "NRI(N) Fees"
    ]

    rows = []

    pdf_stream = io.BytesIO(pdf_bytes)
    with pdfplumber.open(pdf_stream) as pdf:
        for page in pdf.pages:

            # Extract table properly
            table = page.extract_table()

            if not table:
                continue

            for row in table:
                # Skip empty rows
                if not row or len(row) < 8:
                    continue

                # Clean each cell
                clean = []
                for cell in row:
                    if cell:
                        cell = cell.replace("\n", " ").strip()
                    else:
                        cell = ""
                    clean.append(cell)

                # Skip header rows (repeated on every page)
                if clean[0].lower().startswith("sl"):
                    continue

                # Sometimes SL.NO column is empty → skip invalid rows
                if not re.match(r"^\d+$", clean[0]):
                    continue

                # Now append FULL row (this captures rows 36 & 37 also)
                rows.append([
                    clean[0],  # SL.NO
                    clean[1],  # College Code
                    clean[2],  # College Name
                    clean[3],  # College Type
                    clean[4],  # Govt Fees
                    clean[5],  # Private Fees
                    clean[6],  # OTHER Fees
                    clean[7],  # NRI Fees
                ])

    # Final safety check
    if not rows:
        raise Exception("No BDS Fee Structure data extracted")

    # Build dataframe
    df = pd.DataFrame(rows, columns=headers)

    # Save to CSV buffer
    output = io.StringIO()
    df.to_csv(output, index=False, encoding="utf-8-sig")
    output.seek(0)

    return output


def bhms_converter(pdf_bytes):

    headers = [
        "SL.NO",
        "All India Rank",
        "Course Code",
        "Name of the College Allotted",
        "Course Name",
        "Allotted Category",
        "Course Fees"
    ]

    rows = []

    pdf_stream = io.BytesIO(pdf_bytes)
    with pdfplumber.open(pdf_stream) as pdf:

        for page in pdf.pages:

            table = page.extract_table({
                "vertical_strategy": "lines",
                "horizontal_strategy": "lines",
                "intersection_tolerance": 5,
                "snap_tolerance": 3,
                "join_tolerance": 3,
                "edge_min_length": 3,
                "min_words_vertical": 1,
                "min_words_horizontal": 1,
            })

            if not table:
                continue

            for row in table:

                # Skip empty rows
                if not row:
                    continue

                # We expect EXACTLY 7 columns
                if len(row) != 7:
                    continue

                clean = []
                for cell in row:
                    if cell is None:
                        clean.append("")
                    else:
                        clean.append(" ".join(cell.replace("\n", " ").split()))

                # First column must be a number (SL.NO)
                if not clean[0].isdigit():
                    continue

                rows.append(clean)

    if len(rows) == 0:
        raise Exception("No valid rows extracted from BHMS PDF")

    df = pd.DataFrame(rows, columns=headers)

    # Final cleanup
    df = df.replace("\n", " ", regex=True)
    df = df.apply(lambda col: col.str.replace(r"\s+", " ", regex=True).str.strip()
                  if col.dtype == "object" else col)

    # 🔥 IMPORTANT: RETURN CSV BUFFER (NOT DATAFRAME)
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False, encoding="utf-8-sig")
    csv_buffer.seek(0)

    return csv_buffer


# ======================================================
# ===================== MAIN ROUTE =====================
# ======================================================

import traceback

@app.route("/convert", methods=["POST"])
def convert():

    try:
        if "file" not in request.files:
            return jsonify({"error": "PDF file required"}), 400

        file = request.files["file"]
        category = " ".join(request.form.get("category", "").lower().split())

        print("CATEGORY:", category)

        pdf_bytes = file.read()

        converters = {
            "consolidated list mcc": consolidated_mcc_admitted_converter,
            "mbbs - bds": mbbs_bds_converter,
            "medical fee": medical_fee_converter,
            "pg medical mcc 1 2025": pg_mcc_converter_1,
            "pg medical mcc 2 2025": pg_mcc_converter_2,
            "provisional merit list": provisional_merit_list_converter,
            "bpth": bpht_converter,
            "bams- bhms": bams_bhms_converter,
            "bams srv": bams_srv_converter,
            "bds": bds_converter,
            "mbbs": mbbs_converter,
            "selection list": selection_list_converter,
            "mh ai": mh_ai_converter,
            "mht cet": mht_cet_converter,
            "mh cet": mh_cet_converter,
            "bams aiq": bams_aiq_converter,
            "merit list aiq": merit_list_aiq_converter,
            "bams": bams_converter,
            "bds fee structure": bds_fee_structure_converter,
            "bhms": bhms_converter
        }

        if category not in converters:
            return jsonify({"error": f"Invalid category: {category}"}), 400

        csv_buffer = converters[category](pdf_bytes)

        return Response(
            csv_buffer.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=converted.csv"}
        )

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500



# ================= REGEX =================
COLLEGE_RE = re.compile(r"(\d{5})\s*-\s*(.+)")
COURSE_RE = re.compile(r"(\d{10})\s*-\s*(.+)")
STATUS_RE = re.compile(r"Status:\s*(.+)")
RANK_PERC_RE = re.compile(r"(\d+)\s*\(([\d.]+)\)")

LEVEL_PATTERNS = [
    re.compile(p, re.I)
    for p in (
        r"Home University Seats Allotted to Home University Candidates",
        r"Other Than Home University Seats Allotted to Other Than Home University Candidates",
        r"Home University Seats Allotted to Other Than Home University Candidates",
        r"State Level",
        r"Maharashtra State Seats",
    )
]

SKIP_LINES = {"D", "i", "Stage", "rState Common Entrance Test Cell"}


# =====================================================
# CORE FUNCTION (REUSED)
# =====================================================
def extract_pdf_to_csv_bytes(pdf_bytes):

    header = [
        "Sr No", "Page", "College Code", "College Name",
        "Course Code", "Course Name", "Status",
        "Level", "Stage", "Category", "Rank", "Percentile"
    ]

    rows = []
    serial = 0

    # -------- SAFE STATE --------
    last_college_code = ""
    last_college_name = ""
    last_course_code = ""
    last_course_name = ""
    last_status = ""
    last_level = ""

    pdf_stream = io.BytesIO(pdf_bytes)
    reader = PyPDF2.PdfReader(pdf_stream)

    with pdfplumber.open(pdf_stream) as pl:

        for page_index, page in enumerate(pl.pages):
            text = reader.pages[page_index].extract_text() or ""
            lines = [
                l.strip()
                for l in text.split("\n")
                if l.strip() and l.strip() not in SKIP_LINES
            ]

            tables = page.extract_tables() or []
            table_idx = 0
            seen_tables = set()

            for idx, line in enumerate(lines):

                # -------- College --------
                m = COLLEGE_RE.match(line)
                if m:
                    last_college_code, last_college_name = m.groups()
                    continue

                # -------- Course --------
                m = COURSE_RE.match(line)
                if m:
                    last_course_code, last_course_name = m.groups()
                    for j in range(idx + 1, min(idx + 6, len(lines))):
                        sm = STATUS_RE.search(lines[j])
                        if sm:
                            last_status = sm.group(1)
                            break
                    continue

                # -------- Level & Tables --------
                for lvl in LEVEL_PATTERNS:
                    if lvl.search(line):
                        last_level = lvl.pattern

                        if table_idx >= len(tables):
                            break

                        tbl = tables[table_idx]
                        table_idx += 1

                        fp = md5(str(tbl[:2]).encode()).hexdigest()
                        if fp in seen_tables:
                            break
                        seen_tables.add(fp)

                        header_row = [
                            " ".join(str(c or "").split())
                            for c in tbl[0]
                        ]

                        category_offset = (
                            1 if header_row[0].upper() in {"STAGE", ""} else 0
                        )

                        for row in tbl[1:]:
                            cells = [
                                " ".join(str(c or "").split())
                                for c in row
                            ]
                            if not cells:
                                continue

                            stage = cells[0].upper()

                            for idx2, cell in enumerate(cells[1:], start=1):
                                if not cell or cell == "-":
                                    continue

                                rm = RANK_PERC_RE.search(cell)
                                if not rm:
                                    continue

                                rank, perc = rm.groups()
                                hdr_idx = idx2 - 1 + category_offset
                                if hdr_idx >= len(header_row):
                                    continue

                                if not all([
                                    last_college_code,
                                    last_course_code,
                                    last_status,
                                    last_level
                                ]):
                                    continue

                                serial += 1
                                rows.append([
                                    serial,
                                    page_index + 1,
                                    last_college_code,
                                    last_college_name,
                                    last_course_code,
                                    last_course_name,
                                    last_status,
                                    last_level,
                                    stage,
                                    header_row[hdr_idx],
                                    rank,
                                    perc,
                                ])
                        break

    # -------- WRITE CSV IN MEMORY --------
    csv_buffer = io.StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerow(header)
    writer.writerows(rows)
    csv_buffer.seek(0)

    return csv_buffer.getvalue()


# =====================================================
# API ENDPOINT
# =====================================================
@app.route("/extract", methods=["POST"])
def extract_api():

    if "file" not in request.files:
        return jsonify({"error": "PDF file required"}), 400

    pdf_file = request.files["file"]

    if not pdf_file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files allowed"}), 400

    pdf_bytes = pdf_file.read()
    csv_data = extract_pdf_to_csv_bytes(pdf_bytes)

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={pdf_file.filename.rsplit('.',1)[0]}.csv"
        }
    )

# if __name__ == "__main__":
#     app.run(host="0.0.0.0", port=5000)

if __name__ == "__main__":
    app.run(debug=True)