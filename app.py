import json
import os
from decimal import Decimal
from datetime import datetime, timedelta

from flask import Flask, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy import and_, or_

from blueprints import api_bp, installments_bp
from constants import APPLICATION_FIELD_LABELS, DEPARTMENT_NAMES, DOCUMENT_FIELD_MAP, MINIMUM_CGPA, PROGRAM_CHOICES
from config import Config
from directory_service import (
    department_choices,
    department_has_active_hod,
    ensure_department_directory_integrity,
    get_department_record,
    grouped_departments,
    managed_department_names,
    sync_hod_departments,
)
from extensions import csrf, db, login_manager, mail
from forms import (
    AdminDecisionForm,
    AdminUserForm,
    DocumentUploadForm,
    FinanceDisbursementForm,
    FinanceReviewForm,
    ForgotPasswordForm,
    HODReviewForm,
    LoginForm,
    LoanApplicationForm,
    OTPVerificationForm,
    RegistrationForm,
    ResetPasswordForm,
    StudentProfileForm,
    semester_choices_for_program,
    semester_number,
)
from helpers import (
    PENDING_STATUSES,
    WORKFLOW_STEPS,
    application_requires_correction,
    application_progress_index,
    application_ready_for_admin_decision,
    build_report_payload,
    build_tracking_timeline,
    build_correction_request_message,
    clear_rejection_state,
    create_notification,
    enforce_application_access,
    generate_application_pdf,
    generate_report_chart,
    generate_report_csv,
    generate_report_excel,
    generate_report_pdf,
    generate_report_word,
    generate_unique_loan_id,
    log_verification,
    mark_application_rejected,
    reset_application_for_resubmission,
    role_required,
    resolve_managed_upload_path,
    save_application_document,
    save_profile_photo,
    send_otp_email,
    workflow_snapshot,
)
from migrations import run_migrations
from models import Department, Document, Installment, LoanApplication, Notification, Report, User, VerificationLog
from services import (
    add_months,
    evaluate_application_ai,
    generate_installments_for_application,
    installment_admin_confirmed,
    installment_badge_class,
    installment_can_pay,
    installment_status_label,
    recommended_installment_months,
    student_eligibility_block_reason,
    sync_installment_statuses,
)


app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)
mail.init_app(app)
csrf.init_app(app)
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Please sign in to continue."
login_manager.login_message_category = "warning"

STATUS_OPTIONS = [
    "Pending",
    "HOD Verification",
    "Finance Verification",
    "Admin Decision",
    "Correction Required",
    "Resubmitted",
    "Approved",
    "Rejected",
]
MAX_LOAN_AMOUNT = Decimal("50000.00")


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
with app.app_context():
    db.create_all()
    run_migrations()
    ensure_department_directory_integrity()
    db.session.commit()

app.register_blueprint(api_bp)
app.register_blueprint(installments_bp)


@app.context_processor
def inject_layout_data():
    unread_notifications = 0
    student_is_first_semester = False
    if current_user.is_authenticated:
        unread_notifications = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
        student_is_first_semester = current_user.role == "student" and semester_number(current_user.semester) == 1
    return {
        "application_progress_index": application_progress_index,
        "application_in_finance_review": application_in_finance_review,
        "application_requires_correction": application_requires_correction,
        "application_ready_for_admin_decision": application_ready_for_admin_decision,
        "application_status_badge": application_status_badge,
        "build_tracking_timeline": build_tracking_timeline,
        "application_field_labels": APPLICATION_FIELD_LABELS,
        "current_year": datetime.utcnow().year,
        "max_eligible_semester": app.config["MAX_ELIGIBLE_SEMESTER"],
        "minimum_cgpa": MINIMUM_CGPA,
        "program_choices": PROGRAM_CHOICES,
        "required_documents": app.config["REQUIRED_DOCUMENTS"],
        "status_options": STATUS_OPTIONS,
        "installment_badge_class": installment_badge_class,
        "installment_can_pay": installment_can_pay,
        "installment_admin_confirmed": installment_admin_confirmed,
        "installment_status_label": installment_status_label,
        "unread_notifications": unread_notifications,
        "student_is_first_semester": student_is_first_semester,
        "workflow_snapshot": workflow_snapshot,
        "workflow_steps": WORKFLOW_STEPS,
    }


def configure_registration_form(form):
    selected_program = form.program_level.data or "BS"
    form.department.choices = department_choices(include_blank=True)
    form.semester.choices = semester_choices_for_program(selected_program, application_mode=False)


def configure_application_form(form, application_mode=True):
    selected_program = form.program_level.data or (current_user.program_level if current_user.is_authenticated else "BS") or "BS"
    form.department.choices = department_choices(include_blank=True)
    form.semester.choices = semester_choices_for_program(selected_program, application_mode=application_mode)


def configure_admin_user_form(form):
    selected_program = form.program_level.data or "BS"
    form.department.choices = department_choices(include_blank=True)
    form.semester.choices = semester_choices_for_program(selected_program, application_mode=False)
    form.managed_department_ids.choices = [
        (department.id, department.name)
        for department in Department.query.filter(Department.name.in_(DEPARTMENT_NAMES)).order_by(Department.name.asc()).all()
    ]


def student_is_eligible_for_new_application(user):
    return student_application_block_reason(user) is None


def student_application_block_reason(user):
    return student_eligibility_block_reason(user)


def populate_application_form(form, source):
    account_holder_relation = (
        getattr(source, "account_holder_relation", None)
        or getattr(source, "relation_to_student", None)
        or "Self"
    )
    if account_holder_relation not in {"Self", "Father", "Mother", "Guardian"}:
        account_holder_relation = "Self"
    form.student_name.data = source.student_name if hasattr(source, "student_name") else source.full_name
    form.roll_number.data = source.roll_number
    form.father_name.data = source.father_name
    form.phone_number.data = getattr(source, "phone_number", None)
    form.cnic.data = source.cnic
    form.cgpa.data = getattr(source, "cgpa", None)
    form.department.data = getattr(source, "department", None) or ""
    form.program_level.data = getattr(source, "program_level", None) or "BS"
    form.semester.data = source.semester
    form.bank_name.data = getattr(source, "bank_name", None) or ""
    form.iban.data = getattr(source, "iban", None) or getattr(source, "student_iban", None) or ""
    form.account_holder_relation.data = account_holder_relation
    if hasattr(source, "loan_amount_requested"):
        form.loan_amount_requested.data = source.loan_amount_requested
        form.family_income.data = source.family_income
        form.reason_for_loan.data = source.reason_for_loan


def validate_student_identity_updates(form, user):
    is_valid = True
    normalized_roll_number = (form.roll_number.data or "").strip().upper()
    normalized_cnic = (form.cnic.data or "").strip()

    if normalized_roll_number:
        existing_roll = User.query.filter(User.roll_number == normalized_roll_number, User.id != user.id).first()
        if existing_roll:
            form.roll_number.errors.append("This roll number already exists.")
            is_valid = False

    if normalized_cnic:
        existing_cnic = User.query.filter(User.cnic == normalized_cnic, User.id != user.id).first()
        if existing_cnic:
            form.cnic.errors.append("This CNIC already exists.")
            is_valid = False

    return is_valid


def sync_student_from_application_form(user, form):
    user.full_name = form.student_name.data.strip()
    user.roll_number = form.roll_number.data.strip().upper()
    user.father_name = form.father_name.data.strip()
    user.phone_number = form.phone_number.data.strip()
    user.cnic = form.cnic.data.strip()
    user.department = form.department.data
    user.program_level = form.program_level.data
    user.semester = form.semester.data


def sync_application_from_form(application, user, form):
    application.student_name = user.full_name
    application.roll_number = user.roll_number
    application.father_name = user.father_name
    application.phone_number = form.phone_number.data.strip()
    application.cnic = user.cnic
    application.cgpa = form.cgpa.data
    application.department = form.department.data
    application.program_level = form.program_level.data
    application.semester = form.semester.data
    application.bank_name = form.bank_name.data.strip()
    application.iban = form.iban.data.strip()
    application.account_holder_relation = form.account_holder_relation.data.strip()
    application.student_iban = application.iban
    # Account holder for university repayment is admin-owned and must not be student-derived.
    application.account_holder_name = None
    application.relation_to_student = application.account_holder_relation
    application.loan_amount_requested = form.loan_amount_requested.data
    application.family_income = form.family_income.data
    application.reason_for_loan = form.reason_for_loan.data.strip()


def normalize_application_field_value(field_name, value):
    if value is None:
        return None
    if field_name in {
        "student_name",
        "father_name",
        "department",
        "bank_name",
        "account_holder_name",
        "account_holder_relation",
        "relation_to_student",
        "reason_for_loan",
    }:
        return str(value).strip()
    if field_name == "roll_number":
        return str(value).strip().upper()
    if field_name in {"phone_number", "cnic", "program_level", "semester", "student_iban", "iban"}:
        return str(value).strip()
    if field_name in {"cgpa", "loan_amount_requested", "family_income"}:
        try:
            return Decimal(str(value))
        except Exception:
            return value
    return value


