import argparse
import sys
import fitz  # PyMuPDF
import re

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

    def redact_page(self, page):
        """Finds patterns on a page and applies physical redactions."""
        text = page.get_text("text")
        matches = self.find_matches(text)
        
        count = 0
        # Use set() to avoid trying to redact the same word twice on one page
        for pii_str, replacement in set(matches):
            areas = page.search_for(pii_str)
            for rect in areas:
                page.add_redact_annot(
                    rect, 
                    text=replacement, 
                    fill=(1, 1, 1), 
                    text_color=(0, 0, 0)
                )
                count += 1
        
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
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
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("input", help="Input PDF path")
    parser.add_argument("output", help="Output PDF path")
    
    # action='append' allows the user to specify the flag multiple times
    parser.add_argument("--pattern", action="append", required=True, 
                        help="Regex pattern to search for (e.g. 'DEP-\\d{3}')")
    parser.add_argument("--replace", action="append", required=True, 
                        help="Text to replace the match with (e.g. '[ID]')")

    args = parser.parse_args()

    # Validate that every pattern has a corresponding replacement
    if len(args.pattern) != len(args.replace):
        print("Error: The number of --pattern flags must match the number of --replace flags.", file=sys.stderr)
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