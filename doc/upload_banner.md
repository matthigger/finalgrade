# Preparing xlsx to upload to banner

Banner accepts an `xlsx` and asks you to say which of its columns is which. It
matches a row to a student only when all three of these line up, and silently
ignores a row where they don't:

- **CRN** (5 digits) — names *one section*
- **Term Code** (6 digits) — e.g. `202310`
- **Student ID** (9 digits) — no `S` suffix, leading zeros kept

The workbook this writes names those columns exactly as Banner does, so
Banner pre-selects them and there is one less dropdown to get wrong. The
fourth and last column is `Final Grade`, the letter. Banner is for final
grades, so that is all it is handed — pass `--full` if you would rather send
every grade column along with them.

## A CRN per section

A CRN names one section, and the gradebook already says which section each
student is in (gradescope's `Sections` column, canvas' `Section`). Give each
section its CRN and every row carries the one CRN that matches it, so the
whole course uploads in a single import:

    finalgrade banner grade_full.csv 202310 -s sec-01=12345 -s sec-02=67890

`SECTION` need only be the part of the section name that tells it from the
others — gradescope writes them as
`cs2810-34240-mathematics-of-data-models-sec-01-spring-2022`, and nobody is
going to type that. A fragment matching no section, or more than one, is an
error naming the sections there actually are.

A section you leave out is left out of the workbook, with a warning saying who
went and why. That is deliberate: those rows could never match anything, and
it is how you upload one section at a time when you want to.

In the browser, [the page](https://matthigger.github.io/finalgrade) reads the
sections off your gradebook and puts a CRN box next to each one.

## Every CRN on every row

A gradebook with no section column can still name its CRNs outright:

    finalgrade banner grade_full.csv 202310 -c 12345 -c 67890

Every CRN then rides along in its own column (`CRN0`, `CRN1`, …) on every row.
Banner is told which column to match on at import time and discards the rows
that don't line up with a warning, so the same file is uploaded once per
section, changing only which column you point at. The two ways are exclusive:
a row can only carry one CRN per column.

# Uploading to Banner

Select a course (click on a row), then click the "gear" in the top right to
"import" grades to Banner for that course:

<img src="banner.png" width=800>

If a record in the uploaded `xlsx` doesn't match all three fields above, a
warning is thrown.
