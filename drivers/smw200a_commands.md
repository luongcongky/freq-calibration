# Hệ thống lệnh SCPI cho R&S SMW200A Vector Signal Generator

Tài liệu này lưu trữ danh mục các lệnh SCPI được sử dụng để điều khiển máy phát tín hiệu vector Rohde & Schwarz SMW200A.

---

## 1. Các lệnh chung (Common Commands)

Các lệnh tiêu chuẩn IEEE 488.2 dùng cho các chức năng cơ bản.

| Lệnh           | Mô tả                                                                 |
| :------------- | :-------------------------------------------------------------------- |
| `*CLS`         | Xóa trạng thái (Clear status)                                         |
| `*ESE`         | Thiết lập thanh ghi cho phép trạng thái sự kiện (Event status enable) |
| `*ESR?`        | Đọc thanh ghi trạng thái sự kiện tiêu chuẩn                           |
| `*IDN?`        | Truy vấn nhận diện thiết bị (Manufacturer, model, serial, firmware)   |
| `*OPC / *OPC?` | Hoạt động hoàn tất (Operation complete)                               |
| `*OPT?`        | Truy vấn các tùy chọn (options) đã được cài đặt                       |
| `*RST`         | Khôi phục thiết bị về trạng thái mặc định (Reset)                     |
| `*SAV / *RCL`  | Lưu và nạp lại cấu hình từ bộ nhớ trung gian                          |
| `*STB?`        | Đọc byte trạng thái (Status byte query)                               |
| `*TRG`         | Lệnh kích hoạt (Trigger)                                              |
| `*TST?`        | Truy vấn tự kiểm tra thiết bị (Self-test query)                       |
| `*WAI`         | Chờ cho đến khi tất cả các lệnh trước đó hoàn thành                   |

---

## 2. Hệ thống MMEMory (Quản lý tập tin)

Quản lý dữ liệu trên ổ cứng hoặc thiết bị nhớ USB.

| Lệnh                   | Mô tả                                                 |
| :--------------------- | :---------------------------------------------------- |
| `:MMEMory:CATalog?`    | Liệt kê các tệp tin trong thư mục                     |
| `:MMEMory:CDIRectory`  | Thay đổi thư mục mặc định                             |
| `:MMEMory:COPY`        | Sao chép tệp tin                                      |
| `:MMEMory:DATA`        | Truyền dữ liệu tệp tin giữa bộ điều khiển và thiết bị |
| `:MMEMory:DELete`      | Xóa tệp tin                                           |
| `:MMEMory:MDIRectory`  | Tạo thư mục mới                                       |
| `:MMEMory:MOVE`        | Di chuyển hoặc đổi tên tệp tin                        |
| `:MMEMory:STORe:STATe` | Lưu cấu hình hiện tại vào một tệp tin xác định        |
| `:MMEMory:LOAD:STATe`  | Nạp cấu hình từ một tệp tin đã lưu                    |

---

## 3. Hệ thống SCONfiguration (Cấu hình hệ thống)

Thiết lập luồng tín hiệu và kịch bản MIMO.

| Lệnh                                                     | Mô tả                                                                 |
| :------------------------------------------------------- | :-------------------------------------------------------------------- |
| `:SCONfiguration:MODE`                                   | Chọn chế độ vận hành (Standard, Advanced, REG, GNSS,...)              |
| `:SCONfiguration:FADing`                                 | Định nghĩa cấu hình fading và định tuyến tín hiệu (MIMO 2x2, 4x4,...) |
| `:SCONfiguration:APPLy`                                  | Áp dụng các cài đặt cấu hình hệ thống vừa thiết lập                   |
| `:SCONfiguration:OUTPut:MAPPing:RF<ch>:STReam<st>:STATe` | Ánh xạ luồng tín hiệu (stream) tới đầu ra RF                          |
| `:SCONfiguration:EXTernal:REMote:SCAN`                   | Quét mạng để tìm các thiết bị ngoại vi kết nối                        |
| `:SCONfiguration:EXTernal:REMote:ADD`                    | Thêm thiết bị ngoại vi vào danh sách điều khiển                       |

