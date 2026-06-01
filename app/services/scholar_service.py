from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from app.models.scholar import Scholar, ScholarStatus, SemesterRecord, ScholarStatusLog, SCHOLAR_STATUS_TRANSITIONS
from app.models.user import User, UserRole
from app.schemas.scholar import ScholarStatusUpdate, SemesterRecordCreate, SemesterRecordUpdate
from app.exceptions import NotFoundError, ValidationError, ForbiddenError


def _check_dept_scholar(scholar: Scholar, actor: User) -> None:
    """Raise ForbiddenError if an OSFA staff member tries to mutate a scholar outside their dept."""
    if actor.role == UserRole.osfa_staff and actor.department and scholar.scholarship:
        if scholar.scholarship.category and scholar.scholarship.category.value != actor.department.value:
            raise ForbiddenError()


async def get_scholars_by_student(db: AsyncSession, student_id: int) -> list[Scholar]:
    result = await db.execute(
        select(Scholar)
        .options(selectinload(Scholar.semester_records), selectinload(Scholar.status_logs))
        .where(Scholar.student_id == student_id)
    )
    return list(result.scalars().all())


async def list_scholars(db: AsyncSession, user: User | None, page: int, page_size: int):
    from app.models.scholarship import Scholarship
    from app.models.user import UserRole, StudentProfile

    sch_alias = Scholarship.__table__.alias("sch")
    sp_alias  = StudentProfile.__table__.alias("sp")

    q = (
        select(
            Scholar,
            (sp_alias.c.first_name + " " + sp_alias.c.last_name).label("student_name"),
            sch_alias.c.name.label("scholarship_name"),
        )
        .options(
            selectinload(Scholar.semester_records),
            selectinload(Scholar.status_logs),
        )
        .outerjoin(sp_alias,  sp_alias.c.user_id == Scholar.student_id)
        .outerjoin(sch_alias, sch_alias.c.id == Scholar.scholarship_id)
    )
    if user and user.role == UserRole.osfa_staff and user.department:
        q = q.where(sch_alias.c.category == user.department.value)

    count_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = count_result.scalar()
    q = q.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(q)).all()

    scholars = []
    for row in rows:
        s = row[0]
        s.student_name    = row[1]
        s.scholarship_name = row[2]
        scholars.append(s)
    return scholars, total


async def get_scholar(db: AsyncSession, scholar_id: int) -> Scholar:
    from app.models.scholarship import Scholarship as _Scholarship
    result = await db.execute(
        select(Scholar)
        .options(
            selectinload(Scholar.semester_records),
            selectinload(Scholar.status_logs),
            selectinload(Scholar.scholarship),
        )
        .where(Scholar.id == scholar_id)
    )
    scholar = result.scalar_one_or_none()
    if not scholar:
        raise NotFoundError("Scholar", scholar_id)
    return scholar


async def update_scholar_status(
    db: AsyncSession,
    scholar_id: int,
    data: ScholarStatusUpdate,
    actor: User | None = None,
) -> Scholar:
    scholar = await get_scholar(db, scholar_id)
    if actor:
        _check_dept_scholar(scholar, actor)
    old_status = scholar.status

    allowed = SCHOLAR_STATUS_TRANSITIONS.get(old_status, [])
    if data.status not in allowed:
        raise ValidationError(
            f"Cannot transition scholar from '{old_status}' to '{data.status}'. "
            f"Allowed: {[s.value for s in allowed] or 'none (terminal state)'}"
        )

    scholar.status = data.status
    if data.is_graduating is not None:
        scholar.is_graduating = data.is_graduating
    if data.expected_graduation is not None:
        scholar.expected_graduation = data.expected_graduation

    log = ScholarStatusLog(
        scholar_id=scholar_id,
        from_status=old_status,
        to_status=data.status,
        actor_id=actor.id if actor else None,
        reason=data.reason,
    )
    db.add(log)

    # Fetch scholarship name for notification messages
    from app.models.scholarship import Scholarship as _Sch
    sch_result = await db.execute(select(_Sch).where(_Sch.id == scholar.scholarship_id))
    sch = sch_result.scalar_one_or_none()
    sch_name = sch.name if sch else "your scholarship"

    # In-app notification for every status change
    _NOTIF_MAP: dict[str, tuple[str, str]] = {
        "active":       ("Scholarship Status: Active",
                         f"Your scholarship ({sch_name}) is now active. Keep up the good work!"),
        "probationary": ("Scholarship Status: Probationary",
                         f"Your scholarship ({sch_name}) has been placed on probationary status. "
                         "Please maintain your academic performance to avoid suspension."),
        "under_review": ("Scholarship Under Review",
                         f"Your scholarship ({sch_name}) is currently under review by OSFA. "
                         "You will be notified once a decision is made."),
        "on_leave":     ("Scholarship Leave Approved",
                         f"Your leave of absence for {sch_name} has been recorded. "
                         "Please re-enroll and notify OSFA when you return."),
        "suspended":    ("Scholarship Suspended",
                         f"Your scholarship ({sch_name}) has been suspended. "
                         f"{('Reason: ' + data.reason) if data.reason else 'Please contact OSFA for more information.'}"),
        "terminated":   ("Scholarship Terminated",
                         f"Your scholarship ({sch_name}) has been terminated. "
                         f"{('Reason: ' + data.reason) if data.reason else 'Please contact OSFA for more information.'}"),
        "graduated":    ("Congratulations, Scholar!",
                         f"You have successfully completed your scholarship program ({sch_name}). "
                         "Thank you for your dedication and hard work!"),
    }

    notif_key = data.status.value
    if notif_key in _NOTIF_MAP:
        from app.services.notification_service import create_notification
        title, body = _NOTIF_MAP[notif_key]
        try:
            await create_notification(db, scholar.student_id, title, body, scholar.application_id)
        except Exception:
            pass  # notification failure must not block the status update

    # Email for termination (already existed)
    if data.status.value == "terminated":
        from app.utils.email import send_scholar_terminated_email
        from app.models.user import User as UserModel
        user_result = await db.execute(select(UserModel).where(UserModel.id == scholar.student_id))
        user = user_result.scalar_one_or_none()
        if user:
            try:
                await send_scholar_terminated_email(user.email, data.reason)
            except Exception:
                pass

    await db.commit()
    return await get_scholar(db, scholar_id)


