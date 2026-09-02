"""Metadata file writing."""

import json


def write_metadata(path, document):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2)
        handle.write("\n")


def write_tres(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
