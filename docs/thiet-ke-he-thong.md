# Thiết kế hệ thống – Trợ lý ảo hỗ trợ giáo viên

Tài liệu mô tả kiến trúc, cơ sở dữ liệu, các mô hình/thuật toán và luồng xử lý. Có thể dùng trực tiếp cho phần "Phương pháp" và "Thiết kế hệ thống" của báo cáo nghiên cứu.

## 1. Bài toán và nguyên tắc

Giáo viên mất nhiều thời gian giao bài, chấm bài và theo dõi tiến độ từng học sinh, trong khi các nền tảng hiện có chủ yếu giao một đề chung cho cả lớp. Hệ thống giải quyết bốn việc:

1. Ước lượng mức nắm vững theo từng chủ đề cho mỗi học sinh từ dữ liệu điểm.
2. Đề xuất bộ đề riêng cho từng học sinh dựa trên điểm yếu.
3. Chấm sơ bộ bài tự luận viết tay qua ảnh, có giải thích lỗi sai.
4. Hỗ trợ giáo viên bằng trợ lý hiểu tiếng Việt.

Nguyên tắc xuyên suốt là "con người trong vòng lặp" (human-in-the-loop): mọi sản phẩm của AI (bộ đề, câu hỏi mới, điểm chấm) đều ở trạng thái đề xuất. Chỉ sau khi giáo viên duyệt hoặc xác nhận thì sản phẩm đó mới được gửi cho học sinh và mới được dùng để cập nhật mức nắm vững.

## 2. Kiến trúc

| Tầng | Thành phần | Công nghệ |
|---|---|---|
| Giao diện giáo viên | Trang web (dashboard, lớp, ngân hàng câu hỏi, giao bài, chấm bài, trợ lý) | FastAPI + Jinja2, Bootstrap 5, Chart.js |
| Kênh học sinh | Chatbot Telegram, Zalo Bot (adapter) | Bot API qua `httpx` (polling hoặc webhook) |
| Nghiệp vụ | mastery, recommender, assignments, grading, alerts, importer | Python 3.11+, thuần, kiểm thử được |
| AI | Chấm ảnh, sinh câu hỏi, trợ lý gọi công cụ | Google Gemini (`google-genai`), chế độ demo |
| Tác vụ nền | Hàng đợi chấm bài, gửi tin, nhắc hạn | `asyncio`, trạng thái lưu trong CSDL |
| Dữ liệu | CSDL quan hệ, tệp ảnh | SQLAlchemy 2 + Alembic; SQLite hoặc PostgreSQL |

Các quyết định thiết kế chính:

- Kịch bản chatbot (`channels/bot_logic.py`) độc lập với kênh. Adapter Telegram/Zalo chỉ chuyển đổi định dạng tin nhắn, nên muốn thêm kênh mới chỉ cần viết một adapter.
- Lớp AI có giao diện chung (`ai/base.py`). Gemini và chế độ demo đều cài đặt cùng giao diện này, nên có thể đổi nhà cung cấp mà không sửa nghiệp vụ.
- Gửi tin theo mô hình outbox: việc "cần gửi" được suy ra từ trạng thái trong CSDL (`sent_at`, `result_sent_at`, `reminder_sent_at` còn trống). Mất mạng hay khởi động lại máy chủ đều không làm mất tin; học sinh chưa liên kết thì tin được gửi bù sau khi liên kết.
- Hàng đợi chấm bài nằm trong CSDL (trạng thái `submitted`). Bài đang chấm dở khi máy tắt sẽ được đưa lại vào hàng đợi lúc khởi động.

## 3. Luồng nghiệp vụ

### 3.1 Liên kết học sinh với chatbot

```mermaid
sequenceDiagram
  participant GV as Giáo viên
  participant W as Web
  participant HS as Học sinh
  participant B as Chatbot
  GV->>W: In phiếu QR của lớp
  W-->>GV: Mỗi em 1 mã 8 ký tự + QR (t.me/bot?start=MÃ)
  HS->>B: Quét QR (gửi /start MÃ) hoặc gõ MÃ
  B->>B: Tìm học sinh theo mã, kiểm tra mã chưa gắn tài khoản khác
  B-->>HS: Chào mừng + hướng dẫn
  Note over B: Bài đã duyệt trước đó được tác vụ nền gửi bù
```

