#!/usr/bin/env python3
"""Main parser for the 1969-1992 two-column Yalkut HaPirsumim format (parse_page_v2)."""
import difflib
import os
import re
import statistics
from ocr_parser import (cv2, np, render_page_png, denoise_for_ocr, binarize, ocr_tsv, ocr_letter_heights,
  extract_movement, extract_coords, coords_well_formed, strip_niqqud, word_center, median_or_none,
  CATEGORY_KEYWORDS, CATEGORY_HEADER_PHRASES, PREFIX_WORDS)

HEADER_MIN_H = 60
FUZZY_MIN_RATIO = 0.65
GUTTER_COMPONENT_MIN_H = 150
GUTTER_BAND = (0.40, 0.60)
GUTTER_MARGIN = 12
SLICE_MARGIN = 10
MIN_WORD_H = 25
MIN_SYMBOL_W = 20
ISOLATION_FRACTION = 0.40
ISOLATION_MAX_CHARS = 2
REFERENCE_TYPICAL_H_300DPI = 20.0
CENTER_THRESHOLD_300DPI = 20.0
MERGE_GAP_300DPI = 3.0
HEIGHT_CLIP_FACTOR = 1.2
NAME_MAX_WORDS = 5
SELF_CONTAINED_H_FACTOR = 0.55
GAP_NAME_MIN = 40
GAP_NAME_TO_BODY_MAX = 120
GAP_ENTRY_TRANSITION_MIN = 120
STRONG_NAME_MARGIN = 8
NEAR_MISS_FACTOR = 0.75
NEAR_MISS_MAX_WORDS = 4
RESCUE_MAX_WORDS = 4
NAME_GAP_FACTOR = 1.9
AUDIT_MIN_H = 40
AUDIT_MIN_W = 40
CALIB_RANGE = (8, 70)
SUBHEADER_MAP_RE = re.compile(r"מ[פש]\S{0,3}\s+\S{0,4}\s+\S{0,3}\d|\d:\d{2,3},?\d{3}")
COORD_MARKER = r"(?:[נגב][\"*׳״'”“]?צ|\S{0,2}[\"*׳״'”“]\S{0,2})"
SELF_CONTAINED_RE = re.compile(r"^(?P<name>.+?)\s+(?P<rest>" + COORD_MARKER + r"\S*\s*[.,:]?\s*\d{2,4}[.,;\u2013-]{1,2}\s?\d{2,4}.*)$")
COORDS_FIRST_RE = re.compile(r"^(?P<rest>\S{0,2}[\"*׳״'”“]?צ\S*\s*[.,:]?\s*[\d.,;\u2013-]*\d[\d.,;\u2013-]*)\s+(?P<name>.+)$")
CATEGORY_PREFIX_ONLY = {"שמורת"}
MERGE_OVERLAP_FRACTION = 0.5
FRAGMENT_H_FACTOR = 0.6
HEBREW_LETTER_RE = re.compile(r"[א-ת]")
DESCRIPTION_OPENER_RE = re.compile(r"^\s*\S{0,2}[\"*׳״'”“]?צ\s*[.,:]?\s*\d")
LEADING_NUMBER_RE = re.compile(r"^[\d\s.\-:;,()|]*")
PENDING_CATEGORY = "__PENDING__"
STATE_FORCE_NAME = "FORCE_NAME"
STATE_FORCE_BODY = "FORCE_BODY"
STATE_CHECK = "CHECK"


def normalize_for_match(text):
  """Lower-noise form of a line for keyword matching: no niqqud, no leading numbering."""
  return LEADING_NUMBER_RE.sub("", strip_niqqud(text)).strip()


def detect_header_category_v2(text):
  """Strict category detection: a known header keyword must appear verbatim in the text."""
  clean = normalize_for_match(text)
  for category, keywords in CATEGORY_KEYWORDS:
    for kw in keywords:
      if kw in clean:
        return category
  return None


