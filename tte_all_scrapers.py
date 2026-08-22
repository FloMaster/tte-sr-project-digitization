#!/usr/bin/env python3
"""
TTE Echocardiography COMPLETE Code Scraper (v4.0)
==================================================
Downloads/scrapes all four coding schemes:
  1. LOINC (LN)   - official LOINC database download API (requires account)
                    OR a locally-downloaded Loinc_2.8x.zip via --local-loinc-zip
  2. SNOMED (SRT) - DICOM PS3.16 echo Context Groups (CIDs 12234-12251)
  3. DCM          - DICOM PS3.16 echo Context Groups (CIDs)
  4. UCUM         - official ucum-essence.xml standard

Outputs:
  tte_loinc.json / tte_snomed_srt.json / tte_dcm.json / ucum_units.json
  tte_master_table.csv / tte_master_table.xlsx

Usage:
  python tte_all_scrapers.py -u USER -p PASS --excel "ranges.xlsx"
  python tte_all_scrapers.py --local-loinc-zip "Loinc_2.83.zip" --excel "ranges.xlsx"
  python tte_all_scrapers.py --offline --local-loinc-zip "x.zip" --local-ucum ucum.xml
"""
import requests, json, zipfile, base64, argparse, re, sys
from pathlib import Path
from typing import List, Dict, Optional

try:
    from bs4 import BeautifulSoup
    import pandas as pd
    from lxml import etree
    import openpyxl
except ImportError as e:
    print(f"Missing: {e}\nRun: pip install requests beautifulsoup4 pandas lxml openpyxl")
    sys.exit(1)

# ---------------- Config ----------------
CID_BASE = "https://dicom.nema.org/medical/dicom/current/output/chtml/part16/sect_CID_{}.html"
CID_LIST = [12234, 12235, 12237, 12238, 12239, 12240,
            12241, 12242, 12243, 12244, 12245, 12251]
UCUM_XML_URL = "https://raw.githubusercontent.com/ucum-org/ucum/main/ucum-essence.xml"
LOINC_DOWNLOAD = "https://loinc.regenstrief.org/api/v1/Loinc/Download"
HEADERS = {"User-Agent": "Mozilla/5.0 (TTE-AllScraper/1.0)"}
NORM = {"SCT": "SRT", "SNM3": "SRT"}

# ======================================================================
# 1. UCUM
# ======================================================================
def download_ucum(out="ucum-essence.xml") -> Optional[Path]:
    print("Downloading UCUM standard...")
    r = requests.get(UCUM_XML_URL, headers=HEADERS, timeout=60)
    if r.status_code == 200:
        Path(out).write_text(r.text, encoding="utf-8")
        print(f"  ✓ UCUM saved ({len(r.text)//1024} KB)")
        return Path(out)
    print(f"  ✗ UCUM download HTTP {r.status_code}")
    return None

def parse_ucum(path: Optional[Path]) -> List[Dict]:
    units = []
    if not path or not path.exists():
        print("  ⚠ No UCUM file - unit mapping will use fallback only")
        return units
    tree = etree.parse(str(path))
    ns = "{http://unitsofmeasure.org/ucum-essence}"
    for u in tree.getroot().iter(ns + "unit"):
        code = (u.get("Code") or "").strip()
        if not code:
            continue
        names = [n.text.strip() for n in u.findall(ns + "name") if n.text and n.text.strip()]
        units.append({
            "ucum_code": code,
            "ucum_print_symbol": u.get("printSymbol") or code,
            "ucum_names": names,
            "ucum_common_name": names[0] if names else "",
            "ucum_dimension": u.get("dim"),
            "ucum_class": u.get("class"),
        })
    print(f"  ✓ {len(units)} UCUM units parsed")
    return units

# ======================================================================
# 2. DICOM CIDs (SNOMED + DCM)
# ======================================================================
def fetch(url: str) -> Optional[str]:
    import time
    r = requests.get(url, headers=HEADERS, timeout=30)
    time.sleep(1)
    return r.text if r.status_code == 200 else None

def parse_cid(html: str, cid: int) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
            if len(cells) < 3:
                continue
            scheme = NORM.get(cells[0].upper(), cells[0].upper())
            if scheme not in ("SRT", "DCM", "LN"):
                continue
            row = {"cid_source": f"CID_{cid}", "coding_scheme": scheme,
                   "code_value": cells[1], "code_meaning": cells[2], "ucum_unit": None}
            if len(cells) > 3 and cells[3] and not cells[3].lower().startswith(("note", "retired")):
                row["ucum_unit"] = cells[3]
            rows.append(row)
    return rows

