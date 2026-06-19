# Job Tracker

A full-stack job application tracker built with FastAPI, SQLite, SQLAlchemy,
JWT authentication, and Angular.

## Features

- Signup and login
- JWT-protected API routes
- Application tracking with status updates
- Dashboard counts by status
- Resume uploads to local storage
- Notes on each application

## Project Structure

```text
backend/
  auth.py             Password hashing, JWT creation, current-user dependency
  database.py         SQLite database connection
  main.py             FastAPI routes
  models.py           SQLAlchemy tables
  schemas.py          Pydantic request and response schemas
  uploads/            Uploaded resume files

frontend/frontend/
  src/app/app.ts      Angular app logic
  src/app/app.html    App template
  src/app/app.css     App styling
```

## Backend

Install and run:

```bash
cd backend
python -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/uvicorn main:app --reload
```

Open the API docs:

```text
http://127.0.0.1:8000/docs
```

By default, the backend uses:

```text
backend/job_tracker.db
```

To override it, set `JOB_TRACKER_DB_URL` in `backend/.env`.

## Frontend

Run the Angular app:

```bash
cd frontend/frontend
yarn start --host 127.0.0.1 --port 4201
```

Open:

```text
http://127.0.0.1:4201/
```

## API Overview

- `POST /auth/signup`
- `POST /auth/login`
- `GET /me`
- `GET /dashboard`
- `POST /applications`
- `GET /applications`
- `GET /applications/{id}`
- `PUT /applications/{id}`
- `DELETE /applications/{id}`
- `POST /applications/{id}/notes`
- `DELETE /notes/{id}`
- `POST /resumes`
- `GET /resumes`

## Verification

Useful checks:

```bash
python -m py_compile backend/main.py backend/database.py backend/models.py backend/schemas.py backend/auth.py
cd frontend/frontend
./node_modules/.bin/tsc -p tsconfig.app.json --noEmit
```
