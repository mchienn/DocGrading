"""Notebook pipeline 2 prompts; application JSON contracts override output examples."""

SYS_MAP_BASE = """Trích xuất từ [CHUNK], dùng [SECTION] xác định phạm vi.
Chỉ JSON, bỏ field rỗng, không suy diễn hay kết luận mâu thuẫn.
Chỉ trích xuất các nhóm được yêu cầu bên dưới."""

SYS_MAP_SUMMARY = """summary_sentence: tóm tắt 1 câu <=35 từ."""

SYS_MAP_TERMINOLOGY = """terminology:
CHỈ trích thuật ngữ được giải thích trực tiếp về
bản chất, ý nghĩa hoặc chức năng đặc trưng trong CHUNK.
Bao gồm khái niệm, từ viết tắt, bảng, trường dữ liệu
và thành phần có định nghĩa rõ ràng.

Giữ mọi định nghĩa hợp lệ, kể cả dạng \"X: ý nghĩa\"
hoặc mô tả chức năng ngắn, không cần có từ \"là\".
Trích độc lập từng CHUNK, không bỏ định nghĩa lặp lại.

BỎ tên công nghệ, mô hình, dịch vụ chỉ được nêu qua
cách sử dụng, mục đích triển khai hoặc tích hợp.
BỎ mô tả chung chung, liệt kê và thông số cấu hình.
Chỉ giữ chức năng vốn có của thuật ngữ, không biến
mục đích sử dụng trong hệ thống thành định nghĩa.

Mỗi record: term, is_acronym, definition.
term=nguyên văn, giữ chữ hoa/thường, bỏ ký hiệu bao quanh.
definition=ý nghĩa cốt lõi, ngắn gọn và có căn cứ trực tiếp.
Không suy diễn, thêm kiến thức ngoài hoặc gộp giữa các chunk."""

SYS_MAP_DATA = """data_claims: entity, attribute, value;
thêm unit/time/condition/population/scope nếu có."""

SYS_MAP_LOGIC = """logic_statements:
CHỈ lấy quy tắc vận hành có thể kiểm tra mâu thuẫn:
- Quyền/cấm, nghĩa vụ, điều kiện cần/đủ, IF/ELSE, ngoại lệ.
- Chuyển trạng thái, trigger, thứ tự bắt buộc, kết quả bảo đảm.
- Điều kiện xử lý file/dữ liệu, bảo mật, quyền truy xuất
  kể cả thể hiện gián tiếp qua is_public, user_id.
- Quy tắc nghiệp vụ dù không có từ khóa rõ ràng.

BỎ số liệu/giới hạn độc lập thuộc data_claims;
giữ số nếu chi phối điều kiện hoặc hành vi của quy tắc.
BỎ logic ở lời cam đoan, giới thiệu, so sánh hệ thống,
kết luận, định hướng tương lai; bỏ mô tả chức năng,
kiến trúc, công cụ, thao tác không có ràng buộc.
Không biến khả năng thành quyền, mục đích thành điều kiện,
hạn chế thành lệnh cấm; không suy diễn quyền chưa nêu.

Mỗi quy tắc độc lập = 1 record; không trùng lặp.
Tách nhánh, tác động hoặc thứ tự có thể mâu thuẫn riêng;
không tách thao tác thông thường.

TYPE: PRECONDITION, POSTCONDITION, STATE_TRANSITION,
AUTHORIZATION, BUSINESS_RULE, ORDER, TRIGGER_EVENT, EXCEPTION_FLOW.
PRECONDITION=điều kiện cần, không phải mọi IF.
POSTCONDITION=kết quả bảo đảm.
AUTHORIZATION=quyền/cấm, actor là chủ thể được xét quyền.
ORDER=thứ tự có căn cứ; TRIGGER_EVENT=sự kiện kích hoạt.
EXCEPTION_FLOW=nhánh lỗi; BUSINESS_RULE=quy tắc xử lý/chính sách,
không phải loại mặc định.

Mỗi record: type, subject, source_quote;
thêm khi có căn cứ: actor, action, condition, result,
from_state, to_state, polarity, relation.
subject=đối tượng chịu quy tắc/sở hữu trạng thái.
actor=chủ thể thực hiện hoặc được xét quyền.
action=động từ+đối tượng, không chứa điều kiện.
condition=điều kiện áp dụng, giữ AND/OR/NOT và ngoại lệ.
result=kết quả, không lặp action hay mục đích.
from_state/to_state=chỉ khi chuyển trạng thái.
polarity=allow/deny cho quyền, require/prohibit cho nghĩa vụ.
ORDER: subject=sự kiện A, result=sự kiện B,
relation=before/after theo thứ tự được nêu.
source_quote=nguyên văn ngắn đủ chứng minh quy tắc."""