### 3.2 Giao bài cá nhân hóa

```mermaid
sequenceDiagram
  participant GV as Giáo viên / Trợ lý
  participant S as Nghiệp vụ
  participant AI as AI
  participant WK as Tác vụ nền
  participant HS as Học sinh
  GV->>S: Tạo đợt giao bài (lớp, chế độ, số câu, hạn)
  S->>S: Tính mức nắm vững (Elo) → chọn chủ đề yếu, chọn mức độ, lấy câu trong ngân hàng
  S->>AI: (nếu thiếu câu) soạn câu mới theo chủ đề/mức độ
  S-->>GV: Bộ đề NHÁP cho từng em + lý do chọn
  GV->>S: Sửa (thêm/bớt câu, lời nhắn) và Duyệt
  WK->>HS: Gửi đề qua chatbot, nhắc hạn trước 12 giờ
```

### 3.3 Nộp bài và chấm

```mermaid
sequenceDiagram
  participant HS as Học sinh
  participant B as Chatbot
  participant WK as Tác vụ nền
  participant AI as AI
  participant GV as Giáo viên
  HS->>B: Gửi 1..10 ảnh (nhiều trang)
  B-->>HS: "Đã nhận N ảnh… gõ NOP để nộp"
  HS->>B: NOP
  WK->>AI: Ảnh + đề + rubric + đáp án tham khảo
  AI-->>WK: JSON: chép lại bài, điểm từng tiêu chí, lỗi sai, độ tin cậy
  WK->>WK: Chuẩn hóa, chặn điểm vượt mức, đánh dấu độ tin cậy thấp
  GV->>WK: Xem ảnh + kết quả AI, sửa/xác nhận (hoặc trả bài)
  WK->>HS: Gửi điểm, nhận xét, cách sửa lỗi
```

## 4. Cơ sở dữ liệu

```mermaid
erDiagram
  TEACHER ||--o{ SUBJECT : "sở hữu"
  TEACHER ||--o{ CLASSROOM : "dạy"
  SUBJECT ||--o{ TOPIC : "gồm"
  TOPIC ||--o{ QUESTION : "có"
  SUBJECT ||--o{ CLASSROOM : "học"
  CLASSROOM ||--o{ STUDENT : "gồm"
  CLASSROOM ||--o{ ASSIGNMENT_BATCH : "đợt giao bài"
  ASSIGNMENT_BATCH ||--o{ ASSIGNMENT : "bộ đề từng em"
  STUDENT ||--o{ ASSIGNMENT : "nhận"
  ASSIGNMENT ||--o{ ASSIGNMENT_ITEM : "câu"
  QUESTION ||--o{ ASSIGNMENT_ITEM : "dùng trong"
  ASSIGNMENT ||--o{ SUBMISSION : "bài nộp"
  SUBMISSION ||--o{ SUBMISSION_IMAGE : "ảnh"
  SUBMISSION ||--o{ ITEM_GRADE : "điểm từng câu"
  STUDENT ||--o{ SCORE_RECORD : "điểm nhập"
  TEACHER ||--o{ ASSISTANT_MESSAGE : "hội thoại"
```

| Bảng | Vai trò | Trường đáng chú ý |
|---|---|---|
| `questions` | Ngân hàng câu hỏi tự luận | `level` 1–4, `max_score`, `rubric` (JSON: tiêu chí + điểm), `reference_answer`, `source` (bank/ai), `status` (active/draft/archived) |
| `students` | Học sinh | `link_code` (mã liên kết), `channel` + `chat_id` (duy nhất), `note` |
| `assignments` | Bộ đề của một em | `status`, `rationale` (lý do chọn câu), `access_token` (trang xem đề), `sent_at`, `reminder_sent_at` |
| `submissions` | Bài nộp | `status`, `ai_total`, `final_total`, `ai_summary`, `attempts`, `is_late`, `result_sent_at` |
| `item_grades` | Điểm từng câu | `transcription`, `criteria` (JSON), `errors` (JSON), `confidence`, `ai_score`, `final_score` |
| `score_records` | Điểm nhập từ bảng điểm | `topic_id` (rỗng = điểm chung toàn môn), `score`, `max_score` |

