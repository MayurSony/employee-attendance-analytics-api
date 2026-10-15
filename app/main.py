"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""
import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from decimal import Decimal, ROUND_HALF_UP
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from pydantic import BaseModel, Field, field_validator, model_validator
from decimal import Decimal, ROUND_HALF_UP
import re


load_dotenv()

client = MongoClient(
    os.getenv("MONGO_URI", "mongodb://localhost:27017")
)
db = client[os.getenv("MONGO_DB", "attendance_db")]

IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(
    title="Employee Attendance & Analytics API",
    version="2.0.0",
)



@app.on_event("startup")
def create_indexes():
    print("STARTUP: Creating MongoDB indexes...")

    # Employee indexes
    db.employees.create_index(
        [("emp_code", 1)],
        unique=True,
    )

    db.employees.create_index(
        [("department", 1), ("joined_on", 1)],
        name="idx_employee_department_joined",
    )

    # Attendance indexes
    db.attendance_logs.create_index(
        [("emp_code", 1), ("date", 1)],
        unique=True,
    )

    db.attendance_logs.create_index(
        [("date", -1), ("emp_code", 1)],
        name="idx_attendance_date_employee",
    )

    db.attendance_logs.create_index(
        [("emp_code", 1), ("date", -1)],
        name="idx_attendance_employee_date_desc",
    )

    db.attendance_logs.create_index(
        [("status", 1), ("date", -1)],
        name="idx_attendance_status_date",
    )

    print("STARTUP: MongoDB indexes created.")



IST = timezone(timedelta(hours=5, minutes=30))

# app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def employee_response(doc):
    result = {
        key: value
        for key, value in doc.items()
        if key not in {"_id", "id"}
    }

    if isinstance(result.get("created_at"), datetime):
        result["created_at"] = epoch_ms(result["created_at"])

    if isinstance(result.get("joined_on"), date):
        result["joined_on"] = result["joined_on"].isoformat()

    return result

def epoch_ms(value):
    if value is None:
        return None

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return int(value.timestamp() * 1000)


def attendance_response(doc):
    result = {
        key: value
        for key, value in doc.items()
        if key not in {"_id", "id"}
    }

    for field in ("punch_in", "punch_out"):
        result[field] = epoch_ms(result.get(field))

    for entry in result.get("history", []):
        entry["at"] = epoch_ms(entry["at"])

        for change in entry.get("changes", {}).values():
            for key in ("from", "to"):
                if isinstance(change.get(key), datetime):
                    change[key] = epoch_ms(change[key])

    return result


def validate_date_string(value: str, field_name: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must be a valid YYYY-MM-DD date",
        )

    if parsed.date().isoformat() != value:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must use YYYY-MM-DD format",
        )

    return value



