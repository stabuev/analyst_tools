import hashlib
import json

pages = [
    b'{"page": 1, "next": "page-2"}',
    b'{"page": 2, "next": null}',
]
checksums = [hashlib.sha256(page).hexdigest() for page in pages]
run_id = hashlib.sha256(json.dumps(checksums, sort_keys=True).encode()).hexdigest()[:16]

print("Raw checksums:", checksums)
print("Immutable dataset version:", run_id)
print("Atomic pointer:", {"run_id": run_id, "dataset": f"datasets/{run_id}/data"})
