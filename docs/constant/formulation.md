# 混成フリート電気バス充電・運行スケジューリング統合最適化  
## 数理モデル定式化（MILP）

## ステータス
- 分類: 参考資料
- 用途: 混成フリート + PV を含む MILP 数理定式化を確認する
- 備考: UI や業務フローではなく定式化確認向け

**論文タイトル案：** Integrated Optimization of Charging and Vehicle Scheduling for a Mixed Bus Fleet with Operator-Owned PV  
**作成日：** 2026年3月  
**対象：** 日次（day-ahead）計画モデル / BEV・ICE混成フリート + 自前PV

---

## 0. モデルの全体像と想定

### 0.1 研究の位置づけ

本モデルは、BEV（電気バス）とICE（エンジンバス）が混在する**移行期フリート**を対象に、

- **便割当（Vehicle Scheduling）**：どの車両がどの便を担当するか
- **充電計画（Charging Scheduling）**：どの時刻に何kWh充電するか
- **電力配分（Power Allocation）**：PV自家発電と系統買電をどう使うか

の3層を**一体で最適化**する統合MILPである。  
計画粒度は**1日（day-ahead）**、時間刻みは$\Delta t$（例：15分または30分）とする。

### 0.2 モデル化範囲の確認（スコープ）

| 要素 | 本モデルでの扱い |
|------|----------------|
| 便時刻表（trip timetable） | 所与（固定入力） |
| BEVバッテリ容量 | 所与（固定パラメータ） |
| 充電拠点 | デポ中心（拠点充電を基本とする） |
| PV出力 | 決定論的予測値として入力 |
| 交通遅延 | 現フェーズでは非考慮（将来拡張） |
| 電池劣化 | 評価指標として計算（将来目的関数化） |
| HEV | 将来拡張（諸元データ入手後） |

### 0.3 想定車両諸元（参考値）

| 区分 | 車種 | 電池容量 | 最大充電出力 | 航続距離 |
|------|------|----------|------------|---------|
| BEV | BYD K8 2.0 | 314 kWh | 90 kW以下 | 240 km |
| BEV | Jバス ブルーリボンEV | 242 kWh | 50 kW以下 | 360 km |
| BEV | Jバス エルガEV | 242 kWh | 50 kW以下 | 360 km |
| ICE | Jバス ブルーリボン | — | — | 燃費5.35 km/L |
| ICE | Jバス エルガ | — | — | 燃費5.35 km/L |
| ICE | 三菱ふそう エアロスター | — | — | 燃費4.52 km/L |

---

## 1. Sets（集合）

### 1.1 車両・便

| 記号 | 定義 |
|------|------|
| $\mathcal{K}$ | 全車両集合（$k \in \mathcal{K}$） |
| $\mathcal{K}^{BEV} \subset \mathcal{K}$ | BEV車両集合 |
| $\mathcal{K}^{ICE} \subset \mathcal{K}$ | ICE車両集合（$\mathcal{K}^{BEV} \cup \mathcal{K}^{ICE} = \mathcal{K}$，互いに素） |
| $\mathcal{H}$ | 車両タイプ集合（$h \in \mathcal{H}$） |
| $\mathcal{K}_h$ | タイプ $h$ の車両集合 |
| $\mathcal{J}$ | 全便（trip）集合（$j \in \mathcal{J}$，$\lvert\mathcal{J}\rvert = J$） |

> **便（trip）の定義：** 時刻表上の1回の運行単位。出発停留所・到着停留所・出発時刻・到着時刻・走行距離・消費エネルギーが付与される。

### 1.2 ネットワーク（時空間）

| 記号 | 定義 |
|------|------|
| $o$ | 仮想出庫ノード（source） |
| $d$ | 仮想入庫ノード（sink） |
| $\mathcal{I}_1 = \mathcal{J} \cup \{o\}$ | 「出発側」ノード集合 |
| $\mathcal{I}_2 = \mathcal{J} \cup \{d\}$ | 「到着側」ノード集合 |
| $\mathcal{A}$ | 接続可能アーク集合（$a=(i,j) \in \mathcal{I}_1 \times \mathcal{I}_2$，$i \neq j$） |

**接続可能性の条件：** アーク $(i,j)$ が $\mathcal{A}$ に属するための時間整合条件は

$$
t_i^{arr} + t_{ij}^{dh} \leq t_j^{dep}
$$

ただし $t_i^{arr}$：便 $i$ の到着時刻，$t_{ij}^{dh}$：$i$ 終点から $j$ 始点への回送時間，$t_j^{dep}$：便 $j$ の出発時刻。

### 1.3 時間・電力