def compute_late_minutes(
    punch_in: datetime,
    shift_start: str,
    attendance_date: str | None = None,
) -> int:
    h, m = map(int, shift_start.split(":"))

    if punch_in.tzinfo is None:
        punch_in = punch_in.replace(tzinfo=timezone.utc)

    punch_in_ist = punch_in.astimezone(IST)

    # The attendance date identifies the shift's starting date.
    if attendance_date is None:
        attendance_date = punch_in_ist.date().isoformat()

    shift_date = datetime.fromisoformat(attendance_date).date()

    scheduled_start = datetime(
        shift_date.year,
        shift_date.month,
        shift_date.day,
        h,
        m,
        tzinfo=IST,
    )

    elapsed_seconds = (
        punch_in_ist - scheduled_start
    ).total_seconds()

    # More than 10 minutes late triggers the late rule.
    if elapsed_seconds <= 600:
        return 0

    # Count whole minutes from the scheduled start, not after grace.
    return max(0, int(elapsed_seconds // 60))



def compute_work_hours(
    punch_in: datetime,
    punch_out: datetime,
) -> float:
    if punch_in.tzinfo is None:
        punch_in = punch_in.replace(tzinfo=timezone.utc)

    if punch_out.tzinfo is None:
        punch_out = punch_out.replace(tzinfo=timezone.utc)

    seconds = (punch_out - punch_in).total_seconds()
    hours = Decimal(str(seconds)) / Decimal("3600")

    return float(hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def compute_overtime(
    punch_out: datetime,
    shift_end: str,
    date_str: str,
    shift_start: str = "09:30",
) -> int:
    end_hour, end_minute = map(int, shift_end.split(":"))
    start_hour, start_minute = map(int, shift_start.split(":"))

    attendance_date = datetime.fromisoformat(date_str).date()

    shift_end_time = datetime(
        attendance_date.year,
        attendance_date.month,
        attendance_date.day,
        end_hour,
        end_minute,
        tzinfo=IST,
    )

    # A shift whose end time is earlier than or equal to its start time
    # ends on the following calendar day.
    if (end_hour, end_minute) <= (start_hour, start_minute):
        shift_end_time += timedelta(days=1)

    if punch_out.tzinfo is None:
        punch_out = punch_out.replace(tzinfo=timezone.utc)

    punch_out_ist = punch_out.astimezone(IST)
    overtime = int((punch_out_ist - shift_end_time).total_seconds() // 60)

    return max(0, overtime) if overtime >= 30 else 0



# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class EmployeeIn(BaseModel):
    emp_code: str = Field(pattern=r"^EMP\d{4,6}$")
    name: str
    email: str
    department: str
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str

    @field_validator("shift_start", "shift_end")
    @classmethod
    def validate_shift_time(cls, value: str) -> str:
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("Time must be in HH:MM format")
        return value

    @field_validator("joined_on")
    @classmethod
    def validate_joined_on(cls, value: str) -> str:
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise ValueError("joined_on must be a valid YYYY-MM-DD date")

        if parsed.date().isoformat() != value:
            raise ValueError("joined_on must be in YYYY-MM-DD format")
        return value

    @model_validator(mode="after")
    def validate_shift_range(self):
        if self.shift_start == self.shift_end:
            raise ValueError("shift_start and shift_end must differ")
        return self




class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None
    status: str = "PRESENT"

    @field_validator("punched_at", mode="before")
    @classmethod
    def validate_punched_at(cls, value):
        if value is None:
            return value
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("punched_at must be an integer epoch timestamp in milliseconds")
        if value < 100000000000 or value > 4102444800000:
            raise ValueError("punched_at is outside the allowed timestamp range")
        return value

    @field_validator("status")
    @classmethod
    def validate_status(cls, value):
        if value not in {"PRESENT", "WFH", "ON_DUTY"}:
            raise ValueError("status must be PRESENT, WFH, or ON_DUTY")
        return value


class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None

    @field_validator("punched_at", mode="before")
    @classmethod
    def validate_punched_at(cls, value):
        if value is None:
            return value

        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(
                "punched_at must be an integer epoch timestamp in milliseconds"
            )

        if value < 100000000000 or value > 4102444800000:
            raise ValueError("punched_at is outside the allowed timestamp range")

        return value


class RegularizeIn(BaseModel):
    status: Optional[str] = None
    punch_in: Optional[int] = None
    punch_out: Optional[int] = None
    reason: str = Field(min_length=5, max_length=200)
    regularized_by: str = Field(min_length=1, max_length=50)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value):
        if value is not None and value not in {
            "PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"
        }:
            raise ValueError("Invalid attendance status")
        return value

    @field_validator("punch_in", "punch_out", mode="before")
    @classmethod
    def validate_timestamp(cls, value):
        if value is None:
            return value
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("Timestamp must be integer epoch milliseconds")
        if value < 100000000000 or value > 4102444800000:
            raise ValueError("Timestamp is outside the allowed range")
        return value




# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #

@app.get("/health")
def health():
    try:
        db.command("ping")
        return {"status": "ok"}
    except Exception:
        raise HTTPException(status_code=503, detail="MongoDB unavailable")




@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    doc = body.model_dump()
    doc["created_at"] = datetime.now(IST)

    try:
        db.employees.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="emp_code already exists")

    doc.pop("_id", None)
    return employee_response(doc)



@app.get("/employees")
def list_employees(
    department: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    if page < 1:
        raise HTTPException(status_code=422, detail="page must be at least 1")

    if page_size < 1 or page_size > 100:
        raise HTTPException(
            status_code=422,
            detail="page_size must be between 1 and 100",
        )

    q = {}
    if department is not None:
        q["department"] = department

    total = db.employees.count_documents(q)
    skip = (page - 1) * page_size

    items = [
        employee_response(doc)
        for doc in db.employees.find(query, {"_id": 0})
        .sort("emp_code", 1)
        .skip((page - 1) * page_size)
        .limit(page_size)
    ]

    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": db.employees.count_documents(query),
    }



@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if emp is None:
        raise HTTPException(status_code=404, detail="Employee not found")

    if body.punched_at is None:
        ts = datetime.now(IST)
    else:
        ts = datetime.fromtimestamp(body.punched_at / 1000, tz=timezone.utc).astimezone(IST)

    # Truncate to whole seconds as required by the assignment.
    ts = ts.replace(microsecond=0)

    # For an overnight shift, punches before shift_end belong to the previous shift date.
    punch_date = ts.date()
    shift_start = emp["shift_start"]
    shift_end = emp["shift_end"]

    if shift_end <= shift_start:
        end_hour, end_minute = map(int, shift_end.split(":"))
        if (ts.hour, ts.minute) < (end_hour, end_minute):
            punch_date -= timedelta(days=1)

    date_str = punch_date.isoformat()

    doc = {
        "emp_code": body.emp_code,
        "date": date_str,
        "status": body.status,
        "punch_in": ts,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(ts, shift_start, date_str),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }

    try:
        res = db.attendance_logs.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="already punched in for this date")

    return attendance_response(doc)


@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    if page < 1:
        raise HTTPException(
            status_code=422,
            detail="page must be at least 1",
        )

    if page_size < 1 or page_size > 100:
        raise HTTPException(
            status_code=422,
            detail="page_size must be between 1 and 100",
        )

    
    if date_from is not None:
        validate_date_string(date_from, "date_from")

    if date_to is not None:
        validate_date_string(date_to, "date_to")

    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=422,
            detail="date_from must not be after date_to",
        )


    q = {}

    if emp_code is not None:
        q["emp_code"] = emp_code

    
    if status is not None:
        allowed_statuses = {
            "PRESENT",
            "WFH",
            "ON_DUTY",
            "ABSENT",
            "LEAVE",
        }

        if status not in allowed_statuses:
            raise HTTPException(
                status_code=422,
                detail="Invalid attendance status",
            )

        q["status"] = status


    if date_from is not None or date_to is not None:
        q["date"] = {}

        if date_from is not None:
            q["date"]["$gte"] = date_from

        if date_to is not None:
            q["date"]["$lte"] = date_to

    total = db.attendance_logs.count_documents(q)
    skip = (page - 1) * page_size

    docs = list(
        db.attendance_logs.find(q, {"_id": 0})
        .sort([("date", -1), ("emp_code", 1)])
        .skip(skip)
        .limit(page_size)
    )

    return {
        "items": docs,
        "total": total,
        "page": page,
        "page_size": page_size,
    }