MAP_GROUPS = {
    "GLOBAL_COHERENCE": ("summary_sentence", SYS_MAP_SUMMARY),
    "TERMINOLOGY_CONSISTENCY": ("terminology", SYS_MAP_TERMINOLOGY),
    "DATA_CONSISTENCY": ("data_claims", SYS_MAP_DATA),
    "LOGICAL_CONSISTENCY": ("logic_statements", SYS_MAP_LOGIC),
}


def build_map_prompt(kinds) -> str:
    parts = [prompt for kind, (_, prompt) in MAP_GROUPS.items() if kind in kinds]
    if not parts:
        return ""
    return "\n\n".join([
        SYS_MAP_BASE,
        *parts,
        "Không tự điền thông tin thiếu. Chỉ xuất nhóm có dữ liệu.",
    ])


SYS_MAP = build_map_prompt(MAP_GROUPS)

BATCH_VERIFY_SYSTEM = """Kiểm chứng từng candidate bằng evidence gốc; candidate/graph/SMT chỉ là giả thuyết.
Chỉ VERIFIED nếu các rule cùng đối tượng, hành động, actor, thời điểm, phiên bản, phạm vi
và tạo nghĩa vụ/quyền/trạng thái bất tương thích trong cùng kịch bản hợp lệ.
REJECTED nếu không xung đột; UNCERTAIN nếu thiếu bằng chứng liên kết hoặc phạm vi.
Quy tắc suy luận:
- IF: điều kiện đủ; ONLY_IF: điều kiện cần. Quy tắc hẹp hơn không tự là ngoại lệ.
- Kiểm tra chuỗi nhiều rule và luồng rút gọn có dùng cùng tiền điều kiện, quyền, trạng thái không.
- Cấm tự phê duyệt bao trùm có thể mâu thuẫn với quyền tự duyệt cụ thể; hậu kiểm không thay tiền kiểm.
- Gửi thông điệp không đồng nghĩa thực thi thành công; cùng dịch vụ không đồng nghĩa cùng tiền điều kiện.
- Không suy ra DEADLOCK/UNREACHABLE_STATE từ cạnh bị thiếu trong MAP.
- Không suy đoán từ tên role, loại candidate, cùng chunk (IN_CHUNK) hay giả thuyết chuẩn hóa.
- Supporting rules chỉ giúp xác định ngữ cảnh/phạm vi; rule_ids chỉ gồm rule trực tiếp mâu thuẫn.
- Severity: minor (nhỏ), moderate (ảnh hưởng hạn chế), major (ảnh hưởng nghiệp vụ chính),
  critical (vi phạm bất biến cốt lõi hoặc quyền/an toàn trọng yếu). Không phóng đại khi thiếu chứng cứ.
Trả lời ngắn, chính xác, không thêm rule_ids ngoài candidate."""

