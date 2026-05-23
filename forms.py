import re
from decimal import Decimal

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import (
    BooleanField,
    DateField,
    DecimalField,
    HiddenField,
    IntegerField,
    PasswordField,
    SelectField,
    SelectMultipleField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Email, EqualTo, Length, NumberRange, Optional, ValidationError

from constants import (
    ACCOUNT_HOLDER_RELATION_CHOICES,
    BS_ELIGIBLE_SEMESTER_CHOICES,
    DEPARTMENT_NAMES,
    DISBURSEMENT_STATUS_CHOICES,
    DOCUMENT_FIELD_MAP,
    IBAN_PATTERN,
    MINIMUM_CGPA,
    PASSWORD_PATTERN,
    PHONE_NUMBER_PATTERN,
    PROGRAM_CHOICES,
    REGISTRATION_SEMESTER_CHOICES,
    ROLL_NUMBER_PATTERN,
)
from models import User


DOCUMENT_CHOICES = [(document_name, document_name) for document_name in DOCUMENT_FIELD_MAP.values()]
ADMIN_BANKING_REQUIRED_MESSAGE = "All university banking details are required before approval."


def normalize_roll_number(value):
    return (value or "").strip().upper()


def normalize_phone_number(value):
    cleaned = re.sub(r"[\s\-()]", "", value or "")
    if cleaned.startswith("03") and len(cleaned) == 11:
        return f"+92{cleaned[1:]}"
    return cleaned


def normalize_iban(value):
    return (value or "").replace(" ", "").upper()


def validate_roll_number_format(form, field):
    normalized = normalize_roll_number(field.data)
    if not re.fullmatch(ROLL_NUMBER_PATTERN, normalized):
        raise ValidationError("Use the roll number format abc0000000.")
    field.data = normalized


def validate_phone_number_format(form, field):
    normalized = normalize_phone_number(field.data)
    if not re.fullmatch(PHONE_NUMBER_PATTERN, normalized):
        raise ValidationError("Use a valid phone number like 03001234567 or +923001234567.")
    field.data = normalized


def validate_cnic_format(form, field):
    if not re.fullmatch(r"\d{5}-\d{7}-\d", (field.data or "").strip()):
        raise ValidationError("Use the CNIC format 12345-1234567-1.")


def validate_iban_format(form, field):
    normalized = normalize_iban(field.data)
    if not re.fullmatch(IBAN_PATTERN, normalized):
        raise ValidationError("Enter a valid IBAN such as PK36SCBL0000001123456702.")
    field.data = normalized


def validate_password_strength(form, field):
    if not re.fullmatch(PASSWORD_PATTERN, field.data or ""):
        raise ValidationError("Password must include uppercase, lowercase, number, and special character.")


def semester_number(raw_value):
    digits = "".join(character for character in str(raw_value or "") if character.isdigit())
    if not digits:
        return None
    return int(digits)


def semester_choices_for_program(program_level, application_mode=False):
    if (program_level or "BS") == "MS":
        limit = 3
        choices = [choice for choice in REGISTRATION_SEMESTER_CHOICES if int(choice[0]) <= limit]
        if application_mode:
            return [choice for choice in choices if int(choice[0]) >= 2]
        return choices
    if application_mode:
        return [choice for choice in BS_ELIGIBLE_SEMESTER_CHOICES if int(choice[0]) >= 2]
    return REGISTRATION_SEMESTER_CHOICES


def validate_program_semester(program_level, raw_semester, application_mode=False):
    semester = semester_number(raw_semester)
    if semester is None:
        return "Select a valid semester."
    if application_mode and semester == 1:
        return "Students in 1st semester are not eligible to apply for loan."

    if (program_level or "BS") == "MS":
        if semester > 3:
            return "Master students can apply or register only up to Semester 3."
        return None

    max_bs_semester = max(int(choice[0]) for choice in REGISTRATION_SEMESTER_CHOICES)
    if semester > max_bs_semester:
        return f"BS students can apply or register only up to Semester {max_bs_semester}."
    return None


def validate_allowed_department(form, field):
    if not (field.data or "").strip():
        return
    if (field.data or "").strip() not in set(DEPARTMENT_NAMES):
        raise ValidationError("Select a valid department from the approved department list.")


class RegistrationForm(FlaskForm):
    full_name = StringField("Full Name", validators=[DataRequired(), Length(max=120)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField(
        "Password",
        validators=[DataRequired(), Length(min=8, max=64), validate_password_strength],
    )
    confirm_password = PasswordField(
        "Confirm Password",
        validators=[DataRequired(), EqualTo("password")],
    )
    roll_number = StringField("Roll Number", validators=[DataRequired(), Length(max=50), validate_roll_number_format])
    father_name = StringField("Father Name", validators=[DataRequired(), Length(max=120)])
    phone_number = StringField("Phone Number", validators=[DataRequired(), validate_phone_number_format])
    cnic = StringField("CNIC", validators=[DataRequired(), validate_cnic_format])
    department = SelectField("Department", choices=[("", "Select Department")], validators=[DataRequired(), validate_allowed_department])
    program_level = SelectField("Program", choices=PROGRAM_CHOICES, validators=[DataRequired()])
    semester = SelectField("Semester", choices=REGISTRATION_SEMESTER_CHOICES, validators=[DataRequired()])
    profile_photo = FileField(
        "Passport-size Photo",
        validators=[FileRequired(), FileAllowed(["jpg", "jpeg", "png"], "Only JPG and PNG files are allowed.")],
    )
    submit = SubmitField("Register")

    def validate(self, extra_validators=None):
        is_valid = super().validate(extra_validators=extra_validators)
        semester_error = validate_program_semester(self.program_level.data, self.semester.data, application_mode=False)
        if semester_error:
            self.semester.errors.append(semester_error)
            is_valid = False
        return is_valid

    def validate_email(self, field):
        existing_user = User.query.filter_by(email=field.data.strip().lower()).first()
        if existing_user:
            raise ValidationError("This email address is already registered.")

    def validate_roll_number(self, field):
        normalized = normalize_roll_number(field.data)
        existing_user = User.query.filter_by(roll_number=normalized).first()
        if existing_user:
            raise ValidationError("This roll number already exists.")

    def validate_cnic(self, field):
        existing_user = User.query.filter_by(cnic=(field.data or "").strip()).first()
        if existing_user:
            raise ValidationError("This CNIC already exists.")


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])
    remember = BooleanField("Remember me")
    submit = SubmitField("Login")


class OTPVerificationForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    otp = StringField("OTP", validators=[DataRequired(), Length(min=6, max=6)])
    purpose = HiddenField(default="registration")
    submit = SubmitField("Verify OTP")


class ForgotPasswordForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    submit = SubmitField("Send Reset OTP")


class ResetPasswordForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    otp = StringField("OTP", validators=[DataRequired(), Length(min=6, max=6)])
    password = PasswordField(
        "New Password",
        validators=[DataRequired(), Length(min=8, max=64), validate_password_strength],
    )
    confirm_password = PasswordField(
        "Confirm New Password",
        validators=[DataRequired(), EqualTo("password")],
    )
    submit = SubmitField("Reset Password")


class LoanApplicationForm(FlaskForm):
    student_name = StringField("Student Name", validators=[DataRequired(), Length(max=120)])
    roll_number = StringField("Roll Number", validators=[DataRequired(), Length(max=50), validate_roll_number_format])
    father_name = StringField("Father Name", validators=[DataRequired(), Length(max=120)])
    phone_number = StringField("Phone Number", validators=[DataRequired(), validate_phone_number_format])
    cnic = StringField("CNIC", validators=[DataRequired(), validate_cnic_format])
    cgpa = DecimalField(
        "CGPA",
        places=2,
        validators=[DataRequired(), NumberRange(min=Decimal("0.00"), max=Decimal("4.00"))],
    )
    department = SelectField("Department", choices=[("", "Select Department")], validators=[DataRequired(), validate_allowed_department])
    program_level = SelectField("Program", choices=PROGRAM_CHOICES, validators=[DataRequired()])
    semester = SelectField("Semester", choices=REGISTRATION_SEMESTER_CHOICES, validators=[DataRequired()])
    bank_name = StringField(
        "Bank Name",
        validators=[DataRequired(message="Bank name is required."), Length(max=120)],
    )
    iban = StringField(
        "IBAN",
        validators=[
            DataRequired(message="IBAN is required."),
            Length(min=24, max=34, message="IBAN must be at least 24 characters long."),
            validate_iban_format,
        ],
    )
    account_holder_relation = SelectField(
        "Account Holder Relation",
        choices=ACCOUNT_HOLDER_RELATION_CHOICES,
        default="Self",
        validators=[DataRequired(message="Account holder relation is required.")],
    )
    loan_amount_requested = DecimalField(
        "Loan Amount Requested",
        places=2,
        validators=[
            DataRequired(),
            NumberRange(
                min=Decimal("1.00"),
                max=Decimal("50000.00"),
                message="Maximum loan amount is 50,000. You cannot enter more than this limit.",
            ),
        ],
    )
    family_income = DecimalField(
        "Family Income",
        places=2,
        validators=[DataRequired(), NumberRange(min=Decimal("0.00"))],
    )
    reason_for_loan = TextAreaField(
        "Reason for Loan",
        validators=[DataRequired(), Length(min=10, max=1000)],
    )
    cnic_document = FileField(
        "CNIC Document",
        validators=[FileAllowed(["pdf", "jpg", "jpeg", "png"], "Only PDF, JPG, JPEG, and PNG files are allowed.")],
    )
    student_card_document = FileField(
        "Student Card",
        validators=[FileAllowed(["pdf", "jpg", "jpeg", "png"], "Only PDF, JPG, JPEG, and PNG files are allowed.")],
    )
    fee_voucher_document = FileField(
        "Fee Voucher",
        validators=[FileAllowed(["pdf", "jpg", "jpeg", "png"], "Only PDF, JPG, JPEG, and PNG files are allowed.")],
    )
    father_cnic_document = FileField(
        "Father CNIC",
        validators=[FileAllowed(["pdf", "jpg", "jpeg", "png"], "Only PDF, JPG, JPEG, and PNG files are allowed.")],
    )
    academic_transcript_document = FileField(
        "Academic Transcript",
        validators=[FileAllowed(["pdf", "jpg", "jpeg", "png"], "Only PDF, JPG, JPEG, and PNG files are allowed.")],
    )
    submit = SubmitField("Submit Application")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.require_all_documents = False
        self.enforce_application_eligibility = False

    def validate(self, extra_validators=None):
        is_valid = super().validate(extra_validators=extra_validators)

        semester_error = validate_program_semester(
            self.program_level.data,
            self.semester.data,
            application_mode=self.enforce_application_eligibility,
        )
        if semester_error:
            self.semester.errors.append(semester_error)
            is_valid = False

        if self.cgpa.data is not None and self.cgpa.data < Decimal(str(MINIMUM_CGPA)):
            self.cgpa.errors.append(f"Only students with CGPA {MINIMUM_CGPA:.1f} or above can apply.")
            is_valid = False

        if self.require_all_documents:
            for field_name, document_label in DOCUMENT_FIELD_MAP.items():
                field = getattr(self, field_name)
                if not field.data:
                    field.errors.append(f"{document_label} must be uploaded before submission.")
                    is_valid = False

        return is_valid


class DocumentUploadForm(FlaskForm):
    document_type = SelectField("Document Type", choices=DOCUMENT_CHOICES, validators=[DataRequired()])
    document_file = FileField(
        "Upload File",
        validators=[
            FileRequired(),
            FileAllowed(["pdf", "jpg", "jpeg", "png"], "Only PDF, JPG, JPEG, and PNG files are allowed."),
        ],
    )
    submit = SubmitField("Upload Document")


class HODReviewForm(FlaskForm):
    decision = SelectField(
        "Verification Status",
        choices=[("verify", "Verify"), ("not_verify", "Not Verify")],
        validators=[DataRequired()],
    )
    cgpa_verified = BooleanField(f"CGPA is {MINIMUM_CGPA:.1f} or above")
    department_verified = BooleanField("Student belongs to the selected department")
    remarks = TextAreaField("Comments", validators=[Optional(), Length(max=1000)])
    submit = SubmitField("Submit Verification")

    def validate(self, extra_validators=None):
        is_valid = super().validate(extra_validators=extra_validators)
        if self.decision.data == "verify":
            if not self.cgpa_verified.data:
                self.cgpa_verified.errors.append("Confirm the CGPA check before verifying.")
                is_valid = False
            if not self.department_verified.data:
                self.department_verified.errors.append("Confirm the department check before verifying.")
                is_valid = False
        if self.decision.data == "not_verify" and len((self.remarks.data or "").strip()) < 5:
            self.remarks.errors.append("Comments are mandatory (min 5 characters) when marking as not verified.")
            is_valid = False
        return is_valid


class FinanceReviewForm(FlaskForm):
    decision = SelectField(
        "Verification Status",
        choices=[("verify", "Verify"), ("not_verify", "Not Verify")],
        validators=[DataRequired()],
    )
    not_fee_defaulter = BooleanField("Student is NOT a fee defaulter")
    not_scholarship_availing = BooleanField("Student is NOT availing any scholarship")
    remarks = TextAreaField("Comments", validators=[Optional(), Length(max=1000)])
    submit = SubmitField("Submit Verification")

    def validate(self, extra_validators=None):
        is_valid = super().validate(extra_validators=extra_validators)
        if self.decision.data == "not_verify" and len((self.remarks.data or "").strip()) < 5:
            self.remarks.errors.append("Comments are mandatory (min 5 characters) when marking as not verified.")
            is_valid = False
        return is_valid


class AdminDecisionForm(FlaskForm):
    decision = SelectField(
        "Final Decision",
        choices=[("approve", "Approve Loan"), ("reject", "Reject Loan")],
        validators=[DataRequired()],
    )
    hod_cgpa_verified = BooleanField(f"CGPA is {MINIMUM_CGPA:.1f} or above")
    hod_department_verified = BooleanField("Student belongs to the selected department")
    approved_amount = DecimalField(
        "Loan Amount Issued",
        places=2,
        validators=[Optional(), NumberRange(min=Decimal("1.00"))],
    )
    university_bank_name = StringField(
        "University Bank Name",
        validators=[Optional(), Length(max=120)],
    )
    account_holder_name = StringField(
        "Account Holder Name",
        validators=[Optional(), Length(max=120)],
    )
    university_account_number = StringField(
        "University Bank Account Number / IBAN",
        validators=[Optional(), Length(max=64)],
    )
    disbursement_iban = StringField("Disbursement IBAN", validators=[Optional(), Length(max=34)])
    installment_months = IntegerField("Installment Duration (Months)", validators=[Optional(), NumberRange(min=1, max=60)])
    first_installment_date = DateField("First Installment Due Date", format="%Y-%m-%d", validators=[Optional()])
    expected_disbursement_date = DateField("Loan Disbursement Date", format="%Y-%m-%d", validators=[Optional()])
    repayment_deadline = DateField("Repayment Deadline", format="%Y-%m-%d", validators=[Optional()])
    remarks = TextAreaField("Comments", validators=[Optional(), Length(max=1000)])
    submit = SubmitField("Save Final Decision")

    def validate_disbursement_iban(self, field):
        if not field.data:
            return
        validate_iban_format(self, field)

    def validate(self, extra_validators=None):
        is_valid = super().validate(extra_validators=extra_validators)

        decision = self.decision.data
        comments = (self.remarks.data or "").strip()
        if decision == "reject" and len(comments) < 5:
            self.remarks.errors.append("Comments are mandatory (min 5 characters) when rejecting.")
            is_valid = False
        if decision == "approve":
            if not self.hod_cgpa_verified.data:
                self.hod_cgpa_verified.errors.append("Confirm the CGPA validation before approval.")
                is_valid = False
            if not self.hod_department_verified.data:
                self.hod_department_verified.errors.append("Confirm the department validation before approval.")
                is_valid = False
            if self.approved_amount.data is None:
                self.approved_amount.errors.append("Loan amount issued is required for approved applications.")
                is_valid = False
            if not (self.disbursement_iban.data or "").strip():
                self.disbursement_iban.errors.append("Disbursement IBAN is required for approved applications.")
                is_valid = False
            if not (self.university_bank_name.data or "").strip():
                self.university_bank_name.errors.append(ADMIN_BANKING_REQUIRED_MESSAGE)
                is_valid = False
            if not (self.account_holder_name.data or "").strip():
                self.account_holder_name.errors.append(ADMIN_BANKING_REQUIRED_MESSAGE)
                is_valid = False
            if not (self.university_account_number.data or "").strip():
                self.university_account_number.errors.append(ADMIN_BANKING_REQUIRED_MESSAGE)
                is_valid = False
        return is_valid


class FinanceDisbursementForm(FlaskForm):
    disbursement_status = SelectField(
        "Disbursement Status",
        choices=DISBURSEMENT_STATUS_CHOICES,
        validators=[DataRequired()],
    )
    remarks = TextAreaField("Finance Update", validators=[Optional(), Length(max=1000)])
    submit = SubmitField("Save Finance Update")


class InstallmentPaymentForm(FlaskForm):
    receipt_file = FileField(
        "Payment Receipt",
        validators=[
            FileRequired(),
            FileAllowed(["pdf", "jpg", "jpeg", "png"], "Only PDF, JPG, JPEG, and PNG files are allowed."),
        ],
    )
    submit = SubmitField("Submit Receipt")


class InstallmentVerificationForm(FlaskForm):
    decision = SelectField(
        "Verification Decision",
        choices=[("approve", "Approve Receipt"), ("reject", "Reject Receipt")],
        validators=[DataRequired()],
    )
    remarks = TextAreaField("Remarks", validators=[Optional(), Length(max=500)])
    submit = SubmitField("Save Verification")

    def validate(self, extra_validators=None):
        is_valid = super().validate(extra_validators=extra_validators)
        if self.decision.data == "reject" and len((self.remarks.data or "").strip()) < 5:
            self.remarks.errors.append("Add at least 5 characters when rejecting a receipt.")
            is_valid = False
        return is_valid


class AdminUserForm(FlaskForm):
    full_name = StringField("Full Name", validators=[DataRequired(), Length(max=120)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField("Password", validators=[Optional(), Length(min=8, max=64), validate_password_strength])
    role = SelectField(
        "Role",
        choices=[
            ("student", "Student"),
            ("hod", "HOD"),
            ("finance", "Finance Officer"),
            ("admin", "Admin"),
        ],
        validators=[DataRequired()],
    )
    roll_number = StringField("Roll Number", validators=[Optional(), Length(max=50)])
    father_name = StringField("Father Name", validators=[Optional(), Length(max=120)])
    phone_number = StringField("Phone Number", validators=[Optional(), Length(max=20)])
    cnic = StringField("CNIC", validators=[Optional(), Length(max=20)])
    department = SelectField("Department", choices=[("", "Select Department")], validators=[Optional(), validate_allowed_department])
    program_level = SelectField("Program", choices=PROGRAM_CHOICES, validators=[Optional()])
    semester = SelectField("Semester", choices=REGISTRATION_SEMESTER_CHOICES, validators=[Optional()])
    profile_photo = FileField(
        "Passport-size Photo",
        validators=[Optional(), FileAllowed(["jpg", "jpeg", "png"], "Only JPG and PNG files are allowed.")],
    )
    managed_department_ids = SelectMultipleField("Assigned Departments", coerce=int, choices=[], validators=[Optional()])
    is_active_account = BooleanField("Active Account", default=True)
    otp_verified = BooleanField("OTP Verified", default=True)
    submit = SubmitField("Save User")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.existing_profile_photo = False

    def validate(self, extra_validators=None):
        is_valid = super().validate(extra_validators=extra_validators)
        selected_role = self.role.data

        if self.roll_number.data:
            try:
                validate_roll_number_format(self, self.roll_number)
            except ValidationError as exc:
                self.roll_number.errors.append(str(exc))
                is_valid = False

        if self.phone_number.data:
            try:
                validate_phone_number_format(self, self.phone_number)
            except ValidationError as exc:
                self.phone_number.errors.append(str(exc))
                is_valid = False

        if self.cnic.data:
            try:
                validate_cnic_format(self, self.cnic)
            except ValidationError as exc:
                self.cnic.errors.append(str(exc))
                is_valid = False

        if selected_role == "student":
            if not (self.roll_number.data or "").strip():
                self.roll_number.errors.append("Roll number is required for student accounts.")
                is_valid = False
            if not (self.father_name.data or "").strip():
                self.father_name.errors.append("Father name is required for student accounts.")
                is_valid = False
            if not (self.phone_number.data or "").strip():
                self.phone_number.errors.append("Phone number is required for student accounts.")
                is_valid = False
            if not (self.cnic.data or "").strip():
                self.cnic.errors.append("CNIC is required for student accounts.")
                is_valid = False
            if not (self.department.data or "").strip():
                self.department.errors.append("Department is required for student accounts.")
                is_valid = False
            if not (self.program_level.data or "").strip():
                self.program_level.errors.append("Program is required for student accounts.")
                is_valid = False
            if not (self.semester.data or "").strip():
                self.semester.errors.append("Semester is required for student accounts.")
                is_valid = False
            else:
                semester_error = validate_program_semester(self.program_level.data, self.semester.data, application_mode=False)
                if semester_error:
                    self.semester.errors.append(semester_error)
                    is_valid = False
            if not self.profile_photo.data and not self.existing_profile_photo:
                self.profile_photo.errors.append("Passport-size photo is required for student accounts.")
                is_valid = False

        return is_valid


class StudentProfileForm(FlaskForm):
    profile_photo = FileField(
        "Passport-size Photo",
        validators=[Optional(), FileAllowed(["jpg", "jpeg", "png"], "Only JPG and PNG files are allowed.")],
    )
    submit = SubmitField("Save Profile Photo")
