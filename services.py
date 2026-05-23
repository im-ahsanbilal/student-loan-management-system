import mimetypes
import os
import secrets
from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import current_app
from werkzeug.utils import secure_filename

from constants import MINIMUM_CGPA
from extensions import db
from helpers import resolve_managed_upload_path
from models import Installment, LoanApplication, VerificationLog


INSTALLMENT_LOCKED_STATUSES = {"paid", "pending_verification"}
ADMIN_INSTALLMENT_CONFIRMATION_STAGE = "Installment Admin Confirmation"


def parse_semester_number(raw_value):
    digits = "".join(character for character in str(raw_value or "") if character.isdigit())
    if not digits:
        return None
    return int(digits)


def student_eligibility_block_reason(user):
    current_semester = parse_semester_number(user.semester)
    if current_semester is None:
        return "Complete your academic profile before applying for a loan."
    if current_semester == 1:
        return "Students in 1st semester are not eligible to apply for loan."

    max_semester = 3 if (user.program_level or "BS") == "MS" else current_app.config["MAX_ELIGIBLE_SEMESTER"]
    if current_semester > max_semester:
        if (user.program_level or "BS") == "MS":
            return "Master students can apply only up to Semester 3."
        return f"BS students can apply only up to Semester {current_app.config['MAX_ELIGIBLE_SEMESTER']}."

    if not resolve_managed_upload_path(user.profile_photo_path):
        return "Upload your passport-size profile photo before applying for a new loan."

    approved_application = (
        LoanApplication.query.filter_by(student_id=user.id, status="Approved")
        .order_by(LoanApplication.admin_decided_at.desc(), LoanApplication.submitted_at.desc())
        .first()
    )
    if approved_application:
        return f"Loan already issued under application {approved_application.loan_id}. You cannot apply again."

    return None


def evaluate_application_ai(application):
    cgpa_value = float(application.cgpa or 0)
    documents_complete = application.has_all_required_documents(current_app.config["REQUIRED_DOCUMENTS"])
    not_fee_defaulter = application.finance_fee_defaulter is False
    not_on_scholarship = application.finance_scholarship_availing is False

    score = 0
    reasons = []

    if cgpa_value >= MINIMUM_CGPA:
        score += 25
        reasons.append("CGPA meets minimum requirement")
    else:
        reasons.append("CGPA below 3.0")

    if not_fee_defaulter:
        score += 25
        reasons.append("student is not a fee defaulter")
    elif application.finance_fee_defaulter is None:
        reasons.append("fee status not verified yet")
    else:
        reasons.append("student is marked as fee defaulter")

    if not_on_scholarship:
        score += 25
        reasons.append("student is not availing scholarship")
    elif application.finance_scholarship_availing is None:
        reasons.append("scholarship status not verified yet")
    else:
        reasons.append("student is already availing scholarship")

    if documents_complete:
        score += 25
        reasons.append("documents are complete")
    else:
        reasons.append("documents are incomplete")

    if score >= 75:
        recommendation = "Approve"
    elif score >= 50:
        recommendation = "Review"
    else:
        recommendation = "Reject"

    explanation = "; ".join(reasons[:4]) + "."

    application.ai_score = int(score)
    application.ai_recommendation = recommendation
    application.ai_explanation = explanation
    return {
        "ai_score": application.ai_score,
        "ai_recommendation": application.ai_recommendation,
        "ai_explanation": application.ai_explanation,
    }


def approval_chance_from_score(score):
    if score >= 75:
        return "High"
    if score >= 50:
        return "Medium"
    return "Low"


def add_months(base_date, months):
    month_index = base_date.month - 1 + months
    year = base_date.year + month_index // 12
    month = month_index % 12 + 1
    day = min(base_date.day, monthrange(year, month)[1])
    return date(year, month, day)


def determine_installment_status(installment, reference_date=None):
    if installment.status == "paid":
        return "paid"
    if installment.status == "pending_verification":
        return "pending_verification"

    today = reference_date or date.today()
    if today > installment.due_date:
        return "overdue"
    if (installment.due_date - today).days <= 3:
        return "due"
    return "pending"


def sync_installment_statuses(installments, commit=False, reference_date=None):
    changed = False
    for installment in installments:
        new_status = determine_installment_status(installment, reference_date=reference_date)
        if installment.status != new_status:
            installment.status = new_status
            changed = True
    if changed and commit:
        db.session.commit()
    return changed


def installment_badge_class(installment):
    status = installment.status
    if status == "paid":
        return "success"
    if status == "pending_verification":
        return "info"
    if status == "overdue":
        return "danger"
    if status == "due":
        return "warning"
    return "secondary"


def installment_status_label(installment):
    if installment.status == "pending_verification":
        return "Pending Finance Verification"
    return (installment.status or "pending").replace("_", " ").title()


def installment_admin_confirmation_log(installment):
    if not installment or not installment.id:
        return None
    return (
        VerificationLog.query.filter(
            VerificationLog.application_id == installment.application_id,
            VerificationLog.stage == ADMIN_INSTALLMENT_CONFIRMATION_STAGE,
            VerificationLog.remarks.ilike(f"%Installment #{installment.id}:%"),
        )
        .order_by(VerificationLog.created_at.desc())
        .first()
    )


