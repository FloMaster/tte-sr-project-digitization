#!/usr/bin/env python3
"""
make_placeholder_image.py
=========================
Creates a placeholder synthetic Ultrasound Multi-frame DICOM image that the SR
reports reference for frame navigation. Since the professor did not provide real
echo images, this synthetic cine stands in for them.

Output : placeholder_echo.dcm  (200-frame cine, fixed SOPInstanceUID)
"""
import pydicom
from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid
from datetime import datetime

US_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.3.1"   # Ultrasound Multi-frame Image

# Fixed UID so the SR generator can reference it reliably.
PLACEHOLDER_SOP_UID = "1.2.826.0.1.3680043.8.498.191990001.100000001"

FRAMES = 200
ROWS, COLS = 256, 256


def synth_pixel_bytes(n, rows, cols):
    """Return raw uint8 pixel bytes for a synthetic cine without numpy hard-dep.
    (Still fast enough for 200x256x256 = ~13 MB.)"""
    data = bytearray()
    cx, cy = cols / 2.0, rows / 2.0
    for i in range(n):
        ang = 2 * 3.14159265 * i / n
        pulse = 20 * __import__("math").sin(2 * 3.14159265 * i / 30.0)
        for y in range(rows):
            for x in range(cols):
                base = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                # rotating bright "sector" beam
                beam = max(0.0, min(255.0,
                                    80.0 + 120.0 * (1 + __import__("math").cos(
                                        x / cols * 2 * 3.14159265 - ang)) / 2))
                # pulsing "chamber" blob
                d = base - (30.0 + pulse)
                blob = max(0.0, min(200.0, 180.0 - d * d / 8.0))
                data.append(int(min(255.0, beam * 0.4 + blob)))
    return bytes(data)


def build_dcm():
    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID = US_SOP_CLASS
    file_meta.MediaStorageSOPInstanceUID = PLACEHOLDER_SOP_UID
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = "1.2.826.0.1.3680043.8.498.1"

    ds = FileDataset("placeholder_echo.dcm", {}, file_meta=file_meta,
                     preamble=b"\0" * 128)
    ds.SOPClassUID = US_SOP_CLASS
    ds.SOPInstanceUID = PLACEHOLDER_SOP_UID
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.PatientName = "Test^Patient"
    ds.PatientID = "SR001"
    ds.PatientSex = "O"
    ds.StudyDate = datetime.now().strftime("%Y%m%d")
    ds.StudyTime = datetime.now().strftime("%H%M%S")
    ds.Modality = "US"
    ds.SeriesNumber = "1"
    ds.InstanceNumber = "1"
    ds.ImageType = "ORIGINAL\\PRIMARY\\2D"
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.Rows = ROWS
    ds.Columns = COLS
    ds.NumberOfFrames = FRAMES
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.PixelData = synth_pixel_bytes(FRAMES, ROWS, COLS)
    ds.save_as("placeholder_echo.dcm", enforce_file_format=True)

    print("  ✓ placeholder_echo.dcm")
    print(f"    SOP Class : {US_SOP_CLASS}")
    print(f"    SOP UID   : {PLACEHOLDER_SOP_UID}")
    print(f"    Frames    : {FRAMES} ({FRAMES}x{ROWS}x{COLS} 8-bit gray)")
    return PLACEHOLDER_SOP_UID


if __name__ == "__main__":
    build_dcm()
