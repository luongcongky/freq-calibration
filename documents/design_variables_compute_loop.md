# Thiết kế: Biến + Tính toán + Vòng lặp điều kiện cho Scenario

> Mục tiêu: nâng mô hình `core.scenario` từ "đặt/đo/lặp-cố-định/so-ngưỡng-thô"
> lên mức **xử lý số liệu + điều khiển vòng kín (closed-loop)**, đủ để chạy
> kịch bản **đo độ nhạy** khách yêu cầu.

## 1. Kịch bản đích (khách hàng)

Phép đo độ nhạy, vòng kín:

1. Đặt máy phát: tần số `f_set` (vd 100 GHz), công suất `p` (vd −5 dBm).
2. Đo tần số **3 lần**, mỗi lần cách **0,5 s**.
3. **Trung bình** 3 lần đo → `f_avg`.
4. **Tính sai số** tương đối `error = |f_avg − f_set| / f_set`.
5. **So ngưỡng** (`1e-8` / `1e-7`).
6. Nếu `error` lớn hơn ngưỡng → **tăng công suất theo bậc đều** (vd +0,5 dB)
   rồi **đo lại, lặp đến khi đạt**.

## 2. Khoảng trống hiện tại

| Cần | Hiện trạng |
|---|---|
| Trung bình nhiều lần đo | `_Ctx` chỉ giữ `last_value` — không tích lũy |
| Tính sai số (biểu thức) | Không có engine tính toán |
| So ngưỡng trên đại lượng dẫn xuất | `Condition` chỉ so `last_value` với hằng số |
| Lặp đến khi đạt | `LoopBlock.count` cố định, không while/until |
| Tăng tham số theo vòng | Tham số `raw_scpi` là hằng, không tham chiếu biến |

## 3. Thiết kế tổng quát

Thêm **4 trụ cột**, tất cả **cộng thêm (additive)** — không phá vỡ scenario cũ:

### 3.1 Biến runtime (variable store)
`core.scenario_runner._Ctx` thêm:
```python
variables: dict[str, Any] = field(default_factory=dict)   # scalar hoặc list[float]
loop_index: dict[str, int] = field(default_factory=dict)  # chỉ số vòng theo loop id
```
- Biến scalar (`f_set`, `error`…) và biến **list** (`samples`) để tích lũy.
- Reset/khởi tạo qua step `set_var`.

### 3.2 Engine biểu thức an toàn (`core/expr.py` — module mới)
Đánh giá biểu thức **KHÔNG dùng `eval` thô**. Dựa trên `ast` + danh sách trắng:
- Toán tử: `+ - * / % **`, đơn nguyên `-`, ngoặc.
- Hàm: `abs, sqrt, min, max, avg/mean, std, count, last` (last = phần tử cuối list).
- Toán hạng: số, tên biến (tra trong `variables`), `$last` (giá trị đo gần nhất),
  `$iter` (chỉ số vòng hiện tại của loop bao quanh).
- Chặn: gọi hàm lạ, thuộc tính, import, lambda… (duyệt AST, chỉ cho phép node an toàn).
- Lỗi runtime (chia 0, biến chưa định nghĩa) → ném `ExprError` → step LỖI, có thông báo rõ.

```python
evaluate("abs(f_avg - f_set)/f_set", ctx)      # -> float
evaluate("avg(samples)", ctx)                  # -> float
```

### 3.3 Step mới (đều `needs_device=False`, như `wait`)
Thêm vào `ACTION_SPECS` + `execute_action`:

| action | params | Ý nghĩa |
|---|---|---|
| `set_var` | `{name, expr}` | Gán `name = eval(expr)`. `expr="[]"` để khởi tạo list rỗng |
| `collect` | `{var, source}` | Nối giá trị vào list: `var.append(eval(source))` (mặc định `source="$last"`) |
| `compute` | `{target, expr}` | `target = eval(expr)` (tách riêng cho dễ đọc; cùng cơ chế set_var) |

> Gộp được: `collect` và `compute` chỉ là `set_var` ở dạng đặc thù; tách ra cho
> GUI/log dễ hiểu, nhưng dùng chung evaluator.

