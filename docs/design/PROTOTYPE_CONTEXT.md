Context thiết kế prototype — DocGrading

> **Trạng thái:** Tài liệu này là design reference. Product flow hiện chỉ bật session auth, Course, Assignment, Rubric, upload PDF và trạng thái job T-009; các màn hình kết quả, review, audit và quản trị người dùng chưa có API nên không xuất hiện và không chạy bằng mock.

1. Mô tả dự án
DocGrading là hệ thống web hỗ trợ đánh giá chất lượng báo cáo học thuật được nộp dưới dạng PDF.
Hệ thống phân tích cấu trúc, nội dung, bảng biểu, requirement, Use Case, thuật ngữ và tính nhất quán của tài liệu. Kết quả được trình bày theo từng tiêu chí, kèm vị trí và bằng chứng tương ứng trong PDF.
AI và rule chỉ tạo đề xuất hỗ trợ chấm. Teacher là người kiểm tra, điều chỉnh, phê duyệt và công bố kết quả chính thức.
Phạm vi hiện tại:
- Chỉ nhận PDF có text layer.
- Không hỗ trợ OCR cho PDF scan.
- Mỗi lần nộp lại tạo một phiên bản độc lập.
- Student chỉ nhìn thấy kết quả đã được Teacher công bố.
- Mọi thay đổi điểm, rubric, trạng thái và thao tác quản trị phải có audit log.
2. Nguyên tắc thiết kế
- Thiết kế dạng skeleton/wireframe, tập trung vào cấu trúc, hierarchy, layout và flow.
- Không thiết kế màu mè, không dùng gradient, illustration hoặc hiệu ứng trang trí không cần thiết.
- Tham khảo trực tiếp các mẫu ảnh skeleton structure đã được gửi.
- Ưu tiên grayscale, đường viền, placeholder và typography trung tính.
- Không dùng màu làm dấu hiệu trạng thái duy nhất; luôn có label hoặc icon đi kèm.
- Toàn bộ system copy, navigation, trạng thái, validation và button dùng tiếng Anh. Chỉ dữ liệu do người dùng nhập như tên Course, Assignment hoặc tên người dùng có thể dùng tiếng Việt.
- Teacher và Admin ưu tiên desktop.
- Student phải sử dụng được trên desktop và mobile, tối thiểu 320px.
- Mọi màn hình cần có các trạng thái: loading, empty, error, disabled và success.
- Tối ưu số thao tác, đặc biệt trong luồng Teacher duyệt nhiều bài liên tiếp.
3. Vai trò người dùng
Admin
Quản lý người dùng, quyền, rubric/template mặc định, evaluator, queue, job lỗi, audit log và cấu hình vận hành.
Teacher
Quản lý Course; tạo và chỉnh sửa Assignment trong từng Course; cấu hình yêu cầu nộp bài, rubric; theo dõi bài nộp, xem đề xuất chấm, kiểm tra bằng chứng, điều chỉnh và công bố kết quả.
Student
Xem yêu cầu, tải PDF, theo dõi trạng thái xử lý, xem kết quả đã công bố, nộp phiên bản mới và gửi yêu cầu xem lại.
4. Cấu trúc giao diện chung
- Login.
- App shell gồm sidebar, top bar, breadcrumb và vùng nội dung.
- Bộ chuyển workspace/role nếu tài khoản có nhiều vai trò.
- Search, filter, sort và pagination.
- Notification center.
- Toast thông báo.
- Confirmation dialog cho thao tác quan trọng.
- Status badge luôn có text rõ ràng.
- Error message phải nêu nguyên nhân và hành động tiếp theo.
- Không để lộ tên queue, worker, model hoặc lỗi kỹ thuật cho Student.
Các trạng thái chính:
- Đã nhận.
- Đang kiểm tra PDF.
- Chờ xử lý.
- Đang đánh giá.
- Cần xem xét.
- Chờ duyệt.
- Đã duyệt.
- Đã công bố.
- Xử lý lỗi.
- Yêu cầu nộp lại.
5. View Admin
A01 — Admin dashboard
Hiển thị:
- Tổng số người dùng.
- Số đợt đánh giá đang mở.
- Queue depth.
- Job đang chạy, lỗi và quá hạn.
- Thời gian xử lý trung bình.
- Tỷ lệ lỗi theo evaluator.
- Các cảnh báo cần xử lý.
- Danh sách hoạt động gần nhất.
A02 — Quản lý người dùng và quyền
- Danh sách người dùng.
- Search, filter theo vai trò và trạng thái.
- Xem chi tiết người dùng.
- Gán hoặc thu hồi role.
- Khóa/mở khóa tài khoản.
- Xem lịch sử thay đổi quyền.
- Dialog xác nhận đối với thay đổi nhạy cảm.
A03 — Rubric và catalog tiêu chí mặc định
- Danh sách rubric đã lưu.
- Tạo, sửa metadata và xóa rubric chưa được Assignment dùng.
- Chọn criterion từ catalog gồm 12 tiêu chí SRS baseline và `ACC-01`, xem mô tả, nội dung chấm, evaluator, trọng số, mức 0–4 cùng công thức điểm.
- Rubric/criterion đóng băng sau bài nộp đầu tiên; không có publish hoặc new-version trong giao diện.
A04 — Admin Monitoring
- KPI và segmented chart cho trạng thái job, queue depth và tuổi trung bình; tự refresh khi còn job `QUEUED` hoặc `RUNNING`.
- Danh sách job phân trang, filter theo trạng thái/Course và job detail drawer; mỗi job ưu tiên Assignment, tên file và Student, không dùng job UUID làm nhãn chính.
- Retry chỉ bật cho job `ERROR` còn attempt, không tạo job hoặc kết quả trùng.
- Hiển thị error code/detail đã redact và correlation ID khi có; không lộ storage key, credential, prompt, nội dung PDF hoặc provider secret.
- Job UUID, Submission UUID và correlation ID chỉ nằm trong disclosure `Technical details` khi cần điều tra.
- Admin được mở và quản lý mọi Course, roster, Submission, Rubric, review request cùng thao tác lifecycle mà API cho phép. Khi tạo Course, Admin chọn tài khoản Teacher đang hoạt động làm owner. Course được sửa/archive; hard delete chỉ dành cho Course chưa có dữ liệu phụ thuộc, không vượt invariant hoặc xóa audit/history.
- Trong danh sách Course dùng chung, Admin thấy owner để điều phối; Teacher không lặp owner vì danh sách đã giới hạn theo Course mình phụ trách. Owner email, thời điểm tạo/cập nhật và metadata nhỏ nằm trong `Course details`, không cạnh tranh với Assignment, Announcement hoặc CTA chính.
A05 — AI providers và routing
- Chỉ Admin thấy navigation, API key source, provider status, model/protocol và route; Teacher/Student không nhận các metadata này qua UI hoặc API.
- Header tóm tắt route `CITATION_SEMANTIC`: `Manual review only`, `Draft` hoặc `Active`, provider/model hiện tại và các blocker có tên rõ.
- Cảnh báo cố định trước khi activate: job do Student kích hoạt có thể phát sinh phí provider; hệ thống chưa tính, phân bổ hoặc thu phí. Hiển thị `max tokens/call`, `call budget/job`, tối đa ba job attempt, không automatic failover và provider lỗi chuyển review thủ công.
- Danh sách provider cố định gồm OpenAI, Anthropic Claude, Google Gemini, DeepSeek, OpenCode Zen và Amazon Bedrock. Mỗi card hiển thị nguồn credential (`Server environment`, `Encrypted storage`, `AWS IAM` hoặc `Not configured`), hint đã che, enabled/data-policy state, catalog status, revision và thời điểm/latency kiểm tra; không có nút reveal/copy key.
- Configure credential cho phép chọn biến môi trường trong allowlist hoặc paste key vào encrypted storage. UI không nhận tên env/custom base URL. Pasted key chỉ tồn tại trong field password tới lúc submit, không được cache hoặc trả lại; thay key là rotation, xóa credential đang được route active phải deactivate route trong cùng transaction.
- `Verify catalog access` gọi endpoint model-list bằng POST command, không gửi PDF/claim và không tính là generation test. Kết quả gắn đúng credential revision, dùng nhãn `Catalog verified`, `Invalid credential`, `Rate limited`, `Unavailable`, `Timeout` hoặc `Untested`; edit credential làm kết quả cũ stale.
- Route editor chọn provider, exact model ID, protocol phù hợp, region/geographic profile khi là Bedrock, max token và call budget. `Save draft` luôn deactivate bản đang sửa; `Activate` là action riêng có xác nhận phí, yêu cầu credential revision đã verify, data-policy approval và quality approval.
- Một task chỉ có một route active; không cấu hình hoặc lỗi giải mã/provider thì semantic dùng manual review, không chuyển provider ngầm. Route/config dùng revision + `If-Match`; conflict giữ input cục bộ và yêu cầu reload.
- Loading, empty, error, stale và success state có text/icon ngoài màu. Form/dialog có label, focus management, keyboard operation và reflow 320 CSS px. Metadata kỹ thuật ít dùng nằm trong disclosure.
- Audit chỉ ghi safe fields: provider/source/enabled/policy/status/route/model/protocol/revision/actor/time; không ghi plaintext key, ciphertext, header, response body hoặc exception.
A06 — Audit log và retention
- Filter theo người dùng, thao tác, đối tượng và thời gian.
- Xem before/after của thay đổi.
- Theo dõi publish, override, retry, đổi quyền và xóa dữ liệu.
- Cấu hình thời gian lưu dữ liệu.
6. View Teacher
T01 — Danh sách Course
- Course code, tên Course, học kỳ và trạng thái là thông tin chính.
- Số Student, số Assignment, Assignment đang mở và bài cần review.
- Không lặp owner trên card Teacher vì toàn bộ danh sách đã giới hạn theo Course Teacher sở hữu.
- CTA tạo Course mới.
- Mở Course workspace để quản lý Assignment.
T02 — Course workspace
- Header ưu tiên Course code, tên, học kỳ, trạng thái, roster và Submission Queue.
- Assignment và Announcement là nội dung chính; metadata ít dùng nằm trong disclosure `Course details`.
- `Course details` hiển thị owner/instructor bằng display name và email, thời điểm tạo, thời điểm cập nhật; không hiển thị revision hoặc UUID.
- Danh sách Assignment theo trạng thái Draft, Open hoặc Closed; Draft chưa có bài nộp được sửa/xóa.
- Mỗi Assignment mở được danh sách bài nộp gồm Student, email, file, dung lượng, thời điểm, số lượt đã dùng, trạng thái và CTA review/PDF.
- Tab Announcement cho phép Teacher tạo, sửa, xóa thông báo; Student trong Course đọc được ngay.
- CTA tạo Assignment, quản lý Announcement hoặc mở toàn bộ Submission Queue.
T03 — Wizard tạo/chỉnh sửa Assignment
Thiết kế theo 4 bước:
1. Details: tên, description, due date và số lần nộp.
2. Submission requirements: file bắt buộc/tùy chọn, giới hạn PDF, text layer và template.
3. Rubric: chọn rubric đã lưu và xem trạng thái hợp lệ của tiêu chí/trọng số.
4. Review: preview, kiểm tra lỗi và mở Assignment.
Yêu cầu:
- Autosave mỗi bước.
- Hiển thị tiến độ.
- Cho phép lưu Draft; không cho mở nhận bài nếu rubric không có tiêu chí, tổng trọng số khác 100 hoặc thiếu mức 0–4.
- Lỗi phải trỏ đúng bước và criterion liên quan.
T04 — Rubric builder
- Master/detail: danh sách rubric đã lưu bên trái, rubric đang chỉnh sửa bên phải; mobile chuyển thành card xếp dọc.
- Thêm criterion bằng catalog có search/check trạng thái đã chọn.
- Khi chọn criterion, hiển thị mô tả, gạch đầu dòng nội dung chấm, evaluator, trọng số, thang 0–4 và công thức `mức / 4 × trọng số`. `ACC-01` tách kiểm chứng citation thường có tính điểm khỏi semantic có nhãn `Chưa tính điểm`; semantic không được lưu vào evaluator hoặc tổng điểm.
- Criterion editor mở bằng modal có keyboard focus trap; xác nhận quay lại danh sách tiêu chí.
- Tổng trọng số cập nhật tức thời và chỉ báo hợp lệ khi có tiêu chí, đủ mức 0–4 và tổng bằng 100%.
- Cho phép sửa/xóa rubric hoặc criterion trực tiếp trước bài nộp đầu tiên; lỗi khóa hoặc reference từ backend phải hiển thị rõ.
- Không hiển thị publish, status versioning hoặc new version cho rubric.
T05 — Submission queue
- Bảng danh sách bài nộp.
- Filter theo trạng thái, mức điểm, độ tin cậy và lỗi.
- Tab hoặc filter nhanh:
  - Cần xem xét.
  - Chờ duyệt.
  - Đã duyệt.
  - Đã công bố.
  - Lỗi.
