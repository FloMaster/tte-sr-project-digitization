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

PLACEHOLDER_FILE    = "placeholder_echo.dcm"
US_MULTIFRAME_CLASS = "1.2.840.10008.5.1.4.1.1.3.1"
FALLBACK_SOP_UID    = "1.2.826.0.1.3680043.8.498.191990001.100000001"
FALLBACK_FRAMES     = 200

PH = None

# ---- coded concepts
ROOT        = ("125200", "DCM", "Adult Echocardiography Procedure Report")
FINDINGS    = ("59776-5", "LN", "Findings")
FINDING_SITE= ("363698007", "SCT", "Finding Site")
MEAS_GROUP  = ("125007", "DCM", "Measurement Group")
IMAGE_MODE  = ("399264008", "SCT", "Image Mode")
MEAS_METHOD = ("370129005", "SCT", "Measurement Method")
DERIVATION  = ("121401", "DCM", "Derivation")
MEASURED    = ("121401", "DCM", "Measured")
SELECTION   = ("121008", "DCM", "Selection Status")
ORIGINAL    = ("109002", "DCM", "Original")
METHOD_MEASURED = ("11526002", "SCT", "Measured")
MODE_2D     = ("399348008", "SCT", "2D mode")

SITES = {
    "left ventricle":  ("87878005", "Left Ventricle"),
    "lv":              ("87878005", "Left Ventricle"),
    "right ventricle": ("53085002", "Right Ventricle"),
    "rv":              ("53085002", "Right Ventricle"),
    "left atrium":     ("90096002", "Left Atrium"),
    "la":              ("90096002", "Left Atrium"),
    "right atrium":    ("79544007", "Right Atrium"),
    "ra":              ("79544007", "Right Atrium"),
    "mitral":          ("91134007", "Mitral Valve"),
    "aortic":          ("59078006", "Aortic Valve"),
    "tricuspid":       ("46030003", "Tricuspid Valve"),
    "pulmonary":       ("46073000", "Pulmonary Valve"),
    "septum":          ("90096001", "Interventricular Septum"),
    "ivs":             ("90096001", "Interventricular Septum"),
}
DEFAULT_SITE = ("87878005", "Left Ventricle")

def site_for(name):
    nl = (name or "").lower()
    for k, v in SITES.items():
        if k in nl:
            return v
    return DEFAULT_SITE

# ---- primitives -------------------------------------------------------
def C(code_value, scheme, meaning):
    ds = Dataset()
    ds.CodeValue = code_value
    ds.CodingSchemeDesignator = scheme
    ds.CodeMeaning = (meaning or "1")[:64]      # LO 64-char limit
    return ds

def ci(rel, vtype, name=None):
    ds = Dataset()
    ds.RelationshipType = rel
    ds.ValueType = vtype
    if name:
        ds.ConceptNameCodeSequence = [C(*name)]
    return ds

def mod(concept, value):
    """A modifier is a normal child content item (HAS CONCEPT MOD) that lives
    INSIDE the parent's ContentSequence — not a 'ConceptModifierSequence'."""
    ds = ci("HAS CONCEPT MOD", "CODE", concept)
    ds.ConceptCodeSequence = [C(*value)]
    return ds

def ref_image(frame_1based):
    """Image Reference Macro -> placeholder echo (ReferencedSOPSequence 0008,1199)."""
    item = Dataset()
    item.ReferencedSOPClassUID = US_MULTIFRAME_CLASS
    item.ReferencedSOPInstanceUID = PH["sop_uid"]
    item.ReferencedFrameNumber = [int(wrap(frame_1based))]   # 1-based
    return item

def wrap(frame):
    return ((int(frame) - 1) % PH["frames"]) + 1