async def _evaluate_retention(db: AsyncSession, scholar: Scholar, gwa: str | None, has_grade_below_2_5: bool) -> None:
    """Auto-set scholar status based on GWA and grade flag after a semester record is saved."""
    from app.models.scholarship import Scholarship
    sch_result = await db.execute(select(Scholarship).where(Scholarship.id == scholar.scholarship_id))
    scholarship = sch_result.scalar_one_or_none()
    min_gwa = float(scholarship.min_gwa) if (scholarship and scholarship.min_gwa) else 2.0

    if not gwa:
        return  # no GWA submitted yet — nothing to evaluate

    try:
        student_gwa = float(gwa)
    except (ValueError, TypeError):
        return

    # In PUP grading: lower number = better. 1.0 is best, 5.0 is failing.
    gwa_fails = student_gwa > min_gwa
    grade_flag_fails = has_grade_below_2_5

    current = scholar.status
    if current in (ScholarStatus.terminated, ScholarStatus.graduated):
        return  # terminal — never auto-change

    if gwa_fails or grade_flag_fails:
        if current == ScholarStatus.active:
            allowed = SCHOLAR_STATUS_TRANSITIONS.get(current, [])
            if ScholarStatus.probationary in allowed:
                reason = []
                if gwa_fails:
                    reason.append(f"GWA {gwa} does not meet the required {min_gwa}")
                if grade_flag_fails:
                    reason.append("has subject grade below 2.5")
                reason_str = "; ".join(reason)
                log = ScholarStatusLog(
                    scholar_id=scholar.id,
                    from_status=current,
                    to_status=ScholarStatus.probationary,
                    actor_id=None,
                    reason="Auto-evaluated: " + reason_str,
                )
                db.add(log)
                scholar.status = ScholarStatus.probationary
                try:
                    from app.services.notification_service import create_notification
                    from app.models.scholarship import Scholarship as _Sch
                    _sch = (await db.execute(select(_Sch).where(_Sch.id == scholar.scholarship_id))).scalar_one_or_none()
                    _sch_name = str(_sch.name) if _sch else "your scholarship"
                    await create_notification(
                        db, scholar.student_id,
                        "Scholarship Status: Probationary",
                        f"Your scholarship ({_sch_name}) has been placed on probationary status due to: {reason_str}. Please maintain your academic performance.",
                        scholar.application_id,
                    )
                except Exception:
                    pass
                try:
                    from app.utils.email import send_probationary_email
                    _u = (await db.execute(select(User).where(User.id == scholar.student_id))).scalar_one_or_none()
                    if _u:
                        await send_probationary_email(str(_u.email), _sch_name, reason_str)
                except Exception:
                    pass
    else:
        # GWA and grades are good — lift probation if currently on it
        if current == ScholarStatus.probationary:
            log = ScholarStatusLog(
                scholar_id=scholar.id,
                from_status=current,
                to_status=ScholarStatus.active,
                actor_id=None,
                reason=f"Auto-evaluated: GWA {gwa} meets requirement; no failing grades",
            )
            db.add(log)
            scholar.status = ScholarStatus.active
            try:
                from app.services.notification_service import create_notification
                from app.models.scholarship import Scholarship as _Sch
                _sch = (await db.execute(select(_Sch).where(_Sch.id == scholar.scholarship_id))).scalar_one_or_none()
                _sch_name = str(_sch.name) if _sch else "your scholarship"
                await create_notification(
                    db, scholar.student_id,
                    "Probationary Status Lifted",
                    f"Great news! Your scholarship ({_sch_name}) probationary status has been lifted. You are now an active scholar again.",
                    scholar.application_id,
                )
            except Exception:
                pass
            try:
                from app.utils.email import send_probation_lifted_email
                _u = (await db.execute(select(User).where(User.id == scholar.student_id))).scalar_one_or_none()
                if _u:
                    await send_probation_lifted_email(str(_u.email), _sch_name)
            except Exception:
                pass


