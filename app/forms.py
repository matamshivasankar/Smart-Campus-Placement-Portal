"""WTForms definitions with server-side validation and CSRF protection."""
from __future__ import annotations

from datetime import date

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import (
    BooleanField,
    DateField,
    DecimalField,
    IntegerField,
    PasswordField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.fields.datetime import DateTimeLocalField
from wtforms.validators import (
    DataRequired,
    Email,
    EqualTo,
    Length,
    NumberRange,
    Optional,
    Regexp,
    ValidationError,
)

from .models import (
    APPLICATION_TRANSITIONS,
    INTERVIEW_MODES,
    INTERVIEW_RESULTS,
    INTERVIEW_STATUSES,
    USER_ROLES,
)

DEPARTMENT_CHOICES = [
    "Computer Science and Engineering",
    "Information Technology",
    "Electronics and Communication Engineering",
    "Electrical and Electronics Engineering",
    "Mechanical Engineering",
    "Civil Engineering",
    "Artificial Intelligence and Data Science",
    "Business Administration",
    "Other",
]


class LoginForm(FlaskForm):
    email = StringField("Email address", validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=6, max=128)])
    remember = BooleanField("Keep me signed in")
    submit = SubmitField("Log in")


class StudentRegistrationForm(FlaskForm):
    full_name = StringField("Full name", validators=[DataRequired(), Length(min=2, max=150)])
    email = StringField("Email address", validators=[DataRequired(), Email(), Length(max=255)])
    roll_number = StringField("Roll number", validators=[DataRequired(), Length(min=2, max=50)])
    department = SelectField("Department", choices=[(d, d) for d in DEPARTMENT_CHOICES],
                             validators=[DataRequired()])
    degree = StringField("Degree", validators=[DataRequired(), Length(min=2, max=120)])
    cgpa = DecimalField("Current CGPA", places=2, validators=[
        DataRequired(), NumberRange(min=0, max=10, message="CGPA must be between 0 and 10."),
    ])
    graduation_year = IntegerField("Graduation year", validators=[
        DataRequired(), NumberRange(min=1990, max=2100),
    ])
    phone = StringField("Phone number", validators=[
        Optional(), Regexp(r"^[0-9+\-\s()]{7,20}$", message="Enter a valid phone number."),
    ])
    skills = TextAreaField("Skills (comma separated)", validators=[DataRequired(), Length(max=1000)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8, max=128)])
    confirm_password = PasswordField("Confirm password", validators=[
        DataRequired(), EqualTo("password", message="Passwords must match."),
    ])
    submit = SubmitField("Create student account")

    def validate_graduation_year(self, field):
        if field.data and field.data < date.today().year - 12:
            raise ValidationError("Graduation year looks too far in the past.")


class RecruiterRegistrationForm(FlaskForm):
    full_name = StringField("Your name", validators=[DataRequired(), Length(min=2, max=150)])
    email = StringField("Work email", validators=[DataRequired(), Email(), Length(max=255)])
    designation = StringField("Designation", validators=[Optional(), Length(max=120)])
    phone = StringField("Phone number", validators=[
        Optional(), Regexp(r"^[0-9+\-\s()]{7,20}$", message="Enter a valid phone number."),
    ])
    company_name = StringField("Company name", validators=[DataRequired(), Length(min=2, max=200)])
    company_website = StringField("Company website", validators=[
        Optional(), Length(max=255),
        Regexp(r"^https?://[\w\-\.]+\..+$", message="Website must start with http:// or https://"),
    ])
    company_location = StringField("Company location", validators=[Optional(), Length(max=150)])
    company_industry = StringField("Industry", validators=[Optional(), Length(max=120)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8, max=128)])
    confirm_password = PasswordField("Confirm password", validators=[
        DataRequired(), EqualTo("password", message="Passwords must match."),
    ])
    submit = SubmitField("Register recruiter account")