def fuzzy_detect_header_category(text, min_ratio=FUZZY_MIN_RATIO):
  """Fallback category detection by text similarity against the expected header phrases."""
  clean = normalize_for_match(text)
  best_ratio = 0.0
  best_category = None
  for category, phrase in CATEGORY_HEADER_PHRASES:
    ratio = difflib.SequenceMatcher(None, clean, phrase).ratio()
    if ratio > best_ratio:
      best_ratio = ratio
      best_category = category
  if best_ratio >= min_ratio:
    return best_category, best_ratio
  return None, best_ratio


def is_prefix_word(text):
  """True for administrative prefix tokens (מ"א / ד"נ) that must not enter letter-height medians."""
  bare = strip_niqqud(text).strip(".,:;")
  return bare in PREFIX_WORDS


def chars_in_word(chars, word):
  """Character boxes whose center falls inside the word box."""
  x0 = word["left"]
  x1 = word["left"] + word["width"]
  y0 = word["top"]
  y1 = word["top"] + word["height"]
  found = []
  for ch in chars:
    cx = (ch["left"] + ch["right"]) / 2.0
    cy = (ch["top"] + ch["bottom"]) / 2.0
    if x0 <= cx <= x1 and y0 <= cy <= y1:
      found.append(ch)
  return found


def filter_isolated_noise_words(words, col_width):
  """Drop tiny words and words far from every Y-overlapping neighbour (scan dirt read as text)."""
  tall = [w for w in words if w["height"] >= MIN_WORD_H]
  tall = [w for w in tall if w["width"] >= MIN_SYMBOL_W or HEBREW_LETTER_RE.search(w["text"])]
  kept = []
  for w in tall:
    nearest = None
    for o in tall:
      if o is w:
        continue
      if o["top"] + o["height"] <= w["top"] or o["top"] >= w["top"] + w["height"]:
        continue
      d = max(o["left"] - (w["left"] + w["width"]), w["left"] - (o["left"] + o["width"]), 0)
      if nearest is None or d < nearest:
        nearest = d
    short = len(strip_niqqud(w["text"]).strip(".,:;'\"*|-/\\")) <= ISOLATION_MAX_CHARS
    if short and nearest is not None and nearest > ISOLATION_FRACTION * col_width:
      continue
    kept.append(w)
  return kept


def finalize_line(line_words, chars):
  """Build a line record from its words: geometry, RTL text, letter-based median height."""
  ordered = sorted(line_words, key=lambda w: -w["left"])
  top = int(min(w.get("top_core", w["top"]) for w in ordered))
  bottom = int(round(max(w.get("bottom_core", w["top"] + w["height"]) for w in ordered)))
  letter_heights = []
  for w in ordered:
    if is_prefix_word(w["text"]):
      continue
    letter_heights.extend(ch["height"] for ch in chars_in_word(chars, w))
  median_h = median_or_none(letter_heights)
  if median_h is None:
    median_h = statistics.median([w["height"] for w in ordered])
  return {
    "words": ordered,
    "text": " ".join(w["text"] for w in ordered),
    "top": top,
    "bottom": bottom,
    "left": min(w["left"] for w in ordered),
    "right": max(w["left"] + w["width"] for w in ordered),
    "median_h": median_h,
  }


def should_merge_lines(prev, line, merge_gap, typical_h):
  """Merge when the lines' vertical extents really overlap, or when a tiny fragment (niqqud/noise) touches a line."""
  overlap = min(prev["bottom"], line["bottom"]) - max(prev["top"], line["top"])
  min_h = min(prev["bottom"] - prev["top"], line["bottom"] - line["top"])
  if overlap >= MERGE_OVERLAP_FRACTION * min_h:
    return True
  return line["top"] - prev["bottom"] < merge_gap and min_h < FRAGMENT_H_FACTOR * typical_h


