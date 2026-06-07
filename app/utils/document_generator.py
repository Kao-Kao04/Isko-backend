"""
Generates printable HTML documents for scholars.
The frontend renders these in a print-ready view — no extra PDF library needed.
"""
from datetime import datetime, timezone


def _now_ph() -> str:
    return datetime.now(timezone.utc).strftime("%B %d, %Y")


_BASE_STYLE = """
<style>
  body { font-family: Arial, sans-serif; max-width: 720px; margin: 40px auto; color: #1a1a1a; font-size: 13.5px; line-height: 1.7; }
  h1 { color: #800000; font-size: 17px; margin-bottom: 4px; }
  h2 { font-size: 14px; color: #333; margin-top: 24px; }
  .header { text-align: center; margin-bottom: 28px; border-bottom: 3px double #800000; padding-bottom: 14px; }
  .header-republic { font-size: 11px; font-weight: bold; color: #333; letter-spacing: 0.04em; margin-bottom: 4px; }
  .header-univ { font-size: 17px; font-weight: bold; color: #800000; margin-bottom: 2px; }
  .header-office { font-size: 11.5px; font-weight: bold; color: #333; margin-bottom: 1px; }
  .header-contact { font-size: 11px; color: #555; margin-top: 6px; }
  .header-tagline { font-size: 10px; font-style: italic; color: #800000; margin-top: 5px; letter-spacing: 0.03em; }
  .field { margin: 7px 0; }
  .label { font-weight: bold; display: inline-block; min-width: 180px; }
  .section { margin-top: 22px; }
  .conditions li { margin: 5px 0; }
  .signature-block { margin-top: 48px; display: flex; gap: 80px; }
  .sig-line { border-top: 1px solid #333; padding-top: 4px; min-width: 200px; font-size: 12px; color: #555; }
  .footer { margin-top: 40px; font-size: 11px; color: #888; text-align: center; border-top: 1px solid #ddd; padding-top: 8px; }
  @media print { body { margin: 0; } }
</style>
"""

_PUP_HEADER = """
<div class="header">
  <div class="header-republic">REPUBLIC OF THE PHILIPPINES</div>
  <div class="header-univ">POLYTECHNIC UNIVERSITY OF THE PHILIPPINES</div>
  <div class="header-office">OFFICE OF THE VICE PRESIDENT FOR STUDENT AFFAIRS AND SERVICES</div>
  <div class="header-office">OFFICE OF SCHOLARSHIP AND FINANCIAL ASSISTANCE</div>
  <div class="header-contact">W-119 PUP A. Mabini Campus, Anonas Street, Sta. Mesa, Manila 1016</div>
  <div class="header-contact">Direct Line: 5335-1764 &nbsp;|&nbsp; Trunk Line: 5335-1787 or 5335-1777 local 339</div>
  <div class="header-contact">Website: www.pup.edu.ph &nbsp;|&nbsp; Email: scholarship@pup.edu.ph</div>
  <div class="header-tagline">THE COUNTRY'S 1st POLYTECHNIC</div>
</div>
"""


def generate_confirmation_letter(
    scholar_name: str,
    student_number: str,
    scholarship_name: str,
    scholarship_type: str | None,
    amount_raw: int | None,
    period: str | None,
    min_gwa: str | None,
    issued_date: str | None = None,
) -> str:
    date = issued_date or _now_ph()
    amount_display = f"₱{amount_raw:,}" if amount_raw else "as provided by the scholarship"
    period_display = period or "one (1) academic year"

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Scholarship Confirmation Letter</title>{_BASE_STYLE}</head>
<body>
{_PUP_HEADER}
<p style="text-align:right;">{date}</p>

<p>Dear <strong>{scholar_name}</strong>,</p>

<p>
  We are pleased to inform you that you have been officially awarded the
  <strong>{scholarship_name}</strong> scholarship for the academic period
  <strong>{period_display}</strong>.
</p>

<div class="section">
  <h2>Scholar Details</h2>
  <div class="field"><span class="label">Name:</span> {scholar_name}</div>
  <div class="field"><span class="label">Student Number:</span> {student_number}</div>
  <div class="field"><span class="label">Scholarship:</span> {scholarship_name}</div>
  {"<div class='field'><span class='label'>Type:</span> " + scholarship_type + "</div>" if scholarship_type else ""}
  <div class="field"><span class="label">Benefit Amount:</span> {amount_display}</div>
  <div class="field"><span class="label">Period:</span> {period_display}</div>
</div>

