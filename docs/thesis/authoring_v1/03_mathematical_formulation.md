# 現行Phase 3の数理定式化

## 位置づけ

本章は正本SHAで実行された`phase3_two_stage`を説明する。研究目標として過去に記載された統合MILPではない。Stage 1は車両割当と時刻別エネルギーrecourseの緩和を解き、Stage 2は候補ごとに配車を固定して充電・PV・BESS・系統を解く。

## 集合・添字

- $v\in\mathcal V$: active vehicle、$\mathcal V^E$はBEV、$\mathcal V^I$はICE
- $i,j\in\mathcal J$: 便、正本では$|\mathcal J|=264$
- $(i,j)\in\mathcal A_v$: 車両$v$が実行できる便接続
- $t\in\mathcal T=\{0,\ldots,95\}$: 15分スロット
- $d\in\mathcal D$: 営業所、正本では弦巻のみ
- $c\in\mathcal C_d$: 充電器

接続集合は次を満たす場合だけ生成される。

$$a_i+\tau_i+\delta_{ij}^{dh}\le d_j \tag{EQ-CONNECT-01}$$

ここで$a_i$は到着時刻、$\tau_i$は折返し時間、$\delta_{ij}^{dh}$は回送時間、$d_j$は次便出発時刻である。

## Stage 1

### 変数

- $y_{vi}\in\{0,1\}$: 車両$v$が便$i$を担当
- $x_{vij}\in\{0,1\}$: $v$が$i$の後に$j$へ接続
- $s_{vi},e_{vi}\in\{0,1\}$: 便鎖の開始・終了
- $z_v\in\{0,1\}$: 車両使用
- $z_{vq}^{day}\in\{0,1\}$: 車両日使用
- $\widetilde q,\widetilde g,\widetilde p,\widetilde b$: 時刻別エネルギーrecourse緩和変数

### 目的関数

$$
\min J_1=
\widetilde C^{energy}(y)
+C^{fuel}(y,x)
+C^{vehicle}(z)
+C^{vehicle-day}(z^{day})
+C^{driver}+C^{degradation}+C^{switch}
\tag{EQ-OBJ-S1-01}
$$

$\widetilde C^{energy}$は`_add_stage1_time_indexed_energy_recourse_relaxation`が作る近似であり、Stage 2のcanonical costではない。正本では有効成分とゼロ成分をartifactから確認する。

### 便充足と便鎖

$$\sum_{v\in\mathcal V}y_{vi}=1\quad\forall i\in\mathcal J \tag{EQ-COVER-S1-02}$$

$$
\sum_{h:(h,i)\in\mathcal A_v}x_{vhi}+s_{vi}=y_{vi}
=\sum_{j:(i,j)\in\mathcal A_v}x_{vij}+e_{vi}
\tag{EQ-FLOW-S1-03}
$$

$$y_{vi}\le z_v,\qquad \sum_i s_{vi}\le F_v,\quad\sum_i e_{vi}\le F_v \tag{EQ-USE-S1-04}$$

重複する便対$\mathcal O$について、

$$y_{vi}+y_{vj}\le1\quad\forall v,(i,j)\in\mathcal O \tag{EQ-OVERLAP-S1-05}$$

である。正本は完全なfeasible successor networkを使い、successor pruningを用いない。

### ICE燃料

$$F^{I}_{v,t+1}=F^{I}_{v,t}+r_{v,t}-f^{trip}_{v,t}(y)-f^{dh}_{v,t}(x) \tag{EQ-FUEL-ICE-06}$$

$$F_v^{min}\le F^I_{v,t}\le F_v^{tank} \tag{EQ-FUEL-ICE-07}$$

Stage 1の目的には便、回送、出庫回送、返庫回送の燃料費とCO2価格を含む。正本の実行日燃料はRolling後の距離ベース在庫評価から再計算する。

## 候補生成と選択

Stage 1のpool、BEV frontier、車両構成近傍から候補集合$\mathcal K$を作る。正本の実効上限は22、composition radiusは4、BEV frontierは15～35台、120秒である。

$$k^*=\arg\min_{k\in\mathcal K_{feas}}\left(J_{2,k},N_k,H_k\right) \tag{EQ-SELECT-08}$$

$J_{2,k}$はcanonical cost、$N_k$は使用車両数、$H_k$は物理割当hashである。この辞書式選択は評価済み候補内だけで有効である。

## Stage 2

### 変数

- $q_{vt}\ge0$: BEV充電電力[kW]、$u_{vt}\in\{0,1\}$: 充電ON
- $S^E_{vt}$: BEV蓄電量[kWh]
- $G2Bus_{dt},PV2Bus_{dt},B2Bus_{dt}$: bus充電源[kWh]
- $G2B_{dt},PV2B_{dt},Curt_{dt}$: BESS充電とPV抑制[kWh]
- $S^B_{dt}$: BESS SOC[kWh]
- $m^{ch}_{dt},m^{dis}_{dt}\in\{0,1\}$: BESS充放電mode
- $W_d^{on},W_d^{off}$: 最大受電[kW]