def group_words_to_lines(words, chars):
  """Group words into physical lines by vertical center, then merge Y-overlapping fragments."""
  if not words:
    return []
  typical_h = statistics.median([w["height"] for w in words])
  scale = typical_h / REFERENCE_TYPICAL_H_300DPI
  center_threshold = CENTER_THRESHOLD_300DPI * scale
  merge_gap = MERGE_GAP_300DPI * scale
  clip = HEIGHT_CLIP_FACTOR * typical_h
  for w in words:
    core_chars = chars_in_word(chars, w)
    if len(core_chars) >= 2:
      w["top_core"] = statistics.median([c["top"] for c in core_chars])
      w["bottom_core"] = statistics.median([c["bottom"] for c in core_chars])
    else:
      w["top_core"] = w["top"]
      w["bottom_core"] = w["top"] + min(w["height"], clip)
    w["center"] = (w["top_core"] + w["bottom_core"]) / 2.0
  ordered = sorted(words, key=lambda w: w["center"])
  groups = []
  current = [ordered[0]]
  current_sum = ordered[0]["center"]
  for w in ordered[1:]:
    mean_center = current_sum / len(current)
    if abs(w["center"] - mean_center) <= center_threshold:
      current.append(w)
      current_sum += w["center"]
    else:
      groups.append(current)
      current = [w]
      current_sum = w["center"]
  groups.append(current)
  lines = [finalize_line(g, chars) for g in groups]
  lines.sort(key=lambda l: l["top"])
  merged = []
  for line in lines:
    if merged and should_merge_lines(merged[-1], line, merge_gap, typical_h):
      prev = merged.pop()
      joined = prev["words"] + line["words"]
      rec = finalize_line(joined, chars)
      rec["text"] = " ".join(w["text"] for w in joined)
      rec["words"] = joined
      merged.append(rec)
    else:
      merged.append(line)
  return merged


def find_gutter_line_components(img):
  """X position of the printed column separator: tall connected components in the central band."""
  h = img.shape[0]
  w = img.shape[1]
  x0 = int(w * GUTTER_BAND[0])
  x1 = int(w * GUTTER_BAND[1])
  band = binarize(img[:, x0:x1])
  count, _, stats, centroids = cv2.connectedComponentsWithStats(band, connectivity=8)
  total = 0.0
  weighted = 0.0
  coverage = 0
  for i in range(1, count):
    ch = stats[i, cv2.CC_STAT_HEIGHT]
    if ch < GUTTER_COMPONENT_MIN_H:
      continue
    total += ch
    weighted += ch * centroids[i][0]
    coverage += ch
  if total == 0:
    return None, 0.0
  return x0 + weighted / total, coverage / float(h)


def detect_headers(lines, page_width):
  """Section headers on a full page: tall lines whose text names one of the categories."""
  headers = []
  for line in lines:
    if line["median_h"] < HEADER_MIN_H:
      continue
    strict = detect_header_category_v2(line["text"])
    if strict:
      headers.append({"top": line["top"], "bottom": line["bottom"], "category": strict, "text": line["text"], "fuzzy": False})
      continue
    fuzzy, ratio = fuzzy_detect_header_category(line["text"])
    if fuzzy:
      headers.append({"top": line["top"], "bottom": line["bottom"], "category": fuzzy, "text": line["text"], "fuzzy": True, "ratio": ratio})
  headers.sort(key=lambda h: h["top"])
  return headers


def build_slices(headers, page_height, carried_category):
  """Horizontal slices between headers; the first slice inherits the category carried from the previous page."""
  slices = []
  prev_bottom = 0
  category = carried_category
  for h in headers:
    slices.append({"top": prev_bottom, "bottom": h["top"], "category": category, "header": None})
    prev_bottom = h["bottom"] + SLICE_MARGIN
    category = h["category"]
  slices.append({"top": prev_bottom, "bottom": page_height, "category": category, "header": None})
  return [s for s in slices if s["bottom"] - s["top"] > SLICE_MARGIN]


