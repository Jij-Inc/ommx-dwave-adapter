# Adapter conversion benchmark results

2026年9月2日に、D-Wave PR #5の最終Adapter実装を取り込んだ状態で実施した
OMMX v2/v3ローカル分解測定の結果です。
D-Wave Leap tokenを使用しないため、end-to-end測定は対象外です。

## 結論

- v3 regularのv2比では、30ケースの中央値でInstance → Model時間が10.2%減、
  Result → Solution時間が1.5%増でした。ピークメモリはそれぞれ20.3%減、23.1%減でした。
- v3 OneHotは同じv3 regular比で、Instance → Model時間が17.7%増、
  Result → Solution時間が5.7%増でした。ピークメモリはそれぞれ9.3%増、7.0%増でした。
- Preparation専用workloadのv3 directはv2比で、Instance → Model時間が35.7%増、
  Result → Solution時間が14.4%増でした。この比較には、v2の通常制約＋hintと
  v3のnative OneHot変換経路の差が含まれます。
- Preparation履歴によるInstance → Model差は時間0.6%減、メモリ0.0%でした。
  Result → Solutionは時間11.7%増、メモリ19.0%増でした。
- prepare単体は0.103〜1.014 ms、13.859〜109.289 KiBでした。
  prepare・変換・decodeを合算すると、preparedはdirect比で中央値20.1%増でした。

## 集約結果

比較率は各ケースについて
`(比較対象 - baseline) / baseline` を計算し、その中央値を示します。

| 比較 | Operation | 時間 | ピークメモリ | ケース数 |
| --- | --- | ---: | ---: | ---: |
| v3 regular / v2 | Instance → Model | 10.2%減 | 20.3%減 | 30 |
| v3 regular / v2 | Result → Solution | 1.5%増 | 23.1%減 | 30 |
| v3 OneHot / v3 regular | Instance → Model | 17.7%増 | 9.3%増 | 6 |
| v3 OneHot / v3 regular | Result → Solution | 5.7%増 | 7.0%増 | 6 |
| v3 direct / v2 counterpart | Instance → Model | 35.7%増 | 2.4%増 | 9 |
| v3 direct / v2 counterpart | Result → Solution | 14.4%増 | 19.2%減 | 9 |
| v3 prepared / v3 direct | Instance → Model | 0.6%減 | 0.0% | 9 |
| v3 prepared / v3 direct | Result → Solution | 11.7%増 | 19.0%増 | 9 |

## Preparation詳細

`direct合計` はdirectのModel変換とDecode、`prepared合計` はprepare、
preparedのModel変換、Decodeの各中央値を合算した値です。

| Case | Size | prepare ms | prepare KiB | direct合計 ms | prepared合計 ms | Δ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Indicator | 10 | 0.132 | 14.242 | 0.774 | 0.974 | 25.9%増 |
| Indicator | 20 | 0.434 | 49.908 | 2.432 | 2.920 | 20.1%増 |
| Indicator | 30 | 1.014 | 108.980 | 5.201 | 6.180 | 18.8%増 |
| SOS1 | 10 | 0.103 | 13.859 | 0.840 | 0.915 | 8.9%増 |
| SOS1 | 20 | 0.327 | 48.455 | 2.455 | 2.933 | 19.5%増 |
| SOS1 | 30 | 0.710 | 107.145 | 5.015 | 6.104 | 21.7%増 |
| Indicator + SOS1 | 10 | 0.123 | 15.184 | 0.825 | 0.944 | 14.4%増 |
| Indicator + SOS1 | 20 | 0.381 | 46.822 | 2.510 | 3.030 | 20.7%増 |
| Indicator + SOS1 | 30 | 0.876 | 109.289 | 5.114 | 6.142 | 20.1%増 |

## 測定条件

- 時間：ms。ウォームアップ3回後、20回の中央値
- メモリ：KiB。memrayによる2回目のピーク
- 初回時間・初回メモリはraw CSVへ保存
- seed：0
- solver：未使用。決定的な実行可能解からdimod SampleSetをローカル生成
- SampleSet：各ケース1サンプル
- Fixstars版はsolver結果をdecodeするため、Result → Solutionの絶対値はadapter間で直接比較しない
- v2：OMMX 2.6.1 / dimod 0.12.20 / D-Wave System 1.29.1 /
  Adapter `0.1.2.dev10+gf2984945e.d20260902`
- v3：OMMX 3.0.0b4 / dimod 0.12.20 / D-Wave System 1.29.1 /
  Adapter `0.1.2.dev48+gae7234ce4.d20260902`
- 全414測定が成功（v2: 168、v3: 246）
- raw CSV：各branchの `benchmark_results/20260902-pr5-final/`（git管理外）