| 記号 | 定義 |
|------|------|
| $\mathcal{T} = \{1, 2, \ldots, T_{max}\}$ | 時間スロット集合（$t \in \mathcal{T}$） |
| $\Delta t$ | 1スロットの時間幅 [h]（例：0.25 h = 15分刻み） |
| $\mathcal{T}_k^{idle}$ | 車両 $k$ がデポに滞在（充電可能）な時刻スロット集合 |
| $\mathcal{T}_k^{run}(j)$ | 車両 $k$ が便 $j$ を走行中の時刻スロット集合 |
| $\mathcal{C}$ | 充電器集合（$c \in \mathcal{C}$） |
| $\mathcal{T}^{on} \subset \mathcal{T}$ | オンピーク時間スロット集合 |
| $\mathcal{T}^{off} \subset \mathcal{T}$ | オフピーク時間スロット集合（$\mathcal{T}^{on} \cup \mathcal{T}^{off} = \mathcal{T}$） |
| $\mathcal{Z}$ | デマンド計測期間集合（$\zeta \in \mathcal{Z}$），各期間長 $\gamma$ [h] |
| $\mathcal{T}_\zeta$ | デマンド期間 $\zeta$ に含まれる時間スロット集合 |

---

## 2. Parameters（パラメータ）

### 2.1 便・運行関連

| 記号 | 単位 | 説明 |
|------|------|------|
| $t_j^{dep}$ | h | 便 $j$ の出発時刻 |
| $t_j^{arr}$ | h | 便 $j$ の到着時刻（$t_j^{arr} = t_j^{dep} + \tau_j$） |
| $\tau_j$ | h | 便 $j$ の所要時間 |
| $l_j$ | km | 便 $j$ の走行距離 |
| $t_{ij}^{dh}$ | h | 便 $i$ 終点→便 $j$ 始点の回送（deadhead）時間 |
| $l_{ij}^{dh}$ | km | 同回送距離 |

### 2.2 BEV車両・電池関連

| 記号 | 単位 | 説明 |
|------|------|------|
| $E_k^{bat}$ | kWh | BEV $k$ の電池容量 |
| $\text{SOC}^{min}$ | — | SOC下限（例：0.20） |
| $\text{SOC}^{max}$ | — | SOC上限（例：0.95または1.00） |
| $e_k(j)$ | kWh | BEV $k$ が便 $j$ を走行したときの消費エネルギー |
| $e_k^{dh}(i,j)$ | kWh | BEV $k$ がアーク $(i,j)$ を回送したときの消費エネルギー |
| $P_k^{ch,max}$ | kW | BEV $k$ の最大充電電力 |
| $\eta_k^{ch}$ | — | BEV $k$ の充電効率（例：0.95） |

> **エネルギー消費の計算式（参考）：**
> $$e_k(j) = \eta_k^{drive} \cdot l_j \quad [\text{kWh}]$$
> ここで $\eta_k^{drive}$ [kWh/km] は走行消費率（車種・乗客数依存）。  
> より詳細なモデルでは乗客重量補正を加えることができる：  
> $$\eta_k^{drive}(j) = \eta_k^{base} + \alpha_k \cdot \bar{P}_j$$
> ただし $\bar{P}_j$：便 $j$ の平均乗客数，$\alpha_k$：乗客重量係数。

### 2.3 ICE車両関連

| 記号 | 単位 | 説明 |
|------|------|------|
| $f_k(j)$ | L | ICE車両 $k$ が便 $j$ を走行したときの燃料消費量 |
| $f_k^{dh}(i,j)$ | L | ICE車両 $k$ がアーク $(i,j)$ を回送したときの燃料消費量 |
| $c_f$ | 円/L | 燃料単価 |
| $\text{CO}_2^{ICE}$ | g-CO₂/km | ICEの単位走行CO₂排出係数 |
| $\text{CO}_2^{grid}$ | g-CO₂/kWh | 系統電力のCO₂排出係数 |

### 2.4 PV・電力関連

| 記号 | 単位 | 説明 |
|------|------|------|
| $PV_t$ | kW | 時刻スロット $t$ のPV発電電力（予測値，決定論的） |
| $p_t^{grid}$ | 円/kWh | 時刻スロット $t$ の系統買電単価（TOU） |
| $p^{dem,on}$ | 円/kW | オンピークのデマンド（最大需要電力）単価 |
| $p^{dem,off}$ | 円/kW | オフピークのデマンド（最大需要電力）単価 |
| $P^{contract}$ | kW | 営業所の系統受電容量（契約電力上限） |
| $N_c^{max}$ | 台 | 同時充電可能台数（充電器台数上限） |