def scrape_cids(offline=False) -> List[Dict]:
    print("\n" + "=" * 70)
    print("SCRAPING DICOM ECHO CIDs (SNOMED + DCM)")
    print("=" * 70)
    all_rows = []
    for cid in CID_LIST:
        if offline:
            continue
        html = fetch(CID_BASE.format(cid))
        if not html:
            print(f"  CID_{cid} !! failed")
            continue
        rows = parse_cid(html, cid)
        print(f"  CID_{cid} -> {len(rows)} rows")
        all_rows += rows
    srt = [r for r in all_rows if r["coding_scheme"] == "SRT"]
    dcm = [r for r in all_rows if r["coding_scheme"] == "DCM"]
    print(f"  SNOMED: {len(srt)} | DCM: {len(dcm)}")
    return all_rows

# ======================================================================
# 3. LOINC
# ======================================================================
def download_loinc_api(username: str, password: str) -> Optional[Path]:
    """Download via official API; extract the MAIN Loinc.csv (not PanelsAndForms)."""
    print("\n" + "=" * 70)
    print("DOWNLOADING LOINC DATABASE (official API)")
    print("=" * 70)
    cred = base64.b64encode(f"{username}:{password}".encode()).decode()
    headers = {"Authorization": f"Basic {cred}", "Accept": "*/*",
               "User-Agent": "TTE-AllScraper/1.0"}
    try:
        s = requests.Session(); s.headers.update(headers)
        r = s.get(LOINC_DOWNLOAD, timeout=300)
        if r.status_code in (401, 403):
            print(f"  ✗ LOINC rejected credentials (HTTP {r.status_code})")
            print("    ✓ Check username/password, OR")
            print("    ✓ Account may be web-UI-only; needs API enablement (contact LOINC).")
            return None
        if r.status_code != 200:
            print(f"  ✗ LOINC download HTTP {r.status_code}")
            return None
        zpath = Path("loinc_db.zip")
        zpath.write_bytes(r.content)
        print(f"  ✓ Downloaded {len(r.content)//(1024*1024)} MB to loinc_db.zip")
        return extract_main_loinc(zpath)
    except Exception as e:
        print(f"  ✗ LOINC API error: {e}")
        return None

def extract_main_loinc(zpath: Path) -> Optional[Path]:
    """Find and extract the MAIN Loinc.csv, skipping AccessoryFiles/PanelsAndForms."""
    with zipfile.ZipFile(zpath) as zp:
        names = zp.namelist()
        main = None
        for n in names:
            if n.lower().endswith("loinc.csv") and "accessoryfiles" not in n.lower():
                main = n
                break
        if main is None:
            print("  ✗ Main Loinc.csv not found in zip")
            return None
        print(f"  ✓ Found main table at: {main}")
        zp.extract(main, "loinc_db")
        return Path("loinc_db") / main

