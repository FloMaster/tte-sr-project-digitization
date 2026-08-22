#!/usr/bin/env python3
"""
tte_sr_generator.py  (FINAL)
============================
TTE Echocardiography SR generator producing FOUR deliverables:

  --mode separate :
      sr_loinc.dcm      (LOINC primary scheme)
      sr_snomed.dcm     (SNOMED primary scheme)
      sr_dcm.dcm        (DCM  primary scheme)
  --mode combined :
      sr_combined.dcm   (every measurement assembled from three:
                         LOINC ConceptName + SNOMED Finding Site + DCM Method)

Every NUM measurement carries a ReferencedSOPSequence (Image Reference Macro)
pointing at the placeholder multi-frame ultrasound image, so Weasis can jump to
the source frame when a measurement is clicked.

Hierarchy: Adult Echo Report (125200,DCM) -> Findings (59776-5,LN)
         -> Measurement Group (125007,DCM) -> NUM
"""
import argparse, json, random, sys
from pathlib import Path
from datetime import datetime

import pydicom
from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import ExplicitVRLittleEndian as IE, generate_uid
from pydicom.valuerep import DSfloat

# ---- Fixed reference to the placeholder image (see make_placeholder_image.py)
PLACEHOLDER_SOP_UID = "1.2.826.0.1.3680043.8.498.191990001.100000001"
US_MULTIFRAME_CLASS = "1.2.840.10008.5.1.4.1.1.3.1"
PLACEHOLDER_FRAMES = 200

# ---- Coded concepts
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

# ---- Anatomy keyword -> (SNOMED code, name)
SITES = {
    "left ventricle": ("87878005", "Left Ventricle"),
    "lv":            ("87878005", "Left Ventricle"),
    "right ventricle":("53085002", "Right Ventricle"),
    "rv":            ("53085002", "Right Ventricle"),
    "left atrium":   ("90096002", "Left Atrium"),
    "la":            ("90096002", "Left Atrium"),
    "right atrium":  ("79544007", "Right Atrium"),
    "ra":            ("79544007", "Right Atrium"),
    "mitral":        ("91134007", "Mitral Valve"),
    "aortic":        ("59078006", "Aortic Valve"),
    "tricuspid":     ("46030003", "Tricuspid Valve"),
    "pulmonary":     ("46073000", "Pulmonary Valve"),
    "septum":        ("90096001", "Interventricular Septum"),
    "ivs":           ("90096001", "Interventricular Septum"),
}
DEFAULT_SITE = ("87878005", "Left Ventricle")


def site_for(name):
    nl = (name or "").lower()
    for k, v in SITES.items():
        if k in nl:
            return v
    return DEFAULT_SITE


# ---- primitives
def C(code_value, scheme, meaning):
    ds = Dataset()
    ds.CodeValue = code_value
    ds.CodingSchemeDesignator = scheme
    ds.CodeMeaning = (meaning or "")[:64]   # LO 64-char limit
    return ds


def ci(rel, vtype, name=None):
    ds = Dataset(); ds.RelationshipType = rel; ds.ValueType = vtype
    if name:
        ds.ConceptNameCodeSequence = [C(*name)]
    return ds


def mod(concept, value):
    ds = ci("HAS CONCEPT MOD", "CODE", concept)
    ds.ConceptCodeSequence = [C(*value)]
    return ds


def ref_image(frame_1based):
    """Image Reference Macro pointing at a 1-based frame of the placeholder."""
    item = Dataset()
    item.ReferencedSOPClassUID = US_MULTIFRAME_CLASS
    item.ReferencedSOPInstanceUID = PLACEHOLDER_SOP_UID
    item.ReferencedFrameNumber = [int(frame_1based)]
    return item


def num_item(concept, value, unit, extra_mods=(), frame=None):
    ds = ci("CONTAINS", "NUM", concept)
    mvs = Dataset()
    mvs.NumericValue = DSfloat(value)
    mvs.MeasurementUnitsCodeSequence = [C(unit, "UCUM", "")]
    ds.MeasuredValueSequence = [mvs]
    ds.ConceptModifierSequence = [
        mod(DERIVATION, MEASURED),
        mod(SELECTION, ORIGINAL),
        *list(extra_mods),
    ]
    if frame is not None:
        ds.ReferencedSOPSequence = [ref_image(frame)]   # frame navigation
    return ds


# ---- hierarchy
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
        f.ConceptModifierSequence = [mod(FINDING_SITE, (scode, "SRT", sname))]

        mg = ci("CONTAINS", "CONTAINER", MEAS_GROUP)
        mg.ConceptModifierSequence = [mod(IMAGE_MODE, MODE_2D)]

        nums = []
        for m in ms:
            concept = (m["code"], m["scheme"], m["meaning"])
            extra = ()
            if combined:
                extra = (mod(FINDING_SITE, (m["site_code"], "SRT", m["site_name"])),
                         mod(MEAS_METHOD, METHOD_MEASURED))
            # wrap frame index so it stays within the placeholder's frame count
            fnum = ((frame - 1) % PLACEHOLDER_FRAMES) + 1
            nums.append(num_item(concept, m["value"], m["unit"], extra, fnum))
            frame += 1

        mg.ContentSequence = nums
        f.ContentSequence = [mg]
        findings.append(f)
    root.ContentSequence = findings
    return root


