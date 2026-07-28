# tests/test_utils.py
import os
import tempfile

from localmoderationmatrix.cli import (
    deobfuscate_token,
    load_targets_from_source,
    obfuscate_token,
    truncate_text,
)


def test_token_obfuscation():
    assert obfuscate_token("test123") == "MzIxdHNldA=="
    assert deobfuscate_token("MzIxdHNldA==") == "test123"


def test_truncate_text():
    assert truncate_text("CokUzunBirMesaj", 5) == "Co..."
    assert truncate_text("Kisa", 10) == "Kisa"


def test_load_targets_from_source():
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as tmp:
        tmp.write("spam\n")
        tmp.write("ads\n")
        tmp.write("scam\n")
        tmp.write("phishing\n\n")
        tmp_path = tmp.name

    targets = load_targets_from_source(tmp_path)
    os.remove(tmp_path)

    assert targets == {"spam", "ads", "scam", "phishing"}