def crop_image(img_path, out_path, y0, y1, x0, x1):
  """Write a sub-image crop and return its path (cached when it already exists)."""
  if not os.path.exists(out_path):
    img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
    cv2.imwrite(out_path, img[y0:y1, x0:x1])
  return out_path


def ocr_column(img_path, out_path, y0, y1, x0, x1):
  """OCR one column crop; returns its lines and the words the noise filter discarded, in page coordinates."""
  crop_image(img_path, out_path, y0, y1, x0, x1)
  words = ocr_tsv(out_path)
  chars = ocr_letter_heights(out_path)
  kept = filter_isolated_noise_words(words, x1 - x0)
  kept_ids = set(id(w) for w in kept)
  discarded = [w for w in words if id(w) not in kept_ids]
  lines = group_words_to_lines(kept, chars)
  for line in lines:
    line["top"] += y0
    line["bottom"] += y0
    for w in line["words"]:
      w["top"] += y0
      w["left"] += x0
  for w in discarded:
    w["top"] += y0
    w["left"] += x0
  return lines, discarded


def check_unrecognized_text(lines, discarded, page, column):
  """Flag text the OCR read but the parser never used: filtered-out words, and lines no entry consumed."""
  findings = []
  for w in discarded:
    if w["height"] >= AUDIT_MIN_H and w["width"] >= AUDIT_MIN_W:
      findings.append({"page": page, "column": column, "type": "unrecognized-text",
        "text": "discarded as noise at y=%d: %r (h=%d w=%d conf=%.0f)" % (w["top"], w["text"], w["height"], w["width"], w["conf"])})
  for line in lines:
    if not line.get("used") and line["median_h"] >= AUDIT_MIN_H:
      findings.append({"page": page, "column": column, "type": "unrecognized-text",
        "text": "line used by no entry at y=%d: %r (h=%.0f)" % (line["top"], line["text"][:60], line["median_h"])})
  return findings


def is_category_prefix_line(text):
  """True for a lone category prefix word such as 'שמורת-' printed once above a column."""
  return strip_niqqud(text).strip("-.:, ") in CATEGORY_PREFIX_ONLY


def is_map_line(text):
  """True for the 'מפה מס' X' sub-header lines that reset the entry sequence."""
  return SUBHEADER_MAP_RE.search(strip_niqqud(text)) is not None


def split_self_contained_entry(line, name_threshold):
  """Split a 'name + grid reference + coordinates' single-line entry into (name, body), or None."""
  if line["median_h"] < SELF_CONTAINED_H_FACTOR * name_threshold:
    return None
  clean = strip_niqqud(line["text"])
  raw = line["text"].split()
  m = SELF_CONTAINED_RE.match(clean)
  if m and not re.search(r"\d", m.group("name")) and not m.group("name").endswith("."):
    name_words = len(m.group("name").split())
    if 0 < name_words <= NAME_MAX_WORDS:
      return " ".join(raw[:name_words]), " ".join(raw[name_words:])
  m = COORDS_FIRST_RE.match(clean)
  if m and not re.search(r"\d", m.group("name")) and not m.group("name").endswith("."):
    rest_words = len(m.group("rest").split())
    name_words = len(raw) - rest_words
    if 0 < name_words <= NAME_MAX_WORDS:
      return " ".join(raw[rest_words:]), " ".join(raw[:rest_words])
  return None


def continuation_placeholder(page, category, column):
  """Open-entry stand-in so a page parsed independently treats its opening lines as a continuation."""
  return {"name": None, "body_lines": [], "words": [], "page": page, "category": category, "column": column, "top": 0, "bottom": 0, "name_h": 0.0}


def merge_fragment(entry, fragment):
  """Fold a page's leading continuation fragment into the entry left open by the previous page."""
  entry["body_lines"].extend(fragment["body_lines"])
  entry["words"].extend(fragment["words"])
  return entry


def new_entry(name, page, category, column, line, after_map=False):
  """Create an entry record opened by a name line."""
  return {
    "after_map": after_map,
    "name": name,
    "body_lines": [],
    "words": list(line["words"]),
    "page": page,
    "category": category,
    "column": column,
    "top": line["top"],
    "bottom": line["bottom"],
    "name_h": line["median_h"],
  }


