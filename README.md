# TTE Echocardiography DICOM SR Generator

Automated generation of standards-compliant **DICOM Structured Reports (SR)** for
**Transthoracic Echocardiography (TTE)**, built on the **LOINC**, **SNOMED CT**,
**DICOM (DCM)**, and **UCUM** coding standards and renderable in the
**Weasis** DICOM viewer.

## Overview

The project scrapes official DICOM Context Groups (CIDs 12234–12251) for SNOMED
and DCM codes and downloads the full LOINC database from Regenstrief, then merges
them with a measurement list into a consolidated master table. From that table it
generates four DICOM SR files that display every measurement in Weasis —
including an option to assemble a single measurement "from three" coding schemes.

Reports follow the **DICOM Enhanced SR SOP Class**
(`1.2.840.10008.5.1.4.1.1.88.33`) and the template hierarchy
**TID 5200 → 5202 → 5203**:

Adult Echocardiography Procedure Report (125200, DCM)
└─ Findings (59776-5, LN)
└─ Measurement Group (125007, DCM)
└─ NUM measurement items


Each NUM item carries UCUM-compliant units and modifiers for **Finding Site**
(SNOMED), **Derivation**, **Selection Status**, and **Image Mode**.

Because real echo images were not provided, the pipeline ships a **placeholder
multi-frame ultrasound image**. The reports link each measurement to a frame via
`ReferencedSOPSequence` / `ReferencedFrameNumber`, so clicking a measurement in
Weasis jumps to its source frame. (not sure if this one will work :/)

## Deliverables

| File | Description |
|---|---|
| `sr_loinc.dcm` | Report coded with the **LOINC** scheme |
| `sr_snomed.dcm` | Report coded with the **SNOMED CT** scheme |
| `sr_dcm.dcm` | Report coded with the **DICOM (DCM)** scheme |
| `sr_combined.dcm` | Single report where **each measurement is assembled from all three schemes** (LOINC ConceptName + SNOMED Finding Site + DCM Method) |
| `placeholder_echo.dcm` | Synthetic 200-frame multi-frame ultrasound image that the reports reference for frame navigation |

## Scripts

| Script | Purpose |
|---|---|
| `tte_all_scrapers.py` | Scrapes/downloads DICOM CIDs, LOINC, and UCUM; builds `tte_master_table.xlsx` |
| `curate_loinc.py` | Filters raw LOINC rows down to genuine TTE echo measurements -> `tte_loinc_curated.json` |
| `make_placeholder_image.py` | Generates the placeholder multi-frame ultrasound image |
| `tte_sr_generator.py` | Produces the four `.dcm` SR deliverables, with frame navigation |

## Main Data Files

| File | Source |
|---|---|
| `tte_master_table.xlsx` | Consolidated measurement master table |
| `tte_loinc_curated.json` | Curated LOINC echo measurements |
| `tte_snomed_srt.json` | SNOMED codes from DICOM CIDs |
| `tte_dcm.json` | DCM codes from DICOM CIDs |
| `ucum_units.json` | UCUM unit set |
| `ucum-essence.xml` / `.zip` | Official UCUM standard source |

## Installation

```bash
pip install -r requirements.txt
```

Requires Python 3.8+.

## Usage
Run teh pipeline in this order:

## Usage

Run the pipeline in this order:

```bash
# 1. Scrape sources and build the master table
python tte_all_scrapers.py

# 2. Curate the LOINC measurement list
python curate_loinc.py

# 3. Generate the placeholder echo image (frame-navigation target)
python make_placeholder_image.py

# 4. Generate the three separate scheme-based reports
python tte_sr_generator.py --mode separate

# 5. Generate the combined "assembled-from-three" report
python tte_sr_generator.py --mode combined
```

## Viewing the Reports
Open placeholder_echo.dcm together with any of the .dcm SR files in
Weasis:

 - The SR tree displays all measurements grouped by anatomy.
 - Clicking a measurement jumps to the corresponding frame of the placeholder
echo cine, demonstrating the ReferencedSOPSequence frame navigation.

proekt2.0/
├── tte_all_scrapers.py
├── curate_loinc.py
├── make_placeholder_image.py
├── tte_sr_generator.py
├── requirements.txt
├── README.md
├── placeholder_echo.dcm
├── sr_loinc.dcm
├── sr_snomed.dcm
├── sr_dcm.dcm
├── sr_combined.dcm
├── tte_master_table.xlsx
├── tte_loinc_curated.json
├── tte_snomed_srt.json
├── tte_dcm.json
├── ucum_units.json
└── ucum-essence.xml/.zip
```

## License
This project is for academic/educational use. Coding-scheme data (LOINC, SNOMED
CT, DICOM, UCUM) remains subject to its respective owners' terms.
