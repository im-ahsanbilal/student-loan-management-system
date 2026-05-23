import re

from flask import current_app

from constants import DEFAULT_HOD_PASSWORD, DEPARTMENT_NAMES, DEPARTMENT_ROWS
from extensions import db
from models import Department, User


def slugify_department_name(name):
    return re.sub(r"[^a-z0-9]+", ".", (name or "").strip().lower()).strip(".")


def grouped_departments():
    groups = []
    grouped = {}
    for department in Department.query.filter(Department.name.in_(DEPARTMENT_NAMES)).order_by(Department.category.asc(), Department.name.asc()).all():
        grouped.setdefault(department.category, []).append(department)
    for category, departments in grouped.items():
        groups.append({"category": category, "departments": departments})
    return groups


def department_choices(include_blank=False):
    choices = [
        (department.name, department.name)
        for department in Department.query.filter(Department.name.in_(DEPARTMENT_NAMES)).order_by(Department.name.asc()).all()
    ]
    if include_blank:
        return [("", "Select Department")] + choices
    return choices


def is_allowed_department_name(name):
    return (name or "").strip() in set(DEPARTMENT_NAMES)


def get_department_record(name):
    normalized_name = (name or "").strip()
    if not normalized_name or not is_allowed_department_name(normalized_name):
        return None
    return Department.query.filter_by(name=normalized_name).first()


def managed_department_names(user):
    if not user or user.role != "hod":
        return []
    return [
        department.name
        for department in Department.query.filter(
            Department.hod_id == user.id,
            Department.name.in_(DEPARTMENT_NAMES),
        )
        .order_by(Department.name.asc())
        .all()
    ]


def department_has_active_hod(name):
    department = get_department_record(name)
    if not department or not department.hod:
        return False
    return department.hod.role == "hod" and department.hod.is_active_account


def _default_hod_email_for_department(name, sequence=1):
    slug = slugify_department_name(name)
    if sequence <= 1:
        return f"hod.{slug}@studentloan.local"
    return f"hod.{slug}{sequence}@studentloan.local"


def ensure_default_hod_for_department(department, excluded_user_ids=None):
    excluded_user_ids = set(excluded_user_ids or [])
    if department.hod and department.hod.id not in excluded_user_ids and department.hod.role == "hod":
        return department.hod

    legacy_query = User.query.filter_by(role="hod", department=department.name)
    if excluded_user_ids:
        legacy_query = legacy_query.filter(User.id.notin_(excluded_user_ids))
    legacy_hod = legacy_query.order_by(User.id.asc()).first()
    if legacy_hod:
        department.hod_id = legacy_hod.id
        return legacy_hod

    default_user = None
    sequence = 1
    while default_user is None:
        candidate_email = _default_hod_email_for_department(department.name, sequence=sequence)
        existing_user = User.query.filter_by(email=candidate_email).first()
        if existing_user and existing_user.id in excluded_user_ids:
            sequence += 1
            continue
        if existing_user and existing_user.role != "hod":
            sequence += 1
            continue
        if existing_user:
            default_user = existing_user
        else:
            default_user = User(
                full_name=f"{department.name} HOD",
                email=candidate_email,
                role="hod",
                otp_verified=True,
                is_active_account=True,
                is_system_generated=True,
            )
            default_user.set_password(current_app.config.get("DEFAULT_HOD_PASSWORD", DEFAULT_HOD_PASSWORD))
            db.session.add(default_user)
            db.session.flush()

    department.hod_id = default_user.id
    return default_user


def prune_departments_to_catalog():
    valid_department_names = set(DEPARTMENT_NAMES)
    removed_hod_ids = set()

    for department in Department.query.order_by(Department.name.asc()).all():
        if department.name in valid_department_names:
            continue
        if department.hod_id:
            removed_hod_ids.add(department.hod_id)
        db.session.delete(department)

    db.session.flush()

    for student in User.query.filter(User.department.isnot(None)).all():
        if student.department not in valid_department_names:
            student.department = None

    for hod_id in removed_hod_ids:
        hod_user = User.query.get(hod_id)
        if hod_user and hod_user.role == "hod" and hod_user.is_system_generated and not hod_user.managed_departments:
            db.session.delete(hod_user)

    db.session.flush()


def seed_department_directory():
    prune_departments_to_catalog()
    existing_departments = {department.name: department for department in Department.query.all()}

    for row in DEPARTMENT_ROWS:
        department = existing_departments.get(row["name"])
        if department is None:
            department = Department(name=row["name"], category=row["category"])
            db.session.add(department)
            db.session.flush()
            existing_departments[row["name"]] = department
        elif department.category != row["category"]:
            department.category = row["category"]

        ensure_default_hod_for_department(department)

    db.session.flush()


def ensure_department_directory_integrity(excluded_user_ids=None):
    excluded_user_ids = set(excluded_user_ids or [])
    prune_departments_to_catalog()
    for department in Department.query.filter(Department.name.in_(DEPARTMENT_NAMES)).order_by(Department.name.asc()).all():
        if department.hod and department.hod.id not in excluded_user_ids and department.hod.role == "hod" and department.hod.is_active_account:
            continue
        ensure_default_hod_for_department(department, excluded_user_ids=excluded_user_ids)
    db.session.flush()


def sync_hod_departments(hod_user, selected_department_ids, excluded_user_ids=None):
    if not hod_user:
        return

    selected_department_ids = {int(department_id) for department_id in (selected_department_ids or [])}
    excluded_user_ids = set(excluded_user_ids or [])
    current_departments = Department.query.filter_by(hod_id=hod_user.id).all()

    for department in current_departments:
        if department.id not in selected_department_ids:
            department.hod_id = None

    if selected_department_ids:
        departments = Department.query.filter(
            Department.id.in_(selected_department_ids),
            Department.name.in_(DEPARTMENT_NAMES),
        ).all()
        for department in departments:
            department.hod_id = hod_user.id

    db.session.flush()
    integrity_exclusions = set(excluded_user_ids)
    if hod_user.role != "hod":
        integrity_exclusions.add(hod_user.id)
    ensure_department_directory_integrity(excluded_user_ids=integrity_exclusions or None)