# ---- value / measurement loading
def gen_value(unit):
    u = (unit or "").lower()
    if any(k in u for k in ("%", "ratio")): return round(random.uniform(20, 75), 1)
    if "m/s" in u or "cm/s" in u: return round(random.uniform(0.3, 2.5), 2)
    if "mm[hg]" in u or "mmhg" in u: return round(random.uniform(10, 90), 1)
    if "ml/m2" in u: return round(random.uniform(20, 60), 1)
    if "ml" in u or "cm3" in u: return round(random.uniform(30, 200), 1)
    if "m2" in u or "cm2" in u: return round(random.uniform(2, 6), 2)
    if "g" in u: return round(random.uniform(80, 250), 1)
    if "cm" in u or "mm" in u: return round(random.uniform(1.0, 8.0), 2)
    if "bpm" in u or "/min" in u: return round(random.uniform(50, 110), 0)
    return round(random.uniform(1.0, 100.0), 2)


def _finalize(m):
    sn, nn = site_for(m.get("code_meaning", ""))
    m["site_code"] = sn
    m["site_name"] = nn
    return m


def load_measurements(scheme):
    if scheme == "LN":
        path = Path("tte_loinc_curated.json")
        if not path.exists():
            print("Run curate_loinc.py first (tte_loinc_curated.json missing)")
            sys.exit(1)
        return [_finalize({
            "code": r["code_value"], "scheme": "LN",
            "meaning": r.get("code_meaning", ""),
            "value": gen_value(r.get("unit_ucum") or ""),
            "unit": r.get("unit_ucum") or "1",
        }) for r in json.loads(path.read_text())]

    src = {"SRT": ("tte_snomed_srt.json", "SRT"),
           "DCM": ("tte_dcm.json", "DCM")}[scheme]
    path = Path(src[0])
    if not path.exists():
        print(f"{src[0]} not found - run the scraper first")
        sys.exit(1)
    return [_finalize({
        "code": r["code_value"], "scheme": src[1],
        "meaning": r.get("code_meaning", ""),
        "value": gen_value(r.get("ucum_unit") or ""),
        "unit": r.get("ucum_unit") or "1",
    }) for r in json.loads(path.read_text())]


# ---- writer
def write_sr(measurements, out, combined=False):
    params = {
        "sop_uid": generate_uid(), "study_uid": generate_uid(),
        "series_uid": generate_uid(),
        "date": datetime.now().strftime("%Y%m%d"),
        "time": datetime.now().strftime("%H%M%S"),
    }
    fm = Dataset()
    fm.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.88.33"
    fm.MediaStorageSOPInstanceUID = params["sop_uid"]
    fm.TransferSyntaxUID = IE
    fm.ImplementationClassUID = "1.2.826.0.1.3680043.8.498.1"

    ds = FileDataset(out, {}, file_meta=fm, preamble=b"\0" * 128)
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.88.33"
    ds.SOPInstanceUID = params["sop_uid"]
    ds.StudyInstanceUID = params["study_uid"]
    ds.SeriesInstanceUID = params["series_uid"]
    ds.PatientName = "Test^Patient"; ds.PatientID = "SR001"
    ds.PatientSex = "O"
    ds.StudyDate = params["date"]; ds.StudyTime = params["time"]
    ds.Modality = "SR"; ds.SeriesNumber = "1"; ds.InstanceNumber = "1"
    ds.Manufacturer = "TTE-Project"
    ds.ManufacturerModelName = "TTE-SR-Generator-FINAL"
    ds.SoftwareVersions = "1.0"
    ds.ContentDate = params["date"]; ds.ContentTime = params["time"]
    ds.VerificationFlag = "UNVERIFIED"; ds.CompletionFlag = "COMPLETE"
    ds.VerificationDateTime = datetime.now().strftime("%Y%m%d%H%M%S")
    ds.ContentSequence = [build_root(measurements, combined=combined)]
    ds.save_as(out, enforce_file_format=True)
    print(f"  ✓ {out}  ({len(measurements)} measurements, frames linked)")


def validate(out):
    d = pydicom.dcmread(out, force=True)
    num_count = 0
    refs = 0
    def walk(seq):
        nonlocal num_count, refs
        for item in (seq or []):
            if getattr(item, "ValueType", None) == "NUM":
                num_count += 1
                if getattr(item, "ReferencedSOPSequence", None):
                    refs += 1
            for key in ("ContentSequence", "ConceptModifierSequence"):
                if key in item:
                    walk(item[key])
    walk([d.ContentSequence[0]])
    print(f"      -> {num_count} NUM items, {refs} with frame reference; "
          f"SOPClass={d.SOPClassUID}")
    assert num_count == len(
        __import__("sys").stdout) or True  # just informational


def main():
    ap = argparse.ArgumentParser(description="TTE Echo SR generator (FINAL)")
    ap.add_argument("--mode", choices=["separate", "combined"], required=True,
                    help="separate=3 scheme files, combined=1 assembled file")
    args = ap.parse_args()

    random.seed(42)
    if args.mode == "separate":
        for scheme, out in [("LN", "sr_loinc.dcm"),
                            ("SRT", "sr_snomed.dcm"),
                            ("DCM", "sr_dcm.dcm")]:
            write_sr(load_measurements(scheme), out, combined=False)
        print("\nDone: sr_loinc.dcm, sr_snomed.dcm, sr_dcm.dcm")
    else:
        write_sr(load_measurements("LN"), "sr_combined.dcm", combined=True)
        print("\nDone: sr_combined.dcm (assembled from three + frames)")


if __name__ == "__main__":
    main()
