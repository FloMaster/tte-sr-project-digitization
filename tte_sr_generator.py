#!/usr/bin/env python3
"""
tte_sr_generator.py  (FINAL v7 — "Show the image" hyperlinks)
=============================================================
Produces FOUR deliverables that share Patient/Study with the placeholder
echo image so Weasis can resolve the references:

  --mode separate : sr_loinc.dcm, sr_snomed.dcm, sr_dcm.dcm
  --mode combined : sr_combined.dcm (each measurement assembled from
                    LOINC + SNOMED Finding Site + DCM Method)

Per-measurement rendering in Weasis (matching the reference example):

  1. Measurement name = value
     1. Finding Site: <anatomy>          <- HAS CONCEPT MOD child item
     2. Show the image                    <- hyperlink from ReferencedSOPSequence

CRITICAL: modifiers must be child content items inside ContentSequence
(0040,A730). "ConceptModifierSequence" is NOT a DICOM element and pydicom
silently drops it — that is why earlier files showed no sub-items/links.
"""
import argparse, json, random, sys
from pathlib import Path
from datetime import datetime

import pydicom
from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import ExplicitVRLittleEndian as IE, generate_uid
from pydicom.valuerep import DSfloat

PLACEHOLDER_FILE = "placeholder_echo.dcm"
FALLBACK_SOP_UID = "1.2.826.0.1.3680043.8.498.191990001.100000001"
FALLBACK_FRAMES = 200

PH = None  # placeholder attributes loaded at runtime

# --- coded concepts ---------------------------------------------------
ROOT         = ("125200", "DCM", "Adult Echocardiography Procedure Report")
FINDINGS     = ("59776-5", "LN", "Findings")
FINDING_SITE = ("363698007", "SCT", "Finding Site")
MEAS_GROUP   = ("125007", "DCM", "Measurement Group")
IMAGE_MODE   = ("399264008", "SCT", "Image Mode")
MEAS_METHOD  = ("370129005", "SCT", "Measurement Method")
DERIVATION   = ("121401", "DCM", "Derivation")
MEASURED     = ("121401", "DCM", "Measured")
SELECTION    = ("121008", "DCM", "Selection Status")
ORIGINAL     = ("109002", "DCM", "Original")
METHOD_MEASURED = ("11526002", "SCT", "Measured")
MODE_2D      = ("399348008", "SCT", "2D mode")
SELECTED_IMAGE = ("121214", "DCM", "Selected Region")

# --- expanded anatomy map ---------------------------------------------
SITES = {
    # left heart
    "left ventricular outflow tract": ("12956001", "Left Ventricular Outflow Tract"),
    "lvot":                            ("12956001", "Left Ventricular Outflow Tract"),
    "left atrium":                     ("90096002", "Left Atrium"),
    "left atrial":                     ("90096002", "Left Atrium"),
    "la":                              ("90096002", "Left Atrium"),
    "left ventricle":                  ("87878005", "Left Ventricle"),
    "left ventricular":                ("87878005", "Left Ventricle"),
    "lv":                              ("87878005", "Left Ventricle"),
    "left ventric":                    ("87878005", "Left Ventricle"),

    # right heart
    "right ventricular outflow tract": ("95580009", "Right Ventricular Outflow Tract"),
    "rvot":                            ("95580009", "Right Ventricular Outflow Tract"),
    "right atrium":                    ("79544007", "Right Atrium"),
    "right atrial":                    ("79544007", "Right Atrium"),
    "ra":                              ("79544007", "Right Atrium"),
    "right ventricle":                 ("53085002", "Right Ventricle"),
    "right ventricular":               ("53085002", "Right Ventricle"),
    "rv":                              ("53085002", "Right Ventricle"),

    # valves
    "mitral valve":                    ("91134007", "Mitral Valve"),
    "mitral":                          ("91134007", "Mitral Valve"),
    "aortic valve":                    ("59078006", "Aortic Valve"),
    "aortic":                          ("59078006", "Aortic Valve"),
    "aorta":                           ("15825003", "Aorta"),
    "tricuspid valve":                 ("46030003", "Tricuspid Valve"),
    "tricuspid":                       ("46030003", "Tricuspid Valve"),
    "pulmonary valve":                 ("46073000", "Pulmonary Valve"),
    "pulmonary":                       ("46073000", "Pulmonary Valve"),
    "pulmonic valve":                  ("46073000", "Pulmonary Valve"),

    # septum / walls
    "interventricular septum":         ("90096001", "Interventricular Septum"),
    "iv septum":                       ("90096001", "Interventricular Septum"),
    "ivs":                             ("90096001", "Interventricular Septum"),
    "septum":                          ("90096001", "Interventricular Septum"),
    "interatrial septum":              ("63961008", "Interatrial Septum"),
    "posterior wall":                  ("282771008", "Posterior Wall of Left Ventricle"),
    "free wall":                       ("283495006", "Free Wall of Right Ventricle"),

    # chambers / other
    "pericardium":                     ("18796000", "Pericardium"),
    "pericardial":                     ("18796000", "Pericardium"),
}

