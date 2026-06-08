# Hệ thống lệnh SCPI cho Pendulum CNT-90XL

Tài liệu này lưu trữ danh mục các lệnh SCPI (Standard Commands for Programmable Instruments) được sử dụng để điều khiển máy đếm tần số Pendulum CNT-90XL.

Các lệnh này được chia thành các hệ thống chức năng chính:

---

## 1. Hệ thống Đo lường (Measurement System)

Sử dụng để thiết lập cấu hình và thực hiện các phép đo.

| Lệnh (Dài)   | Lệnh (Ngắn) | Mô tả                                                    |
| :----------- | :---------- | :------------------------------------------------------- |
| `:MEASure`   | `:MEAS`     | Thiết lập và thực hiện đo lường (kết hợp CONF + READ)    |
| `:CONFigure` | `:CONF`     | Chỉ thiết lập các thông số đo, không thực hiện đo ngay   |
| `:READ`      | `:READ`     | Thực hiện đo và đọc kết quả (dành cho cấu hình hiện tại) |
| `:FETCh`     | `:FETC`     | Truy xuất kết quả đo hiện có trong bộ nhớ đệm            |

---

## 2. Các hàm đo (Measurement Functions)

Các chức năng đo lường cụ thể được hỗ trợ.

| Lệnh (Dài)    | Lệnh (Ngắn) | Mô tả                                         |
| :------------ | :---------- | :-------------------------------------------- |
| `:FREQuency`  | `:FREQ`     | Đo tần số (Frequency)                         |
| `:PERiod`     | `:PER`      | Đo chu kỳ (Period)                            |
| `:TINTerval`  | `:TINT`     | Đo khoảng thời gian (Time Interval)           |
| `:PHASe`      | `:PHAS`     | Đo pha (Phase)                                |
| `:RISE:TIME`  | `:RTIM`     | Đo thời gian sườn lên (Rise Time)             |
| `:FALL:TIME`  | `:FTIM`     | Đo thời gian sườn xuống (Fall Time)           |
| `:PWIDth`     | `:PWID`     | Đo độ rộng xung dương (Positive Pulse Width)  |
| `:NWIDth`     | `:NWID`     | Đo độ rộng xung âm (Negative Pulse Width)     |
| `:PDUTycycle` | `:PDUT`     | Đo hệ số lấp đầy dương (Positive Duty Cycle)  |
| `:BTBack`     | `:BTB`      | Đo liên tục (Back-to-back)                    |
| `:TIError`    | `:TIE`      | Đo lỗi khoảng thời gian (Time Interval Error) |

---

## 3. Hệ thống Đầu vào (Input System)

Cấu hình các thông số vật lý cho các kênh đầu vào (A, B, E).

| Lệnh (Dài)     | Lệnh (Ngắn) | Mô tả                                         |
| :------------- | :---------- | :-------------------------------------------- |
| `:INPut`       | `:INP`      | Các cài đặt đầu vào chung                     |
| `:ATTenuation` | `:ATT`      | Độ suy giảm tín hiệu (Attenuation: 1x, 10x)   |
| `:COUPling`    | `:COUP`     | Kiểu ghép nối (AC/DC Coupling)                |
| `:IMPedance`   | `:IMP`      | Trở kháng đầu vào (Input Impedance: 50Ω, 1MΩ) |
| `:FILTer`      | `:FILT`     | Bộ lọc tín hiệu (Low-pass Filter)             |
| `:LEVel`       | `:LEV`      | Mức ngưỡng kích hoạt (Trigger Level)          |

---

## 4. Hệ thống Kích hoạt (Trigger System)

Điều khiển điều kiện bắt đầu và thực hiện phép đo.

| Lệnh (Dài) | Lệnh (Ngắn) | Mô tả                                   |
| :--------- | :---------- | :-------------------------------------- |
| `:ARM`     | `:ARM`      | Thiết lập điều kiện sẵn sàng đo         |
| `:TRIGger` | `:TRIG`     | Hệ thống kích hoạt đo                   |
| `:COUNt`   | `:COUN`     | Thiết lập số lần đo (Sample count)      |
| `:DELay`   | `:DEL`      | Thiết lập thời gian trễ (Trigger delay) |
| `:SOURce`  | `:SOUR`     | Chọn nguồn tín hiệu kích hoạt           |

---

## 5. Hệ thống Tính toán (Calculate System)

Xử lý dữ liệu sau khi đo (Hậu xử lý).

| Lệnh (Dài)   | Lệnh (Ngắn) | Mô tả                                                    |
| :----------- | :---------- | :------------------------------------------------------- |
| `:CALCulate` | `:CALC`     | Các phép tính toán hậu xử lý chung                       |
| `:AVERage`   | `:AVER`     | Các lệnh về thống kê/trung bình (Mean, StdDev, Max, Min) |
| `:LIMit`     | `:LIM`      | Giám sát các giới hạn đo (Pass/Fail testing)             |
| `:MATH`      | `:MATH`     | Các biểu thức toán học tùy chỉnh                         |

---

## 6. Hệ thống Chung (General System)

Quản lý cài đặt thiết bị và giao tiếp.

| Lệnh (Dài)     | Lệnh (Ngắn) | Mô tả                                           |
| :------------- | :---------- | :---------------------------------------------- |
| `:SYSTem`      | `:SYST`     | Cài đặt hệ thống chung                          |
| `:COMMunicate` | `:COMM`     | Cấu hình giao tiếp (GPIB/USB/LAN)               |
| `:ERRor`       | `:ERR`      | Truy vấn lỗi hệ thống (Error Queue)             |
| `:DISPlay`     | `:DISP`     | Điều khiển màn hình hiển thị (Bật/Tắt, Độ sáng) |
| `:FORMat`      | `:FORM`     | Định dạng dữ liệu phản hồi (ASCII, REAL)        |
