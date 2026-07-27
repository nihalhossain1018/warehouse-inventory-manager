# UI helper: turns a SKU or location code into an inline, scannable Code128
# barcode (SVG). Kept separate from the web layer since it's pure rendering,
# not a Flask route or a business rule.

import io
import barcode
from barcode.writer import SVGWriter

_OPTIONS = {
    "write_text": True,
    "module_height": 10,
    "module_width": 0.3,
    "quiet_zone": 2,
    "font_size": 8,
    "text_distance": 2,
}


def svg_for(code):
    """Render `code` as a Code128 barcode and return just the <svg>...</svg>
    markup (no XML prolog/DOCTYPE) so it can be embedded directly in a page."""
    buffer = io.BytesIO()
    barcode.Code128(code, writer=SVGWriter()).write(buffer, options=_OPTIONS)
    full_svg = buffer.getvalue().decode("utf-8")
    return full_svg[full_svg.index("<svg"):]