---

## 3. Decision Variables（意思決定変数）

### 3.1 便割当（Vehicle Scheduling）

| 記号 | 型 | 説明 |
|------|----|------|
| $x_{ij}^k \in \{0,1\}$ | Binary | 車両 $k$ が便 $i$ の直後に便 $j$ を担当する（または $i=o$：最初の便，$j=d$：最後の便への返庫） |

> **解釈：**  
> - $x_{oj}^k = 1$：車両 $k$ が便 $j$ を最初の便として出庫する  
> - $x_{id}^k = 1$：車両 $k$ が便 $i$ を最後の便として帰庫する  
> - $x_{ij}^k = 1$（$i,j \in \mathcal{J}$）：車両 $k$ が便 $i$ の直後に便 $j$ を担当（直行または回送経由）

### 3.2 BEV充電（Charging）

| 記号 | 型 | 説明 |
|------|----|------|
| $z_{k,t} \geq 0$ | Continuous | BEV $k$ の時刻スロット $t$ での充電電力 [kW] |
| $\xi_{k,t} \in \{0,1\}$ | Binary | BEV $k$ が時刻スロット $t$ で充電している場合1（充電ON/OFFフラグ） |
| $\text{SOC}_{k,t}$ | Continuous | BEV $k$ の時刻スロット $t$ 終了時点でのSOC [—] |

### 3.3 電力配分（Power Allocation）

| 記号 | 型 | 説明 |
|------|----|------|
| $g_t \geq 0$ | Continuous | 時刻スロット $t$ の系統買電量 [kWh]（$= $ 系統買電電力 $\times \Delta t$） |
| $pv_t^{ch} \geq 0$ | Continuous | 時刻スロット $t$ にPV電力のうち充電へ割り当てた電力量 [kWh] |
| $pv_t^{sell} \geq 0$ | Continuous | 時刻スロット $t$ にPV電力のうち売電（余剰放出）した電力量 [kWh]（将来拡張） |

### 3.4 デマンド計算用

| 記号 | 型 | 説明 |
|------|----|------|
| $W^{on} \geq 0$ | Continuous | オンピーク最大需要電力 [kW] |
| $W^{off} \geq 0$ | Continuous | オフピーク最大需要電力 [kW] |
| $P_\zeta^{avg} \geq 0$ | Continuous | デマンド期間 $\zeta$ の平均需要電力 [kW] |

---

## 4. Constraints（制約条件）

### 4.1 便の割当整合（Trip Covering / Flow Conservation）

#### (C1) 各便は必ず1台の車両に担当される

$$
\sum_{k \in \mathcal{K}} \sum_{(i,j) \in \mathcal{A},\ j=\text{当該便}} x_{ij}^k = 1 \qquad \forall j \in \mathcal{J}
$$

**意味：** 任意の便 $j$ に対し，$j$ へ入るアークを持つ割当がちょうど1つ。どの便も必ず担当車両が存在し，重複も欠落もない。

#### (C2) フロー保存（便ノードで入流 = 出流）

$$
\sum_{i \in \mathcal{I}_1,\ (i,j)\in\mathcal{A}} x_{ij}^k = \sum_{l \in \mathcal{I}_2,\ (j,l)\in\mathcal{A}} x_{jl}^k \qquad \forall k \in \mathcal{K},\ \forall j \in \mathcal{J}
$$

**意味：** 車両 $k$ の便鎖（trip chain）が途切れない。ある便に「入った」車両は必ず「出る」。

#### (C3) 各車両は高々1回出庫し，高々1回入庫する

$$
\sum_{j \in \mathcal{J}} x_{oj}^k \leq 1 \qquad \forall k \in \mathcal{K}
$$

$$
\sum_{i \in \mathcal{J}} x_{id}^k \leq 1 \qquad \forall k \in \mathcal{K}
$$

**意味：** 各車両は1日に1本の便鎖のみ形成する（出庫・入庫は各1回）。

#### (C4) 接続可能なアークのみ選択可

$$
x_{ij}^k = 0 \qquad \forall k \in \mathcal{K},\ \forall (i,j) \notin \mathcal{A}
$$

**意味：** 時間的に間に合わない接続は構造的に禁止（事前に $\mathcal{A}$ を構築することで実現）。

#### (C5) 各時刻に1台の車両は1便以上担当しない（時間重複禁止）

$$
\sum_{j \in \mathcal{J}} x_{ij}^k \cdot \mathbb{1}[t \in \mathcal{T}_k^{run}(j)] \leq 1 \qquad \forall k \in \mathcal{K},\ \forall t \in \mathcal{T}
$$

