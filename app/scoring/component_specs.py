"""Version 1 component schema. Numeric field names carry explicit units."""
import math
from django.core.exceptions import ValidationError

CATEGORIES = ["riser", "limbs", "string", "sight", "stabiliser", "arrow_rest", "plunger", "clicker", "scope_peep", "damper", "release_tab", "other"]
STATUSES = ["active", "in_repair", "damaged", "lost", "retired", "sold", "archived"]
SCHEMA_VERSION = 1
# Optional positive finite numbers; counts must also be integers.
NUMBERS = {
    "riser": "length_in mass_g", "limbs": "marked_draw_weight_lb reference_length_in measured_draw_weight_lb",
    "string": "strand_count length_in", "sight": "extension_length_in",
    "stabiliser": "length_in mass_g weight_count", "arrow_rest": "", "plunger": "",
    "clicker": "length_mm", "scope_peep": "aperture_mm magnification", "damper": "mass_g",
    "release_tab": "", "other": "",
}
TEXT = {
    "riser": "handedness material interface", "limbs": "limb_length interface construction",
    "string": "material serving_notes brace_height_notes", "sight": "adjustment_notes",
    "stabiliser": "subtype angle_offset_notes", "arrow_rest": "subtype fit_notes setting_notes",
    "plunger": "spring setting_notes", "clicker": "subtype setting_notes", "scope_peep": "subtype",
    "damper": "subtype attachment_notes", "release_tab": "subtype size handedness fit_notes",
    "other": "label",
}

def validate_specs(category, specs):
    if category not in CATEGORIES or not isinstance(specs, dict):
        raise ValidationError("Choose a component category and a specification object.")
    numeric, text = NUMBERS[category].split(), TEXT[category].split()
    if set(specs) - set(numeric + text + ["discipline"] + (["attributes"] if category == "other" else [])):
        raise ValidationError("Unsupported specification field or unit for this category.")
    for key, value in specs.items():
        if key == "attributes":
            if not isinstance(value, dict) or len(value) > 20 or any(not isinstance(k, str) or not k.strip() or len(k) > 60 or not isinstance(v, str) or len(v) > 250 for k, v in value.items()):
                raise ValidationError("Other-accessory attributes need at most 20 short text key/value pairs.")
            continue
        if key in numeric:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValidationError(f"{key} must be a positive finite number in its named unit.")
            if key.endswith("count") and not float(value).is_integer():
                raise ValidationError(f"{key} must be an integer.")
        elif not isinstance(value, str) or not value.strip() or len(value) > 1000:
            raise ValidationError(f"{key} must be nonempty text of at most 1000 characters.")
        if key == "handedness" and value not in ("left", "right", "ambidextrous"):
            raise ValidationError("Invalid handedness.")
        if key == "discipline" and value not in ("recurve", "compound", "barebow"):
            raise ValidationError("Invalid discipline.")