def parse_loinc_csv(path: Path) -> List[Dict]:
    """Robustly parse the main Loinc.csv (auto-detects tab OR comma delimiter)."""
    print(f"\nParsing LOINC: {path}")

    # ---- Auto-detect delimiter: sniff the first line ----
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        head = f.readline()
    sep = "\t" if head.count("\t") > head.count(",") else ","
    print(f"  Detected delimiter: {'TAB' if sep == chr(9) else 'COMMA'}")

    # ---- Read with the detected separator + python engine (handles quoting) ----
    df = pd.read_csv(path, sep=sep, dtype=str, engine="python",
                     quotechar='"', on_bad_lines="skip")
    print(f"  {len(df)} total LOINC rows")
    df.columns = [str(c).strip().strip('"').strip() for c in df.columns]
    print(f"  Columns ({len(df.columns)}): {list(df.columns)[:40]}")

    cols = {str(c).strip().upper(): c for c in df.columns}
    def pick(*names):
        for n in names:
            if n in cols:
                return cols[n]
        return None

    col_num    = pick("LOINC_NUM", "LOINC")
    col_lcn    = pick("LONG_COMMON_NAME")
    col_units  = pick("EXAMPLE_UCUM_UNITS", "EXAMPLE_UNITS", "UCUM_UNITS")
    col_short  = pick("SHORTNAME")
    col_status = pick("STATUS")
    col_comp   = pick("COMPONENT", "PART_NAME")
    col_sys    = pick("SYSTEM", "LPART_NAME")
    col_class  = pick("CLASS", "CLASS_TYPE")
    col_method = pick("METHOD_TYP", "METHOD")

    if col_num is None or col_lcn is None:
        print("  ✗ Required LOINC columns missing - cannot parse")
        return []

    # ---- Build combined free-text for fallback matching ----
    text_parts = [c for c in [col_lcn, col_comp, col_sys, col_method] if c]
    combined = df[text_parts[0]].astype(str)
    for c in text_parts[1:]:
        combined = combined + " " + df[c].astype(str)

    # ---- SYSTEM-based detection ----
    sys_val = df[col_sys].astype(str) if col_sys else combined
    system_mask = sys_val.str.contains(
        r"\bHeart\b|Left ventricle|Right ventricle|Left atrium|Right atrium|"
        r"Aortic valve|Mitral valve|Tricuspid valve|Pulmonary valve|"
        r"Thoracic aorta|Cardiovascular system|Heart.valve", na=False, regex=True)

    # ---- CLASS-based detection ----
    class_mask = pd.Series(False, index=df.index)
    if col_class:
        class_mask = df[col_class].astype(str).str.contains(
            r"\bCARD\.US\b|CARD\b|ECHOCARDIOGRAM|CARDIAC", na=False, regex=True)

    # ---- Free-text fallback ----
    text_mask = combined.str.contains(
        r"echocardiogram|echocardiography|\becho\b|cardi\w*|ventricular \w* "
        r"(dimension|thickness|volume|mass|ejection|fraction)|ejection fraction|"
        r"stroke volume|cardiac output|velocity time integral|valve gradient|"
        r"valve area|valve velocity", na=False, regex=True)

    mask = system_mask | class_mask | text_mask
    echo_df = df[mask]
    print(f"  system matches: {int(system_mask.sum())} | "
          f"class matches: {int(class_mask.sum())} | "
          f"free-text matches: {int(text_mask.sum())}")
    print(f"  TOTAL echo/cardiac rows: {len(echo_df)}")

    if len(echo_df) == 0:
        print("\n  ⚠ 0 matches — dumping samples for diagnosis:")
        for col in [col_sys, col_class, col_comp]:
            if col:
                vals = df[col].astype(str).dropna().unique()[:15]
                print(f"    [{col}] e.g. {list(vals)}")
        return []

    echo = []
    for _, r in echo_df.iterrows():
        echo.append({
            "coding_scheme": "LN",
            "code_value": str(r.get(col_num, "") or "").strip(),
            "code_meaning": str(r.get(col_lcn, "") or "").strip(),
            "shortname": str(r.get(col_short, "") or "").strip() if col_short else "",
            "status": str(r.get(col_status, "") or "").strip() if col_status else "",
            "component": str(r.get(col_comp, "") or "").strip() if col_comp else "",
            "system": str(r.get(col_sys, "") or "").strip() if col_sys else "",
            "class": str(r.get(col_class, "") or "").strip() if col_class else "",
            "unit_ucum": str(r.get(col_units, "") or "").strip() if col_units else "",
        })
    print(f"  ✓ {len(echo)} echo-related LOINC codes extracted")
    return echo

# ======================================================================
# 4. Merge & save
# ======================================================================
COMMON = {"cm": "cm", "mm": "mm", "m": "m", "m/s": "m/s", "cm/s": "cm/s",
          "mmHg": "mm[Hg]", "mmhg": "mm[Hg]", "mL": "mL", "ml": "mL",
          "cm3": "cm3", "g": "g", "g/m2": "g/m2", "g/m²": "g/m2",
          "mL/m2": "mL/m2", "ml/m2": "mL/m2", "bpm": "{beats}/min",
          "s": "s", "ms": "ms", "sec": "s", "deg": "deg", "°": "deg",
          "cm2": "cm2", "%": "%", "ratio": "1", "1/min": "1/min", "/min": "1/min"}

def map_ucum(u, ucum_units):
    if not u:
        return None
    u = str(u).strip()
    for uu in ucum_units:
        if uu["ucum_code"] == u or uu["ucum_print_symbol"] == u or \
           any(n.lower() == u.lower() for n in uu.get("ucum_names", [])):
            return uu["ucum_code"]
    return COMMON.get(u, COMMON.get(u.lower()))

