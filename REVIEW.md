# REVIEW.md

## Defects Found and Fixed

| # | Where (function / line) | What is wrong | How noticed (test, input, or symptom) | How fixed |
|---|---|---|---|---|
| 1 | MongoDB startup/index creation | Creating an existing index with a conflicting name can cause startup to fail. | Application startup reported an index creation conflict. | Aligned index creation with existing key patterns and used stable names for additional indexes. |
| 2 | Punch-in response | Returning the inserted document directly can expose MongoDB identifiers and inconsistent timestamp formats. | Inspected the endpoint response in Swagger. | Added `attendance_response()` to exclude internal identifiers and convert attendance timestamps to epoch milliseconds. |
| 3 | Punch-out response | Returning the updated document directly can expose internal identifiers and inconsistent timestamp formats. | Inspected the response-building code. | Used `attendance_response()` for the updated attendance document. |
| 4 | Employee response handling | Employee responses can expose internal identifiers or serialize `created_at` inconsistently. | Inspected employee endpoint responses. | Added `employee_response()` to normalize employee response fields. |
| 5 | Late leaderboard aggregation | The `$rank` window stage rejected a multi-field sort specification. | The leaderboard endpoint returned an aggregation error. | Used a single sort field for ranking and applied deterministic ordering afterward. |

## Reviewed but Not Confirmed as Defects

- The department trend endpoint returned seven entries for the tested seven-day date range.
- The attendance list, employee monthly, department summary, and late leaderboard explain requests used index scans on the local sample dataset.
- Eight smoke-tested endpoints returned HTTP 200. These results confirm that the tested requests succeeded, but do not prove that every business rule is correct or that performance will remain acceptable on a larger dataset.

## Remaining Verification

- Test punch-out behavior for open, completed, duplicate, and out-of-order records.
- Verify regularization validation and history consistency.
- Check all response fields against the API contract, including timestamp formats and exclusion of MongoDB internal identifiers.
- Validate analytics calculations against boundary cases and rounding rules.
- Verify that each admin explain option represents the corresponding endpoint's actual query or aggregation pipeline.
- Test query performance using representative larger data volumes.