######################################################
# Punch out
######################################################


@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})

    if emp is None:
        raise HTTPException(status_code=404, detail="Employee not found")

    if body.punched_at is None:
        ts = datetime.now(IST)
    else:
        ts = datetime.fromtimestamp(
            body.punched_at / 1000, tz=timezone.utc
        ).astimezone(IST)

    ts = ts.replace(microsecond=0)

    # Find the most recent attendance record that started by this time.
   
    record = db.attendance_logs.find_one(
        {
            "emp_code": body.emp_code,
            "punch_in": {"$lte": ts},
            "punch_out": None,
        },
        sort=[("punch_in", -1)],
    )


    if record is None:
        raise HTTPException(
            status_code=404,
            detail="No punch-in record found",
        )

    if record.get("punch_out") is not None:
        raise HTTPException(
            status_code=409,
            detail="Attendance record already punched out",
        )

    punch_in_time = record["punch_in"]

    # PyMongo may return stored datetimes as naive UTC values.
    if punch_in_time.tzinfo is None:
        punch_in_time = punch_in_time.replace(tzinfo=timezone.utc)

    if ts <= punch_in_time:
        raise HTTPException(
            status_code=422,
            detail="Punch-out must be after punch-in",
        )

    if (ts - punch_in_time).total_seconds() > 24 * 60 * 60:
        raise HTTPException(
            status_code=422,
            detail="Punch-out cannot be more than 24 hours after punch-in",
        )

    # Work out the scheduled shift end.
    shift_end_hour, shift_end_minute = map(
        int, emp["shift_end"].split(":")
    )

    attendance_date = datetime.fromisoformat(record["date"]).date()
    shift_start = emp["shift_start"]
    shift_end = emp["shift_end"]

    shift_end_time = datetime(
        attendance_date.year,
        attendance_date.month,
        attendance_date.day,
        shift_end_hour,
        shift_end_minute,
        tzinfo=IST,
    )

    # If the shift crosses midnight, its end is on the next day.
    if shift_end <= shift_start:
        shift_end_time += timedelta(days=1)

    overtime_minutes = compute_overtime(
        ts,
        emp["shift_end"],
        record["date"],
        emp["shift_start"],
    )

    elapsed_seconds = (ts - punch_in_time).total_seconds()
    work_hours = compute_work_hours(punch_in_time, ts)
    half_day = work_hours < 4.50

    result = db.attendance_logs.update_one(
        {
            "_id": record["_id"],
            "punch_out": None,
        },
        {
            "$set": {
                "punch_out": ts,
                "work_hours": work_hours,
                "overtime_minutes": overtime_minutes,
                "half_day": half_day,
            }
        },
    )

    if result.modified_count == 0:
        raise HTTPException(
            status_code=409,
            detail="Attendance record was already updated",
        )

    updated = db.attendance_logs.find_one(
        {"_id": record["_id"]},
        {"_id": 0},
    )

    return attendance_response(updated)


