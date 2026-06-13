import pandas as pd
import pyarrow as pa

frame = pd.DataFrame(
    {
        "order_id": pd.Series(["O1", "O2"], dtype="string[pyarrow]"),
        "amount": pd.Series([1200.5, None], dtype="float64[pyarrow]"),
    }
)
table = pa.Table.from_pandas(frame, preserve_index=False)
returned = table.to_pandas(types_mapper=pd.ArrowDtype)

print("pandas:", {name: str(dtype) for name, dtype in frame.dtypes.items()})
print("Arrow:", table.schema)
print("roundtrip:", {name: str(dtype) for name, dtype in returned.dtypes.items()})
