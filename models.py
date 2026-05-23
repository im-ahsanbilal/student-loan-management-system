import json
import secrets
from datetime import datetime, timedelta

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    roll_number = db.Column(db.String(50), unique=True, nullable=True, index=True)
    father_name = db.Column(db.String(120), nullable=True)
    phone_number = db.Column(db.String(20), nullable=True)
    cnic = db.Column(db.String(20), unique=True, nullable=True, index=True)
    department = db.Column(db.String(100), nullable=True, index=True)
    program_level = db.Column(db.String(10), nullable=True, default="BS")
    semester = db.Column(db.String(20), nullable=True)
    role = db.Column(db.String(20), nullable=False, default="student", index=True)
    otp_verified = db.Column(db.Boolean, nullable=False, default=False)
    registration_otp = db.Column(db.String(6), nullable=True)
    registration_otp_expiry = db.Column(db.DateTime, nullable=True)
    reset_otp = db.Column(db.String(6), nullable=True)
    reset_otp_expiry = db.Column(db.DateTime, nullable=True)
    is_active_account = db.Column(db.Boolean, nullable=False, default=True)
    is_system_generated = db.Column(db.Boolean, nullable=False, default=False)
    profile_photo_path = db.Column(db.String(255), nullable=True)
    profile_photo_original_name = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    applications = db.relationship(
        "LoanApplication",
        back_populates="student",
        lazy=True,
        cascade="all, delete-orphan",
    )
    notifications = db.relationship(
        "Notification",
        back_populates="user",
        lazy=True,
        cascade="all, delete-orphan",
    )
    verification_actions = db.relationship(
        "VerificationLog",
        back_populates="actor",
        lazy=True,
        foreign_keys="VerificationLog.actor_id",
    )
    generated_reports = db.relationship(
        "Report",
        back_populates="generator",
        lazy=True,
        foreign_keys="Report.generated_by",
    )
    managed_departments = db.relationship(
        "Department",
        back_populates="hod",
        lazy=True,
        foreign_keys="Department.hod_id",
    )

    @property
    def is_active(self):
        return self.is_active_account

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def set_registration_otp(self, expiry_minutes):
        self.registration_otp = f"{secrets.randbelow(900000) + 100000:06d}"
        self.registration_otp_expiry = datetime.utcnow() + timedelta(minutes=expiry_minutes)
        return self.registration_otp

    def registration_otp_valid(self, otp):
        return bool(
            self.registration_otp
            and self.registration_otp == otp
            and self.registration_otp_expiry
            and self.registration_otp_expiry >= datetime.utcnow()
        )

    def clear_registration_otp(self):
        self.registration_otp = None
        self.registration_otp_expiry = None

    def set_reset_otp(self, expiry_minutes):
        self.reset_otp = f"{secrets.randbelow(900000) + 100000:06d}"
        self.reset_otp_expiry = datetime.utcnow() + timedelta(minutes=expiry_minutes)
        return self.reset_otp

    def reset_otp_valid(self, otp):
        return bool(
            self.reset_otp
            and self.reset_otp == otp
            and self.reset_otp_expiry
            and self.reset_otp_expiry >= datetime.utcnow()
        )

    def clear_reset_otp(self):
        self.reset_otp = None
        self.reset_otp_expiry = None

    def assigned_department_names(self):
        return sorted(department.name for department in self.managed_departments)


class Department(db.Model):
    __tablename__ = "departments"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True, index=True)
    category = db.Column(db.String(100), nullable=False, index=True)
    hod_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    hod = db.relationship("User", back_populates="managed_departments", foreign_keys=[hod_id])