### 3.4 Điều kiện trên biểu thức (`Condition.kind = "expr"`)
Mở rộng `Condition`:
```python
kind: str            # "measure" | "status" | "expr"   (thêm "expr")
expr: str = ""       # dùng khi kind == "expr", vd "error"
# tái dùng: op, value, value2  (so sánh eval(expr) với value / [value,value2])
```
- `evaluate_condition` thêm nhánh `expr`: `v = evaluate(cond.expr, ctx)` rồi `_compare(v, op, value, value2)`.
- `kind="measure"` giữ nguyên (tương thích ngược).

### 3.5 Vòng lặp điều kiện — mở rộng `LoopBlock`
```python
mode: str = "count"          # "count" | "until"
condition: Optional[Condition] = None   # dùng khi mode=="until"
max_iter: int = 50           # chặn vòng vô hạn (an toàn)
# count giữ nguyên cho mode "count"
```
Ngữ nghĩa `until` (do-until): chạy body → đánh giá `condition`; **đạt thì dừng**,
chưa đạt thì lặp; chạm `max_iter` → dừng kèm cảnh báo (kết quả "không hội tụ").
- Runner đặt `ctx.loop_index[id(loop)] = i` mỗi vòng để biểu thức dùng `$iter`.

### 3.6 Tham số tham chiếu biến/biểu thức
`raw_scpi` (và `set_frequency`, `set_power`…) cho phép **giá trị tham số là biểu thức**:
- Quy ước: giá trị bắt đầu bằng `=` → là biểu thức, đánh giá lúc chạy.
  - `{"power": "=p_base + 0.5*($iter-1)"}` → tính theo vòng.
  - `{"Hz": "=f_set"}` → lấy từ biến.
- Không có `=` → hằng như cũ. (Tương thích ngược tuyệt đối.)
- `execute_action` resolve biểu thức trước khi `template.format(...)`.

## 4. Kịch bản độ nhạy diễn đạt bằng mô hình mới

```text
set_var   f_set = 100000000000
set_var   thr   = 1e-8
set_var   p     = -5
raw_scpi  SOUR1:FREQ:CW {Hz} HZ        params: Hz="=f_set"        [SMW200A]

LoopBlock mode=until, max_iter=20,
          condition: kind=expr  expr="error"  op="<="  value=thr
    raw_scpi  SOUR1:POW:POW {pw} dBm   params: pw="=p + 0.5*($iter-1)"  [SMW200A]
    set_var   samples = []
    LoopBlock count=3
        raw_scpi  MEAS:FREQ? (@1)      (query -> $last)            [CNT91]
        collect   samples <- $last
        wait      0.5
    compute   f_avg = avg(samples)
    compute   error = abs(f_avg - f_set)/f_set
# Sau vòng: error <= thr (đạt) hoặc chạm max_iter (không hội tụ)
```

> Lưu ý: thiết kế hiện cấm **lồng khối** (Loop/If trong Loop). Kịch bản này
> CẦN **Loop trong Loop** (until bao quanh count=3) → xem mục 7 (bỏ giới hạn 1 cấp).

## 5. Thay đổi dữ liệu & JSON (tương thích ngược)

- `ScenarioStep`: không đổi cấu trúc; chỉ thêm action mới + cho phép giá trị param
  dạng `"=..."`.
- `Condition.to_dict/from_dict`: thêm `kind="expr"`, `expr`. File cũ thiếu → mặc định.
- `LoopBlock.to_dict/from_dict`: thêm `mode`, `condition`, `max_iter`. File cũ:
  `mode="count"`, `condition=None`, `max_iter=50`.
- Scenario `.json` cũ vẫn nạp & chạy y nguyên.

## 6. Thay đổi Runner

1. `_Ctx`: thêm `variables`, `loop_index`; helper `set/get`.
2. `execute_action`: xử lý `set_var/collect/compute`; resolve param `"=..."` qua evaluator.
3. `evaluate_condition`: thêm nhánh `expr`.
4. `_run_loop`: nhánh `mode=="until"` (do-until + max_iter + set `$iter`).
5. Mỗi `compute/set_var` phát một `StepResult` (kind="control" hoặc "compute") để
   **log + report** hiển thị `error=…`, `f_avg=…` (định dạng số VN sẵn có).
6. Module mới `core/expr.py` (evaluator), có unit test riêng.

