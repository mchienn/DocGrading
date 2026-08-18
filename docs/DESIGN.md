# Design Guide — Hệ thống đánh giá chất lượng tài liệu

Phiên bản: 0.1  
Ngày nghiên cứu: 18/08/2026  
Phạm vi: giao diện web độc lập cho Admin, Giảng viên và Sinh viên

## 1. Mục đích tài liệu

Tài liệu này mô tả hướng thiết kế giao diện cho một hệ thống độc lập dùng để đánh giá chất lượng tài liệu học thuật, trước mắt tập trung vào PDF có text layer.

Tài liệu được viết để có thể sao chép trực tiếp sang một repository mới và dùng làm căn cứ cho thiết kế, frontend, backend và kiểm thử giao diện. Tài liệu không phụ thuộc framework, ngôn ngữ lập trình, hệ thống hiện tại hoặc hạ tầng triển khai cụ thể.

Các từ khóa quy ước:

- **PHẢI**: yêu cầu bắt buộc đối với phiên bản đầu tiên.
- **NÊN**: mặc định nên thực hiện; chỉ thay đổi khi có lý do rõ ràng.
- **CÓ THỂ**: phần mở rộng, không bắt buộc trong phiên bản đầu tiên.

## 2. Phạm vi sản phẩm liên quan đến giao diện

### 2.1. Tác nhân

- **Admin**: quản lý người dùng, rubric mặc định, hoạt động xử lý và nhật ký hệ thống.
- **Giảng viên**: tạo đợt đánh giá, chọn hoặc cấu hình rubric, xem kết quả tự động, điều chỉnh và công bố kết quả.
- **Sinh viên**: nộp tài liệu, theo dõi trạng thái xử lý và xem kết quả đã được công bố.

### 2.2. Ràng buộc đã xác định

- Hệ thống là một ứng dụng độc lập.
- Tài liệu đầu vào là PDF.
- Chỉ chấp nhận PDF có text layer đủ dùng, ví dụ PDF xuất từ Word hoặc LaTeX.
- Không chấp nhận PDF scan hoặc PDF trộn lẫn trang text và trang scan.
- Hệ thống có rubric mặc định.
- Giảng viên có thể bật, tắt, cấu hình tiêu chí và thay đổi trọng số.
- Hệ thống có thể dùng rule, thuật toán và LLM để tạo kết quả đánh giá.
- Kết quả tự động phải có bằng chứng để giảng viên kiểm tra.
- Giảng viên là người có quyền điều chỉnh và công bố kết quả chính thức.

### 2.3. Không sao chép trực tiếp sản phẩm tham khảo

Thiết kế được phép học theo mô hình tương tác của Turnitin và Gradescope nhưng:

- Không sử dụng tên, logo, màu thương hiệu hoặc tài sản đồ họa của họ.
- Không sao chép nguyên văn nội dung giao diện.
- Không dựng lại từng pixel của màn hình tham khảo.
- Không đưa các chức năng kiểm tra đạo văn hoặc phát hiện AI vào sản phẩm nếu chúng chưa thuộc yêu cầu nghiệp vụ.
- Mọi component phải sử dụng hệ thống thiết kế và nhận diện riêng.

## 3. Kết quả nghiên cứu

### 3.1. Turnitin Feedback Studio

Turnitin tổ chức việc đọc và phản hồi trong cùng một không gian làm việc: nội dung tài liệu là vùng chính, công cụ phản hồi và rubric nằm trong panel bên cạnh.

Các điểm nên học theo:

- Comment được gắn vào đúng vị trí trong tài liệu.
- Comment xuất hiện ngoài lề nên dễ nhìn hơn marker rời rạc.
- Có thể ghim các phản hồi quan trọng để sinh viên không bỏ sót.
- Comment có thể liên kết với một tiêu chí rubric.
- Comment thường dùng có thể chuyển thành QuickMark để tái sử dụng.
- Panel phản hồi có thể thu gọn để tăng không gian đọc.
- Điểm tổng luôn xuất hiện ở vùng trên cùng.
- Rubric có chế độ panel gọn và chế độ toàn màn hình.
- Thư viện rubric/comment được chia theo cá nhân, tổ chức và mẫu hệ thống để giảm lộn xộn.

Các điểm không nên sao chép:

- Không chia quá nhiều lớp công cụ nếu hệ thống chỉ đánh giá chất lượng tài liệu.
- Không dùng quá nhiều icon không có nhãn.
- Không mở rubric quan trọng trong cửa sổ mới hoặc popup trình duyệt.
- Không yêu cầu người dùng bấm “Apply to grade” sau mỗi thay đổi nhỏ nếu hệ thống đã có autosave và trạng thái duyệt rõ ràng.
- Không để annotation dày đặc che nội dung tài liệu.

Nguồn chính:

