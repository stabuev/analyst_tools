import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT.parent / "data" / "tiny" / "events_nested.json"


def reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Повторяющийся JSON key: {key}")
        result[key] = value
    return result


def reject_non_finite(value):
    raise ValueError(f"Недопустимое JSON number: {value}")


raw = SOURCE.read_bytes()
payload = json.loads(
    raw.decode("utf-8", errors="strict"),
    object_pairs_hook=reject_duplicate_keys,
    parse_constant=reject_non_finite,
)
print("SHA-256 исходных байтов:", hashlib.sha256(raw).hexdigest())
print("Envelope exported_at:", payload["exported_at"])

parent_rows = []
child_rows = []
for event in payload["events"]:
    parent_rows.append(
        {
            "event_id": event["event_id"],
            "user_id": event["user"]["id"],
            "occurred_at": event["occurred_at"],
            "device_os": event["context"]["device"]["os"],
            "screen": event["context"]["screen"],
        }
    )
    for item_position, item in enumerate(event["items"], start=1):
        child_rows.append(
            {
                "event_id": event["event_id"],
                "item_position": item_position,
                **item,
            }
        )

print("Ручной parent grain event_id:", len(parent_rows), "строки")
print("Ручной child grain (event_id, item_position):", len(child_rows), "строки")
print("У события E5002 пустой items:", payload["events"][1]["items"] == [])

parent_frame = pd.json_normalize(payload["events"], sep=".").drop(columns="items")
child_frame = pd.json_normalize(
    payload["events"],
    record_path="items",
    meta=["event_id"],
    record_prefix="item.",
    meta_prefix="event.",
)
child_frame.insert(
    1,
    "item_position",
    child_frame.groupby("event.event_id").cumcount() + 1,
)
print("pandas parent columns:", parent_frame.columns.tolist())
print("pandas child columns:", child_frame.columns.tolist())
print("pandas grains:", len(parent_frame), "events /", len(child_frame), "items")