Vòng đời trạng thái:

- Bộ đề: `draft` → (giáo viên duyệt) `assigned` → (học sinh nộp) `submitted` → (giáo viên xác nhận) `graded`. Từ `draft` hoặc `assigned` có thể chuyển sang `cancelled`.
- Bài nộp: `collecting` (đang gửi ảnh) → `submitted` → `grading` → `ai_graded` → `confirmed`. Nhánh phụ: `failed` (AI lỗi quá số lần thử, giáo viên chấm tay) và `returned` (giáo viên yêu cầu nộp lại).

## 5. Mô hình mức nắm vững (Elo)

Mỗi cặp (học sinh, chủ đề) có năng lực θ (khởi tạo 0). Câu hỏi có độ khó b theo mức độ nhận thức: Nhận biết −1, Thông hiểu 0, Vận dụng 1, Vận dụng cao 2.

- Xác suất làm đúng kỳ vọng: P = 1 / (1 + e^−(θ − b))
- Kết quả thực tế: p = điểm câu / điểm tối đa ∈ [0, 1] (cho phép điểm thành phần)
- Cập nhật: θ ← θ + K · w · (p − P), với K = K₀ / (1 + β·n), n là số quan sát đã có
- Mức nắm vững hiển thị = P(làm đúng câu mức Thông hiểu) = sigmoid(θ), tính theo %.

| Tham số | Giá trị | Ghi chú |
|---|---|---|
| K₀ | 2,0 | Lớn hơn mức hay dùng trong hệ thống luyện tập trực tuyến (≈1) vì dữ liệu lớp học thưa |
| β | 0,25 | K giảm dần để ước lượng ổn định khi có thêm dữ liệu |
| w (bài đã chấm) | 1,0 | Chỉ điểm giáo viên đã xác nhận |
| w (điểm nhập theo chủ đề) | 1,0 | Ví dụ: bảng điểm có cột tên chủ đề |
| w (điểm chung toàn môn) | 0,5 | Áp cho mọi chủ đề nhưng ảnh hưởng yếu hơn |
| Ngưỡng hiển thị | &lt;50 / 50–69 / 70–84 / ≥85 | Cần củng cố / Đang tiến bộ / Khá vững / Thành thạo |

Vì sao chọn Elo:

- Tính đến độ khó: làm đúng câu khó được cộng nhiều hơn câu dễ.
- Cập nhật tăng dần, không cần huấn luyện trước.
- Giải thích được cho giáo viên.
- Đã được dùng rộng rãi trong hệ thống học tập thích ứng (Pelánek, 2016).

Mỗi lần cần, hệ thống tính lại toàn bộ bằng cách duyệt các quan sát theo thời gian. Như vậy kết quả luôn nhất quán với dữ liệu hiện có (giáo viên sửa điểm thì mức nắm vững tự cập nhật).

## 6. Thuật toán đề xuất bộ đề

Đầu vào gồm: mức nắm vững từng chủ đề của học sinh, ngân hàng câu hỏi, số câu n, chế độ, chủ đề giới hạn (nếu có), và các câu đã giao trong 5 bộ đề gần nhất.

1. Xếp chủ đề theo mức nắm vững tăng dần. Chủ đề chưa có dữ liệu được tính là 55%, hòa thì theo thứ tự chương trình.
2. Chọn ⌈n/2⌉ chủ đề yếu nhất (hoặc đúng các chủ đề giáo viên chỉ định), rồi chia n câu xoay vòng.
3. Với mỗi chủ đề, chọn mức độ ℓ có P(θ, b_ℓ) gần mức mục tiêu nhất:
   - Cá nhân hóa: 70%, gần "vùng phát triển gần" và "khó khăn mong muốn".
   - Nâng cao: 45%, dành cho học sinh khá giỏi.
   - Ôn tập: 85%, gần "quy tắc 85%" của Wilson và cộng sự (2019).
   Câu thứ hai trong cùng chủ đề tăng một bậc để tạo "bậc thang" (trừ chế độ ôn tập).