async def add_semester_record(db: AsyncSession, scholar_id: int, data: SemesterRecordCreate, actor: User | None = None) -> SemesterRecord:
    scholar = await get_scholar(db, scholar_id)
    if actor:
        _check_dept_scholar(scholar, actor)
    record = SemesterRecord(scholar_id=scholar_id, **data.model_dump())
    db.add(record)
    await db.flush()
    await _evaluate_retention(db, scholar, data.gwa, data.has_grade_below_2_5)
    # Capture IDs before commit — async SA expires attributes after commit
    _student_id     = int(scholar.student_id)      # type: ignore[arg-type]
    _application_id = int(scholar.application_id) if scholar.application_id else None  # type: ignore[arg-type]
    _scholarship_id = int(scholar.scholarship_id)  # type: ignore[arg-type]
    await db.flush()
    _record_id = int(record.id)  # type: ignore[arg-type]
    await db.commit()
    try:
        from app.services.notification_service import create_notification
        from app.models.scholarship import Scholarship as _Sch
        _sch = (await db.execute(select(_Sch).where(_Sch.id == _scholarship_id))).scalar_one_or_none()
        _sch_name = str(_sch.name) if _sch else "your scholarship"
        gwa_part = f" GWA: {data.gwa}." if data.gwa else ""
        await create_notification(
            db, _student_id,
            "Semester Record Added",
            f"OSFA has recorded your grades for {data.semester} {data.academic_year} ({_sch_name}).{gwa_part}",
            _application_id,
        )
        await db.commit()
    except Exception:
        pass
    result = await db.execute(select(SemesterRecord).where(SemesterRecord.id == _record_id))
    return result.scalar_one()


