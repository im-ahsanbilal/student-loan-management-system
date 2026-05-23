CREATE DATABASE IF NOT EXISTS student_loan_management CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE student_loan_management;

CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    full_name VARCHAR(120) NOT NULL,
    email VARCHAR(120) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    roll_number VARCHAR(50) NULL UNIQUE,
    father_name VARCHAR(120) NULL,
    phone_number VARCHAR(20) NULL,
    cnic VARCHAR(20) NULL UNIQUE,
    department VARCHAR(100) NULL,
    program_level VARCHAR(10) NULL DEFAULT 'BS',
    semester VARCHAR(20) NULL,
    role ENUM('student', 'hod', 'finance', 'admin') NOT NULL DEFAULT 'student',
    otp_verified TINYINT(1) NOT NULL DEFAULT 0,
    registration_otp VARCHAR(6) NULL,
    registration_otp_expiry DATETIME NULL,
    reset_otp VARCHAR(6) NULL,
    reset_otp_expiry DATETIME NULL,
    is_active_account TINYINT(1) NOT NULL DEFAULT 1,
    is_system_generated TINYINT(1) NOT NULL DEFAULT 0,
    profile_photo_path VARCHAR(255) NULL,
    profile_photo_original_name VARCHAR(255) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_users_role (role),
    INDEX idx_users_department (department)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS departments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    category VARCHAR(100) NOT NULL,
    hod_id INT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_departments_hod FOREIGN KEY (hod_id) REFERENCES users(id) ON DELETE SET NULL,
    INDEX idx_departments_category (category)
) ENGINE=InnoDB;

INSERT INTO departments (name, category)
VALUES
    ('Zoology', 'Life Sciences'),
    ('Botany', 'Life Sciences'),
    ('Information Technology', 'Computer & IT'),
    ('Computer Science', 'Computer & IT'),
    ('Physics', 'Natural Sciences'),
    ('Chemistry', 'Natural Sciences'),
    ('Mathematics', 'Natural Sciences'),
    ('Business Administration', 'Business & Management'),
    ('Economics', 'Business & Management'),
    ('Education', 'Education'),
    ('English', 'Languages & Humanities'),
    ('Urdu', 'Languages & Humanities')
ON DUPLICATE KEY UPDATE category = VALUES(category);

