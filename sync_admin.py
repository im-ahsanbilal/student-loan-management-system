import os
from app import app, db
from models import User

def sync_admin():
    with app.app_context():
        email = os.getenv("ADMIN_EMAIL")
        password = os.getenv("ADMIN_PASSWORD")

        admin = User.query.filter_by(role="admin").first()

        if not admin:
            admin = User(
                full_name="Admin",
                email=email,
                role="admin",
                is_active_account=True,
                otp_verified=True
            )
            admin.set_password(password)
            db.session.add(admin)
        else:
            admin.email = email
            admin.set_password(password)

        db.session.commit()
        print("Admin synced successfully")

if __name__ == "__main__":
    sync_admin()