@app.patch("/attendance/{emp_code}/{date}")
def regularize_attendance(
    emp_code: str,
    date: str,
    body: RegularizeIn,
):
    validate_date_string(date, "date")

    emp = db.employees.find_one({"emp_code": emp_code})
    if emp is None:
        raise HTTPException(status_code=404, detail="Employee not found")

    query = {"emp_code": emp_code, "date": date}
    record = db.attendance_logs.find_one(query)

    if record is None:
        raise HTTPException(status_code=404, detail="Attendance record not found")

    changes_requested = body.model_dump(
        exclude_unset=True,
        exclude={"reason", "regularized_by"},
    )

    old_values = {
        "status": record.get("status"),
        "punch_in": record.get("punch_in"),
        "punch_out": record.get("punch_out"),
    }

    new_status = changes_requested.get("status", record.get("status"))
    new_in = changes_requested.get("punch_in", record.get("punch_in"))
    new_out = changes_requested.get("punch_out", record.get("punch_out"))

    def from_epoch(value):
        if value is None:
            return None
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)

    if "punch_in" in changes_requested:
        new_in = from_epoch(changes_requested["punch_in"])

    if "punch_out" in changes_requested:
        new_out = from_epoch(changes_requested["punch_out"])

    if new_status in {"ABSENT", "LEAVE"}:
        if "punch_in" in changes_requested or "punch_out" in changes_requested:
            raise HTTPException(
                status_code=422,
                detail="ABSENT and LEAVE cannot include punch times",
            )
        new_in = None
        new_out = None

    if new_status in {"PRESENT", "WFH", "ON_DUTY"} and new_in is None:
        raise HTTPException(
            status_code=422,
            detail="Presence status requires punch_in",
        )

    if new_in is not None:
        if new_in.tzinfo is None:
            new_in = new_in.replace(tzinfo=timezone.utc)

        new_in_ist = new_in.astimezone(IST)
        if new_in_ist.date().isoformat() != date:
            raise HTTPException(
                status_code=422,
                detail="punch_in must be on the attendance date",
            )

    if new_out is not None:
        if new_in is None:
            raise HTTPException(
                status_code=422,
                detail="punch_out requires punch_in",
            )

        if new_out.tzinfo is None:
            new_out = new_out.replace(tzinfo=timezone.utc)

        if new_out <= new_in:
            raise HTTPException(
                status_code=422,
                detail="punch_out must be after punch_in",
            )

        if (new_out - new_in).total_seconds() > 86400:
            raise HTTPException(
                status_code=422,
                detail="punch_out cannot be more than 24 hours after punch_in",
            )

    new_in = new_in.replace(microsecond=0) if new_in else None
    new_out = new_out.replace(microsecond=0) if new_out else None

    new_late = 0
    new_work = None
    new_overtime = 0
    new_half = False

    if new_in is not None:
        new_late = compute_late_minutes(
            new_in, emp["shift_start"], date
        )

    if new_in is not None and new_out is not None:
        new_work = compute_work_hours(new_in, new_out)
        new_overtime = compute_overtime(
            new_out,
            emp["shift_end"],
            date,
            emp["shift_start"],
        )
        new_half = new_work < 4.50

    final_values = {
        "status": new_status,
        "punch_in": new_in,
        "punch_out": new_out,
        "late_minutes": new_late,
        "work_hours": new_work,
        "overtime_minutes": new_overtime,
        "half_day": new_half,
    }

    changes = {}

    for field, new_value in final_values.items():
        old_value = record.get(field)

        if field in {"punch_in", "punch_out"} and old_value is not None:
            if old_value.tzinfo is None:
                old_value = old_value.replace(tzinfo=timezone.utc)

        if old_value != new_value:
            if field in {"punch_in", "punch_out"}:
                old_ms = (
                    int(old_value.timestamp() * 1000)
                    if old_value is not None else None
                )
                new_ms = (
                    int(new_value.timestamp() * 1000)
                    if new_value is not None else None
                )
                changes[field] = {"from": old_ms, "to": new_ms}
            else:
                changes[field] = {"from": old_value, "to": new_value}

    if not changes:
        raise HTTPException(
            status_code=422,
            detail="Request does not change the attendance record",
        )

    history_entry = {
        "at": datetime.now(timezone.utc).replace(microsecond=0),
        "by": body.regularized_by,
        "reason": body.reason,
        "changes": changes,
    }

    update_query = {
        "_id": record["_id"],
        "history": record.get("history", []),
    }

    result = db.attendance_logs.update_one(
        update_query,
        {
            "$set": final_values,
            "$push": {"history": history_entry},
        },
    )

    if result.modified_count == 0:
        raise HTTPException(
            status_code=409,
            detail="Attendance record changed concurrently; retry",
        )

    updated = db.attendance_logs.find_one(query, {"_id": 0})

    def epoch_ms(value):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int(value.timestamp() * 1000)

    for field in ("punch_in", "punch_out"):
        updated[field] = epoch_ms(updated.get(field))

    for entry in updated.get("history", []):
        entry["at"] = epoch_ms(entry["at"])
        for change in entry.get("changes", {}).values():
            pass

    return updated



