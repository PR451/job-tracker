from datetime import datetime, timedelta
from pathlib import Path
from secrets import randbelow
from shutil import copyfileobj

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
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

    resume = Resume(user_id=user.id, file_name=safe_name, file_path=str(file_path))
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