def num_item(concept, value, unit, site=None, extra_mods=(), frame=None):
    ds = ci("CONTAINS", "NUM", concept)
    mvs = Dataset()
    mvs.NumericValue = DSfloat(value)
    mvs.MeasurementUnitsCodeSequence = [C(unit or "1", "UCUM", unit or "1")]
    ds.MeasuredValueSequence = [mvs]

    # HAS CONCEPT MOD children -> rendered as indented sub-items in Weasis
    children = []
    if site:
        children.append(mod(FINDING_SITE, site))
    children.extend(list(extra_mods))
    if children:
        ds.ContentSequence = children

    # image reference -> Weasis renders the "Show the image" hyperlink
    if frame is not None:
        ds.ReferencedSOPSequence = [ref_image(frame)]
    return ds

# ---- hierarchy --------------------------------------------------------
def build_root(measurements, combined=False, group_links=False):
    root = ci("CONTAINS", "CONTAINER", ROOT)
    groups = {}
    for m in measurements:
        groups.setdefault(m["site_name"], []).append(m)

    frame = 1
    findings = []
    for sname, ms in groups.items():
        scode = ms[0]["site_code"]
        f = ci("CONTAINS", "CONTAINER", FINDINGS)
        f.ContentSequence = []                     # modifiers as child items

        mg = ci("CONTAINS", "CONTAINER", MEAS_GROUP)
        mg.ContentSequence = [mod(IMAGE_MODE, MODE_2D)]

        nums, group_frames = [], []
        for m in ms:
            concept = (m["code"], m["scheme"], m["meaning"])
            site   = (m["site_code"], "SRT", m["site_name"])
            extra  = ()
            if combined:
                extra = (mod(MEAS_METHOD, METHOD_MEASURED),)
            gframe = wrap(frame)
            nums.append(num_item(concept, m["value"], m["unit"], site, extra, gframe))
            group_frames.append(gframe)
            frame += 1

        if group_links:
            grp = Dataset()
            grp.ReferencedSOPClassUID = US_MULTIFRAME_CLASS
            grp.ReferencedSOPInstanceUID = PH["sop_uid"]
            grp.ReferencedFrameNumber = [int(g) for g in group_frames]
            mg.ReferencedSOPSequence = [grp]

        mg.ContentSequence += nums          # modifiers first, then NUM items
        f.ContentSequence.append(mg)
        f.ContentSequence.insert(0, mod(FINDING_SITE, (scode, "SRT", sname)))
        root_f = findings
        root_f.append(f)
    root = ci("CONTAINS", "CONTAINER", ROOT)
    root.ContentSequence = findings
    return root

# ---- values / loaders (unchanged) -------------------------------------
def gen_value(unit):
    u = (unit or "").lower()
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
        return [_finalize({"code": r["code_value"], "scheme": "LN",
                           "meaning": r.get("code_meaning", ""),
                           "value": gen_value(r.get("unit_ucum") or ""),
                           "unit": r.get("unit_ucum") or "1"})
                for r in json.loads(path.read_text())]
    src = {"SRT": ("tte_snomed_srt.json", "SRT"),
           "DCM": ("tte_dcm.json", "DCM")}[scheme]
    path = Path(src[0])
    if not path.exists():
        print(f"{src[0]} not found"); sys.exit(1)
    return [_finalize({"code": r["code_value"], "scheme": src[1],
                       "meaning": r.get("code_meaning", ""),
                       "value": gen_value(r.get("ucum_unit") or ""),
                       "unit": r.get("ucum_unit") or "1"})
            for r in json.loads(path.read_text())]

def load_placeholder():
    try:
        img = pydicom.dcmread(PLACEHOLDER_FILE, stop_before_pixels=True)
        ph = {"sop_uid": str(img.SOPInstanceUID),
              "study_uid": str(img.StudyInstanceUID),
              "frames": int(getattr(img, "NumberOfFrames", FALLBACK_FRAMES)),
              "patient": str(img.PatientName or "Test^Patient"),
              "pid": str(img.PatientID or "SR001")}
        print(f"  placeholder loaded: frames={ph['frames']}, study shared")
        return ph
    except Exception as e:
        print(f"  ! {PLACEHOLDER_FILE} missing ({e}) — run make_placeholder_image.py")
        return {"sop_uid": FALLBACK_SOP_UID, "study_uid": generate_uid(),
                "frames": FALLBACK_FRAMES, "patient": "Test^Patient", "pid": "SR001"}

