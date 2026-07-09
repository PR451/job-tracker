from datetime import datetime, timedelta
from html import unescape
from json import load as load_json
from pathlib import Path
from re import findall, search, sub
from secrets import randbelow
from shutil import copyfileobj
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
from zipfile import ZipFile

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from auth import create_access_token, get_current_user, get_db, hash_password, verify_password
from database import BASE_DIR, engine
from email_service import EmailDeliveryError, send_password_reset_code
from models import Application, Base, Note, PasswordReset, Resume, User
from schemas import (
    ApplicationCreate,
    ApplicationOut,
    ApplicationUpdate,
    AuthResponse,
    DashboardOut,
    JobRecommendationSearchOut,
    MessageOut,
    NoteCreate,
    NoteOut,
    PasswordResetConfirm,
    PasswordResetRequest,
    PasswordResetRequestOut,
    ResumeOut,
    UserCreate,
    UserLogin,
    UserOut,
)


Base.metadata.create_all(bind=engine)

app = FastAPI(title="Job Tracker API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

RESUME_KEYWORDS = [
    "React",
    "JavaScript",
    "Python",
    "FastAPI",
    "Teaching",
    "Healthcare",
    "SQL",
]


def ensure_sqlite_columns() -> None:
    if not str(engine.url).startswith("sqlite"):
        return

    with engine.begin() as connection:
        resume_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(resumes)")}
        if "extracted_text" not in resume_columns:
            connection.exec_driver_sql("ALTER TABLE resumes ADD COLUMN extracted_text TEXT NOT NULL DEFAULT ''")
        if "keywords" not in resume_columns:
            connection.exec_driver_sql("ALTER TABLE resumes ADD COLUMN keywords VARCHAR(500) NOT NULL DEFAULT ''")


ensure_sqlite_columns()


def clean_text(value: str) -> str:
    return sub(r"\\s+", " ", value).strip()


def extract_docx_text(file_path: Path) -> str:
    with ZipFile(file_path) as document:
        xml = document.read("word/document.xml").decode("utf-8", errors="ignore")
    text = sub(r"<[^>]+>", " ", xml)
    return clean_text(unescape(text))


def extract_resume_text(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix == ".docx":
        try:
            return extract_docx_text(file_path)
        except Exception:
            return ""

    data = file_path.read_bytes()
    if suffix in {".txt", ".md", ".csv"}:
        return clean_text(data.decode("utf-8", errors="ignore"))

    decoded = data.decode("latin-1", errors="ignore")
    candidates = findall(r"[A-Za-z0-9+#./,() -]{4,}", decoded)
    return clean_text(" ".join(candidates))[:20000]


def detect_resume_keywords(text: str) -> list[str]:
    found: list[str] = []
    for keyword in RESUME_KEYWORDS:
        pattern = rf"(?<![A-Za-z0-9]){keyword.replace('+', r'\\+')}(?![A-Za-z0-9])"
        if search(pattern, text, flags=2):
            found.append(keyword)
    return found


def latest_resume_for_user(user: User, db: Session) -> Resume | None:
    return (
        db.query(Resume)
        .filter(Resume.user_id == user.id)
        .order_by(Resume.uploaded_at.desc())
        .first()
    )


def fetch_remotive_jobs(query: str) -> list[dict]:
    url = f"https://remotive.com/api/remote-jobs?search={quote_plus(query)}"
    request = Request(url, headers={"User-Agent": "JobTrackerPortfolio/1.0"})
    with urlopen(request, timeout=12) as response:
        payload = load_json(response)
    return payload.get("jobs", [])


def build_job_recommendations(keywords: list[str], location: str) -> list[dict]:
    search_terms = keywords[:4] or ["Python", "JavaScript"]
    raw_jobs: list[dict] = []
    seen_ids: set[str] = set()

    for term in search_terms:
        try:
            jobs = fetch_remotive_jobs(term)
        except Exception:
            continue

        for job in jobs:
            job_id = str(job.get("id") or job.get("url") or "")
            if not job_id or job_id in seen_ids:
                continue
            seen_ids.add(job_id)
            raw_jobs.append(job)
            if len(raw_jobs) >= 30:
                break
        if len(raw_jobs) >= 30:
            break

    location_text = location.strip().lower()

    def score(job: dict) -> int:
        haystack = " ".join(
            str(job.get(field, ""))
            for field in ("title", "company_name", "description", "candidate_required_location")
        ).lower()
        value = sum(3 for keyword in keywords if keyword.lower() in haystack)
        if location_text and location_text in haystack:
            value += 5
        if location_text and any(word in haystack for word in ("worldwide", "anywhere", "remote")):
            value += 1
        return value

    ranked = sorted(raw_jobs, key=score, reverse=True)
    recommendations: list[dict] = []
    for job in ranked[:12]:
        haystack = " ".join(
            str(job.get(field, ""))
            for field in ("title", "company_name", "description", "candidate_required_location")
        ).lower()
        matched = [keyword for keyword in keywords if keyword.lower() in haystack]
        recommendations.append(
            {
                "id": str(job.get("id") or job.get("url") or len(recommendations)),
                "company": job.get("company_name") or "Unknown company",
                "title": job.get("title") or "Untitled role",
                "location": job.get("candidate_required_location") or "Remote",
                "url": job.get("url") or "",
                "source": "Remotive",
                "matched_keywords": matched,
                "description": clean_text(sub(r"<[^>]+>", " ", job.get("description") or ""))[:240],
            }
        )
    return recommendations


def get_user_application(application_id: int, user: User, db: Session) -> Application:
    application = (
        db.query(Application)
        .options(selectinload(Application.notes))
        .filter(Application.id == application_id, Application.user_id == user.id)
        .first()
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return application


@app.get("/")
def root():
    return {"message": "Job Tracker API running"}


@app.post("/auth/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: UserCreate, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(func.lower(User.email) == payload.email.lower()).first()
    if existing_user:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        name=payload.name.strip(),
        email=payload.email.lower(),
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return AuthResponse(access_token=create_access_token(str(user.id)), user=user)


@app.post("/auth/login", response_model=AuthResponse)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(func.lower(User.email) == payload.email.lower()).first()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    return AuthResponse(access_token=create_access_token(str(user.id)), user=user)


@app.post("/auth/forgot-password", response_model=PasswordResetRequestOut)
def forgot_password(payload: PasswordResetRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(func.lower(User.email) == payload.email.lower()).first()
    generic_message = "If that email is registered, a reset code has been sent."
    if user is None:
        return PasswordResetRequestOut(message=generic_message, email_sent=False)

    code = f"{randbelow(1_000_000):06d}"
    reset = PasswordReset(
        user_id=user.id,
        code_hash=hash_password(code),
        expires_at=datetime.utcnow() + timedelta(minutes=15),
    )
    db.add(reset)
    db.commit()

    try:
        send_password_reset_code(user.email, code)
        return PasswordResetRequestOut(message=generic_message, email_sent=True)
    except EmailDeliveryError as exc:
        return PasswordResetRequestOut(
            message=generic_message,
            email_sent=False,
            email_error=str(exc),
        )


@app.post("/auth/reset-password", response_model=MessageOut)
def reset_password(payload: PasswordResetConfirm, db: Session = Depends(get_db)):
    user = db.query(User).filter(func.lower(User.email) == payload.email.lower()).first()
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid or expired reset code")

    reset = (
        db.query(PasswordReset)
        .filter(PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None))
        .order_by(PasswordReset.created_at.desc())
        .first()
    )
    if reset is None or reset.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired reset code")

    if not verify_password(payload.code, reset.code_hash):
        raise HTTPException(status_code=400, detail="Invalid or expired reset code")

    user.hashed_password = hash_password(payload.new_password)
    reset.used_at = datetime.utcnow()
    db.commit()
    return MessageOut(message="Password updated. You can log in with your new password.")


@app.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@app.get("/applications", response_model=list[ApplicationOut])
def list_applications(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(Application)
        .options(selectinload(Application.notes))
        .filter(Application.user_id == user.id)
        .order_by(Application.created_at.desc())
        .all()
    )


@app.post("/applications", response_model=ApplicationOut, status_code=status.HTTP_201_CREATED)
def create_application(
    payload: ApplicationCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application = Application(user_id=user.id, **payload.model_dump())
    db.add(application)
    db.commit()
    db.refresh(application)
    return application


@app.get("/applications/{application_id}", response_model=ApplicationOut)
def get_application(
    application_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_user_application(application_id, user, db)


@app.put("/applications/{application_id}", response_model=ApplicationOut)
def update_application(
    application_id: int,
    payload: ApplicationUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application = get_user_application(application_id, user, db)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(application, key, value)
    db.commit()
    db.refresh(application)
    return application


@app.delete("/applications/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_application(
    application_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application = get_user_application(application_id, user, db)
    db.delete(application)
    db.commit()
    return None


@app.post("/applications/{application_id}/notes", response_model=NoteOut, status_code=status.HTTP_201_CREATED)
def create_note(
    application_id: int,
    payload: NoteCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application = get_user_application(application_id, user, db)
    note = Note(application_id=application.id, content=payload.content.strip())
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@app.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(
    note_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    note = (
        db.query(Note)
        .join(Application)
        .filter(Note.id == note_id, Application.user_id == user.id)
        .first()
    )
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    db.delete(note)
    db.commit()
    return None


@app.post("/resumes", response_model=ResumeOut, status_code=status.HTTP_201_CREATED)
def upload_resume(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="File name is required")

    safe_name = Path(file.filename).name.replace(" ", "_")
    stored_name = f"user_{user.id}_{safe_name}"
    file_path = UPLOAD_DIR / stored_name

    with file_path.open("wb") as output:
        copyfileobj(file.file, output)

    extracted_text = extract_resume_text(file_path)
    keywords = detect_resume_keywords(extracted_text)
    resume = Resume(
        user_id=user.id,
        file_name=safe_name,
        file_path=str(file_path),
        extracted_text=extracted_text,
        keywords=", ".join(keywords),
    )
    db.add(resume)
    db.commit()
    db.refresh(resume)
    return resume


@app.get("/resumes", response_model=list[ResumeOut])
def list_resumes(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(Resume)
        .filter(Resume.user_id == user.id)
        .order_by(Resume.uploaded_at.desc())
        .all()
    )


@app.get("/job-recommendations", response_model=JobRecommendationSearchOut)
def job_recommendations(
    location: str = Query(default="", max_length=120),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    resume = latest_resume_for_user(user, db)
    if resume is None:
        return JobRecommendationSearchOut(keywords=[], location=location, jobs=[])

    keywords = [keyword.strip() for keyword in resume.keywords.split(",") if keyword.strip()]
    if not keywords and resume.extracted_text:
        keywords = detect_resume_keywords(resume.extracted_text)

    jobs = build_job_recommendations(keywords, location)
    return JobRecommendationSearchOut(keywords=keywords, location=location, jobs=jobs)


@app.get("/dashboard", response_model=DashboardOut)
def dashboard(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    applications = (
        db.query(Application)
        .options(selectinload(Application.notes))
        .filter(Application.user_id == user.id)
        .order_by(Application.created_at.desc())
        .all()
    )
    resumes = (
        db.query(Resume)
        .filter(Resume.user_id == user.id)
        .order_by(Resume.uploaded_at.desc())
        .limit(5)
        .all()
    )

    by_status: dict[str, int] = {}
    for application in applications:
        by_status[application.status] = by_status.get(application.status, 0) + 1

    return DashboardOut(
        total=len(applications),
        by_status=by_status,
        recent_applications=applications[:5],
        resumes=resumes,
    )