SYS_VERIFY_LOCAL = """Kiểm tra LOCAL COHERENCE của văn xuôi trong tài liệu khoa học.
Candidate chỉ là nghi vấn. Dựa vào section và ngữ cảnh trước/sau để xác minh:
- off_topic: toàn đoạn thực sự lệch chủ đề;
- intrusive_span: một hoặc nhiều câu liên tiếp phá vỡ mạch;
- flow_break: hai phần liền nhau thiếu liên kết hợp lý.
Không báo lỗi cho ví dụ, chuyển ý, đối chiếu, mở rộng nội dung có liên hệ.
Không kiểm tra factual, logic, thuật ngữ, bảng, code hay bố cục heading.
Không dùng similarity thấp làm bằng chứng duy nhất; thiếu chắc chắn thì bỏ.
Severity: minor = gián đoạn nhẹ; moderate = gây khó theo dõi;
major = phá vỡ rõ rệt mạch chính của đoạn.
Chỉ xuất lỗi đã xác nhận. JSON duy nhất:
{\"issues\":[{\"candidate_id\":\"LC_0001\",\"severity\":\"minor|moderate|major\",\"reason\":\"ngắn, cụ thể\"}]}.
Không có lỗi: {\"issues\":[]}."""

SYS_VERIFY_DATA = """Kiểm chứng DATA CONSISTENCY. Candidate là giả thuyết, không mặc định là lỗi.
Với mỗi cặp, xét entity, attribute (theo NGHĨA), giá trị đã chuẩn hóa, đơn vị,
time, condition, population và scope. Similarity/chung section chỉ là tín hiệu.
Chọn một relation:
- same_fact: hai giá trị tương thích, không mâu thuẫn.
- different_context: có bằng chứng rõ ràng hai claim áp dụng cho bối cảnh/đại lượng khác.
- insufficient_context: thiếu bằng chứng để khẳng định cùng fact hoặc cùng bối cảnh.
- conflict: cùng fact và bối cảnh áp dụng, giá trị không thể đồng thời đúng.
Field trống không tự chứng minh bối cảnh khác; cũng không chứng minh bối cảnh giống.
Nếu cùng fact, không có dấu hiệu khác bối cảnh và giá trị loại trừ nhau, có thể conflict.
Nếu chưa xác định chắc entity/attribute, thời điểm, phạm vi thì insufficient_context.
Không nhầm chỉ số toàn bộ với bộ phận, mục tiêu với thực tế, phiên bản hoặc thời kỳ khác.
Severity chỉ cho conflict: minor = ít ảnh hưởng; moderate = sai lệch cách hiểu/phân tích;
major = ảnh hưởng kết luận, đánh giá hoặc quyết định. Không phóng đại tác động.
Trả đúng một JSON cho mỗi candidate_index, không thêm văn bản:
{\"results\":[{\"candidate_index\":0,\"relation\":\"conflict\",\"is_error\":true,\"severity\":\"moderate\",\"reason\":\"ngắn gọn\"}]}
Với các relation khác conflict, is_error=false và severity=\"\".
"""

SYS_VERIFY_POLYSEMY = """Kiểm tra tính nhất quán định nghĩa của CÙNG một thuật ngữ.
Candidate và các chỉ số similarity/coverage chỉ dùng để sàng lọc, không chứng minh lỗi.

Phân loại quan hệ:
- same_meaning: cùng nghĩa, khác cách diễn đạt.
- role_description: bản chất so với vai trò/chức năng.
- specialization: định nghĩa cụ thể hóa định nghĩa kia.
- generalization: định nghĩa khái quát hơn định nghĩa kia.
- related_description: hai khía cạnh khác nhau nhưng tương thích.
- invalid_definition: mơ hồ hoặc không đủ dữ kiện xác định nghĩa.
- conflict: hai nghĩa BẤT TƯƠNG THÍCH khi áp dụng cho cùng thuật ngữ.

Chỉ conflict nếu hai định nghĩa làm cùng đối tượng được hiểu, phân loại hoặc đo lường
khác nhau về bản chất, điều kiện cần/đủ, phạm vi, tiêu chí hợp lệ hoặc nghĩa acronym.
Nếu cả hai vẫn có thể cùng đúng (khác chi tiết, vai trò, nguồn tạo trạng thái) thì không
conflict. Không suy luận lỗi từ similarity thấp. Không đủ căn cứ: invalid_definition.

Trả đúng một kết quả cho mỗi candidate_index, JSON thuần, không markdown:
{\"results\":[{\"candidate_index\":0,\"relation\":\"same_meaning\",\"reason\":\"Giải thích ngắn dựa trên hai định nghĩa\"}]}
relation phải thuộc 7 loại liệt kê trên. Không thêm nội dung ngoài JSON."""

