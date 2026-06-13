import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT.parent / "data" / "tiny" / "events_nested.json"
payload = json.loads(SOURCE.read_text(encoding="utf-8"))

manual = [
    {
        "event_id": event["event_id"],
        "user_id": event["user"]["id"],
        "device_os": event["context"]["device"]["os"],
    }
    for event in payload["events"]
]
print("Ручной grain event_id:", manual)

frame = pd.json_normalize(payload["events"], sep=".")
print("pandas columns:", frame.columns.tolist())
print("Массив items остался вложенным:", isinstance(frame.loc[0, "items"], list))