- [Navigating the new grading and feedback experience — Turnitin](https://guides.turnitin.com/hc/en-us/articles/35446790262541-Navigating-the-new-grading-and-feedback-experience)
- [Using in-margin comments — Turnitin](https://guides.turnitin.com/hc/en-us/articles/35561995985037--New-Using-in-margin-comments)
- [Grading with rubrics and grading forms — Turnitin](https://guides.turnitin.com/hc/en-us/articles/35739418092941--New-Grading-with-rubrics-and-grading-forms)
- [Creating QuickMarks and sets — Turnitin](https://guides.turnitin.com/hc/en-us/articles/35768177036941--New-Creating-QuickMarks-and-sets-in-the-QuickMark-Manager)
- [New Feedback Studio FAQ — Turnitin](https://guides.turnitin.com/hc/en-us/articles/36246136051725-New-Turnitin-Feedback-Studio-FAQ)

### 3.2. Gradescope

Gradescope tối ưu cho tốc độ và tính nhất quán khi chấm số lượng lớn. Màn hình chấm gồm ba vùng rõ ràng: bài nộp, rubric và thanh hành động phía dưới.

Các điểm nên học theo:

- Rubric nằm ngay cạnh bài nộp.
- Có list view để chấm nhanh và grid view để xem đầy đủ rubric.
- Có phím tắt cho rubric và chuyển tới bài chưa chấm tiếp theo.
- Có thao tác “Next Ungraded” thay vì bắt giảng viên quay lại danh sách.
- Một annotation có thể gắn với rubric item và comment.
- Comment đã dùng có thể tái sử dụng.
- Giảng viên có thể thay đổi rubric trong lúc chấm và giữ cách áp dụng nhất quán.
- Có bước Review Grades riêng trước khi Publish Grades.
- Trạng thái đã công bố và sinh viên đã xem kết quả được hiển thị rõ.

Các điểm không nên sao chép:

- Không tổ chức toàn bộ hệ thống theo từng “question”, vì tài liệu báo cáo có cấu trúc dài và nhiều loại tiêu chí.
- Không hiển thị mọi thao tác cấu hình rubric ngay trong panel chấm; chỉ cho phép sửa nhỏ trong ngữ cảnh.
- Không dùng quá nhiều màu cho trạng thái rubric.
- Không để comment riêng của bài nộp nằm quá thấp và dễ bị bỏ qua.

Nguồn chính:

- [Grading submissions with rubrics — Gradescope](https://guides.gradescope.com/hc/en-us/articles/22249389005709-Grading-submissions-with-rubrics)
- [Reviewing Grades — Gradescope](https://guides.gradescope.com/hc/en-us/articles/22067099093517-Reviewing-Grades)
- [AI-assisted grading and answer groups — Gradescope](https://guides.gradescope.com/hc/en-us/articles/24838908062093-AI-assisted-grading-and-answer-groups)

### 3.3. Phản hồi từ giảng viên và đơn vị đào tạo

Các phản hồi thực tế lặp lại một số nhu cầu:

- Giảng viên thích việc tài liệu, rubric và nhận xét nằm cùng một màn hình.
- Comment mẫu giúp giảm việc gõ lặp lại và tăng tính nhất quán giữa nhiều người chấm.
- Phím tắt và luồng chuyển trực tiếp sang bài tiếp theo giúp giảm thời gian thao tác.
- Rubric chi tiết giúp giải thích điểm nhưng có thể khiến người dùng chỉ “quét để tìm lỗi” và bỏ qua việc đọc tổng thể.
- Tài liệu dài gây mỏi khi chấm hoàn toàn trên màn hình.
- Độ trễ khi cuộn tài liệu hoặc lưu comment phá vỡ luồng chấm.
- Sinh viên có thể không biết phản hồi đã được công bố hoặc chỉ nhìn điểm tổng.
- Giảng viên cần kiểm soát các đề xuất do AI sinh ra; UI không được khiến đề xuất tự động trông giống quyết định cuối cùng.

Các nguồn phản hồi:

- [Case Study: Marking using Turnitin Feedback Studio — University of Bristol](https://www.bristol.ac.uk/digital-education/case-studies/pre-2018/marking-using-turnitin-feedback-studio/)
- [Summative marking with Turnitin Feedback Studio — University of York](https://vle-support.york.ac.uk/training/case-studies/eng-asciuto/)
- [Creating Assignments and Grading Online with Gradescope — Columbia University](https://ctl.columbia.edu/resources-and-technology/teaching-with-technology/teaching-online/gradescope/)
- [Discussion: Gradescope workflow — r/Professors](https://www.reddit.com/r/Professors/comments/1o3ssr7/discussion_what_is_your_gradescope_workflow/)
- [Turnitin Feedback Studio marking tips — r/Professors](https://www.reddit.com/r/Professors/comments/g467xq/turnitin_feedback_studio_marking_tips_and_tricks/)

Ý kiến cộng đồng chỉ được dùng để phát hiện vấn đề và gợi ý thiết kế, không được coi là bằng chứng định lượng.

### 3.4. Nghiên cứu về chấm điểm có AI hỗ trợ

CoGrader đề xuất quy trình cộng tác giữa giảng viên và LLM cho việc chấm báo cáo dự án, trong đó giảng viên vẫn kiểm soát các phán quyết. Nghiên cứu về giao diện rubric sinh bởi AI cũng cho thấy giáo viên cần khả năng thêm, xóa, sửa tiêu chí dễ dàng và cần giữ quyền kiểm soát do nội dung tự động có thể chung chung hoặc lệch mục tiêu môn học.

Quy tắc rút ra cho giao diện:

- Kết quả tự động phải được gọi là **đề xuất** trước khi giảng viên xác nhận.
- Mỗi phát hiện phải trỏ tới bằng chứng trong tài liệu nếu có thể.
- Giảng viên phải có thể chấp nhận, sửa hoặc loại bỏ đề xuất.
- Không dùng một con số “độ tin cậy” thiếu hiệu chuẩn để thuyết phục người dùng.
- Các trường hợp không chắc chắn phải được đưa vào hàng đợi “Cần kiểm tra”.
- Lịch sử thay đổi phải phân biệt hành động của hệ thống và hành động của con người.

Nguồn nghiên cứu:

- [CoGrader: Transforming Instructors' Assessment of Project Reports through Collaborative LLM Integration](https://arxiv.org/abs/2507.20655)
- [AI-Generated Rubric Interfaces: K-12 Teachers' Perceptions and Practices](https://arxiv.org/abs/2603.10773)

## 4. Quyết định thiết kế tổng thể

### 4.1. Ba phương án đã xem xét

| Phương án | Điểm mạnh | Rủi ro |
|---|---|---|
| Turnitin-first | Đọc tài liệu dài và phản hồi theo vị trí tốt | Dễ tạo quá nhiều lớp công cụ và annotation |
| Gradescope-first | Rubric nhanh, phù hợp tải chấm lớn | Quá thiên về câu hỏi hoặc bài thi |
| Hybrid | Kết hợp đọc tài liệu tốt với luồng rubric nhanh | Cần kỷ luật thiết kế để không gom quá nhiều chức năng |

### 4.2. Phương án được chọn

**Sử dụng thiết kế Hybrid:**

- Lấy cấu trúc PDF viewer, comment ngoài lề, pinned feedback và panel thu gọn từ Turnitin.
- Lấy cấu trúc rubric thao tác nhanh, thanh hành động cố định, phím tắt và “bài cần duyệt tiếp theo” từ Gradescope.
- Dùng hệ thống thiết kế riêng, tối giản và trung tính.
- Đặt bằng chứng và quyền kiểm soát của giảng viên làm trung tâm.

## 5. Nguyên tắc thiết kế

### 5.1. Nội dung là trung tâm

- PDF PHẢI là vùng lớn nhất trên màn hình review.
- Công cụ không được che nội dung trừ khi người dùng chủ động mở.
- Annotation mặc định PHẢI nhẹ; chỉ làm nổi bật mạnh khi được chọn.

### 5.2. Bằng chứng trước, kết luận sau

- Điểm hoặc lỗi do hệ thống đề xuất PHẢI đi kèm vị trí hoặc đoạn trích liên quan khi có thể.
- Bấm vào một phát hiện PHẢI đưa PDF đến đúng trang và vùng bằng chứng.
- Bấm vào marker trên PDF PHẢI chọn đúng phát hiện trong panel.

### 5.3. Giảng viên giữ quyền quyết định

- Hệ thống không được tự trình bày kết quả tự động như điểm chính thức.
- Trạng thái **Tự động đề xuất**, **Giảng viên đã sửa**, **Giảng viên đã xác nhận** PHẢI phân biệt được bằng nhãn và icon, không chỉ bằng màu.
- Nút công bố phải là hành động rõ ràng và tách khỏi lưu nháp.

### 5.4. Hiển thị vừa đủ

- Thông tin kỹ thuật như model, token, prompt hoặc rule ID không hiển thị ở màn hình sinh viên.
- Màn hình giảng viên chỉ hiển thị phương pháp đánh giá ở mức dễ hiểu: Rule, Thuật toán, LLM hoặc Kết hợp.
- Chi tiết kỹ thuật chỉ nằm trong vùng mở rộng dành cho kiểm tra hoặc quản trị.

### 5.5. Tối ưu thao tác lặp lại

- Hệ thống PHẢI autosave.
- Các hành động thường dùng PHẢI có phím tắt.
- Sau khi hoàn thành một bài, giảng viên có thể chuyển thẳng đến bài cần duyệt tiếp theo.
- Comment thường dùng có thể lưu thành mẫu và tái sử dụng.

### 5.6. Trạng thái luôn rõ ràng

- Người dùng phải biết tài liệu đang upload, kiểm tra, xử lý, chờ duyệt, đã công bố hay gặp lỗi.
- Không dùng spinner vô thời hạn mà không có mô tả trạng thái.
- Lỗi phải chỉ rõ nguyên nhân và hành động tiếp theo.

## 6. Mô hình thông tin

### 6.1. Thuật ngữ hiển thị

| Thuật ngữ | Ý nghĩa trên giao diện |
|---|---|
| Đợt đánh giá | Một bài tập hoặc hoạt động yêu cầu sinh viên nộp tài liệu |
| Rubric | Bộ tiêu chí, mức đánh giá, trọng số và cách tính điểm |
| Tiêu chí | Một khía cạnh được đánh giá trong rubric |
| Phát hiện | Một vấn đề hoặc điểm mạnh cụ thể được hệ thống/giảng viên ghi nhận |
| Bằng chứng | Vị trí, đoạn trích, bảng hoặc section trong PDF liên quan đến phát hiện |
| Đề xuất tự động | Điểm hoặc nhận xét chưa được giảng viên xác nhận |
| Kết quả đã công bố | Kết quả sinh viên được phép xem |

### 6.2. Vòng đời bài nộp

```text
Chưa nộp
   ↓
Đang tải lên
   ↓
Đang kiểm tra PDF
   ├── Không hợp lệ → Yêu cầu nộp lại
   ↓
Đang đánh giá
   ↓
Chờ giảng viên duyệt
   ↓
Đã duyệt
   ↓
Đã công bố
```

Tên queue, worker, model hoặc lỗi stack trace không được dùng làm trạng thái hướng tới người dùng.

## 7. Kiến trúc điều hướng

### 7.1. Giảng viên

```text
Tổng quan
Đợt đánh giá
  └─ Danh sách bài nộp
      └─ Không gian review
Rubric
Thư viện nhận xét
```

### 7.2. Sinh viên

```text
Bài cần nộp
Bài đã nộp
  └─ Trạng thái xử lý
  └─ Kết quả đã công bố
```

### 7.3. Admin

```text
Tổng quan hệ thống
Người dùng
Rubric mặc định
Hoạt động xử lý
Mức sử dụng
Nhật ký
```

Không hiển thị chức năng của vai trò khác trong menu. Nếu một tài khoản có nhiều vai trò, dùng bộ chuyển vai trò hoặc workspace rõ ràng.

## 8. Khung giao diện chung

### 8.1. App shell

- Sidebar trái rộng 224 px ở desktop và có thể thu gọn xuống 64 px.
- Header cao 56 px.
- Nội dung dùng chiều rộng khả dụng; không ép toàn bộ ứng dụng vào container hẹp.
- Breadcrumb chỉ dùng khi có từ ba cấp điều hướng trở lên.
- Tên trang, trạng thái và hành động chính nằm trên cùng một hàng nếu đủ chỗ.
- Mỗi trang chỉ có một primary action nổi bật.

### 8.2. Mật độ giao diện

- Mặc định dùng mật độ vừa phải.
- Bảng dữ liệu có row height 48 px.
- Nút chính cao 40 px; vùng bấm icon tối thiểu 32 x 32 px, khuyến nghị 40 x 40 px.
- Không dùng card cho mọi nội dung; bảng, danh sách và section phẳng được ưu tiên.
- Không dùng dashboard với nhiều biểu đồ trang trí.

## 9. Đặc tả màn hình

### 9.1. Đăng nhập

Mục tiêu: đưa người dùng vào đúng vai trò với ít thao tác.

Phải có:

- Tên và biểu tượng hệ thống riêng.
- Cơ chế đăng nhập do hệ thống triển khai quy định.
- Thông báo lỗi rõ ràng.
- Liên kết trợ giúp hoặc liên hệ hỗ trợ.

Không đặt ảnh minh họa lớn nếu không mang thông tin hữu ích.

### 9.2. Tổng quan giảng viên

Mục tiêu: cho biết việc gì cần xử lý ngay.

Thứ tự nội dung:

1. Các bài đang chờ duyệt.
2. Các job gặp lỗi hoặc cần sinh viên nộp lại.
3. Các đợt đánh giá gần đây.
4. Các kết quả đã duyệt nhưng chưa công bố.

Chỉ sử dụng các số liệu hành động được:

- Chờ xử lý.
- Chờ duyệt.
- Có lỗi.
- Chưa công bố.

Không cần biểu đồ điểm hoặc biểu đồ sử dụng ở màn hình đầu của phiên bản đầu tiên.

### 9.3. Tạo đợt đánh giá

Luồng đề xuất gồm bốn bước:

1. Thông tin cơ bản.
2. Chọn rubric.
3. Điều chỉnh tiêu chí và trọng số.
4. Xem trước và tạo.

Quy tắc:

- Người dùng có thể lưu nháp ở mọi bước.
- Khi chọn rubric mặc định, hiển thị phiên bản và mô tả ngắn.
- Nếu rubric được tùy chỉnh, tạo bản sao gắn với đợt đánh giá; không sửa âm thầm bản mặc định.
- Tổng trọng số luôn hiển thị.
- Không cho hoàn thành nếu tổng trọng số bắt buộc khác 100%.
- Phần lựa chọn cách xử lý rule/LLM nằm trong vùng “Nâng cao”, không cản trở luồng cơ bản.

### 9.4. Thư viện rubric

Màn hình dùng layout danh sách, không dùng gallery card lớn.

Mỗi dòng rubric hiển thị:

- Tên.
- Loại tài liệu phù hợp.
- Số tiêu chí.
- Phiên bản.
- Nguồn: hệ thống hoặc giảng viên.
- Trạng thái: nháp, đang dùng hoặc lưu trữ.
- Ngày cập nhật.

Hành động:

- Xem.
- Nhân bản.
- Chỉnh sửa bản cá nhân.
- Xuất/nhập.
- Lưu trữ.

Rubric mặc định của hệ thống không được chỉnh sửa trực tiếp bởi giảng viên; giảng viên phải nhân bản trước.

### 9.5. Rubric Builder

Rubric Builder dùng bảng tiêu chí có thể mở rộng từng dòng.

```text
┌──────────────────────────────────────────────────────────────────────┐
│ Rubric: Báo cáo học thuật chuẩn                     Tổng: 100%       │
├────────────────────────┬──────────┬──────────────┬───────────────────┤
│ Tiêu chí               │ Trọng số │ Cách đánh giá│ Trạng thái        │
├────────────────────────┼──────────┼──────────────┼───────────────────┤
│ Cấu trúc tài liệu      │ 20%      │ Rule         │ Đang bật          │
│ Tính đầy đủ            │ 25%      │ Kết hợp      │ Đang bật          │
│ Tính nhất quán         │ 20%      │ Kết hợp      │ Đang bật          │
│ Chất lượng nội dung    │ 25%      │ LLM + duyệt  │ Đang bật          │
│ Trình bày              │ 10%      │ Rule         │ Đang bật          │
└────────────────────────┴──────────┴──────────────┴───────────────────┘
```

Khi mở một tiêu chí, hiển thị:

- Mô tả tiêu chí.
- Các mức đánh giá và điểm.
- Trọng số.
- Hướng dẫn chấm.
- Phương pháp đánh giá.
- Cấu hình nâng cao nếu người dùng có quyền.

Quy tắc:

- Kéo thả để sắp xếp phải có phương án thay thế bằng nút lên/xuống.
- Thay đổi chưa lưu phải có chỉ báo.
- Xóa tiêu chí phải có xác nhận và cho phép hoàn tác khi phù hợp.
- Công thức hoặc code tự do không xuất hiện trong luồng chính của phiên bản đầu tiên.
- Khi chức năng công thức/code được bổ sung, nó phải nằm trong chế độ nâng cao, có validation, preview và lịch sử phiên bản.

### 9.6. Danh sách bài nộp

Dùng bảng với các cột tối thiểu:

- Sinh viên.
- Tên tài liệu.
- Thời điểm nộp.
- Trạng thái xử lý.
- Trạng thái duyệt.
- Điểm đề xuất hoặc điểm chính thức.
- Số mục cần kiểm tra.
- Người đang duyệt, nếu có.

Bộ lọc quan trọng:

- Chờ duyệt.
- Có lỗi.
- Có mục cần kiểm tra.
- Đã duyệt.
- Đã công bố.

Hành động hàng loạt chỉ áp dụng cho thao tác an toàn như gán người duyệt hoặc công bố các kết quả đã được duyệt. Không cho công bố hàng loạt các kết quả chưa duyệt.

### 9.7. Không gian review của giảng viên

Đây là màn hình quan trọng nhất.

#### 9.7.1. Bố cục mặc định

```text
┌─────────────────────────────────────────────────────────────────────┐
│ ← Danh sách | Tên bài nộp | Sinh viên ▾ | Đã lưu | Điểm 7.8/10     │
├──────────────────────────────────────────┬──────────────────────────┤
│ PDF toolbar                              │ Rubric | Phát hiện | Tổng│
├──────────────────────────────────────────┼──────────────────────────┤
│                                          │ Cần kiểm tra: 3          │
│                                          │                          │
│                PDF VIEWER                │ ▼ Cấu trúc       1.5/2.0 │
│                                          │   2 phát hiện            │
│      marker và highlight theo bằng chứng │ ▼ Tính đầy đủ    2.0/2.5 │
│                                          │   1 mục cần kiểm tra     │
│                                          │ ▼ Nhất quán      1.6/2.0 │
│                                          │                          │
├──────────────────────────────────────────┴──────────────────────────┤
│ Trước | Mục cần kiểm tra tiếp | Lưu nháp | Duyệt | Duyệt & tiếp    │
└─────────────────────────────────────────────────────────────────────┘
```

#### 9.7.2. Kích thước và panel

- PDF chiếm khoảng 60–70% chiều rộng mặc định.
- Panel đánh giá rộng 360–480 px và có thể resize.
- Panel có thể thu gọn hoàn toàn.
- Danh sách bài nộp mở bằng drawer hoặc submission selector, không chiếm một cột cố định.
- Header và action bar luôn cố định trong viewport.
- Điểm tổng, trạng thái lưu và số mục cần kiểm tra luôn nhìn thấy mà không phải cuộn.

#### 9.7.3. PDF viewer

Toolbar tối thiểu:

- Trang trước/sau.
- Số trang hiện tại.
- Zoom in/out và fit width.
- Tìm kiếm trong tài liệu.
- Bật/tắt thumbnail trang.
- Bật/tắt marker.

Không đặt download, print và các công cụ ít dùng ngang hàng với thao tác review chính; đưa chúng vào menu “Thêm”.

#### 9.7.4. Tab Rubric

Đây là tab mặc định.

Mỗi tiêu chí hiển thị:

- Tên tiêu chí.
- Điểm hiện tại / điểm tối đa.
- Trọng số.
- Số phát hiện liên quan.
- Trạng thái xác nhận.
- Nút mở rộng.

Khi mở rộng:

- Mức rubric được chọn.
- Giải thích ngắn.
- Các phát hiện liên quan.
- Phương pháp tạo đề xuất.
- Các thao tác Chấp nhận, Sửa và Loại bỏ.

Không dùng slider làm cách duy nhất để nhập điểm. Luôn có ô nhập hoặc mức rubric có nhãn rõ ràng.

#### 9.7.5. Tab Phát hiện

Mỗi phát hiện là một card gọn gồm:

- Tiêu đề hành động được, ví dụ “Bổ sung mô tả luồng thay thế”.
- Loại hoặc mức độ.
- Tiêu chí liên quan.
- Trang và section.
- Đoạn trích bằng chứng.
- Giải thích.
- Trạng thái xác nhận.

Thao tác:

- Đi tới bằng chứng.
- Chấp nhận.
- Sửa nhận xét.
- Loại bỏ.
- Ghim cho sinh viên.
- Liên kết sang tiêu chí khác.

Danh sách hỗ trợ lọc theo tiêu chí, trạng thái và mức độ. Mặc định đưa các mục “Cần kiểm tra” lên trước.

#### 9.7.6. Tab Tổng kết

Gồm:

- Nhận xét tổng quan.
- Danh sách phản hồi đã ghim.
- Điểm tổng và breakdown ngắn.
- Kiểm tra trước khi duyệt.

Nhận xét tổng quan hỗ trợ comment mẫu nhưng phải cho phép giảng viên sửa trước khi công bố.

#### 9.7.7. Annotation

Loại annotation ban đầu:

- Highlight đoạn văn.
- Marker tại vùng bằng chứng.
- Comment ngoài lề.
- Liên kết tới tiêu chí.

Quy tắc hiển thị:

- Marker tự động chưa duyệt dùng đường viền rỗng.
- Marker đã được giảng viên xác nhận dùng nền đặc và có biểu tượng xác nhận.
- Khi không được chọn, highlight dùng độ tương phản thấp để giữ khả năng đọc.
- Chọn card sẽ làm nổi marker; chọn marker sẽ cuộn card vào tầm nhìn.
- Không dùng màu làm dấu hiệu duy nhất.
- Có nút ẩn toàn bộ annotation để đọc tài liệu nguyên bản.

#### 9.7.8. Autosave và xung đột

- Thay đổi phải được lưu tự động sau khoảng dừng ngắn.
- Header hiển thị `Đang lưu`, `Đã lưu` hoặc `Không thể lưu`.
- Nếu mất mạng, giữ thay đổi cục bộ và cảnh báo rõ.
- Không cho hai người ghi đè âm thầm cùng một bài.
- Nếu bài đang được người khác mở để duyệt, hiển thị người đó và dùng soft lock hoặc cảnh báo xung đột.

#### 9.7.9. Phím tắt đề xuất

| Phím | Hành động |
|---|---|
| `J` / `K` | Phát hiện tiếp theo / trước đó |
| `A` | Chấp nhận phát hiện đang chọn |
| `E` | Sửa phát hiện đang chọn |
| `D` | Loại bỏ phát hiện đang chọn |
| `[` / `]` | Trang PDF trước / sau |
| `Shift + Enter` | Duyệt và chuyển bài tiếp theo |
| `?` | Mở danh sách phím tắt |

Phím tắt không được kích hoạt khi người dùng đang nhập trong text field.

### 9.8. Upload của sinh viên

Màn hình upload chỉ gồm một luồng chính.

Thông tin trước upload:

- Tên đợt đánh giá.
- Hạn nộp nếu có.
- Yêu cầu file.
- Rubric hoặc tiêu chí được phép xem trước.
- Trạng thái lần nộp hiện tại.

Dropzone phải nói rõ:

> Chỉ chấp nhận PDF có thể chọn và sao chép văn bản. Không chấp nhận tài liệu scan hoặc tài liệu trộn trang scan.

Sau khi chọn file, kiểm tra theo hai bước:

1. Kiểm tra nhanh trên trình duyệt: định dạng, khả năng mở file.
2. Kiểm tra trên hệ thống: text layer, trang scan/trộn scan và tính hợp lệ của tài liệu.

Ví dụ lỗi tốt:

> Trang 4–6 không có text layer nên hệ thống không thể đánh giá ổn định. Hãy xuất lại toàn bộ tài liệu từ Word hoặc LaTeX rồi nộp lại.

Ví dụ lỗi không được dùng:

> File không hợp lệ.

Không rời màn hình hoặc xóa lựa chọn của người dùng khi validation thất bại.

### 9.9. Trạng thái xử lý của sinh viên

Hiển thị timeline ngắn:

```text
Đã nhận tài liệu → Đã kiểm tra PDF → Đang đánh giá → Chờ duyệt → Đã công bố
```

- Không hiển thị phần trăm giả nếu hệ thống không đo được tiến độ thực.
- Có thể hiển thị thời gian cập nhật gần nhất.
- Khi xử lý lỗi, nói rõ sinh viên cần nộp lại hay giảng viên/admin đang xử lý.
- Không hiển thị kết quả tạm thời nếu chưa được phép công bố.

### 9.10. Kết quả của sinh viên

Thứ tự thông tin:

1. Trạng thái đã công bố và điểm tổng.
2. Ba đến năm phản hồi được giảng viên ghim.
3. Breakdown theo tiêu chí.
4. PDF và annotation.
5. Toàn bộ phát hiện và nhận xét.

Mỗi tiêu chí hiển thị:

- Điểm đạt được / điểm tối đa.
- Mức rubric.
- Nhận xét ngắn.
- Liên kết tới bằng chứng trong PDF.

Sinh viên không thấy:

- Prompt LLM.
- Rule ID.
- Độ tin cậy kỹ thuật chưa được hiệu chuẩn.
- Phát hiện đã bị giảng viên loại bỏ.
- Nhật ký nội bộ.

Nếu có chức năng yêu cầu xem lại điểm, nó phải liên kết với tiêu chí hoặc phát hiện cụ thể, không chỉ là một hộp thoại chung.

### 9.11. Admin

#### Người dùng

- Bảng người dùng, vai trò, trạng thái và hoạt động gần nhất.
- Phân quyền phải có xác nhận khi thay đổi vai trò nhạy cảm.

#### Rubric mặc định

- Quản lý phiên bản rubric.
- Xem số đợt đánh giá đang sử dụng một phiên bản.
- Không sửa nội dung đã được dùng để chấm; tạo phiên bản mới.

#### Hoạt động xử lý

- Số job đang chờ, đang chạy, thất bại và cần thử lại.
- Bộ lọc theo đợt đánh giá, trạng thái và thời gian.
- Lỗi kỹ thuật đầy đủ chỉ hiển thị cho người có quyền.

#### Mức sử dụng

- Số tài liệu và số trang đã xử lý.
- Mức sử dụng LLM/API nếu có.
- Chi phí ước tính phải ghi rõ là ước tính.
- Không biến màn hình này thành dashboard hạ tầng phức tạp.

## 10. Hệ thống thiết kế trực quan

### 10.1. Phong cách

- Trung tính, sáng, ít màu.
- Không gradient.
- Không glassmorphism.
- Không shadow lớn.
- Không dùng card bo tròn quá mức.
- Ưu tiên hierarchy bằng khoảng cách, typography và border.

### 10.2. Màu đề xuất

| Token | Giá trị tham khảo | Mục đích |
|---|---|---|
| `background` | `#F7F8FA` | Nền ứng dụng |
| `surface` | `#FFFFFF` | Panel và nội dung |
| `text-primary` | `#111827` | Nội dung chính |
| `text-secondary` | `#667085` | Nội dung phụ |
| `border` | `#D0D5DD` | Đường phân cách |
| `primary` | `#2563EB` | Hành động chính |
| `primary-hover` | `#1D4ED8` | Hover |
| `success` | `#15803D` | Hoàn tất/đã duyệt |
| `warning` | `#B45309` | Cần kiểm tra |
| `danger` | `#B42318` | Lỗi/nguy hiểm |
| `info` | `#175CD3` | Đang xử lý/thông tin |

Màu trạng thái phải đi kèm text hoặc icon.

### 10.3. Typography

- Font giao diện: system sans-serif hoặc Inter-compatible.
- Body mặc định: 14–16 px.
- Line-height body: 1.45–1.6.
- Tiêu đề trang: 24–28 px, semibold.
- Tiêu đề section: 18–20 px, semibold.
- Không dùng quá ba cấp độ đậm trong một màn hình.
- Không dùng chữ viết hoa cho câu hoặc nút dài.

### 10.4. Khoảng cách và hình dạng

- Hệ thống spacing: 4, 8, 12, 16, 24, 32 px.
- Border radius cơ bản: 6–8 px.
- Dialog có thể dùng 10–12 px.
- Border 1 px dùng nhiều hơn shadow.
- Icon giao diện dùng một bộ outline thống nhất, cỡ 18–20 px.

## 11. Component rules

### 11.1. Button

- Một vùng chỉ có một primary button.
- Hành động phá hủy dùng danger style và yêu cầu xác nhận phù hợp.
- Nút chỉ có icon phải có tooltip và accessible label.
- Nút loading giữ nguyên chiều rộng để giao diện không nhảy.

### 11.2. Tabs

- Dùng tabs cho các góc nhìn của cùng một đối tượng.
- Không dùng tabs thay cho quy trình nhiều bước.
- Số tab trong panel review không vượt quá bốn.

### 11.3. Table

- Header sticky khi bảng dài.
- Cho phép lọc và sort các cột quan trọng.
- Không nhồi quá nhiều icon action vào mỗi dòng; dùng một hành động chính và menu “Thêm”.
- Trạng thái rỗng giải thích vì sao chưa có dữ liệu và hành động tiếp theo.

### 11.4. Dialog

- Chỉ dùng cho xác nhận ngắn hoặc chỉnh sửa nhỏ.
- Không dùng dialog cho Rubric Builder, review tài liệu hoặc form nhiều bước.
- Không mở dialog chồng dialog.

### 11.5. Toast và thông báo

- Toast dùng cho xác nhận ngắn như “Đã lưu”.
- Lỗi cần hành động không được chỉ xuất hiện trong toast; phải tồn tại trong màn hình cho tới khi được xử lý.
- Hành động có thể hoàn tác nên cung cấp Undo trong khoảng thời gian hợp lý.

## 12. Loading, empty và error states

### 12.1. Loading

- Dùng skeleton cho bảng và panel.
- PDF viewer hiển thị khung trang đang tải, không để toàn màn hình trắng.
- Không khóa toàn bộ giao diện khi chỉ một panel đang refresh.

### 12.2. Empty

Empty state phải trả lời:

1. Chưa có gì?
2. Vì sao?
3. Người dùng có thể làm gì tiếp theo?

### 12.3. Error

Mỗi lỗi hướng người dùng phải có:

- Mô tả ngắn.
- Nguyên nhân ở mức người dùng hiểu được.
- Hành động khắc phục.
- Mã tham chiếu nếu cần liên hệ hỗ trợ.

Không hiển thị stack trace, tên model, queue hoặc exception nội bộ cho sinh viên/giảng viên.

## 13. Responsive design

### 13.1. Desktop

- Không gian review được thiết kế desktop-first.
- Kích thước khuyến nghị từ 1280 px trở lên.
- Ở 1024–1279 px, panel đánh giá hẹp hơn nhưng vẫn giữ split view.

### 13.2. Tablet

- PDF và panel đánh giá chuyển thành hai tab hoặc bottom sheet.
- Cho phép đọc, comment và duyệt cơ bản.
- Không yêu cầu Rubric Builder đầy đủ hoạt động tốt trên tablet trong phiên bản đầu tiên.

### 13.3. Mobile

- Sinh viên phải upload, theo dõi trạng thái và xem kết quả được.
- Giảng viên có thể xem trạng thái và nhận xét tổng quan.
- Không cố nhét toàn bộ không gian review desktop vào màn hình nhỏ.

## 14. Accessibility

Mục tiêu tối thiểu: WCAG 2.2 AA.

- Mọi thao tác chính phải dùng được bằng bàn phím.
- Không có keyboard trap trong PDF viewer, dialog hoặc panel.
- Focus phải luôn nhìn thấy và không bị sticky header/footer che khuất.
- Vùng bấm tối thiểu tuân theo WCAG 2.2; nên dùng 40 x 40 px cho thao tác chính.
- Text và UI component phải đạt tương phản phù hợp.
- Marker và trạng thái không phụ thuộc duy nhất vào màu.
- Annotation phải có danh sách text tương đương cho screen reader.
- Panel resize phải có điều khiển bàn phím hoặc kích thước preset.
- Tooltip không được chứa thông tin duy nhất cần thiết để hoàn thành tác vụ.
- Tài liệu vẫn có thể xem ở chế độ text/outline khi PDF canvas không phù hợp với công nghệ hỗ trợ.

Tham khảo: [Web Content Accessibility Guidelines 2.2 — W3C](https://www.w3.org/TR/WCAG22/).

## 15. Hiệu năng cảm nhận

Các mục tiêu sau là yêu cầu UX, không phải cam kết hạ tầng cụ thể:

- App shell và metadata phải xuất hiện trước khi toàn bộ PDF tải xong.
- Tải trang PDF theo nhu cầu; ưu tiên trang đang xem và các trang liền kề.
- Chuyển phát hiện phải phản hồi ngay; không tải lại toàn bộ PDF.
- Autosave chạy nền và không chặn thao tác tiếp theo.
- Prefetch bài tiếp theo khi giảng viên gần hoàn thành bài hiện tại.
- Danh sách dài phải phân trang hoặc virtualize.
- Khi job xử lý lâu, người dùng có thể rời trang và quay lại mà không mất trạng thái.

## 16. Quy tắc nội dung giao diện

- Viết ngắn, trực tiếp và hướng tới hành động.
- Dùng “Đánh giá”, “Duyệt”, “Công bố”, không dùng các từ kỹ thuật như inference hoặc worker.
- Dùng “Đề xuất tự động”, không dùng “AI đã quyết định”.
- Comment cho sinh viên nên nói việc cần làm tiếp theo.
- Không gắn nhãn “Sai” cho mọi phát hiện; phân biệt Lỗi, Cần xem lại và Gợi ý cải thiện.

Ví dụ:

- Tốt: `Bổ sung mô tả điều kiện kết thúc của luồng thay thế.`
- Chưa tốt: `Use case không hợp lý.`
- Tốt: `Đã lưu lúc 14:32.`
- Chưa tốt: `Success.`

## 17. Thứ tự triển khai giao diện

### Giai đoạn 1 — Prototype có dữ liệu giả

1. App shell và role navigation.
2. Danh sách bài nộp của giảng viên.
3. Không gian review với PDF giả lập, rubric và findings.
4. Upload và trạng thái xử lý của sinh viên.
5. Kết quả sinh viên.

Mục tiêu: kiểm tra luồng và mật độ thông tin trước khi nối backend.

### Giai đoạn 2 — MVP

1. Upload và validation PDF.
2. Hiển thị trạng thái xử lý thực.
3. Review workspace nối dữ liệu đánh giá.
4. Chấp nhận, sửa, loại bỏ phát hiện.
5. Autosave, duyệt và công bố.
6. Rubric mặc định và cấu hình trọng số.
7. Admin quản lý người dùng và job.

### Giai đoạn 3 — Tối ưu quy mô sử dụng

1. Phím tắt và command palette.
2. Thư viện comment dùng lại.
3. Review hàng loạt và phân công người duyệt.
4. Rubric versioning nâng cao.
5. Theo dõi mức sử dụng và chi phí.
6. Tích hợp hệ thống bên ngoài nếu cần.

### Giai đoạn 4 — Cấu hình đánh giá nâng cao

1. Công thức tùy chỉnh.
2. Rule builder.
3. Code evaluator có sandbox và validation.
4. Preview kết quả trên tài liệu mẫu.
5. Audit và rollback phiên bản.

## 18. Acceptance checklist cho prototype

### Toàn cục

- [ ] Nhận diện riêng, không sao chép thương hiệu Turnitin/Gradescope.
- [ ] Giao diện trung tính, không gradient và không thừa màu.
- [ ] Mỗi màn hình có một hành động chính rõ ràng.
- [ ] Loading, empty và error state đều được thiết kế.
- [ ] Điều hướng theo vai trò rõ ràng.

### Review workspace

- [ ] PDF là vùng lớn nhất.
- [ ] Điểm, trạng thái lưu và mục cần kiểm tra luôn nhìn thấy.
- [ ] Panel đánh giá resize và thu gọn được.
- [ ] Bấm finding nhảy đúng tới bằng chứng.
- [ ] Bấm marker chọn đúng finding.
- [ ] Có Chấp nhận, Sửa và Loại bỏ đề xuất.
- [ ] Có Duyệt và Duyệt & tiếp.
- [ ] Không mất comment khi refresh hoặc mất kết nối ngắn.
- [ ] Có thể ẩn annotation để đọc tài liệu nguyên bản.
- [ ] Dùng được các thao tác chính bằng bàn phím.

### Rubric

- [ ] Có rubric mặc định và rubric tùy chỉnh.
- [ ] Tổng trọng số luôn hiển thị.
- [ ] Không cho phát hành rubric sai tổng trọng số bắt buộc.
- [ ] Rubric hệ thống chỉ được nhân bản, không sửa trực tiếp.
- [ ] Mỗi thay đổi có lịch sử phiên bản phù hợp.

### Sinh viên

- [ ] Điều kiện PDF hợp lệ hiển thị trước khi upload.
- [ ] Lỗi scan/trộn scan chỉ rõ trang và cách khắc phục.
- [ ] Trạng thái xử lý dễ hiểu.
- [ ] Chỉ hiển thị kết quả đã được công bố.
- [ ] Phản hồi được ghim xuất hiện trước breakdown chi tiết.
- [ ] Bấm nhận xét mở đúng bằng chứng trong PDF.

## 19. Tài liệu trực quan tham khảo

Chỉ dùng để hiểu bố cục và hành vi, không dùng làm tài sản sản phẩm:

- [Turnitin Feedback Studio: giao diện rubric trong document viewer](https://desystemshelp.leeds.ac.uk/turnitin-staff/how-to-download-submissions-from-turnitin-with-rubric-marks-included-staff-guide/)
- [Turnitin Feedback Studio: marking and feedback](https://elearn.soton.ac.uk/knowledge-base/feedback-studio-pc/)
- [Gradescope: homework grading interface](https://www.teachingcollege.fse.manchester.ac.uk/gradescope-homework-assignment/)
- [Gradescope: individual submission view](https://lpt.it.miami.edu/platforms/supported/gradescope/index.html)

## 20. Tóm tắt quyết định để bắt đầu repo mới

Nếu chỉ đọc một phần trước khi triển khai, sử dụng các quyết định sau:

1. Dựng ứng dụng độc lập với ba role: Admin, Giảng viên và Sinh viên.
2. Dùng thiết kế Hybrid Turnitin + Gradescope, không clone thương hiệu.
3. Review workspace mặc định là PDF bên trái và panel đánh giá bên phải.
4. Rubric là tab mặc định; finding luôn liên kết với bằng chứng.
5. Kết quả tự động là đề xuất cho tới khi giảng viên xác nhận.
6. Điểm, autosave và mục cần kiểm tra phải luôn nhìn thấy.
7. Sinh viên chỉ thấy kết quả đã công bố và phản hồi đã được duyệt.
8. Giao diện dùng nền sáng, màu trung tính và một màu primary.
9. Prototype review workspace trước khi xây toàn bộ dashboard.
10. Kiểm thử bằng bàn phím, PDF dài, rubric dài, nhiều findings và kết nối chậm ngay từ prototype.