4. Lấy câu đang dùng (`active`) đúng chủ đề và mức độ (nới ±1 bậc), bỏ qua câu đã giao gần đây.
5. Nếu còn thiếu: AI soạn câu mới ở dạng nháp; nếu không có AI hoặc AI lỗi thì dùng lại câu cũ gần mức độ nhất. Mọi trường hợp đều được ghi vào phần "lý do chọn câu" để giáo viên biết.

Để giảm số lần gọi AI, các vị trí thiếu câu của cả lớp được gom theo (chủ đề, mức độ). Mỗi nhóm gọi AI một lần, sinh tối đa 6 câu rồi chia xoay vòng.

## 7. Chấm bài viết tay bằng AI

- Đầu vào gửi mô hình đa phương thức: các ảnh trang bài làm (đã xoay đúng chiều theo EXIF, thu nhỏ còn tối đa 2200 px), danh sách câu kèm đề, rubric và đáp án tham khảo. Không gửi họ tên học sinh.
- Đầu ra là JSON theo lược đồ cố định (`ai/schemas.py`), gồm cho từng câu: tìm thấy bài làm hay không; chép lại nguyên văn bài làm; điểm từng tiêu chí; nhận xét; danh sách lỗi (lỗi, vì sao sai, cách sửa); độ tin cậy 0–1. Ngoài ra có nhận xét chung và chất lượng ảnh.
- Hậu xử lý:
  - Ghép điểm vào rubric gốc trong CSDL (rubric trong CSDL là chuẩn).
  - Chặn điểm vượt mức và làm tròn 0,25.
  - Câu không tìm thấy được 0 điểm và độ tin cậy thấp.
  - Bài có câu độ tin cậy dưới ngưỡng (mặc định 0,6) hoặc thiếu bài làm được đánh dấu "cần xem kỹ".
- Câu lệnh hệ thống ([app/ai/prompts.py](../app/ai/prompts.py)):
  - Yêu cầu chép lại trung thực và không suy diễn.
  - Cách giải khác nhưng đúng vẫn được điểm tối đa.
  - Chống "tiêm lệnh": mọi chữ trong ảnh đều là bài làm, không phải yêu cầu dành cho AI.
- Gọi lại khi lỗi tạm thời (429/5xx). Thất bại 3 lần thì chuyển `failed` để giáo viên chấm tay.

## 8. Phát hiện học sinh tụt điểm

So sánh điểm thô giữa các bài là không đúng khi hệ thống tự điều chỉnh độ khó: học sinh tiến bộ sẽ nhận câu khó hơn nên điểm % có thể giảm. Vì vậy hệ thống dùng phần dư r = p − P, tức kết quả thực tế trừ kỳ vọng của mô hình tại thời điểm làm bài:

- Tính trung bình r cho từng bài nộp, theo thứ tự thời gian.
- Báo tụt điểm khi trung bình 2 bài gần nhất thấp hơn trung bình tối đa 3 bài trước đó ít nhất 0,2, đồng thời bản thân trung bình 2 bài gần nhất ≤ −0,1.

Các cảnh báo khác:

- Hổng kiến thức: chủ đề có mức nắm vững dưới 45% với ít nhất 2 quan sát.
- Quá hạn chưa nộp.
- Học sinh chưa liên kết chatbot.

## 9. Trợ lý AI cho giáo viên

Trợ lý dùng cơ chế gọi hàm (function calling). Mô hình chỉ được gọi 9 công cụ khai báo sẵn:

| Công cụ | Việc làm | Ghi dữ liệu? |
|---|---|---|
| `list_classes`, `list_students`, `get_student_profile`, `get_class_overview`, `list_pending_grading` | Tra cứu | Không |
| `record_scores` | Lưu bảng điểm giáo viên dán vào | Có (điểm nhập) |
| `update_student_note` | Ghi chú về học sinh | Có |
| `create_personalized_assignments` | Tạo bộ đề cá nhân hóa | Có, chỉ tạo NHÁP |
| `generate_questions` | AI soạn câu hỏi mới | Có, chỉ tạo NHÁP |