### 固定配車とBEV SOC

Stage 2では$y,x$を変更しない。15分幅$\Delta=0.25$ h、充電効率$\eta_E=0.95$として、

$$S^E_{v,t+1}=S^E_{vt}+\eta_E q_{vt}\Delta-E^{drive}_{vt} \tag{EQ-SOC-BEV-09}$$

$$S^{E,min}_v\le S^E_{vt}\le S^{E,max}_v \tag{EQ-SOC-BEV-10}$$

$$q_{vt}\le P^{ch,max}_v u_{vt} \tag{EQ-CHARGE-11}$$

走行中、回送中、home depot不在時は$u_{vt}=0$である。出発時には便・回送・reserveを満たす下限を課す。正本では終端方針`return_to_initial`を全BEVへ適用する。

### 物理充電器

充電器割当$h_{vct}$と電力$p_{vct}$を用い、

$$\sum_c h_{vct}=u_{vt},\qquad q_{vt}=\sum_c p_{vct} \tag{EQ-CHARGER-12}$$

$$\sum_v h_{vct}\le Ports_c,\qquad \sum_vp_{vct}\le P_c^{rated} \tag{EQ-CHARGER-13}$$

である。正本は90 kW・1ポートの10基である。

### 電力収支

$$G2V_{vt}+PV2V_{vt}+B2V_{vt}=q_{vt}\Delta \tag{EQ-POWER-14}$$

$$G2Bus_{dt}=\sum_{v\in\mathcal V_d^E}G2V_{vt},\quad PV2Bus_{dt}=\sum_vPV2V_{vt},\quad B2Bus_{dt}=\sum_vB2V_{vt} \tag{EQ-POWER-15}$$

$$PV_{dt}=PV2Bus_{dt}+PV2B_{dt}+Curt_{dt} \tag{EQ-PV-16}$$

$$Grid_{dt}=G2Bus_{dt}+G2B_{dt}\le P_d^{grid}\Delta \tag{EQ-GRID-17}$$

正本では$G2B=0$であり、受電上限は200 kWである。

### BESS

$$S^B_{d,t+1}=S^B_{dt}+\eta_c(PV2B_{dt}+G2B_{dt})-\frac{B2Bus_{dt}}{\eta_d} \tag{EQ-SOC-BESS-18}$$

$$S^{B,min}_d\le S^B_{dt}\le S^{B,max}_d \tag{EQ-SOC-BESS-19}$$

$$PV2B_{dt}+G2B_{dt}\le P_d^B\Delta m^{ch}_{dt},\quad B2Bus_{dt}\le P_d^B\Delta m^{dis}_{dt} \tag{EQ-BESS-20}$$

$$m^{ch}_{dt}+m^{dis}_{dt}\le1 \tag{EQ-BESS-21}$$

$$S^B_{d,0}=3000,\qquad S^B_{d,96}=3000 \tag{EQ-BESS-TERM-22}$$

### Stage 2目的

$$
\min J_2=\sum_{d,t}\{c_t^{grid}(G2Bus_{dt}+G2B_{dt})+c^{Bcycle}B2Bus_{dt}+c^{PV}(PV2Bus_{dt}+PV2B_{dt})+c^{curt}Curt_{dt}\}+C^{demand}+C^{over}+C^{CO2}_{grid}
\tag{EQ-OBJ-S2-23}
$$

車両使用費と燃料費は固定配車のcanonical accountingへ加わるが、Stage 2の連続・二値電力変数を選ぶ`objective2`は上式の電力recourseである。

## Rollingと実行日会計

時刻$h=0,\ldots,23$で、固定配車、現在BEV SOC、BESS SOC、既発生peakを与え、残余時間を再最適化する。

$$\pi_h^*=\arg\min_{\pi_h\in\mathcal F(s_h)}J_{2,h}^{remaining}(\pi_h),\qquad s_{h+1}=T(s_h,\pi_h^*[h,h+1)) \tag{EQ-ROLL-24}$$

実行日費用は$J_{2,h}^{remaining}$を足さず、24個の実行prefixから96スロットをつないで一度だけ評価する。

$$J^{exec}=C^{vehicle-day}+C^{fuel}+C^{grid}+C^{CO2}+C^{enabled\ other} \tag{EQ-ACCOUNT-25}$$

正本では需要料金、運転士費、電池劣化費、PV/BESS設備費がゼロであり、`objective_is_actual_cost=false`である。

## 検算条件

$$N^{served}=264,\quad N^{unserved}=0 \tag{EQ-VALID-26}$$

$$\text{physical}=VALID,\quad \text{Rolling}=24/24,\quad |J^{ledger}-\sum_m C_m|\le10^{-6}\text{ JPY} \tag{EQ-VALID-27}$$

Stage 1 certified gapは$J_1$に対する証明であり、$J^{exec}$や統合問題のgapではない。
