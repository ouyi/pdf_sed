import argparse
import sys
import fitz  # PyMuPDF
import re
import json


class RedactionEngine:
    """Handles text replacement based on a list of (pattern, replacement) tuples."""

    def __init__(self, pattern_pairs):
        # pattern_pairs is a list of tuples: [ (regex_str, replace_str), ... ]
        self.pairs = pattern_pairs

    def find_matches(self, text: str):
        """Returns a list of (found_text, replacement) tuples."""
        matches = []
        for pattern, replacement in self.pairs:
            try:
                found = re.findall(pattern, text)
                for item in found:
                    matches.append((item, replacement))
            except re.error as e:
                print(f"Warning: Invalid Regex '{pattern}': {e}", file=sys.stderr)
        return matches

    def _get_font_info(self, page, rect):
        """Extract font size and name from text at the given rectangle."""
        font_size = 12  # default font size
        font_name = "helv"  # default font

        try:
            text_dict = page.get_text("dict")

            # Handle case where get_text returns a string (e.g., in tests)
            if isinstance(text_dict, str):
                text_dict = json.loads(text_dict)

            # Search through blocks to find text overlapping with the rect
            for block in text_dict.get("blocks", []):
                if block.get("type") != 0:  # type 0 is text block
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        # Check if span overlaps with our rect
                        span_rect = fitz.Rect(span["bbox"])
                        if span_rect.intersects(rect):
                            font_size = span["size"]
                            font_name = span["font"]
                            return font_size, font_name
        except (AttributeError, KeyError, json.JSONDecodeError, TypeError):
            # If anything fails, just use defaults
            pass

        return font_size, font_name

    def redact_page(self, page):
        """Finds patterns on a page and applies physical redactions."""
        text = page.get_text("text")
        matches = self.find_matches(text)

        count = 0
        # Use set() to avoid trying to redact the same word twice on one page
        for pii_str, replacement in set(matches):
            areas = page.search_for(pii_str)
            for rect in areas:
                # Extract font size and name from the original text
                font_size, font_name = self._get_font_info(page, rect)

                # Draw a white rectangle to cover the original text
                page.draw_rect(rect, fill=(1, 1, 1), color=None)

                # Then insert the replacement text with the correct font size
                # Position the text at the top-left of the rect area
                text_point = fitz.Point(rect.x0, rect.y0 + font_size * 0.75)

                try:
                    # Try to use the original font name
                    page.insert_text(
                        text_point,
                        replacement,
                        fontsize=font_size,
                        fontname=font_name,
                        color=(0, 0, 0),
                    )
                except Exception:
                    # If font is not available, fall back to helvetica
                    page.insert_text(
                        text_point,
                        replacement,
                        fontsize=font_size,
                        fontname="helv",
                        color=(0, 0, 0),
                    )

                count += 1

        return count

    def redact_pdf(self, input_path, output_path):
        """Process a PDF file and apply redactions based on patterns."""
        doc = fitz.open(input_path)
        total_redactions = 0

        for page in doc:
            total_redactions += self.redact_page(page)

        doc.save(output_path, garbage=4, deflate=True, clean=True)
        doc.close()
        return total_redactions


def main():
    parser = argparse.ArgumentParser(
        description="Redact PDF using regex patterns.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("input", help="Input PDF path")
    parser.add_argument("output", help="Output PDF path")

    # action='append' allows the user to specify the flag multiple times
    parser.add_argument(
        "--pattern",
        action="append",
        required=True,
        help="Regex pattern to search for (e.g. 'DEP-\\d{3}')",
    )
    parser.add_argument(
        "--replace",
        action="append",
        required=True,
        help="Text to replace the match with (e.g. '[ID]')",
    )

    args = parser.parse_args()

    # Validate that every pattern has a corresponding replacement
    if len(args.pattern) != len(args.replace):
        print(
            "Error: The number of --pattern flags must match the number of --replace flags.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Zip them into pairs: [('p1', 'r1'), ('p2', 'r2')]
    pattern_pairs = list(zip(args.pattern, args.replace))

    try:
        engine = RedactionEngine(pattern_pairs)
        count = engine.redact_pdf(args.input, args.output)
        print(f"Done. {count} items redacted.")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
