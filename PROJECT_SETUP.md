# Job Tracker Setup

## What This App Does

Job Tracker helps a user manage their job search. After signup or login, the
user can add job applications, update each application status, upload resumes,
write notes, review dashboard counts, and find job recommendations based on
resume keywords.

## Backend Environment

The app works with SQLite by default and creates:

```text
backend/job_tracker.db
```

Optional database override in `backend/.env`:

```env
JOB_TRACKER_DB_URL=sqlite:///./job_tracker.db
```

Password reset emails require SMTP settings in `backend/.env`:

```env
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=your-smtp-username
SMTP_PASSWORD=your-smtp-password
SMTP_FROM=no-reply@example.com
SMTP_USE_TLS=true
```

Set a production JWT secret before deploying:

```env
SECRET_KEY=replace-this-with-a-long-random-value
```

## Run Backend

```bash
cd backend
python -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/uvicorn main:app --reload
```

## Run Frontend

```bash
cd frontend/frontend
yarn start --host 127.0.0.1 --port 4201
```

Open:

```text
http://127.0.0.1:4201/
```

If port `4201` is busy, choose another port and keep the backend on
`http://127.0.0.1:8010` if your frontend API URL is set to that port.

## Job Recommendations

Upload a resume, then enter a preferred location in the Job suggestions panel.
The backend detects keywords such as React, JavaScript, Python, FastAPI,
Teaching, Healthcare, and SQL, calls the public Remotive jobs API, and returns
recommended jobs. Use Save to Tracker to add a recommendation to your
applications list.