@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(emp_code: str, month: str):
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(
            status_code=422,
            detail="month must use YYYY-MM format",
        )

    try:
        month_start = datetime.strptime(month, "%Y-%m").date()
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid month")

    emp = db.employees.find_one({"emp_code": emp_code})
    if emp is None:
        raise HTTPException(status_code=404, detail="Employee not found")

    year, month_num = map(int, month.split("-"))

    if month_num == 12:
        next_month = datetime(year + 1, 1, 1).date()
    else:
        next_month = datetime(year, month_num + 1, 1).date()

    month_end = next_month - timedelta(days=1)

    first_day = max(month_start, datetime.fromisoformat(emp["joined_on"]).date())

    working_days = 0
    current = first_day
    while current <= month_end:
        if current.weekday() < 5:
            working_days += 1
        current += timedelta(days=1)

    pipeline = [
        {
            "$match": {
                "emp_code": emp_code,
                "date": {
                    "$gte": month_start.isoformat(),
                    "$lte": month_end.isoformat(),
                },
            }
        },
        {
            "$addFields": {
                "_date_obj": {
                    "$dateFromString": {"dateString": "$date"}
                },
                "_presence": {
                    "$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]
                },
            }
        },
        {
            "$addFields": {
                "_weekday": {"$dayOfWeek": "$_date_obj"}
            }
        },
        {
            "$group": {
                "_id": None,
                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    "$_presence",
                                    {"$gt": ["$_weekday", 1]},
                                    {"$lt": ["$_weekday", 7]},
                                ]
                            },
                            {
                                "$cond": [
                                    {"$eq": ["$half_day", True]},
                                    0.5,
                                    1,
                                ]
                            },
                            0,
                        ]
                    }
                },
                "leave_days": {
                    "$sum": {
                        "$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]
                    }
                },
                "late_count": {
                    "$sum": {
                        "$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]
                    }
                },
                "total_late_minutes": {"$sum": "$late_minutes"},
                "total_overtime_minutes": {"$sum": "$overtime_minutes"},
            }
        },
    ]

    results = list(db.attendance_logs.aggregate(pipeline))
    stats = results[0] if results else {}

    present_days = float(stats.get("present_days", 0))
    attendance_pct = None

    if working_days > 0:
        attendance_pct = float(
            (Decimal(str(present_days)) * Decimal("100")
             / Decimal(working_days)).quantize(
                Decimal("0.0001"),
                rounding=ROUND_HALF_UP,
            )
        )

    return {
        "emp_code": emp_code,
        "month": month,
        "working_days": working_days,
        "present_days": present_days,
        "leave_days": stats.get("leave_days", 0),
        "late_count": stats.get("late_count", 0),
        "total_late_minutes": stats.get("total_late_minutes", 0),
        "total_overtime_minutes": stats.get("total_overtime_minutes", 0),
        "attendance_pct": attendance_pct,
    }


