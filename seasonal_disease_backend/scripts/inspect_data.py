import pandas as pd
import os

base = os.path.join(os.path.dirname(__file__), "..", "uploads")

for fname in ["train_history.xlsx", "predict_current.xlsx", "predict_current_2.xlsx"]:
    fpath = os.path.join(base, fname)
    print("=" * 80)
    print(f"FILE: {fname}")
    print("=" * 80)
    try:
        df = pd.read_excel(fpath)
        print(f"Shape: {df.shape}")
        print(f"Columns: {list(df.columns)}")
        print(f"Dtypes:\n{df.dtypes}")
        print(f"\nHead 5:\n{df.head()}")
        if "month" in df.columns:
            print(f"\nmonth describe:\n{df['month'].describe()}")
            print(f"month unique sample: {sorted(df['month'].dropna().unique())[:30]}")
        print()
    except Exception as e:
        print(f"Error: {e}")