def append_body(entry, line, text=None):
  """Append a description line to an open entry."""
  entry["body_lines"].append(text if text is not None else line["text"])
  entry["words"].extend(line["words"])
  entry["bottom"] = max(entry.get("bottom", line["bottom"]), line["bottom"])


def lines_to_entries_v2(lines, category, name_threshold, open_entry, page, column):
  """Gap-driven state machine turning column lines into entries; returns (entries, warnings, still_open, names_opened)."""
  entries = []
  warnings = []
  names_opened = 0
  after_map = False
  state = STATE_FORCE_NAME
  current = open_entry
  if current is not None and lines and lines[0]["median_h"] < name_threshold:
    state = STATE_CHECK
  elif current is not None:
    entries.append(current)
    current = None
  for i, line in enumerate(lines):
    gap_before = line["top"] - lines[i - 1]["bottom"] if i > 0 else None
    gap_after = lines[i + 1]["top"] - line["bottom"] if i + 1 < len(lines) else None
    next_line = lines[i + 1] if i + 1 < len(lines) else None
    if is_category_prefix_line(line["text"]):
      line["used"] = "prefix"
      continue
    if is_map_line(line["text"]):
      if current is not None:
        entries.append(current)
        current = None
      state = STATE_FORCE_NAME
      after_map = True
      line["used"] = "map"
      continue
    split_allowed = state == STATE_FORCE_NAME or (state == STATE_CHECK and (i == 0 or gap_before > GAP_NAME_MIN or opens_description(line)))
    split = split_self_contained_entry(line, name_threshold) if split_allowed else None
    if split is not None:
      if current is not None:
        entries.append(current)
      current = new_entry(split[0], page, category, column, line, after_map)
      after_map = False
      names_opened += 1
      line["used"] = "name"
      append_body(current, line, split[1])
      state = STATE_CHECK
      continue
    if state == STATE_FORCE_NAME:
      if len(HEBREW_LETTER_RE.findall(line["text"])) < 2 and not opens_description(next_line):
        continue
      if current is not None:
        entries.append(current)
      current = new_entry(line["text"], page, category, column, line, after_map)
      after_map = False
      names_opened += 1
      line["used"] = "name"
      state = STATE_FORCE_BODY
      continue
    if state == STATE_FORCE_BODY:
      append_body(current, line)
      line["used"] = "body"
      state = STATE_CHECK
      continue
    if is_name_candidate(line, gap_before, gap_after, name_threshold, next_line):
      if current is not None:
        entries.append(current)
      current = new_entry(line["text"], page, category, column, line, after_map)
      after_map = False
      names_opened += 1
      line["used"] = "name"
      state = STATE_FORCE_BODY
    else:
      if current is None:
        warnings.append({"page": page, "column": column, "type": "body-without-name", "text": line["text"]})
        continue
      if gap_before is not None and gap_before >= GAP_ENTRY_TRANSITION_MIN:
        warnings.append({"page": page, "column": column, "type": "large-gap-continuation", "text": line["text"]})
      append_body(current, line)
      line["used"] = "body"
      state = STATE_CHECK
  return entries, warnings, current, names_opened


def opens_description(line):
  """True when a line starts with a grid-reference marker, which only a new entry's description does."""
  return line is not None and DESCRIPTION_OPENER_RE.match(strip_niqqud(line["text"])) is not None


def is_garbled_name(line, gap_before, next_line):
  """Rescue a name the OCR mangled or that opens a column: a short line whose next line opens a description."""
  if len(line["words"]) > RESCUE_MAX_WORDS or not opens_description(next_line):
    return False
  return gap_before is None or gap_before >= GAP_ENTRY_TRANSITION_MIN


