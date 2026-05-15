from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from sqlalchemy.orm import selectinload
from app.models.scholarship import Scholarship, ScholarshipRequirement, ScholarshipStatus
from app.models.application import Application, ApplicationStatus
from app.models.user import User, UserRole
from app.schemas.scholarship import ScholarshipCreate, ScholarshipUpdate, ScholarshipStatusUpdate
from app.exceptions import NotFoundError, ForbiddenError, ValidationError

# Allowed scholarship status transitions — prevents arbitrary jumps
_STATUS_TRANSITIONS: dict[ScholarshipStatus, list[ScholarshipStatus]] = {
    ScholarshipStatus.draft:     [ScholarshipStatus.active, ScholarshipStatus.archived],
    ScholarshipStatus.active:    [ScholarshipStatus.closed],
    ScholarshipStatus.closed:    [ScholarshipStatus.archived, ScholarshipStatus.active],
    ScholarshipStatus.archived:  [],  # terminal
}


def _check_dept_owns_scholarship(scholarship: Scholarship, staff: User) -> None:
    """OSFA staff can only modify scholarships within their department."""
    if staff.role == UserRole.osfa_staff and staff.department and scholarship.category != staff.department:
        raise ForbiddenError("This scholarship belongs to a different department")


def _with_requirements(q):
    return q.options(selectinload(Scholarship.requirements))


async def _attach_applicants_counts(db: AsyncSession, scholarships: list) -> None:
    if not scholarships:
        return
    ids = [s.id for s in scholarships]
    rows = await db.execute(
        select(Application.scholarship_id, func.count(Application.id))
        .where(
            Application.scholarship_id.in_(ids),
            Application.status.notin_([ApplicationStatus.withdrawn]),
        )
        .group_by(Application.scholarship_id)
    )
    counts = {row[0]: row[1] for row in rows}
    for s in scholarships:
        s.applicants_count = counts.get(s.id, 0)


async def _auto_close_expired(db: AsyncSession) -> None:
    """Close active scholarships whose deadline has passed or whose slots are all filled."""
    now = datetime.now(timezone.utc)

    # Close past-deadline scholarships
    await db.execute(
        update(Scholarship)
        .where(Scholarship.status == ScholarshipStatus.active, Scholarship.deadline < now)
        .values(status=ScholarshipStatus.closed)
    )

    # Close fully-booked scholarships (slots not null and all filled with non-withdrawn apps)
    filled_subq = (
        select(Application.scholarship_id, func.count(Application.id).label("cnt"))
        .where(Application.status.notin_([ApplicationStatus.withdrawn]))
        .group_by(Application.scholarship_id)
        .subquery()
    )
    await db.execute(
        update(Scholarship)
        .where(
            Scholarship.status == ScholarshipStatus.active,
            Scholarship.slots.isnot(None),
            Scholarship.id.in_(
                select(filled_subq.c.scholarship_id)
                .where(filled_subq.c.cnt >= Scholarship.slots)
            ),
        )
        .values(status=ScholarshipStatus.closed)
    )
    await db.commit()


async def list_scholarships(db: AsyncSession, user: User, page: int, page_size: int):
    base = select(Scholarship)
    if user.role == UserRole.student:
        base = base.where(Scholarship.status == ScholarshipStatus.active)
    elif user.role == UserRole.osfa_staff and user.department:
        base = base.where(Scholarship.category == user.department.value)

    base = base.order_by(Scholarship.created_at.desc())
    count_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = count_result.scalar()

    q = _with_requirements(base).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    scholarships = list(result.scalars().all())
    await _attach_applicants_counts(db, scholarships)
    return scholarships, total


async def get_scholarship(db: AsyncSession, scholarship_id: int, user: User | None = None) -> Scholarship:
    result = await db.execute(
        _with_requirements(select(Scholarship).where(Scholarship.id == scholarship_id))
    )
    scholarship = result.scalar_one_or_none()
    if not scholarship:
        raise NotFoundError("Scholarship", scholarship_id)
    # Students cannot view draft or archived scholarships
    if user and user.role == UserRole.student:
        if scholarship.status not in (ScholarshipStatus.active, ScholarshipStatus.closed):
            raise NotFoundError("Scholarship", scholarship_id)
    await _attach_applicants_counts(db, [scholarship])
    return scholarship


