Context thiết kế prototype — DocGrading
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
A03 — Rubric và template mặc định
- Danh sách rubric/template.
- Trạng thái draft, active, archived.
- Xem các phiên bản.
- Nhân bản rubric.
- Xem criterion, trọng số và evaluator.
- Không sửa trực tiếp phiên bản đã công bố.
A04 — Queue và job monitoring
- Danh sách job theo trạng thái.
- Queue depth, job age và thời gian xử lý.
- Filter theo đợt đánh giá, evaluator và lỗi.
- Job detail drawer.
- Retry job có kiểm soát.
- Hiển thị nguyên nhân lỗi và correlation ID.
- Không cho retry tạo kết quả trùng.
A05 — Evaluator/model configuration
- Danh sách evaluator.
- Phiên bản rule, prompt và model.
- Benchmark result.
- Ngưỡng chất lượng.
- Trạng thái draft, testing, active, rollback.
- Chỉ cho activate khi benchmark và phê duyệt đạt yêu cầu.
A06 — Audit log và retention
- Filter theo người dùng, thao tác, đối tượng và thời gian.
- Xem before/after của thay đổi.
- Theo dõi publish, override, retry, đổi quyền và xóa dữ liệu.
- Cấu hình thời gian lưu dữ liệu.
6. View Teacher
T01 — Danh sách Course
- Course code, tên Course, học kỳ và số Student.
- Số Assignment, Assignment đang mở và bài cần review.
- CTA tạo Course mới.
- Mở Course workspace để quản lý Assignment.
T02 — Course workspace
- Thông tin Course và Course settings.
- Danh sách Assignment theo trạng thái Draft, Open hoặc Closed.
- Số bài Submitted, Reviewed và Published cho từng Assignment.
- CTA tạo Assignment, chỉnh sửa Assignment hoặc mở Submission Queue.
T03 — Wizard tạo/chỉnh sửa Assignment
Thiết kế theo 4 bước:
1. Details: tên, description, due date và số lần nộp.
2. Submission requirements: file bắt buộc/tùy chọn, giới hạn PDF, text layer và template.
3. Rubric: chọn/nhân bản rubric, cấu hình criterion, evaluator, trọng số và evidence.
4. Review: preview, kiểm tra lỗi và publish Assignment.
Yêu cầu:
- Autosave mỗi bước.
- Hiển thị tiến độ.
- Cho phép lưu Draft; không cho publish nếu tổng trọng số khác 100 hoặc thiếu yêu cầu bắt buộc.
- Lỗi phải trỏ đúng bước và criterion liên quan.
T04 — Rubric builder
- Danh sách criterion có thể sắp xếp.
- Thêm, sửa, bật/tắt criterion.
- Cấu hình mô tả, phạm vi, evaluator, trọng số và evidence requirement.
- Criterion editor mở bằng drawer hoặc modal.
- Preview rubric trước khi công bố.
- Hiển thị version và trạng thái bất biến sau khi công bố.
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
Panel review cần có:
- Tổng điểm đề xuất.
- Danh sách criterion.
- Trạng thái từng criterion.
- Điểm hoặc mức đề xuất.
- Độ tin cậy.
- Finding và bằng chứng.
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
- Progress upload.
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
Danh sách Course → mở Course workspace → tạo/chỉnh sửa Assignment → nhập details → chọn submission requirements → chọn/nhân bản rubric → cấu hình criterion → preview → sửa lỗi → lưu Draft hoặc publish Assignment.
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