**意味：** 同一車両が同じ時刻帯に2つの便を走ることはできない。

---

### 4.2 SOC（電池残量）制約（BEVのみ）

> 以下の制約は $k \in \mathcal{K}^{BEV}$ のみに適用する。

#### (C6) SOC遷移方程式（デポ滞在中：充電期間）

$$
\text{SOC}_{k,t} = \text{SOC}_{k,t-1} + \frac{\eta_k^{ch} \cdot z_{k,t} \cdot \Delta t}{E_k^{bat}}
\qquad \forall k \in \mathcal{K}^{BEV},\ \forall t \in \mathcal{T}_k^{idle}
$$

**意味：** デポ滞在中は充電によってSOCが増加する。効率 $\eta_k^{ch}$ を考慮した入力エネルギーで更新。

#### (C7) SOC遷移方程式（走行期間）

便 $j$ を担当する車両 $k$ の，便 $j$ **終了直後**のSOC：

$$
\text{SOC}_{k,\ t_j^{arr}} = \text{SOC}_{k,\ t_j^{dep} - 1} - \frac{e_k(j)}{E_k^{bat}} \cdot \sum_{i \in \mathcal{I}_1} x_{ij}^k
\qquad \forall k \in \mathcal{K}^{BEV},\ \forall j \in \mathcal{J}
$$

**Big-M形式（等価，MILPでの実装推奨）：**

$$
\text{SOC}_{k,\ t_j^{arr}} \leq \text{SOC}_{k,\ t_j^{dep} - 1} - \frac{e_k(j)}{E_k^{bat}} + M\left(1 - \sum_{i \in \mathcal{I}_1} x_{ij}^k\right)
\qquad \forall k,j
$$

$$
\text{SOC}_{k,\ t_j^{arr}} \geq \text{SOC}_{k,\ t_j^{dep} - 1} - \frac{e_k(j)}{E_k^{bat}} - M\left(1 - \sum_{i \in \mathcal{I}_1} x_{ij}^k\right)
\qquad \forall k,j
$$

**意味：** 便 $j$ を担当する（$\sum x_{ij}^k = 1$）場合のみ，走行消費でSOCが減少する。Big-M（$M = \text{SOC}^{max}$で十分）で条件付けする。

#### (C8) 回送（deadhead）によるSOC消費

アーク $(i,j)$ を通る場合の回送消費を反映：

$$
\text{SOC}_{k,\ t_j^{dep}} \leq \text{SOC}_{k,\ t_i^{arr}} - \frac{e_k^{dh}(i,j)}{E_k^{bat}} + M\left(1 - x_{ij}^k\right)
\qquad \forall k \in \mathcal{K}^{BEV},\ \forall (i,j) \in \mathcal{A}
$$

$$
\text{SOC}_{k,\ t_j^{dep}} \geq \text{SOC}_{k,\ t_i^{arr}} - \frac{e_k^{dh}(i,j)}{E_k^{bat}} - M\left(1 - x_{ij}^k\right)
\qquad \forall k \in \mathcal{K}^{BEV},\ \forall (i,j) \in \mathcal{A}
$$

**意味：** アーク $(i,j)$ が選ばれた場合のみ，便間の回送消費でSOCが更新される。

#### (C9) SOC上下限（常時）

$$
\text{SOC}^{min} \leq \text{SOC}_{k,t} \leq \text{SOC}^{max}
\qquad \forall k \in \mathcal{K}^{BEV},\ \forall t \in \mathcal{T}
$$

**意味：** 電池の過放電・過充電を防ぐための安全制約。電欠による欠便を防ぐ最重要制約。

#### (C10) 出庫時SOC（満充電）

$$
\text{SOC}_{k,\ 1} = \text{SOC}^{max} \cdot \sum_{j \in \mathcal{J}} x_{oj}^k
\qquad \forall k \in \mathcal{K}^{BEV}
$$

**意味：** 前夜のデポ充電が完了しており，翌日の運行開始時は満充電とする。

#### (C11) 帰庫後のSOC（翌日用確保）

$$
\text{SOC}_{k,\ T_{max}} \geq \text{SOC}^{min} \cdot \sum_{i \in \mathcal{J}} x_{id}^k
\qquad \forall k \in \mathcal{K}^{BEV}
$$

**意味：** 帰庫後（翌日への引き継ぎ）にも最低限のSOCを確保する。将来的には翌日必要SOCを明示的に設定可能。

---

### 4.3 充電スケジュール制約

#### (C12) 走行中は充電不可（運行と充電の排他）