- Hiển thị người đang duyệt để tránh hai Teacher sửa cùng lúc.
- Hỗ trợ chuyển tới bài chưa duyệt tiếp theo.
T06 — Review workspace
Đây là màn hình quan trọng nhất.
Layout desktop:
- Khu vực PDF chiếm khoảng 60–70% chiều rộng.
- Panel criterion/finding khoảng 360–480px.
- Thanh hành động cố định.
PDF viewer cần có:
- Điều hướng trang.
- Zoom và fit width.
- Search.
- Thumbnail.
- Marker bằng chứng.
- Chọn marker trong PDF phải mở đúng finding.
- Chọn finding phải điều hướng tới đúng trang/vùng PDF.
- Chỉ hiển thị marker của criterion/rule set đang được chọn.
- Finding trong cùng criterion dùng màu, ký hiệu và kiểu viền ổn định để phân biệt; marker không được che chữ.
- Khi tìm thấy focus text chính xác trong PDF, highlight chỉ cụm liên quan; nếu PDF scan hoặc không khớp text thì dùng bbox outline-only, không giả lập độ chính xác.
- Marker chồng nhau phải chọn được đầy đủ qua toolbar hoặc thao tác cycle.
Panel review cần có:
- Tổng điểm đề xuất.
- Danh sách criterion/rule set theo tab; hỗ trợ phím mũi tên và chỉ render finding của tab đang chọn.
- Mỗi finding hiển thị criterion bằng `code` và `title`; UUID chỉ dùng nội bộ.
- Trạng thái từng criterion.
- Điểm hoặc mức đề xuất.
- Độ tin cậy.
- Finding và bằng chứng.
- Finding citation ưu tiên một câu ngắn tiếng Việt nêu đúng citation/reference và loại vấn đề; page, snippet, gợi ý và điểm đề xuất nằm trong disclosure chi tiết, không hiển thị internal `mention-*`/`reference-*` hash.
- Panel finding phải giới hạn chiều cao, scroll nội bộ và wrap chuỗi dài, không làm tràn layout.
- Tổng hợp citation/semantic diagnostics đặt sau khu vực PDF/review chính trong disclosure thu gọn, không đẩy PDF xuống dưới fold.
- Gợi ý sửa.
- Accept, edit hoặc reject đề xuất.
- Nhập lý do khi override ảnh hưởng kết quả.
- Reusable comment library.
- Autosave và trạng thái Đang lưu/Đã lưu/Không thể lưu.
- Cảnh báo version stale hoặc soft lock.
- Nút duyệt và nút công bố phải tách biệt.
T06 — Publish result
- Kiểm tra completeness trước khi publish.
- Danh sách criterion còn thiếu bằng chứng hoặc chưa duyệt.
- Preview nội dung Student sẽ nhìn thấy.
- Publish một bài hoặc batch publish.
- Confirmation dialog nêu số lượng bài và ảnh hưởng.
- Không công bố các bài chưa hoàn tất.
T07 — Review request/appeal inbox
- Danh sách yêu cầu xem lại.
- Filter theo trạng thái và criterion.
- Hiển thị lý do của Student.
- Liên kết tới đúng kết quả và bằng chứng.
- Teacher giữ nguyên hoặc điều chỉnh kết quả.
- Bắt buộc lưu lý do và lịch sử trao đổi.
7. View Student
S01 — Danh sách đợt đánh giá
- Đang mở.
- Đã nộp.
- Đang xử lý.
- Có kết quả.
- Cần nộp lại.
- Deadline và trạng thái rõ ràng.
- Mỗi Assignment hiển thị đồng bộ `số lượt đã dùng / số lượt tối đa`; hết lượt thì ẩn CTA upload.
- Hiển thị Announcement mới nhất của các Course đã tham gia.
- Course code và tên gắn với từng Assignment; disclosure `Course information` riêng hiển thị học kỳ, trạng thái và instructor bằng display name/email. Student không thấy thời điểm tạo/cập nhật, revision hoặc UUID vì không phục vụ luồng nộp bài.
S02 — Chi tiết đợt đánh giá
- Mô tả yêu cầu.
- Rubric công khai.
- Loại tài liệu được chấp nhận.
- Deadline.
- Lịch sử các phiên bản đã nộp.
- CTA nộp tài liệu.
S03 — Upload PDF
- Drag-and-drop và file picker.
- Hiển thị tên, dung lượng và số trang.
- Kiểm tra định dạng và text layer.
- Progress upload mô tả hành động dễ hiểu như kiểm tra tính toàn vẹn tài liệu, không phơi tên thuật toán SHA-256.
- Validation hai bước: kiểm tra file và kiểm tra nội dung PDF.
- Nếu PDF scan, nêu rõ lý do và hướng dẫn xuất lại PDF text-native.
- Giữ dữ liệu form nếu upload lỗi.
S04 — Theo dõi trạng thái
- Timeline trạng thái xử lý.
- Thời điểm cập nhật gần nhất.
- Thông báo dễ hiểu.
- Khi lỗi, cung cấp hành động nộp lại hoặc liên hệ Teacher.
- Không hiển thị chi tiết hạ tầng nội bộ.
S05 — Kết quả đã công bố
- Tổng điểm và trạng thái.
- Breakdown theo criterion.
- Nhận xét của Teacher.
- Finding theo mức độ.
- Vị trí và bằng chứng trong PDF.
- Gợi ý sửa.
- Chỉ hiển thị dữ liệu đã được Teacher công bố.
- Không hiển thị model, prompt, confidence nội bộ hoặc đề xuất bị loại.
S06 — So sánh phiên bản
- Chọn hai phiên bản.
- So sánh tổng điểm và từng criterion.
- Finding mới, đã giải quyết và còn tồn tại.
- Không cần diff toàn bộ PDF ở giai đoạn đầu.
S07 — Yêu cầu xem lại
- Chọn criterion hoặc finding.
- Nhập lý do.
- Đính kèm thông tin liên quan nếu cần.
- Xem trạng thái yêu cầu.
- Hiển thị phản hồi và lịch sử xử lý.
8. Các modal, drawer và cửa sổ phụ
Cần thiết kế tối thiểu:
- Criterion editor drawer.
- Job detail drawer.
- Finding/evidence detail drawer.
- Rubric preview modal.
- PDF không hợp lệ/PDF scan dialog.
- Override score/reject finding dialog.
- Publish confirmation dialog.
- Batch publish confirmation.
- Unsaved changes dialog.
- Autosave failure banner.
- Concurrent editing/soft-lock dialog.
- Retry job dialog.
- Activate evaluator/model confirmation.
- Role change confirmation.
- Request review dialog.
- Notification panel.
- Filter panel trên mobile.
- Delete/archive confirmation.
9. Flow chính
Flow 1 — Teacher quản lý Course và Assignment
Danh sách Course → mở Course workspace → tạo/chỉnh sửa rubric từ catalog → lưu → tạo/chỉnh sửa Assignment → nhập details → chọn submission requirements → chọn rubric → kiểm tra tổng trọng số/mức điểm → mở Assignment.
Flow 2 — Student nộp tài liệu
Danh sách yêu cầu → xem chi tiết → chọn PDF → kiểm tra file → kiểm tra text layer → xác nhận upload → tạo phiên bản → theo dõi trạng thái.
Flow 3 — Hệ thống phân tích
Đã nhận → kiểm tra PDF → chờ xử lý → đang đánh giá → kiểm tra kết quả → cần xem xét hoặc chờ duyệt.
Flow 4 — Teacher duyệt
Submission queue → chọn bài → review PDF và finding → accept/edit/reject → ghi lý do override → duyệt → preview kết quả Student → công bố.
Flow 5 — Student xem kết quả và nộp lại
Thông báo có kết quả → xem breakdown → mở evidence → sửa tài liệu ngoài hệ thống → nộp phiên bản mới → theo dõi → so sánh kết quả.
Flow 6 — Yêu cầu xem lại
Student chọn criterion/finding → gửi lý do → Teacher nhận thông báo → kiểm tra evidence → giữ nguyên hoặc điều chỉnh → phản hồi → đóng yêu cầu.
Flow 7 — Admin xử lý job lỗi
Dashboard cảnh báo → mở job → xem nguyên nhân → kiểm tra quyền → retry hoặc yêu cầu nộp lại → theo dõi trạng thái → audit log.
10. Yêu cầu đầu ra cho Agent thiết kế
- Tạo sitemap hoặc screen map trước.
- Tạo user flow cho ba vai trò.
- Thiết kế skeleton cho các màn hình chính nêu trên.
- Tập trung nhiều nhất vào:
  - Wizard tạo đợt đánh giá.
  - Submission queue.
  - Review workspace.
  - Student upload.
  - Student result.
  - Admin job monitoring.
- Mỗi màn hình cần thể hiện loading, empty, error và success state.
- Không tự thêm chức năng ngoài phạm vi nếu không phục vụ trực tiếp flow chính.
- Không thiết kế màu sắc hoặc visual branding chi tiết.
- Bám sát bố cục và ngôn ngữ cấu trúc của các ảnh skeleton reference đã gửi.
