# DECISIONS.md

## 1. Indexes

I created a unique index on `employees.emp_code` to prevent duplicate employee codes and support employee lookups. The unique compound index on `attendance_logs.emp_code` and `date` prevents duplicate daily attendance records. Additional compound indexes support date-based attendance listing, employee attendance history, and status/date filtering. I did not add an index on `late_minutes` because the current explain results do not show enough evidence that it is necessary.

## 2. Punch-in race

Two identical punch-in requests may both check for an existing record before either inserts. The unique compound index on `(emp_code, date)` ensures that only one insert succeeds. The other insert raises a duplicate-key error, which the API should convert to HTTP 409 Conflict.

## 3. Ties

The leaderboard ranks employees by total late minutes. Employees tied at the cutoff can share the same rank and may all be returned, so the number of results can exceed the requested limit. A secondary employee-code sort provides deterministic ordering.

## 4. Headcount

Department headcount should be calculated from employees who joined by the end of the selected month, not only from attendance records. This includes eligible employees who have no attendance logs.

## 5. Scaling

For 100 times more data, I would test using a representative large dataset, inspect execution statistics, and optimize the actual aggregation pipelines before adding more indexes. I would also review pagination and database workload.