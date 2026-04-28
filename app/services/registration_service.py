from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.models.user import User, AccountStatus, StudentProfile
from app.models.registration import RegistrationDocument, RegistrationDocType
from app.exceptions import ForbiddenError


async def submit_registration(
    db: AsyncSession,
    user: User,
    student_number: str,
    first_name: str,
    last_name: str,
    middle_name: str | None,
    college: str,
    program: str,
    year_level: int,
    school_id_path: str,
    school_id_filename: str,
    school_id_content_type: str,
    cor_path: str,
    cor_filename: str,
    cor_content_type: str,
) -> User:
    if user.account_status not in (AccountStatus.unregistered, AccountStatus.rejected):
        raise ForbiddenError("You have already submitted your registration documents")

    # Upsert StudentProfile
    result = await db.execute(select(StudentProfile).where(StudentProfile.user_id == user.id))
    profile = result.scalar_one_or_none()
    if profile:
        profile.student_number = student_number
        profile.first_name = first_name
        profile.last_name = last_name
        profile.middle_name = middle_name
        profile.college = college
        profile.program = program
        profile.year_level = year_level
    else:
        profile = StudentProfile(
            user_id=user.id,
            student_number=student_number,
            first_name=first_name,
            last_name=last_name,
            middle_name=middle_name,
            college=college,
            program=program,
            year_level=year_level,
        )
        db.add(profile)

    # Replace any existing registration documents
    await db.execute(
        delete(RegistrationDocument).where(RegistrationDocument.user_id == user.id)
    )

    db.add(RegistrationDocument(
        user_id=user.id,
        doc_type=RegistrationDocType.school_id,
        filename=school_id_filename,
        storage_path=school_id_path,
        content_type=school_id_content_type,
    ))
    db.add(RegistrationDocument(
        user_id=user.id,
        doc_type=RegistrationDocType.cor,
        filename=cor_filename,
        storage_path=cor_path,
        content_type=cor_content_type,
    ))

    user.account_status = AccountStatus.pending_verification
    user.rejection_remarks = None
    await db.commit()
    await db.refresh(user)
    return user


async def get_registration_documents(
    db: AsyncSession, user_id: int
) -> list[RegistrationDocument]:
    result = await db.execute(
        select(RegistrationDocument).where(RegistrationDocument.user_id == user_id)
    )
    return result.scalars().all()