class LoanApplication(db.Model):
    __tablename__ = "loan_applications"

    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(db.String(30), unique=True, nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    student_name = db.Column(db.String(120), nullable=False, index=True)
    roll_number = db.Column(db.String(50), nullable=False, index=True)
    father_name = db.Column(db.String(120), nullable=False)
    phone_number = db.Column(db.String(20), nullable=True)
    cnic = db.Column(db.String(20), nullable=False, index=True)
    cgpa = db.Column(db.Numeric(4, 2), nullable=True)
    department = db.Column(db.String(100), nullable=False, index=True)
    program_level = db.Column(db.String(10), nullable=True, default="BS")
    semester = db.Column(db.String(20), nullable=False)
    loan_amount_requested = db.Column(db.Numeric(12, 2), nullable=False)
    family_income = db.Column(db.Numeric(12, 2), nullable=False)
    reason_for_loan = db.Column(db.Text, nullable=False)
    bank_name = db.Column(db.String(120), nullable=True)
    iban = db.Column(db.String(34), nullable=True)
    account_holder_relation = db.Column(db.String(20), nullable=True)
    student_iban = db.Column(db.String(34), nullable=True)
    account_holder_name = db.Column(db.String(120), nullable=True)
    relation_to_student = db.Column(db.String(120), nullable=True)
    field_corrections_json = db.Column(db.Text, nullable=True)
    ai_score = db.Column(db.Integer, nullable=True)
    ai_recommendation = db.Column(db.String(20), nullable=True)
    ai_explanation = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), nullable=False, default="Pending", index=True)
    current_stage = db.Column(
        db.String(50),
        nullable=False,
        default="Document Submission",
    )
    hod_status = db.Column(db.String(20), nullable=False, default="Pending")
    finance_status = db.Column(db.String(20), nullable=False, default="Pending")
    admin_status = db.Column(db.String(20), nullable=False, default="Pending")
    scholarship_status = db.Column(db.String(30), nullable=False, default="Not Checked")
    hod_cgpa_verified = db.Column(db.Boolean, nullable=False, default=False)
    hod_department_verified = db.Column(db.Boolean, nullable=False, default=False)
    finance_fee_defaulter = db.Column(db.Boolean, nullable=True)
    finance_scholarship_availing = db.Column(db.Boolean, nullable=True)
    hod_comments = db.Column(db.Text, nullable=True)
    finance_comments = db.Column(db.Text, nullable=True)
    admin_comments = db.Column(db.Text, nullable=True)
    rejected_by_stage = db.Column(db.String(50), nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)
    resubmission_count = db.Column(db.Integer, nullable=False, default=0)
    last_resubmitted_at = db.Column(db.DateTime, nullable=True)
    loan_amount_issued = db.Column(db.Numeric(12, 2), nullable=True)
    disbursement_iban = db.Column(db.String(34), nullable=True)
    university_bank_name = db.Column(db.String(120), nullable=True)
    university_account_number = db.Column(db.String(64), nullable=True)
    expected_disbursement_date = db.Column(db.Date, nullable=True)
    repayment_deadline = db.Column(db.Date, nullable=True)
    disbursement_status = db.Column(db.String(30), nullable=False, default="Pending")
    disbursement_sent_at = db.Column(db.DateTime, nullable=True)
    disbursement_received_at = db.Column(db.DateTime, nullable=True)
    hod_verified_at = db.Column(db.DateTime, nullable=True)
    finance_verified_at = db.Column(db.DateTime, nullable=True)
    admin_decided_at = db.Column(db.DateTime, nullable=True)
    submitted_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    student = db.relationship("User", back_populates="applications", lazy=True)
    documents = db.relationship(
        "Document",
        back_populates="application",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="Document.document_type",
    )
    logs = db.relationship(
        "VerificationLog",
        back_populates="application",
        lazy=True,
        cascade="all, delete-orphan",
    )
    notifications = db.relationship(
        "Notification",
        back_populates="application",
        lazy=True,
        cascade="all, delete-orphan",
    )
    installments = db.relationship(
        "Installment",
        back_populates="application",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="Installment.due_date",
    )

    @property
    def approval_date(self):
        return self.admin_decided_at

    @property
    def disbursement_date(self):
        return self.expected_disbursement_date

    def has_all_required_documents(self, required_documents):
        uploaded_types = {document.document_type for document in self.documents}
        return set(required_documents).issubset(uploaded_types)

    def last_rejection_reason(self):
        if self.rejection_reason:
            return self.rejection_reason
        for comment in [self.admin_comments, self.finance_comments, self.hod_comments]:
            cleaned_comment = (comment or "").strip()
            if cleaned_comment:
                return cleaned_comment
        return ""

    def field_correction_items(self):
        if not self.field_corrections_json:
            return []
        try:
            payload = json.loads(self.field_corrections_json)
        except (TypeError, ValueError):
            return []
        if not isinstance(payload, list):
            return []
        items = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            field_name = (item.get("field") or "").strip()
            label = (item.get("label") or field_name).strip()
            message = (item.get("message") or "").strip()
            if field_name and message:
                items.append({"field": field_name, "label": label or field_name, "message": message})
        return items

    def set_field_correction_items(self, items):
        cleaned = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            field_name = (item.get("field") or "").strip()
            label = (item.get("label") or field_name).strip()
            message = (item.get("message") or "").strip()
            if field_name and message:
                cleaned.append({"field": field_name, "label": label or field_name, "message": message})
        self.field_corrections_json = json.dumps(cleaned) if cleaned else None

    def clear_field_correction(self, field_name):
        self.set_field_correction_items(
            [item for item in self.field_correction_items() if item.get("field") != field_name]
        )

    def flagged_documents(self):
        return [document for document in self.documents if (document.review_status or "Accepted") in {"Pending", "Rejected"}]

    def document_correction_items(self):
        items = []
        for document in self.flagged_documents():
            items.append(
                {
                    "id": document.id,
                    "label": document.document_type,
                    "message": document.review_remarks or f"Document marked {document.review_status}.",
                    "status": document.review_status,
                }
            )
        return items

    def has_outstanding_corrections(self):
        return bool(self.field_correction_items() or self.flagged_documents())

    def correction_request_labels(self):
        labels = [item["label"] for item in self.field_correction_items()]
        labels.extend(item["label"] for item in self.document_correction_items())
        return labels

    def correction_summary(self):
        field_items = self.field_correction_items()
        document_items = self.document_correction_items()
        if field_items and len(field_items) == 1 and not document_items:
            item = field_items[0]
            return f"{item['label']}: {item['message']}"
        if document_items and len(document_items) == 1 and not field_items:
            item = document_items[0]
            return f"{item['label']}: {item['message']}"
        labels = self.correction_request_labels()
        if labels:
            if len(labels) == 2:
                return f"{labels[0]} and {labels[1]} require updates."
            if len(labels) > 2:
                return f"{labels[0]}, {labels[1]}, and {len(labels) - 2} more items require updates."
        return ""

    def flow_progress_index(self):
        if self.status in {"Pending", "HOD Verification"}:
            return 0
        if self.status == "Finance Verification":
            return 1
        if self.status == "Admin Decision":
            return 2
        return 3

    def hod_verified(self):
        return self.hod_status in {"Approved", "Verified"}

    def hod_not_verified(self):
        return self.hod_status in {"Rejected", "Not Verified"}

    def finance_verified(self):
        return self.finance_status in {"Approved", "Verified"}

    def finance_not_verified(self):
        return self.finance_status in {"Rejected", "Not Verified"}

    def approvals_complete(self):
        return self.hod_verified() and self.finance_verified()