async def create_scholarship(db: AsyncSession, data: ScholarshipCreate, user: User) -> Scholarship:
    # OSFA staff always create within their department; super_admin can specify freely
    if user.role == UserRole.osfa_staff and user.department:
        data.category = user.department.value
    if not data.category:
        data.category = "public"

    # Build from all schema fields dynamically — never miss a new field again
    create_data = data.model_dump(exclude={"requirements"})
    create_data["created_by"] = user.id

    scholarship = Scholarship(**create_data)
    db.add(scholarship)
    await db.flush()

    for req in data.requirements:
        db.add(ScholarshipRequirement(
            scholarship_id=scholarship.id,
            name=req.name,
            description=req.description,
            is_required=req.is_required,
        ))

    await db.commit()
    return await get_scholarship(db, scholarship.id)


async def update_scholarship(db: AsyncSession, scholarship_id: int, data: ScholarshipUpdate, user: User) -> Scholarship:
    scholarship = await get_scholarship(db, scholarship_id)
    _check_dept_owns_scholarship(scholarship, user)

    update_data = data.model_dump(exclude_unset=True)
    requirements_data = update_data.pop('requirements', None)
    for field, value in update_data.items():
        setattr(scholarship, field, value)
    if requirements_data is not None:
        for req in scholarship.requirements:
            await db.delete(req)
        for req in requirements_data:
            db.add(ScholarshipRequirement(
                scholarship_id=scholarship_id,
                name=req['name'],
                description=req.get('description'),
                is_required=req.get('is_required', True),
            ))
    await db.commit()
    return await get_scholarship(db, scholarship_id)


async def update_status(db: AsyncSession, scholarship_id: int, data: ScholarshipStatusUpdate, user: User) -> Scholarship:
    scholarship = await get_scholarship(db, scholarship_id)
    _check_dept_owns_scholarship(scholarship, user)

    allowed = _STATUS_TRANSITIONS.get(scholarship.status, [])
    if data.status not in allowed:
        raise ValidationError(
            f"Cannot transition scholarship status from '{scholarship.status}' to '{data.status}'. "
            f"Allowed: {[s.value for s in allowed] or 'none (terminal state)'}"
        )

    scholarship.status = data.status
    await db.commit()
    return await get_scholarship(db, scholarship_id)


async def delete_scholarship(db: AsyncSession, scholarship_id: int, user: User) -> None:
    result = await db.execute(
        select(Scholarship)
        .options(selectinload(Scholarship.requirements))
        .where(Scholarship.id == scholarship_id)
    )
    scholarship = result.scalar_one_or_none()
    if not scholarship:
        raise NotFoundError("Scholarship", scholarship_id)

    _check_dept_owns_scholarship(scholarship, user)

    # Prevent deletion if any non-withdrawn applications exist
    app_count_result = await db.execute(
        select(func.count(Application.id)).where(
            Application.scholarship_id == scholarship_id,
            Application.status.notin_([ApplicationStatus.withdrawn]),
        )
    )
    active_app_count = app_count_result.scalar()
    if active_app_count > 0:
        raise ValidationError(
            f"Cannot delete this scholarship — it has {active_app_count} active application(s). "
            "Archive it instead, or withdraw all applications first."
        )

    await db.delete(scholarship)
    await db.commit()


async def duplicate_scholarship(db: AsyncSession, scholarship_id: int, user: User) -> Scholarship:
    original = await get_scholarship(db, scholarship_id)
    _check_dept_owns_scholarship(original, user)

    clone = Scholarship(
        name=f"{original.name} (Copy)",
        description=original.description,
        slots=original.slots,
        deadline=original.deadline,
        eligible_colleges=original.eligible_colleges,
        eligible_programs=original.eligible_programs,
        eligible_year_levels=original.eligible_year_levels,
        min_gwa=original.min_gwa,
        category=original.category,
        status=ScholarshipStatus.draft,
        created_by=user.id,
    )
    db.add(clone)
    await db.flush()

    for req in original.requirements:
        db.add(ScholarshipRequirement(
            scholarship_id=clone.id,
            name=req.name,
            description=req.description,
            is_required=req.is_required,
        ))

    await db.commit()
    return await get_scholarship(db, clone.id)