DEFAULT_SITE = ("87878005", "Left Ventricle")


def site_for(name):
    """Return the most specific cardiac anatomy site for a measurement name."""
    nl = (" " + (name or "").lower() + " ").replace(".", " ")

    matches = []
    for k, v in SITES.items():
        kw = " " + k.lower() + " "
        if kw in nl:
            matches.append((len(kw), v, k))
    if matches:
        matches.sort(reverse=True)
        return matches[0][1]

    simple = nl.replace("-", " ").replace("/", " ")
    matches2 = []
    for k, v in SITES.items():
        kw = " " + k.lower() + " "
        if kw in simple:
            matches2.append((len(kw), v, k))
    if matches2:
        matches2.sort(reverse=True)
        return matches2[0][1]

    return DEFAULT_SITE


# --- DICOM helpers ----------------------------------------------------
def C(code_value, scheme, meaning):
    ds = Dataset()
    ds.CodeValue = code_value
    ds.CodingSchemeDesignator = scheme
    ds.CodeMeaning = (meaning or "1")[:64]
    return ds


def ci(rel, vtype, name=None):
    ds = Dataset()
    ds.RelationshipType = rel
    ds.ValueType = vtype
    if name:
        ds.ConceptNameCodeSequence = [C(*name)]
    return ds


def mod(concept, value):
    ds = ci("HAS CONCEPT MOD", "CODE", concept)
    ds.ConceptCodeSequence = [C(*value)]
    return ds


def image_child(frame_1based):
    ds = ci("INFERRED FROM", "IMAGE", SELECTED_IMAGE)
    ref = Dataset()
    ref.ReferencedSOPClassUID = PH["class_uid"]
    ref.ReferencedSOPInstanceUID = PH["sop_uid"]
    ref.ReferencedFrameNumber = int(wrap(frame_1based))
    ds.ReferencedSOPSequence = [ref]
    return ds


def wrap(frame):
    return ((int(frame) - 1) % PH["frames"]) + 1


def clean_unit(u):
    u = str(u or "").strip()
    return "1" if u.lower() in ("", "nan", "none") else u


def num_item(concept, value, unit, site=None, extra_mods=(), frame=None):
    ds = ci("CONTAINS", "NUM", concept)
    mvs = Dataset()
    mvs.NumericValue = DSfloat(value)
    mvs.MeasurementUnitsCodeSequence = [C(unit, "UCUM", unit)]
    ds.MeasuredValueSequence = [mvs]

    children = []
    if site:
        children.append(mod(FINDING_SITE, site))
    children.extend(list(extra_mods))
    if frame is not None:
        children.append(image_child(frame))
    if children:
        ds.ContentSequence = children
    return ds


# --- content tree -----------------------------------------------------
def build_root(measurements, combined=False):
    root = ci("CONTAINS", "CONTAINER", ROOT)
    groups = {}
    for m in measurements:
        groups.setdefault(m["site_name"], []).append(m)

    frame = 1
    findings = []
    for sname, ms in groups.items():
        scode = ms[0]["site_code"]

        f = ci("CONTAINS", "CONTAINER", FINDINGS)
        f.ContentSequence = [mod(FINDING_SITE, (scode, "SRT", sname))]

        mg = ci("CONTAINS", "CONTAINER", MEAS_GROUP)
        mg.ContentSequence = [mod(IMAGE_MODE, MODE_2D)]

        for m in ms:
            concept = (m["code"], m["scheme"], m["meaning"])
            site = (m["site_code"], "SRT", m["site_name"])
            extra = (mod(MEAS_METHOD, METHOD_MEASURED),) if combined else ()
            mg.ContentSequence.append(
                num_item(concept, m["value"], m["unit"], site, extra, frame)
            )
            frame += 1

        f.ContentSequence.append(mg)
        findings.append(f)

    root.ContentSequence = findings
    return root


# --- data loaders / value generation ----------------------------------
def gen_value(unit):
    u = unit.lower()
    if any(k in u for k in ("%", "ratio")): return round(random.uniform(20, 75), 1)
    if "m/s" in u or "cm/s" in u:           return round(random.uniform(0.3, 2.5), 2)
    if "mm[hg]" in u or "mmhg" in u:        return round(random.uniform(10, 90), 1)
    if "ml/m2" in u:                        return round(random.uniform(20, 60), 1)
    if "ml" in u or "cm3" in u:             return round(random.uniform(30, 200), 1)
    if "m2" in u or "cm2" in u:             return round(random.uniform(2, 6), 2)
    if "g" in u:                            return round(random.uniform(80, 250), 1)
    if "cm" in u or "mm" in u:              return round(random.uniform(1.0, 8.0), 2)
    if "bpm" in u or "/min" in u:           return round(random.uniform(50, 110), 0)
    return round(random.uniform(1.0, 100.0), 2)


def _finalize(m):
    sn, nn = site_for(m.get("code_meaning", ""))
    m["site_code"], m["site_name"] = sn, nn
    return m