$$
z_{k,t} = 0 \qquad \forall k \in \mathcal{K}^{BEV},\ \forall t \notin \mathcal{T}_k^{idle}
$$

等価形（Big-Mによる明示化）：

$$
z_{k,t} \leq P_k^{ch,max} \cdot \left(1 - \sum_{j \in \mathcal{J}} \mathbb{1}[t \in \mathcal{T}_k^{run}(j)] \cdot x_{ij}^k\right)
\qquad \forall k,t
$$

**意味：** 走行中は物理的に充電できない。デポ滞在時間帯のみ充電が可能。

#### (C13) 充電電力上限（充電器定格）

$$
0 \leq z_{k,t} \leq P_k^{ch,max} \cdot \xi_{k,t}
\qquad \forall k \in \mathcal{K}^{BEV},\ \forall t \in \mathcal{T}
$$

**意味：** 充電している場合（$\xi_{k,t}=1$）は最大充電電力以下，充電していない場合（$\xi_{k,t}=0$）はゼロ。

#### (C14) 同時充電台数制約（充電器台数上限）

$$
\sum_{k \in \mathcal{K}^{BEV}} \xi_{k,t} \leq N_c^{max}
\qquad \forall t \in \mathcal{T}
$$

**意味：** 同一時刻に充電中の車両台数は充電器台数を超えない。

---

### 4.4 電力バランス・PV利用制約

#### (C15) 電力バランス（供給 = 需要）

$$
g_t + pv_t^{ch} = \sum_{k \in \mathcal{K}^{BEV}} z_{k,t} \cdot \Delta t
\qquad \forall t \in \mathcal{T}
$$

**意味：** 時刻 $t$ における充電電力量は，系統買電量とPV利用量の合計で賄われる。

#### (C16) PV供給上限（PV発電量を超えて使用不可）

$$
pv_t^{ch} \leq PV_t \cdot \Delta t
\qquad \forall t \in \mathcal{T}
$$

**意味：** PVへの充電割当は実際の発電量（予測値）を超えられない。

#### (C17) 非逆潮流（系統への注入禁止，基本形）

$$
g_t \geq 0
\qquad \forall t \in \mathcal{T}
$$

**意味：** 系統から買電のみ（売電は現フェーズで考慮しない。将来的には $pv_t^{sell}$ 変数を追加して売電を許可可能）。

#### (C18) 系統受電容量上限（契約電力制約）

$$
\frac{g_t}{\Delta t} \leq P^{contract}
\qquad \forall t \in \mathcal{T}
$$

**意味：** 時刻 $t$ の系統受電電力（$g_t / \Delta t$ [kW]）が契約電力を超えない。

---

### 4.5 デマンドチャージ計算（需要料金）

#### (C19) デマンド計測期間の平均需要電力

$$
P_\zeta^{avg} = \frac{1}{\gamma} \sum_{t \in \mathcal{T}_\zeta} \frac{g_t}{\Delta t} \cdot \Delta t
= \frac{1}{\lvert\mathcal{T}_\zeta\rvert} \sum_{t \in \mathcal{T}_\zeta} \frac{g_t}{\Delta t}
\qquad \forall \zeta \in \mathcal{Z}
$$

**意味：** 各計測期間 $\zeta$（例：15分または30分ごと）の平均受電電力を定義する。

#### (C20) オンピーク最大需要電力（線形最大値）

$$
W^{on} \geq P_\zeta^{avg}
\qquad \forall \zeta \in \mathcal{Z}:\ \mathcal{T}_\zeta \cap \mathcal{T}^{on} \neq \emptyset
$$

**意味：** オンピーク時間帯の全デマンド期間の中での最大平均需要電力を $W^{on}$ が表す（線形最大値の定義）。

#### (C21) オフピーク最大需要電力（線形最大値）

$$
W^{off} \geq P_\zeta^{avg}
\qquad \forall \zeta \in \mathcal{Z}:\ \mathcal{T}_\zeta \cap \mathcal{T}^{off} \neq \emptyset
$$

**意味：** オフピーク時間帯の最大平均需要電力を $W^{off}$ が表す。

---

### 4.6 変数領域（Domain）

$$
x_{ij}^k \in \{0,1\} \qquad \forall k,\ \forall (i,j)
$$

$$
\xi_{k,t} \in \{0,1\} \qquad \forall k \in \mathcal{K}^{BEV},\ \forall t
$$

$$
z_{k,t} \geq 0 \qquad \forall k \in \mathcal{K}^{BEV},\ \forall t
$$

$$
0 \leq \text{SOC}_{k,t} \leq 1 \qquad \forall k \in \mathcal{K}^{BEV},\ \forall t
$$

