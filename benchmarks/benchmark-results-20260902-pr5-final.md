# Adapter conversion benchmark results

2026年9月2日に、D-Wave PR #5の最終Adapter実装を取り込んだ状態で実施した
OMMX v2/v3ローカル分解測定の結果です。
D-Wave Leap tokenを使用しないため、end-to-end測定は対象外です。

## 結論

- v3 regularのv2比では、Instance → Modelの30ケースで時間が10.1%減、
  Result → Solutionの33ケースで時間が1.9%減でした。ピークメモリはそれぞれ20.3%減、23.1%減でした。
- v3 OneHotは同じv3 regular比で、Instance → Model時間が19.7%増、
  Result → Solution時間が7.7%増でした。ピークメモリはそれぞれ9.3%増、7.0%増でした。
- Preparation専用workloadのv3 directはv2比で、Instance → Model時間が37.7%増、
  Result → Solution時間が13.6%増でした。この比較には、v2の通常制約＋hintと
  v3のnative OneHot変換経路の差が含まれます。
- Preparation履歴によるInstance → Model差は時間0.1%減、メモリ0.0%でした。
  Result → Solutionは時間8.6%増、メモリ12.3%増でした。
- prepare単体は0.101〜0.999 ms、13.859〜109.289 KiBでした。
  prepare・変換・decodeを合算すると、preparedはdirect比で中央値19.2%増でした。

## 集約結果

比較率は各ケースについて
`(比較対象 - baseline) / baseline` を計算し、その中央値を示します。

| 比較 | Operation | 時間 | ピークメモリ | ケース数 |
| --- | --- | ---: | ---: | ---: |
| v3 regular / v2 | Instance → Model | 10.1%減 | 20.3%減 | 30 |
| v3 regular / v2 | Result → Solution | 1.9%減 | 23.1%減 | 33 |
| v3 OneHot / v3 regular | Instance → Model | 19.7%増 | 9.3%増 | 6 |
| v3 OneHot / v3 regular | Result → Solution | 7.7%増 | 7.0%増 | 6 |
| v3 direct / v2 counterpart | Instance → Model | 37.7%増 | 2.4%増 | 9 |
| v3 direct / v2 counterpart | Result → Solution | 13.6%増 | 15.9%減 | 18 |
| v3 prepared / v3 direct | Instance → Model | 0.1%減 | 0.0% | 9 |
| v3 prepared / v3 direct | Result → Solution | 8.6%増 | 12.3%増 | 18 |

## Preparation詳細

`direct合計` はdirectのModel変換とDecode、`prepared合計` はprepare、
preparedのModel変換、Decodeの各中央値を合算した値です。

| Case | Size | prepare ms | prepare KiB | direct合計 ms | prepared合計 ms | Δ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Indicator | 10 | 0.127 | 14.242 | 0.799 | 0.997 | 24.7%増 |
| Indicator | 20 | 0.443 | 49.908 | 2.399 | 2.980 | 24.2%増 |
| Indicator | 30 | 0.999 | 108.980 | 5.054 | 6.169 | 22.1%増 |
| SOS1 | 10 | 0.101 | 13.859 | 0.816 | 0.898 | 10.0%増 |
| SOS1 | 20 | 0.320 | 48.455 | 2.538 | 2.798 | 10.2%増 |
| SOS1 | 30 | 0.686 | 107.145 | 5.001 | 5.942 | 18.8%増 |
| Indicator + SOS1 | 10 | 0.110 | 15.184 | 0.788 | 0.910 | 15.5%増 |
| Indicator + SOS1 | 20 | 0.390 | 46.822 | 2.423 | 2.890 | 19.3%増 |
| Indicator + SOS1 | 30 | 0.826 | 109.289 | 5.083 | 6.061 | 19.2%増 |

## 測定条件

- 時間：ms。ウォームアップ3回後、20回の中央値
- メモリ：KiB。memrayによる2回目のピーク
- 初回時間・初回メモリはraw CSVへ保存
- seed：0
- solver：未使用。決定的な実行可能解からdimod SampleSetをローカル生成
- SampleSet：各ケース1サンプル
- `clique` と `one-hot-preparation` のdecodeサイズ：10 / 20 / 30 / 50 / 70 / 100
- Fixstars版はsolver結果をdecodeするため、Result → Solutionの絶対値はadapter間で直接比較しない
- v2：OMMX 2.6.1 / dimod 0.12.20 / Adapter `0.1.2.dev17+g7ba3e7899`
- v3：OMMX 3.0.0b4 / dimod 0.12.20 / Adapter `0.1.2.dev55+ga36ba935c`
- 全492測定が成功（v2: 198、v3: 294）
- raw CSV：各branchの `benchmark_results/20260902-pr5-final/`（git管理外）