@app.get("/analytics/departments/summary")
def department_summary(
    month: str,
    department: Optional[str] = None,
):
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(
            status_code=422,
            detail="month must use YYYY-MM format",
        )

    year, month_num = map(int, month.split("-"))
    month_start = datetime(year, month_num, 1).date()

    if month_num == 12:
        next_month = datetime(year + 1, 1, 1).date()
    else:
        next_month = datetime(year, month_num + 1, 1).date()

    month_end = next_month - timedelta(days=1)

    employee_match = {
        "joined_on": {"$lte": month_end.isoformat()}
    }
    if department is not None:
        employee_match["department"] = department

    employees = list(db.employees.find(employee_match, {"_id": 0}))
    departments = sorted({e["department"] for e in employees})

    items = []

    for dept in departments:
        dept_employees = [
            e for e in employees if e["department"] == dept
        ]
        emp_codes = [e["emp_code"] for e in dept_employees]

        pipeline = [
            {
                "$match": {
                    "emp_code": {"$in": emp_codes},
                    "date": {
                        "$gte": month_start.isoformat(),
                        "$lte": month_end.isoformat(),
                    },
                }
            },
            {
                "$group": {
                    "_id": None,
                    "present_days": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$and": [
                                        {
                                            "$in": [
                                                "$status",
                                                ["PRESENT", "WFH", "ON_DUTY"],
                                            ]
                                        },
                                        {
                                            "$in": [
                                                {
                                                    "$dayOfWeek": {
                                                        "$dateFromString": {
                                                            "dateString": "$date"
                                                        }
                                                    }
                                                },
                                                [2, 3, 4, 5, 6],
                                            ]
                                        },
                                    ]
                                },
                                {
                                    "$cond": [
                                        {"$eq": ["$half_day", True]},
                                        0.5,
                                        1,
                                    ]
                                },
                                0,
                            ]
                        }
                    },
                    "avg_work_hours": {
                        "$avg": {
                            "$cond": [
                                {
                                    "$and": [
                                        {
                                            "$in": [
                                                "$status",
                                                ["PRESENT", "WFH", "ON_DUTY"],
                                            ]
                                        },
                                        {"$ne": ["$work_hours", None]},
                                    ]
                                },
                                "$work_hours",
                                None,
                            ]
                        }
                    },
                    "late_count": {
                        "$sum": {
                            "$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]
                        }
                    },
                    "total_late_minutes": {"$sum": "$late_minutes"},
                    "leave_count": {
                        "$sum": {
                            "$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]
                        }
                    },
                    "on_duty_count": {
                        "$sum": {
                            "$cond": [{"$eq": ["$status", "ON_DUTY"]}, 1, 0]
                        }
                    },
                }
            },
        ]

        result = list(db.attendance_logs.aggregate(pipeline))
        stats = result[0] if result else {}

        items.append(
            {
                "department": dept,
                "headcount": len(dept_employees),
                "present_days": float(stats.get("present_days", 0)),
                "avg_work_hours": (
                    float(
                        Decimal(str(stats["avg_work_hours"])).quantize(
                            Decimal("0.01"),
                            rounding=ROUND_HALF_UP,
                        )
                    )
                    if stats.get("avg_work_hours") is not None
                    else None
                ),
                "late_count": stats.get("late_count", 0),
                "total_late_minutes": stats.get("total_late_minutes", 0),
                "leave_count": stats.get("leave_count", 0),
                "on_duty_count": stats.get("on_duty_count", 0),
            }
        )

    return {"month": month, "items": items}


@app.get("/analytics/leaderboard/late")
def late_leaderboard(
    month: str,
    limit: int = 10,
    department: Optional[str] = None,
):
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise HTTPException(422, "month must be YYYY-MM")

    if not 1 <= limit <= 50:
        raise HTTPException(422, "limit must be between 1 and 50")

    try:
        month_start = datetime.strptime(month, "%Y-%m").date()
    except ValueError:
        raise HTTPException(422, "Invalid month")

    next_month = (
        month_start.replace(year=month_start.year + 1, month=1)
        if month_start.month == 12
        else month_start.replace(month=month_start.month + 1)
    )

    match = {
        "date": {
            "$gte": month_start.isoformat(),
            "$lt": next_month.isoformat(),
        },
        "late_minutes": {"$gt": 0},
    }

    pipeline = [
        {"$match": match},
        {
            "$group": {
                "_id": "$emp_code",
                "total_late_minutes": {"$sum": "$late_minutes"},
                "late_count": {"$sum": 1},
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "localField": "_id",
                "foreignField": "emp_code",
                "as": "employee",
            }
        },
        {"$unwind": "$employee"},
    ]

    if department is not None:
        pipeline.append(
            {"$match": {"employee.department": department}}
        )

    pipeline.extend([
        {
            "$project": {
                "_id": 0,
                "emp_code": "$_id",
                "name": "$employee.name",
                "department": "$employee.department",
                "total_late_minutes": 1,
                "late_count": 1,
            }
        },
        {
            "$setWindowFields": {
                "sortBy": {
                    "total_late_minutes": -1
                },
                "output": {
                    "rank": {
                        "$rank": {}
                    }
                },
            },
        },
        {"$sort": {"total_late_minutes": -1, "emp_code": 1}},
        {"$match": {"rank": {"$lte": limit}}},
    ])

    items = list(db.attendance_logs.aggregate(pipeline))

    return {
        "month": month,
        "items": items,
    }