<div class="section">
  <h2>Maintaining Requirements</h2>
  <ul class="conditions">
    {"<li>Maintain a General Weighted Average (GWA) of <strong>" + min_gwa + "</strong> or better each semester.</li>" if min_gwa else "<li>Maintain good academic standing as required by the scholarship guidelines.</li>"}
    <li>No individual subject grade below <strong>2.5</strong>.</li>
    <li>Must remain enrolled full-time every semester of the scholarship period.</li>
    <li>Must submit a copy of grades and Certificate of Registration (COR) to OSFA at the start of each semester.</li>
    <li>Must comply with all university rules and regulations.</li>
  </ul>
</div>

<p style="margin-top:24px;">
  Failure to meet the above maintaining requirements may result in suspension or termination of the scholarship benefit.
</p>

<p>Congratulations and good luck on your studies!</p>

<div class="signature-block">
  <div>
    <div class="sig-line">Scholar's Signature over Printed Name</div>
  </div>
  <div>
    <div class="sig-line">OSFA Head / Authorized Representative</div>
  </div>
</div>

<div class="footer">
  IskoMo Scholarship Management System — Generated {date} — PUP OSFA
</div>
</body>
</html>"""


def generate_scholar_terms(
    scholar_name: str,
    scholarship_name: str,
    min_gwa: str | None,
    max_semesters: int | None,
    requires_thank_you_letter: bool,
    issued_date: str | None = None,
) -> str:
    date = issued_date or _now_ph()
    sem_text = f"up to <strong>{max_semesters} semesters</strong>" if max_semesters else "for the duration of your course"

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Scholarship Terms & Conditions</title>{_BASE_STYLE}</head>
<body>
{_PUP_HEADER}
<h1 style="text-align:center;">SCHOLARSHIP TERMS AND CONDITIONS</h1>
<p style="text-align:center;color:#555;">{scholarship_name}</p>
<p style="text-align:right;">{date}</p>

<p>This document outlines the terms and conditions governing the <strong>{scholarship_name}</strong>
awarded to <strong>{scholar_name}</strong>.</p>

<div class="section">
  <h2>1. Duration</h2>
  <p>This scholarship is valid {sem_text}, subject to the maintaining requirements below.</p>
</div>

<div class="section">
  <h2>2. Academic Requirements</h2>
  <ul class="conditions">
    {"<li>Maintain a GWA of <strong>" + min_gwa + "</strong> or better (lower number = better grade in PUP's 1.0–5.0 scale).</li>" if min_gwa else ""}
    <li>No individual subject grade below <strong>2.5</strong>.</li>
    <li>Must be enrolled full-time every semester.</li>
    <li>Failure to meet GWA requirement in one semester places the scholar on <strong>probationary status</strong>.</li>
    <li>Failure to meet requirements for two (2) consecutive semesters results in <strong>scholarship termination</strong>.</li>
  </ul>
</div>

<div class="section">
  <h2>3. Obligations</h2>
  <ul class="conditions">
    <li>Submit Certificate of Registration (COR) and official grade slip to OSFA at the start of each semester.</li>
    <li>Notify OSFA immediately of any Leave of Absence, course shifting, or change in enrollment status.</li>
    {"<li>Submit a <strong>thank you letter</strong> addressed to the scholarship provider after each semester benefit is received.</li>" if requires_thank_you_letter else ""}
    <li>Comply with all university policies and uphold the PUP core values.</li>
  </ul>
</div>

<div class="section">
  <h2>4. Termination Grounds</h2>
  <ul class="conditions">
    <li>Failure to maintain academic requirements for two consecutive semesters.</li>
    <li>Voluntarily dropping out of the university.</li>
    <li>Any form of academic dishonesty or disciplinary violation.</li>
    <li>Failure to submit required documents within the prescribed deadline.</li>
  </ul>
</div>

<p style="margin-top:24px;">
  By accepting this scholarship, the scholar agrees to abide by all the terms and conditions stated above.
</p>

<div class="signature-block">
  <div>
    <div class="sig-line">Scholar's Signature over Printed Name / Date</div>
  </div>
  <div>
    <div class="sig-line">Parent/Guardian Signature / Date</div>
  </div>
</div>

<div class="footer">
  IskoMo Scholarship Management System — Generated {date} — PUP OSFA
</div>
</body>
</html>"""