---

## 4. Hệ thống SOURce (Cấu hình tín hiệu)

Điều khiển chi tiết các thông số của tín hiệu được tạo ra.

| Lệnh                                                | Mô tả                                  |
| :-------------------------------------------------- | :------------------------------------- |
| `:SOURce<hw>:FREQuency[:CW\|:FIXed]`                | Thiết lập tần số sóng mang RF          |
| `:SOURce<hw>:POWer[:LEVel][:IMMediate][:AMPLitude]` | Thiết lập mức công suất đầu ra         |
| `:SOURce<hw>:BB:EUTRa:STATe`                        | Bật/tắt chuẩn tín hiệu số (ví dụ: LTE) |
| `:SOURce<hw>:BB:ARBitrary:WAVeform:SELect`          | Chọn tệp waveform (ARB) để phát        |
| `:SOURce<hw>:IQ:STATe`                              | Kích hoạt điều chế I/Q                 |

---

## 5. Hệ thống OUTPut (Điều khiển đầu ra)

Bật/tắt và bảo vệ đầu ra RF.

| Lệnh                           | Mô tả                                            |
| :----------------------------- | :----------------------------------------------- |
| `:OUTPut<hw>[:STATe]`          | Bật/tắt đầu ra RF của đường dẫn (path) tương ứng |
| `:OUTPut:ALL[:STATe]`          | Bật/tắt tất cả các đầu ra RF đồng thời           |
| `:OUTPut<hw>:PROTection:CLEar` | Xóa mạch bảo vệ sau khi bị kích hoạt quá tải     |

---

## 6. Hệ thống HUMS & DIAGnostic (Chẩn đoán và Giám sát)

Kiểm tra trạng thái sức khỏe và thông tin phần cứng.

| Lệnh                              | Mô tả                                               |
| :-------------------------------- | :-------------------------------------------------- |
| `DIAGnostic:HUMS:STATe`           | Bật/tắt hệ thống giám sát sức khỏe và sử dụng       |
| `DIAGnostic:HUMS:DEVice:HISTory?` | Truy vấn lịch sử hoạt động của thiết bị             |
| `:DIAGnostic:INFO:OTIMe?`         | Truy vấn số giờ hoạt động của máy                   |
| `:DIAGnostic<hw>:BGINfo?`         | Truy vấn thông tin chi tiết về các module phần cứng |

---

## 7. Hệ thống DISPlay & HCOPy (Hiển thị và Chụp màn hình)

| Lệnh                      | Mô tả                                                      |
| :------------------------ | :--------------------------------------------------------- |
| `:DISPlay:UPDate[:STATe]` | Bật/tắt cập nhật màn hình (tăng tốc độ điều khiển từ xa)   |
| `:DISPlay:DIALog:OPEN`    | Mở một hộp thoại cấu hình cụ thể trên giao diện người dùng |
| `:HCOPy:EXECute`          | Thực hiện chụp ảnh màn hình và lưu vào tệp tin             |

---

## 8. Nhóm đo lường (SENSe, READ, INITiate)

Sử dụng khi kết nối với cảm biến công suất (Power Sensor).

| Lệnh                               | Mô tả                                             |
| :--------------------------------- | :------------------------------------------------ |
| `:INITiate<hw>[:POWer]:CONTinuous` | Thiết lập chế độ đo công suất liên tục            |
| `:READ<ch>[:POWer]?`               | Kích hoạt và đọc kết quả đo công suất từ cảm biến |
| `:SLISt:SCAN[:STATe]`              | Tìm kiếm cảm biến R&S NRP trong mạng LAN hoặc USB |

---

> **Lưu ý**: Trong chế độ Advanced Mode với nhiều thực thể (entities), sử dụng tiền tố `ENTity<ch>:SOURce<hw>:...` để quản lý nhiều nguồn tín hiệu một cách logic.