class StudentProfileForm(FlaskForm):
    full_name = StringField("Full name", validators=[DataRequired(), Length(min=2, max=150)])
    roll_number = StringField("Roll number", validators=[DataRequired(), Length(min=2, max=50)])
    department = SelectField("Department", choices=[(d, d) for d in DEPARTMENT_CHOICES],
                             validators=[DataRequired()])
    degree = StringField("Degree", validators=[DataRequired(), Length(min=2, max=120)])
    cgpa = DecimalField("Current CGPA", places=2, validators=[
        DataRequired(), NumberRange(min=0, max=10, message="CGPA must be between 0 and 10."),
    ])
    graduation_year = IntegerField("Graduation year", validators=[
        DataRequired(), NumberRange(min=1990, max=2100),
    ])
    phone = StringField("Phone number", validators=[
        Optional(), Regexp(r"^[0-9+\-\s()]{7,20}$", message="Enter a valid phone number."),
    ])
    active_backlogs = IntegerField("Active backlogs", validators=[
        Optional(), NumberRange(min=0, max=30, message="Backlogs must be between 0 and 30."),
    ])
    skills = TextAreaField("Skills (comma separated)", validators=[DataRequired(), Length(max=1000)])
    about = TextAreaField("About you", validators=[Optional(), Length(max=2000)])
    linkedin_url = StringField("LinkedIn profile", validators=[
        Optional(), Length(max=255),
        Regexp(r"^https?://[\w\-\.]+\..+$", message="LinkedIn URL must start with http:// or https://"),
    ])
    github_url = StringField("GitHub profile", validators=[
        Optional(), Length(max=255),
        Regexp(r"^https?://[\w\-\.]+\..+$", message="GitHub URL must start with http:// or https://"),
    ])
    submit = SubmitField("Save profile")


class ResumeUploadForm(FlaskForm):
    resume = FileField("Resume file", validators=[
        FileRequired(message="Choose a file to upload."),
        FileAllowed(["pdf", "doc", "docx"], "Only PDF, DOC and DOCX files are allowed."),
    ])
    submit = SubmitField("Upload resume")


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("Current password", validators=[DataRequired()])
    new_password = PasswordField("New password", validators=[DataRequired(), Length(min=8, max=128)])
    confirm_password = PasswordField("Confirm new password", validators=[
        DataRequired(), EqualTo("new_password", message="Passwords must match."),
    ])
    submit = SubmitField("Update password")


class CompanyForm(FlaskForm):
    name = StringField("Company name", validators=[DataRequired(), Length(min=2, max=200)])
    website = StringField("Website", validators=[
        Optional(), Length(max=255),
        Regexp(r"^https?://[\w\-\.]+\..+$", message="Website must start with http:// or https://"),
    ])
    industry = StringField("Industry", validators=[Optional(), Length(max=120)])
    location = StringField("Headquarters", validators=[Optional(), Length(max=150)])
    description = TextAreaField("About the company", validators=[Optional(), Length(max=4000)])
    submit = SubmitField("Save company profile")


class JobForm(FlaskForm):
    title = StringField("Job title", validators=[DataRequired(), Length(min=3, max=200)])
    description = TextAreaField("Job description", validators=[DataRequired(), Length(max=8000)])
    responsibilities = TextAreaField("Responsibilities", validators=[Optional(), Length(max=8000)])
    location = StringField("Location", validators=[DataRequired(), Length(max=150)])
    employment_type = SelectField("Employment type", choices=[
        ("Full time", "Full time"), ("Internship", "Internship"),
        ("Internship + Full time", "Internship + Full time"), ("Part time", "Part time"),
    ], validators=[DataRequired()])
    openings = IntegerField("Number of openings", validators=[
        DataRequired(), NumberRange(min=1, max=500),
    ])
    currency = SelectField("Currency", choices=[("INR", "INR"), ("USD", "USD"), ("EUR", "EUR")],
                           validators=[DataRequired()])
    salary_min = DecimalField("Salary range (from)", places=2, validators=[Optional(), NumberRange(min=0)])
    salary_max = DecimalField("Salary range (to)", places=2, validators=[Optional(), NumberRange(min=0)])
    min_cgpa = DecimalField("Minimum CGPA", places=2, validators=[
        Optional(), NumberRange(min=0, max=10, message="Minimum CGPA must be between 0 and 10."),
    ])
    eligible_graduation_year = IntegerField("Eligible graduation year", validators=[
        Optional(), NumberRange(min=1990, max=2100),
    ])
    required_departments = StringField(
        "Eligible departments (comma separated, blank = all)",
        validators=[Optional(), Length(max=500)],
    )
    max_backlogs = IntegerField("Maximum active backlogs allowed", validators=[
        Optional(), NumberRange(min=0, max=30),
    ])
    required_skills = TextAreaField("Required skills (comma separated)",
                                    validators=[DataRequired(), Length(max=1000)])
    deadline = DateField("Application deadline", validators=[DataRequired()])
    submit = SubmitField("Save job posting")

    def validate_salary_max(self, field):
        if field.data is not None and self.salary_min.data is not None:
            if field.data < self.salary_min.data:
                raise ValidationError("Maximum salary cannot be lower than the minimum salary.")

    def validate_deadline(self, field):
        if field.data and field.data < date.today():
            raise ValidationError("The application deadline cannot be in the past.")