## 7. Bỏ giới hạn "không lồng khối"

Kịch bản đòi Loop-until **bao** Loop-count. Cần cho phép **lồng 1 thân**:
- `_run_loop`/`_run_if` cho phép body chứa Loop/If (đệ quy `_run_node`).
- Validate: cho phép lồng nhưng giới hạn độ sâu (vd ≤ 3) để tránh rối.
- GUI cây (Classic) đã là tree → render lồng được; Flow Editor: marker
  start/end đã có, cần cho phép marker lồng (state machine export dùng **stack**
  thay vì 1 mức).

## 8. Phơi bày trên GUI

**Classic (grid):**
- `StepEditorDialog`: thêm nhóm action **"Biến / Tính toán"** (`set_var, collect,
  compute`) với ô nhập tên biến + biểu thức (có gợi ý hàm).
- `LoopEditorDialog`: thêm lựa chọn **"Lặp đến khi (Until)"** + ô điều kiện + `max_iter`.
- `ConditionDialog`: thêm kiểu **"Biểu thức"** (nhập expr) cạnh "Đo"/"Trạng thái".
- Cho phép nhập param dạng `=biểu_thức` (hiển thị gợi ý).

**Digital (Flow Editor):**
- Node mới: **Var / Compute / Collect** (icon riêng).
- Loop marker hỗ trợ `until` (hiển thị điều kiện trên `loop_start`).
- Panel thuộc tính: ô biểu thức cho node tính toán; ô param hỗ trợ `=`.

## 9. An toàn & validate
- Evaluator AST whitelist (không thực thi mã tùy ý).
- `max_iter` bắt buộc cho until (mặc định 50, trần cứng vd 10000).
- Bắt chia 0 / biến chưa định nghĩa → báo lỗi rõ tại step, không treo.
- Validate trước khi chạy: parse mọi biểu thức; cảnh báo biến dùng trước khi gán
  (best-effort theo thứ tự tuyến tính).

## 10. Kế hoạch triển khai (phân pha)

| Pha | Nội dung | Đáp ứng bước | Trạng thái |
|---|---|---|---|
| **P1** | `core/expr.py` + evaluator + unit test | nền tảng | ✅ Done |
| **P2** | `_Ctx.variables`; action `set_var/collect/compute`; param `=expr`; `Condition.kind=expr` | bước 2,3,4 | ✅ Done |
| **P3** | `LoopBlock` until + `max_iter` + `$iter`; bỏ giới hạn lồng 1 cấp | bước 5,6 | ✅ Done |
| **P4** | GUI Classic (dialogs: StepEditor var-mode, Loop-until, Condition-expr) | dùng được tay | ✅ Done |
| **P5** | GUI Flow Editor (node Var/Compute, loop-until, export stack, lồng) | parity Digital | ✅ Done (trừ authoring biến trên canvas) |
| **P6** | Kịch bản độ nhạy đầy đủ `scenarios/scenario_do_do_nhay_full.json` + report biến + tài liệu | bàn giao | ✅ Done |

> **Đã hoàn tất toàn bộ.** Kịch bản đo độ nhạy vòng kín chạy được end-to-end
> (test `test_sensitivity_closed_loop` + file `scenario_do_do_nhay_full.json`).
> Còn lại tuỳ chọn: **Phase 5b** — thêm nút/panel soạn-sửa node Biến ngay trên
> canvas Flow Editor (hiện soạn ở Classic, Digital load/export trung thực).

> P1–P3 là **lõi** (không Qt, test được bằng pytest) — sau P3 đã chạy được kịch
> bản độ nhạy bằng file `.json`/script. P4–P5 là phần giao diện.

## 11. Rủi ro / lưu ý
- **Lồng khối** chạm nhiều chỗ (runner, validate, cả 2 GUI, export Flow) — là phần
  rủi ro nhất; nên làm cẩn thận, nhiều test.
- Biểu thức sai/đánh máy → cần thông báo lỗi thân thiện.
- Vòng until không hội tụ → `max_iter` + báo cáo "không đạt sau N vòng".
- Đo thật: trung bình 3 lần + delay 0,5 s phụ thuộc tốc độ máy đo (gate time);
  thời gian 1 vòng until = 3×(đo + 0,5 s) + overhead.
```
