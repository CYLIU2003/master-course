# 実験レポート — 2026-03-16 15:47

## 条件一覧
- 実行日時: 2026-03-16 15:47
- 車両数 BEV: 3, ICE: 0
- タスク数: 225
- 充電器数: 2
- 時間刻み: 15 分 (80 スロット)
- PV 有効: False
- V2G 有効: False
- デマンド料金有効: True

## ソルバー結果
- ステータス: **OPTIMAL**
- 目的関数値: 15000.0
- MIP ギャップ: 0.0
- 計算時間: 0.00 秒

## 目的関数内訳
| 項目 | 値 [円] |
|------|---------|
| 電力量料金 | 0 |
| デマンド料金 | 0 |
| 燃料費 | 0 |
| 電池劣化 | 0 |
| **合計** | **127,500** |

## 主要 KPI
- タスク担当率: 28.9 %
- 未担当タスク: ['T_Weekday.0551', 'T_Weekday.0601__dup2', 'T_Weekday.0603', 'T_Weekday.0609', 'T_Weekday.0614', 'T_Weekday.0623', 'T_Weekday.0625', 'T_Weekday.0629', 'T_Weekday.0638', 'T_Weekday.0640', 'T_Weekday.0647__dup2', 'T_Weekday.0649', 'T_Weekday.0652', 'T_Weekday.0653', 'T_Weekday.0657__dup1', 'T_Weekday.0657__dup2', 'T_Weekday.0657__dup3', 'T_Weekday.0702', 'T_Weekday.0705__dup1', 'T_Weekday.0705__dup2', 'T_Weekday.0709', 'T_Weekday.0713', 'T_Weekday.0717', 'T_Weekday.0721', 'T_Weekday.0723', 'T_Weekday.0724', 'T_Weekday.0727', 'T_Weekday.0733', 'T_Weekday.0736', 'T_Weekday.0739', 'T_Weekday.0742', 'T_Weekday.0751', 'T_Weekday.0754', 'T_Weekday.0757', 'T_Weekday.0800', 'T_Weekday.0803', 'T_Weekday.0806', 'T_Weekday.0809', 'T_Weekday.0812', 'T_Weekday.0818', 'T_Weekday.0821', 'T_Weekday.0824', 'T_Weekday.0827', 'T_Weekday.0833', 'T_Weekday.0836', 'T_Weekday.0839', 'T_Weekday.0842', 'T_Weekday.0848', 'T_Weekday.0851', 'T_Weekday.0854', 'T_Weekday.0857', 'T_Weekday.0903', 'T_Weekday.0907', 'T_Weekday.0911', 'T_Weekday.0919', 'T_Weekday.0924', 'T_Weekday.0936', 'T_Weekday.0941', 'T_Weekday.0953', 'T_Weekday.0958', 'T_Weekday.1004', 'T_Weekday.1010', 'T_Weekday.1021', 'T_Weekday.1027', 'T_Weekday.1038', 'T_Weekday.1044', 'T_Weekday.1055', 'T_Weekday.1101', 'T_Weekday.1106', 'T_Weekday.1112', 'T_Weekday.1123', 'T_Weekday.1129', 'T_Weekday.1140', 'T_Weekday.1152', 'T_Weekday.1157', 'T_Weekday.1203', 'T_Weekday.1209', 'T_Weekday.1214', 'T_Weekday.1226', 'T_Weekday.1237', 'T_Weekday.1243', 'T_Weekday.1254', 'T_Weekday.1300', 'T_Weekday.1305', 'T_Weekday.1311', 'T_Weekday.1322', 'T_Weekday.1328', 'T_Weekday.1339', 'T_Weekday.1351', 'T_Weekday.1356', 'T_Weekday.1402', 'T_Weekday.1408', 'T_Weekday.1413', 'T_Weekday.1425', 'T_Weekday.1436', 'T_Weekday.1442', 'T_Weekday.1453', 'T_Weekday.1459', 'T_Weekday.1504', 'T_Weekday.1510', 'T_Weekday.1521', 'T_Weekday.1527', 'T_Weekday.1538', 'T_Weekday.1544', 'T_Weekday.1555', 'T_Weekday.1601', 'T_Weekday.1607', 'T_Weekday.1611', 'T_Weekday.1612', 'T_Weekday.1623', 'T_Weekday.1629', 'T_Weekday.1639', 'T_Weekday.1644', 'T_Weekday.1655', 'T_Weekday.1700', 'T_Weekday.1705', 'T_Weekday.1710', 'T_Weekday.1721', 'T_Weekday.1726', 'T_Weekday.1736', 'T_Weekday.1741', 'T_Weekday.1752', 'T_Weekday.1757', 'T_Weekday.1807', 'T_Weekday.1813', 'T_Weekday.1823', 'T_Weekday.1828', 'T_Weekday.1839', 'T_Weekday.1844', 'T_Weekday.1854', 'T_Weekday.1859', 'T_Weekday.1905', 'T_Weekday.1910', 'T_Weekday.1920', 'T_Weekday.1925', 'T_Weekday.1936', 'T_Weekday.1941', 'T_Weekday.1951', 'T_Weekday.1957', 'T_Weekday.2007', 'T_Weekday.2012', 'T_Weekday.2023', 'T_Weekday.2028', 'T_Weekday.2038', 'T_Weekday.2043', 'T_Weekday.2054', 'T_Weekday.2059', 'T_Weekday.2109', 'T_Weekday.2115', 'T_Weekday.2120', 'T_Weekday.2125', 'T_Weekday.2135', 'T_Weekday.2141', 'T_Weekday.2157', 'T_Weekday.2204', 'T_Weekday.2211', 'T_Weekday.2225', 'T_Weekday.2246', 'T_Weekday.2253', 'T_Weekday.2329']
- 系統受電量: 0.00 kWh
- PV 利用量: 0.00 kWh
- PV 自家消費率: 0.0 %
- ピーク需要: 0.00 kW
- CO2 排出: 0.00 kg
- 最低 SOC: 159.73 kWh
- SOC 違反: 0 件

## infeasible 情報
なし

---
*本レポートは result_exporter.py により自動生成されました。*