def clear_resolved_field_corrections(application, original_snapshot):
    remaining_items = []
    for item in application.field_correction_items():
        field_name = item.get("field")
        if not field_name:
            continue
        original_value = normalize_application_field_value(field_name, original_snapshot.get(field_name))
        updated_value = normalize_application_field_value(field_name, getattr(application, field_name, None))
        if original_value == updated_value:
            remaining_items.append(item)
    application.set_field_correction_items(remaining_items)


def validate_loan_amount_limit(loan_amount):
    if loan_amount is None:
        return False
    try:
        amount_value = Decimal(str(loan_amount))
    except Exception:
        return False
    return amount_value <= MAX_LOAN_AMOUNT


def build_application_review_fields(application):
    rows = []
    hidden_legacy_fields = {"student_iban", "account_holder_name", "relation_to_student"}
    for field_name, label in APPLICATION_FIELD_LABELS.items():
        if field_name in hidden_legacy_fields:
            continue
        if field_name == "bank_name":
            value = application.bank_name
        elif field_name == "iban":
            value = application.iban or application.student_iban
        elif field_name == "account_holder_relation":
            value = application.account_holder_relation or application.relation_to_student
        else:
            value = getattr(application, field_name, None)
        if field_name == "semester" and value:
            display_value = f"Semester {value}"
        elif field_name in {"loan_amount_requested", "family_income"} and value is not None:
            display_value = f"PKR {float(value):,.2f}"
        elif field_name == "cgpa" and value is not None:
            display_value = f"{float(value):.2f}"
        else:
            display_value = value or "-"
        rows.append({"field_name": field_name, "label": label, "value": display_value})
    return rows


def populate_admin_user_form(form, user):
    form.full_name.data = user.full_name
    form.email.data = user.email
    form.role.data = user.role
    form.roll_number.data = user.roll_number
    form.father_name.data = user.father_name
    form.phone_number.data = user.phone_number
    form.cnic.data = user.cnic
    form.department.data = user.department or ""
    form.program_level.data = user.program_level or "BS"
    form.semester.data = user.semester or ""
    form.managed_department_ids.data = [department.id for department in user.managed_departments]
    form.is_active_account.data = user.is_active_account
    form.otp_verified.data = user.otp_verified
    form.existing_profile_photo = bool(user.profile_photo_path and os.path.exists(user.profile_photo_path))


def apply_user_form_to_user(user, form):
    role = form.role.data
    user.full_name = form.full_name.data.strip()
    user.email = form.email.data.strip().lower()
    user.role = role
    user.is_active_account = bool(form.is_active_account.data)
    user.phone_number = (form.phone_number.data or "").strip() or None

    if role == "student":
        user.roll_number = form.roll_number.data.strip().upper()
        user.father_name = form.father_name.data.strip()
        user.cnic = form.cnic.data.strip()
        user.department = form.department.data or None
        user.program_level = form.program_level.data or "BS"
        user.semester = form.semester.data
        user.otp_verified = bool(form.otp_verified.data)
    else:
        user.roll_number = None
        user.father_name = None
        user.cnic = None
        user.department = None
        user.program_level = None
        user.semester = None
        user.otp_verified = True

    if form.password.data:
        user.set_password(form.password.data)


def validate_unique_user_fields(form, existing_user=None):
    is_valid = True
    normalized_email = form.email.data.strip().lower()
    normalized_roll_number = (form.roll_number.data or "").strip().upper()
    normalized_cnic = (form.cnic.data or "").strip()

    email_query = User.query.filter_by(email=normalized_email)
    roll_query = User.query.filter_by(roll_number=normalized_roll_number) if normalized_roll_number else None
    cnic_query = User.query.filter_by(cnic=normalized_cnic) if normalized_cnic else None

    if existing_user:
        email_query = email_query.filter(User.id != existing_user.id)
        if roll_query is not None:
            roll_query = roll_query.filter(User.id != existing_user.id)
        if cnic_query is not None:
            cnic_query = cnic_query.filter(User.id != existing_user.id)

    if email_query.first():
        form.email.errors.append("This email address is already registered.")
        is_valid = False
    if roll_query is not None and roll_query.first():
        form.roll_number.errors.append("This roll number already exists.")
        is_valid = False
    if cnic_query is not None and cnic_query.first():
        form.cnic.errors.append("This CNIC already exists.")
        is_valid = False
    return is_valid


def validate_hod_department_selection(form):
    if form.role.data != "hod":
        return True
    selected_ids = {int(department_id) for department_id in (form.managed_department_ids.data or [])}
    if not selected_ids:
        return True
    valid_ids = {
        department.id
        for department in Department.query.filter(
            Department.id.in_(selected_ids),
            Department.name.in_(DEPARTMENT_NAMES),
        ).all()
    }
    invalid_ids = selected_ids - valid_ids
    if invalid_ids:
        form.managed_department_ids.errors.append("Select departments from the approved department list only.")
        return False
    return True


def render_users_page(user_form, editing_user=None, search="", role_filter=""):
    query = User.query
    if search:
        query = query.filter(
            or_(
                User.full_name.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%"),
                User.roll_number.ilike(f"%{search}%"),
                User.cnic.ilike(f"%{search}%"),
                User.phone_number.ilike(f"%{search}%"),
                User.department.ilike(f"%{search}%"),
                User.managed_departments.any(Department.name.ilike(f"%{search}%")),
            )
        )
    if role_filter:
        query = query.filter(User.role == role_filter)
    department_filter = request.args.get("department", "").strip()
    if department_filter and department_filter not in DEPARTMENT_NAMES:
        department_filter = ""
    if department_filter:
        query = query.filter(
            or_(
                User.department == department_filter,
                User.managed_departments.any(Department.name == department_filter),
            )
        )

    users = query.order_by(User.created_at.desc()).all()
    return render_template(
        "users.html",
        users=users,
        search=search,
        role_filter=role_filter,
        selected_department=department_filter,
        department_options=[choice[0] for choice in department_choices()],
        user_form=user_form,
        editing_user=editing_user,
        department_groups=grouped_departments(),
    )


def save_photo_with_form_feedback(user, form, require_photo=False):
    existing_photo_available = bool(user.profile_photo_path and os.path.exists(user.profile_photo_path))
    if require_photo and not form.profile_photo.data and not existing_photo_available:
        form.profile_photo.errors.append("Passport-size photo is required for student accounts.")
        return False
    if not form.profile_photo.data:
        return True
    try:
        save_profile_photo(form.profile_photo.data, user)
        return True
    except ValueError as exc:
        form.profile_photo.errors.append(str(exc))
        return False


def ensure_admin_safety_before_role_change(existing_user, target_role, target_active_state):
    if existing_user.role != "admin":
        return True

    active_admin_query = User.query.filter_by(role="admin", is_active_account=True)
    if target_role != "admin":
        if active_admin_query.count() <= 1 and existing_user.is_active_account:
            return False
    if not target_active_state and existing_user.is_active_account and active_admin_query.count() <= 1:
        return False
    return True


def hod_applications_query(user):
    department_names = managed_department_names(user)
    if not department_names:
        return LoanApplication.query.filter(LoanApplication.id == -1)
    return LoanApplication.query.filter(LoanApplication.department.in_(department_names))


def application_in_finance_review(application):
    return application.status == "Finance Verification" or (
        application.status == "Resubmitted" and application.current_stage == "Finance Verification"
    )


def application_status_badge(application):
    if application.status == "Approved":
        return "success"
    if application.status == "Rejected":
        return "danger"
    if application.status in {"Admin Decision", "Resubmitted"} or application_requires_correction(application):
        return "warning"
    return "pending"


def finance_review_query():
    return LoanApplication.query.filter(
        or_(
            LoanApplication.status == "Finance Verification",
            and_(
                LoanApplication.status == "Resubmitted",
                LoanApplication.current_stage == "Finance Verification",
            ),
        )
    )


def notify_role_users(role, title, message, application_id):
    for user in User.query.filter_by(role=role, is_active_account=True).all():
        create_notification(user.id, title, message, application_id)


def reject_other_pending_applications_after_approval(approved_application):
    other_applications = (
        LoanApplication.query.filter(
            LoanApplication.student_id == approved_application.student_id,
            LoanApplication.id != approved_application.id,
            LoanApplication.status.in_(PENDING_STATUSES),
        )
        .order_by(LoanApplication.submitted_at.asc())
        .all()
    )

    for application in other_applications:
        application.admin_status = "Rejected"
        application.admin_comments = "Loan already issued. Other applications are rejected."
        application.loan_amount_issued = None
        application.disbursement_iban = None
        application.expected_disbursement_date = None
        application.repayment_deadline = None
        mark_application_rejected(application, "Admin Decision", "Loan already issued. Other applications are rejected.")
        create_notification(
            application.student_id,
            "Loan already issued",
            f"Application {application.loan_id} was rejected automatically because another loan has already been approved. Loan already issued. Other applications are rejected.",
            application.id,
        )
        log_verification(
            application.id,
            current_user.id,
            "Admin Decision",
            "Auto Rejected",
            "Loan already issued. Other applications are rejected.",
        )

    return len(other_applications)


