# Isko Backend — Frontend Integration Guide

**Base URL:** configured via env (`BACKEND_URL`)  
**All endpoints are prefixed with `/api/...`**  
**Auth:** Bearer token in `Authorization` header for all protected endpoints.  
**Tokens:** Access token (15 min) + refresh token (7 days, HttpOnly cookie).

---

## Table of Contents
1. [Roles & Access Levels](#1-roles--access-levels)
2. [Auth Flow](#2-auth-flow)
3. [Student Account Lifecycle](#3-student-account-lifecycle)
4. [Scholarship Visibility Rules](#4-scholarship-visibility-rules)
5. [Application & Workflow State Machine](#5-application--workflow-state-machine)
6. [Full API Reference](#6-full-api-reference)
7. [Real-Time Notifications (WebSocket)](#7-real-time-notifications-websocket)
8. [Error Handling](#8-error-handling)
9. [UI State Decision Tables](#9-ui-state-decision-tables)

---

## 1. Roles & Access Levels

There are three roles. The role is embedded in the JWT and returned in `/api/auth/me`.

| Role | Value | Can do |
|---|---|---|
| Student | `student` | Register, apply, upload docs, view own data, appeal, schedule interview, withdraw |
| OSFA Staff | `osfa_staff` | Manage scholarships (own dept), process applications, run workflow, manage scholars |
| Super Admin | `super_admin` | Everything OSFA staff can do + manage staff accounts + broadcast notifications |

> **Important:** Super admins share ALL OSFA staff permissions. Any page/button available to OSFA staff must also be available to super admins. Use `role === 'osfa_staff' || role === 'super_admin'` for OSFA-level checks — never `role === 'osfa_staff'` alone.

---

## 2. Auth Flow

### Sign Up (Students only)
```
POST /api/auth/signup
Body: { email: string, password: string }
```
- **Dev:** Auto-verified. Student can log in immediately.
- **Prod:** Supabase sends a verification email. Student must click the link before they can log in.
- Response: `{ message: string }` — not a token. Redirect to a "check your email" screen.

### Email Verification (Prod only)
The backend handles the Supabase callback at `GET /api/auth/verify-email?code=...` and redirects to:
- `{FRONTEND_URL}/login?verified=true` → show "Email verified. You can now log in."
- `{FRONTEND_URL}/login?error=invalid_token` → show "Invalid or expired link."

### Login
```
POST /api/auth/login
Body: { email: string, password: string, remember_me: boolean }
Response: { access_token: string, token_type: "bearer" }
```
The refresh token is set as an **HttpOnly cookie** automatically. Store the `access_token` in memory (not localStorage).

After login, call `GET /api/auth/me` to get the user's full profile and determine which dashboard to show.

### Get Current User
```
GET /api/auth/me
Headers: Authorization: Bearer {access_token}
Response: UserResponse (see schema below)
```
Call this on every app load to restore session state.

### Refresh Token
```
POST /api/auth/refresh
(No body — uses the HttpOnly refresh_token cookie)
Response: { access_token: string, token_type: "bearer" }
```
Call this when any request returns `401`. The backend re-validates the user is still active. If this also returns `401`, the session is dead — redirect to login.

### Logout
```
POST /api/auth/logout
```
Clears the refresh token cookie. Discard the access token from memory.

### Forgot Password
```
POST /api/auth/forgot-password
Body: { email: string }
Response: { message: string }  ← Always same message (no email enumeration)
Rate limited: 5 requests per 15 minutes per IP.
```

### Reset Password (via token in URL)
The Supabase reset email redirects to `{FRONTEND_URL}/reset-password?token=...`.  
Extract the token from the URL and call:
```
POST /api/auth/reset-password
Body: { token: string, new_password: string }  ← min 8 characters
```

### Change Password (logged-in user)
```
POST /api/auth/change-password
Body: { current_password: string, new_password: string }  ← min 8 characters
```

---

## 3. Student Account Lifecycle

A student's `account_status` field controls what they can access. This is the most important field for gating student UI.

```
unregistered → pending_verification → verified
                                    ↘ rejected → (can resubmit) → pending_verification
```

| `account_status` | What student sees |
|---|---|
| `unregistered` | Must complete registration form (submit profile + documents) |
| `pending_verification` | "Your documents are under review" — read-only. Cannot apply. |
| `verified` | Full access — can browse and apply to scholarships |
| `rejected` | Shows rejection remarks — can resubmit registration documents |

### Registration Submission
```
POST /api/registration/submit
Content-Type: multipart/form-data
Fields:
  student_number: string
  first_name: string
  last_name: string
  middle_name: string (optional)
  college: string
  program: string
  year_level: integer
  school_id: File  (PDF, JPG, PNG — max 5MB)
  cor: File        (PDF, JPG, PNG — max 5MB)
```
- Only available when `account_status` is `unregistered` or `rejected`.
- On success: `account_status` becomes `pending_verification`.
- **If resubmitting (rejected status):** Old files are deleted from storage automatically.

### View Own Registration Documents
```
GET /api/registration/my-documents
Response: [{ id, doc_type, filename, url, uploaded_at }]
doc_type: "school_id" | "cor"
```

### Update Student Profile (after verified)
```
PUT /api/users/me
Body: { first_name?, last_name?, middle_name?, college?, program?, year_level? }
```

---

## 4. Scholarship Visibility Rules

| User role | Sees | Filter |
|---|---|---|
| `student` | Only `active` scholarships | All active (no dept filter — students see all active) |
| `osfa_staff` | All statuses | Only their department (`public` or `private`) |
| `super_admin` | All statuses | All departments |

### Scholarship Statuses
```
draft → active → closed → archived
draft → archived (skip publish)
closed → active (reopen)
archived → (nothing — terminal)
```

- Students can only `GET /api/scholarships/{id}` for `active` or `closed` scholarships. Draft and archived return 404 for students.
- OSFA/admin can see all statuses in listings and by ID.

---

## 5. Application & Workflow State Machine

Every application has **two parallel status fields** in its API response:

| Field | Purpose |
|---|---|
| `status` | Legacy field: `pending`, `approved`, `rejected`, `incomplete`, `withdrawn` |
| `main_status` | New workflow stage — use this for UI progress display |
| `sub_status` | Detailed state within the stage |

> **Always use `main_status` + `sub_status` to render workflow progress.**  
> Use the legacy `status` only for backward-compatible checks (e.g., withdrawal eligibility).

### Complete Workflow Map

```
[APPLICATION]
  SUBMITTED           ← set automatically when student submits
  SCREENING           ← OSFA starts screening
  SCREENING_PASSED    ← OSFA passes screening
  SCREENING_FAILED    ↘
                    [REJECTED / REJECTED]  ← terminal

[VERIFICATION]
  PENDING_VALIDATION  ← OSFA starts document verification
  REVISION_REQUESTED  ← OSFA requests changes (student must resubmit)
     ↓ (student resubmits)
  PENDING_VALIDATION  ← back to validation
  VALIDATED           ← docs approved
  VALIDATION_FAILED   ↘
                    [REJECTED / REJECTED]  ← terminal

[INTERVIEW]
  NOT_SCHEDULED       ← OSFA opens scheduling
  SCHEDULED           ← student or OSFA picks a slot
  RESCHEDULED         ← either party requests reschedule
     ↓ (schedule again)
  SCHEDULED           ← new slot confirmed
  INTERVIEW_COMPLETED ← OSFA marks interview done
  EVALUATED           ← OSFA submits evaluation scores

[DECISION]
  UNDER_REVIEW        ← OSFA moves to final review
  APPROVED            ← auto-progresses to COMPLETION
  WAITLISTED          ← can move to APPROVED or REJECTED later
  REJECTED            ← terminal (student can appeal)

[COMPLETION]
  PENDING_REQUIREMENTS ← student must submit final docs
  REQUIREMENTS_SUBMITTED ← student submitted
  COMPLETED           ← OSFA finalizes ← terminal (success)

[WITHDRAWN / WITHDRAWN]  ← terminal (student withdrew)
[REJECTED / REJECTED]    ← terminal (screened/verified/decided out)
```

### What triggers each transition

| API Call | Who | From state → To state |
|---|---|---|
| `POST /api/applications` | Student | — → `APPLICATION/SUBMITTED` (auto) |
| `POST /api/workflow/{id}/screen` | OSFA | `APPLICATION/SUBMITTED` → `APPLICATION/SCREENING` |
| `POST /api/workflow/{id}/screening-result` `{ passed: true }` | OSFA | `SCREENING` → `SCREENING_PASSED` |
| `POST /api/workflow/{id}/screening-result` `{ passed: false }` | OSFA | `SCREENING` → `SCREENING_FAILED` → `REJECTED/REJECTED` |
| `POST /api/workflow/{id}/start-verification` | OSFA | `SCREENING_PASSED` → `VERIFICATION/PENDING_VALIDATION` |
| `POST /api/workflow/{id}/request-revision` | OSFA | `PENDING_VALIDATION` → `VERIFICATION/REVISION_REQUESTED` |
| `PATCH /api/applications/{id}/resubmit` | Student | resets `status=pending`, workflow → `PENDING_VALIDATION` |
| `POST /api/workflow/{id}/verification-result` `{ passed: true }` | OSFA | `PENDING_VALIDATION` → `VERIFIED` |
| `POST /api/workflow/{id}/verification-result` `{ passed: false }` | OSFA | `PENDING_VALIDATION` → `VALIDATION_FAILED` → `REJECTED/REJECTED` |
| `POST /api/workflow/{id}/open-scheduling` | OSFA | `VALIDATED` → `INTERVIEW/NOT_SCHEDULED` |
| `POST /api/workflow/{id}/schedule-interview` | Student or OSFA | `NOT_SCHEDULED` or `RESCHEDULED` → `INTERVIEW/SCHEDULED` |
| `POST /api/workflow/{id}/reschedule-interview` | Student or OSFA | `SCHEDULED` or `RESCHEDULED` → `INTERVIEW/RESCHEDULED` |
| `POST /api/workflow/{id}/complete-interview` | OSFA | `SCHEDULED` → `INTERVIEW/INTERVIEW_COMPLETED` |
| `POST /api/workflow/{id}/evaluate` | OSFA | `INTERVIEW_COMPLETED` → `INTERVIEW/EVALUATED` |
| `POST /api/workflow/{id}/move-to-review` | OSFA | `EVALUATED` → `DECISION/UNDER_REVIEW` |
| `POST /api/workflow/{id}/decide` `{ decision: "approved" }` | OSFA | `UNDER_REVIEW` → `DECISION/APPROVED` → `COMPLETION/PENDING_REQUIREMENTS` |
| `POST /api/workflow/{id}/decide` `{ decision: "rejected" }` | OSFA | `UNDER_REVIEW` → `DECISION/REJECTED` (terminal) |
| `POST /api/workflow/{id}/decide` `{ decision: "waitlisted" }` | OSFA | `UNDER_REVIEW` → `DECISION/WAITLISTED` |
| `POST /api/workflow/{id}/decide` `{ decision: "approved" }` | OSFA | `WAITLISTED` → `DECISION/APPROVED` → `COMPLETION/PENDING_REQUIREMENTS` |
| `POST /api/workflow/{id}/submit-requirements` | Student | `PENDING_REQUIREMENTS` → `COMPLETION/REQUIREMENTS_SUBMITTED` |
| `POST /api/workflow/{id}/finalize` | OSFA | `REQUIREMENTS_SUBMITTED` → `COMPLETION/COMPLETED` |
| `POST /api/workflow/{id}/withdraw` | Student | any non-terminal → `WITHDRAWN/WITHDRAWN` |
| `PATCH /api/applications/{id}/withdraw` | Student | legacy (pending/incomplete only) → withdrawn (also syncs workflow) |

### Student: When can they appeal?
- `status === 'rejected'` (legacy) **OR**
- `main_status === 'decision' && sub_status === 'rejected'` (workflow decision rejection)
- After appeal is **approved** by OSFA, the application resets to `APPLICATION/SUBMITTED` for re-processing.

### Student: When can they resubmit?
- `status === 'incomplete'` — which is set when OSFA requests a revision (`REVISION_REQUESTED`)

### Student: When can they upload documents?
Documents can only be uploaded/deleted while `sub_status` is one of:
- `submitted`, `screening`, `screening_passed`, `revision_requested`

Once verification starts, document upload is blocked for students.

### OSFA: Legacy status endpoint vs workflow endpoints
There is also a legacy `PATCH /api/applications/{id}/status` endpoint. Prefer the workflow endpoints for all new UI. The legacy endpoint is kept for backward compatibility but it does not trigger notifications or advance the workflow.

---

## 6. Full API Reference

### Auth — `/api/auth`
| Method | Path | Auth | Body | Response |
|---|---|---|---|---|
| POST | `/signup` | None | `{ email, password }` | `{ message }` |
| GET | `/verify-email?code=...` | None | — | Redirect |
| POST | `/login` | None | `{ email, password, remember_me }` | `{ access_token }` |
| POST | `/refresh` | Cookie | — | `{ access_token }` |
| POST | `/logout` | Any | — | `{ message }` |
| GET | `/me` | Any | — | UserResponse |
| POST | `/change-password` | Any | `{ current_password, new_password }` | `{ message }` |
| POST | `/forgot-password` | None | `{ email }` | `{ message }` |
| GET | `/reset-callback?code=...` | None | — | Redirect |
| POST | `/reset-password` | None | `{ token, new_password }` | `{ message }` |
| POST | `/reset-password-token` | None | `{ access_token, new_password }` | `{ message }` |

---

### Users — `/api/users`
| Method | Path | Auth | Notes |
|---|---|---|---|
| PUT | `/me` | Student | Update own profile fields |
| GET | `/` | OSFA+Admin | List all students (paginated). Query: `?page&page_size&account_status` |
| GET | `/{user_id}` | OSFA+Admin | Get specific student |
| GET | `/{user_id}/registration-documents` | OSFA+Admin | Returns `[{ id, doc_type, filename, url, uploaded_at }]` |
| PATCH | `/{user_id}/approve` | OSFA+Admin | Set `account_status=verified`. Only from `pending_verification`. |
| PATCH | `/{user_id}/reject` | OSFA+Admin | Body: `{ remarks: string }`. Only from `pending_verification`. |

**UserResponse shape:**
```json
{
  "id": 1,
  "email": "student@example.com",
  "role": "student",
  "is_active": true,
  "is_verified": true,
  "account_status": "verified",
  "rejection_remarks": null,
  "department": null,
  "created_at": "...",
  "updated_at": "...",
  "student_profile": {
    "id": 1,
    "student_number": "2021-00001",
    "first_name": "Juan",
    "last_name": "Dela Cruz",
    "middle_name": null,
    "college": "Engineering",
    "program": "BSCS",
    "year_level": 3,
    "gwa": "1.75"
  }
}
```

---

### Registration — `/api/registration`
| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | `/submit` | Student | Multipart form. See §3. |
| GET | `/my-documents` | Student | Own registration docs |

---

### Scholarships — `/api/scholarships`
| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/` | Any | Paginated. Students see active only. OSFA sees own dept. `?page&page_size` |
| GET | `/{id}` | Any | Students get 404 for draft/archived |
| POST | `/` | OSFA+Admin | Create scholarship |
| PUT | `/{id}` | OSFA+Admin | Full update. OSFA can only update own dept. |
| DELETE | `/{id}` | OSFA+Admin | Blocked if active applications exist |
| PATCH | `/{id}/status` | OSFA+Admin | `{ status: "active"|"closed"|"archived"|"draft" }` — enforces transition rules |
| POST | `/{id}/duplicate` | OSFA+Admin | Creates a `draft` copy |

**Status transition rules (enforce in UI too):**
- `draft` → `active` or `archived`
- `active` → `closed`
- `closed` → `active` or `archived`
- `archived` → nothing (hide the status change button)

**ScholarshipResponse shape:**
```json
{
  "id": 1,
  "name": "DOST Scholarship",
  "description": "...",
  "slots": 10,
  "deadline": "2025-12-31T00:00:00Z",
  "status": "active",
  "eligible_colleges": ["Engineering", "Science"],
  "eligible_programs": ["BSCS", "BSEE"],
  "eligible_year_levels": [2, 3, 4],
  "min_gwa": "2.0",
  "amount_raw": 7000,
  "period": "Per Semester",
  "scholarship_type": "Merit-based",
  "eligibility_text": "Must be a Filipino citizen...",
  "cover_image_url": null,
  "category": "public",
  "applicants_count": 5,
  "requirements": [
    { "id": 1, "name": "Transcript of Records", "description": "...", "is_required": true }
  ]
}
```

**Create/Update body:**
```json
{
  "name": "string (required)",
  "description": "string",
  "slots": 10,
  "deadline": "2025-12-31T00:00:00Z",
  "eligible_colleges": ["Engineering"],
  "eligible_programs": ["BSCS"],
  "eligible_year_levels": [2, 3, 4],
  "min_gwa": "2.0",
  "amount_raw": 7000,
  "period": "Per Semester",
  "scholarship_type": "Merit-based",
  "eligibility_text": "...",
  "cover_image_url": "...",
  "category": "public",
  "requirements": [
    { "name": "TOR", "description": "...", "is_required": true }
  ]
}
```

---

### Applications — `/api/applications`
| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/` | Any | Paginated. Students see own only. OSFA sees own dept only. `?page&page_size&status` |
| GET | `/count` | Any | `?status=pending` etc. Returns `{ count: number }` |
| GET | `/{id}` | Any | Students can only get own applications |
| POST | `/` | Verified Student | `{ scholarship_id: int }` — triggers eligibility + slot + deadline checks |
| PATCH | `/{id}/resubmit` | Verified Student | No body. Only when `status === 'incomplete'` |
| PATCH | `/{id}/withdraw` | Verified Student | No body. Only when `status === 'pending' or 'incomplete'`. Also syncs workflow. |
| PATCH | `/{id}/status` | OSFA+Admin | Legacy: `{ status, remarks?, rejected_docs? }` |
| PATCH | `/{id}/eval-status` | OSFA+Admin | `{ eval_status: "not_started"|"in_review"|"completed" }` |
| PATCH | `/{id}/eval-score` | OSFA+Admin | `{ financial_need, essay, interview, community }` |
| POST | `/{id}/appeal` | Verified Student | `{ reason: string }` — only when rejected |
| PATCH | `/{id}/appeal` | OSFA+Admin | `{ approved: bool, review_note? }` |
| GET | `/{id}/audit` | Any (own only for students) | Audit trail entries |

**ApplicationResponse shape:**
```json
{
  "id": 1,
  "student_id": 5,
  "scholarship_id": 2,
  "status": "pending",
  "eval_status": "not_started",
  "rejected_docs": [],
  "eval_score": null,
  "remarks": null,
  "submitted_at": "2025-01-01T00:00:00Z",
  "updated_at": "2025-01-02T00:00:00Z",
  "main_status": "verification",
  "sub_status": "pending_validation",
  "appeal": null,
  "student": {
    "id": 5, "email": "...", "first_name": "Juan", "last_name": "Dela Cruz",
    "student_number": "2021-00001", "college": "Engineering", "program": "BSCS", "year_level": 3
  },
  "scholarship": { "id": 2, "name": "DOST", "scholarship_type": "Merit-based" }
}
```

---

### Documents — `/api/applications/{application_id}/documents`
| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | `/` | Any | Multipart: `file` (required) + `requirement_name` (optional form field). Max 5MB, PDF/JPG/PNG only. |
| GET | `/` | Any | List documents for the application |
| DELETE | `/{doc_id}` | Any | Students blocked after verification starts |
| PATCH | `/flag` | OSFA+Admin | `{ rejected_doc_ids: [int] }` — flags listed docs, resets others to submitted |

> Students are blocked from uploading/deleting when `sub_status` is past `revision_requested` (i.e., once in `pending_validation` stage from verification onward). Show an appropriate message: "Documents can no longer be changed at this stage."

**DocumentResponse shape:**
```json
{
  "id": 1,
  "application_id": 1,
  "requirement_id": 2,
  "filename": "tor.pdf",
  "url": "https://storage.supabase.co/...",
  "file_url": "https://storage.supabase.co/...",
  "file_name": "tor.pdf",
  "requirement_name": "Transcript of Records",
  "content_type": "application/pdf",
  "file_size": 204800,
  "status": "submitted",
  "flagged": false,
  "uploaded_at": "..."
}
```

---

### Workflow — `/api/workflow`
| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/{id}` | Any (own only for students) | Full workflow status + logs |
| GET | `/{id}/logs` | Any (own only for students) | Array of log entries |
| POST | `/{id}/initialize` | OSFA+Admin | Manually initialize (only if not yet initialized) |
| POST | `/{id}/screen` | OSFA+Admin | Start screening |
| POST | `/{id}/screening-result` | OSFA+Admin | `{ passed: bool, note? }` |
| POST | `/{id}/start-verification` | OSFA+Admin | Move to document verification |
| POST | `/{id}/request-revision` | OSFA+Admin | `{ note: string }` — student must resubmit |
| POST | `/{id}/verification-result` | OSFA+Admin | `{ passed: bool, note? }` |
| POST | `/{id}/open-scheduling` | OSFA+Admin | Allow interview scheduling |
| POST | `/{id}/schedule-interview` | Any | `{ interview_datetime, location?, note? }` |
| POST | `/{id}/reschedule-interview` | Any | `{ reason: string }` |
| POST | `/{id}/complete-interview` | OSFA+Admin | `{ notes? }` |
| POST | `/{id}/evaluate` | OSFA+Admin | `{ eval_score?: object, note? }` |
| POST | `/{id}/move-to-review` | OSFA+Admin | No body |
| POST | `/{id}/decide` | OSFA+Admin | `{ decision: "approved"|"rejected"|"waitlisted", remarks? }` |
| POST | `/{id}/submit-requirements` | Verified Student | `{ requirements: [{ requirement_type, file_url? }] }` — min 1 item |
| POST | `/{id}/finalize` | OSFA+Admin | `{ note? }` |
| POST | `/{id}/withdraw` | Any (own app only for students) | `{ reason? }` — syncs both status systems |

**WorkflowStatusResponse shape:**
```json
{
  "application_id": 1,
  "main_status": "interview",
  "sub_status": "scheduled",
  "submitted_at": "...",
  "screened_at": "...",
  "validated_at": null,
  "interview_scheduled_at": "...",
  "interview_datetime": "2025-06-15T09:00:00Z",
  "interview_completed_at": null,
  "evaluated_at": null,
  "decision_released_at": null,
  "completion_submitted_at": null,
  "closed_at": null,
  "interview_location": "OSFA Office, Room 201",
  "decision_remarks": null,
  "logs": [
    {
      "id": 1,
      "from_main": null, "from_sub": null,
      "to_main": "application", "to_sub": "submitted",
      "note": null, "changed_by": 5, "created_at": "..."
    }
  ]
}
```

---

### Scholars — `/api/scholars`
| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/me` | Student | Own scholar records (created automatically on approval) |
| GET | `/` | OSFA+Admin | Paginated list of all scholars |
| GET | `/{scholar_id}` | OSFA+Admin | Single scholar with semester records |
| PATCH | `/{scholar_id}/status` | OSFA+Admin | `{ status: "active"|"probationary"|"terminated"|"graduated" }` |
| POST | `/{scholar_id}/semester-records` | OSFA+Admin | `{ semester, academic_year, gwa, is_enrolled, notes? }` |
| PUT | `/{scholar_id}/semester-records/{record_id}` | OSFA+Admin | Update a semester record |

---

### Notifications — `/api/notifications`
| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/` | Any | Paginated. `?page&page_size` |
| PATCH | `/{id}/read` | Any | Mark single notification as read |
| PATCH | `/read-all` | Any | Mark all as read |
| DELETE | `/{id}` | Any | Dismiss (delete) a notification |
| POST | `/broadcast` | Super Admin only | `{ title, body }` — sends to all students |

**NotificationResponse shape:**
```json
{
  "id": 1,
  "title": "Application Submitted",
  "body": "Your application for DOST Scholarship has been submitted.",
  "is_read": false,
  "application_id": 3,
  "created_at": "..."
}
```

**Notifications are automatically sent when:**
- Student submits application
- Student application is screened out (failed)
- Verification starts
- Revision is requested
- Documents are verified
- Interview scheduling is opened
- Interview is scheduled
- Interview is rescheduled
- Decision is released (approved / rejected / waitlisted)
- Scholarship is finalized (completed)
- OSFA staff: when a student submits registration documents (pending review)

---

### Reports — `/api/reports`
| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/overview` | OSFA+Admin | Dashboard stats |
| GET | `/scholarships` | OSFA+Admin | Per-scholarship breakdown |
| GET | `/applications` | OSFA+Admin | Application trends |

---

### Admin — `/api/admin`
| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/staff` | Super Admin only | List all OSFA staff |
| POST | `/staff` | Super Admin only | `{ email, password, department: "public"|"private" }` |
| PATCH | `/staff/{id}` | Super Admin only | `{ department?, is_active? }` |

---

## 7. Real-Time Notifications (WebSocket)

```
WS /ws/notifications?token={access_token}
```

Connect after login. The backend pushes notification payloads as JSON when new notifications arrive for the user.

**Payload shape:**
```json
{
  "id": 1,
  "title": "Interview Scheduled",
  "body": "Your interview has been scheduled for June 15, 2025 at 9:00 AM.",
  "is_read": false,
  "application_id": 3,
  "created_at": "..."
}
```

**Frontend behavior:**
- On receive: increment unread badge, append to notification list, optionally show toast.
- Reconnect with backoff if the connection drops.
- Use the REST notification endpoints for the full list and mark-read actions.

---

## 8. Error Handling

All errors follow this shape:
```json
{
  "code": "not_found",
  "message": "Application not found",
  "detail": null
}
```

| HTTP Status | `code` | When |
|---|---|---|
| 400 | `validation_error` | Invalid input / business rule violation |
| 401 | `unauthorized` | Missing/expired/invalid token |
| 403 | `forbidden` | Role not allowed, or student accessing another student's data |
| 404 | `not_found` | Resource doesn't exist (or student accessing draft scholarship) |
| 409 | `conflict` | Duplicate application, student number already taken |
| 422 | (FastAPI) | Request body fails schema validation |
| 429 | (rate limit) | Too many password reset requests |
| 500 | `internal_error` | Server error (details hidden in production) |

**Common business errors to handle gracefully:**
- `"Scholarship is not accepting applications"` — scholarship is not `active`
- `"The application deadline for this scholarship has passed"` — disable apply button if `deadline < now`
- `"This scholarship has no available slots"` — show "Full" badge
- `"Not eligible: college restriction"` / `"program restriction"` / `"year level restriction"` / `"GWA does not meet minimum"` — show specific ineligibility reason
- `"Already applied to this scholarship"` — show "Applied" state on card
- `"Cannot delete this scholarship — it has N active application(s)"` — show count in error message
- `"Cannot transition scholarship status from X to Y"` — only show valid status actions
- `"Documents can only be uploaded or deleted while your application is in submission or revision stage"` — hide upload button in wrong workflow states
- `"Application is already in a terminal state"` — hide all action buttons for terminal apps
- `"Invalid transition: ..."` — the workflow action is not valid from the current state

---

## 9. UI State Decision Tables

### Student Dashboard — What to show based on `account_status`

| `account_status` | Show |
|---|---|
| `unregistered` | Registration form CTA |
| `pending_verification` | "Under review" banner, no apply button |
| `verified` | Full scholarship listing + apply buttons |
| `rejected` | Rejection remarks + re-submit registration button |

### Scholarship Card — Student view

| Condition | Badge / Button |
|---|---|
| Student already applied (non-withdrawn) | "Applied" — disable apply |
| `applicants_count >= slots` | "Full" — disable apply |
| `deadline < now` | "Deadline Passed" — disable apply |
| Student profile GWA > `min_gwa` | "Not Eligible" — disable apply |
| All good | "Apply" button enabled |

### Application Progress Bar — use `main_status` + `sub_status`

| Stage | sub_status values to show progress |
|---|---|
| Application | `submitted` → `screening` → `screening_passed` |
| Verification | `pending_validation` → `revision_requested` → `validated` |
| Interview | `not_scheduled` → `scheduled` → `rescheduled` → `interview_completed` → `evaluated` |
| Decision | `under_review` → `approved` / `rejected` / `waitlisted` |
| Completion | `pending_requirements` → `requirements_submitted` → `completed` |
| Terminal | `withdrawn` or `rejected` (main) |

### Application — Student action buttons

| `sub_status` | Student can |
|---|---|
| `submitted`, `screening`, `screening_passed`, `pending_validation` | Withdraw |
| `revision_requested` | Resubmit, upload/delete docs, Withdraw |
| `not_scheduled` | Schedule interview |
| `scheduled`, `rescheduled` | Reschedule interview |
| `pending_requirements` | Submit completion requirements |
| `decision/rejected` | Appeal |
| `withdrawn`, `rejected` (main), `completed` | No actions (terminal) |

### OSFA Application Queue — Action buttons per state

| `sub_status` | OSFA can |
|---|---|
| `submitted` | Start Screening |
| `screening` | Pass or Fail Screening |
| `screening_passed` | Start Verification |
| `pending_validation` | Validate, Fail, or Request Revision |
| `revision_requested` | (wait for student resubmit) |
| `validated` | Open Interview Scheduling |
| `not_scheduled` | (wait for student to schedule) |
| `scheduled` | Complete Interview, or Reschedule |
| `interview_completed` | Submit Evaluation |
| `evaluated` | Move to Review |
| `under_review` | Release Decision (approve / reject / waitlist) |
| `waitlisted` | Release Final Decision (approve / reject) |
| `requirements_submitted` | Finalize |
| Terminal states | No actions |

### Scholarship — OSFA status button availability

| Current status | Can change to |
|---|---|
| `draft` | Publish (`active`), Archive |
| `active` | Close |
| `closed` | Reopen (`active`), Archive |
| `archived` | (nothing — hide button) |

---

## Pagination

All list endpoints that return `PaginatedResponse` have this shape:
```json
{
  "items": [...],
  "total": 100,
  "page": 1,
  "page_size": 20,
  "pages": 5
}
```
Default: `page=1`, `page_size=20`. Max page_size varies: applications=50, scholarships=500, users=100.

Results are ordered:
- Applications: newest `submitted_at` first
- Scholarships: newest `created_at` first
- Users: newest `created_at` first

---

## Department Isolation (OSFA Staff)

OSFA staff have a `department` field: `"public"` or `"private"`.

- Scholarships: OSFA staff only see/manage scholarships matching their department.
- Applications: OSFA staff only see applications for scholarships in their department.
- Students: All OSFA staff can see all students (registration is not department-scoped).
- Super admins see everything across both departments.

The `department` field on the staff user from `GET /api/auth/me` tells you which context they're in. You don't need to send the department in requests — the backend enforces it automatically.