SYS_VERIFY_SYNONYM = """Kiểm tra liệu hai TÊN KHÁC NHAU có được dùng cho CÙNG một khái niệm.
Similarity của định nghĩa chỉ là candidate, không đủ xác nhận synonymy.

Chọn một relation:
- same_concept: cùng referent, hai tên độc lập thay thế được cho nhau trong ngữ cảnh.
- acronym_expansion: dạng viết tắt và dạng đầy đủ.
- translation_equivalent: hai cách gọi khác ngôn ngữ; không tự động là lỗi.
- instance_of: một thuật ngữ là sản phẩm/trường hợp/implementation của thuật ngữ kia.
- broader_narrower: một khái niệm rộng hơn khái niệm kia.
- same_category: cùng loại nhưng là hai đối tượng khác nhau.
- related_but_distinct: liên quan nhưng không cùng referent.
- different_concept: khác khái niệm.
- invalid_definition: thiếu thông tin phân biệt.

Chỉ báo is_error=true nếu relation=same_concept VÀ tài liệu dùng hai tên độc lập
cho đúng một referent. Không coi là lỗi do cùng lĩnh vực, cùng chức năng hay định nghĩa
có từ ngữ giống nhau. Nếu chưa chắc chắn, không báo lỗi.

Trả đúng một kết quả cho mỗi candidate_index, JSON thuần, không markdown:
{\"results\":[{\"candidate_index\":0,\"relation\":\"same_concept\",\"is_error\":true,\"reason\":\"Giải thích ngắn\"}]}
relation chỉ thuộc 9 loại trên. Không thêm nội dung ngoài JSON."""

SYS_GLOBAL_SUMMARY = """Tóm tắt mạch nội dung tài liệu thành 3–5 câu, không đánh giá hay sửa cấu trúc.
STRUCTURAL_ONLY chỉ xác nhận mục tồn tại, không chứng minh nội dung ảnh/bảng.
Chỉ trả JSON: {\"global_summary\":\"...\"}."""

SYS_GLOBAL_TRANSITIONS = """Xác minh Global Coherence giữa các section được đánh dấu nghi vấn.
Cosine thấp không phải bằng chứng lỗi. Chỉ báo khi mạch chủ đề/lập luận thực sự bị gián đoạn,
thiếu phụ thuộc cần thiết hoặc sai thứ tự theo ngữ cảnh toàn tài liệu.
Chuyển chương hợp lý, đổi từ vựng, mục ảnh/bảng chưa được đọc không phải lỗi.
Không chắc chắn thì bỏ qua. Phân loại: topic_discontinuity, missing_dependency,
wrong_order, logic_break, orphan_section. Severity: minor (nhỏ, cục bộ),
moderate (khó theo dõi một phần), major (gián đoạn mạch lập luận chính).
Trả JSON: {\"coherence_issues\":[{\"from_section\":\"S1\",\"to_section\":\"S2\",
\"issue_type\":\"...\",\"severity\":\"minor|moderate|major\",\"reason\":\"...\"}]}.
Chỉ nêu các lỗi có căn cứ, không thêm lỗi ngoài candidate."""

SYS_GLOBAL_STRUCTURE = """Kiểm tra mạch tổ chức và lập luận tổng thể của tài liệu theo section map.
Chỉ báo lỗi có căn cứ: topic_drift (lạc mục tiêu), orphan_section (mục không có vai trò),
wrong_order (thứ tự vô lý), missing_dependency (thiếu liên kết bắt buộc),
discourse_break (đứt mạch tổng thể). Severity: minor (cục bộ), moderate (ảnh hưởng
một phần), major (ảnh hưởng mạch chính hoặc nhiều phần).
Không chấm factual, logic contradiction, terminology, local coherence hay ngữ pháp.
STRUCTURAL_ONLY là mục có thật nhưng nội dung ảnh/bảng chưa được phân tích; không tự
suy diễn nội dung hay coi khoảng trống preprocessing là lỗi. Không chắc chắn thì bỏ qua.
Trả JSON: {\"coherence_issues\":[{\"section\":\"S1\",\"issue_type\":\"...\",
\"severity\":\"minor|moderate|major\",\"reason\":\"...\"}]}.
Chỉ nêu lỗi được chứng minh từ section map."""

