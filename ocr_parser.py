#!/usr/bin/env python3
"""Base OCR helpers for the Yalkut HaPirsumim names-committee parser."""
import csv
import importlib
import os
import re
import statistics
import subprocess
import sys


def ensure_package(module_name, pip_name=None):
  """Import a non-standard module, installing it with pip when missing."""
  try:
    return importlib.import_module(module_name)
  except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--break-system-packages", pip_name or module_name], check=True)
    return importlib.import_module(module_name)


cv2 = ensure_package("cv2", "opencv-python-headless")
np = ensure_package("numpy")

DPI_DEFAULT = 600
BOTTOM_CROP_FRACTION = 0.90
NOISE_AREA_THRESHOLD_600DPI = 100
NOISE_AREA_THRESHOLD_300DPI = 35
ACTIVE_DPI = DPI_DEFAULT
TESSERACT_OMP_THREADS = 1
NIQQUD_RE = re.compile(r"[֑-ׇ]")
PREFIX_WORDS = {'מ"א', 'ד"נ', "מ״א", "ד״נ", "מ*א", "ד*נ", "מ'א", "ד'נ"}
MOVEMENT_RE = re.compile(r"(?:משקי\s+)?תנועת\s+(.+?)(?:,|\s+ב[א-ת]{2,}|\s*\(|\.)")
COORDS_RE = re.compile(r"(?:[נגב][\"*׳״'”“]?|[\"*׳״'”“])צ\s*[.,:]?\s*(\d{2,6})(?:\s*[.,;:\u2013-]{0,2}\s*(\d{2,6}))?")
COORDS_OK_RE = re.compile(r"^\d{3}\.\d{3}$|^\d{4}\.\d{4}$")
CATEGORY_KEYWORDS = [
  ("מועצות אזוריות", ["מועצות אזוריות", "למועצות"]),
  ("ישובים", ["ליישובים", "לישובים"]),
  ("קווי דואר-נע", ["דואר נע", "דואר-נע"]),
  ("אתרים היסטוריים", ["אתרים היסטוריים", "היסטוריים"]),
  ("שמורות טבע", ["שמורות טבע", "לשמורות"]),
  ("עצמים גיאוגרפיים", ["עצמים גיאוגרפיים", "לעצמים", "עצמים"]),
  ("מאגרי מים", ["מאגרי מים", "למאגרי"]),
  ("מערות", ["למערות"]),
  ("דרכים", ["לדרכים"]),
  ("מחלפים", ["למחלפים"]),
  ("צמתים", ["לצמתים"]),
]
CATEGORY_HEADER_PHRASES = [
  ("מועצות אזוריות", "שמות למועצות אזוריות"),
  ("ישובים", "שמות ליישובים"),
  ("קווי דואר-נע", "קווי דואר נע"),
  ("אתרים היסטוריים", "שמות לאתרים היסטוריים"),
  ("שמורות טבע", "שמות לשמורות טבע"),
  ("עצמים גיאוגרפיים", "שמות לעצמים גיאוגרפיים"),
  ("מאגרי מים", "שמות למאגרי מים"),
  ("מערות", "שמות למערות"),
  ("דרכים", "שמות לדרכים"),
  ("מחלפים", "שמות למחלפים"),
  ("צמתים", "שמות לצמתים"),
]


def strip_niqqud(text):
  """Remove Hebrew vowel points and cantillation marks from text."""
  return NIQQUD_RE.sub("", text)


def render_page_png(pdf_path, page, out_dir, dpi=DPI_DEFAULT, crop_fraction=BOTTOM_CROP_FRACTION):
  """Render one PDF page to PNG at the given dpi and crop the footer strip from the bottom."""
  global ACTIVE_DPI
  ACTIVE_DPI = dpi
  os.makedirs(out_dir, exist_ok=True)
  prefix = os.path.join(out_dir, "page_%03d_%ddpi" % (page, dpi))
  out_path = prefix + ".png"
  if not os.path.exists(out_path):
    subprocess.run(["pdftoppm", "-r", str(dpi), "-f", str(page), "-l", str(page), "-png", "-gray", "-singlefile", pdf_path, prefix], check=True)
    img = cv2.imread(out_path, cv2.IMREAD_GRAYSCALE)
    keep_h = int(img.shape[0] * crop_fraction)
    cv2.imwrite(out_path, img[:keep_h, :])
  return out_path