@app.get("/analytics/departments/{department}/trend")
def department_trend(
    department: str,
    from_date: str = Query(alias="from"),
    to_date: str = Query(alias="to"),
):
    # Validate date format
    validate_date_string(from_date, "from")
    validate_date_string(to_date, "to")

    start = datetime.strptime(from_date, "%Y-%m-%d").date()
    end = datetime.strptime(to_date, "%Y-%m-%d").date()

    if end < start:
        raise HTTPException(
            status_code=422,
            detail="'to' must be on or after 'from'",
        )

    if (end - start).days > 91:
        raise HTTPException(
            status_code=422,
            detail="Date range cannot exceed 92 days",
        )

    # Confirm department exists
    if not db.employees.find_one({"department": department}):
        raise HTTPException(
            status_code=404,
            detail="Department not found",
        )

    # Generate one row per date, even when there are no attendance records.
    # MongoDB 5.1+ supports $densify.
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end, datetime.min.time())

    pipeline = [
        {
            "$match": {
                "date": {
                    "$gte": from_date,
                    "$lte": to_date,
                }
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "localField": "emp_code",
                "foreignField": "emp_code",
                "as": "employee",
            }
        },
        {"$unwind": "$employee"},
        {"$match": {"employee.department": department}},
        {
            "$project": {
                "day": {
                    "$dateFromString": {
                        "dateString": "$date",
                        "format": "%Y-%m-%d",
                    }
                },
                "status": 1,
                "half_day": {"$ifNull": ["$half_day", False]},
                "late_minutes": {"$ifNull": ["$late_minutes", 0]},
            }
        },
        {
            "$group": {
                "_id": "$day",
                "present_count": {
                    "$sum": {
                        "$cond": [
                            {
                                "$in": [
                                    "$status",
                                    ["PRESENT", "WFH", "ON_DUTY"],
                                ]
                            },
                            {"$cond": ["$half_day", 0.5, 1]},
                            0,
                        ]
                    }
                },
                "late_count": {
                    "$sum": {
                        "$cond": [
                            {"$gt": ["$late_minutes", 0]},
                            1,
                            0,
                        ]
                    }
                },
            }
        },
        {
            "$project": {
                "_id": 0,
                "day": "$_id",
                "present_count": 1,
                "late_count": 1,
            }
        },
        {
            "$densify": {
                "field": "day",
                "range": {
                    "step": 1,
                    "unit": "day",
                    "bounds": [start_dt, end_dt],
                },
            }
        },
        {
            "$set": {
                "present_count": {"$ifNull": ["$present_count", 0]},
                "late_count": {"$ifNull": ["$late_count", 0]},
                "date_string": {
                    "$dateToString": {
                        "format": "%Y-%m-%d",
                        "date": "$day",
                    }
                },
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "let": {"current_date": "$date_string"},
                "pipeline": [
                    {
                        "$match": {
                            "department": department,
                            "$expr": {
                                "$lte": ["$joined_on", "$$current_date"]
                            },
                        }
                    },
                    {"$count": "count"},
                ],
                "as": "headcount_result",
            }
        },
        {
            "$set": {
                "headcount": {
                    "$ifNull": [
                        {"$arrayElemAt": ["$headcount_result.count", 0]},
                        0,
                    ]
                },
                "weekday": {"$dayOfWeek": "$day"},
            }
        },
        {
            "$set": {
                "is_working_day": {
                    "$and": [
                        {"$gte": ["$weekday", 2]},
                        {"$lte": ["$weekday", 6]},
                    ]
                },
                "attendance_rate": {
                    "$cond": [
                        {
                            "$and": [
                                {"$gte": ["$weekday", 2]},
                                {"$lte": ["$weekday", 6]},
                                {"$gt": ["$headcount", 0]},
                            ]
                        },
                        {
                            "$multiply": [
                                {
                                    "$divide": [
                                        "$present_count",
                                        "$headcount",
                                    ]
                                },
                                100,
                            ]
                        },
                        None,
                    ]
                },
            }
        },
        {
            "$setWindowFields": {
                "sortBy": {"day": 1},
                "output": {
                    "moving_avg_7d": {
                        "$avg": "$attendance_rate",
                        "window": {"documents": [-6, 0]},
                    }
                },
            }
        },
        {
            "$project": {
                "_id": 0,
                "date": "$date_string",
                "is_working_day": 1,
                "headcount": 1,
                "present_count": 1,
                "late_count": 1,
                "attendance_rate": 1,
                "moving_avg_7d": 1,
            }
        },
        {"$sort": {"date": 1}},
    ]

    items = list(db.attendance_logs.aggregate(pipeline))

    # Round rates to four decimal places using half-up rounding.
    def round_four(value):
        if value is None:
            return None

        return float(
            Decimal(str(value)).quantize(
                Decimal("0.0001"),
                rounding=ROUND_HALF_UP,
            )
        )

    for item in items:
        item["attendance_rate"] = round_four(
            item.get("attendance_rate")
        )
        item["moving_avg_7d"] = round_four(
            item.get("moving_avg_7d")
        )

    return {
        "department": department,
        "from": from_date,
        "to": to_date,
        "items": items,
    }

