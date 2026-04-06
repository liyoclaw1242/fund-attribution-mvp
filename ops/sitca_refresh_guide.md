# SITCA 月度資料更新 SOP

每月更新 SITCA 基金持股資料的操作指南。

## 前置條件

- 可存取 SITCA 網站
- 本專案已 clone 至本機，且 `data/sitca_raw/` 目錄存在

## 步驟

### 1. 前往 SITCA 下載頁面

開啟瀏覽器，進入：

```
https://www.sitca.org.tw/ROC/Download/K0000.aspx
```

### 2. 選擇下載條件

- **資料類別**：選擇「基金持股明細」(FHS) 或「基金持股權重」(FHW)
- **期間**：選擇目標月份（通常為上個月）
- **基金代碼**：輸入需要更新的基金代碼，或選擇全部

點擊「下載」，取得 ZIP 檔案。

### 3. 解壓縮 ZIP

將下載的 ZIP 解壓縮，取得 Excel 檔案（`.xls` 或 `.xlsx`）。

```bash
cd ~/Downloads
unzip K0000_*.zip -d sitca_temp
```

### 4. 放入專案目錄

將解壓後的 Excel 檔案複製到 `data/sitca_raw/`：

```bash
cp sitca_temp/*.xls* /path/to/fund-attribution-mvp/data/sitca_raw/
```

建議以年月命名或保留原始檔名，方便追蹤：

```
data/sitca_raw/
├── FHS_202603.xlsx
├── FHS_202602.xlsx
└── ...
```

### 5. 驗證資料

啟動應用程式並確認資料可被正確解析：

```bash
cd /path/to/fund-attribution-mvp
python -c "
from data.sitca_parser import parse_sitca_excel
import glob

files = glob.glob('data/sitca_raw/*.xls*')
for f in files:
    try:
        df = parse_sitca_excel(f)
        print(f'{f}: {len(df)} rows OK')
    except Exception as e:
        print(f'{f}: ERROR - {e}')
"
```

確認每個檔案都能成功解析，且筆數合理。

### 6. 清理暫存

```bash
rm -rf ~/Downloads/sitca_temp
```

## 排程建議

SITCA 資料通常在每月 15 日後更新上月資料。建議於每月 16–20 日之間執行本 SOP。

## 常見問題

| 問題 | 解法 |
|------|------|
| ZIP 解壓後是 `.xls`（舊格式） | `sitca_parser.py` 支援 `.xls` 和 `.xlsx`，直接放入即可 |
| 找不到產業欄位 | 確認 Excel 表頭是否包含「產業」「產業類別」等欄位名稱，參考 `sitca_parser.py` 中的 `SITCA_INDUSTRY_COLS` |
| 權重總和不為 100% | Parser 會自動將百分比轉換為比例（除以 100），屬正常行為 |
