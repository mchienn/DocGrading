import type { RubricCriterion } from '../types/docgrading';

export interface LevelDescriptor extends Record<string, unknown> {
  level: number;
  label: string;
  percentage: number;
  description: string;
}

export interface CatalogCriterion extends RubricCriterion {
  gradingBullets: string[];
  semanticPreview?: string[];
  evaluationMethod: 'AI' | 'HYBRID' | 'RULE_BASED' | 'MANUAL' | 'CITATION';
  levelDescriptors?: LevelDescriptor[];
}

export const COMMON_LEVEL_DESCRIPTORS: LevelDescriptor[] = [
  {
    level: 4,
    label: 'Đạt đầy đủ',
    percentage: 100,
    description: 'Đáp ứng yêu cầu của tiêu chí và không có lỗi đáng kể trong phạm vi kiểm tra.',
  },
  {
    level: 3,
    label: 'Tốt',
    percentage: 75,
    description: 'Đáp ứng phần lớn; chỉ còn lỗi cục bộ, không nghiêm trọng.',
  },
  {
    level: 2,
    label: 'Một phần',
    percentage: 50,
    description: 'Đáp ứng một phần; còn lỗi ảnh hưởng khả năng hiểu hoặc sử dụng.',
  },
  {
    level: 1,
    label: 'Yếu',
    percentage: 25,
    description: 'Có dấu hiệu đáp ứng nhưng lỗi nghiêm trọng hoặc thiếu phần lớn.',
  },
  {
    level: 0,
    label: 'Không đạt',
    percentage: 0,
    description: 'Thiếu hoặc sai bản chất; không có bằng chứng đáp ứng.',
  },
];