def generate_scholarship_agreement(
    scholar_name: str,
    student_number: str,
    scholarship_name: str,
    period: str | None,
    issued_date: str | None = None,
) -> str:
    date = issued_date or _now_ph()
    period_display = period or "the duration of the scholarship"

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Scholarship Agreement</title>{_BASE_STYLE}</head>
<body>
{_PUP_HEADER}
<h1 style="text-align:center;">SCHOLARSHIP AGREEMENT</h1>
<p style="text-align:center;color:#555;">{scholarship_name}</p>
<p style="text-align:right;">{date}</p>

<p>
  This Agreement is entered into between the <strong>Office of Scholarship and Financial Assistance (OSFA)</strong>
  of the Polytechnic University of the Philippines and <strong>{scholar_name}</strong> (Student Number: <strong>{student_number}</strong>),
  hereinafter referred to as the "Scholar," governing the latter's participation in the
  <strong>{scholarship_name}</strong> for <strong>{period_display}</strong>.
</p>

<div class="section">
  <h2>1. Grant of Scholarship</h2>
  <p>OSFA agrees to extend the benefits of the {scholarship_name} to the Scholar, subject to the
  Scholar's continued compliance with the eligibility and maintaining requirements set by the scholarship provider and the University.</p>
</div>

<div class="section">
  <h2>2. Scholar's Commitment</h2>
  <ul class="conditions">
    <li>Abide by the terms and conditions, academic standards, and maintaining requirements of the scholarship.</li>
    <li>Submit all required compliance documents (e.g., Acceptance Form, Bank Details, Maintaining Conditions Form) within the prescribed period.</li>
    <li>Promptly inform OSFA of any change in enrollment, academic, or personal status that may affect scholarship eligibility.</li>
    <li>Uphold the good name of the University and the scholarship provider at all times.</li>
  </ul>
</div>

<div class="section">
  <h2>3. Effectivity and Termination</h2>
  <p>This Agreement takes effect upon signing by both parties and remains in force for {period_display},
  unless earlier terminated for failure to comply with the maintaining requirements or for any of the
  termination grounds stated in the Scholarship Terms and Conditions.</p>
</div>

<p style="margin-top:24px;">
  By signing below, the Scholar acknowledges having read, understood, and agreed to be bound by this Agreement.
</p>

<div class="signature-block">
  <div>
    <div class="sig-line">Scholar's Signature over Printed Name / Date</div>
  </div>
  <div>
    <div class="sig-line">OSFA Head / Authorized Representative / Date</div>
  </div>
</div>

<div class="footer">
  IskoMo Scholarship Management System — Generated {date} — PUP OSFA
</div>
</body>
</html>"""


def generate_acceptance_form(
    scholar_name: str,
    student_number: str,
    scholarship_name: str,
    period: str | None,
    issued_date: str | None = None,
) -> str:
    date = issued_date or _now_ph()
    period_display = period or "the academic period stated in the award notice"

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Scholarship Acceptance Form</title>{_BASE_STYLE}</head>
<body>
{_PUP_HEADER}
<h1 style="text-align:center;">SCHOLARSHIP ACCEPTANCE FORM</h1>
<p style="text-align:center;color:#555;">{scholarship_name}</p>
<p style="text-align:right;">{date}</p>

<div class="section">
  <h2>Scholar Details</h2>
  <div class="field"><span class="label">Name:</span> {scholar_name}</div>
  <div class="field"><span class="label">Student Number:</span> {student_number}</div>
  <div class="field"><span class="label">Scholarship:</span> {scholarship_name}</div>
  <div class="field"><span class="label">Period:</span> {period_display}</div>
</div>

<div class="section">
  <h2>Statement of Acceptance</h2>
  <p>
    I, <strong>{scholar_name}</strong>, hereby formally <strong>ACCEPT</strong> the award of the
    <strong>{scholarship_name}</strong> for {period_display}. I understand that this scholarship
    is granted subject to the terms and conditions and maintaining requirements set by OSFA and the
    scholarship provider, and that I am responsible for complying with all submission deadlines and
    academic standards required to retain this benefit.
  </p>
  <p>
    I further understand that failure to comply with the above may result in the suspension or
    termination of this scholarship.
  </p>
</div>

<div class="signature-block">
  <div>
    <div class="sig-line">Scholar's Signature over Printed Name / Date</div>
  </div>
  <div>
    <div class="sig-line">OSFA Head / Authorized Representative / Date</div>
  </div>
</div>

<div class="footer">
  IskoMo Scholarship Management System — Generated {date} — PUP OSFA
</div>
</body>
</html>"""


