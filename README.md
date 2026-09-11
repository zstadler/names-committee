# names-committee

Extract official names from the Israel Names Committee publications.

The decisions of the Israeli Government Names Committee (ועדת השמות הממשלתית) are published in
Yalkut HaPirsumim (ילקוט הפרסומים); this extracts them from the scanned issues, 1950-2026.

The text layer in older publications is damaged. The pipeline ignores it and runs real
OCR on 600dpi page renders, reconstructing each record from the page.

## Requirements

- `tesseract` with Hebrew data, `poppler-utils` (`pdftoppm`, `pdfinfo`)
- Python: `opencv-python-headless`, `numpy`, `openpyxl`, `docopt` (auto-installed on first run)

The Hebrew model matters: install the full model, not the legacy apt package.

```bash
curl -sL -o /tmp/heb.traineddata \
  "https://raw.githubusercontent.com/tesseract-ocr/tessdata/main/heb.traineddata"
ls -la /tmp/heb.traineddata   # must be ~5.4MB - a few hundred bytes means an error page
sudo cp /tmp/heb.traineddata /usr/share/tesseract-ocr/5/tessdata/heb.traineddata
```

`apt-get install tesseract-ocr-heb` installs a 961KB 2019 model instead. It runs, but every
threshold in this repo was calibrated against the full model.

## Usage

```bash
mkdir -p samples
# download an issue PDF into samples/ (URLs are in data/stage1_input_clean.csv)
./run_batch_600dpi --pdf=samples/booklet_2633.pdf --booklet=2633 --jobs=2 --budget=3000 \
  --stage1=data/stage1_input_clean.xlsx
./build_v3_output --booklet=2633 --date=1980-06-10 --tag=run --out=.
```

`run_batch_600dpi` writes one JSON file per page under `scan/pages/`, so an interrupted run
resumes where it stopped; `--reset` discards them. It then stitches the pages in order into
`scan/entries_600dpi.jsonl` and `scan/warnings_600dpi.jsonl`. `build_v3_output` turns those
into a workbook: one sheet of names in source order, plus a warnings sheet.

Set `--jobs` to the number of cores. Note that Tesseract's own OpenMP threading is
counter-productive here (measured 3.5x slower at 600dpi with identical output), so the code
pins `OMP_THREAD_LIMIT=1` per worker and parallelises across pages instead.

## Files

| File | Role |
|---|---|
| `ocr_parser.py` | render, denoise, OCR (word boxes and letter boxes), field regexes |
| `ocr_parser2.py` | the parser: headers, slices, column split, line grouping, entry state machine, checks |
| `run_batch_600dpi` | per-page parallel runner and the page-stitching pass |
| `build_v3_output` | Excel builder |
| `PROJECT_NOTES.md` | full specification and development log, in Hebrew |
| `data/stage1_input_clean.xlsx` | the 42 relevant issues, with PDF URLs and per-issue calibration - the parser reads this and writes calibrated thresholds back into it |
| `data/stage1_input_clean.csv` | text export of the above, for diffing and quick viewing |
| `data/stage1_removed_records.csv` | 33 issues filtered out in stage 1, kept for audit |
| `output/booklet_2633_v28.xlsx` | current results for issue 2633: names in source order, plus a warnings sheet |
| `output/booklet_2633_*.csv` | text export of the same results |

`PROJECT_NOTES.md` is the authoritative document. The working environment was lost once, and
the code was rebuilt from those notes alone, so they are kept detailed on purpose: every
threshold records how it was measured, and mechanisms that were tried and rejected are
documented as rejected so they are not reintroduced.

## Quality checks

The parser cannot be assumed correct, so each run emits warnings for manual review:

- `possible-skipped-name` - a column has more description openers than names, meaning a name
  was missed. Precise, but blind in three categories whose descriptions do not open with a
  grid reference (regional councils, postal lines, roads).
- `large-gap-continuation` - a description line follows an oversized vertical gap, meaning its
  name was missed and the text attached to the previous entry. Works in every category.
- `unrecognized-text` - text the OCR read that no entry used: words dropped by the noise
  filter, or lines no entry consumed. The only check that catches text deleted by a filter.
- `name-gap-suspicious` - an unusual distance between consecutive names. Weak (measured 55%
  sensitivity), kept as a secondary net pending evaluation over more issues.
- `coords-format` - an extracted grid reference that is not `nnn.nnn` or `nnnn.nnnn`.
- `gutter-fallback` - no printed column separator found in a slice; harmless above the first
  heading on a page, where there are no two columns of content.

Each entry also carries minimum and average OCR confidence and its weakest word, and the
workbook colours the score column against two editable thresholds in row 1.

## Source

Yalkut HaPirsumim is published by the Israeli Ministry of Justice. Issue PDFs are served from
`free-justice.openapi.gov.il` and `pub-justice.openapi.gov.il`; availability of the two hosts
varies over time, so try both and verify the result is a real PDF rather than a JSON error body.
