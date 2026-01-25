import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add parent directory to path so we can import app.py reliably
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import RedactionEngine

class TestRedactor(unittest.TestCase):
    
    def test_engine_pairs(self):
        """Test that the engine handles multiple different patterns correctly."""
        # User wants to replace 'Bob' with 'Alice' and '123' with '000'
        pairs = [
            (r"Bob", "Alice"), 
            (r"\d{3}", "000")
        ]
        engine = RedactionEngine(pairs)
        
        text = "Bob lives at 123 Street."
        matches = engine.find_matches(text)
        
        # We expect matches for both patterns
        # Note: Order depends on which regex hits first in the loop
        expected = {("Bob", "Alice"), ("123", "000")}
        self.assertEqual(set(matches), expected)

    @patch("fitz.open")
    def test_pdf_redaction_flow(self, mock_open):
        """Test the integration with the PDF library logic."""
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_doc.__iter__.return_value = [mock_page]
        mock_open.return_value = mock_doc
        
        # 1. Simulate text on the page
        mock_page.get_text.return_value = "Depot DEP-999 is active."

        # 2. CRITICAL FIX: Simulate finding the text coordinates
        # We must return a list (e.g., [rect]) so the loop runs at least once.
        mock_page.search_for.return_value = [MagicMock()] 
        
        # Run with one pattern
        pairs = [(r"DEP-\d{3}", "[ID]")]
        engine = RedactionEngine(pairs)
        count = engine.redact_pdf("dummy.pdf", "out.pdf")
        
        # Verify it found 'DEP-999' and tried to redact it
        mock_page.search_for.assert_called_with("DEP-999")
        mock_page.draw_rect.assert_called()
        mock_page.insert_text.assert_called()

if __name__ == "__main__":
    unittest.main()