async def generate_report_html(db: AsyncSession, scholarship_id: int) -> str:
    """Return a printable HTML report for a specific scholarship."""
    from sqlalchemy.orm import selectinload as _sil
    from app.models.user import User as _User, StudentProfile as _SP

    result = await db.execute(
        select(Scholarship)
        .options(selectinload(Scholarship.requirements))
        .where(Scholarship.id == scholarship_id)
    )
    sch = result.scalar_one_or_none()
    if not sch:
        raise NotFoundError("Scholarship", scholarship_id)

    # Fetch all non-withdrawn applications with student info
    apps_result = await db.execute(
        select(Application)
        .options(
            _sil(Application.student).selectinload(_User.student_profile),
        )
        .where(
            Application.scholarship_id == scholarship_id,
            Application.status.notin_([ApplicationStatus.withdrawn]),
        )
        .order_by(Application.submitted_at)
    )
    apps = apps_result.scalars().all()

    # Tally
    total      = len(apps)
    approved   = sum(1 for a in apps if a.status == ApplicationStatus.approved)
    rejected   = sum(1 for a in apps if a.status == ApplicationStatus.rejected)
    pending    = sum(1 for a in apps if a.status == ApplicationStatus.pending)
    incomplete = sum(1 for a in apps if a.status == ApplicationStatus.incomplete)

    def fmt_date(d) -> str:
        if not d:
            return "—"
        if hasattr(d, 'strftime'):
            return d.strftime("%B %d, %Y")
        return str(d)

    def student_name(app) -> str:
        if app.student and app.student.student_profile:
            p = app.student.student_profile
            return f"{p.last_name}, {p.first_name} {p.middle_name or ''}".strip()
        return f"Student #{app.student_id}"

    def student_num(app) -> str:
        if app.student and app.student.student_profile:
            return app.student.student_profile.student_number or "—"
        return "—"

    def email(app) -> str:
        return app.student.email if app.student else "—"

    STATUS_BADGE = {
        "approved":   ('<span style="color:#15803d;font-weight:700">Approved</span>'),
        "rejected":   ('<span style="color:#dc2626;font-weight:700">Rejected</span>'),
        "pending":    ('<span style="color:#d97706;font-weight:700">Pending</span>'),
        "incomplete": ('<span style="color:#ea580c;font-weight:700">Incomplete</span>'),
    }

    rows = "".join(
        f"""<tr style="border-bottom:1px solid #f3f4f6;">
              <td style="padding:10px 12px;font-size:13px;">{i+1}</td>
              <td style="padding:10px 12px;font-size:13px;font-weight:600;">{student_name(a)}</td>
              <td style="padding:10px 12px;font-size:13px;">{student_num(a)}</td>
              <td style="padding:10px 12px;font-size:13px;">{email(a)}</td>
              <td style="padding:10px 12px;font-size:13px;">{fmt_date(a.submitted_at)}</td>
              <td style="padding:10px 12px;font-size:13px;">{STATUS_BADGE.get(a.status.value if hasattr(a.status,'value') else str(a.status), str(a.status))}</td>
            </tr>"""
        for i, a in enumerate(apps)
    )

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8"/>
  <title>Scholarship Report — {sch.name}</title>
  <style>
    * {{ box-sizing:border-box; margin:0; padding:0; }}
    body {{ font-family:'Segoe UI',Arial,sans-serif; color:#111827; padding:40px 48px; }}
    h1 {{ font-size:22px; font-weight:800; color:#7f1d1d; margin-bottom:4px; }}
    .sub {{ font-size:13px; color:#6b7280; margin-bottom:28px; }}
    .meta {{ display:flex; gap:32px; flex-wrap:wrap; margin-bottom:28px; padding:20px 24px;
             background:#fafafa; border:1px solid #e5e7eb; border-radius:10px; }}
    .meta-item {{ display:flex; flex-direction:column; gap:3px; }}
    .meta-label {{ font-size:10px; font-weight:700; color:#9ca3af; text-transform:uppercase; letter-spacing:.06em; }}
    .meta-value {{ font-size:14px; font-weight:600; color:#111827; }}
    .stats {{ display:flex; gap:16px; flex-wrap:wrap; margin-bottom:28px; }}
    .stat {{ flex:1; min-width:100px; padding:16px 20px; border-radius:10px; border:1px solid #e5e7eb; text-align:center; }}
    .stat-num {{ font-size:28px; font-weight:800; line-height:1; }}
    .stat-label {{ font-size:11px; color:#6b7280; margin-top:4px; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    thead tr {{ background:#7f1d1d; color:#fff; }}
    thead th {{ padding:11px 12px; text-align:left; font-size:12px; font-weight:700; }}
    tbody tr:nth-child(even) {{ background:#fafafa; }}
    .footer {{ margin-top:32px; padding-top:16px; border-top:1px solid #e5e7eb;
               font-size:11px; color:#9ca3af; text-align:right; }}
    @media print {{ body {{ padding:20px 24px; }} }}
  </style>
</head>
<body>
  <div style="display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:6px;">
    <div>
      <h1>Scholarship Report</h1>
      <div class="sub">{sch.name} &nbsp;·&nbsp; Generated {fmt_date(datetime.now(timezone.utc))}</div>
    </div>
    <div style="font-size:11px;color:#9ca3af;text-align:right;">IskoMo — OSFA Portal<br/>PUP Scholarship Management System</div>
  </div>

  <div class="meta">
    <div class="meta-item"><span class="meta-label">Type</span><span class="meta-value">{sch.scholarship_type or '—'}</span></div>
    <div class="meta-item"><span class="meta-label">Category</span><span class="meta-value">{(sch.category.value if hasattr(sch.category,'value') else str(sch.category)).title() if sch.category else '—'}</span></div>
    <div class="meta-item"><span class="meta-label">Slots</span><span class="meta-value">{sch.slots or 'Unlimited'}</span></div>
    <div class="meta-item"><span class="meta-label">Amount</span><span class="meta-value">{'₱{:,}'.format(sch.amount_raw) if sch.amount_raw else '—'} {sch.period or ''}</span></div>
    <div class="meta-item"><span class="meta-label">Deadline</span><span class="meta-value">{fmt_date(sch.deadline)}</span></div>
    <div class="meta-item"><span class="meta-label">Status</span><span class="meta-value">{(sch.status.value if hasattr(sch.status,'value') else str(sch.status)).upper()}</span></div>
  </div>

  <div class="stats">
    <div class="stat"><div class="stat-num" style="color:#374151;">{total}</div><div class="stat-label">Total Applications</div></div>
    <div class="stat"><div class="stat-num" style="color:#15803d;">{approved}</div><div class="stat-label">Approved / Scholars</div></div>
    <div class="stat"><div class="stat-num" style="color:#dc2626;">{rejected}</div><div class="stat-label">Rejected</div></div>
    <div class="stat"><div class="stat-num" style="color:#d97706;">{pending}</div><div class="stat-label">Pending</div></div>
    <div class="stat"><div class="stat-num" style="color:#ea580c;">{incomplete}</div><div class="stat-label">Incomplete</div></div>
  </div>

  <table>
    <thead>
      <tr>
        <th>#</th><th>Full Name</th><th>Student No.</th>
        <th>Email</th><th>Submitted</th><th>Status</th>
      </tr>
    </thead>
    <tbody>{rows if rows else '<tr><td colspan="6" style="padding:24px;text-align:center;color:#9ca3af;">No applications yet.</td></tr>'}</tbody>
  </table>

  <div class="footer">
    Report generated by IskoMo OSFA Portal &nbsp;·&nbsp; {fmt_date(datetime.now(timezone.utc))} &nbsp;·&nbsp; Scholarship ID #{scholarship_id}
  </div>
  <script>window.onload = () => window.print();</script>
</body>
</html>"""
    return html