Cách hoạt động và an toàn:

- Thời điểm hiện tại (giờ Việt Nam) được đưa vào câu lệnh hệ thống, để mô hình đổi các hạn nộp nói bằng lời như "10h ngày mai" hay "tối thứ Sáu" sang chuẩn ISO 8601.
- Tên học sinh được so khớp không dấu, theo họ tên đầy đủ hoặc phần tên. Nếu trùng tên, công cụ trả về danh sách để mô hình hỏi lại giáo viên.
- Trợ lý không có công cụ gửi bài cho học sinh; việc gửi chỉ diễn ra khi giáo viên bấm duyệt trên web.
- Mỗi lượt có tối đa 6 bước gọi công cụ.
- Khi chưa có khóa API, chế độ demo nhận diện các câu lệnh mẫu và gọi đúng các công cụ này, nên vẫn trình diễn được toàn bộ quy trình.

## 10. Bảo mật

- Mật khẩu băm bằng scrypt.
- Phiên đăng nhập là cookie ký số (SameSite=Lax). Mọi form và API thay đổi dữ liệu có mã CSRF.
- Mỗi truy vấn đều kiểm tra quyền sở hữu: giáo viên chỉ truy cập lớp, học sinh và bài nộp của mình.
- Ảnh bài làm chỉ xem được khi đã đăng nhập, và đường dẫn tệp được kiểm tra để không thoát ra ngoài thư mục lưu trữ.
- Webhook xác thực bằng chuỗi bí mật trong header. Trang xem đề công khai dùng mã ngẫu nhiên khó đoán và không hiển thị bộ đề nháp.

## 11. Gợi ý đánh giá thực nghiệm (cho NCKH)

| Câu hỏi đánh giá | Chỉ số | Cách thu |
|---|---|---|
| AI chấm có sát giáo viên không? | MAE điểm/câu và điểm/bài; hệ số Kappa có trọng số bậc hai (QWK); tỉ lệ câu khớp ±0,25 | So `ai_score` với `final_score` trong bảng `item_grades` |
| AI đọc chữ viết tay đúng không? | Tỉ lệ lỗi ký tự (CER) trên mẫu đã gõ lại thủ công | Chọn ngẫu nhiên 30–50 bài |
| Độ tin cậy có hữu ích không? | Sai số ở nhóm "cần xem kỹ" so với nhóm còn lại | `confidence` và chênh lệch điểm |
| Bộ đề đề xuất có phù hợp? | Tỉ lệ bộ đề giáo viên duyệt không cần sửa; tỉ lệ làm đúng thực tế so với mục tiêu 70% | `assignments`, `item_grades` |
| Có tiết kiệm thời gian? | Thời gian chấm/bài trước và sau; thời gian soạn đề | Bấm giờ, khảo sát giáo viên |
| Học sinh có tiến bộ? | Mức nắm vững theo thời gian; so sánh nhóm thực nghiệm/đối chứng (nếu có) | Bảng điểm, dashboard |

## Tài liệu tham khảo

- Elo, A. E. (1978). *The Rating of Chessplayers, Past and Present*. Arco.
- Pelánek, R. (2016). Applications of the Elo rating system in adaptive educational systems. *Computers & Education*, 98, 169–179.
- Wilson, R. C., Shenhav, A., Straccia, M., & Cohen, J. D. (2019). The Eighty Five Percent Rule for optimal learning. *Nature Communications*, 10, 4646.
- Cohen, J. (1968). Weighted kappa: Nominal scale agreement with provision for scaled disagreement or partial credit. *Psychological Bulletin*, 70(4), 213–220.
- Google. Gemini API documentation – Structured output, Function calling. https://ai.google.dev/gemini-api/docs
- Telegram Bot API. https://core.telegram.org/bots/api · Zalo Bot Platform. https://bot.zaloplatforms.com
