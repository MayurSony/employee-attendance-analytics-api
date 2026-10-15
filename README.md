# Employee Attendance & Analytics API

## Overview

This project implements an Employee Attendance & Analytics REST API using **FastAPI, Python, and MongoDB**. It supports employee management, attendance tracking, punch-in/punch-out operations, attendance regularization, and workforce analytics.

The API follows the provided OpenAPI contract and uses MongoDB indexes to support efficient queries and prevent duplicate daily attendance records.

## Features

- Create and list employees with pagination.
- Record employee punch-in and punch-out.
- List attendance records with filtering and pagination.
- Regularize attendance records with change history.
- Generate monthly employee attendance analytics.
- Generate department-level monthly summaries.
- Rank employees by total late-arrival minutes.
- Generate department attendance trends.
- Inspect MongoDB query execution plans through an admin endpoint.
- Validate request data and return appropriate HTTP errors.

## Technology Stack

- Python
- FastAPI
- MongoDB
- PyMongo
- Pydantic
- Uvicorn

## Prerequisites

- Python 3.10 or a compatible version supported by the installed dependencies.
- MongoDB Community Server 6.0 or newer.
- Git (for version control).

## Installation and Setup

Run the following commands from the project root directory.

### 1. Create a virtual environment

```powershell
python -m venv .venv
```

Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configure environment variables

Create a `.env` file in the project root containing:

```env
MONGO_URI=mongodb://localhost:27017
MONGO_DB=attendance_db
```

Ensure MongoDB is running locally before starting the API. Environment variables can also be configured in the execution environment.

**Security:** Do not commit `.env`, credentials, or other secrets to Git.

### 4. Start the application

```powershell
uvicorn app.main:app --port 8000
```

### 5. Access the API

- **Swagger UI:** http://127.0.0.1:8000/docs
- **Health check:** http://127.0.0.1:8000/health

Swagger UI provides interactive API documentation and allows requests to be executed directly.

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Check API and database health |
| POST | `/employees` | Create an employee |
| GET | `/employees` | List employees |
| POST | `/attendance/punch-in` | Record punch-in |
| POST | `/attendance/punch-out` | Record punch-out |
| GET | `/attendance` | List and filter attendance |
| PATCH | `/attendance/{emp_code}/{date}` | Regularize an attendance record |
| GET | `/analytics/employees/{emp_code}/monthly` | Get monthly employee analytics |
| GET | `/analytics/departments/summary` | Get monthly department summaries |
| GET | `/analytics/leaderboard/late` | Get the late-arrival leaderboard |
| GET | `/analytics/departments/{department}/trend` | Get department attendance trends |
| GET | `/admin/explain/{endpoint}` | Inspect MongoDB query execution plans |

Refer to Swagger UI for the exact request schemas, required parameters, validation rules, and response formats.

## Database Design

The application uses two MongoDB collections:

- **`employees`** — stores employee details, department, joining date, and related information.
- **`attendance_logs`** — stores attendance dates, punch timestamps, status, derived attendance metrics, and regularization history.

A unique compound index on `(emp_code, date)` prevents duplicate attendance records for the same employee and date. Additional indexes support employee lookups, attendance filtering, and date-based sorting.

## Attendance and Analytics

The API calculates attendance metrics according to the assignment's business rules, including late minutes, work hours, overtime, and half-day status.

Monthly analytics and department summaries aggregate attendance information over the requested period. The department summary must account for eligible employees even when they have no attendance logs.

Timestamps are returned in epoch milliseconds where required by the API contract. Attendance dates and shift calculations follow the configured IST rules.

## Testing and Performance

The implemented endpoints were smoke-tested locally through Swagger UI. The following endpoint groups returned successful responses during testing:

- Health, employee listing, and attendance listing.
- Monthly employee analytics.
- Department summaries and trends.
- Late-arrival leaderboard.
- Admin query explain.

MongoDB explain results showed index usage for the tested attendance and analytics queries on the local sample dataset.

These smoke tests and explain results are initial verification only. Complete business-rule correctness and performance on the grader's larger dataset require additional testing.

## Repository Hygiene

The repository should contain the application source code, `requirements.txt`, and the required documentation files:

- `README.md`
- `DECISIONS.md`
- `REVIEW.md`

Do not commit `.env`, `.venv/`, credentials, or local database dumps.