@app.get("/admin/explain/{endpoint}")
def admin_explain(
    endpoint: str,
    emp_code: Optional[str] = None,
    month: Optional[str] = None,
    department: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    limit: int = 10,
):
    allowed = {
        "attendance_list",
        "employee_monthly",
        "department_summary",
        "late_leaderboard",
        "department_trend",
    }

    if endpoint not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"endpoint must be one of {sorted(allowed)}",
        )

    if page < 1 or not 1 <= page_size <= 100:
        raise HTTPException(422, "Invalid pagination parameters")

    if not 1 <= limit <= 50:
        raise HTTPException(422, "limit must be between 1 and 50")

    def require_month():
        if not month or not re.fullmatch(r"\d{4}-\d{2}", month):
            raise HTTPException(422, "month must be YYYY-MM")
        try:
            datetime.strptime(month, "%Y-%m")
        except ValueError:
            raise HTTPException(422, "Invalid month")

    def month_bounds():
        require_month()
        start = datetime.strptime(month, "%Y-%m").date()
        next_month = (
            start.replace(year=start.year + 1, month=1)
            if start.month == 12
            else start.replace(month=start.month + 1)
        )
        return start.isoformat(), next_month.isoformat()

    collection = "attendance_logs"
    skip = (page - 1) * page_size

    if endpoint == "attendance_list":
        query = {}

        if emp_code:
            query["emp_code"] = emp_code

        if status:
            if status not in {
                "PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"
            }:
                raise HTTPException(422, "Invalid status")
            query["status"] = status

        if date_from:
            validate_date_string(date_from, "date_from")
            query.setdefault("date", {})["$gte"] = date_from

        if date_to:
            validate_date_string(date_to, "date_to")
            query.setdefault("date", {})["$lte"] = date_to

        if date_from and date_to and date_from > date_to:
            raise HTTPException(422, "date_from must not exceed date_to")

        explain = db.command(
            "explain",
            {
                "find": collection,
                "filter": query,
                "sort": {"date": -1, "emp_code": 1},
                "skip": skip,
                "limit": page_size,
            },
            verbosity="executionStats",
        )

    else:
        start, end = month_bounds() if endpoint != "department_trend" else (None, None)

        if endpoint == "employee_monthly":
            if not emp_code:
                raise HTTPException(422, "emp_code is required")

            if not db.employees.find_one({"emp_code": emp_code}):
                raise HTTPException(404, "Employee not found")

            match = {
                "emp_code": emp_code,
                "date": {"$gte": start, "$lt": end},
            }

        elif endpoint == "department_summary":
            match = {"date": {"$gte": start, "$lt": end}}

            if department:
                match["department"] = department

        elif endpoint == "late_leaderboard":
            match = {
                "date": {"$gte": start, "$lt": end},
                "late_minutes": {"$gt": 0},
            }

        else:
            if not department or not from_date or not to_date:
                raise HTTPException(
                    422, "department, from and to are required"
                )

            validate_date_string(from_date, "from")
            validate_date_string(to_date, "to")

            if from_date > to_date:
                raise HTTPException(422, "'to' must be on or after 'from'")

            if (
                datetime.strptime(to_date, "%Y-%m-%d").date()
                - datetime.strptime(from_date, "%Y-%m-%d").date()
            ).days > 91:
                raise HTTPException(422, "Date range cannot exceed 92 days")

            match = {
                "date": {"$gte": from_date, "$lte": to_date}
            }

        pipeline = [{"$match": match}]

        if endpoint == "department_summary":
            pipeline.append({
                "$lookup": {
                    "from": "employees",
                    "localField": "emp_code",
                    "foreignField": "emp_code",
                    "as": "employee",
                }
            })
            pipeline.append({"$unwind": "$employee"})

            if department:
                pipeline.append({
                    "$match": {"employee.department": department}
                })

        elif endpoint == "late_leaderboard":
            pipeline.extend([
                {
                    "$group": {
                        "_id": "$emp_code",
                        "total_late_minutes": {"$sum": "$late_minutes"},
                    }
                },
                {"$sort": {"total_late_minutes": -1, "_id": 1}},
                {"$limit": limit},
            ])

        elif endpoint == "department_trend":
            pipeline.extend([
                {
                    "$lookup": {
                        "from": "employees",
                        "localField": "emp_code",
                        "foreignField": "emp_code",
                        "as": "employee",
                    }
                },
                {"$unwind": "$employee"},
                {"$match": {"employee.department": department}},
                {"$group": {"_id": "$date", "records": {"$sum": 1}}},
                {"$sort": {"_id": 1}},
            ])

        pipeline.append({"$limit": 1}) if endpoint == "employee_monthly" else None

        explain = db.command(
            "explain",
            {
                "aggregate": collection,
                "pipeline": pipeline,
                "cursor": {},
            },
            verbosity="executionStats",
        )

    return {
        "endpoint": endpoint,
        "collection": collection,
        "explain": explain,
    }


# --------------------------------------------------------------------------- #
# TODO - the rest of the contract (see openapi.yaml):
#   POST  /attendance/punch-out
#   PATCH /attendance/{emp_code}/{date}
#   GET   /analytics/employees/{emp_code}/monthly
#   GET   /analytics/departments/summary
#   GET   /analytics/leaderboard/late
#   GET   /analytics/departments/{department}/trend
#   GET   /admin/explain/{endpoint}
# --------------------------------------------------------------------------- #
