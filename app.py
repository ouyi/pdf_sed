import argparse
import sys
import fitz  # PyMuPDF
import re
import json
import random
import string


class RedactionEngine:
    """
    Handles text replacement based on a list of (pattern, replacement) tuples.

    The core logic follows a strict 3-step process to ensure visibility:
    1. FIND: Locate text and save its properties (font, size, location).
    2. CLEAN: Apply redactions (draw white boxes over old text).
    3. WRITE: Insert new text on top of the white boxes.
    """

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
            # "dict" format gives us hierarchy: block -> line -> span -> char
            text_dict = page.get_text("dict")

            # Handle case where get_text returns a string (e.g., in some test mocks)
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
                        # We look for intersection to find the specific font used in this area
                        if span_rect.intersects(rect):
                            return span["size"], span["font"]
        except (AttributeError, KeyError, json.JSONDecodeError, TypeError):
            # If anything fails during font detection, just use defaults
            pass

        return font_size, font_name

    def redact_page(self, page):
        """
        Finds patterns on a page, cleans the area, and inserts new text.
        Crucial: Insertions happen AFTER redactions are applied.
        """
        text = page.get_text("text")
        matches = self.find_matches(text)

        # We need a queue to store text details.
        # If we insert text immediately inside the loop, the subsequent
        # page.apply_redactions() call would draw a white box over our NEW text.
        insertions_queue = []
        count = 0

        # Use set() to avoid processing duplicates multiple times if regex matches overlap
        for matched_text, replacement in set(matches):
            # Generate random string if replacement is None or empty
            if not replacement:
                replacement = "".join(
                    random.choices(
                        string.ascii_letters + string.digits, k=len(matched_text)
                    )
                )

            # Find all coordinates of the matched text on this page
            areas = page.search_for(matched_text)

            # Shrink the rectangle height by 10% to avoid hitting lines above/below
            for i in range(len(areas)):
                # .y1 is the bottom of the box, .y0 is the top.
                # We pull them slightly toward the middle.
                areas[i].y1 -= areas[i].height * 0.1
                areas[i].y0 += areas[i].height * 0.1

            for rect in areas:
                # 1. ANALYSIS: Capture font info from the original text
                font_size, font_name = self._get_font_info(page, rect)

                # 2. MARKING: Add the redaction annotation.
                # fill=(1, 1, 1) ensures the area becomes white after application.
                page.add_redact_annot(rect, fill=(1, 1, 1))

                # Store the insertion task for step 4
                insertions_queue.append(
                    {
                        "rect": rect,
                        "text": replacement,
                        "fontsize": font_size,
                        "fontname": font_name,
                    }
                )
                count += 1

        # 3. CLEANING: Apply the redactions.
        # This physically removes the old text and draws the white fill.
        # It MUST happen before we write the new text.
        page.apply_redactions()

        # 4. WRITING: Insert the new text onto the now-clean page
        for task in insertions_queue:
            rect = task["rect"]

            # Estimate baseline position (y0 + ascent adjustment)
            # 0.8 is a heuristic; exact baseline calc requires font metrics but this is usually sufficient
            text_point = fitz.Point(rect.x0, rect.y0 + task["fontsize"] * 0.8)

            try:
                # Try to use the original font name
                page.insert_text(
                    text_point,
                    task["text"],
                    fontsize=task["fontsize"],
                    fontname=task["fontname"],
                    color=(0, 0, 0),
                )
            except Exception:
                # If the specific font isn't embedded or recognized for writing,
                # fall back to standard Helvetica
                page.insert_text(
                    text_point,
                    task["text"],
                    fontsize=task["fontsize"],
                    fontname="helv",
                    color=(0, 0, 0),
                )

        return count

    def redact_pdf(self, input_path, output_path):
        """Process a PDF file and apply redactions based on patterns."""
        doc = fitz.open(input_path)
        total_redactions = 0

        for page in doc:
            # We process page by page.
            # Note: apply_redactions() is called INSIDE redact_page now.
            total_redactions += self.redact_page(page)

        # Save with high compression and garbage collection
        # garbage=4: Remove unused objects
        # deflate=True: Compress streams
        # clean=True: Standardize structure
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
        help="Text to replace the match with (e.g. '[ID]'). Use empty string '' for random text.",
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
