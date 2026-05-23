## 🔐 Demo Login Credentials

Use these accounts to test the system:

| Role    | Email                          | Password     |
|---------|-------------------------------|--------------|
| Admin   | admin@university.edu          | Admin@123    |
| HOD     | hod.information.technology@studentloan.local | HOD@123 |
| Finance | finance@university.edu        | Finance@123  |
| Student | Register a new account on the site |         |

## 🌐 Live Demo
https://imahsanbilal.pythonanywhere.com

## 💻 GitHub Code
https://github.com/im-ahsanbilal/student-loan-management-system
 
 
 # Web-Based Student Loan Management System

A complete Final Year Project built with Flask, MySQL, Bootstrap 5, Flask-Login, Flask-WTF, Flask-Mail, and ReportLab.

## Features

- Student registration with OTP email verification
- Login, logout, session management, and forgot-password OTP reset
- Student dashboard with profile, loan application, document upload, status tracking, and notifications
- HOD verification workflow for department validation
- Finance officer verification workflow for scholarship checking
- Admin dashboard for final decisions, application search, report generation, logs, and user management
- PDF download for each application
- PDF and CSV report downloads
- Secure password hashing, RBAC, CSRF protection, and secure file uploads

## Technology Stack

- Frontend: HTML5, CSS3, Bootstrap 5, JavaScript
- Backend: Python Flask
- Database: MySQL
- Libraries: Flask-Mail, Flask-Login, Flask-WTF, Werkzeug Security, ReportLab

## Project Structure

```text
student_loan_system/
|-- app.py
|-- config.py
|-- extensions.py
|-- forms.py
|-- helpers.py
|-- models.py
|-- requirements.txt
|-- database.sql
|-- .env.example
|-- README.md
|-- templates/
|   |-- base.html
|   |-- login.html
|   |-- register.html
|   |-- otp_verify.html
|   |-- forgot_password.html
|   |-- reset_password.html
|   |-- student_dashboard.html
|   |-- hod_dashboard.html
|   |-- finance_dashboard.html
|   |-- admin_dashboard.html
|   |-- apply_loan.html
|   |-- applications.html
|   |-- reports.html
|   |-- upload_documents.html
|   |-- review_application.html
|   |-- profile.html
|   |-- notifications.html
|   |-- users.html
|   |-- logs.html
|   |-- 403.html
|   |-- 404.html
|   |-- 500.html
|-- static/
|   |-- css/style.css
|   |-- js/main.js
|   |-- images/
|-- uploads/
```

## Setup Guide

### 1. Install Python

Install Python 3.11 or later from the official Python installer and make sure `python` and `pip` are available in your terminal.

### 2. Install MySQL

Install MySQL Server 8 or later and remember your root username and password.

### 3. Create the database and import the schema

Open MySQL and run:

```sql
SOURCE path/to/student_loan_system/database.sql;
```

Or from the terminal:

```bash
mysql -u root -p < database.sql
```

This creates the `student_loan_management` database and all required tables.

### 4. Create a virtual environment

Inside the project folder run:

```bash
python -m venv venv
```

Activate it:

Windows:

```bash
venv\Scripts\activate
```

macOS/Linux:

```bash
source venv/bin/activate
```

### 5. Install requirements

```bash
pip install -r requirements.txt
```

### 6. Configure environment variables

Copy `.env.example` to `.env` and update the values:

```bash
copy .env.example .env
```

Set these especially:

- `SECRET_KEY`
- `DATABASE_URL`
- `MAIL_USERNAME`
- `MAIL_PASSWORD`
- `MAIL_DEFAULT_SENDER`

For Gmail OTP delivery, use a Gmail App Password instead of your normal password.

### 7. Manually create staff accounts in the database

Admin accounts are not created through registration.

Generate a password hash:

```bash
python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('Admin@123'))"
```

Use the generated hash in MySQL:

```sql
INSERT INTO users (full_name, email, password_hash, department, role, otp_verified, is_active_account)
VALUES ('System Admin', 'admin@university.edu', 'PASTE_HASH_HERE', NULL, 'admin', 1, 1);

INSERT INTO users (full_name, email, password_hash, department, role, otp_verified, is_active_account)
VALUES ('Computer Science HOD', 'hod.cs@university.edu', 'PASTE_HASH_HERE', 'Computer Science', 'hod', 1, 1);

INSERT INTO users (full_name, email, password_hash, department, role, otp_verified, is_active_account)
VALUES ('Finance Officer', 'finance@university.edu', 'PASTE_HASH_HERE', NULL, 'finance', 1, 1);
```

### 8. Run the Flask server

```bash
flask run
```

Open the local URL shown in the terminal, usually `http://127.0.0.1:5000`.

## OTP Email Notes

- If valid SMTP settings are configured, OTP emails will be sent through Flask-Mail.
- If email is not configured locally, the application logs the OTP in the Flask terminal so the project can still be tested on a laptop.

## Default Workflow

1. Student registers and verifies email using OTP.
2. Student logs in and submits a loan application.
3. Student uploads all five required documents.
4. System moves the application to HOD verification.
5. HOD approves or rejects.
6. Finance officer approves or rejects.
7. Admin gives the final decision.
8. Students receive notifications and each role can download the application PDF.

## Required Upload Documents

- CNIC
- Student Card
- Fee Voucher
- Father CNIC
- Academic Transcript

Allowed formats: PDF, JPG, PNG

## Security Highlights

- Password hashing with Werkzeug
- Role-based route protection
- CSRF protection with Flask-WTF
- File type validation and secure filenames
- SQL injection protection through SQLAlchemy ORM

## Run Command

```bash
flask run
```
