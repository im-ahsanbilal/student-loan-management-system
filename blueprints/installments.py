from datetime import datetime
import os

from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user

from extensions import db
from forms import InstallmentPaymentForm, InstallmentVerificationForm
from helpers import create_notification, enforce_application_access, log_verification, resolve_managed_upload_path, role_required
from models import Installment, User
from services import (
    ADMIN_INSTALLMENT_CONFIRMATION_STAGE,
    clear_installment_receipt,
    installment_admin_confirmation_log,
    installment_can_pay,
    save_installment_receipt,
    sync_installment_statuses,
)


installments_bp = Blueprint("installments", __name__)


def _notify_active_admins(title, message, application_id):
    for admin_user in User.query.filter_by(role="admin", is_active_account=True).all():
        create_notification(admin_user.id, title, message, application_id)


def _notify_active_finance_users(title, message, application_id):
    for finance_user in User.query.filter_by(role="finance", is_active_account=True).all():
        create_notification(finance_user.id, title, message, application_id)


@installments_bp.route("/installments/<int:installment_id>/pay", methods=["GET"])
@role_required("student")
def pay_installment_page(installment_id):
    installment = Installment.query.get_or_404(installment_id)
    if installment.application.student_id != current_user.id:
        return render_template("403.html"), 403

    sync_installment_statuses([installment], commit=True)
    if not installment_can_pay(installment):
        flash("This installment is not available for payment right now.", "warning")
        return redirect(url_for("view_application", application_id=installment.application_id))

    form = InstallmentPaymentForm()
    return render_template("installment_payment.html", installment=installment, form=form)


@installments_bp.route("/pay_installment/<int:installment_id>", methods=["POST"])
@role_required("student")
def pay_installment(installment_id):
    installment = Installment.query.get_or_404(installment_id)
    if installment.application.student_id != current_user.id:
        return render_template("403.html"), 403

    sync_installment_statuses([installment], commit=True)
    if not installment_can_pay(installment):
        flash("This installment cannot accept a new receipt right now.", "warning")
        return redirect(url_for("view_application", application_id=installment.application_id))

    form = InstallmentPaymentForm()
    if not form.validate_on_submit():
        return render_template("installment_payment.html", installment=installment, form=form)

    try:
        save_installment_receipt(form.receipt_file.data, installment)
    except ValueError as exc:
        form.receipt_file.errors.append(str(exc))
        return render_template("installment_payment.html", installment=installment, form=form)

    create_notification(
        current_user.id,
        "Installment receipt submitted",
        f"Receipt submitted for installment due on {installment.due_date.strftime('%d %b %Y')}. It is now awaiting finance verification.",
        installment.application_id,
    )
    _notify_active_finance_users(
        "Installment payment verification request",
        f"{installment.application.loan_id} has a receipt uploaded by {installment.application.student_name} for the installment due on {installment.due_date.strftime('%d %b %Y')}.",
        installment.application_id,
    )
    log_verification(
        installment.application_id,
        current_user.id,
        "Installment Payment",
        "Receipt Submitted",
        f"Installment #{installment.id} receipt uploaded.",
    )
    db.session.commit()
    flash("Receipt uploaded successfully. Finance verification is pending.", "success")
    return redirect(url_for("view_application", application_id=installment.application_id))