$$
g_t,\ pv_t^{ch},\ W^{on},\ W^{off},\ P_\zeta^{avg} \geq 0 \qquad \forall t,\ \forall \zeta
$$

---

## 5. Objective Function（目的関数）

### 5.1 総コスト最小化

$$
\min \quad C_{total} = C_{fuel} + C_{elec} + C_{dem} + C_{veh}
$$

#### (O1) ICE燃料費

$$
C_{fuel} = c_f \sum_{k \in \mathcal{K}^{ICE}} \left[
\sum_{j \in \mathcal{J}} f_k(j) \sum_{i \in \mathcal{I}_1} x_{ij}^k
+ \sum_{(i,j) \in \mathcal{A}} f_k^{dh}(i,j) \cdot x_{ij}^k
\right]
$$

**意味：** ICE車両が担当した便の燃料消費量と回送時の燃料消費量の合計に単価を掛ける。

#### (O2) TOU電力料金（系統買電費）

$$
C_{elec} = \sum_{t \in \mathcal{T}} p_t^{grid} \cdot g_t
$$

**意味：** 時間帯別単価（TOU）と系統買電量の積の総和。安い時間帯（夜間・オフピーク）に充電を誘導する効果を持つ。

#### (O3) デマンド（最大需要電力）料金

$$
C_{dem} = p^{dem,on} \cdot W^{on} + p^{dem,off} \cdot W^{off}
$$

**意味：** オンピーク・オフピーク別の最大需要電力に対して課金される。ピーク需要の平滑化を誘導する。

#### (O4) 車両固定費（オプション）

$$
C_{veh} = \sum_{k \in \mathcal{K}} c_k^{veh} \cdot \left(\sum_{j \in \mathcal{J}} x_{oj}^k\right)
$$

**意味：** 使用する車両台数に比例する固定費（日割り減価償却費等）。$c_k^{veh} = 0$ として無視することも可能（車台数は便数から定まる場合）。

### 5.2 CO₂排出量（評価指標，目的関数化オプション）

$$
\text{CO}_2^{total} = \text{CO}_2^{ICE} \sum_{k \in \mathcal{K}^{ICE}} \sum_{j \in \mathcal{J}} l_j \sum_{i \in \mathcal{I}_1} x_{ij}^k
+ \text{CO}_2^{grid} \sum_{t \in \mathcal{T}} g_t
$$

**意味：** ICE走行由来のCO₂ + 系統電力由来のCO₂。PV自家消費分のCO₂はゼロとする。  
（将来的には $\epsilon$-制約法または重み付きで多目的化を検討。）

---

## 6. 完全なMILP定式化（まとめ）

$$
\min \quad C_{fuel} + C_{elec} + C_{dem} + C_{veh}
$$

**subject to:**

| 分類 | 制約番号 | 内容 |
|------|----------|------|
| 便割当 | (C1) | 各便の一意割当 |
| 便割当 | (C2) | フロー保存 |
| 便割当 | (C3) | 出庫・入庫各1回 |
| 便割当 | (C4) | 接続可能アークのみ |
| 便割当 | (C5) | 時間重複禁止 |
| SOC（BEV） | (C6) | SOC更新（デポ滞在中） |
| SOC（BEV） | (C7) | SOC更新（便走行後） |
| SOC（BEV） | (C8) | SOC更新（回送後） |
| SOC（BEV） | (C9) | SOC上下限 |
| SOC（BEV） | (C10) | 出庫時満充電 |
| SOC（BEV） | (C11) | 帰庫後SOC確保 |
| 充電 | (C12) | 走行中充電禁止 |
| 充電 | (C13) | 充電電力上限 |
| 充電 | (C14) | 同時充電台数上限 |
| 電力 | (C15) | 電力バランス |
| 電力 | (C16) | PV上限 |
| 電力 | (C17) | 非逆潮流 |
| 電力 | (C18) | 系統容量上限 |
| デマンド | (C19) | 平均需要電力定義 |
| デマンド | (C20) | オンピーク最大需要 |
| デマンド | (C21) | オフピーク最大需要 |
| 変数領域 | — | 二値・非負・SOC範囲 |

---

## 7. 先行研究との対応と本研究の差別化

| 機能要素 | 本研究 | 先行研究の代表 |
|----------|--------|--------------|
| BEV/ICE混成フリート | ✓（移行期） | No24のみ（BEV異種混在） |
| 自前PV利用 | ✓ | No35（マイクログリッド） |
| TOU料金 | ✓ | 多数が対応 |
| デマンド（需要）料金 | ✓ | No16（CESO），No55 |
| 便割当（配車） | ✓ | No06, No25等は除外 |
| デポ充電 | ✓ | 多数 |
| 日次計画 | ✓ | 多数 |
| ロバスト化（不確実性） | 将来拡張 | No24, No25, No26, No27 |
| 電池劣化 | 評価のみ（将来） | No16, No25, No27 |