@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/dashboard")
def dashboard():
    if not current_user.is_authenticated:
        return redirect(url_for("login"))
    if current_user.role == "student":
        return redirect(url_for("student_dashboard"))
    if current_user.role == "hod":
        return redirect(url_for("hod_dashboard"))
    if current_user.role == "finance":
        return redirect(url_for("finance_dashboard"))
    if current_user.role == "admin":
        return redirect(url_for("admin_dashboard"))
    flash("Your account role is not configured correctly.", "danger")
    return redirect(url_for("logout"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    form = RegistrationForm()
    configure_registration_form(form)
    if form.validate_on_submit():
        user = User(
            full_name=form.full_name.data.strip(),
            email=form.email.data.strip().lower(),
            roll_number=form.roll_number.data.strip().upper(),
            father_name=form.father_name.data.strip(),
            phone_number=form.phone_number.data.strip(),
            cnic=form.cnic.data.strip(),
            department=form.department.data,
            program_level=form.program_level.data,
            semester=form.semester.data,
            role="student",
            otp_verified=False,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.flush()
        if not save_photo_with_form_feedback(user, form, require_photo=True):
            db.session.rollback()
            return render_template("register.html", form=form)

        otp = user.set_registration_otp(app.config["OTP_EXPIRY_MINUTES"])
        db.session.commit()

        email_sent = send_otp_email(user, otp, "registration")
        flash("Registration successful. Enter the OTP sent to your email.", "success")
        if not email_sent:
            flash("Email delivery is not configured locally. Check the Flask terminal log for the OTP.", "warning")
        return redirect(url_for("verify_otp", email=user.email, purpose="registration"))

    return render_template("register.html", form=form)


@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    form = OTPVerificationForm()
    if request.method == "GET":
        form.email.data = request.args.get("email", "")
        form.purpose.data = request.args.get("purpose", "registration")

    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.strip().lower()).first()
        if not user or form.purpose.data != "registration":
            flash("Invalid verification request.", "danger")
        elif not user.registration_otp_valid(form.otp.data.strip()):
            flash("Invalid or expired OTP.", "danger")
        else:
            user.otp_verified = True
            user.clear_registration_otp()
            create_notification(user.id, "Registration completed", "Your email has been verified and your account is now active.")
            db.session.commit()
            flash("Email verified successfully. You can now log in.", "success")
            return redirect(url_for("login"))

    return render_template("otp_verify.html", form=form)


@app.route("/resend-otp", methods=["POST"])
def resend_otp():
    email = request.form.get("email", "").strip().lower()
    purpose = request.form.get("purpose", "registration").strip().lower()
    user = User.query.filter_by(email=email).first()

    if not user:
        flash("No account was found for that email address.", "danger")
        if purpose == "reset":
            return redirect(url_for("forgot_password"))
        return redirect(url_for("register"))

    if purpose == "reset":
        otp = user.set_reset_otp(app.config["OTP_EXPIRY_MINUTES"])
    else:
        otp = user.set_registration_otp(app.config["OTP_EXPIRY_MINUTES"])

    db.session.commit()
    email_sent = send_otp_email(user, otp, purpose)
    flash("A new OTP has been generated.", "success")
    if not email_sent:
        flash("Email delivery is not configured locally. Check the Flask terminal log for the OTP.", "warning")

    if purpose == "reset":
        return redirect(url_for("reset_password", email=email))
    return redirect(url_for("verify_otp", email=email, purpose="registration"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = User.query.filter_by(email=email).first()

        if not user or not user.check_password(form.password.data):
            flash("Invalid email or password.", "danger")
        elif not user.is_active_account:
            flash("Your account is inactive. Please contact the administrator.", "danger")
        elif user.role == "student" and not user.otp_verified:
            flash("Verify your email OTP before logging in.", "warning")
            return redirect(url_for("verify_otp", email=user.email, purpose="registration"))
        else:
            login_user(user, remember=form.remember.data)
            next_page = request.args.get("next")
            if next_page and not next_page.startswith("/"):
                next_page = None
            flash("Login successful.", "success")
            return redirect(next_page or url_for("dashboard"))

    return render_template("login.html", form=form)


@app.route("/logout")
@role_required("student", "hod", "finance", "admin")
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    form = ForgotPasswordForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            otp = user.set_reset_otp(app.config["OTP_EXPIRY_MINUTES"])
            db.session.commit()
            email_sent = send_otp_email(user, otp, "reset")
            if not email_sent:
                flash("Email delivery is not configured locally. Check the Flask terminal log for the OTP.", "warning")
        flash("If the email exists, a password reset OTP has been sent.", "info")
        return redirect(url_for("reset_password", email=email))

    return render_template("forgot_password.html", form=form)


@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    form = ResetPasswordForm()
    if request.method == "GET":
        form.email.data = request.args.get("email", "")

    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.strip().lower()).first()
        if not user or not user.reset_otp_valid(form.otp.data.strip()):
            flash("Invalid or expired OTP.", "danger")
        else:
            user.set_password(form.password.data)
            user.clear_reset_otp()
            db.session.commit()
            flash("Password reset successfully. You can now log in.", "success")
            return redirect(url_for("login"))

    return render_template("reset_password.html", form=form)


@app.route("/student/dashboard")
@role_required("student")
def student_dashboard():
    applications = LoanApplication.query.filter_by(student_id=current_user.id).order_by(LoanApplication.submitted_at.desc()).all()
    installments = (
        Installment.query.join(LoanApplication)
        .filter(LoanApplication.student_id == current_user.id)
        .order_by(Installment.due_date.asc(), Installment.id.asc())
        .all()
    )
    sync_installment_statuses(installments, commit=True)
    notifications = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(5).all()
    application_block_reason = student_application_block_reason(current_user)
    paid_installments = [installment for installment in installments if installment.status == "paid"]
    unpaid_installments = [installment for installment in installments if installment.status != "paid"]
    installment_summary = {
        "total": len(installments),
        "paid": len(paid_installments),
        "overdue": len([installment for installment in installments if installment.status == "overdue"]),
        "remaining_amount": sum(Decimal(str(installment.amount or "0")) for installment in unpaid_installments),
    }
    return render_template(
        "student_dashboard.html",
        applications=applications,
        installments=installments,
        notifications=notifications,
        installment_summary=installment_summary,
        payment_history=paid_installments[:5],
        application_block_reason=application_block_reason,
        is_eligible_for_application=application_block_reason is None,
    )


@app.route("/student/profile", methods=["GET", "POST"])
@role_required("student")
def student_profile():
    form = StudentProfileForm()
    if form.validate_on_submit():
        if save_photo_with_form_feedback(current_user, form, require_photo=not current_user.profile_photo_path):
            db.session.commit()
            flash("Profile photo updated successfully.", "success")
            return redirect(url_for("student_profile"))
    return render_template("profile.html", user=current_user, form=form)


@app.route("/users/<int:user_id>/profile-photo")
@role_required("student", "hod", "finance", "admin")
def serve_profile_photo(user_id):
    user = User.query.get_or_404(user_id)
    if current_user.role == "student" and current_user.id != user.id:
        return render_template("403.html"), 403
    profile_photo_path = resolve_managed_upload_path(user.profile_photo_path)
    if not profile_photo_path:
        return render_template("404.html"), 404
    return send_file(profile_photo_path)


@app.route("/student/apply-loan", methods=["GET", "POST"])
@role_required("student")
def apply_loan():
    form = LoanApplicationForm()
    form.require_all_documents = True
    form.enforce_application_eligibility = True
    configure_application_form(form, application_mode=True)
    application_block_reason = student_application_block_reason(current_user)
    is_eligible = application_block_reason is None
    if semester_number(current_user.semester) == 1:
        flash("Students in 1st semester are not eligible to apply for loan.", "danger")
        return redirect(url_for("student_dashboard"))

    if request.method == "GET":
        populate_application_form(form, current_user)
        configure_application_form(form, application_mode=True)

    if form.validate_on_submit():
        if semester_number(form.semester.data) == 1:
            flash("Students in 1st semester are not eligible to apply for loan.", "danger")
            return redirect(url_for("student_dashboard"))
        if not is_eligible:
            flash(application_block_reason or "You are not eligible for a new loan application.", "danger")
            return redirect(url_for("student_dashboard"))
        if not validate_loan_amount_limit(form.loan_amount_requested.data):
            flash("Maximum loan amount is 50,000. You cannot enter more than this limit.", "danger")
            return render_template(
                "apply_loan.html",
                form=form,
                page_heading="Loan Application Form",
                submit_label="Submit Application",
                eligibility_blocked=not is_eligible,
                is_edit_mode=False,
            )
        if not validate_student_identity_updates(form, current_user):
            return render_template(
                "apply_loan.html",
                form=form,
                page_heading="Loan Application Form",
                submit_label="Submit Application",
                eligibility_blocked=not is_eligible,
                is_edit_mode=False,
            )

        if not department_has_active_hod(form.department.data):
            flash("The selected department does not currently have an active HOD assignment. Please contact the administrator.", "danger")
            return render_template(
                "apply_loan.html",
                form=form,
                page_heading="Loan Application Form",
                submit_label="Submit Application",
                eligibility_blocked=not is_eligible,
                is_edit_mode=False,
            )

        sync_student_from_application_form(current_user, form)

        application = LoanApplication(
            loan_id=generate_unique_loan_id(),
            student_id=current_user.id,
            student_name=current_user.full_name,
            roll_number=current_user.roll_number,
            father_name=current_user.father_name,
            phone_number=current_user.phone_number,
            cnic=current_user.cnic,
            cgpa=form.cgpa.data,
            department=form.department.data,
            program_level=form.program_level.data,
            semester=form.semester.data,
            bank_name=form.bank_name.data.strip(),
            iban=form.iban.data.strip(),
            account_holder_relation=form.account_holder_relation.data.strip(),
            student_iban=form.iban.data.strip(),
            account_holder_name=None,
            relation_to_student=form.account_holder_relation.data.strip(),
            loan_amount_requested=form.loan_amount_requested.data,
            family_income=form.family_income.data,
            reason_for_loan=form.reason_for_loan.data.strip(),
            status="HOD Verification",
            current_stage="HOD Verification",
        )
        db.session.add(application)
        db.session.flush()

        for field_name, document_type in DOCUMENT_FIELD_MAP.items():
            save_application_document(getattr(form, field_name).data, application, document_type)
        evaluate_application_ai(application)

        create_notification(
            current_user.id,
            "Loan application submitted",
            f"Application {application.loan_id} was submitted successfully and moved to HOD verification.",
            application.id,
        )
        department = get_department_record(application.department)
        if department and department.hod_id:
            create_notification(
                department.hod_id,
                "New department application",
                f"{application.loan_id} is waiting for HOD review for the {application.department} department.",
                application.id,
            )
        log_verification(
            application.id,
            current_user.id,
            "Application Submission",
            "Submitted",
            "Student submitted the application with all mandatory documents, structured IBAN details, and profile photo on record.",
        )
        db.session.commit()
        flash("Application submitted successfully. All required documents were attached and the case is now with the HOD.", "success")
        return redirect(url_for("student_applications"))

    return render_template(
        "apply_loan.html",
        form=form,
        page_heading="Loan Application Form",
        submit_label="Submit Application",
        eligibility_blocked=not is_eligible,
        is_edit_mode=False,
    )


@app.route("/student/applications")
@role_required("student")
def student_applications():
    applications = LoanApplication.query.filter_by(student_id=current_user.id).order_by(LoanApplication.submitted_at.desc()).all()
    return render_template(
        "applications.html",
        applications=applications,
        page_title="My Applications",
        role_view="student",
        application_block_reason=student_application_block_reason(current_user),
    )


@app.route("/student/applications/<int:application_id>/edit", methods=["GET", "POST"])
@role_required("student")
def edit_application(application_id):
    application = LoanApplication.query.filter_by(id=application_id, student_id=current_user.id).first_or_404()
    is_correction_mode = application_requires_correction(application)
    if application.status not in {"Rejected", "Pending", "Correction Required"}:
        flash("Only returned, correction-required, or rejected applications can be edited.", "warning")
        return redirect(url_for("student_applications"))

    form = LoanApplicationForm()
    form.require_all_documents = False
    form.enforce_application_eligibility = False
    configure_application_form(form, application_mode=False)
    if request.method == "GET":
        populate_application_form(form, application)
        configure_application_form(form, application_mode=False)

    if form.validate_on_submit():
        if not validate_loan_amount_limit(form.loan_amount_requested.data):
            flash("Maximum loan amount is 50,000. You cannot enter more than this limit.", "danger")
            return render_template(
                "apply_loan.html",
                form=form,
                application=application,
                page_heading="Edit Application After Correction" if is_correction_mode else "Edit Rejected Application",
                submit_label="Save Changes",
                rejection_reason=application.last_rejection_reason(),
                correction_reason=application.correction_summary() if is_correction_mode else None,
                eligibility_blocked=False,
                is_edit_mode=True,
                is_correction_mode=is_correction_mode,
            )
        if not validate_student_identity_updates(form, current_user):
            return render_template(
                "apply_loan.html",
                form=form,
                application=application,
                page_heading="Edit Application After Correction" if is_correction_mode else "Edit Rejected Application",
                submit_label="Save Changes",
                rejection_reason=application.last_rejection_reason(),
                correction_reason=application.correction_summary() if is_correction_mode else None,
                eligibility_blocked=False,
                is_edit_mode=True,
                is_correction_mode=is_correction_mode,
            )

        original_snapshot = {field_name: getattr(application, field_name, None) for field_name in APPLICATION_FIELD_LABELS}
        sync_student_from_application_form(current_user, form)
        sync_application_from_form(application, current_user, form)
        clear_resolved_field_corrections(application, original_snapshot)
        evaluate_application_ai(application)
        db.session.commit()
        flash(
            "Application details updated. Replace any incorrect documents if needed, then submit it back into the review workflow.",
            "success",
        )
        return redirect(url_for("upload_documents", application_id=application.id))

    return render_template(
        "apply_loan.html",
        form=form,
        application=application,
        page_heading="Edit Application After Correction" if is_correction_mode else "Edit Rejected Application",
        submit_label="Save Changes",
        rejection_reason=application.last_rejection_reason(),
        correction_reason=application.correction_summary() if is_correction_mode else None,
        eligibility_blocked=False,
        is_edit_mode=True,
        is_correction_mode=is_correction_mode,
    )


@app.route("/student/applications/<int:application_id>/documents", methods=["GET", "POST"])
@role_required("student")
def upload_documents(application_id):
    application = LoanApplication.query.filter_by(id=application_id, student_id=current_user.id).first_or_404()
    form = DocumentUploadForm()
    uploads_locked = application.status not in {"Pending", "Rejected", "Correction Required"}

    if form.validate_on_submit():
        if uploads_locked:
            flash("Document updates are locked while this application is under review or already finalized.", "warning")
            return redirect(url_for("upload_documents", application_id=application.id))
        try:
            save_application_document(form.document_file.data, application, form.document_type.data)
            evaluate_application_ai(application)
            if (
                application.has_all_required_documents(app.config["REQUIRED_DOCUMENTS"])
                and application.status == "Pending"
            ):
                application.status = "HOD Verification"
                application.current_stage = "HOD Verification"
                clear_rejection_state(application)
                evaluate_application_ai(application)
                create_notification(
                    current_user.id,
                    "Documents completed",
                    f"All required documents for application {application.loan_id} were uploaded successfully and forwarded to HOD verification.",
                    application.id,
                )
                department = get_department_record(application.department)
                if department and department.hod_id:
                    create_notification(
                        department.hod_id,
                        "New department application",
                        f"{application.loan_id} is waiting for HOD review for the {application.department} department.",
                        application.id,
                    )
                log_verification(
                    application.id,
                    current_user.id,
                    "Document Submission",
                    "Completed",
                    "All required documents were uploaded and the application moved to HOD verification.",
                )
                flash("Document uploaded successfully. Your application is now in the HOD verification queue.", "success")
            elif application.status in {"Rejected", "Pending", "Correction Required"}:
                flash("Corrected document uploaded. Review the requested changes and resubmit when ready.", "success")
            else:
                flash("Document uploaded successfully.", "success")
            db.session.commit()
            return redirect(url_for("upload_documents", application_id=application.id))
        except ValueError as exc:
            flash(str(exc), "danger")

    uploaded_types = {document.document_type for document in application.documents}
    missing_documents = [doc for doc in app.config["REQUIRED_DOCUMENTS"] if doc not in uploaded_types]
    can_resubmit = (
        application.status in {"Rejected", "Pending", "Correction Required"}
        and application.has_all_required_documents(app.config["REQUIRED_DOCUMENTS"])
        and not application.has_outstanding_corrections()
    )
    return render_template(
        "upload_documents.html",
        application=application,
        form=form,
        missing_documents=missing_documents,
        can_resubmit=can_resubmit,
        rejection_reason=application.last_rejection_reason(),
        uploads_locked=uploads_locked,
    )


@app.route("/student/applications/<int:application_id>/resubmit", methods=["POST"])
@role_required("student")
def resubmit_application(application_id):
    application = LoanApplication.query.filter_by(id=application_id, student_id=current_user.id).first_or_404()
    is_correction_resubmission = application_requires_correction(application)
    if application.status not in {"Rejected", "Pending", "Correction Required"}:
        flash("Only returned, correction-required, or rejected applications can be resubmitted.", "warning")
        return redirect(url_for("student_applications"))

    if not application.has_all_required_documents(app.config["REQUIRED_DOCUMENTS"]):
        flash("Upload all required documents before resubmitting the application.", "danger")
        return redirect(url_for("upload_documents", application_id=application.id))

    if application.has_outstanding_corrections():
        flash("Resolve every document and information correction before resubmitting the application.", "danger")
        return redirect(url_for("upload_documents", application_id=application.id))

    if is_correction_resubmission:
        reset_application_for_resubmission(
            application,
            status="Resubmitted",
            current_stage="Finance Verification",
        )
    else:
        reset_application_for_resubmission(
            application,
            status="HOD Verification",
            current_stage="HOD Verification",
        )
    evaluate_application_ai(application)
    create_notification(
        current_user.id,
        "Application resubmitted",
        (
            f"Application {application.loan_id} has been submitted after correction and moved back to finance verification."
            if is_correction_resubmission
            else f"Application {application.loan_id} has been resubmitted and moved back to HOD verification."
        ),
        application.id,
    )
    department = get_department_record(application.department)
    if is_correction_resubmission:
        notify_role_users(
            "finance",
            "Corrected application ready for finance review",
            f"{application.loan_id} was submitted after correction and is now waiting for finance verification.",
            application.id,
        )
    elif department and department.hod_id:
        create_notification(
            department.hod_id,
            "Resubmitted application ready",
            f"{application.loan_id} has been resubmitted and is ready for HOD review.",
            application.id,
        )
    log_verification(
        application.id,
        current_user.id,
        "Resubmission",
        "Resubmitted",
        (
            "Student updated the requested corrections and submitted the application back to finance verification."
            if is_correction_resubmission
            else "Student updated the application after rejection and sent it back into the workflow."
        ),
    )
    db.session.commit()
    flash(
        (
            "Application submitted after correction. It has been returned to finance verification."
            if is_correction_resubmission
            else "Application resubmitted successfully. It has been sent back to HOD verification."
        ),
        "success",
    )
    return redirect(url_for("student_applications"))


@app.route("/notifications")
@app.route("/student/notifications")
@role_required("student", "hod", "finance", "admin")
def student_notifications():
    notifications = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).all()
    return render_template("notifications.html", notifications=notifications)


@app.route("/notifications/<int:notification_id>/read", methods=["POST"])
@app.route("/student/notifications/<int:notification_id>/read", methods=["POST"])
@role_required("student", "hod", "finance", "admin")
def mark_notification_read(notification_id):
    notification = Notification.query.filter_by(id=notification_id, user_id=current_user.id).first_or_404()
    notification.is_read = True
    db.session.commit()
    flash("Notification marked as read.", "success")
    return redirect(url_for("student_notifications"))


@app.route("/hod/dashboard")
@role_required("hod")
def hod_dashboard():
    department_names = managed_department_names(current_user)
    department_query = hod_applications_query(current_user)
    verification_queue = department_query.filter(LoanApplication.status == "HOD Verification")
    recent_applications = verification_queue.order_by(LoanApplication.submitted_at.desc()).limit(8).all()
    stats = {
        "departments": department_names,
        "pending_verification": verification_queue.count(),
        "verified_by_hod": department_query.filter(LoanApplication.hod_status.in_(["Approved", "Verified"])).count(),
        "not_verified_by_hod": department_query.filter(LoanApplication.hod_status.in_(["Rejected", "Not Verified"])).count(),
    }
    return render_template("hod_dashboard.html", applications=recent_applications, stats=stats)


@app.route("/hod/applications")
@role_required("hod")
def hod_applications():
    status_filter = request.args.get("status", "").strip()
    query = hod_applications_query(current_user)
    if status_filter:
        query = query.filter(LoanApplication.status == status_filter)
    applications = query.order_by(LoanApplication.submitted_at.desc()).all()
    return render_template(
        "applications.html",
        applications=applications,
        page_title="Assigned Department Applications",
        role_view="hod",
        selected_status=status_filter,
    )


@app.route("/hod/applications/<int:application_id>/review", methods=["GET", "POST"])
@role_required("hod")
def hod_review_application(application_id):
    application = LoanApplication.query.get_or_404(application_id)
    if application.department not in managed_department_names(current_user):
        return render_template("403.html"), 403
    if application.status != "HOD Verification":
        flash("This application is not awaiting HOD verification.", "warning")
        return redirect(url_for("hod_applications"))

    form = HODReviewForm()
    if request.method == "GET":
        cgpa_value = float(application.cgpa) if application.cgpa is not None else 0.0
        form.cgpa_verified.data = application.hod_cgpa_verified or cgpa_value >= MINIMUM_CGPA
        form.department_verified.data = application.hod_department_verified or application.department in managed_department_names(current_user)
    if form.validate_on_submit():
        verified = form.decision.data == "verify"
        finance_already_verified = application.finance_verified()
        application.hod_status = "Verified" if verified else "Not Verified"
        application.hod_cgpa_verified = bool(form.cgpa_verified.data)
        application.hod_department_verified = bool(form.department_verified.data)
        application.hod_comments = (form.remarks.data or "").strip() or None
        application.hod_verified_at = datetime.utcnow()
        if verified:
            clear_rejection_state(application)
            action = "Verified"
            if finance_already_verified:
                application.status = "Admin Decision"
                application.current_stage = "Admin Decision"
                title = "HOD verification completed"
                message = f"Application {application.loan_id} passed HOD verification and is back with admin for the final decision."
                notify_role_users(
                    "admin",
                    "Corrected application ready for admin decision",
                    f"{application.loan_id} completed HOD verification after correction and is ready for final admin review.",
                    application.id,
                )
            else:
                application.status = "Finance Verification"
                application.current_stage = "Finance Verification"
                title = "HOD verification completed"
                message = f"Application {application.loan_id} passed HOD verification and has been forwarded to the finance office."
                notify_role_users(
                    "finance",
                    "Application ready for finance review",
                    f"{application.loan_id} is now waiting for finance verification.",
                    application.id,
                )
        else:
            mark_application_rejected(application, "HOD Verification", application.hod_comments)
            title = "Application not verified by HOD"
            message = f"Application {application.loan_id} could not be verified during HOD review. Comments: {application.hod_comments}"
            action = "Not Verified"
        create_notification(application.student_id, title, message, application.id)
        log_verification(application.id, current_user.id, "HOD Verification", action, application.hod_comments)
        db.session.commit()
        flash("HOD verification saved successfully.", "success")
        return redirect(url_for("hod_applications"))

    return render_template(
        "review_application.html",
        form=form,
        application=application,
        review_title="HOD Verification Review",
        review_field_rows=build_application_review_fields(application),
    )


@app.route("/finance/dashboard")
@role_required("finance")
def finance_dashboard():
    queue_query = finance_review_query()
    recent_applications = queue_query.order_by(LoanApplication.submitted_at.desc()).limit(8).all()
    pending_installments_query = (
        Installment.query.join(LoanApplication)
        .filter(Installment.status == "pending_verification")
    )
    pending_installments = pending_installments_query.order_by(Installment.paid_date.desc()).limit(8).all()
    stats = {
        "pending_verification": queue_query.count(),
        "verified_by_finance": LoanApplication.query.filter(LoanApplication.finance_status.in_(["Approved", "Verified"])).count(),
        "not_verified_by_finance": LoanApplication.query.filter(LoanApplication.finance_status.in_(["Rejected", "Not Verified"])).count(),
        "pending_installments": pending_installments_query.count(),
    }
    return render_template(
        "finance_dashboard.html",
        applications=recent_applications,
        pending_installments=pending_installments,
        stats=stats,
    )


@app.route("/finance/applications")
@role_required("finance")
def finance_applications():
    status_filter = request.args.get("status", "").strip()
    if status_filter == "Resubmitted":
        query = LoanApplication.query.filter(
            and_(
                LoanApplication.status == "Resubmitted",
                LoanApplication.current_stage == "Finance Verification",
            )
        )
    elif status_filter:
        query = LoanApplication.query
        query = query.filter(LoanApplication.status == status_filter)
    else:
        query = finance_review_query()
    applications = query.order_by(LoanApplication.submitted_at.desc()).all()
    return render_template(
        "applications.html",
        applications=applications,
        page_title="Finance Verification Queue",
        role_view="finance",
        selected_status=status_filter,
    )


@app.route("/finance/applications/<int:application_id>/review", methods=["GET", "POST"])
@role_required("finance")
def finance_review_application(application_id):
    application = LoanApplication.query.get_or_404(application_id)
    if not application_in_finance_review(application):
        flash("This application is not awaiting finance verification.", "warning")
        return redirect(url_for("finance_applications"))

    form = FinanceReviewForm()
    if request.method == "GET":
        form.not_fee_defaulter.data = application.finance_fee_defaulter is False
        form.not_scholarship_availing.data = (
            application.finance_scholarship_availing is False
            if application.finance_scholarship_availing is not None
            else application.scholarship_status == "Not Receiving"
        )

    if form.validate_on_submit():
        verified = form.decision.data == "verify"
        corrected_application = application.status == "Resubmitted"
        application.finance_status = "Verified" if verified else "Not Verified"
        # These flags only capture verification conditions and AI inputs.
        # They must not reject the application unless finance explicitly selects "Not Verify".
        application.finance_fee_defaulter = not bool(form.not_fee_defaulter.data)
        application.finance_scholarship_availing = not bool(form.not_scholarship_availing.data)
        application.scholarship_status = "Receiving" if application.finance_scholarship_availing else "Not Receiving"
        application.finance_comments = (form.remarks.data or "").strip() or None
        application.finance_verified_at = datetime.utcnow()
        evaluate_application_ai(application)
        if verified:
            clear_rejection_state(application)
            action = "Verified"
            if corrected_application:
                application.status = "HOD Verification"
                application.current_stage = "HOD Verification"
                title = "Finance verification completed"
                message = f"Application {application.loan_id} passed finance verification after correction and is back with the HOD for re-verification."
                department = get_department_record(application.department)
                if department and department.hod_id:
                    create_notification(
                        department.hod_id,
                        "Corrected application ready for HOD review",
                        f"{application.loan_id} completed finance verification after correction and is ready for HOD review.",
                        application.id,
                    )
            else:
                application.status = "Admin Decision"
                application.current_stage = "Admin Decision"
                title = "Finance verification completed"
                message = f"Application {application.loan_id} passed finance verification and is waiting for the final admin decision."
                notify_role_users(
                    "admin",
                    "Application ready for admin decision",
                    f"{application.loan_id} completed finance verification and is ready for final decision.",
                    application.id,
                )
        else:
            mark_application_rejected(application, "Finance Verification", application.finance_comments)
            title = "Application not verified by finance"
            message = f"Application {application.loan_id} could not be verified during finance review. Comments: {application.finance_comments}"
            action = "Not Verified"
        create_notification(application.student_id, title, message, application.id)
        log_verification(application.id, current_user.id, "Finance Verification", action, application.finance_comments)
        db.session.commit()
        flash("Finance verification saved successfully.", "success")
        return redirect(url_for("finance_applications"))

    return render_template(
        "review_application.html",
        form=form,
        application=application,
        review_title="Finance Verification Review",
        review_field_rows=build_application_review_fields(application),
    )


@app.route("/finance/applications/<int:application_id>/disbursement", methods=["GET", "POST"])
@role_required("finance")
def finance_track_disbursement(application_id):
    application = LoanApplication.query.get_or_404(application_id)
    if application.status != "Approved" or application.admin_status != "Approved":
        flash("Disbursement tracking is available only for approved applications.", "warning")
        return redirect(url_for("finance_applications"))

    form = FinanceDisbursementForm()
    if request.method == "GET":
        form.disbursement_status.data = application.disbursement_status if application.disbursement_status != "Pending" else "Eligible"

    if form.validate_on_submit():
        application.disbursement_status = form.disbursement_status.data
        finance_note = (form.remarks.data or "").strip()

        if application.disbursement_status == "Eligible":
            application.disbursement_sent_at = None
            application.disbursement_received_at = None
        elif application.disbursement_status == "Sent":
            application.disbursement_sent_at = application.disbursement_sent_at or datetime.utcnow()
            application.disbursement_received_at = None
        elif application.disbursement_status == "Received":
            application.disbursement_sent_at = application.disbursement_sent_at or datetime.utcnow()
            application.disbursement_received_at = application.disbursement_received_at or datetime.utcnow()

        detail = finance_note or f"Loan disbursement marked as {application.disbursement_status.lower()}."
        create_notification(
            application.student_id,
            "Finance disbursement update",
            f"Application {application.loan_id}: {detail}",
            application.id,
        )
        log_verification(
            application.id,
            current_user.id,
            "Loan Tracking",
            f"Disbursement {application.disbursement_status}",
            detail,
        )
        db.session.commit()
        flash("Disbursement tracking updated successfully.", "success")
        return redirect(url_for("view_application", application_id=application.id))

    return render_template("finance_disbursement.html", form=form, application=application)


@app.route("/admin/dashboard")
@role_required("admin")
def admin_dashboard():
    total_applications = LoanApplication.query.count()
    approved_loans = LoanApplication.query.filter(LoanApplication.status == "Approved").count()
    rejected_loans = LoanApplication.query.filter(LoanApplication.status == "Rejected").count()
    pending_applications = LoanApplication.query.filter(LoanApplication.status.in_(PENDING_STATUSES)).count()
    pending_installments = Installment.query.filter(Installment.status == "pending_verification").count()
    recent_applications = LoanApplication.query.order_by(LoanApplication.submitted_at.desc()).limit(8).all()
    notifications = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(5).all()
    recent_installment_logs = (
        VerificationLog.query.filter(
            VerificationLog.stage.in_(["Installment Verification", "Installment Admin Confirmation"])
        )
        .order_by(VerificationLog.created_at.desc())
        .limit(6)
        .all()
    )
    high_risk_applications = (
        LoanApplication.query.filter(
            LoanApplication.status.in_(PENDING_STATUSES),
            LoanApplication.ai_score.isnot(None),
            LoanApplication.ai_score < 50,
        )
        .order_by(LoanApplication.submitted_at.desc())
        .limit(5)
        .all()
    )
    students_with_overdues = (
        db.session.query(LoanApplication.student_name, LoanApplication.id)
        .join(Installment, Installment.application_id == LoanApplication.id)
        .filter(Installment.status == "overdue")
        .all()
    )
    overdue_counts = {}
    for student_name, _application_id in students_with_overdues:
        overdue_counts[student_name] = overdue_counts.get(student_name, 0) + 1
    multi_overdue_students = sorted(
        [{"student_name": name, "overdue_count": count} for name, count in overdue_counts.items() if count >= 2],
        key=lambda item: item["overdue_count"],
        reverse=True,
    )[:5]
    stats = {
        "total_applications": total_applications,
        "approved_loans": approved_loans,
        "rejected_loans": rejected_loans,
        "pending_applications": pending_applications,
        "pending_installments": pending_installments,
    }
    return render_template(
        "admin_dashboard.html",
        applications=recent_applications,
        notifications=notifications,
        recent_installment_logs=recent_installment_logs,
        high_risk_applications=high_risk_applications,
        multi_overdue_students=multi_overdue_students,
        stats=stats,
    )


@app.route("/admin/applications")
@role_required("admin")
def admin_applications():
    loan_id = request.args.get("loan_id", "").strip()
    student_name = request.args.get("student_name", "").strip()
    roll_number = request.args.get("roll_number", "").strip()
    cnic = request.args.get("cnic", "").strip()
    status = request.args.get("status", "").strip()
    department = request.args.get("department", "").strip()
    if department and department not in DEPARTMENT_NAMES:
        department = ""

    query = LoanApplication.query
    if loan_id:
        query = query.filter(LoanApplication.loan_id.ilike(f"%{loan_id}%"))
    if student_name:
        query = query.filter(LoanApplication.student_name.ilike(f"%{student_name}%"))
    if roll_number:
        query = query.filter(LoanApplication.roll_number.ilike(f"%{roll_number}%"))
    if cnic:
        query = query.filter(LoanApplication.cnic.ilike(f"%{cnic}%"))
    if status:
        query = query.filter(LoanApplication.status == status)
    if department:
        query = query.filter(LoanApplication.department == department)

    applications = query.order_by(LoanApplication.submitted_at.desc()).all()
    return render_template(
        "applications.html",
        applications=applications,
        page_title="All Applications",
        role_view="admin",
        selected_status=status,
        selected_department=department,
        department_options=[choice[0] for choice in department_choices()],
    )


@app.route("/admin/applications/<int:application_id>/decision", methods=["GET", "POST"])
@role_required("admin")
def admin_review_application(application_id):
    application = LoanApplication.query.get_or_404(application_id)
    if application.admin_status != "Pending":
        flash("A final admin decision has already been recorded for this application.", "warning")
        return redirect(url_for("view_application", application_id=application.id))
    if application_requires_correction(application):
        flash("This application is currently with the student for corrections and cannot be finalized yet.", "warning")
        return redirect(url_for("view_application", application_id=application.id))
    if not application_ready_for_admin_decision(application):
        flash("Admin can finalize only after both HOD and finance approvals are completed.", "warning")
        return redirect(url_for("view_application", application_id=application.id))

    form = AdminDecisionForm()
    ai_snapshot = evaluate_application_ai(application)
    if request.method == "GET":
        db.session.commit()
    if request.method == "GET":
        form.hod_cgpa_verified.data = application.hod_cgpa_verified
        form.hod_department_verified.data = application.hod_department_verified
        # Keep university repayment details empty until admin explicitly enters them on approval.
        form.university_bank_name.data = ""
        form.account_holder_name.data = ""
        form.university_account_number.data = ""
        form.disbursement_iban.data = application.iban or application.student_iban or application.disbursement_iban or ""
        form.expected_disbursement_date.data = application.expected_disbursement_date
        form.repayment_deadline.data = application.repayment_deadline
        form.installment_months.data = len(application.installments) or recommended_installment_months(application)
        if application.installments:
            form.first_installment_date.data = application.installments[0].due_date
        else:
            scheduled_disbursement = application.expected_disbursement_date or (datetime.utcnow() + timedelta(days=7)).date()
            form.first_installment_date.data = add_months(scheduled_disbursement, 1)

    if form.validate_on_submit():
        approved = form.decision.data == "approve"
        application.hod_cgpa_verified = bool(form.hod_cgpa_verified.data)
        application.hod_department_verified = bool(form.hod_department_verified.data)
        application.admin_status = "Approved" if approved else "Rejected"
        application.admin_comments = (form.remarks.data or "").strip() or None
        approval_timestamp = datetime.utcnow()
        application.admin_decided_at = approval_timestamp
        if approved:
            application.status = "Approved"
            application.current_stage = "Loan Tracking"
            application.loan_amount_issued = form.approved_amount.data
            application.disbursement_iban = form.disbursement_iban.data
            application.university_bank_name = (form.university_bank_name.data or "").strip()
            application.account_holder_name = (form.account_holder_name.data or "").strip()
            application.university_account_number = (form.university_account_number.data or "").strip()
            application.expected_disbursement_date = (approval_timestamp + timedelta(days=7)).date()
            application.disbursement_status = "Eligible"
            application.disbursement_sent_at = None
            application.disbursement_received_at = None
            application.field_corrections_json = None
            clear_rejection_state(application)
            first_installment_date = form.first_installment_date.data or add_months(application.expected_disbursement_date, 1)
            installments = generate_installments_for_application(
                application,
                duration_months=form.installment_months.data,
                first_due_date=first_installment_date,
            )
            application.repayment_deadline = installments[-1].due_date if installments else None
            evaluate_application_ai(application)
            title = "Loan approved"
            message = (
                f"Application {application.loan_id} has been approved. PKR {application.loan_amount_issued} "
                f"will be disbursed to {application.disbursement_iban} on {application.expected_disbursement_date.strftime('%d %b %Y')} "
                f"with repayment due by {application.repayment_deadline.strftime('%d %b %Y') if application.repayment_deadline else 'the generated installment schedule'}."
            )
            action = "Approved"
            rejected_count = reject_other_pending_applications_after_approval(application)
            if rejected_count:
                message = f"{message} Loan already issued. Other applications are rejected."
            notify_role_users(
                "finance",
                "Student eligible for disbursement",
                f"{application.loan_id} is approved. This student is now eligible for loan disbursement.",
                application.id,
            )
        else:
            application.loan_amount_issued = None
            application.disbursement_iban = None
            application.university_bank_name = None
            application.account_holder_name = None
            application.university_account_number = None
            application.expected_disbursement_date = None
            application.repayment_deadline = None
            application.disbursement_sent_at = None
            application.disbursement_received_at = None
            mark_application_rejected(application, "Admin Decision", application.admin_comments)
            title = "Loan rejected"
            message = f"Application {application.loan_id} was rejected by the administrator. Comments: {application.admin_comments}"
            action = "Rejected"
        create_notification(application.student_id, title, message, application.id)
        log_verification(application.id, current_user.id, "Admin Decision", action, application.admin_comments)
        db.session.commit()
        flash("Final admin decision saved successfully.", "success")
        return redirect(url_for("admin_applications"))
    elif request.method == "POST" and form.decision.data == "approve":
        banking_field_names = {"university_bank_name", "account_holder_name", "university_account_number"}
        if any(form.errors.get(field_name) for field_name in banking_field_names):
            flash("All university banking details are required before approval.", "danger")

    return render_template(
        "review_application.html",
        form=form,
        application=application,
        ai_snapshot=ai_snapshot,
        review_title="Final Admin Decision",
        review_field_rows=build_application_review_fields(application),
    )


@app.route("/admin/applications/<int:application_id>/installments", methods=["GET", "POST"])
@role_required("admin")
def admin_manage_installments(application_id):
    application = LoanApplication.query.get_or_404(application_id)
    if application.admin_status != "Approved" or application.status != "Approved":
        flash("Installment editing is available only after loan approval.", "warning")
        return redirect(url_for("view_application", application_id=application.id))

    sync_installment_statuses(application.installments, commit=True)

    if request.method == "POST":
        action = request.form.get("action", "").strip()
        if action == "regenerate":
            duration_months = request.form.get("duration_months", type=int)
            first_due_date = request.form.get("first_due_date", "").strip()
            if not duration_months or duration_months < 1:
                flash("Enter a valid installment duration in months.", "danger")
                return redirect(url_for("admin_manage_installments", application_id=application.id))
            try:
                first_due_date_value = datetime.strptime(first_due_date, "%Y-%m-%d").date()
            except ValueError:
                flash("Select a valid first installment due date.", "danger")
                return redirect(url_for("admin_manage_installments", application_id=application.id))

            installments = generate_installments_for_application(
                application,
                duration_months=duration_months,
                first_due_date=first_due_date_value,
            )
            application.repayment_deadline = installments[-1].due_date if installments else None
            create_notification(
                application.student_id,
                "Installment plan updated",
                f"The repayment plan for application {application.loan_id} was regenerated by admin.",
                application.id,
            )
            log_verification(
                application.id,
                current_user.id,
                "Installment Plan",
                "Regenerated",
                f"Duration: {duration_months} months | First due date: {first_due_date_value.isoformat()}",
            )
            db.session.commit()
            flash("Installment plan regenerated successfully.", "success")
            return redirect(url_for("admin_manage_installments", application_id=application.id))

        if action == "save":
            total_amount = Decimal("0.00")
            updated_installments = []
            for installment in application.installments:
                amount_value = request.form.get(f"amount_{installment.id}", "").strip()
                due_date_value = request.form.get(f"due_date_{installment.id}", "").strip()
                try:
                    amount_decimal = Decimal(amount_value)
                except Exception:
                    flash("Enter valid installment amounts before saving the schedule.", "danger")
                    return redirect(url_for("admin_manage_installments", application_id=application.id))
                try:
                    due_date = datetime.strptime(due_date_value, "%Y-%m-%d").date()
                except ValueError:
                    flash("Enter valid installment due dates before saving the schedule.", "danger")
                    return redirect(url_for("admin_manage_installments", application_id=application.id))
                if amount_decimal <= 0:
                    flash("Installment amounts must be greater than zero.", "danger")
                    return redirect(url_for("admin_manage_installments", application_id=application.id))

                installment.amount = amount_decimal
                installment.due_date = due_date
                total_amount += amount_decimal
                updated_installments.append(installment)

            issued_amount = Decimal(str(application.loan_amount_issued or "0"))
            if total_amount.quantize(Decimal("0.01")) != issued_amount.quantize(Decimal("0.01")):
                flash("The installment total must match the approved loan amount.", "danger")
                return redirect(url_for("admin_manage_installments", application_id=application.id))

            application.repayment_deadline = max(item.due_date for item in updated_installments) if updated_installments else None
            sync_installment_statuses(updated_installments)
            create_notification(
                application.student_id,
                "Installment plan updated",
                f"The repayment schedule for application {application.loan_id} was adjusted by admin.",
                application.id,
            )
            log_verification(
                application.id,
                current_user.id,
                "Installment Plan",
                "Updated",
                f"Admin updated {len(updated_installments)} installment entries.",
            )
            db.session.commit()
            flash("Installment schedule updated successfully.", "success")
            return redirect(url_for("view_application", application_id=application.id))

    plan_duration = len(application.installments) or recommended_installment_months(application)
    first_due_date = application.installments[0].due_date if application.installments else add_months(application.expected_disbursement_date, 1)
    return render_template(
        "admin_installments.html",
        application=application,
        plan_duration=plan_duration,
        first_due_date=first_due_date,
    )


@app.route("/admin/applications/<int:application_id>/corrections", methods=["POST"])
@role_required("admin")
def admin_request_correction(application_id):
    application = LoanApplication.query.get_or_404(application_id)
    if application.admin_status != "Pending":
        flash("Corrections cannot be requested after a final admin decision.", "warning")
        return redirect(url_for("view_application", application_id=application.id))
    if not application_ready_for_admin_decision(application):
        flash("Admin corrections can only be requested after HOD and finance approvals are complete.", "warning")
        return redirect(url_for("view_application", application_id=application.id))

    remarks = request.form.get("remarks", "").strip()
    field_names = [item.strip() for item in request.form.getlist("field_names") if item.strip()]
    document_ids = [int(item) for item in request.form.getlist("document_ids") if item.strip().isdigit()]
    single_field_name = request.form.get("field_name", "").strip()
    single_document_id = request.form.get("document_id", type=int)
    if single_field_name and single_field_name not in field_names:
        field_names.append(single_field_name)
    if single_document_id and single_document_id not in document_ids:
        document_ids.append(single_document_id)

    if len(remarks) < 5:
        flash("Provide at least 5 characters so the student understands the correction request.", "danger")
        return redirect(url_for("admin_review_application", application_id=application.id))

    invalid_fields = [field_name for field_name in field_names if field_name not in APPLICATION_FIELD_LABELS]
    if invalid_fields:
        flash("One or more selected application fields are invalid for correction.", "danger")
        return redirect(url_for("admin_review_application", application_id=application.id))

    selected_documents = []
    if document_ids:
        selected_documents = (
            Document.query.filter(Document.application_id == application.id, Document.id.in_(document_ids))
            .order_by(Document.document_type.asc())
            .all()
        )
        if len(selected_documents) != len(document_ids):
            flash("One or more selected documents are invalid for correction.", "danger")
            return redirect(url_for("admin_review_application", application_id=application.id))

    if not field_names and not selected_documents:
        flash("Select at least one field or document to request a correction.", "danger")
        return redirect(url_for("admin_review_application", application_id=application.id))

    field_corrections = [item for item in application.field_correction_items() if item.get("field") not in field_names]
    selected_labels = []
    for field_name in field_names:
        field_corrections.append(
            {
                "field": field_name,
                "label": APPLICATION_FIELD_LABELS[field_name],
                "message": remarks,
            }
        )
        selected_labels.append(APPLICATION_FIELD_LABELS[field_name])
    application.set_field_correction_items(field_corrections)

    for document in selected_documents:
        document.review_status = "Pending"
        document.review_remarks = remarks
        document.reviewed_at = datetime.utcnow()
        document.reviewed_by_id = current_user.id
        selected_labels.append(document.document_type)

    application.status = "Correction Required"
    application.current_stage = "Correction Required"
    application.disbursement_status = "Pending"
    application.disbursement_sent_at = None
    application.disbursement_received_at = None
    clear_rejection_state(application)

    create_notification(
        application.student_id,
        "Correction requested",
        build_correction_request_message(application, selected_labels, remarks),
        application.id,
    )
    log_verification(
        application.id,
        current_user.id,
        "Admin Correction",
        "Requested",
        f"{', '.join(selected_labels)} | Notes: {remarks}",
    )
    db.session.commit()
    flash("Correction request saved. The application has been returned to the student for updates.", "success")
    return redirect(url_for("view_application", application_id=application.id))


@app.route("/applications/<int:application_id>")
@role_required("student", "hod", "finance", "admin")
def view_application(application_id):
    application = LoanApplication.query.get_or_404(application_id)
    enforce_application_access(application)
    sync_installment_statuses(application.installments, commit=True)
    return render_template("application_detail.html", application=application)


@app.route("/admin/users")
@role_required("admin")
def admin_users():
    search = request.args.get("search", "").strip()
    role_filter = request.args.get("role", "").strip()
    edit_user_id = request.args.get("edit", type=int)
    user_form = AdminUserForm()
    configure_admin_user_form(user_form)
    editing_user = None

    if edit_user_id:
        editing_user = User.query.get_or_404(edit_user_id)
        populate_admin_user_form(user_form, editing_user)
        configure_admin_user_form(user_form)

    return render_users_page(user_form, editing_user=editing_user, search=search, role_filter=role_filter)


@app.route("/admin/users/create", methods=["POST"])
@role_required("admin")
def create_user():
    user_form = AdminUserForm()
    configure_admin_user_form(user_form)
    if not user_form.password.data:
        user_form.password.errors.append("Password is required when creating a user.")

    is_valid = user_form.validate_on_submit()
    if user_form.password.errors:
        is_valid = False
    if is_valid:
        is_valid = validate_unique_user_fields(user_form)
    if is_valid:
        is_valid = validate_hod_department_selection(user_form)

    if is_valid:
        user = User()
        apply_user_form_to_user(user, user_form)
        db.session.add(user)
        db.session.flush()
        is_valid = save_photo_with_form_feedback(user, user_form, require_photo=user.role == "student")

    if is_valid:
        if user.role == "hod":
            selected_departments = user_form.managed_department_ids.data if user.is_active_account else []
            sync_hod_departments(user, selected_departments, excluded_user_ids={user.id} if not user.is_active_account else None)
        db.session.commit()
        flash("User created successfully.", "success")
        return redirect(url_for("admin_users"))

    db.session.rollback()
    return render_users_page(user_form)


@app.route("/admin/users/<int:user_id>/edit", methods=["POST"])
@role_required("admin")
def update_user(user_id):
    editing_user = User.query.get_or_404(user_id)
    user_form = AdminUserForm()
    configure_admin_user_form(user_form)
    user_form.existing_profile_photo = bool(editing_user.profile_photo_path and os.path.exists(editing_user.profile_photo_path))

    is_valid = user_form.validate_on_submit()
    if is_valid:
        is_valid = validate_unique_user_fields(user_form, existing_user=editing_user)
    if is_valid:
        is_valid = validate_hod_department_selection(user_form)

    target_active = bool(user_form.is_active_account.data)
    target_role = user_form.role.data
    if is_valid and not ensure_admin_safety_before_role_change(editing_user, target_role, target_active):
        user_form.role.errors.append("The last active admin account cannot be removed or deactivated.")
        is_valid = False

    if is_valid:
        apply_user_form_to_user(editing_user, user_form)
        db.session.flush()
        is_valid = save_photo_with_form_feedback(editing_user, user_form, require_photo=target_role == "student")

    if is_valid:
        selected_departments = user_form.managed_department_ids.data if target_role == "hod" and target_active else []
        sync_hod_departments(
            editing_user,
            selected_departments,
            excluded_user_ids={editing_user.id} if target_role != "hod" or not target_active else None,
        )
        db.session.commit()
        flash("User updated successfully.", "success")
        return redirect(url_for("admin_users"))

    db.session.rollback()
    return render_users_page(user_form, editing_user=editing_user)


@app.route("/admin/users/<int:user_id>/toggle-status", methods=["POST"])
@role_required("admin")
def toggle_user_status(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("You cannot change your own account status.", "danger")
        return redirect(url_for("admin_users"))

    if user.role == "admin" and user.is_active_account:
        active_admins = User.query.filter_by(role="admin", is_active_account=True).count()
        if active_admins <= 1:
            flash("You cannot deactivate the last active admin account.", "danger")
            return redirect(url_for("admin_users"))

    if user.role == "hod" and user.is_active_account:
        sync_hod_departments(user, [], excluded_user_ids={user.id})

    user.is_active_account = not user.is_active_account
    db.session.commit()
    flash("User status updated successfully.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@role_required("admin")
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for("admin_users"))

    if user.role == "admin":
        admin_count = User.query.filter_by(role="admin").count()
        if admin_count <= 1:
            flash("You cannot delete the last admin account.", "danger")
            return redirect(url_for("admin_users"))

    if user.role == "hod":
        sync_hod_departments(user, [], excluded_user_ids={user.id})

    db.session.delete(user)
    db.session.commit()
    flash("User deleted successfully.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/logs")
@role_required("admin")
def admin_logs():
    logs = VerificationLog.query.order_by(VerificationLog.created_at.desc()).all()
    return render_template("logs.html", logs=logs)


@app.route("/admin/reports", methods=["GET", "POST"])
@role_required("admin")
def reports():
    status_filter = request.values.get("status", "").strip()
    department_filter = request.values.get("department", "").strip()
    if department_filter and department_filter not in DEPARTMENT_NAMES:
        department_filter = ""
    payload = build_report_payload(status_filter or None, department_filter or None)

    department_options = [choice[0] for choice in department_choices()]

    if request.method == "POST":
        export_format = request.form.get("format", "pdf").strip().lower()
        try:
            if export_format == "excel":
                buffer, file_name = generate_report_excel(payload)
                mimetype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                file_format = "EXCEL"
            elif export_format == "word":
                buffer, file_name = generate_report_word(payload)
                mimetype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                file_format = "WORD"
            elif export_format == "chart":
                buffer, file_name = generate_report_chart(payload)
                mimetype = "image/png"
                file_format = "CHART"
            elif export_format == "csv":
                buffer, file_name = generate_report_csv(payload)
                mimetype = "text/csv"
                file_format = "CSV"
            else:
                buffer, file_name = generate_report_pdf(payload)
                mimetype = "application/pdf"
                file_format = "PDF"
        except RuntimeError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("reports", status=status_filter, department=department_filter))

        report = Report(
            generated_by=current_user.id,
            report_type="Loan Summary Report",
            file_format=file_format,
            filters_json=json.dumps(payload["filters"]),
            file_name=file_name,
        )
        db.session.add(report)
        db.session.commit()
        return send_file(buffer, as_attachment=True, download_name=file_name, mimetype=mimetype)

    recent_reports = Report.query.order_by(Report.generated_at.desc()).limit(10).all()
    chart_payload = {
        "status_labels": [status_name for status_name, _ in payload["status_rows"]],
        "status_values": [count for _, count in payload["status_rows"]],
        "department_labels": [(department or "Unknown") for department, _ in payload["department_rows"]],
        "department_values": [count for _, count in payload["department_rows"]],
    }
    return render_template(
        "reports.html",
        summary=payload["summary"],
        department_rows=payload["department_rows"],
        coverage_rows=payload["coverage_rows"],
        applications=payload["applications"],
        recent_reports=recent_reports,
        status_filter=status_filter,
        department_filter=department_filter,
        department_options=department_options,
        chart_payload=chart_payload,
    )


@app.route("/applications/<int:application_id>/pdf")
@role_required("student", "hod", "finance", "admin")
def download_application_pdf(application_id):
    application = LoanApplication.query.get_or_404(application_id)
    enforce_application_access(application)
    try:
        buffer = generate_application_pdf(application)
        return send_file(
            buffer,
            as_attachment=True,
            download_name=f"{application.loan_id}-application.pdf",
            mimetype="application/pdf",
        )
    except Exception as exc:
        app.logger.exception("Application PDF generation failed for %s: %s", application.loan_id, exc)
        flash("The application PDF could not be generated right now. Please try again.", "danger")
        return redirect(url_for("view_application", application_id=application.id))


@app.route("/documents/<int:document_id>/download")
@role_required("student", "hod", "finance", "admin")
def download_document(document_id):
    document = Document.query.get_or_404(document_id)
    enforce_application_access(document.application)
    safe_document_path = resolve_managed_upload_path(document.file_path)
    if not safe_document_path:
        flash("The requested file is no longer available.", "danger")
        return redirect(url_for("dashboard"))
    return send_file(
        safe_document_path,
        as_attachment=True,
        download_name=document.original_filename,
        mimetype=document.mime_type or "application/octet-stream",
    )


@app.route("/documents/<int:document_id>/preview")
@role_required("student", "hod", "finance", "admin")
def preview_document(document_id):
    document = Document.query.get_or_404(document_id)
    enforce_application_access(document.application)
    safe_document_path = resolve_managed_upload_path(document.file_path)
    if not safe_document_path:
        flash("The requested file is no longer available.", "danger")
        return redirect(url_for("dashboard"))
    return send_file(
        safe_document_path,
        as_attachment=False,
        download_name=document.original_filename,
        mimetype=document.mime_type or "application/octet-stream",
        conditional=True,
    )


@app.errorhandler(403)
def forbidden(error):
    return render_template("403.html"), 403


@app.errorhandler(404)
def page_not_found(error):
    return render_template("404.html"), 404


@app.errorhandler(500)
def internal_server_error(error):
    db.session.rollback()
    return render_template("500.html"), 500


if __name__ == "__main__":
    app.run(debug=True)