CREATE TABLE IF NOT EXISTS loan_applications (
    id INT AUTO_INCREMENT PRIMARY KEY,
    loan_id VARCHAR(30) NOT NULL UNIQUE,
    student_id INT NOT NULL,
    student_name VARCHAR(120) NOT NULL,
    roll_number VARCHAR(50) NOT NULL,
    father_name VARCHAR(120) NOT NULL,
    phone_number VARCHAR(20) NULL,
    cnic VARCHAR(20) NOT NULL,
    cgpa DECIMAL(4,2) NULL,
    department VARCHAR(100) NOT NULL,
    program_level VARCHAR(10) NULL DEFAULT 'BS',
    semester VARCHAR(20) NOT NULL,
    loan_amount_requested DECIMAL(12,2) NOT NULL,
    family_income DECIMAL(12,2) NOT NULL,
    reason_for_loan TEXT NOT NULL,
    bank_name VARCHAR(120) NULL,
    iban VARCHAR(34) NULL,
    account_holder_relation VARCHAR(20) NULL,
    student_iban VARCHAR(34) NULL,
    account_holder_name VARCHAR(120) NULL,
    relation_to_student VARCHAR(120) NULL,
    field_corrections_json TEXT NULL,
    ai_score INT NULL,
    ai_recommendation VARCHAR(20) NULL,
    ai_explanation TEXT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'Pending',
    current_stage VARCHAR(50) NOT NULL DEFAULT 'Document Submission',
    hod_status VARCHAR(20) NOT NULL DEFAULT 'Pending',
    finance_status VARCHAR(20) NOT NULL DEFAULT 'Pending',
    admin_status VARCHAR(20) NOT NULL DEFAULT 'Pending',
    scholarship_status VARCHAR(30) NOT NULL DEFAULT 'Not Checked',
    hod_cgpa_verified TINYINT(1) NOT NULL DEFAULT 0,
    hod_department_verified TINYINT(1) NOT NULL DEFAULT 0,
    finance_fee_defaulter TINYINT(1) NULL,
    finance_scholarship_availing TINYINT(1) NULL,
    hod_comments TEXT NULL,
    finance_comments TEXT NULL,
    admin_comments TEXT NULL,
    rejected_by_stage VARCHAR(50) NULL,
    rejection_reason TEXT NULL,
    resubmission_count INT NOT NULL DEFAULT 0,
    last_resubmitted_at DATETIME NULL,
    loan_amount_issued DECIMAL(12,2) NULL,
    disbursement_iban VARCHAR(34) NULL,
    university_bank_name VARCHAR(120) NULL,
    university_account_number VARCHAR(64) NULL,
    expected_disbursement_date DATE NULL,
    repayment_deadline DATE NULL,
    disbursement_status VARCHAR(30) NOT NULL DEFAULT 'Pending',
    disbursement_sent_at DATETIME NULL,
    disbursement_received_at DATETIME NULL,
    hod_verified_at DATETIME NULL,
    finance_verified_at DATETIME NULL,
    admin_decided_at DATETIME NULL,
    submitted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_loan_student FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_loan_status (status),
    INDEX idx_loan_department (department),
    INDEX idx_loan_roll_number (roll_number),
    INDEX idx_loan_cnic (cnic)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS documents (
    id INT AUTO_INCREMENT PRIMARY KEY,
    application_id INT NOT NULL,
    document_type VARCHAR(50) NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    stored_filename VARCHAR(255) NOT NULL,
    file_path VARCHAR(255) NOT NULL,
    mime_type VARCHAR(100) NULL,
    review_status VARCHAR(20) NOT NULL DEFAULT 'Accepted',
    review_remarks TEXT NULL,
    reviewed_at DATETIME NULL,
    reviewed_by_id INT NULL,
    uploaded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_documents_application FOREIGN KEY (application_id) REFERENCES loan_applications(id) ON DELETE CASCADE,
    CONSTRAINT fk_documents_reviewer FOREIGN KEY (reviewed_by_id) REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT uq_documents_application_type UNIQUE (application_id, document_type)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS notifications (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    application_id INT NULL,
    title VARCHAR(150) NOT NULL,
    message TEXT NOT NULL,
    is_read TINYINT(1) NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_notifications_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_notifications_application FOREIGN KEY (application_id) REFERENCES loan_applications(id) ON DELETE CASCADE,
    INDEX idx_notifications_user_read (user_id, is_read)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS installments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    application_id INT NOT NULL,
    amount DECIMAL(12,2) NOT NULL,
    due_date DATE NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'pending',
    receipt_file VARCHAR(255) NULL,
    paid_date DATETIME NULL,
    verified_by INT NULL,
    verified_at DATETIME NULL,
    CONSTRAINT fk_installments_application FOREIGN KEY (application_id) REFERENCES loan_applications(id) ON DELETE CASCADE,
    CONSTRAINT fk_installments_verifier FOREIGN KEY (verified_by) REFERENCES users(id) ON DELETE SET NULL,
    INDEX idx_installments_application (application_id),
    INDEX idx_installments_due_date (due_date),
    INDEX idx_installments_status (status)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS verification_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    application_id INT NOT NULL,
    actor_id INT NOT NULL,
    stage VARCHAR(50) NOT NULL,
    action VARCHAR(50) NOT NULL,
    remarks TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_logs_application FOREIGN KEY (application_id) REFERENCES loan_applications(id) ON DELETE CASCADE,
    CONSTRAINT fk_logs_actor FOREIGN KEY (actor_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_logs_created_at (created_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS reports (
    id INT AUTO_INCREMENT PRIMARY KEY,
    generated_by INT NOT NULL,
    report_type VARCHAR(100) NOT NULL,
    file_format VARCHAR(10) NOT NULL,
    filters_json TEXT NULL,
    file_name VARCHAR(255) NOT NULL,
    generated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_reports_user FOREIGN KEY (generated_by) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_reports_generated_at (generated_at)
) ENGINE=InnoDB;

-- The application bootstraps default HOD users automatically on first run.
-- Each department receives a manageable HOD account if one does not already exist.
-- The default password for bootstrap HOD accounts is HOD@123 unless overridden in .env.

-- Manual staff account creation example for the first administrator:
-- Generate a password hash after creating the virtual environment:
-- python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('Admin@123'))"
--
-- Then insert the admin:
-- INSERT INTO users (full_name, email, password_hash, role, otp_verified, is_active_account)
-- VALUES ('System Admin', 'admin@university.edu', 'PASTE_HASH_HERE', 'admin', 1, 1);
