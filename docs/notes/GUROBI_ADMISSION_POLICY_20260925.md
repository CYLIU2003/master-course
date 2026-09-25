# Gurobiの32GB制限と親機による枠管理

2026-09-25。ユーザー指示: Gurobiの利用は搭載32GB以上へ限定し、親機が同時利用枠を管理する。

## 確認した問題・変更

1. 既存resource_fitは空きRAMと要求RAMを検査するが、搭載32GB必須条件がなかった。`GetPhysicallyInstalledSystemMemory` による搭載容量を追加し、OS認識容量・空き容量と分離した。配置、起動直前、worker実行直前、通常ローカルGurobi取得で検査する。指定PC・小さいminimum_ram指定・license_testも迂回できない。非Gurobi経路は維持。
2. キュー内のLicenseBrokerにはSQLiteトランザクション、同時2枠、LOST保持、330秒cooldownが既にあるが、別controllerが別DBで2枠を持つ余地があった。親機ユーザー共通のauthorityファイルで管理キューを固定。serve_controller/get_scheduler/通常ローカル実行から設定し、各broker取得でも照合する。所有者は時間切れで移さず、他キューや破損時は取得不可。直接のLicenseBroker単体は低レベル部品で、実行入口ではauthorityを必ず設定する。
3. ライセンス失敗後に同じworkerへ次のケースを投入し続けるのを防ぐため、検証済み終了記録にGUROBI_LICENSE_UNAVAILABLEがあるworkerをdisabledにする。結果とcooldownは保存。解除は原因確認後の明示enable。単なる一時SSH失敗でこの処理は行わない。

## 呼出し経路

分散API → Scheduler.tick → resource_fit/WorkerRegistry → LicenseBroker.acquire（予約とSTAGINGの同一トランザクション）→ preflight → worker runner → admitted_cluster_attempt → guarded_execution → managed_gurobi_session。
通常ローカル実行・license_smoke → guarded_execution → local_license_callbacks → 同じauthority・キューのLicenseBroker → managed_gurobi_session。
一つのmanaged sessionでEnvを使い回し、モデル・Env破棄後に終了確認と解放待ちへ進む。通信不明は枠を保持し、別attemptの自動投入に読み替えない。

## 今回の稼働系への適用

- 8891の登録4台をread-only SSH/Windows APIで実測: local 32GB、desktop-6ae0mir 32GB、laptop-a709una0 32GB、desktop-3pru7qp 64GB。原記録: `output/monthly_latest_20260925/installed-ram-admission.json`。OS利用可能値31.70/31.74/31.53GBを32GBの証拠に丸めたわけではない。
- 64GB機は既知のライセンス失敗によるdisabledを保持。失敗理由はライセンス利用不可であり、同時枠超過と断定できる原エラーは保存されていない。新しいライセンス試験を実行中2枠へ追加していない。
- 旧8890は待機・稼働・不明のジョブ0をAPI確認。settingsから参照するconfigを退避しexternal_gurobi_slots=2へ設定、PIDと起動コマンドを照合して旧controller PID52180のみ停止。旧成果物・キューは保持。
- 8868はtotal2/external2/使用0、8891はtotal2/external0/使用2。現行の割当先と既存brokerでユーザーの制限を適用。authorityは8891の既存queueへ固定し、別queue拒否を実確認。
- 稼働中のcontroller PID27940と計算SHA cf4beb973169b2e0ecc771882838adb6d9bc58dcは保持。新しい強制検査コードをこの凍結版へ注入していない。main同期後の新しい固定版ではコードとして検査する。
- 今後も親機の同じ永続queueを管理正本に使う。違うqueueへの権限移動は自動化しない。新しい版へ切替時は実行中attemptとコードの一致を保つ既存手順に従う。

## 検証と限界

- 関連8ファイルのPythonテスト124件通過。16/24GB拒否、実搭載32GB＋OS31.5GB許可、空き不足拒否、固定PCのpreflight拒否、ローカルのEnv取得前拒否、10同時要求で2予約、通信断・再起動・cooldown保持、別controller拒否、license失敗worker隔離を含む。
- 画面テスト60件、TypeScript/Vite/Electron build通過。メモリ表示を搭載・OS認識・現在利用可能に分けた。旧workerから搭載容量の報告がない場合は未確認と表示する。
- 自己レビューの対象に残るP0/P1はなし。独立レビューは未実施。実Gurobiの新規起動は行わず、既存の2件を維持した。物理条件・入力・SOC・料金・数理モデルは不変。
- 管理アプリ外のGurobi利用はこのキューで制御できない。同じ資格情報の外部使用はexternal_gurobi_slotsへ予約する。ライセンス数・契約は今回増やしていない。

参照: [Windows搭載メモリAPI](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-getphysicallyinstalledsystemmemory)、[GurobiのWLSセッション・token寿命](https://support.gurobi.com/hc/en-us/articles/34567582787345-How-do-I-resolve-the-error-Too-many-sessions)。WLSはEnv終了とtoken失効の両方が必要で、即時の枠再利用としない。