def noise_area_threshold_for():
  """Pick the denoise area threshold for the active render resolution."""
  if ACTIVE_DPI >= 600:
    return NOISE_AREA_THRESHOLD_600DPI
  return NOISE_AREA_THRESHOLD_300DPI


def binarize(img):
  """Return an inverted binary image (ink=255) using Otsu thresholding."""
  _, binary = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
  return binary


def denoise_for_ocr(img_path, out_path=None):
  """Remove small isolated connected components (scan dirt) and write the cleaned image."""
  if out_path is None:
    out_path = img_path[:-4] + "_clean.png"
  if os.path.exists(out_path):
    return out_path
  img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
  threshold = noise_area_threshold_for()
  binary = binarize(img)
  count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
  small = np.zeros(count, dtype=bool)
  small[1:] = stats[1:, cv2.CC_STAT_AREA] < threshold
  mask = small[labels]
  cleaned = img.copy()
  cleaned[mask] = 255
  cv2.imwrite(out_path, cleaned)
  return out_path


def run_tesseract(img_path, args, lang="heb"):
  """Run tesseract on an image with extra arguments and return its stdout as text."""
  cmd = ["tesseract", img_path, "stdout", "-l", lang] + args
  env = dict(os.environ)
  env["OMP_THREAD_LIMIT"] = str(TESSERACT_OMP_THREADS)
  result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
  return result.stdout


def ocr_tsv(img_path, psm=4, lang="heb", denoise=True):
  """OCR an image (after denoising) and return word boxes with confidence from tesseract TSV output."""
  path = denoise_for_ocr(img_path) if denoise else img_path
  output = run_tesseract(path, ["--psm", str(psm), "tsv"], lang)
  words = []
  reader = csv.reader(output.splitlines(), delimiter="\t", quoting=csv.QUOTE_NONE)
  header = None
  for row in reader:
    if header is None:
      header = row
      continue
    if len(row) < 12:
      continue
    rec = dict(zip(header, row))
    if rec["level"] != "5":
      continue
    text = rec["text"].strip()
    if not text:
      continue
    words.append({
      "text": text,
      "left": int(rec["left"]),
      "top": int(rec["top"]),
      "width": int(rec["width"]),
      "height": int(rec["height"]),
      "conf": float(rec["conf"]),
      "block": int(rec["block_num"]),
      "par": int(rec["par_num"]),
      "line": int(rec["line_num"]),
    })
  return words


def ocr_letter_heights(img_path, psm=4, lang="heb", denoise=True):
  """Run tesseract makebox and return per-character boxes in top-left image coordinates."""
  path = denoise_for_ocr(img_path) if denoise else img_path
  img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
  img_h = img.shape[0]
  output = run_tesseract(path, ["--psm", str(psm), "makebox"], lang)
  chars = []
  for line in output.splitlines():
    parts = line.split(" ")
    if len(parts) < 6:
      continue
    ch = parts[0]
    try:
      left = int(parts[1])
      bottom = int(parts[2])
      right = int(parts[3])
      top = int(parts[4])
    except ValueError:
      continue
    chars.append({
      "char": ch,
      "left": left,
      "right": right,
      "top": img_h - top,
      "bottom": img_h - bottom,
      "height": top - bottom,
    })
  return chars


def extract_movement(body):
  """Extract the settling movement name from an entry body, or None."""
  m = MOVEMENT_RE.search(body)
  if not m:
    return None
  return m.group(1).strip()


def normalize_coords(first, second):
  """Join the two halves of a grid reference with a dot; split a single 6- or 8-digit run in half."""
  if second:
    return "%s.%s" % (first, second)
  if len(first) in (6, 8):
    half = len(first) // 2
    return "%s.%s" % (first[:half], first[half:])
  return first


def coords_well_formed(coords):
  """True when a coordinate string has the expected nnn.nnn or nnnn.nnnn shape."""
  return bool(coords) and COORDS_OK_RE.match(coords) is not None


def extract_coords(body):
  """Extract the coordinate string following a grid-reference marker from an entry body, or None."""
  m = COORDS_RE.search(body)
  if not m:
    return None
  return normalize_coords(m.group(1), m.group(2))


def word_center(word):
  """Vertical center of a word box."""
  return word["top"] + word["height"] / 2.0


def median_or_none(values):
  """Median of a non-empty list, or None."""
  if not values:
    return None
  return statistics.median(values)
