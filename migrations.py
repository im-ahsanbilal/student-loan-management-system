from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

from directory_service import prune_departments_to_catalog, seed_department_directory
from extensions import db
from models import Document, Installment, LoanApplication, User


MIGRATION_NAMES = [
    "001_profile_and_workflow_extensions",
    "002_department_directory_bootstrap",
    "003_profile_photo_iban_and_review_controls",
    "004_review_validation_and_disbursement_tracking",
    "005_ai_scoring_and_installments",
    "006_application_bank_details_fields",
    "007_university_banking_details",
]


def _migration_exists(name):
    row = db.session.execute(
        text("SELECT name FROM schema_migrations WHERE name = :name"),
        {"name": name},
    ).first()
    return row is not None


def _create_migration_table():
    db.session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name VARCHAR(100) PRIMARY KEY,
                applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    db.session.commit()


def _has_column(table_name, column_name):
    inspector = inspect(db.engine)
    if table_name not in inspector.get_table_names():
        return False
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def _add_column_if_missing(table_name, column_name, ddl):
    if _has_column(table_name, column_name):
        return
    try:
        db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {ddl}"))
        db.session.commit()
    except OperationalError as exc:
        db.session.rollback()
        error_text = str(exc).lower()
        if "duplicate column" in error_text:
            return
        raise


def _apply_profile_and_workflow_extensions():
    _add_column_if_missing("users", "phone_number", "phone_number VARCHAR(20) NULL")
    _add_column_if_missing("users", "program_level", "program_level VARCHAR(10) NULL DEFAULT 'BS'")
    _add_column_if_missing("users", "is_system_generated", "is_system_generated BOOLEAN NOT NULL DEFAULT 0")
    _add_column_if_missing("loan_applications", "phone_number", "phone_number VARCHAR(20) NULL")
    _add_column_if_missing("loan_applications", "program_level", "program_level VARCHAR(10) NULL DEFAULT 'BS'")
    _add_column_if_missing("loan_applications", "student_iban", "student_iban VARCHAR(34) NULL")
    _add_column_if_missing("loan_applications", "repayment_deadline", "repayment_deadline DATE NULL")

    for user in User.query.filter(User.program_level.is_(None)).all():
        user.program_level = "BS"
    for application in LoanApplication.query.all():
        if not application.program_level:
            application.program_level = application.student.program_level if application.student and application.student.program_level else "BS"
        if not application.phone_number and application.student and application.student.phone_number:
            application.phone_number = application.student.phone_number
        if not application.student_iban and application.disbursement_iban:
            application.student_iban = application.disbursement_iban
    db.session.commit()


def _apply_department_directory_bootstrap():
    seed_department_directory()
    db.session.commit()


def _apply_profile_photo_iban_and_review_controls():
    _add_column_if_missing("users", "profile_photo_path", "profile_photo_path VARCHAR(255) NULL")
    _add_column_if_missing("users", "profile_photo_original_name", "profile_photo_original_name VARCHAR(255) NULL")
    _add_column_if_missing("loan_applications", "account_holder_name", "account_holder_name VARCHAR(120) NULL")
    _add_column_if_missing("loan_applications", "relation_to_student", "relation_to_student VARCHAR(120) NULL")
    _add_column_if_missing("loan_applications", "field_corrections_json", "field_corrections_json TEXT NULL")
    _add_column_if_missing("documents", "review_status", "review_status VARCHAR(20) NOT NULL DEFAULT 'Accepted'")
    _add_column_if_missing("documents", "review_remarks", "review_remarks TEXT NULL")
    _add_column_if_missing("documents", "reviewed_at", "reviewed_at DATETIME NULL")
    _add_column_if_missing("documents", "reviewed_by_id", "reviewed_by_id INTEGER NULL")

    for application in LoanApplication.query.all():
        if application.account_holder_name == "":
            application.account_holder_name = None
        if not application.relation_to_student:
            application.relation_to_student = "Self"
        if application.field_corrections_json == "":
            application.field_corrections_json = None

    for document in Document.query.all():
        if not document.review_status:
            document.review_status = "Accepted"

    prune_departments_to_catalog()
    db.session.commit()