def save(echo_rows, loinc_rows, ucum_units, excel_path=None):
    table = []
    def push(scheme, value, name, unit, view, src):
        table.append({"Coding_Scheme": scheme, "Code_Value": value, "Full_Name": name,
                      "Shortcode": value, "Viewport": view, "Unit": unit,
                      "UCUM_Unit": map_ucum(unit, ucum_units), "CID_Source": src})

    # SNOMED + DCM from CIDs
    for r in echo_rows:
        push(r["coding_scheme"], r["code_value"], r["code_meaning"],
             r.get("ucum_unit"), r["cid_source"], r["cid_source"])
    # LOINC from database
    for r in loinc_rows:
        push("LN", r["code_value"], r["code_meaning"],
             r.get("unit_ucum"), "", "LOINC_db")

    # Merge viewport / normal ranges from the professor's Excel
    if excel_path and Path(excel_path).exists():
        print(f"\nMerging Excel: {excel_path}")
        xl = pd.read_excel(excel_path, header=2)
        xl.columns = [str(c).strip() for c in xl.columns]
        matched = 0
        for row in table:
            nm = (row["Full_Name"] or "").lower()
            for _, er in xl.iterrows():
                en = str(er.get("Name", "")).lower()
                if nm and en and (nm in en or en in nm):
                    row["Viewport"] = er.get("Viewport", row["Viewport"])
                    row["Unit"] = er.get("unit", row["Unit"])
                    row["UCUM_Unit"] = map_ucum(row["Unit"], ucum_units)
                    for col in xl.columns:
                        if any(k in col.lower() for k in ("normal", "range", "severity", "male", "female")):
                            val = er[col]
                            if val is not None and not (isinstance(val, float) and val != val):
                                row[col] = val
                    row["Shortcode"] = er.get("Abbreviation", row["Shortcode"])
                    matched += 1
                    break
        print(f"  {matched} rows enriched with Excel data")

    Path("tte_loinc.json").write_text(json.dumps(loinc_rows, indent=2))
    Path("tte_snomed_srt.json").write_text(
        json.dumps([r for r in echo_rows if r["coding_scheme"] == "SRT"], indent=2))
    Path("tte_dcm.json").write_text(
        json.dumps([r for r in echo_rows if r["coding_scheme"] == "DCM"], indent=2))
    Path("ucum_units.json").write_text(json.dumps(ucum_units, indent=2))
    pd.DataFrame(table).to_csv("tte_master_table.csv", index=False)
    pd.DataFrame(table).to_excel("tte_master_table.xlsx", index=False, engine="openpyxl")

    print("\nSaved: tte_loinc.json, tte_snomed_srt.json, tte_dcm.json, "
          "ucum_units.json, tte_master_table.csv/xlsx")
    print(f"Master table: {len(table)} rows")

# ======================================================================
def main():
    ap = argparse.ArgumentParser(description="TTE echo LOINC/SNOMED/DCM/UCUM scraper")
    ap.add_argument("-u", "--loinc-user", help="LOINC username (free at loinc.org/join)")
    ap.add_argument("-p", "--loinc-pass", help="LOINC password")
    ap.add_argument("--local-loinc-zip", help="Path to a manually-downloaded Loinc zip (skips API)")
    ap.add_argument("--excel", help="Professor's Excel for viewport/normal ranges")
    ap.add_argument("--offline", action="store_true", help="Skip CID scraping")
    ap.add_argument("--local-ucum", help="Path to local ucum-essence.xml")
    args = ap.parse_args()

    # UCUM
    if args.local_ucum and Path(args.local_ucum).exists():
        ucum_path = Path(args.local_ucum)
        print(f"Using local UCUM: {ucum_path}")
    else:
        ucum_path = download_ucum()
    ucum_units = parse_ucum(ucum_path)

    # SNOMED + DCM (CIDs)
    echo_rows = scrape_cids(offline=args.offline)

    # LOINC
    loinc_rows = []
    if args.local_loinc_zip and Path(args.local_loinc_zip).exists():
        print("\nUsing local LOINC zip (no API):")
        main_csv = extract_main_loinc(Path(args.local_loinc_zip))
        loinc_rows = parse_loinc_csv(main_csv) if main_csv else []
    elif args.loinc_user and args.loinc_pass:
        main_csv = download_loinc_api(args.loinc_user, args.loinc_pass)
        loinc_rows = parse_loinc_csv(main_csv) if main_csv else []
    else:
        print("\n⚠ No LOINC source provided. Use --local-loinc-zip OR -u/-p to fetch LOINC.")

    # Merge & save
    save(echo_rows, loinc_rows, ucum_units, args.excel)


if __name__ == "__main__":
    main()
