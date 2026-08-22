#!/usr/bin/env python3
"""
curate_loinc.py
===============
Filter tte_loinc.json down to only genuine TTE echo leaf measurements.
Drops panels/reports, ECG-lead rows, scoring scales, and non-echo lab rows.
Output: tte_loinc_curated.json
"""
import json, re
from pathlib import Path

DROP = re.compile(
    r"report\b|finding scale|segment|\bscale\b|R wave|R['‘’]?\s?wave|"
    r"\blead\b|\bAVR?\b|\bAVL\b|\bAVF\b|\bV1\b|\bV2\b|\bV3\b|\bV4\b|\bV5\b|\bV6\b|"
    r"\bpanel\b|protocol|pediatric|fetal|adult congenital|diagnosis|search set|"
    r"question|interpretation|\bscore\b|\bscan\b|guideline|\bPET\b|\bSPECT\b|"
    r"perfusion|thallium|catheterization|angiography|nuclear|\bbiopsy\b",
    re.IGNORECASE)

KEEP_IF_ANY = re.compile(
    r"ejection fraction|fractional shortening|cardiac output|stroke volume|"
    r"cardiac index|stroke index|left ventricular|right ventricular|left atrial|"
    r"right atrial|aortic (valve|root|diameter|annulus|gradient|velocity|area|"
    r"regurgit)|mitral (valve|annulus|gradient|velocity|area|inflow|regurgit)|"
    r"tricuspid (valve|annulus|gradient|velocity|regurgit)|pulmonary (valve|"
    r"gradient|velocity|regurgit|arterial pressure)|interventricular septum|"
    r"intraventricular septum|ventricular septal defect|atrial septal defect|"
    r"aorta diameter|outflow tract|velocity.?time.?integral|e/a ratio|"
    r"deceleration|isovolumic|dp/dt|global longitudinal|\bstrain\b|tapse|"
    r"fractional area change",
    re.IGNORECASE)


def keep(r):
    name = str(r.get("code_meaning", "") or "")
    if not name or DROP.search(name):
        return False
    cls = str(r.get("class", "") or "")
    return bool(KEEP_IF_ANY.search(name)) or ("CARD" in cls and "US" in cls)


def main():
    src = Path("tte_loinc.json")
    if not src.exists():
        print("tte_loinc.json not found - run the scraper first")
        return
    rows = json.loads(src.read_text())
    uniq, seen = [], set()
    for r in rows:
        if keep(r) and r.get("code_value") not in seen:
            seen.add(r.get("code_value"))
            uniq.append(r)
    Path("tte_loinc_curated.json").write_text(json.dumps(uniq, indent=2))
    print(f"  original: {len(rows)} -> curated: {len(uniq)}")
    for r in uniq[:15]:
        print(f"    {r['code_value']}  {str(r.get('code_meaning',''))[:60]}")


if __name__ == "__main__":
    main()