def is_name_candidate(line, gap_before, gap_after, name_threshold, next_line=None):
  """Decide in CHECK state whether a line opens a new entry: letter height plus vertical-gap evidence."""
  if is_garbled_name(line, gap_before, next_line):
    return True
  if gap_before is None or gap_before <= GAP_NAME_MIN:
    return False
  if len(HEBREW_LETTER_RE.findall(line["text"])) < 2:
    return False
  h = line["median_h"]
  strong = h >= name_threshold + STRONG_NAME_MARGIN
  sentence_end = line["text"].rstrip().endswith(".")
  if h >= name_threshold:
    return strong or not sentence_end
  after_ok = gap_after is None or gap_after <= GAP_NAME_TO_BODY_MAX
  near_miss = h >= NEAR_MISS_FACTOR * name_threshold and len(line["words"]) <= NEAR_MISS_MAX_WORDS
  return near_miss and gap_before >= GAP_ENTRY_TRANSITION_MIN and after_ok and not sentence_end


def check_name_gaps(entries, factor=NAME_GAP_FACTOR):
  """Flag unusually large vertical distances between consecutive names in one column, a skipped-name signal."""
  groups = {}
  for e in entries:
    groups.setdefault((e["page"], e["column"], e["category"]), []).append(e)
  spans = []
  for group in groups.values():
    for a, b in zip(group, group[1:]):
      if not b.get("after_map"):
        spans.append(b["top"] - a["top"])
  if not spans:
    return []
  typical = statistics.median(spans)
  warnings = []
  for group in groups.values():
    for a, b in zip(group, group[1:]):
      span = b["top"] - a["top"]
      if not b.get("after_map") and span > factor * typical:
        warnings.append({"page": a["page"], "column": a["column"], "type": "name-gap-suspicious",
          "text": "%dpx between '%s' and '%s' (typical %d)" % (span, a["name"], b["name"], typical)})
  return warnings


def check_coords_format(entries):
  """Flag entries whose extracted grid reference is not in the expected nnn.nnn or nnnn.nnnn shape."""
  return [{"page": e["page"], "column": e["column"], "type": "coords-format",
    "text": "%s: %s" % (e["name"], e["coords"])} for e in entries if e["coords"] and not coords_well_formed(e["coords"])]


def finish_entry(entry):
  """Compute derived fields (body text, coords, movement, OCR scores) on a closed entry."""
  body = " ".join(entry["body_lines"])
  confs = [w["conf"] for w in entry["words"] if w["conf"] >= 0]
  lowest = min(entry["words"], key=lambda w: w["conf"]) if entry["words"] else None
  entry["body"] = body
  entry["coords"] = extract_coords(body) or extract_coords(entry["name"])
  entry["movement"] = extract_movement(body)
  entry["ocr_min"] = min(confs) if confs else None
  entry["ocr_avg"] = sum(confs) / len(confs) if confs else None
  entry["ocr_lowest_word"] = lowest["text"] if lowest else None
  entry["word_count"] = len(entry["words"])
  entry.pop("words", None)
  entry.pop("body_lines", None)
  return entry


def page_lines_full(img_path):
  """Full-page lines (used only for header detection)."""
  words = ocr_tsv(img_path)
  chars = ocr_letter_heights(img_path)
  return group_words_to_lines(words, chars)