def generate_bank_details_form(
    scholar_name: str,
    student_number: str,
    scholarship_name: str,
    issued_date: str | None = None,
) -> str:
    date = issued_date or _now_ph()
    blank = "<span style='display:inline-block; min-width:260px; border-bottom:1px solid #888;'>&nbsp;</span>"

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Bank Details / Account Information Form</title>{_BASE_STYLE}</head>
<body>
{_PUP_HEADER}
<h1 style="text-align:center;">BANK DETAILS / ACCOUNT INFORMATION FORM</h1>
<p style="text-align:center;color:#555;">{scholarship_name}</p>
<p style="text-align:right;">{date}</p>

<div class="section">
  <h2>Scholar Details</h2>
  <div class="field"><span class="label">Name:</span> {scholar_name}</div>
  <div class="field"><span class="label">Student Number:</span> {student_number}</div>
  <div class="field"><span class="label">Scholarship:</span> {scholarship_name}</div>
</div>

<p>
  Please complete the fields below with your personal bank or e-wallet account information.
  This account will be used by the Accounting Office to release your scholarship benefit/allowance.
</p>

<div class="section">
  <h2>Account Information</h2>
  <div class="field"><span class="label">Bank / E-Wallet Name:</span> {blank}</div>
  <div class="field"><span class="label">Account Holder's Name:</span> {blank}</div>
  <div class="field"><span class="label">Account Number:</span> {blank}</div>
  <div class="field"><span class="label">Branch (if applicable):</span> {blank}</div>
  <div class="field"><span class="label">Mobile Number Linked to Account:</span> {blank}</div>
</div>

<p style="margin-top:16px;">
  I certify that the account information provided above is true and correct, and that it belongs to me.
  I understand that any error in the details I provide may delay or prevent the release of my scholarship benefit.
</p>

<div class="signature-block">
  <div>
    <div class="sig-line">Scholar's Signature over Printed Name / Date</div>
  </div>
  <div>
    <div class="sig-line">Verified by: OSFA Staff / Date</div>
  </div>
</div>

<div class="footer">
  IskoMo Scholarship Management System — Generated {date} — PUP OSFA
</div>
</body>
</html>"""


def generate_maintaining_conditions_form(
    scholar_name: str,
    student_number: str,
    scholarship_name: str,
    min_gwa: str | None,
    issued_date: str | None = None,
) -> str:
    date = issued_date or _now_ph()

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Maintaining Conditions Form</title>{_BASE_STYLE}</head>
<body>
{_PUP_HEADER}
<h1 style="text-align:center;">MAINTAINING CONDITIONS FORM</h1>
<p style="text-align:center;color:#555;">{scholarship_name}</p>
<p style="text-align:right;">{date}</p>

<div class="section">
  <h2>Scholar Details</h2>
  <div class="field"><span class="label">Name:</span> {scholar_name}</div>
  <div class="field"><span class="label">Student Number:</span> {student_number}</div>
  <div class="field"><span class="label">Scholarship:</span> {scholarship_name}</div>
</div>

<div class="section">
  <h2>Conditions for Continued Eligibility</h2>
  <p>To continue receiving the benefits of this scholarship, the Scholar must maintain the following:</p>
  <ul class="conditions">
    {"<li>Maintain a General Weighted Average (GWA) of <strong>" + min_gwa + "</strong> or better each semester.</li>" if min_gwa else "<li>Maintain good academic standing as required by the scholarship guidelines.</li>"}
    <li>No individual subject grade below <strong>2.5</strong>.</li>
    <li>Remain enrolled full-time every semester of the scholarship period.</li>
    <li>Submit a copy of grades and Certificate of Registration (COR) to OSFA at the start of each semester.</li>
    <li>Promptly report any Leave of Absence, course shifting, or change in enrollment status to OSFA.</li>
    <li>Comply with all university rules, regulations, and the scholarship's specific requirements.</li>
  </ul>
</div>

<p style="margin-top:24px;">
  By signing below, I, <strong>{scholar_name}</strong>, acknowledge that I have read and understood
  the above maintaining conditions, and that failure to comply may result in the suspension or
  termination of my scholarship.
</p>

<div class="signature-block">
  <div>
    <div class="sig-line">Scholar's Signature over Printed Name / Date</div>
  </div>
  <div>
    <div class="sig-line">OSFA Head / Authorized Representative / Date</div>
  </div>
</div>

<div class="footer">
  IskoMo Scholarship Management System — Generated {date} — PUP OSFA
</div>
</body>
</html>"""