def _apply_review_validation_and_disbursement_tracking():
    _add_column_if_missing("loan_applications", "cgpa", "cgpa NUMERIC(4,2) NULL")
    _add_column_if_missing(
        "loan_applications",
        "hod_cgpa_verified",
        "hod_cgpa_verified BOOLEAN NOT NULL DEFAULT 0",
    )
    _add_column_if_missing(
        "loan_applications",
        "hod_department_verified",
        "hod_department_verified BOOLEAN NOT NULL DEFAULT 0",
    )
    _add_column_if_missing(
        "loan_applications",
        "finance_fee_defaulter",
        "finance_fee_defaulter BOOLEAN NULL",
    )
    _add_column_if_missing(
        "loan_applications",
        "finance_scholarship_availing",
        "finance_scholarship_availing BOOLEAN NULL",
    )
    _add_column_if_missing(
        "loan_applications",
        "disbursement_sent_at",
        "disbursement_sent_at DATETIME NULL",
    )
    _add_column_if_missing(
        "loan_applications",
        "disbursement_received_at",
        "disbursement_received_at DATETIME NULL",
    )

    for application in LoanApplication.query.all():
        if application.finance_scholarship_availing is None:
            scholarship_status = (application.scholarship_status or "").strip().lower()
            if scholarship_status == "receiving":
                application.finance_scholarship_availing = True
            elif scholarship_status in {"not receiving", "not checked"}:
                application.finance_scholarship_availing = False
        if application.disbursement_status == "Scheduled":
            application.disbursement_status = "Eligible"

    db.session.commit()


def _apply_ai_scoring_and_installments():
    _add_column_if_missing("loan_applications", "ai_score", "ai_score INTEGER NULL")
    _add_column_if_missing(
        "loan_applications",
        "ai_recommendation",
        "ai_recommendation VARCHAR(20) NULL",
    )
    _add_column_if_missing(
        "loan_applications",
        "ai_explanation",
        "ai_explanation TEXT NULL",
    )
    Installment.__table__.create(bind=db.engine, checkfirst=True)
    db.session.commit()


def _apply_application_bank_details_fields():
    _add_column_if_missing("loan_applications", "bank_name", "bank_name VARCHAR(120) NULL")
    _add_column_if_missing("loan_applications", "iban", "iban VARCHAR(34) NULL")
    _add_column_if_missing(
        "loan_applications",
        "account_holder_relation",
        "account_holder_relation VARCHAR(20) NULL",
    )

    for application in LoanApplication.query.all():
        if not application.iban and application.student_iban:
            application.iban = application.student_iban
        if not application.account_holder_relation:
            application.account_holder_relation = application.relation_to_student or "Self"

    db.session.commit()


def _apply_university_banking_details():
    _add_column_if_missing("loan_applications", "university_bank_name", "university_bank_name VARCHAR(120) NULL")
    _add_column_if_missing("loan_applications", "university_account_number", "university_account_number VARCHAR(64) NULL")
    db.session.commit()


def run_migrations():
    _create_migration_table()

    if not _migration_exists(MIGRATION_NAMES[0]):
        _apply_profile_and_workflow_extensions()
        db.session.execute(
            text("INSERT INTO schema_migrations (name) VALUES (:name)"),
            {"name": MIGRATION_NAMES[0]},
        )
        db.session.commit()

    if not _migration_exists(MIGRATION_NAMES[2]):
        _apply_profile_photo_iban_and_review_controls()
        db.session.execute(
            text("INSERT INTO schema_migrations (name) VALUES (:name)"),
            {"name": MIGRATION_NAMES[2]},
        )
        db.session.commit()

    if not _migration_exists(MIGRATION_NAMES[1]):
        _apply_department_directory_bootstrap()
        db.session.execute(
            text("INSERT INTO schema_migrations (name) VALUES (:name)"),
            {"name": MIGRATION_NAMES[1]},
        )
        db.session.commit()
    else:
        seed_department_directory()
        db.session.commit()

    if not _migration_exists(MIGRATION_NAMES[3]):
        _apply_review_validation_and_disbursement_tracking()
        db.session.execute(
            text("INSERT INTO schema_migrations (name) VALUES (:name)"),
            {"name": MIGRATION_NAMES[3]},
        )
        db.session.commit()

    if not _migration_exists(MIGRATION_NAMES[4]):
        _apply_ai_scoring_and_installments()
        db.session.execute(
            text("INSERT INTO schema_migrations (name) VALUES (:name)"),
            {"name": MIGRATION_NAMES[4]},
        )
        db.session.commit()

    if not _migration_exists(MIGRATION_NAMES[5]):
        _apply_application_bank_details_fields()
        db.session.execute(
            text("INSERT INTO schema_migrations (name) VALUES (:name)"),
            {"name": MIGRATION_NAMES[5]},
        )
        db.session.commit()

    if not _migration_exists(MIGRATION_NAMES[6]):
        _apply_university_banking_details()
        db.session.execute(
            text("INSERT INTO schema_migrations (name) VALUES (:name)"),
            {"name": MIGRATION_NAMES[6]},
        )
        db.session.commit()
