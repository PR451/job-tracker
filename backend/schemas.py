from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: EmailStr
    created_at: datetime


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class ApplicationBase(BaseModel):
    company: str = Field(min_length=1, max_length=160)
    job_title: str = Field(min_length=1, max_length=160)
    status: str = Field(default="Saved", max_length=40)
    job_link: str = Field(default="", max_length=500)
    applied_date: date = Field(default_factory=date.today)


class ApplicationCreate(ApplicationBase):
    pass


class ApplicationUpdate(BaseModel):
    company: str | None = Field(default=None, min_length=1, max_length=160)
    job_title: str | None = Field(default=None, min_length=1, max_length=160)
    status: str | None = Field(default=None, max_length=40)
    job_link: str | None = Field(default=None, max_length=500)
    applied_date: date | None = None


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    content: str
    created_at: datetime


class ApplicationOut(ApplicationBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    created_at: datetime
    notes: list[NoteOut] = []


class NoteCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class ResumeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    file_name: str
    file_path: str
    uploaded_at: datetime


class DashboardOut(BaseModel):
    total: int
    by_status: dict[str, int]
    recent_applications: list[ApplicationOut]
    resumes: list[ResumeOut]
