"""
Generates printable HTML documents for scholars.
The frontend renders these in a print-ready view — no extra PDF library needed.
"""
from datetime import datetime, timezone


def _now_ph() -> str:
    return datetime.now(timezone.utc).strftime("%B %d, %Y")


_BASE_STYLE = """
<style>
  body { font-family: Arial, sans-serif; max-width: 680px; margin: 40px auto; color: #1a1a1a; font-size: 14px; line-height: 1.6; }
  h1 { color: #800000; font-size: 18px; margin-bottom: 4px; }
  h2 { font-size: 15px; color: #333; margin-top: 24px; }
  .header { text-align: center; margin-bottom: 32px; border-bottom: 2px solid #800000; padding-bottom: 16px; }
  .header img { height: 60px; }
  .school { font-size: 13px; color: #555; }
  .field { margin: 8px 0; }
  .label { font-weight: bold; display: inline-block; min-width: 180px; }
  .section { margin-top: 24px; }
  .conditions li { margin: 6px 0; }
  .signature-block { margin-top: 48px; display: flex; gap: 80px; }
  .sig-line { border-top: 1px solid #333; padding-top: 4px; min-width: 200px; font-size: 12px; color: #555; }
  .footer { margin-top: 40px; font-size: 11px; color: #888; text-align: center; border-top: 1px solid #ddd; padding-top: 8px; }
  @media print { body { margin: 0; } }
</style>
"""

_PUP_HEADER = """
<div class="header">
  <div style="font-weight:bold;font-size:16px;color:#800000;">POLYTECHNIC UNIVERSITY OF THE PHILIPPINES</div>
  <div class="school">Office of Student Financial Assistance (OSFA)</div>
  <div class="school">A. Mabini Campus, Sta. Mesa, Manila</div>
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