# ---- writer -----------------------------------------------------------
def write_sr(measurements, out, combined=False, group_links=False, series_desc=""):
    fm = Dataset()
    fm.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.88.33"
    sop = generate_uid()
    fm.MediaStorageSOPInstanceUID = sop
    fm.TransferSyntaxUID = IE
    fm.ImplementationClassUID = "1.2.826.0.1.3680043.8.498.1"

    ds = FileDataset(out, {}, file_meta=fm, preamble=b"\0" * 128)
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.88.33"
    ds.SOPInstanceUID = sop
    ds.StudyInstanceUID = PH["study_uid"]        # same study -> links resolve
    ds.SeriesInstanceUID = generate_uid()
    ds.PatientName = PH["patient"]
    ds.PatientID = PH["pid"]
    ds.PatientSex = "O"
    ds.StudyDate = datetime.now().strftime("%Y%m%d")
    ds.StudyTime = datetime.now().strftime("%H%M%S")
    ds.Modality = "SR"; ds.SeriesNumber = "1"; ds.InstanceNumber = "1"
    ds.SeriesDescription = series_desc
    ds.Manufacturer = "TTE-Project"
    ds.ManufacturerModelName = "TTE-SR-Generator-FINAL"
    ds.SoftwareVersions = "1.0"
    ds.ContentDate = ds.StudyDate; ds.ContentTime = ds.StudyTime
    ds.VerificationFlag = "UNVERIFIED"; ds.CompletionFlag = "COMPLETE"
    ds.VerificationDateTime = datetime.now().strftime("%Y%m%d%H%M%S")
    ds.ContentSequence = [build_root(measurements, combined=combined,
                                     group_links=group_links)]
    ds.save_as(out, enforce_file_format=True)
    print(f"  ✓ {out}  ({len(measurements)} measurements, image links on)")

def validate(out):
    d = pydicom.dcmread(out, force=True)
    stats = {"num": 0, "mods": 0, "refs": 0}
    def walk(seq):
        for item in (seq or []):
            if getattr(item, "ValueType", None) == "NUM":
                stats["num"] += 1
            if getattr(item, "ReferencedSOPSequence", None):
                stats["refs"] += 1
            for it in (getattr(item, "ContentSequence", None) or []):
                if it.RelationshipType == "HAS CONCEPT MOD":
                    stats["mods"] += 1
    walk(d.ContentSequence)
    print(f"      -> NUM={stats['num']}, HAS CONCEPT MOD items={stats['mods']}, "
          f"image refs={stats['refs']}, same study as placeholder: "
          f"{str(d.StudyInstanceUID) == PH['study_uid']}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["separate", "combined"], required=True)
    ap.add_argument("--group-links", action="store_true",
                    help="also attach frame lists to Measurement Groups")
    args = ap.parse_args()

    global PH
    random.seed(42)
    PH = load_placeholder()

    if args.mode == "separate":
        for scheme, out, desc in [("LN", "sr_loinc.dcm", "TTE SR LOINC"),
                                  ("SRT", "sr_snomed.dcm", "TTE SR SNOMED"),
                                  ("DCM", "sr_dcm.dcm", "TTE SR DCM")]:
            write_sr(load_measurements(scheme), out, group_links=args.group_links,
                     series_desc=desc)
            validate(out)
        print("\nDone.")
    else:
        out = "sr_combined.dcm"
        write_sr(load_measurements("LN"), out, combined=True,
                 group_links=args.group_links,
                 series_desc="TTE SR combined (LOINC+SNOMED+DCM)")
        validate(out)
        print("\nDone.")

if __name__ == "__main__":
    main()