TMPL_MAP = """[SECTION]: {sections}
[CHUNK]: {content}"""

SCORE_FORMAT = """
Chỉ chấm tiêu chí được yêu cầu theo rubric và detected_errors trong JSON đầu vào.
Rubric cụ thể do giảng viên cung cấp được ưu tiên; nếu không có, dùng rubric gốc.
detected_errors là kết quả từ bước phát hiện lỗi đã chạy trước lời gọi chấm điểm này.
Dùng toàn bộ danh sách lỗi này làm context để phân tích mức độ và quyết định điểm.
Thang điểm duy nhất là 0-10, không phải phần trăm. Không nhân điểm với trọng số.
Các levels dùng thang 0-10. Nếu rubric không mô tả mức điểm, dùng hướng dẫn bên dưới.
Giải thích mức độ, phạm vi ảnh hưởng và lý do trừ điểm bằng tiếng Việt.
Không tự thêm hoặc bỏ lỗi trong context. Nếu nhiều lỗi phản ánh cùng
một vấn đề, không trừ điểm hai lần cho cùng vấn đề.
Nếu không có lỗi, có thể cho 10 theo rubric nhưng chỉ kết luận \"không phát hiện lỗi\",
không khẳng định tài liệu chắc chắn đúng; nêu giới hạn nếu không có dữ liệu so sánh.
Không suy ra điểm từ số lượng lỗi bằng công thức trừ điểm cố định.
Chỉ trả JSON gồm score và analysis theo schema.
analysis chỉ 1–2 câu ngắn về mức độ và lý do điểm.
Không liệt kê lại từng lỗi, không sinh annotation, gợi ý hoặc trích dẫn mới.
Ứng dụng giữ nguyên lỗi và bằng chứng đã có từ bước xác minh.
Schema JSON thay thế định dạng báo cáo văn bản, nội dung đánh giá giữ nguyên.
"""

VERIFY_FORMAT = """
Định dạng cuối cùng theo schema JSON: results phải có đúng một quyết định cho
MỖI candidate, kể cả candidate không phải lỗi. Sao chép chính xác candidate_index
được gắn trong đầu vào; không dùng chỉ số chunk, record hoặc claim thay thế.
Không bỏ sót hoặc lặp index. Viết reason bằng tiếng Việt.
Với lỗi đã xác nhận, severity phải là minor, moderate hoặc major nếu schema
có trường severity; nếu không phải lỗi có thể để severity rỗng.
"""

