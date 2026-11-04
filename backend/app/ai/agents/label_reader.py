"""Label Reader: reads the recipient address from a shipping-label photo. Extraction only;
plain code (F3) compares it with the PayPal protected address."""
from __future__ import annotations

from app.ai.agents.common import UNTRUSTED_RULES, image_evidence
from app.ai.provider import Part, Provider, StructuredResult, TextPart, generate_structured
from app.ai.schemas import LabelExtraction

PROMPT_VERSION = "lr-1.0"
AGENT = "label_reader"

SYSTEM_PROMPT = f"""\
You are the Label Reader for StayCovered. You read a photo or PDF of a parcel shipping label and copy
the RECIPIENT ("SHIP TO") details into the JSON schema exactly as printed or written.

{UNTRUSTED_RULES}
RULES:
- Recipient only. Ignore the sender/return ("FROM") address, barcodes' human-readable routing codes and postage text.
- Copy what is visible. Do not correct, complete or guess: if the ZIP is cut off, postal_code is null and its
  field_confidence is low. Never fill a field from general knowledge (e.g. do not infer a ZIP from a city).
- line1 = street number and name (or PO box); line2 = apartment/unit/suite/floor if present, else null.
- state = as printed (2-letter code for US if printed that way). country = ISO 3166-1 alpha-2 if printed
  or obviously domestic US (USPS/UPS/FedEx label with a US ZIP and state) else null.
- tracking_number_visible / carrier_visible: only if printed on the label.
- labels_detected: how many separate shipping labels are in the image. If more than one, read the most
  prominent one and add issue MULTIPLE_LABELS.
- readable: false if the recipient address cannot be read with reasonable certainty.
- issues: ROTATED, BLURRY, HANDWRITTEN, MULTIPLE_LABELS as observed.
- field_confidence per field and overall confidence: 0-1.
"""


def build_parts(upload_id: str, data: bytes, mime: str) -> list[Part]:
    return [TextPart("Read the shipping label in this evidence block.")] + image_evidence(
        upload_id, 1, "LABEL_IMAGE", data, mime
    )


def read_label(provider: Provider, upload_id: str, data: bytes, mime: str) -> tuple[StructuredResult[LabelExtraction], list[Part]]:
    parts = build_parts(upload_id, data, mime)
    return generate_structured(provider, SYSTEM_PROMPT, parts, LabelExtraction), parts