export const DEFAULT_SRS_CATALOG: CatalogCriterion[] = [
  {
    id: 'CRT-01',
    code: 'SRS-01',
    name: 'Đúng cấu trúc và template bắt buộc',
    description: 'Tài liệu tuân thủ cấu trúc SRS và template được giao.',
    weight: 7,
    maxLevel: 4,
    defaultEvaluator: 'Rule-Engine',
    evaluationMethod: 'RULE_BASED',
    evidenceRequired: true,
    gradingBullets: [
      'Có đủ phần bắt buộc của tài liệu SRS theo template môn học.',
      'Đúng thứ tự, tên mục và phạm vi nội dung của từng phần.',
      'Không thiếu trang bìa, lịch sử thay đổi hoặc thông tin tài liệu bắt buộc.',
    ],
  },
  {
    id: 'CRT-02',
    code: 'SRS-02',
    name: 'Heading, mục lục và section rỗng',
    description: 'Heading phân cấp đúng, mục lục khớp nội dung và không có section bắt buộc bị bỏ trống.',
    weight: 5,
    maxLevel: 4,
    defaultEvaluator: 'Rule-Engine',
    evaluationMethod: 'RULE_BASED',
    evidenceRequired: true,
    gradingBullets: [
      'Heading dùng cấp độ nhất quán, không nhảy cấp hoặc lặp số.',
      'Mục lục khớp tiêu đề và số trang trong nội dung.',
      'Section bắt buộc có nội dung hữu ích, không chỉ chứa tiêu đề hoặc placeholder.',
    ],
  },
  {
    id: 'CRT-03',
    code: 'SRS-03',
    name: 'Bảng, hình và caption',
    description: 'Bảng và hình có caption, đánh số, nội dung đọc được và được tham chiếu trong văn bản.',
    weight: 3,
    maxLevel: 4,
    defaultEvaluator: 'Rule-Engine',
    evaluationMethod: 'RULE_BASED',
    evidenceRequired: true,
    gradingBullets: [
      'Mỗi bảng và hình có số thứ tự cùng caption mô tả.',
      'Bảng, hình được nhắc tới từ phần nội dung liên quan.',
      'Nội dung không bị cắt, mờ hoặc thiếu chú thích cần thiết.',
    ],
  },
  {
    id: 'CRT-04',
    code: 'SRS-04',
    name: 'Requirement ID và tính nguyên tử',
    description: 'Mỗi yêu cầu có mã duy nhất và mô tả một hành vi hoặc ràng buộc có thể đánh giá độc lập.',
    weight: 7,
    maxLevel: 4,
    defaultEvaluator: 'Hybrid-IR',
    evaluationMethod: 'HYBRID',
    evidenceRequired: true,
    gradingBullets: [
      'Requirement ID đúng quy ước, duy nhất và không bị đứt chuỗi bất thường.',
      'Mỗi yêu cầu chỉ chứa một hành vi hoặc ràng buộc chính.',
      'Không gộp nhiều nghĩa bằng các liên từ làm mất khả năng kiểm tra độc lập.',
    ],
  },
  {
    id: 'CRT-05',
    code: 'SRS-05',
    name: 'Rõ ràng, không mơ hồ',
    description: 'Yêu cầu dùng ngôn ngữ cụ thể, một nghĩa và xác định rõ chủ thể cùng hành vi.',
    weight: 7,
    maxLevel: 4,
    defaultEvaluator: 'Hybrid-IR',
    evaluationMethod: 'HYBRID',
    evidenceRequired: true,
    gradingBullets: [
      'Tránh từ mơ hồ như “nhanh”, “thân thiện”, “phù hợp” khi không có ngưỡng đo.',
      'Chủ thể, hành động, đối tượng và điều kiện thực hiện được nêu rõ.',
      'Không dùng đại từ hoặc thuật ngữ khiến yêu cầu có nhiều cách hiểu.',
    ],
  },
  {
    id: 'CRT-06',
    code: 'SRS-06',
    name: 'Đầy đủ và kiểm thử được',
    description: 'Yêu cầu có đủ điều kiện, dữ liệu và kết quả để xây dựng tiêu chí nghiệm thu.',
    weight: 9,
    maxLevel: 4,
    defaultEvaluator: 'Hybrid-IR',
    evaluationMethod: 'HYBRID',
    evidenceRequired: true,
    gradingBullets: [
      'Nêu rõ đầu vào, điều kiện kích hoạt và kết quả mong đợi.',
      'Có tiêu chí nghiệm thu hoặc ngưỡng định lượng khi cần.',
      'Người kiểm thử có thể xác định đạt hoặc không đạt mà không phải suy đoán.',
    ],
  },
  {
    id: 'CRT-07',
    code: 'SRS-07',
    name: 'Nhất quán giữa các phần',
    description: 'Thông tin về tác nhân, dữ liệu, quy tắc và hành vi không mâu thuẫn giữa các phần.',
    weight: 7,
    maxLevel: 4,
    defaultEvaluator: 'Hybrid-IR',
    evaluationMethod: 'HYBRID',
    evidenceRequired: true,
    gradingBullets: [
      'Tên tác nhân, thực thể và chức năng được dùng nhất quán.',
      'Quy tắc nghiệp vụ và điều kiện không xung đột giữa requirement, use case và mô hình.',
      'Số liệu, trạng thái và quan hệ quan trọng khớp ở mọi vị trí liên quan.',
    ],
  },
  {
    id: 'CRT-08',
    code: 'SRS-08',
    name: 'Độ đầy đủ của Use Case',
    description: 'Use Case xác định đủ tác nhân, mục tiêu, điều kiện, luồng và kết quả.',
    weight: 8,
    maxLevel: 4,
    defaultEvaluator: 'Rule-Engine',
    evaluationMethod: 'RULE_BASED',
    evidenceRequired: true,
    gradingBullets: [
      'Có tác nhân, mục tiêu, tiền điều kiện và hậu điều kiện.',
      'Có luồng chính, luồng thay thế và ngoại lệ phù hợp.',
      'Mọi Use Case trong danh sách đều có đặc tả chi tiết tương ứng.',
    ],
  },
  {
    id: 'CRT-09',
    code: 'SRS-09',
    name: 'Logic của luồng Use Case',
    description: 'Các bước Use Case có thứ tự hợp lý, đầy đủ nhánh và không tự mâu thuẫn.',
    weight: 12,
    maxLevel: 4,
    defaultEvaluator: 'Hybrid-IR',
    evaluationMethod: 'HYBRID',
    evidenceRequired: true,
    gradingBullets: [
      'Mỗi bước nêu rõ bên thực hiện và phản hồi của hệ thống.',
      'Luồng thay thế hoặc ngoại lệ quay lại hay kết thúc tại điểm xác định.',
      'Tiền điều kiện, bước xử lý và hậu điều kiện tạo thành chuỗi logic.',
    ],
  },
  {
    id: 'CRT-10',
    code: 'SRS-10',
    name: 'Truy vết Actor–Use Case–Requirement',
    description: 'Quan hệ giữa mục tiêu tác nhân, Use Case và requirement được thể hiện đầy đủ hai chiều.',
    weight: 15,
    maxLevel: 4,
    defaultEvaluator: 'Hybrid-IR',
    evaluationMethod: 'HYBRID',
    evidenceRequired: true,
    gradingBullets: [
      'Mỗi Actor liên kết tới Use Case thuộc trách nhiệm của mình.',
      'Mỗi Use Case truy vết tới requirement nguồn và ngược lại.',
      'Không có Actor, Use Case hoặc requirement mồ côi.',
    ],
  },
  {
    id: 'CRT-11',
    code: 'SRS-11',
    name: 'Thuật ngữ, chính tả và văn phong',
    description: 'Tài liệu dùng thuật ngữ nhất quán, chính tả đúng và văn phong kỹ thuật rõ ràng.',
    weight: 10,
    maxLevel: 4,
    defaultEvaluator: 'Hybrid-IR',
    evaluationMethod: 'HYBRID',
    evidenceRequired: true,
    gradingBullets: [
      'Thuật ngữ nghiệp vụ và từ viết tắt được định nghĩa, dùng thống nhất.',
      'Không có lỗi chính tả hoặc ngữ pháp lặp lại gây khó hiểu.',
      'Câu văn khách quan, ngắn gọn và phù hợp tài liệu kỹ thuật.',
    ],
  },
  {
    id: 'CRT-12',
    code: 'SRS-12',
    name: 'Tính mạch lạc tổng thể',
    description: 'Toàn bộ tài liệu tạo thành một đặc tả có tổ chức, liên kết và dễ theo dõi.',
    weight: 10,
    maxLevel: 4,
    defaultEvaluator: 'LLM-Evaluator',
    evaluationMethod: 'AI',
    evidenceRequired: true,
    gradingBullets: [
      'Các phần chuyển tiếp hợp lý và cùng phục vụ phạm vi hệ thống đã nêu.',
      'Mức độ chi tiết cân đối, không lặp nội dung hoặc bỏ qua kết nối quan trọng.',
      'Người đọc có thể hiểu phạm vi, hành vi và ràng buộc hệ thống từ đầu đến cuối.',
    ],
  },
  {
    id: 'CRT-ACCURACY',
    code: 'ACC-01',
    name: 'Accuracy — Thuật ngữ, kiến thức và citations',
    description:
      'Kiểm tra độ chính xác của thuật ngữ và kiến thức được dẫn nguồn bằng citation checks xác định được và duyệt thủ công.',
    weight: 10,
    maxLevel: 4,
    defaultEvaluator: 'Citation checks + Manual review',
    evaluationMethod: 'CITATION',
    evidenceRequired: true,
    gradingBullets: [
      'DOI/arXiv và metadata của tài liệu tham khảo khớp nguồn được xác minh.',
      'Citation trong nội dung liên kết đúng tới bibliography; citation mồ côi, thiếu nguồn hoặc không resolve được phải được review.',
      'Giảng viên đối chiếu thủ công độ chính xác của thuật ngữ và kiến thức với nguồn đã dẫn trước khi chốt mức điểm.',
    ],
    semanticPreview: [
      'Đối chiếu claim với passage nguồn để xác định được hỗ trợ, hỗ trợ một phần, mâu thuẫn hoặc không liên quan.',
      'Kiểm tra nghĩa của thuật ngữ và kết luận trong ngữ cảnh claim–source thay vì chỉ kiểm tra metadata/linkage.',
      'Đo coverage và giữ evidence passage cho từng semantic verdict.',
    ],
  },
];