class Document(db.Model):
    __tablename__ = "documents"
    __table_args__ = (
        db.UniqueConstraint(
            "application_id",
            "document_type",
            name="uq_documents_application_type",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(
        db.Integer,
        db.ForeignKey("loan_applications.id"),
        nullable=False,
        index=True,
    )
    document_type = db.Column(db.String(50), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(100), nullable=True)
    review_status = db.Column(db.String(20), nullable=False, default="Accepted")
    review_remarks = db.Column(db.Text, nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    uploaded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    application = db.relationship("LoanApplication", back_populates="documents", lazy=True)
    reviewer = db.relationship("User", foreign_keys=[reviewed_by_id], lazy=True)


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    application_id = db.Column(
        db.Integer,
        db.ForeignKey("loan_applications.id"),
        nullable=True,
        index=True,
    )
    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user = db.relationship("User", back_populates="notifications", lazy=True)
    application = db.relationship("LoanApplication", back_populates="notifications", lazy=True)


class Installment(db.Model):
    __tablename__ = "installments"

    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(
        db.Integer,
        db.ForeignKey("loan_applications.id"),
        nullable=False,
        index=True,
    )
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    due_date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(30), nullable=False, default="pending", index=True)
    receipt_file = db.Column(db.String(255), nullable=True)
    paid_date = db.Column(db.DateTime, nullable=True)
    verified_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    verified_at = db.Column(db.DateTime, nullable=True)

    application = db.relationship("LoanApplication", back_populates="installments", lazy=True)
    verifier = db.relationship("User", foreign_keys=[verified_by], lazy=True)


class VerificationLog(db.Model):
    __tablename__ = "verification_logs"

    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(
        db.Integer,
        db.ForeignKey("loan_applications.id"),
        nullable=False,
        index=True,
    )
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    stage = db.Column(db.String(50), nullable=False)
    action = db.Column(db.String(50), nullable=False)
    remarks = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    application = db.relationship("LoanApplication", back_populates="logs", lazy=True)
    actor = db.relationship("User", back_populates="verification_actions", lazy=True)


class Report(db.Model):
    __tablename__ = "reports"

    id = db.Column(db.Integer, primary_key=True)
    generated_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    report_type = db.Column(db.String(100), nullable=False)
    file_format = db.Column(db.String(10), nullable=False)
    filters_json = db.Column(db.Text, nullable=True)
    file_name = db.Column(db.String(255), nullable=False)
    generated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    generator = db.relationship("User", back_populates="generated_reports", lazy=True)