---

## 8. MILPからALNSへの分解設計（実装指針）

### 8.1 外側（ALNS）：便割当変数 $x_{ij}^k$

- **Destroy操作（壊し操作）例：**
  - ランダム便選択：ランダムに $n$ 本の便を便鎖から取り外す
  - ルート帯域壊し（route-based destroy）：特定の路線・時間帯の便をまとめて取り外す
  - SOC逼迫壊し：SOC違反・余裕なし状態の周辺便を取り外す

- **Repair操作（修復操作）例：**
  - 貪欲挿入（greedy insert）：コスト増分最小の位置に便を挿入
  - Regret挿入（regret-based insert）：第2候補との差（regret値）が大きい便から優先挿入

### 8.2 内側（LP/MILP）：充電計画・電力配分

- $x_{ij}^k$ を固定したうえで，$z_{k,t},\ \xi_{k,t},\ g_t,\ pv_t^{ch},\ \text{SOC}_{k,t},\ W^{on},\ W^{off}$ を最適化
- $\xi_{k,t}$ を含むため内側はMILP（ただし $\xi_{k,t}$ を連続緩和すれば内側はLP）
- **連続緩和LPとして解く場合のポイント：** $\xi_{k,t} \in [0,1]$ と緩和し高速化。実際の整数解からの乖離は小さいことが多い（充電器台数制約が緩めであれば自然に0/1に近い解になる）。

### 8.3 フロー（全体構成）

```
入力データ（時刻表・車両諸元・PV時系列・料金）
    │
    ▼
初期解生成（Greedy便鎖構築）
    │
    ▼
ALNS外側ループ:
  1. Destroy: 一部の便割当 x_ij^k を取り外す
  2. Repair: 取り外した便を再挿入（実行可能便鎖を生成）
  3. Inner LP/MILP: 充電計画・電力配分を最適化
  4. 評価: 総コスト（C_fuel + C_elec + C_dem + C_veh）を計算
  5. 受容基準: コスト改善 or SA確率受容 → 解を更新
    │  終了条件（反復回数・時間制限）まで繰り返す
    ▼
最終解出力（車両別運行チャート・充電スケジュール・電力コスト）
```

---

## 9. 評価計画（比較ケース）

### 9.1 比較ケース設定

| ケース | 車両構成 | PV | 評価目的 |
|--------|----------|-----|---------|
| Case A | ICEのみ（現状） | なし | ベースライン（現在のコスト・CO₂） |
| Case B | BEV/ICE混成 | なし | PVなしでの混成運用効果 |
| Case C | BEV/ICE混成 | あり | PVありでの混成統合最適化（提案手法） |
| Case D | BEVのみ | なし | 完全BEV化の将来シナリオ |
| Case E | BEVのみ | あり | 完全BEV化＋PV（将来理想形） |

### 9.2 評価指標

| 指標 | 計算方法 | 目標方向 |
|------|----------|---------|
| 総コスト $C_{total}$ | 目的関数値 [円/日] | 最小化 |
| CO₂排出量 | $\text{CO}_2^{total}$ [kg-CO₂/日] | 最小化 |
| 欠便数（未達成便数） | SOC制約違反が生じた便の数 | ゼロ |
| 最大需要電力 | $\max(W^{on}, W^{off})$ [kW] | 最小化 |
| PV自家消費率 | $\sum_t pv_t^{ch} / \sum_t PV_t \Delta t$ [—] | 最大化 |
| BEV稼働率 | BEVが担当した便数 / 全便数 [—] | 参考 |

### 9.3 感度分析

以下のパラメータを変化させてロバスト性を確認する：

- PV容量（設置容量を0/50/100/200 kWp等で変化）
- BEV台数比率（フリート中のBEV割合）
- 充電器台数 $N_c^{max}$
- 契約電力 $P^{contract}$
- 電力単価（TOU条件の変化）

---

## 10. 実装に向けたチェックリスト

### MILP実装（小規模・妥当性確認）