async def update_semester_record(
    db: AsyncSession, scholar_id: int, record_id: int, data: SemesterRecordUpdate, actor: User | None = None
) -> SemesterRecord:
    if actor:
        scholar = await get_scholar(db, scholar_id)
        _check_dept_scholar(scholar, actor)
    result = await db.execute(
        select(SemesterRecord).where(SemesterRecord.id == record_id, SemesterRecord.scholar_id == scholar_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise NotFoundError("SemesterRecord", record_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(record, field, value)
    # Re-evaluate retention whenever GWA or grade flag changes
    if data.gwa is not None or data.has_grade_below_2_5 is not None:
        scholar = await get_scholar(db, scholar_id)
        await _evaluate_retention(
            db, scholar,
            record.gwa,
            record.has_grade_below_2_5,
        )
    # Cache notification data before commit — attributes expire after commit.
    scholar2 = await get_scholar(db, scholar_id)
    _student_id2    = int(scholar2.student_id)   # type: ignore[arg-type]
    _application_id2 = int(scholar2.application_id) if scholar2.application_id else None  # type: ignore[arg-type]
    _scholarship_id2 = int(scholar2.scholarship_id)  # type: ignore[arg-type]
    _sem            = str(record.semester)
    _ay             = str(record.academic_year)
    _gwa            = str(record.gwa) if record.gwa else None
    await db.commit()
    try:
        from app.services.notification_service import create_notification
        from app.models.scholarship import Scholarship as _Sch
        _sch = (await db.execute(select(_Sch).where(_Sch.id == _scholarship_id2))).scalar_one_or_none()
        _sch_name = str(_sch.name) if _sch else "your scholarship"
        gwa_part = f" GWA: {_gwa}." if _gwa else ""
        await create_notification(
            db, _student_id2,
            "Semester Record Updated",
            f"OSFA has updated your grades for {_sem} {_ay} ({_sch_name}).{gwa_part}",
            _application_id2,
        )
        await db.commit()
    except Exception:
        pass
    result2 = await db.execute(select(SemesterRecord).where(SemesterRecord.id == record_id))
    return result2.scalar_one()


async def _get_semester_record(db: AsyncSession, scholar_id: int, record_id: int) -> SemesterRecord:
    result = await db.execute(
        select(SemesterRecord).where(
            SemesterRecord.id == record_id,
            SemesterRecord.scholar_id == scholar_id,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        raise NotFoundError("SemesterRecord", record_id)
    return record


async def release_benefit(db: AsyncSession, scholar_id: int, record_id: int, actor: User) -> SemesterRecord:
    """OSFA marks a scholar's semester benefit as released."""
    scholar = await get_scholar(db, scholar_id)
    _check_dept_scholar(scholar, actor)
    if scholar.status not in (ScholarStatus.active, ScholarStatus.probationary):
        raise ValidationError(
            f"Cannot release benefit — scholar status is '{scholar.status}'. "
            "Only active or probationary scholars can receive benefits."
        )
    record = await _get_semester_record(db, scholar_id, record_id)
    if record.benefit_released:
        raise ValidationError("Benefit has already been released for this semester record.")

    # Cache scalar values before commit — after commit all ORM attributes expire.
    _record_id     = int(record.id)          # type: ignore[arg-type]
    _student_id    = int(scholar.student_id)  # type: ignore[arg-type]
    _application_id = int(scholar.application_id) if scholar.application_id else None  # type: ignore[arg-type]
    _scholarship_id = int(scholar.scholarship_id)  # type: ignore[arg-type]

    record.benefit_released = True
    record.benefit_released_at = datetime.now(timezone.utc)
    await db.commit()

    try:
        from app.models.scholarship import Scholarship as _Sch
        _sch = (await db.execute(select(_Sch).where(_Sch.id == _scholarship_id))).scalar_one_or_none()
        _sch_name = str(_sch.name) if _sch else "your scholarship"
        _u = (await db.execute(select(User).where(User.id == _student_id))).scalar_one_or_none()
        _u_email = str(_u.email) if _u else None  # cache before second commit expires _u

        from app.services.notification_service import create_notification
        await create_notification(
            db, _student_id,
            "Scholarship Benefit Released",
            f"Your scholarship benefit/allowance for {_sch_name} has been released by OSFA. Please check with your scholarship office for details.",
            _application_id,
        )
        await db.commit()

        if _u_email:
            from app.utils.email import send_benefit_released_email
            await send_benefit_released_email(_u_email, _sch_name)
    except Exception:
        pass

    result = await db.execute(select(SemesterRecord).where(SemesterRecord.id == _record_id))
    return result.scalar_one()


async def submit_thank_you(db: AsyncSession, scholar_id: int, record_id: int, actor: User) -> SemesterRecord:
    """OSFA confirms they received the student's physical thank you letter."""
    # Only OSFA staff or admin can mark this — the letter is submitted physically
    if actor.role.value == "student":
        raise ForbiddenError("Only OSFA staff can confirm receipt of the thank you letter.")

    scholar = await get_scholar(db, scholar_id)
    _check_dept_scholar(scholar, actor)
    record = await _get_semester_record(db, scholar_id, record_id)
    if not record.benefit_released:
        raise ValidationError("Thank you letter can only be confirmed after the benefit has been released.")
    if record.thank_you_submitted:
        raise ValidationError("Thank you letter already confirmed for this semester.")

    from app.models.scholarship import Scholarship
    sch = (await db.execute(select(Scholarship).where(Scholarship.id == scholar.scholarship_id))).scalar_one_or_none()
    if sch and not sch.requires_thank_you_letter:
        raise ValidationError("This scholarship does not require a thank you letter.")

    # Cache scalar values before commit — after commit all ORM attributes expire.
    _record_id      = int(record.id)           # type: ignore[arg-type]
    _student_id     = int(scholar.student_id)   # type: ignore[arg-type]
    _application_id = int(scholar.application_id) if scholar.application_id else None  # type: ignore[arg-type]
    _sch_name       = str(sch.name) if sch else "your scholarship"

    record.thank_you_submitted = True
    record.thank_you_submitted_at = datetime.now(timezone.utc)
    await db.commit()

    try:
        from app.services.notification_service import create_notification
        await create_notification(
            db, _student_id,
            "Thank You Letter Confirmed",
            f"OSFA has confirmed receipt of your thank you letter for {_sch_name}. Thank you for your gratitude!",
            _application_id,
        )
        await db.commit()
    except Exception:
        pass

    result = await db.execute(select(SemesterRecord).where(SemesterRecord.id == _record_id))
    return result.scalar_one()
