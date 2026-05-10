from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.application import Application, CompletionRequirement
from app.models.scholarship import ComplianceDocumentType
from app.models.user import User
from app.exceptions import NotFoundError, ValidationError, ForbiddenError


async def get_compliance_doc_types(db: AsyncSession, scholarship_id: int) -> list[ComplianceDocumentType]:
    result = await db.execute(
        select(ComplianceDocumentType)
        .where(ComplianceDocumentType.scholarship_id == scholarship_id)
        .order_by(ComplianceDocumentType.order)
    )
    return list(result.scalars().all())


async def create_compliance_doc_type(
    db: AsyncSession,
    scholarship_id: int,
    name: str,
    description: str | None,
    is_required: bool,
    order: int,
) -> ComplianceDocumentType:
    doc_type = ComplianceDocumentType(
        scholarship_id=scholarship_id,
        name=name,
        description=description,
        is_required=is_required,
        order=order,
    )
    db.add(doc_type)
    await db.commit()
    await db.refresh(doc_type)
    return doc_type


async def delete_compliance_doc_type(db: AsyncSession, doc_type_id: int) -> None:
    result = await db.execute(
        select(ComplianceDocumentType).where(ComplianceDocumentType.id == doc_type_id)
    )
    doc_type = result.scalar_one_or_none()
    if not doc_type:
        raise NotFoundError("ComplianceDocumentType", doc_type_id)
    await db.delete(doc_type)
    await db.commit()


async def submit_compliance_doc(
    db: AsyncSession,
    application_id: int,
    requirement_type: str,
    file_url: str | None,
    notes: str | None,
    actor: User,
) -> CompletionRequirement:
    app_result = await db.execute(select(Application).where(Application.id == application_id))
    app = app_result.scalar_one_or_none()
    if not app:
        raise NotFoundError("Application", application_id)

    if actor.role.value == "student" and app.student_id != actor.id:
        raise ForbiddenError()

    from app.models.workflow import MainStatus, SubStatus
    if app.main_status != MainStatus.COMPLETION or app.sub_status not in (
        SubStatus.PENDING_REQUIREMENTS, SubStatus.REQUIREMENTS_SUBMITTED
    ):
        raise ValidationError("Application is not in the compliance submission stage.")

    # Upsert — replace existing unverified submission for the same type
    existing_result = await db.execute(
        select(CompletionRequirement).where(
            CompletionRequirement.application_id == application_id,
            CompletionRequirement.requirement_type == requirement_type,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing and existing.is_verified:
        raise ValidationError(f"'{requirement_type}' has already been verified and cannot be replaced.")

    if existing:
        existing.file_url = file_url
        existing.notes = notes
        existing.submitted_at = datetime.now(timezone.utc)
        existing.is_verified = False
        doc = existing
    else:
        doc = CompletionRequirement(
            application_id=application_id,
            requirement_type=requirement_type,
            file_url=file_url,
            notes=notes,
            submitted_at=datetime.now(timezone.utc),
        )
        db.add(doc)

    await db.commit()
    await db.refresh(doc)
    return doc


async def verify_compliance_doc(
    db: AsyncSession,
    application_id: int,
    requirement_id: int,
    actor: User,
) -> CompletionRequirement:
    result = await db.execute(
        select(CompletionRequirement).where(
            CompletionRequirement.id == requirement_id,
            CompletionRequirement.application_id == application_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise NotFoundError("CompletionRequirement", requirement_id)
    if not doc.submitted_at:
        raise ValidationError("Document has not been submitted yet.")

    doc.is_verified = True
    doc.verified_by = actor.id
    doc.verified_at = datetime.now(timezone.utc)

    # After verifying, check if ALL required docs are now verified
    # If so, auto-advance sub_status to REQUIREMENTS_SUBMITTED
    app_result = await db.execute(select(Application).where(Application.id == application_id))
    app = app_result.scalar_one_or_none()
    if app:
        required_types = (await db.execute(
            select(ComplianceDocumentType.name).where(
                ComplianceDocumentType.scholarship_id == app.scholarship_id,
                ComplianceDocumentType.is_required == True,
            )
        )).scalars().all()

        if required_types:
            all_verified = (await db.execute(
                select(CompletionRequirement).where(
                    CompletionRequirement.application_id == application_id,
                    CompletionRequirement.requirement_type.in_(required_types),
                    CompletionRequirement.is_verified == True,
                )
            )).scalars().all()

            from app.models.workflow import MainStatus, SubStatus
            if (len(all_verified) >= len(required_types)
                    and app.sub_status == SubStatus.PENDING_REQUIREMENTS):
                from app.models.application import WorkflowLog
                db.add(WorkflowLog(
                    application_id=application_id,
                    changed_by=actor.id,
                    from_main=app.main_status,
                    from_sub=app.sub_status,
                    to_main=MainStatus.COMPLETION,
                    to_sub=SubStatus.REQUIREMENTS_SUBMITTED,
                    note="All required compliance documents verified",
                ))
                app.main_status = MainStatus.COMPLETION
                app.sub_status = SubStatus.REQUIREMENTS_SUBMITTED

    await db.commit()
    await db.refresh(doc)
    return doc


async def list_compliance_docs(
    db: AsyncSession, application_id: int
) -> list[CompletionRequirement]:
    result = await db.execute(
        select(CompletionRequirement)
        .where(CompletionRequirement.application_id == application_id)
        .order_by(CompletionRequirement.created_at)
    )
    return list(result.scalars().all())
