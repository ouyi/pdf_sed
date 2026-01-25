# Installation

pip install -r requirements.txt

# Test
python -m unittest discover tests

# Run
python app.py input.pdf output.pdf \
  --pattern "DEP-\d{5}" --replace "[DEPOT-ID]" \
  --pattern "\d{5}\s[A-Za-z]+" --replace "[ADDRESS]"