SCORING_PROMPTS = {
    kind: prompt + SCORE_FORMAT
    for kind, prompt in {
        "LOGICAL_CONSISTENCY": """Chấm Logical Consistency 0-10, CHỈ từ các lỗi CONFIRMED đã nhóm theo nguyên nhân gốc.
Không tạo lỗi, không đếm đôi finding, rule_ids hoặc candidate; không nâng severity hay suy diễn tác động.
Dựa vào mức nghiêm trọng nhất và SỐ NGUYÊN NHÂN ĐỘC LẬP, không phải số bằng chứng.
Rubric bắt buộc (phù hợp khoảng điểm kiểm soát trong code):
- Chỉ minor: 9.0-9.9, mốc 9.7.
- Cao nhất moderate: 7.5-8.9, mốc 8.5.
- Đúng 1 major, không critical: 5.5-7.4, mốc 7.0.
- Có 1 critical HOẶC >=2 major: 3.0-5.4, mốc 5.0.
- >=2 critical độc lập: 0-2.9, mốc 2.4.
Ưu tiên mốc mặc định khi chứng cứ không chỉ rõ phạm vi. Chỉ hạ nhiều nếu có
bằng chứng về tác động rộng hoặc nhiều luồng độc lập; lỗi cô lập không mặc định lan toàn hệ thống.
Điều chỉnh quanh mốc theo tác động thực tế, có lý do rõ; cùng dữ liệu phải cùng cách chấm.
Trả JSON DUY NHẤT: {\"score\":7.0,\"status\":\"...\",\"analysis\":\"Lý do điểm, ngắn gọn\"}.""",
        "TERMINOLOGY_CONSISTENCY": """Chấm Terminology Consistency 0–10 (số nguyên) từ lỗi ĐÃ XÁC NHẬN.
Chỉ dùng synonymy_errors và polysemy_errors. Không tạo/xóa/sửa lỗi, không verify lại.
Synonymy = nhiều tên cho một concept; polysemy = một tên có nghĩa bất tương thích.
Polysemy thường ảnh hưởng nặng hơn khi làm thay đổi cách hiểu quy tắc/khái niệm.

RUBRIC NEO ĐIỂM (chọn theo tác động có bằng chứng, không chỉ theo số lượng):
10: không có lỗi.
9: 1–2 nhóm synonymy cục bộ, ảnh hưởng rất nhỏ.
8: 1 polysemy cục bộ hoặc vài vấn đề thuật ngữ, vẫn hiểu rõ tài liệu.
7: nhiều vấn đề độc lập, ảnh hưởng một số phần nhưng nghĩa chung vẫn hiểu được.
5–6: nhiều lỗi đáng kể lặp lại ở các phần, gây hiểu nhầm rõ rệt.
3–4: mơ hồ rộng khắp, nhiều định nghĩa/chỉ dẫn không rõ nghĩa.
1–2: phần lớn hệ thống thuật ngữ khó hiểu do nhiều xung đột nghiêm trọng.
0: hầu như không thể xác định nghĩa của thuật ngữ chính.

CÁCH CHỌN ĐIỂM:
- Ưu tiên mốc CAO nếu chỉ thấy 1–2 lỗi cục bộ; không suy rộng tác động thiếu chứng cứ.
- Các vị trí/cặp trùng cùng một vấn đề không thành nhiều nguyên nhân độc lập.
- Chỉ xuống dưới 7 nếu có bằng chứng ảnh hưởng đáng kể ở nhiều khái niệm/phần.
- Khi lưỡng lự giữa hai điểm, chọn điểm gần mốc neo phù hợp nhất.
- Viết overall_comment 1–3 câu nêu tình trạng và tác động chính, không liệt kê lại lỗi.

Chỉ xuất JSON: {\"terminology_score\":8,\"overall_comment\":\"...\"}.""",
        "DATA_CONSISTENCY": """Bạn chấm FACTUAL / DATA CONSISTENCY từ 0–10. Input CHỈ gồm các lỗi
đã được Verify xác nhận; không tạo, xóa, sửa hoặc xác minh lại lỗi.
Chấm theo NGUYÊN NHÂN/FACT ĐỘC LẬP, không theo số cặp hay số lần xuất hiện;
cùng một đại lượng, cùng bộ giá trị mâu thuẫn, cùng bối cảnh chỉ tính một nhóm lỗi.
Xét severity, mức độ ảnh hưởng đã được chứng minh và phạm vi trên tài liệu.
Không suy diễn lỗi lan rộng chỉ từ nhiều bản ghi hoặc nhiều section.
MỐC MẶC ĐỊNH (chọn mốc này nếu chưa có chứng cứ tăng nặng):
- 10: không có conflict được xác nhận.
- 9: 1–2 minor cục bộ.
- 8: 1 moderate cô lập hoặc vài minor.
- 7: 1 major cô lập hoặc vài moderate độc lập.
- 6: 2–3 major độc lập hoặc nhiều moderate ảnh hưởng nhiều phần.
- 5: nhiều major thực sự ảnh hưởng đáng kể tới độ tin cậy.
- 3–4: nhiều mâu thuẫn nghiêm trọng, lan rộng và tác động các dữ liệu cốt lõi.
- 1–2: mâu thuẫn có tính hệ thống, phần lớn dữ liệu quan trọng không đáng tin.
- 0: gần như không thể sử dụng dữ liệu vì mâu thuẫn nghiêm trọng và lan rộng.
Chỉ hạ dưới mốc khi evidence chứng minh ảnh hưởng lớn hơn; ưu tiên mốc cao
khi lỗi ít, cô lập, chưa rõ ảnh hưởng. Không chấm <5 chỉ vì đếm nhiều lỗi.
Chỉ trả JSON {\"factual_consistency_score\":7,\"overall_comment\":\"1-2 câu giải thích điểm và ảnh hưởng thực tế\"}.
Điểm là số nguyên 0–10. Không markdown.
""",
        "LOCAL_COHERENCE": """Chấm LOCAL COHERENCE từ 0 đến 10 dựa CHỈ trên lỗi đã Verify.
Không phát hiện lỗi = 10; không được kết luận toàn tài liệu hoàn hảo.
Đánh giá độ nghiêm trọng, số vùng lỗi ĐỘC LẬP và phạm vi ảnh hưởng thực sự.
Một vùng bị gắn nhiều loại lỗi chỉ tính một lần (lấy lỗi nặng nhất).
Không trừ theo số candidate, số câu hay độ thấp của semantic_score.
Không suy diễn lỗi cục bộ thành lỗi toàn tài liệu; không tự thêm hay nâng severity.
Mốc nhất quán: 1 minor cục bộ ≈9.5; 1 moderate ≈8.8; 1 major ≈7.8.
Một số lỗi độc lập ở nhiều vùng: khoảng 6.5–8 theo tác động.
Dưới 6 chỉ khi nhiều lỗi major độc lập làm mất mạch ở nhiều phần;
dưới 4 chỉ khi văn xuôi bị đứt mạch trên diện rộng có bằng chứng.
Với một lỗi cô lập, chỉ lệch mốc tối đa 0.4 khi có căn cứ rõ.
Trường hợp thiếu chứng cứ về phạm vi ảnh hưởng: ưu tiên mức nhẹ hơn.
Nêu nhận xét 1–2 câu, chỉ dựa vào input. Trả JSON duy nhất:
{\"local_coherence_score\":8.8,\"overall_comment\":\"...\"}.""",
        "GLOBAL_COHERENCE": """Chấm Global Coherence của tài liệu từ 0–10 dựa CHỈ trên lỗi đã xác nhận.
Không phát hiện lỗi mới, không thay severity, không chấm factual, logical, terminology,
local coherence hoặc grammar. Gộp lỗi cùng nguyên nhân/hậu quả, chỉ trừ một lần;
không dựa máy móc vào số lượng finding hay section_id.

MỐC THAM CHIẾU (chọn mức gần nhất rồi xét tác động thực tế):
- 1 minor cô lập: 9.5; vài minor cục bộ: khoảng 9.0.
- 1 moderate cô lập: 8.8; vài moderate độc lập: khoảng 8.0–8.4.
- 1 major cô lập: 7.8; 2 major thực sự độc lập: khoảng 7.0–7.3.
- 5–6: nhiều lỗi major làm hỏng rõ rệt tiến trình ở nhiều phần.
- Dưới 5: chỉ khi có bằng chứng cấu trúc tổng thể rất khó theo dõi.

Ưu tiên mốc cao cho lỗi cục bộ. Chỉ hạ sâu nếu evidence cho thấy phạm vi rộng;
không phạt phần thiếu do preprocessing/STRUCTURAL_ONLY. Khi tác động chưa rõ,
giữ mốc; điều chỉnh nhẹ (khoảng ±0.3) nếu có lý do cụ thể. Điểm một chữ số thập phân.
Nhận xét 1–3 câu, giải thích mức độ và nguyên nhân chính, không liệt kê lại mọi lỗi.
JSON duy nhất: {\"coherence_score\":8.8,\"overall_comment\":\"...\"}.""",
    }.items()
}