def parse_page_v2(pdf_path, page, name_threshold, work_dir, carried_category=None, open_entry=None):
  """Parse one page; returns dict with entries, warnings, headers, still-open entry and current category."""
  png_dir = os.path.join(work_dir, "png")
  img_path = render_page_png(pdf_path, page, png_dir)
  img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
  page_h = img.shape[0]
  page_w = img.shape[1]
  if page_w > page_h:
    warning = {"page": page, "column": "-", "type": "landscape-page-skipped", "text": "%dx%d" % (page_w, page_h)}
    return {"page": page, "entries": [], "leading_fragment": open_entry, "warnings": [warning], "headers": [], "open_entry": None, "category": carried_category}
  full_lines = page_lines_full(img_path)
  headers = detect_headers(full_lines, page_w)
  slices = build_slices(headers, page_h, carried_category)
  raw_entries = []
  warnings = []
  current = open_entry
  category = carried_category
  for si, s in enumerate(slices):
    if si > 0 and current is not None:
      raw_entries.append(current)
      current = None
    if s["category"] is None:
      continue
    category = s["category"]
    slice_img = img[s["top"]:s["bottom"], :]
    gutter_x, coverage = find_gutter_line_components(slice_img)
    if gutter_x is None:
      gutter_x = page_w / 2.0
      warnings.append({"page": page, "column": "-", "type": "gutter-fallback", "text": "slice %d" % si})
    gx = int(round(gutter_x))
    columns = [("right", gx + GUTTER_MARGIN, page_w), ("left", 0, gx - GUTTER_MARGIN)]
    for col_name, x0, x1 in columns:
      crop_path = os.path.join(png_dir, "page_%03d_s%d_%s.png" % (page, si, col_name))
      lines, discarded = ocr_column(img_path, crop_path, s["top"], s["bottom"], x0, x1)
      col_entries, col_warnings, current, names_opened = lines_to_entries_v2(lines, category, name_threshold, current, page, col_name)
      raw_entries.extend(col_entries)
      warnings.extend(col_warnings)
      openers = sum(1 for l in lines if opens_description(l))
      if openers > names_opened:
        warnings.append({"page": page, "column": col_name, "type": "possible-skipped-name",
          "text": "%d description openers but %d names in category %s" % (openers, names_opened, category)})
      warnings.extend(check_unrecognized_text(lines, discarded, page, col_name))
  leading = None
  if raw_entries and raw_entries[0]["name"] is None:
    leading = raw_entries.pop(0)
  elif current is not None and current["name"] is None:
    leading = current
    current = None
  return {
    "page": page,
    "entries": [finish_entry(e) for e in raw_entries],
    "leading_fragment": leading,
    "warnings": warnings,
    "headers": headers,
    "open_entry": current,
    "category": category,
  }


def collect_line_heights(pdf_path, page, work_dir):
  """Letter-based median heights of all column lines on a page (for threshold calibration)."""
  png_dir = os.path.join(work_dir, "png")
  img_path = render_page_png(pdf_path, page, png_dir)
  img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
  page_h = img.shape[0]
  page_w = img.shape[1]
  headers = detect_headers(page_lines_full(img_path), page_w)
  slices = build_slices(headers, page_h, "calib")
  heights = []
  for si, s in enumerate(slices):
    gutter_x, _ = find_gutter_line_components(img[s["top"]:s["bottom"], :])
    gx = int(round(gutter_x if gutter_x is not None else page_w / 2.0))
    for col_name, x0, x1 in [("right", gx + GUTTER_MARGIN, page_w), ("left", 0, gx - GUTTER_MARGIN)]:
      crop_path = os.path.join(png_dir, "page_%03d_s%d_%s.png" % (page, si, col_name))
      lines, _ = ocr_column(img_path, crop_path, s["top"], s["bottom"], x0, x1)
      heights.extend(l["median_h"] for l in lines)
  return heights


def calibrate_tier_threshold(heights):
  """Center of the largest empty gap in the sorted height distribution within the calibration range."""
  values = sorted(set(round(h, 1) for h in heights if CALIB_RANGE[0] <= h <= CALIB_RANGE[1]))
  if len(values) < 2:
    return None
  best_gap = 0.0
  best_center = None
  for a, b in zip(values, values[1:]):
    if b - a > best_gap:
      best_gap = b - a
      best_center = (a + b) / 2.0
  return best_center


def calibrate_document_threshold(pdf_path, pages, work_dir):
  """Calibrate the name/description letter-height threshold once per booklet from sample pages."""
  heights = []
  for page in pages:
    heights.extend(collect_line_heights(pdf_path, page, work_dir))
  return calibrate_tier_threshold(heights), heights