def load_measurements(scheme):
    if scheme == "LN":
        path = Path("tte_loinc_curated.json")
        if not path.exists():
            print("Run curate_loinc.py first"); sys.exit(1)
        return [_finalize({
            "code": r["code_value"], "scheme": "LN",
            "meaning": r.get("code_meaning", ""),
            "value": gen_value(clean_unit(r.get("unit_ucum"))),
            "unit": clean_unit(r.get("unit_ucum")),
        }) for r in json.loads(path.read_text())]

    src = {"SRT": ("tte_snomed_srt.json", "SRT"),
           "DCM": ("tte_dcm.json", "DCM")}[scheme]
    path = Path(src[0])
    if not path.exists():
        print(f"{src[0]} not found"); sys.exit(1)
    return [_finalize({
        "code": r["code_value"], "scheme": src[1],
        "meaning": r.get("code_meaning", ""),
        "value": gen_value(clean_unit(r.get("ucum_unit"))),
        "unit": clean_unit(r.get("ucum_unit")),
    }) for r in json.loads(path.read_text())]


def load_placeholder():
    global PH
    try:
        img = pydicom.dcmread(PLACEHOLDER_FILE, stop_before_pixels=True)
        PH = {
            "sop_uid":   str(img.SOPInstanceUID),
            "class_uid": str(img.SOPClassUID),
            "study_uid": str(img.StudyInstanceUID),
            "frames":    int(getattr(img, "NumberOfFrames", FALLBACK_FRAMES)),
            "patient":   str(img.PatientName or "Test^Patient"),
            "pid":       str(img.PatientID or "SR001"),
        }
        print(f"  placeholder loaded: {PH['frames']} frames")
        return PH
    except Exception as e:
        print(f"  ! {PLACEHOLDER_FILE} missing or unreadable ({e})")
        print("    Run: python make_placeholder_image.py")
        sys.exit(1)


# --- writer -----------------------------------------------------------
def write_sr(measurements, out, combined=False, series_desc=""):
    fm = Dataset()
    fm.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.88.33"
    sop = generate_uid()
    fm.MediaStorageSOPInstanceUID = sop
    fm.TransferSyntaxUID = IE
    fm.ImplementationClassUID = "1.2.826.0.1.3680043.8.498.1"

    ds = FileDataset(out, {}, file_meta=fm, preamble=b"\0" * 128)
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.88.33"
    ds.SOPInstanceUID = sop
    ds.StudyInstanceUID = PH["study_uid"]
    ds.SeriesInstanceUID = generate_uid()
    ds.PatientName = PH["patient"]
    ds.PatientID = PH["pid"]
    ds.PatientSex = "O"
    ds.StudyDate = datetime.now().strftime("%Y%m%d")
    ds.StudyTime = datetime.now().strftime("%H%M%S")
    ds.Modality = "SR"
    ds.SeriesNumber = "1"
    ds.InstanceNumber = "1"
    ds.SeriesDescription = series_desc
    ds.Manufacturer = "TTE-Project"
    ds.ManufacturerModelName = "TTE-SR-ImageLink"
    ds.SoftwareVersions = "1.0"
    ds.ContentDate = ds.StudyDate
    ds.ContentTime = ds.StudyTime
    ds.VerificationFlag = "UNVERIFIED"
    ds.CompletionFlag = "COMPLETE"
    ds.VerificationDateTime = datetime.now().strftime("%Y%m%d%H%M%S")
    ds.ContentSequence = [build_root(measurements, combined=combined)]
    ds.save_as(out, enforce_file_format=True)
    print(f"  ✓ {out}  ({len(measurements)} measurements)")


def validate(out):
    d = pydicom.dcmread(out, force=True)
    stats = {"num": 0, "mods": 0, "image_children": 0}
    def walk(seq):
        for item in (seq or []):
            if getattr(item, "ValueType", None) == "NUM":
                stats["num"] += 1
            if getattr(item, "ValueType", None) == "IMAGE":
                stats["image_children"] += 1
            for it in (getattr(item, "ContentSequence", None) or []):
                if getattr(it, "RelationshipType", None) == "HAS CONCEPT MOD":
                    stats["mods"] += 1
            walk(item.get("ContentSequence", []))
    walk(d.ContentSequence)
    print(f"      -> NUM={stats['num']}, modifiers={stats['mods']}, "
          f"IMAGE children={stats['image_children']}, "
          f"same study={str(d.StudyInstanceUID) == PH['study_uid']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["separate", "combined"], required=True)
    args = ap.parse_args()

    global PH
    random.seed(42)
    PH = load_placeholder()

    if args.mode == "separate":
        for scheme, out, desc in [("LN", "sr_loinc.dcm", "TTE SR LOINC"),
                                  ("SRT", "sr_snomed.dcm", "TTE SR SNOMED"),
                                  ("DCM", "sr_dcm.dcm", "TTE SR DCM")]:
            write_sr(load_measurements(scheme), out, series_desc=desc)
            validate(out)
        print("\nDone.")
    else:
        out = "sr_combined.dcm"
        write_sr(load_measurements("LN"), out, combined=True,
                 series_desc="TTE SR combined (LOINC+SNOMED+DCM)")
        validate(out)
        print("\nDone.")


if __name__ == "__main__":
    main()