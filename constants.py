DEPARTMENT_CATALOG = [
    (
        "Life Sciences",
        [
            "Zoology",
            "Botany",
        ],
    ),
    (
        "Computer & IT",
        [
            "Information Technology",
            "Computer Science",
        ],
    ),
    (
        "Natural Sciences",
        [
            "Physics",
            "Chemistry",
            "Mathematics",
        ],
    ),
    (
        "Business & Management",
        [
            "Business Administration",
            "Economics",
        ],
    ),
    (
        "Education",
        [
            "Education",
        ],
    ),
    (
        "Languages & Humanities",
        [
            "English",
            "Urdu",
        ],
    ),
]

DEPARTMENT_ROWS = [
    {"category": category, "name": department_name}
    for category, department_names in DEPARTMENT_CATALOG
    for department_name in department_names
]

DEPARTMENT_NAMES = [row["name"] for row in DEPARTMENT_ROWS]

PROGRAM_CHOICES = [
    ("BS", "BS"),
    ("MS", "MS / Masters"),
]

ACCOUNT_HOLDER_RELATION_CHOICES = [
    ("Self", "Self"),
    ("Father", "Father"),
    ("Mother", "Mother"),
    ("Guardian", "Guardian"),
]

MINIMUM_CGPA = 3.0

REGISTRATION_SEMESTER_CHOICES = [(str(number), f"Semester {number}") for number in range(1, 9)]
BS_ELIGIBLE_SEMESTER_CHOICES = [(str(number), f"Semester {number}") for number in range(1, 9)]
MS_ELIGIBLE_SEMESTER_CHOICES = [(str(number), f"Semester {number}") for number in range(1, 4)]

REQUIRED_DOCUMENTS = [
    "CNIC",
    "Student Card",
    "Fee Voucher",
    "Father CNIC",
    "Academic Transcript",
]

DOCUMENT_FIELD_MAP = {
    "cnic_document": "CNIC",
    "student_card_document": "Student Card",
    "fee_voucher_document": "Fee Voucher",
    "father_cnic_document": "Father CNIC",
    "academic_transcript_document": "Academic Transcript",
}

APPLICATION_FIELD_LABELS = {
    "student_name": "Student Name",
    "roll_number": "Roll Number",
    "father_name": "Father Name",
    "phone_number": "Phone Number",
    "cnic": "CNIC",
    "cgpa": "CGPA",
    "department": "Department",
    "program_level": "Program",
    "semester": "Semester",
    "bank_name": "Bank Name",
    "iban": "IBAN",
    "account_holder_relation": "Account Holder Relation",
    "student_iban": "IBAN Number",
    "account_holder_name": "Account Holder Name",
    "relation_to_student": "Relation to Student",
    "loan_amount_requested": "Loan Amount Requested",
    "family_income": "Family Income",
    "reason_for_loan": "Reason for Loan",
}

ROLL_NUMBER_PATTERN = r"^[A-Za-z]{3}\d{7}$"
PHONE_NUMBER_PATTERN = r"^(?:\+92|0)3\d{9}$"
IBAN_PATTERN = r"^[A-Z]{2}[0-9A-Z]{13,32}$"
PASSWORD_PATTERN = r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{8,64}$"

DISBURSEMENT_STATUS_CHOICES = [
    ("Eligible", "Eligible for Disbursement"),
    ("Sent", "Sent to Student"),
    ("Received", "Received by Student"),
]

INSTALLMENT_STATUS_CHOICES = [
    ("pending", "Pending"),
    ("due", "Due"),
    ("overdue", "Overdue"),
    ("pending_verification", "Pending Finance Verification"),
    ("paid", "Paid"),
]

DEFAULT_HOD_PASSWORD = "HOD@123"