class ApplyForm(FlaskForm):
    cover_letter = TextAreaField("Cover note (optional)", validators=[Optional(), Length(max=5000)])
    submit = SubmitField("Submit application")


class ApplicationStatusForm(FlaskForm):
    """Status choices are rebuilt per application so only legal transitions appear."""

    status = SelectField("New status", choices=[], validators=[DataRequired()])
    note = StringField("Note to the student (optional)", validators=[Optional(), Length(max=300)])
    submit = SubmitField("Update application")

    def __init__(self, *args, current_status: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        allowed = APPLICATION_TRANSITIONS.get(current_status or "", ())
        self.status.choices = [(s, s) for s in allowed]
        if not allowed:
            self.status.choices = [("", "No further transitions available")]


class InterviewForm(FlaskForm):
    round_name = StringField("Round name", validators=[DataRequired(), Length(min=2, max=120)])
    scheduled_at = DateTimeLocalField("Date and time", format="%Y-%m-%dT%H:%M",
                                      validators=[DataRequired()])
    duration_minutes = IntegerField("Duration (minutes)", validators=[
        DataRequired(), NumberRange(min=10, max=480),
    ])
    mode = SelectField("Mode", choices=[(m, m) for m in INTERVIEW_MODES], validators=[DataRequired()])
    venue = StringField("Venue (for in-person rounds)", validators=[Optional(), Length(max=255)])
    meeting_link = StringField("Meeting link (for online rounds)", validators=[
        Optional(), Length(max=500),
        Regexp(r"^https?://.+", message="Meeting link must start with http:// or https://"),
    ])
    interviewer_name = StringField("Interviewer", validators=[Optional(), Length(max=150)])
    submit = SubmitField("Schedule interview")

    def validate_meeting_link(self, field):
        if self.mode.data == "Online" and not field.data:
            raise ValidationError("Provide a meeting link for online interviews.")

    def validate_venue(self, field):
        if self.mode.data == "In person" and not field.data:
            raise ValidationError("Provide a venue for in-person interviews.")

    def validate_scheduled_at(self, field):
        from .models import utcnow
        if field.data and field.data < utcnow():
            raise ValidationError("The interview must be scheduled in the future.")


class InterviewUpdateForm(FlaskForm):
    status = SelectField("Interview status", choices=[(s, s) for s in INTERVIEW_STATUSES],
                         validators=[DataRequired()])
    result = SelectField("Result", choices=[(r, r) for r in INTERVIEW_RESULTS],
                         validators=[DataRequired()])
    feedback = TextAreaField("Feedback", validators=[Optional(), Length(max=5000)])
    scheduled_at = DateTimeLocalField("Reschedule to", format="%Y-%m-%dT%H:%M", validators=[Optional()])
    mode = SelectField("Mode", choices=[(m, m) for m in INTERVIEW_MODES], validators=[DataRequired()])
    venue = StringField("Venue", validators=[Optional(), Length(max=255)])
    meeting_link = StringField("Meeting link", validators=[
        Optional(), Length(max=500),
        Regexp(r"^https?://.+", message="Meeting link must start with http:// or https://"),
    ])
    submit = SubmitField("Save interview")


class RejectForm(FlaskForm):
    reason = StringField("Reason", validators=[DataRequired(), Length(min=5, max=500)])
    submit = SubmitField("Confirm")


class RoleFilterForm(FlaskForm):
    """Read-only helper used to render GET filter bars with CSRF disabled."""

    class Meta:
        csrf = False


class AdminUserForm(FlaskForm):
    is_active = BooleanField("Account active")
    submit = SubmitField("Save account")
