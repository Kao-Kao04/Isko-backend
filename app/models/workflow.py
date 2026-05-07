import enum


class MainStatus(str, enum.Enum):
    APPLICATION      = "application"
    VERIFICATION     = "verification"
    INTERVIEW        = "interview"
    DECISION         = "decision"
    COMPLETION       = "completion"
    # Terminal states
    WITHDRAWN        = "withdrawn"
    REJECTED         = "rejected"


class SubStatus(str, enum.Enum):
    # ── APPLICATION ──────────────────────────────
    SUBMITTED         = "submitted"
    SCREENING         = "screening"
    SCREENING_PASSED  = "screening_passed"
    SCREENING_FAILED  = "screening_failed"

    # ── VERIFICATION ─────────────────────────────
    PENDING_VALIDATION   = "pending_validation"
    REVISION_REQUESTED   = "revision_requested"
    VALIDATED            = "validated"
    VALIDATION_FAILED    = "validation_failed"

    # ── INTERVIEW ────────────────────────────────
    NOT_SCHEDULED        = "not_scheduled"
    SCHEDULED            = "scheduled"
    RESCHEDULED          = "rescheduled"
    INTERVIEW_COMPLETED  = "interview_completed"
    EVALUATED            = "evaluated"

    # ── DECISION ─────────────────────────────────
    UNDER_REVIEW = "under_review"
    APPROVED     = "approved"
    REJECTED     = "rejected"
    WAITLISTED   = "waitlisted"

    # ── COMPLETION ───────────────────────────────
    PENDING_REQUIREMENTS     = "pending_requirements"
    REQUIREMENTS_SUBMITTED   = "requirements_submitted"
    COMPLETED                = "completed"

    # ── TERMINAL ─────────────────────────────────
    WITHDRAWN = "withdrawn"


# ─── State machine ───────────────────────────────────────────────────────────
# (from_main, from_sub) → [(to_main, to_sub), ...]
ALLOWED_TRANSITIONS: dict[
    tuple[MainStatus, SubStatus],
    list[tuple[MainStatus, SubStatus]],
] = {
    # APPLICATION stage
    (MainStatus.APPLICATION, SubStatus.SUBMITTED): [
        (MainStatus.APPLICATION, SubStatus.SCREENING),
    ],
    (MainStatus.APPLICATION, SubStatus.SCREENING): [
        (MainStatus.APPLICATION, SubStatus.SCREENING_PASSED),
        (MainStatus.APPLICATION, SubStatus.SCREENING_FAILED),
    ],
    (MainStatus.APPLICATION, SubStatus.SCREENING_PASSED): [
        (MainStatus.VERIFICATION, SubStatus.PENDING_VALIDATION),
    ],
    (MainStatus.APPLICATION, SubStatus.SCREENING_FAILED): [
        (MainStatus.REJECTED, SubStatus.REJECTED),
    ],

    # VERIFICATION stage
    (MainStatus.VERIFICATION, SubStatus.PENDING_VALIDATION): [
        (MainStatus.VERIFICATION, SubStatus.VALIDATED),
        (MainStatus.VERIFICATION, SubStatus.VALIDATION_FAILED),
        (MainStatus.VERIFICATION, SubStatus.REVISION_REQUESTED),
    ],
    (MainStatus.VERIFICATION, SubStatus.REVISION_REQUESTED): [
        (MainStatus.VERIFICATION, SubStatus.PENDING_VALIDATION),
    ],
    (MainStatus.VERIFICATION, SubStatus.VALIDATED): [
        (MainStatus.INTERVIEW, SubStatus.NOT_SCHEDULED),
    ],
    (MainStatus.VERIFICATION, SubStatus.VALIDATION_FAILED): [
        (MainStatus.REJECTED, SubStatus.REJECTED),
    ],

    # INTERVIEW stage
    (MainStatus.INTERVIEW, SubStatus.NOT_SCHEDULED): [
        (MainStatus.INTERVIEW, SubStatus.SCHEDULED),
    ],
    (MainStatus.INTERVIEW, SubStatus.SCHEDULED): [
        (MainStatus.INTERVIEW, SubStatus.RESCHEDULED),
        (MainStatus.INTERVIEW, SubStatus.INTERVIEW_COMPLETED),
    ],
    # RESCHEDULED can be rescheduled again or scheduled (to confirm new slot)
    (MainStatus.INTERVIEW, SubStatus.RESCHEDULED): [
        (MainStatus.INTERVIEW, SubStatus.SCHEDULED),
        (MainStatus.INTERVIEW, SubStatus.RESCHEDULED),
    ],
    (MainStatus.INTERVIEW, SubStatus.INTERVIEW_COMPLETED): [
        (MainStatus.INTERVIEW, SubStatus.EVALUATED),
    ],
    (MainStatus.INTERVIEW, SubStatus.EVALUATED): [
        (MainStatus.DECISION, SubStatus.UNDER_REVIEW),
    ],

    # DECISION stage
    (MainStatus.DECISION, SubStatus.UNDER_REVIEW): [
        (MainStatus.DECISION, SubStatus.APPROVED),
        (MainStatus.DECISION, SubStatus.REJECTED),
        (MainStatus.DECISION, SubStatus.WAITLISTED),
    ],
    (MainStatus.DECISION, SubStatus.APPROVED): [
        (MainStatus.COMPLETION, SubStatus.PENDING_REQUIREMENTS),
    ],
    # WAITLISTED can eventually move to approved or rejected
    (MainStatus.DECISION, SubStatus.WAITLISTED): [
        (MainStatus.DECISION, SubStatus.APPROVED),
        (MainStatus.DECISION, SubStatus.REJECTED),
    ],
    # DECISION/REJECTED has no outgoing transitions — treated as terminal by is_terminal()

    # COMPLETION stage
    (MainStatus.COMPLETION, SubStatus.PENDING_REQUIREMENTS): [
        (MainStatus.COMPLETION, SubStatus.REQUIREMENTS_SUBMITTED),
    ],
    (MainStatus.COMPLETION, SubStatus.REQUIREMENTS_SUBMITTED): [
        (MainStatus.COMPLETION, SubStatus.COMPLETED),
    ],
    # COMPLETION/COMPLETED has no outgoing transitions — treated as terminal by is_terminal()
}


def is_terminal(main: MainStatus, sub: SubStatus | None = None) -> bool:
    """Returns True if the application is in a state that allows no further transitions."""
    if main in (MainStatus.WITHDRAWN, MainStatus.REJECTED):
        return True
    # DECISION/REJECTED is a terminal decision-stage rejection
    if main == MainStatus.DECISION and sub == SubStatus.REJECTED:
        return True
    # COMPLETION/COMPLETED is the final successful terminal state
    if main == MainStatus.COMPLETION and sub == SubStatus.COMPLETED:
        return True
    return False


def can_transition(
    from_main: MainStatus,
    from_sub: SubStatus,
    to_main: MainStatus,
    to_sub: SubStatus,
) -> bool:
    allowed = ALLOWED_TRANSITIONS.get((from_main, from_sub), [])
    return (to_main, to_sub) in allowed
