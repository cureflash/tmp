# STATUS

5ワーカーの進捗共有用。各ワーカーは実行開始時に必ず最新状態を読み、完了後に自分の行だけ更新する。

| Worker | 担当 | 次のtopic_id | 完了済み |
|---|---|---|---|
| 1 | LAW + RADL | LAW-01 | なし |
| 2 | NUC + RNUC | NUC-01 | なし |
| 3 | MAT + CYC | MAT-01 | なし |
| 4 | SAF + ACC | SAF-01 | なし |
| 5 | DET + WST + CAL/DES | DET-01 | なし |

## 成果物方針
- 作問結果は `kakunen-question-scope/questions/<topic_id>.md` に保存する。
- 1ファイルは1 topic_id。
- 各問題に問題文、正答、解説、出典、検証状態を含める。
- 一次資料で答えを確認できた問題のみ verified とする。
- 同じtopic_idの既存ファイルがある場合は内容を読んで重複を避け、未完成なら続きから進める。
