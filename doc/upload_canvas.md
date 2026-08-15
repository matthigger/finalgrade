# Uploading processed grades (`grade_full.csv`) to Canvas

Download a Canvas gradebook as some `canvas.csv` and run:

    finalgrade canvas grade_full.csv canvas.csv

The script will merge the grades and means into a new `canvas_<timestamp>.csv`
file which can be imported to Canvas.

## Notes
- Canvas displays to two rounded decimal places on the website, which can be ambiguous for students who rely on this last decimal place to determine grading thresholds at the end of the semester.  Consider passing the `--scale100` flag to scale your grades by 100 before uploading.

- We'll print a list of students who didn't match between the gradebooks (either from canvas or our own gradescope-derived csv).

- Canvas didn't take any string data as a grade (i.e. "letter") for me (Dec
  2022)

## Complaint
This approach, downloading and modifying a canvas template is cumbersome but I
don't see a better way: canvas has some internal ID which the gradescope csv doesn't have (even though this data initialized canvas!).  Canvas won't accept grades without this ID ... even though it's redundant with SIS User ID, which gradescope does have.