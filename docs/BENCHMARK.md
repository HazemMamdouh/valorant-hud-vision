# Benchmark report

Raw data: [`benchmark/benchmark.json`](benchmark/benchmark.json), [`benchmark/robustness.json`](benchmark/robustness.json), [`real_eval/results.json`](real_eval/results.json), and the demo reports [`real_eval/match_demo_replica.json`](real_eval/match_demo_replica.json) and [`real_eval/match_demo_real.json`](real_eval/match_demo_real.json). Charts are drawn by `python tools/make_figures.py`.

## Target vs. test machine

| | Target (brief) | Machine used for these numbers |
|---|---|---|
| CPU threads | 16 | **2** vCPUs, Intel Xeon @ 2.10 GHz (cloud VM) |
| RAM | 18 GB | 7.8 GB (runs capped at 18 GB with `RLIMIT_AS`) |
| Software | — | Linux 6.18, Python 3.13, OpenCV 5.0, NumPy 2.5 |

Everything here is **measured on the 2-vCPU machine**, except rows explicitly labelled *projection*. To replace the projections with measurements on the 16-thread box:

```bash
OMP_NUM_THREADS=1 python tools/benchmark.py --threads 16 --mem-limit-gb 18
python tools/make_figures.py
```

## 1. Per-frame latency (one 720p frame, one core)

| Pipeline | median | p95 |
|---|---|---|
| 2022 engine: 14 threads per frame + Tesseract ×2 | 158.0 ms | 196.7 ms |
| 2022 engine with OCR stubbed out | 9.2 ms | 25.9 ms |
| **v2, sequential (default)** | **2.58 ms** | **4.17 ms** |
| v2, persistent thread pool (2) | 3.37 ms | 8.12 ms |

v2 is about **61× faster** than the 2022 engine. It is slower than the 1.8 ms of the first v2 version because the real-HUD detectors do more work: a health-bar check per slot, carrier NCC over 10 cells, the teal colour gate. On real 16:10 frames the per-frame cost is ~4.5 ms, because padding to 16:9 adds a resize. Thread pools never help a single frame: each detector runs for 0.1–0.5 ms, less than a thread hand-off costs.

| Stage (median µs) | |
|---|---|
| roster (alive + health bar + identities on change) | 488 |
| resize + grayscale | 477 |
| HP + shield digits | 440 |
| spike planted + carrier NCC | 390 |
| abilities + ult (teal gate) | 283 |
| loadout | 255 |
| current agent (spectator HUD only) | 100 |

## 2. The engine server with 10 players (the match system)

| Measurement | Value |
|---|---|
| **Engine capacity, 10 sessions saturated** (decode + analyse + track, no network) | **151 frames/s = 15.1 fps for each of 10 players** on 2 vCPUs |
| Decode per 720p JPEG | ~3.7 ms on an idle core (8.3 ms while all ten workers compete) |
| Live demo, everything on one 2-vCPU box (engine + commentator + 10 senders + Chromium recording), 8 fps per player | 2,075 of ~2,240 frames analysed, 115 replaced by newer ones (newest-frame-wins) |
| Memory (PSS), 16 offline worker processes | 933 MB (~60 MB per worker) |

**Projection for the 16-thread target.** Ten players at 30 fps means 300 frames/s, at ~5.5–6 ms of CPU each (decode plus analysis) ≈ 1.8 cores. On 16 threads that is roughly **10–15% CPU, with headroom for over 1,000 frames/s**. Memory stays under 1 GB. The measured 2-vCPU capacity (151 frames/s) scaled by the measured efficiency (76%) gives ~900–1,200 frames/s for 16 threads.

## 3. Offline analysis throughput (one video, decode + analyse + track)

| Worker processes | fps | |
|---|---|---|
| 1 | 208.9 | |
| 2 | 246.1 | |
| 4 / 8 / 12 / 16 | 206.7 / 176.1 / 142.4 / 119.1 | oversubscribed on 2 vCPUs |

CPU per frame: 6.14 ms. *Projection* for 16 threads: 16 × 1000 / 6.14 × 0.756 (measured efficiency) ≈ **1,970 fps**, about 65× real time.

## 4. Accuracy on real 2022 screenshots (held-out split)

See [REAL_FOOTAGE.md](REAL_FOOTAGE.md).

| Field | v2 | 2022 engine |
|---|---|---|
| alive per slot | 99.6% | 99.3% |
| spike planted | 97.7% | 88.6% |
| spike carrier | 100% | 79.5% |
| ability charges | 96.8% | 95.9% |
| ult ready | 100% | 90.2% |
| HP | 92.1% | 94.7% |
| shield | 71.0% | 73.7% |

## 5. Fusion accuracy, 10-player replica round (live system, end to end)

`python tools/match_demo.py --mode replica --fps 12 --replay`. Ten sender processes, the engine server and the commentator server run on the 2-vCPU box at 12 fps per player; the POVs have real 2022 map views behind the replica HUD. The fused state is sampled at 5 Hz and counted correct if it matches ground truth within the last 0.6 s (pipeline lag).

| Fused field | Accuracy | Samples |
|---|---|---|
| player alive | 99.2% | 660 |
| player loadout | 99.3% | 440 |
| ult ready | 98.9% | 440 |
| spike planted | 98.5% | 66 |
| player C/Q/E | 95.7% | 440 |
| player HP | 94.8% | 440 |
| team alive count | 93.9% | 132 |
| spike carrier (which player) | 93.9% | 66 |

2,863 frames were analysed in 30 s (95 frames/s); 668 were replaced by newer ones (newest-frame-wins), because 120 frames/s were offered to 2 vCPUs that also ran all ten senders. Most misses happen at transitions: with every process sharing 2 vCPUs, some updates arrive more than 0.6 s late. Readings of individual frames are 100% on the replica (`samples/sample_2022q1_30s.analysis.json`).

## 6. Robustness on the replica (raw per-frame readings)

| Condition | 2022 engine (10 shared fields) | v2 (10 shared) | v2 (all 14 fields) | v2 weakest field |
|---|---|---|---|---|
| clean | 96.3% | 100.0% | 100.0% | — |
| stream compression (crf 35) | 91.7% | 96.1% | 97.2% | shield 78% |
| 540p source | 83.2% | 93.1% | 95.0% | shield 58% |
| 1080p source | 86.5% | 100.0% | 100.0% | — |
| Gaussian blur σ 1.2 | 52.9% | 87.5% | 91.1% | C 48%, shield 43% |
| darker (γ 1.4) | 52.6% | 97.5% | 98.4% | shield 77% |
| brighter (γ 0.7) | **94.5%** | 92.7% | 94.8% | shield 43% |
| sensor noise σ 10 | 95.5% | 99.9% | 99.9% | — |
| HUD offset 1 px | 93.3% | 100.0% | 92.9% | roster names 0% |
| HUD offset 3 px | 87.7% | 100.0% | 85.7% | primary 0%, roster names |

The 9 px shield digits are the weakest element in both real and degraded footage. HUD offsets now break agent names, because registration is off: its anchor does not exist in the player HUD.
