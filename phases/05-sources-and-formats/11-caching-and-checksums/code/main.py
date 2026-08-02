import hashlib
import json


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


source = {
    "page-1": canonical_bytes({"items": ["O2301", "O2302"], "next": "page-2"}),
    "page-2": canonical_bytes({"items": ["O2303"], "next": None}),
}
blobs = {}
cache_index = {}
current = None


def prepare_run(*, refresh=False, replacement=None):
    candidate_index = dict(cache_index)
    pages = []
    url = "page-1"
    fetched = 0
    while url is not None:
        if not refresh and url in cache_index:
            checksum = cache_index[url]
            body = blobs[checksum]
        else:
            body = (replacement or source)[url]
            checksum = digest(body)
            blobs[checksum] = body  # immutable blob; old digest remains available
            candidate_index[url] = checksum
            fetched += 1
        payload = json.loads(body)
        if set(payload) != {"items", "next"}:
            raise ValueError(f"invalid page contract: {url}")
        pages.append({"url": url, "sha256": checksum, "rows": len(payload["items"])})
        url = payload["next"]
    snapshot_id = digest(canonical_bytes(pages))
    run_id = digest(
        canonical_bytes(
            {
                "snapshot_id": snapshot_id,
                "schema": "schema-v2",
                "layout": "month-currency-v1",
                "pipeline": "orders-delivery-v1",
            }
        )
    )
    return candidate_index, {
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "fetched": fetched,
        "rows": sum(page["rows"] for page in pages),
    }


candidate_index, first = prepare_run()
cache_index = candidate_index
current = {"run_id": first["run_id"]}  # commit point after candidate verification
print("first run:", first)

candidate_index, replay = prepare_run()
cache_index = candidate_index
current = {"run_id": replay["run_id"]}
print("replay:", replay)

broken_source = dict(source)
broken_source["page-2"] = canonical_bytes({"records": ["O2303"], "next": None})
old_index = dict(cache_index)
old_current = dict(current)
try:
    prepare_run(refresh=True, replacement=broken_source)
except ValueError as error:
    print("failed refresh:", error)
print("old cache index preserved:", cache_index == old_index)
print("old current preserved:", current == old_current)