- [ ] 便集合 $\mathcal{J}$ と車両集合 $\mathcal{K}$ の構築
- [ ] 接続可能アーク集合 $\mathcal{A}$ の事前計算（時間整合チェック）
- [ ] 時間スロット集合 $\mathcal{T}$ の離散化（時間刻み $\Delta t$ の決定）
- [ ] BEVのエネルギー消費 $e_k(j)$ の推定（路線・距離データから）
- [ ] PV時系列データの取得・前処理
- [ ] TOU料金テーブルの設定
- [ ] SOC制約の Big-M 定数の適切な設定（$M = \text{SOC}^{max}$ 程度）
- [ ] Gurobi/PuLP/OR-Tools 等のソルバーへの実装
- [ ] 小規模テストケース（便数10〜20本，BEV3〜5台）での動作確認
- [ ] 最適解の出力（車両別ガントチャート，SOC推移，電力時系列）

### ALNS実装（大規模・実用規模）

- [ ] Destroy演算子（ランダム，ルート帯域，SOC逼迫）の実装
- [ ] Repair演算子（貪欲挿入，Regret挿入）の実装
- [ ] 内側LP/MILPの呼び出し（Python-Gurobi等）
- [ ] 受容基準（SA：焼きなまし法の温度スケジュール設定）
- [ ] 演算子重みの適応更新（ALNSのスコアリング）
- [ ] 大規模ケース（便数100〜200本，BEV20台規模）での計算時間確認
- [ ] MILP厳密解との解品質比較（小規模で両方を実行してギャップを確認）

---

## 付録A：記号一覧（コーディング用対応表）

| 数学記号 | Python変数名（案） | 型 | 説明 |
|----------|-------------------|-----|------|
| $x_{ij}^k$ | `x[k,i,j]` | bool | 便割当変数 |
| $z_{k,t}$ | `z_charge[k,t]` | float | 充電電力 |
| $\xi_{k,t}$ | `xi_charge[k,t]` | bool | 充電ON/OFFフラグ |
| $\text{SOC}_{k,t}$ | `soc[k,t]` | float | SOC |
| $g_t$ | `grid_buy[t]` | float | 系統買電量 |
| $pv_t^{ch}$ | `pv_charge[t]` | float | PV充電割当 |
| $W^{on}$ | `W_peak_on` | float | オンピーク最大需要 |
| $W^{off}$ | `W_peak_off` | float | オフピーク最大需要 |
| $P_\zeta^{avg}$ | `P_avg[zeta]` | float | 期間平均需要 |
| $\mathcal{K}^{BEV}$ | `K_BEV` | list | BEV車両リスト |
| $\mathcal{K}^{ICE}$ | `K_ICE` | list | ICE車両リスト |
| $\mathcal{J}$ | `trips` | list | 便リスト |
| $\mathcal{A}$ | `arcs` | list | 接続可能アークリスト |
| $\mathcal{T}$ | `time_slots` | list | 時間スロットリスト |
| $PV_t$ | `pv_output[t]` | float | PV発電電力 |
| $p_t^{grid}$ | `price_grid[t]` | float | TOU単価 |
| $E_k^{bat}$ | `battery_cap[k]` | float | 電池容量 |
| $e_k(j)$ | `energy_trip[k,j]` | float | 便走行消費エネルギー |
| $N_c^{max}$ | `N_chargers` | int | 充電器台数 |
| $P^{contract}$ | `P_contract` | float | 契約電力 |
| $M$ | `BIG_M` | float | Big-M定数 |

---

## 付録B：接続グラフ構築アルゴリズム（疑似コード）

```python
# 接続可能アーク集合 A の構築
arcs = []

for k in K_BEV + K_ICE:
    # デポ出庫アーク
    for j in trips:
        if depot_time + deadhead(depot, trip_start[j]) <= dep_time[j]:
            arcs.append((k, 'o', j))
    
    # 便→便アーク
    for i in trips:
        for j in trips:
            if i != j:
                # 時間整合チェック
                available_time = arr_time[i] + deadhead(trip_end[i], trip_start[j])
                if available_time <= dep_time[j]:
                    # BEVの場合は追加でSOCの初期チェック（オプション）
                    arcs.append((k, i, j))
    
    # 便→デポ入庫アーク
    for i in trips:
        arcs.append((k, i, 'd'))

return arcs
```

---

## 付録C：感度分析の枠組み

デマンド料金の「ピーク電力」対コスト・PV自家消費率のトレードオフを確認するために以下の2軸分析を行う：

1. **横軸：PV容量** [kWp]：0, 50, 100, 150, 200 kWp
2. **縦軸：BEV比率** [%]：20%, 40%, 60%, 80%, 100%

各組合せに対して提案モデルを解き，総コスト・CO₂・最大需要電力のヒートマップを描画する。

---

*（本ドキュメントはコーディング移行前の仕様書として機能するよう設計されています。モデルの変更・拡張があれば本文を更新してください。）*
