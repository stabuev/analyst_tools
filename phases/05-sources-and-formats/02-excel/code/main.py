from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = ROOT.parent / "data" / "tiny" / "orders_report.xlsx"

book = load_workbook(WORKBOOK, data_only=False)
sheet = book["Заказы"]
print("Листы:", book.sheetnames)
print("Merged cells:", [str(value) for value in sheet.merged_cells.ranges])
print("Формула G5:", sheet["G5"].value)

frame = pd.read_excel(
    WORKBOOK,
    sheet_name="Заказы",
    header=3,
    usecols="A:F",
    nrows=5,
    engine="openpyxl",
)
print("Табличная схема:", frame.columns.tolist())
print("Строк:", len(frame), "Сумма amount:", frame["amount"].sum())