def installment_admin_confirmed(installment):
    return installment_admin_confirmation_log(installment) is not None


def installment_can_pay(installment):
    return installment.status in {"pending", "due", "overdue"}


def recommended_installment_months(application):
    max_semester = int(current_app.config.get("MAX_ELIGIBLE_SEMESTER", 8))
    current_semester = parse_semester_number(application.semester) or max_semester
    return max(1, (max_semester - current_semester + 1) * 4)


def generate_installments_for_application(application, duration_months=None, first_due_date=None):
    if application.loan_amount_issued is None:
        return []

    for installment in list(application.installments):
        db.session.delete(installment)
    db.session.flush()

    total_amount = Decimal(str(application.loan_amount_issued or "0"))
    remaining_months = max(1, int(duration_months or recommended_installment_months(application)))
    first_due_date = first_due_date or add_months(application.expected_disbursement_date or date.today(), 1)
    base_amount = (total_amount / remaining_months).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    installments = []
    allocated = Decimal("0.00")
    for index in range(remaining_months):
        if index == remaining_months - 1:
            amount = (total_amount - allocated).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            amount = base_amount
            allocated += amount

        installment = Installment(
            application_id=application.id,
            amount=amount,
            due_date=add_months(first_due_date, index),
            status="pending",
        )
        db.session.add(installment)
        installments.append(installment)

    db.session.flush()
    sync_installment_statuses(installments)
    return installments


def save_installment_receipt(file_storage, installment):
    filename = secure_filename(file_storage.filename or "")
    if not filename:
        raise ValueError("Select a valid receipt file.")

    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in current_app.config["ALLOWED_EXTENSIONS"]:
        raise ValueError("Only PDF, JPG, JPEG, and PNG receipts are allowed.")

    folder_name = os.path.join(current_app.config["UPLOAD_FOLDER"], installment.application.loan_id, "installments")
    os.makedirs(folder_name, exist_ok=True)

    stored_filename = f"installment_{installment.id}_{secrets.token_hex(8)}.{extension}"
    file_path = os.path.join(folder_name, stored_filename)

    existing_receipt_path = resolve_managed_upload_path(installment.receipt_file)
    if existing_receipt_path:
        try:
            os.remove(existing_receipt_path)
        except OSError:
            current_app.logger.warning("Could not delete old installment receipt %s", installment.receipt_file)

    file_storage.save(file_path)
    installment.receipt_file = file_path
    installment.paid_date = datetime.utcnow()
    installment.verified_by = None
    installment.verified_at = None
    installment.status = "pending_verification"
    return {
        "file_path": file_path,
        "mime_type": mimetypes.guess_type(filename)[0] or "application/octet-stream",
    }


def clear_installment_receipt(installment):
    receipt_path = resolve_managed_upload_path(installment.receipt_file)
    if receipt_path:
        try:
            os.remove(receipt_path)
        except OSError:
            current_app.logger.warning("Could not delete installment receipt %s", installment.receipt_file)
    installment.receipt_file = None
    installment.paid_date = None
    installment.verified_by = None
    installment.verified_at = None
    installment.status = determine_installment_status(installment)


def chatbot_response_for_student(user, message):
    normalized_message = (message or "").strip().lower()
    latest_application = (
        LoanApplication.query.filter_by(student_id=user.id)
        .order_by(LoanApplication.submitted_at.desc())
        .first()
    )

    status_keywords = {"status", "application", "progress", "stage", "track"}
    correction_keywords = {"correction", "correct", "fix", "issue", "update"}
    eligibility_keywords = {"eligible", "eligibility", "apply", "can i apply"}
    approval_keywords = {"chance", "approved", "approval", "rejected", "reject", "risk"}

    if any(keyword in normalized_message for keyword in approval_keywords):
        if not latest_application:
            return "You do not have any applications yet."
        ai_result = evaluate_application_ai(latest_application)
        chance = approval_chance_from_score(ai_result["ai_score"])
        return (
            f"Approval chance: {chance}. "
            f"AI recommendation: {ai_result['ai_recommendation']}. "
            f"Reason: {ai_result['ai_explanation']}"
        )

    if any(keyword in normalized_message for keyword in status_keywords):
        if not latest_application:
            return "You do not have any applications yet."
        return (
            f"Your latest application {latest_application.loan_id} is {latest_application.status}. "
            f"Current stage: {latest_application.current_stage}."
        )

    if any(keyword in normalized_message for keyword in correction_keywords):
        if not latest_application:
            return "There are no correction requests because you do not have an application yet."
        if latest_application.has_outstanding_corrections():
            return latest_application.correction_summary() or "You have pending corrections on your latest application."
        return "There are no pending correction requests on your latest application."

    if any(keyword in normalized_message for keyword in eligibility_keywords):
        block_reason = student_eligibility_block_reason(user)
        if block_reason:
            return f"You are not ready to submit a new application right now. {block_reason}"
        return (
            "You can start a new application if your CGPA is 3.0 or above and you upload the required documents."
        )

    return (
        "I can help with application status, corrections, eligibility, and approval chance. "
        "Try: 'status', 'corrections', 'eligible', or 'approval chance'."
    )