@installments_bp.route("/finance/installments/<int:installment_id>/verify", methods=["GET", "POST"])
@role_required("finance")
def verify_installment(installment_id):
    installment = Installment.query.get_or_404(installment_id)
    enforce_application_access(installment.application)
    sync_installment_statuses([installment], commit=True)

    if installment.status != "pending_verification":
        flash("This installment does not have a receipt waiting for verification.", "warning")
        return redirect(url_for("view_application", application_id=installment.application_id))

    form = InstallmentVerificationForm()
    if form.validate_on_submit():
        remarks = (form.remarks.data or "").strip() or None
        if form.decision.data == "approve":
            installment.status = "paid"
            installment.verified_by = current_user.id
            installment.verified_at = datetime.utcnow()
            installment.paid_date = installment.paid_date or datetime.utcnow()
            create_notification(
                installment.application.student_id,
                "Installment verified",
                f"Your installment due on {installment.due_date.strftime('%d %b %Y')} has been marked as paid.",
                installment.application_id,
            )
            _notify_active_admins(
                "Installment payment verified",
                f"Finance verified {installment.application.loan_id} installment due on {installment.due_date.strftime('%d %b %Y')} for {installment.application.student_name}.",
                installment.application_id,
            )
            action = "Verified"
        else:
            clear_installment_receipt(installment)
            create_notification(
                installment.application.student_id,
                "Installment receipt rejected",
                f"Receipt verification failed for the installment due on {installment.due_date.strftime('%d %b %Y')}. {remarks or 'Please upload a clearer receipt.'}",
                installment.application_id,
            )
            _notify_active_admins(
                "Installment payment rejected",
                f"Finance rejected {installment.application.loan_id} installment receipt for {installment.application.student_name}. {remarks or 'A clearer receipt is required.'}",
                installment.application_id,
            )
            action = "Rejected"

        log_verification(
            installment.application_id,
            current_user.id,
            "Installment Verification",
            action,
            remarks or f"Installment #{installment.id}",
        )
        db.session.commit()
        flash("Finance installment verification saved successfully.", "success")
        return redirect(url_for("view_application", application_id=installment.application_id))

    return render_template("installment_verification.html", installment=installment, form=form)


@installments_bp.route("/admin/installments/<int:installment_id>/confirm", methods=["POST"])
@role_required("admin")
def confirm_installment_record(installment_id):
    installment = Installment.query.get_or_404(installment_id)
    enforce_application_access(installment.application)
    sync_installment_statuses([installment], commit=True)

    if installment.status != "paid" or not installment.verified_at:
        flash("Only finance-verified installment payments can be confirmed by admin.", "warning")
        return redirect(url_for("view_application", application_id=installment.application_id))

    if installment_admin_confirmation_log(installment):
        flash("This installment record has already been confirmed by admin.", "info")
        return redirect(url_for("view_application", application_id=installment.application_id))

    remarks = (request.form.get("remarks") or "").strip()
    detail = remarks or "Admin confirmed the finance-verified payment record."
    log_verification(
        installment.application_id,
        current_user.id,
        ADMIN_INSTALLMENT_CONFIRMATION_STAGE,
        "Confirmed",
        f"Installment #{installment.id}: {detail}",
    )
    create_notification(
        installment.application.student_id,
        "Installment record confirmed",
        f"Admin confirmed the finance-verified installment due on {installment.due_date.strftime('%d %b %Y')}.",
        installment.application_id,
    )
    _notify_active_finance_users(
        "Installment record confirmed by admin",
        f"Admin confirmed {installment.application.loan_id} installment due on {installment.due_date.strftime('%d %b %Y')} after finance verification.",
        installment.application_id,
    )
    db.session.commit()
    flash("Installment payment record confirmed and logged successfully.", "success")
    return redirect(url_for("view_application", application_id=installment.application_id))


@installments_bp.route("/installments/<int:installment_id>/receipt", methods=["GET"])
@role_required("student", "hod", "finance", "admin")
def installment_receipt(installment_id):
    installment = Installment.query.get_or_404(installment_id)
    enforce_application_access(installment.application)

    safe_receipt_path = resolve_managed_upload_path(installment.receipt_file)
    if not safe_receipt_path:
        flash("The requested receipt file is not available.", "danger")
        return redirect(url_for("view_application", application_id=installment.application_id))

    download_requested = request.args.get("download", type=int) == 1
    extension = os.path.splitext(safe_receipt_path)[1]
    return send_file(
        safe_receipt_path,
        as_attachment=download_requested,
        download_name=f"{installment.application.loan_id}-installment-{installment.id}{extension}",
        conditional=True,
    )
