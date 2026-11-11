"""Dữ liệu mẫu: môn Tin học 10 (lập trình Python) + một lớp có lịch sử học tập 3 tuần.

Dùng để dùng thử, trình diễn và kiểm thử. Tên học sinh là tên giả định.
"""

from __future__ import annotations

import math
import random
from datetime import timedelta
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.orm import Session

from .ai.base import AIProvider
from .config import Settings
from .models import (
    AssignmentStatus,
    Classroom,
    ItemGrade,
    Question,
    ScoreRecord,
    Subject,
    Submission,
    SubmissionImage,
    SubmissionStatus,
    Teacher,
    Topic,
)
from .services.assignments import approve_assignment, create_batch
from .services.mastery import difficulty_of
from .services.storage import save_submission_file
from .services.students import add_student
from .utils.text import round_quarter, strip_accents
from .utils.timeutil import utcnow

MAX_BY_LEVEL = {1: 1.0, 2: 2.0, 3: 3.0, 4: 4.0}

# (chủ đề, [(mức độ, nội dung, [(tiêu chí, điểm)], đáp án tham khảo)])
TIN_HOC_10: list[tuple[str, list[tuple[int, str, list[tuple[str, float]], str]]]] = [
    (
        "Biến, kiểu dữ liệu và lệnh gán",
        [
            (
                1,
                "Nêu quy tắc đặt tên biến trong Python. Trong các tên sau, tên nào hợp lệ, tên nào không hợp lệ? Vì sao?\n"
                "    so_luong    2x    _tong    diem-tb    class",
                [
                    (
                        "Nêu đúng quy tắc: chỉ gồm chữ cái, chữ số, dấu gạch dưới; không bắt đầu bằng chữ số; không trùng từ khóa",
                        0.5,
                    ),
                    ("Xác định đúng: hợp lệ so_luong, _tong; không hợp lệ 2x, diem-tb, class", 0.5),
                ],
                "Tên biến chỉ gồm chữ cái, chữ số và dấu gạch dưới, không bắt đầu bằng chữ số, không trùng từ khóa, "
                "phân biệt chữ hoa/thường.\nHợp lệ: so_luong, _tong.\nKhông hợp lệ: 2x (bắt đầu bằng số), diem-tb (chứa dấu -), class (từ khóa).",
            ),
            (
                2,
                "Cho đoạn chương trình:\na = 7\nb = 2\nc = a // b + a % b\nd = a / b\nprint(c, d)\n"
                "Hãy cho biết kết quả in ra màn hình và giải thích.",
                [
                    ("Tính đúng c = 4, giải thích phép // (chia lấy phần nguyên) và % (chia lấy dư)", 1.0),
                    ("Tính đúng d = 3.5, nêu phép / cho kết quả số thực", 1.0),
                ],
                "a // b = 3, a % b = 1 → c = 4; d = 7 / 2 = 3.5.\nKết quả: 4 3.5",
            ),
            (
                3,
                "Viết chương trình nhập vào hai số nguyên a và b (b khác 0), mỗi số trên một dòng. In ra tổng, hiệu, tích "
                "và thương của hai số (thương làm tròn 2 chữ số thập phân).",
                [
                    ("Nhập dữ liệu đúng, chuyển sang kiểu int", 1.0),
                    ("Tính và in đúng tổng, hiệu, tích", 1.0),
                    ("Tính thương và làm tròn 2 chữ số thập phân đúng cú pháp", 1.0),
                ],
                "a = int(input())\nb = int(input())\nprint(a + b, a - b, a * b)\nprint(round(a / b, 2))",
            ),
            (
                3,
                "Viết chương trình nhập chiều dài và chiều rộng của một hình chữ nhật (số thực), tính và in ra chu vi, "
                "diện tích của hình chữ nhật (làm tròn 2 chữ số thập phân).",
                [
                    ("Nhập dữ liệu đúng, chuyển sang kiểu float", 1.0),
                    ("Công thức chu vi, diện tích đúng", 1.5),
                    ("In kết quả làm tròn 2 chữ số thập phân", 0.5),
                ],
                "d = float(input())\nr = float(input())\nprint(round(2 * (d + r), 2), round(d * r, 2))",
            ),
            (
                4,
                "Viết chương trình nhập số giây n (0 ≤ n < 86400) và đổi ra dạng giờ:phút:giây, mỗi phần gồm 2 chữ số. "
                "Ví dụ n = 3725 thì in ra 01:02:05. Giải thích ngắn gọn cách tính.",
                [
                    ("Tính đúng giờ, phút, giây bằng phép // và %", 1.5),
                    ("In đúng định dạng hh:mm:ss có số 0 ở đầu", 1.5),
                    ("Giải thích cách tính rõ ràng", 1.0),
                ],
                'n = int(input())\nh = n // 3600\nm = n % 3600 // 60\ns = n % 60\nprint(f"{h:02d}:{m:02d}:{s:02d}")\n'
                "1 giờ = 3600 giây; phần dư sau khi lấy giờ chia 60 được số phút; phần dư khi chia 60 là số giây.",
            ),
        ],
    ),
    (
        "Câu lệnh rẽ nhánh if",
        [
            (
                1,
                "Viết cú pháp câu lệnh if...else trong Python. Việc thụt lề các lệnh bên trong có vai trò gì?",
                [
                    ("Viết đúng cú pháp if <điều kiện>: ... else: ... (có dấu hai chấm)", 0.5),
                    ("Nêu được thụt lề dùng để xác định khối lệnh thuộc if/else", 0.5),
                ],
                "if <điều kiện>:\n    <khối lệnh 1>\nelse:\n    <khối lệnh 2>\n"
                "Python dùng thụt lề để xác định các lệnh thuộc cùng một khối; thụt lề sai gây lỗi hoặc sai logic.",
            ),
            (
                2,
                "Cho đoạn chương trình:\nx = int(input())\nif x % 2 == 0 and x > 10:\n    print('A')\nelif x % 2 == 0:\n"
                "    print('B')\nelse:\n    print('C')\nCho biết kết quả in ra khi nhập x lần lượt là 12, 8 và 15. Giải thích.",
                [
                    ("x = 12 in ra A (chẵn và lớn hơn 10)", 0.75),
                    ("x = 8 in ra B (chẵn nhưng không lớn hơn 10)", 0.75),
                    ("x = 15 in ra C (số lẻ)", 0.5),
                ],
                "12 → A; 8 → B; 15 → C.",
            ),
            (
                3,
                "Viết chương trình nhập điểm trung bình môn của một học sinh (số thực từ 0 đến 10) và in ra xếp loại: "
                "Giỏi nếu điểm ≥ 8; Khá nếu điểm ≥ 6,5; Trung bình nếu điểm ≥ 5; còn lại là Yếu.",
                [
                    ("Nhập điểm và chuyển sang kiểu float", 0.75),
                    ("Dùng cấu trúc if–elif–else với các điều kiện đúng thứ tự", 1.5),
                    ("In đúng xếp loại tương ứng", 0.75),
                ],
                "d = float(input())\nif d >= 8:\n    print('Giỏi')\nelif d >= 6.5:\n    print('Khá')\nelif d >= 5:\n"
                "    print('Trung bình')\nelse:\n    print('Yếu')",
            ),
            (
                3,
                "Viết chương trình nhập một năm (số nguyên dương) và cho biết năm đó có phải năm nhuận không. Biết năm "
                "nhuận là năm chia hết cho 400, hoặc chia hết cho 4 nhưng không chia hết cho 100.",
                [
                    ("Nhập năm đúng kiểu int", 0.5),
                    ("Biểu thức điều kiện năm nhuận đúng (kết hợp and/or)", 2.0),
                    ("In kết luận đúng", 0.5),
                ],
                "n = int(input())\nif n % 400 == 0 or (n % 4 == 0 and n % 100 != 0):\n    print('Năm nhuận')\nelse:\n"
                "    print('Không nhuận')",
            ),
            (
                4,
                "Viết chương trình nhập ba số thực dương a, b, c. Kiểm tra ba số đó có phải độ dài ba cạnh của một tam giác "
                "hay không; nếu có, cho biết tam giác đó là tam giác đều, cân, vuông hay thường.",
                [
                    ("Kiểm tra đúng điều kiện tam giác (tổng hai cạnh bất kì lớn hơn cạnh còn lại)", 1.0),
                    ("Phân loại đúng tam giác đều, cân", 1.0),
                    ("Kiểm tra đúng tam giác vuông (định lí Pi-ta-go, xét đủ 3 trường hợp)", 1.5),
                    ("Cấu trúc rẽ nhánh hợp lí, in kết quả rõ ràng", 0.5),
                ],
                "a = float(input()); b = float(input()); c = float(input())\nif a + b > c and a + c > b and b + c > a:\n"
                "    if a == b == c:\n        print('Tam giác đều')\n    elif a == b or b == c or a == c:\n        print('Tam giác cân')\n"
                "    elif a*a + b*b == c*c or a*a + c*c == b*b or b*b + c*c == a*a:\n        print('Tam giác vuông')\n"
                "    else:\n        print('Tam giác thường')\nelse:\n    print('Không phải tam giác')",
            ),
        ],
    ),
    (
        "Vòng lặp for và while",
        [
            (
                1,
                "Cho biết dãy giá trị mà range(2, 11, 3) tạo ra. Vòng lặp for i in range(5) thực hiện bao nhiêu lần, "
                "i nhận những giá trị nào?",
                [("range(2, 11, 3) tạo ra 2, 5, 8", 0.5), ("for i in range(5) lặp 5 lần, i = 0, 1, 2, 3, 4", 0.5)],
                "range(2, 11, 3): 2, 5, 8.\nrange(5): lặp 5 lần với i = 0, 1, 2, 3, 4.",
            ),
            (
                2,
                "Cho đoạn chương trình:\ns = 0\nfor i in range(1, 6):\n    if i % 2 == 1:\n        s = s + i\nprint(s)\n"
                "Cho biết kết quả in ra màn hình và giải thích.",
                [("Chỉ ra các giá trị i được cộng là 1, 3, 5", 1.0), ("Kết quả in ra 9", 1.0)],
                "i chạy từ 1 đến 5; chỉ cộng các số lẻ: 1 + 3 + 5 = 9. In ra 9.",
            ),
            (
                2,
                "Cho đoạn chương trình:\nn = 10\nk = 0\nwhile n > 0:\n    n = n - 3\n    k = k + 1\nprint(n, k)\n"
                "Vòng lặp thực hiện bao nhiêu lần? Kết quả in ra là gì?",
                [("Vòng lặp thực hiện 4 lần (n: 10 → 7 → 4 → 1 → -2)", 1.0), ("Kết quả in ra -2 4", 1.0)],
                "n lần lượt 10 → 7 → 4 → 1 → -2, dừng khi n ≤ 0. Lặp 4 lần, in ra: -2 4",
            ),
            (
                3,
                "Viết chương trình nhập số nguyên dương n, tính tổng S = 1 + 1/2 + 1/3 + ... + 1/n và in kết quả "
                "với 3 chữ số thập phân.",
                [
                    ("Nhập n đúng kiểu int", 0.5),
                    ("Vòng lặp duyệt đúng i từ 1 đến n (range(1, n + 1))", 1.0),
                    ("Khởi tạo S = 0 và cộng dồn 1/i đúng", 1.0),
                    ("In kết quả 3 chữ số thập phân", 0.5),
                ],
                'n = int(input())\ns = 0\nfor i in range(1, n + 1):\n    s = s + 1 / i\nprint(f"{s:.3f}")',
            ),
            (
                3,
                "Viết chương trình nhập số nguyên dương n và in ra tổng các chữ số của n. Ví dụ n = 2026 thì in ra 10.",
                [
                    ("Nhập n đúng kiểu int", 0.5),
                    ("Dùng vòng lặp while với % 10 và // 10 để tách từng chữ số", 1.5),
                    ("Cộng dồn và in kết quả đúng", 1.0),
                ],
                "n = int(input())\ns = 0\nwhile n > 0:\n    s += n % 10\n    n //= 10\nprint(s)",
            ),
            (
                4,
                "Viết chương trình nhập số nguyên n > 1 và kiểm tra n có phải số nguyên tố không. Yêu cầu chỉ kiểm tra "
                "các ước từ 2 đến √n và giải thích vì sao như vậy là đủ.",
                [
                    ("Thuật toán kiểm tra ước đúng, kết luận đúng", 1.5),
                    ("Chỉ duyệt đến √n (vd while i * i <= n)", 1.0),
                    ("Giải thích: nếu n có ước d > √n thì n/d < √n cũng là ước", 1.0),
                    ("Trình bày, in kết quả rõ ràng", 0.5),
                ],
                "n = int(input())\nla_nt = True\ni = 2\nwhile i * i <= n:\n    if n % i == 0:\n        la_nt = False\n"
                "        break\n    i += 1\nprint('Là số nguyên tố' if la_nt else 'Không là số nguyên tố')\n"
                "Nếu n = d·e với d > √n thì e = n/d < √n, nên chỉ cần xét các ước không vượt quá √n.",
            ),
        ],
    ),
    (
        "Kiểu dữ liệu danh sách (list)",
        [
            (
                1,
                "Cho A = [3, 8, 1, 6]. Cho biết giá trị của A[0], A[-1] và len(A).",
                [("A[0] = 3 và A[-1] = 6 (chỉ số âm tính từ cuối)", 0.5), ("len(A) = 4", 0.5)],
                "A[0] = 3; A[-1] = 6; len(A) = 4.",
            ),
            (
                2,
                "Cho đoạn chương trình:\nA = [5, 2, 9]\nA.append(4)\nA.insert(1, 7)\nA.remove(9)\nprint(A)\n"
                "Giải thích tác dụng của từng lệnh và cho biết kết quả in ra.",
                [("Giải thích đúng append, insert, remove", 1.0), ("Kết quả [5, 7, 2, 4]", 1.0)],
                "append(4): [5, 2, 9, 4]; insert(1, 7): [5, 7, 2, 9, 4]; remove(9) xóa phần tử 9 đầu tiên: [5, 7, 2, 4].",
            ),
            (
                3,
                "Viết chương trình nhập số nguyên n, sau đó nhập n số nguyên vào danh sách A. In ra giá trị lớn nhất và "
                "chỉ số đầu tiên của nó trong A (không dùng hàm max).",
                [
                    ("Nhập n và tạo danh sách A đúng", 1.0),
                    ("Duyệt danh sách tìm giá trị lớn nhất và lưu chỉ số", 1.5),
                    ("In kết quả đúng", 0.5),
                ],
                "n = int(input())\nA = [int(input()) for _ in range(n)]\nvt = 0\nfor i in range(1, n):\n"
                "    if A[i] > A[vt]:\n        vt = i\nprint(A[vt], vt)",
            ),
            (
                3,
                "Viết chương trình nhập điểm của cả lớp trên một dòng (các số thực cách nhau bởi dấu cách), tính điểm "
                "trung bình và đếm số bạn có điểm từ 8 trở lên.",
                [
                    ("Nhập và chuyển đúng thành danh sách số thực", 1.0),
                    ("Tính đúng điểm trung bình", 1.0),
                    ("Đếm đúng số điểm ≥ 8", 1.0),
                ],
                "A = [float(x) for x in input().split()]\ntb = sum(A) / len(A)\ndem = 0\nfor x in A:\n    if x >= 8:\n"
                "        dem += 1\nprint(round(tb, 2), dem)",
            ),
            (
                4,
                "Viết chương trình nhập một danh sách các số nguyên, tạo danh sách mới chỉ gồm các phần tử xuất hiện đúng "
                "một lần trong danh sách ban đầu (giữ nguyên thứ tự). Ví dụ: [4, 1, 4, 2, 3, 2] → [1, 3].",
                [
                    ("Nhập danh sách đúng", 1.0),
                    ("Thuật toán chọn đúng các phần tử xuất hiện một lần, giữ thứ tự", 2.0),
                    ("In kết quả và giải thích cách làm", 1.0),
                ],
                "A = [int(x) for x in input().split()]\nB = []\nfor x in A:\n    if A.count(x) == 1:\n        B.append(x)\nprint(B)",
            ),
        ],
    ),
    (
        "Xâu kí tự (string)",
        [
            (
                1,
                "Cho s = 'Tin hoc 10'. Cho biết giá trị của len(s), s[0] và s[-2:].",
                [("len(s) = 10", 0.5), ("s[0] = 'T' và s[-2:] = '10'", 0.5)],
                "len(s) = 10 (kể cả dấu cách); s[0] = 'T'; s[-2:] = '10'.",
            ),
            (
                2,
                "Cho s = 'python'. Cho biết kết quả của các biểu thức: s.upper(), s[1:4], s[::-1] và 'th' in s.",
                [
                    ("s.upper() = 'PYTHON'", 0.5),
                    ("s[1:4] = 'yth'", 0.5),
                    ("s[::-1] = 'nohtyp'", 0.5),
                    ("'th' in s cho kết quả True", 0.5),
                ],
                "'PYTHON'; 'yth'; 'nohtyp'; True.",
            ),
            (
                3,
                "Viết chương trình nhập một xâu bất kì, đếm và in ra số chữ số và số chữ cái có trong xâu.",
                [
                    ("Nhập xâu và duyệt từng kí tự", 1.0),
                    ("Dùng isdigit()/isalpha() (hoặc so sánh kí tự) để đếm đúng", 1.5),
                    ("In kết quả rõ ràng", 0.5),
                ],
                "s = input()\nso = chu = 0\nfor ch in s:\n    if ch.isdigit():\n        so += 1\n    elif ch.isalpha():\n"
                "        chu += 1\nprint('Chữ số:', so, '- Chữ cái:', chu)",
            ),
            (
                3,
                "Viết chương trình nhập một xâu s và một kí tự c. Đếm số lần c xuất hiện trong s (không dùng hàm count) "
                "và in ra vị trí đầu tiên của c trong s (nếu không có thì in -1).",
                [
                    ("Duyệt xâu và đếm đúng số lần xuất hiện", 1.5),
                    ("Tìm đúng vị trí đầu tiên, xử lý trường hợp không có", 1.0),
                    ("In kết quả rõ ràng", 0.5),
                ],
                "s = input()\nc = input()\ndem = 0\nvt = -1\nfor i in range(len(s)):\n    if s[i] == c:\n        dem += 1\n"
                "        if vt == -1:\n            vt = i\nprint(dem, vt)",
            ),
            (
                4,
                "Viết chương trình nhập họ tên và chuẩn hóa: xóa khoảng trắng thừa ở đầu, cuối và giữa các từ; viết hoa "
                "chữ cái đầu mỗi từ, các chữ còn lại viết thường. Ví dụ '  nGUYEN   van  an ' → 'Nguyen Van An'.",
                [
                    ("Xóa đúng khoảng trắng thừa (split/join hoặc duyệt)", 1.5),
                    ("Viết hoa chữ cái đầu, các chữ còn lại viết thường", 1.5),
                    ("Chương trình hoàn chỉnh, giải thích cách làm", 1.0),
                ],
                "s = input()\nkq = ' '.join(w.capitalize() for w in s.split())\nprint(kq)\n"
                "split() không tham số tách theo khoảng trắng và bỏ khoảng trắng thừa; capitalize() viết hoa chữ đầu.",
            ),
        ],
    ),
    (
        "Hàm trong Python",
        [
            (
                1,
                "Nêu cú pháp định nghĩa một hàm trong Python. Lệnh return có tác dụng gì?",
                [
                    ("Viết đúng cú pháp def ten_ham(tham_so): và khối lệnh thụt lề", 0.5),
                    ("Nêu đúng: return trả giá trị về nơi gọi và kết thúc hàm", 0.5),
                ],
                "def ten_ham(tham_so):\n    <các lệnh>\n    return <giá trị>\nreturn kết thúc hàm và trả giá trị về nơi gọi.",
            ),
            (
                2,
                "Cho đoạn chương trình:\ndef f(x, y=2):\n    return x * y + 1\n\nprint(f(3), f(3, 4))\n"
                "Cho biết kết quả in ra và giải thích về tham số y.",
                [("f(3) = 7, giải thích y nhận giá trị mặc định 2", 1.0), ("f(3, 4) = 13", 1.0)],
                "f(3): y mặc định = 2 → 3*2 + 1 = 7; f(3, 4) → 3*4 + 1 = 13. In ra: 7 13",
            ),
            (
                3,
                "Viết hàm ucln(a, b) trả về ước chung lớn nhất của hai số nguyên dương bằng thuật toán Euclid. "
                "Viết chương trình chính nhập a, b rồi in ra ƯCLN và BCNN của chúng.",
                [
                    ("Hàm ucln cài đặt đúng thuật toán Euclid", 1.5),
                    ("Tính BCNN = a * b // ƯCLN", 1.0),
                    ("Chương trình chính nhập dữ liệu, gọi hàm và in kết quả đúng", 0.5),
                ],
                "def ucln(a, b):\n    while b != 0:\n        a, b = b, a % b\n    return a\n\na = int(input())\nb = int(input())\n"
                "u = ucln(a, b)\nprint(u, a * b // u)",
            ),
            (
                3,
                "Viết hàm tong_uoc(n) trả về tổng các ước dương nhỏ hơn n của n. Dùng hàm này kiểm tra số nhập vào có phải "
                "số hoàn hảo không (số bằng tổng các ước nhỏ hơn nó, ví dụ 6 = 1 + 2 + 3).",
                [
                    ("Hàm tính tổng các ước nhỏ hơn n đúng", 1.5),
                    ("Gọi hàm và kết luận số hoàn hảo đúng", 1.0),
                    ("Chương trình rõ ràng, đặt tên hợp lí", 0.5),
                ],
                "def tong_uoc(n):\n    s = 0\n    for i in range(1, n):\n        if n % i == 0:\n            s += i\n    return s\n\n"
                "n = int(input())\nprint('Số hoàn hảo' if tong_uoc(n) == n else 'Không phải số hoàn hảo')",
            ),
            (
                4,
                "Viết hàm la_doi_xung(s) kiểm tra xâu s có phải xâu đối xứng không (bỏ qua dấu cách, không phân biệt chữ "
                "hoa/thường). Dùng hàm này để đếm số xâu đối xứng trong n xâu nhập từ bàn phím.",
                [
                    ("Hàm chuẩn hóa xâu (bỏ dấu cách, chữ thường) và so sánh với xâu đảo đúng", 1.5),
                    ("Chương trình nhập n xâu và đếm bằng cách gọi hàm", 1.5),
                    ("Đặt tên, trình bày rõ ràng; giải thích ngắn gọn", 1.0),
                ],
                "def la_doi_xung(s):\n    t = s.replace(' ', '').lower()\n    return t == t[::-1]\n\nn = int(input())\ndem = 0\n"
                "for _ in range(n):\n    if la_doi_xung(input()):\n        dem += 1\nprint(dem)",
            ),
        ],
    ),
    (
        "Thuật toán tìm kiếm và sắp xếp",
        [
            (
                1,
                "Trình bày ý tưởng của thuật toán tìm kiếm tuần tự (Linear Search) và tìm kiếm nhị phân (Binary Search). "
                "Điều kiện bắt buộc để áp dụng thuật toán tìm kiếm nhị phân là gì?",
                [
                    ("Nêu đúng ý tưởng tìm kiếm tuần tự và tìm kiếm nhị phân", 0.5),
                    ("Nêu đúng điều kiện bắt buộc: danh sách phải được sắp xếp trước", 0.5),
                ],
                "Ý tưởng:\n"
                "- Tìm kiếm tuần tự: Duyệt lần lượt từng phần tử từ đầu đến cuối danh sách, so sánh với khóa cần tìm cho đến khi thấy hoặc hết danh sách.\n"
                "- Tìm kiếm nhị phân: Tại mỗi bước, so sánh khóa với phần tử ở giữa danh sách. Nếu nhỏ hơn thì tìm ở nửa đầu, nếu lớn hơn thì tìm ở nửa sau, mỗi lần chia đôi phạm vi tìm kiếm.\n"
                "Điều kiện bắt buộc: Danh sách dữ liệu phải được sắp xếp theo thứ tự (tăng dần hoặc giảm dần).",
            ),
            (
                2,
                "Cho dãy số đã sắp xếp: A = [5, 11, 18, 24, 32, 45, 60] và cần tìm khóa k = 45.\n"
                "Hãy mô phỏng từng bước của thuật toán tìm kiếm nhị phân: chỉ rõ chỉ số trái (left), phải (right), giữa (mid) và giá trị so sánh ở mỗi lần lặp.",
                [
                    ("Bước 1: xác định đúng left=0, right=6, mid=3 (A[3]=24 < 45) -> chuyển sang nửa sau", 1.0),
                    ("Bước 2: xác định đúng left=4, right=6, mid=5 (A[5]=45 == 45) -> tìm thấy tại vị trí 5", 1.0),
                ],
                "Mô phỏng:\n"
                "- Bước 1: left = 0, right = 6 -> mid = (0 + 6) // 2 = 3. Giá trị A[3] = 24. Vì 24 < 45 nên chuyển sang nửa sau: left = mid + 1 = 4.\n"
                "- Bước 2: left = 4, right = 6 -> mid = (4 + 6) // 2 = 5. Giá trị A[5] = 45. Vì 45 == 45 nên tìm thấy khóa k tại chỉ số 5 (vị trí thứ 6). Dừng thuật toán.",
            ),
            (
                3,
                "Viết hàm Python tim_kiem_nhi_phan(a, x) nhận vào danh sách số nguyên a đã sắp xếp tăng dần và giá trị x cần tìm.\n"
                "Hàm trả về chỉ số đầu tiên của x trong danh sách, nếu không tìm thấy trả về -1.",
                [
                    ("Khởi tạo đúng left, right và vòng lặp while left <= right", 1.0),
                    ("Tính đúng mid, so sánh và cập nhật left, right chính xác", 1.5),
                    ("Trả về mid khi tìm thấy và -1 khi kết thúc vòng lặp", 0.5),
                ],
                "def tim_kiem_nhi_phan(a, x):\n"
                "    left, right = 0, len(a) - 1\n"
                "    while left <= right:\n"
                "        mid = (left + right) // 2\n"
                "        if a[mid] == x:\n"
                "            return mid\n"
                "        elif a[mid] < x:\n"
                "            left = mid + 1\n"
                "        else:\n"
                "            right = mid - 1\n"
                "    return -1",
            ),
            (
                4,
                "Viết chương trình Python thực hiện thuật toán Sắp xếp chọn (Selection Sort) hoặc Sắp xếp nổi bọt (Bubble Sort) "
                "để sắp xếp một dãy số nguyên nhập từ bàn phím theo thứ tự tăng dần.\n"
                "Giải thích cơ chế đổi chỗ và nêu độ phức tạp thời gian của thuật toán trong trường hợp xấu nhất.",
                [
                    ("Viết đúng thuật toán sắp xếp (hai vòng lặp lồng nhau, so sánh và đổi chỗ đúng)", 2.0),
                    ("Nhập xuất dữ liệu chuẩn trong Python", 1.0),
                    ("Giải thích đúng cơ chế đổi chỗ và độ phức tạp O(n^2)", 1.0),
                ],
                "def sap_xep_chon(a):\n"
                "    n = len(a)\n"
                "    for i in range(n - 1):\n"
                "        min_idx = i\n"
                "        for j in range(i + 1, n):\n"
                "            if a[j] < a[min_idx]:\n"
                "                min_idx = j\n"
                "        a[i], a[min_idx] = a[min_idx], a[i]\n"
                "    return a\n\n"
                "a = list(map(int, input().split()))\n"
                "print(*sap_xep_chon(a))\n\n"
                "# Giải thích:\n"
                "# - Cơ chế: Ở mỗi bước i, thuật toán tìm phần tử nhỏ nhất từ chỉ số i đến cuối dãy rồi đổi chỗ với a[i].\n"
                "# - Độ phức tạp: O(n^2) trong trường hợp xấu nhất do có 2 vòng lặp lồng nhau duyệt n*(n-1)/2 lần.",
            ),
        ],
    ),
]

TIN_HOC_11: list[tuple[str, list[tuple[int, str, list[tuple[str, float]], str]]]] = [
    (
        "Hệ điều hành và phần mềm ứng dụng",
        [
            (
                1,
                "Nêu 3 chức năng cơ bản của hệ điều hành. Phân biệt phần mềm nguồn mở và phần mềm thương mại nguồn đóng.",
                [
                    ("Nêu đúng 3 chức năng của hệ điều hành (quản lý phần cứng, quản lý tệp, giao tiếp người dùng)", 0.5),
                    ("Phân biệt đúng phần mềm nguồn mở và phần mềm thương mại nguồn đóng", 0.5),
                ],
                "3 chức năng cơ bản của hệ điều hành: quản lý và điều khiển tài nguyên phần cứng (CPU, RAM, ổ đĩa); "
                "quản lý hệ thống tệp và thư mục; cung cấp giao diện giao tiếp giữa người dùng và máy tính.\n"
                "Phân biệt: Phần mềm nguồn mở (như Linux, LibreOffice) được cung cấp mã nguồn công khai, người dùng có quyền tự do nghiên cứu, sửa đổi và phân phối lại theo giấy phép (như GPL). "
                "Phần mềm thương mại nguồn đóng (như Microsoft Windows, MS Office) không công khai mã nguồn, người dùng phải mua bản quyền và không được sửa đổi mã nguồn.",
            ),
            (
                2,
                "So sánh hệ điều hành cho máy tính cá nhân (như Windows, Linux) và hệ điều hành cho thiết bị di động (như Android, iOS) về giao diện người dùng và cơ chế quản lý năng lượng.",
                [
                    ("So sánh đúng về giao diện: chuột/bàn phím (máy tính) vs màn hình cảm ứng, cử chỉ đa điểm (di động)", 1.0),
                    ("So sánh đúng về quản lý năng lượng: di động tối ưu pin nghiêm ngặt, tự động đóng/ngủ ứng dụng chạy nền; máy tính có nguồn điện dồi dào hơn", 1.0),
                ],
                "So sánh:\n"
                "- Giao diện người dùng: HĐH máy tính thiết kế tối ưu cho chuột, bàn phím và màn hình lớn, hỗ trợ đa cửa sổ linh hoạt. HĐH di động tối ưu cho màn hình cảm ứng, thao tác chạm lướt, cử chỉ đa điểm.\n"
                "- Quản lý năng lượng: HĐH di động ưu tiên cao nhất cho việc tiết kiệm pin, có cơ chế quản lý ứng dụng nền rất nghiêm ngặt (đóng băng/ngừng tiến trình ngầm). HĐH máy tính thường cắm sạc trực tiếp hoặc pin dung lượng lớn nên duy trì nhiều tiến trình nền đầy đủ hơn.",
            ),
            (
                3,
                "Một trường học dự định chuyển đổi toàn bộ máy tính phòng thực hành từ Windows sang hệ điều hành Linux và bộ phần mềm văn phòng LibreOffice.\n"
                "Hãy phân tích 2 ưu điểm lớn và 2 khó khăn/thách thức khi thực hiện quá trình chuyển đổi này.",
                [
                    ("Phân tích 2 ưu điểm: tiết kiệm chi phí bản quyền và an toàn/ít bị nhiễm virus máy tính", 1.5),
                    ("Phân tích 2 khó khăn: thói quen sử dụng của giáo viên/học sinh và tính tương thích định dạng tệp nâng cao", 1.5),
                ],
                "Ưu điểm:\n"
                "1. Tiết kiệm ngân sách lớn do Linux và LibreOffice là phần mềm nguồn mở miễn phí, không tốn tiền mua bản quyền hàng năm.\n"
                "2. An toàn và bảo mật cao, hệ thống ít bị tấn công bởi các loại virus/mã độc phổ biến trên Windows.\n"
                "Thách thức:\n"
                "1. Thói quen sử dụng: Giáo viên và học sinh đã quen giao diện Windows/MS Office nên cần thời gian đào tạo, làm quen lại.\n"
                "2. Tính tương thích tài liệu: Các tệp có định dạng phức tạp (như macro VBA trong Excel, font chữ cũ) có thể bị lệch bố cục khi mở trên LibreOffice.",
            ),
            (
                4,
                "Trình bày giải pháp thiết lập quy trình sao lưu và lưu trữ dữ liệu học tập an toàn trên dịch vụ đám mây (Google Drive / OneDrive) cho học sinh:\n"
                "a) Phân tích 2 nguy cơ mất mát dữ liệu nếu chỉ lưu trên máy tính cá nhân.\n"
                "b) Thiết kế quy trình 3 bước (tổ chức thư mục, cài đặt đồng bộ tự động, chia sẻ và bảo mật tài khoản 2 lớp) để đảm bảo dữ liệu luôn sẵn sàng.",
                [
                    ("Nêu đúng 2 nguy cơ mất dữ liệu: hỏng phần cứng vật lý và bị nhiễm mã độc/ransomware", 1.0),
                    ("Đề xuất cấu trúc thư mục học tập khoa học và cấu hình đồng bộ tự động", 1.5),
                    ("Trình bày đúng nguyên tắc phân quyền chia sẻ và bảo mật 2 lớp (2FA)", 1.5),
                ],
                "a) Nguy cơ khi chỉ lưu trên máy:\n"
                "- Hỏng phần cứng vật lý (cháy nổ, hỏng ổ cứng, rơi vỡ máy tính).\n"
                "- Bị mã độc (ransomware) mã hóa dữ liệu đòi tiền chuộc hoặc vô tình xóa nhầm.\n"
                "b) Quy trình 3 bước sao lưu an toàn:\n"
                "1. Tổ chức thư mục: Tạo cây thư mục chuẩn theo năm học và môn học (VD: /2026-2027/TinHoc11/BaiTap).\n"
                "2. Đồng bộ tự động: Cài phần mềm Google Drive for Desktop hoặc OneDrive để tự động đồng bộ thư mục bài tập lên đám mây theo thời gian thực.\n"
                "3. Phân quyền và bảo mật: Bật xác thực 2 bước (2FA) cho tài khoản đám mây; khi chia sẻ bài tập chỉ cấp quyền 'Người xem' (Viewer) thay vì 'Người chỉnh sửa' (Editor) để tránh bị sửa đè.",
            ),
        ],
    ),
    (
        "Cơ sở dữ liệu và Hệ quản trị CSDL",
        [
            (
                1,
                "Khái niệm Cơ sở dữ liệu (CSDL) là gì? Nêu sự khác nhau cơ bản giữa Cơ sở dữ liệu và Hệ quản trị cơ sở dữ liệu (DBMS).",
                [
                    ("Nêu đúng khái niệm CSDL: tập hợp dữ liệu có liên quan, lưu trữ có cấu trúc trên thiết bị nhớ", 0.5),
                    ("Phân biệt đúng CSDL (dữ liệu lưu trữ) và Hệ quản trị CSDL (phần mềm quản lý, thao tác dữ liệu)", 0.5),
                ],
                "Cơ sở dữ liệu (CSDL) là một tập hợp các dữ liệu có liên quan với nhau, được tổ chức và lưu trữ một cách có cấu trúc trên các thiết bị nhớ của máy tính nhằm phục vụ nhu cầu khai thác thông tin của nhiều người dùng.\n"
                "Sự khác nhau: CSDL là bản thân dữ liệu được lưu trữ; còn Hệ quản trị CSDL (DBMS - như MySQL, PostgreSQL, SQLite, MS Access) là phần mềm cung cấp môi trường để tạo lập, lưu trữ, cập nhật và tìm kiếm dữ liệu trên CSDL đó.",
            ),
            (
                2,
                "Phân tích 3 ưu điểm vượt trội của việc lưu trữ dữ liệu bằng Hệ quản trị CSDL so với việc lưu trữ bằng các bảng tính Excel rời rạc trong bài toán quản lý học sinh nhà trường.",
                [
                    ("Phân tích giảm thiểu dư thừa dữ liệu và đảm bảo tính nhất quán", 1.0),
                    ("Phân tích khả năng truy cập đồng thời của nhiều giáo viên và phân quyền bảo mật", 1.0),
                ],
                "3 ưu điểm vượt trội:\n"
                "1. Tránh dư thừa dữ liệu và đảm bảo tính nhất quán: Trong Excel, thông tin học sinh có thể bị nhập trùng lặp nhiều lần ở các sheet khác nhau dẫn đến không đồng nhất khi sửa đổi. CSDL quan hệ chuẩn hóa dữ liệu, sửa một nơi thì mọi nơi liên kết đều cập nhật đúng.\n"
                "2. Hỗ trợ nhiều người truy cập đồng thời: Hệ quản trị CSDL cho phép hàng chục giáo viên cùng nhập điểm, xem thông tin tại cùng một thời điểm mà không bị khóa file hay ghi đè lỗi như file Excel chia sẻ thông thường.\n"
                "3. An toàn, bảo mật và phân quyền chi tiết: CSDL cho phép phân quyền chặt chẽ (giáo viên bộ môn chỉ sửa điểm môn mình, học sinh chỉ xem điểm của mình) và có cơ chế sao lưu tự động khôi phục giao dịch khi mất điện.",
            ),
            (
                3,
                "Để xây dựng một hệ thống quản lý mượn/trả sách cho thư viện trường học:\n"
                "a) Hãy xác định 3 thực thể (bảng) cơ bản nhất cần quản lý.\n"
                "b) Với mỗi thực thể, hãy liệt kê ít nhất 4 thuộc tính (trường) tương ứng và chỉ rõ kiểu dữ liệu dự kiến.",
                [
                    ("Xác định đúng 3 thực thể hợp lý (Độc giả/Học sinh, Sách, Phiếu mượn)", 1.0),
                    ("Liệt kê đủ ít nhất 4 thuộc tính cho mỗi bảng kèm kiểu dữ liệu phù hợp", 2.0),
                ],
                "a) 3 thực thể cơ bản:\n"
                "1. Bảng DOC_GIA (Độc giả)\n"
                "2. Bảng SACH (Sách trong thư viện)\n"
                "3. Bảng PHIEU_MUON (Quản lý việc mượn trả)\n\n"
                "b) Các thuộc tính và kiểu dữ liệu:\n"
                "1. DOC_GIA:\n"
                "- MaDocGia (Xâu kí tự / VARCHAR - Mã thẻ độc giả)\n"
                "- HoTen (Xâu kí tự / VARCHAR - Tên học sinh)\n"
                "- Lop (Xâu kí tự / VARCHAR - Lớp học)\n"
                "- NgaySinh (Ngày tháng / DATE)\n"
                "2. SACH:\n"
                "- MaSach (Xâu kí tự / VARCHAR - Mã sách)\n"
                "- TenSach (Xâu kí tự / VARCHAR - Tên sách)\n"
                "- TacGia (Xâu kí tự / VARCHAR - Tác giả)\n"
                "- NamXuatBan (Số nguyên / INT)\n"
                "3. PHIEU_MUON:\n"
                "- MaPhieu (Xâu kí tự / VARCHAR - Mã phiếu)\n"
                "- MaDocGia (Xâu kí tự / VARCHAR - Mã độc giả mượn)\n"
                "- MaSach (Xâu kí tự / VARCHAR - Mã sách mượn)\n"
                "- NgayMuon (Ngày tháng / DATE)\n"
                "- NgayTra (Ngày tháng / DATE)",
            ),
            (
                4,
                "Cho lược đồ một bảng lưu trữ gộp chung:\n"
                "KET_QUA_HOC_TAP (MaHS, HoTen, Lop, GVCN, MaMon, TenMon, DiemHK1, DiemHK2)\n"
                "a) Hãy chỉ ra những hiện tượng bất thường (dư thừa, bất thường khi sửa, bất thường khi xóa) có thể xảy ra với bảng trên.\n"
                "b) Đề xuất cách tách bảng trên thành 3 bảng riêng biệt có liên kết để khắc phục triệt để các bất thường này.",
                [
                    ("Phân tích chính xác bất thường dư thừa (GVCN lặp lại), sửa đổi và xóa dữ liệu", 2.0),
                    ("Đề xuất mô hình 3 bảng chuẩn (HOC_SINH, MON_HOC, BANG_DIEM) kèm khóa chính, khóa ngoại", 2.0),
                ],
                "a) Các bất thường của bảng gộp chung:\n"
                "- Dư thừa dữ liệu: Tên học sinh, tên giáo viên chủ nhiệm (GVCN) bị lặp lại ở mọi môn học của em đó.\n"
                "- Bất thường khi sửa (Update Anomaly): Khi lớp thay đổi GVCN, phải cập nhật hàng chục dòng cho tất cả các môn của tất cả học sinh trong lớp; nếu sót một dòng sẽ dẫn đến mâu thuẫn thông tin.\n"
                "- Bất thường khi xóa (Delete Anomaly): Nếu một học sinh tạm nghỉ và xóa điểm của em, thông tin về môn học mới tạo (nếu chỉ có em đó đăng ký) cũng có nguy cơ bị xóa mất.\n\n"
                "b) Đề xuất tách thành 3 bảng chuẩn hóa:\n"
                "1. HOC_SINH (MaHS [PK], HoTen, Lop, GVCN)\n"
                "2. MON_HOC (MaMon [PK], TenMon)\n"
                "3. BANG_DIEM (MaHS [FK], MaMon [FK], DiemHK1, DiemHK2) với Khóa chính là cặp (MaHS, MaMon).",
            ),
        ],
    ),
    (
        "Khóa chính và Khóa ngoại trong CSDL quan hệ",
        [
            (
                1,
                "Khóa chính (Primary Key) là gì? Nêu 2 điều kiện bắt buộc của một thuộc tính khi được chọn làm khóa chính.",
                [
                    ("Nêu đúng định nghĩa khóa chính: tập thuộc tính nhận diện duy nhất mỗi bản ghi trong bảng", 0.5),
                    ("Nêu đúng 2 điều kiện: giá trị phải duy nhất (không trùng lặp) và không được mang giá trị rỗng (NOT NULL)", 0.5),
                ],
                "Khóa chính (Primary Key) là một hoặc một tập hợp thuộc tính dùng để phân biệt và xác định duy nhất mỗi bản ghi (dòng) trong một bảng quan hệ.\n"
                "2 điều kiện bắt buộc của khóa chính:\n"
                "1. Tính duy nhất (Unique): Không bao giờ có hai dòng dữ liệu có cùng giá trị khóa chính.\n"
                "2. Tính không rỗng (NOT NULL): Khóa chính không bao giờ được phép mang giá trị NULL (rỗng), đảm bảo tính toàn vẹn thực thể.",
            ),
            (
                2,
                "Cho hai bảng sau:\n"
                "- LOP (MaLop, TenLop, GVCN)\n"
                "- HOC_SINH (MaHS, HoTen, NgaySinh, MaLop)\n"
                "a) Xác định khóa chính của từng bảng.\n"
                "b) Chỉ ra khóa ngoại và giải thích ràng buộc toàn vẹn tham chiếu giữa hai bảng.",
                [
                    ("Xác định đúng khóa chính: MaLop của bảng LOP và MaHS của bảng HOC_SINH", 1.0),
                    ("Chỉ ra đúng khóa ngoại MaLop ở HOC_SINH tham chiếu tới LOP(MaLop) và nêu ý nghĩa ràng buộc", 1.0),
                ],
                "a) Khóa chính:\n"
                "- Bảng LOP: Khóa chính là MaLop.\n"
                "- Bảng HOC_SINH: Khóa chính là MaHS.\n"
                "b) Khóa ngoại & ràng buộc tham chiếu:\n"
                "- Khóa ngoại: Trường MaLop trong bảng HOC_SINH là khóa ngoại tham chiếu đến khóa chính MaLop của bảng LOP.\n"
                "- Ràng buộc toàn vẹn tham chiếu: Mọi giá trị MaLop xuất hiện trong bảng HOC_SINH bắt buộc phải tồn tại từ trước trong bảng LOP (không thể gán học sinh vào một lớp chưa từng tồn tại).",
            ),
            (
                3,
                "Xét hệ thống mượn sách thư viện gồm bảng DOC_GIA(MaThe, TenDG, Lop) và MUON_SACH(MaMuon, MaThe, MaSach, NgayMuon).\n"
                "a) Khóa chính và khóa ngoại của bảng MUON_SACH là gì?\n"
                "b) Nếu thủ thư muốn xóa một bạn đọc khỏi bảng DOC_GIA trong khi bạn đọc này vẫn đang có sách mượn chưa trả trong bảng MUON_SACH, hệ thống CSDL quan hệ sẽ xử lý như thế nào? Vì sao?",
                [
                    ("Xác định đúng MaMuon là PK, MaThe là FK tham chiếu DOC_GIA(MaThe)", 1.5),
                    ("Giải thích đúng: CSDL sẽ từ chối thao tác xóa (lỗi vi phạm ràng buộc khóa ngoại) để bảo vệ tính toàn vẹn tham chiếu", 1.5),
                ],
                "a) Bảng MUON_SACH:\n"
                "- Khóa chính (PK): MaMuon (hoặc cặp MaThe, MaSach, NgayMuon nếu không có mã mượn riêng).\n"
                "- Khóa ngoại (FK): MaThe tham chiếu đến bảng DOC_GIA(MaThe).\n"
                "b) Cách CSDL xử lý khi xóa:\n"
                "Hệ thống sẽ từ chối thao tác xóa và phát sinh lỗi vi phạm ràng buộc toàn vẹn tham chiếu (Foreign Key Constraint Violation).\n"
                "Lý do: Nếu cho phép xóa độc giả, các bản ghi trong bảng MUON_SACH sẽ trỏ đến một mã độc giả không còn tồn tại (bản ghi 'mồ côi'), khiến thư viện không thể biết ai đang giữ sách.",
            ),
            (
                4,
                "Hãy thiết kế lược đồ CSDL cho hệ thống 'Đăng ký câu lạc bộ ngoại khóa' trong trường THPT:\n"
                "- Mỗi học sinh có thể đăng ký tham gia nhiều câu lạc bộ (CLB).\n"
                "- Mỗi câu lạc bộ có nhiều học sinh tham gia.\n"
                "Yêu cầu:\n"
                "1. Giải thích vì sao không thể liên kết trực tiếp bảng HOC_SINH và CAU_LAC_BO bằng một khóa ngoại đơn thuần (quan hệ nhiều - nhiều).\n"
                "2. Xây dựng bảng trung gian DANG_KY, xác định rõ các trường, khóa chính (khóa phức hợp) và 2 khóa ngoại.",
                [
                    ("Giải thích chính xác tính chất quan hệ nhiều - nhiều (N-N) không thể biểu diễn trực tiếp bằng 1 khóa ngoại", 1.5),
                    ("Thiết kế hoàn chỉnh 3 bảng (HOC_SINH, CAU_LAC_BO, DANG_KY)", 1.5),
                    ("Xác định chính xác khóa phức hợp (MaHS, MaCLB) và 2 khóa ngoại tham chiếu", 1.0),
                ],
                "1. Giải thích:\n"
                "Đây là mối quan hệ nhiều - nhiều (N-N). Một học sinh tham gia nhiều CLB nên không thể đặt MaCLB vào bảng HOC_SINH (sẽ vi phạm tính nguyên tử của thuộc tính hoặc lặp bản ghi). Tương tự không thể đặt MaHS vào bảng CAU_LAC_BO. Do đó bắt buộc phải dùng bảng trung gian để chuyển quan hệ nhiều-nhiều thành 2 quan hệ một-nhiều (1-N).\n\n"
                "2. Thiết kế lược đồ:\n"
                "- Bảng 1: HOC_SINH(MaHS [PK], HoTen, NgaySinh, Lop)\n"
                "- Bảng 2: CAU_LAC_BO(MaCLB [PK], TenCLB, ChuNhiemCLB, PhongHoatDong)\n"
                "- Bảng 3: DANG_KY(MaHS [FK], MaCLB [FK], NgayThamGia, VaiTro)\n"
                "  * Khóa chính của bảng DANG_KY là cặp khóa phức hợp: (MaHS, MaCLB).\n"
                "  * MaHS là khóa ngoại tham chiếu đến HOC_SINH(MaHS).\n"
                "  * MaCLB là khóa ngoại tham chiếu đến CAU_LAC_BO(MaCLB).",
            ),
        ],
    ),
    (
        "Truy vấn dữ liệu cơ bản với SQL (SELECT, WHERE, ORDER BY)",
        [
            (
                1,
                "Viết câu lệnh SQL lấy ra tất cả thông tin (tất cả các cột và các dòng) từ bảng HOC_SINH.",
                [
                    ("Viết đúng cú pháp SELECT * FROM HOC_SINH", 1.0),
                ],
                "SELECT * FROM HOC_SINH;",
            ),
            (
                2,
                "Cho bảng SAN_PHAM có các cột: MaSP, TenSP, DonGia, SoLuong.\n"
                "Viết câu lệnh SQL để hiển thị TenSP và DonGia của các sản phẩm có DonGia lớn hơn hoặc bằng 50000, kết quả sắp xếp giảm dần theo DonGia.",
                [
                    ("Chọn đúng các cột TenSP, DonGia từ bảng SAN_PHAM", 0.5),
                    ("Viết đúng điều kiện WHERE DonGia >= 50000", 1.0),
                    ("Viết đúng mệnh đề ORDER BY DonGia DESC", 0.5),
                ],
                "SELECT TenSP, DonGia\n"
                "FROM SAN_PHAM\n"
                "WHERE DonGia >= 50000\n"
                "ORDER BY DonGia DESC;",
            ),
            (
                3,
                "Cho bảng KET_QUA có các cột: MaHS, MaMon, Diem (số thực từ 0 đến 10).\n"
                "Hãy viết 2 câu lệnh SQL riêng biệt:\n"
                "a) Tính điểm trung bình của môn học có MaMon = 'TIN11' (đặt tên cột kết quả là DiemTB).\n"
                "b) Đếm số lượng học sinh có điểm thi môn 'TIN11' đạt từ 8.0 trở lên (đặt tên cột là SoLuongGioi).",
                [
                    ("Câu a: Dùng đúng hàm AVG(Diem) kèm alias DiemTB và điều kiện WHERE MaMon = 'TIN11'", 1.5),
                    ("Câu b: Dùng đúng COUNT(*) kèm điều kiện kết hợp AND MaMon = 'TIN11' AND Diem >= 8.0", 1.5),
                ],
                "a) Câu lệnh tính điểm trung bình:\n"
                "SELECT AVG(Diem) AS DiemTB\n"
                "FROM KET_QUA\n"
                "WHERE MaMon = 'TIN11';\n\n"
                "b) Câu lệnh đếm số học sinh đạt từ 8.0 trở lên:\n"
                "SELECT COUNT(*) AS SoLuongGioi\n"
                "FROM KET_QUA\n"
                "WHERE MaMon = 'TIN11' AND Diem >= 8.0;",
            ),
            (
                4,
                "Cho bảng HOC_SINH có các trường: MaHS, HoTen, Lop, DiemRenLuyen, KhuVuc.\n"
                "Viết câu lệnh SQL thống kê:\n"
                "- Đếm tổng số học sinh của từng Lớp.\n"
                "- Tính điểm rèn luyện trung bình của từng Lớp.\n"
                "- Chỉ lấy những lớp có sĩ số từ 30 học sinh trở lên và sắp xếp điểm rèn luyện trung bình giảm dần.\n"
                "Giải thích sự khác nhau giữa mệnh đề WHERE và HAVING trong câu lệnh của bạn.",
                [
                    ("Viết đúng SELECT Lop, COUNT(MaHS), AVG(DiemRenLuyen) và GROUP BY Lop", 1.5),
                    ("Viết đúng mệnh đề lọc nhóm HAVING COUNT(MaHS) >= 30 và ORDER BY", 1.5),
                    ("Giải thích phân biệt WHERE (lọc từng dòng trước khi gộp nhóm) và HAVING (lọc nhóm sau khi GROUP BY)", 1.0),
                ],
                "Câu lệnh SQL:\n"
                "SELECT Lop, COUNT(MaHS) AS SiSo, AVG(DiemRenLuyen) AS DTRenLuyenTB\n"
                "FROM HOC_SINH\n"
                "GROUP BY Lop\n"
                "HAVING COUNT(MaHS) >= 30\n"
                "ORDER BY DTRenLuyenTB DESC;\n\n"
                "Phân biệt WHERE và HAVING:\n"
                "- WHERE được dùng để lọc từng bản ghi riêng lẻ trước khi thực hiện phép gom nhóm GROUP BY (không thể dùng với các hàm gộp như COUNT, AVG).\n"
                "- HAVING được dùng để lọc trên kết quả của việc gom nhóm sau khi đã thực hiện GROUP BY (áp dụng điều kiện trực tiếp trên các hàm gộp).",
            ),
        ],
    ),
    (
        "Liên kết bảng (JOIN) và Cập nhật dữ liệu trong SQL",
        [
            (
                1,
                "Viết câu lệnh SQL thêm một học sinh mới vào bảng HOC_SINH(MaHS, HoTen, Lop, NgaySinh) với thông tin:\n"
                "- MaHS: 'HS1105'\n"
                "- HoTen: 'Trần Minh Quân'\n"
                "- Lop: '11A2'\n"
                "- NgaySinh: '2009-10-15'",
                [
                    ("Cú pháp INSERT INTO HOC_SINH (...) VALUES (...) đúng", 0.5),
                    ("Các giá trị chuỗi và ngày nằm trong cặp dấu nháy đơn đúng quy định", 0.5),
                ],
                "INSERT INTO HOC_SINH (MaHS, HoTen, Lop, NgaySinh)\n"
                "VALUES ('HS1105', 'Trần Minh Quân', '11A2', '2009-10-15');",
            ),
            (
                2,
                "Cho bảng HOC_SINH(MaHS, HoTen, DiemTB, XepLoai).\n"
                "a) Viết câu lệnh SQL cập nhật XepLoai thành 'Xuất sắc' cho tất cả học sinh có DiemTB >= 9.0.\n"
                "b) Điều gì sẽ xảy ra nếu người lập trình quên viết mệnh đề WHERE trong câu lệnh trên?",
                [
                    ("Viết đúng câu lệnh UPDATE HOC_SINH SET XepLoai = 'Xuất sắc' WHERE DiemTB >= 9.0", 1.0),
                    ("Nêu chính xác rủi ro: toàn bộ tất cả bản ghi trong bảng đều bị cập nhật thành 'Xuất sắc'", 1.0),
                ],
                "a) Câu lệnh SQL cập nhật:\n"
                "UPDATE HOC_SINH\n"
                "SET XepLoai = 'Xuất sắc'\n"
                "WHERE DiemTB >= 9.0;\n\n"
                "b) Hậu quả khi quên WHERE:\n"
                "Nếu không có mệnh đề WHERE, câu lệnh UPDATE sẽ sửa đổi toàn bộ dữ liệu của tất cả học sinh trong bảng thành 'Xuất sắc' (kể cả học sinh trung bình hoặc yếu), gây sai lệch dữ liệu nghiêm trọng.",
            ),
            (
                3,
                "Cho hai bảng trong CSDL Quản lý trường học:\n"
                "- LOP(MaLop, TenLop, PhongHoc)\n"
                "- HOC_SINH(MaHS, HoTen, GioiTinh, MaLop)\n"
                "Viết câu lệnh SQL sử dụng phép kết nối INNER JOIN để hiển thị danh sách gồm: MaHS, HoTen, TenLop, PhongHoc của tất cả học sinh nữ (GioiTinh = 'Nữ').",
                [
                    ("Chọn đúng các cột cần hiển thị có tiền tố bảng rõ ràng", 1.0),
                    ("Dùng đúng cú pháp FROM HOC_SINH INNER JOIN LOP ON HOC_SINH.MaLop = LOP.MaLop", 1.0),
                    ("Viết đúng điều kiện lọc WHERE GioiTinh = 'Nữ'", 1.0),
                ],
                "SELECT HOC_SINH.MaHS, HOC_SINH.HoTen, LOP.TenLop, LOP.PhongHoc\n"
                "FROM HOC_SINH\n"
                "INNER JOIN LOP ON HOC_SINH.MaLop = LOP.MaLop\n"
                "WHERE HOC_SINH.GioiTinh = 'Nữ';",
            ),
            (
                4,
                "Cho CSDL Quản lý bán hàng gồm hai bảng:\n"
                "- KHACH_HANG(MaKH, HoTen, DienThoai)\n"
                "- DON_HANG(MaDH, MaKH, NgayDat, TongTien)\n"
                "a) Viết câu lệnh SQL lấy ra HoTen của khách hàng và Tổng giá trị tiền mua sắm của họ (tổng TongTien), chỉ hiển thị những khách hàng có tổng tiền mua sắm trên 10,000,000 VNĐ.\n"
                "b) Viết câu lệnh SQL xóa những đơn hàng có NgayDat trước ngày '2025-01-01' và TongTien = 0.",
                [
                    ("Câu a: Kết nối 2 bảng qua MaKH, GROUP BY HoTen/MaKH, SUM(TongTien) và HAVING > 10000000", 2.5),
                    ("Câu b: Viết đúng DELETE FROM DON_HANG WHERE NgayDat < '2025-01-01' AND TongTien = 0", 1.5),
                ],
                "a) Câu lệnh thống kê khách hàng mua sắm trên 10 triệu:\n"
                "SELECT KHACH_HANG.HoTen, SUM(DON_HANG.TongTien) AS TongChiTieu\n"
                "FROM KHACH_HANG\n"
                "INNER JOIN DON_HANG ON KHACH_HANG.MaKH = DON_HANG.MaKH\n"
                "GROUP BY KHACH_HANG.MaKH, KHACH_HANG.HoTen\n"
                "HAVING SUM(DON_HANG.TongTien) > 10000000;\n\n"
                "b) Câu lệnh xóa đơn hàng không hợp lệ cũ:\n"
                "DELETE FROM DON_HANG\n"
                "WHERE NgayDat < '2025-01-01' AND TongTien = 0;",
            ),
        ],
    ),
    (
        "Bảo mật và an toàn hệ cơ sở dữ liệu",
        [
            (
                1,
                "Nêu 3 nguyên tắc hoặc biện pháp kỹ thuật cơ bản để đảm bảo an toàn và bảo mật cho hệ cơ sở dữ liệu.",
                [
                    ("Nêu đúng nguyên tắc kiểm soát truy cập và xác thực tài khoản", 0.5),
                    ("Nêu đúng nguyên tắc sao lưu định kỳ và mã hóa dữ liệu", 0.5),
                ],
                "3 biện pháp kỹ thuật cơ bản:\n"
                "1. Xác thực và phân quyền người dùng: Bắt buộc đăng nhập bằng mật khẩu mạnh, phân quyền tối thiểu (chỉ cấp đúng quyền cần thiết để thực hiện công việc).\n"
                "2. Sao lưu dữ liệu định kỳ (Backup): Thường xuyên tạo bản sao dự phòng của CSDL và lưu trữ ở vị trí độc lập để có thể khôi phục khi gặp sự cố.\n"
                "3. Mã hóa dữ liệu: Mã hóa các trường dữ liệu nhạy cảm (như mật khẩu, thông tin cá nhân) khi lưu trữ và mã hóa kênh truyền (sử dụng SSL/TLS).",
            ),
            (
                2,
                "Phân biệt hai khái niệm 'Xác thực người dùng' (Authentication) và 'Phân quyền truy cập' (Authorization) trong bảo mật CSDL. Cho ví dụ cụ thể trong hệ thống quản lý học sinh.",
                [
                    ("Phân biệt đúng khái niệm Xác thực (xác minh danh tính: ai?) và Phân quyền (quyền hạn được làm gì?)", 1.0),
                    ("Lấy ví dụ chính xác về vai trò của Giáo viên bộ môn vs Học sinh trong trường", 1.0),
                ],
                "Phân biệt:\n"
                "- Xác thực (Authentication): Là quá trình xác minh danh tính của người dùng xem họ có đúng là người mà họ tuyên bố hay không (trả lời câu hỏi: Bạn là ai?). Thường thực hiện qua tên đăng nhập, mật khẩu, mã OTP.\n"
                "- Phân quyền (Authorization): Là quá trình xác định người dùng đã đăng nhập có quyền thực hiện những thao tác gì trên dữ liệu (trả lời câu hỏi: Bạn được phép làm gì?).\n\n"
                "Ví dụ trong quản lý học sinh:\n"
                "- Cả thầy An (giáo viên Tin) và em Hoa (học sinh) đều phải đăng nhập xác thực thành công.\n"
                "- Tuy nhiên về phân quyền: Thầy An có quyền xem và sửa điểm môn Tin học của các lớp thầy dạy; em Hoa chỉ có quyền đọc (xem) điểm của bản thân và hoàn toàn không có quyền sửa đổi điểm.",
            ),
            (
                3,
                "Một trường học có hệ thống CSDL phục vụ 2.000 học sinh. Hãy thiết kế chiến lược sao lưu (Backup) và phục hồi (Restore) dữ liệu cho nhà trường:\n"
                "a) Phân biệt sao lưu toàn bộ (Full Backup) và sao lưu gia tăng (Incremental Backup).\n"
                "b) Đề xuất lịch sao lưu cụ thể trong tuần và quy trình thử nghiệm phục hồi định kỳ.",
                [
                    ("Phân biệt chính xác Full Backup (sao lưu toàn bộ CSDL) và Incremental Backup (chỉ sao lưu phần thay đổi kể từ lần sao lưu trước)", 1.5),
                    ("Đề xuất lịch sao lưu khoa học (Full vào cuối tuần, Incremental mỗi ngày) và quy trình kiểm thử phục hồi", 1.5),
                ],
                "a) Phân biệt:\n"
                "- Full Backup: Sao chép toàn bộ tất cả dữ liệu có trong CSDL tại thời điểm sao lưu. Ưu điểm: khôi phục nhanh nhất; nhược điểm: tốn nhiều dung lượng và thời gian thực hiện.\n"
                "- Incremental Backup: Chỉ sao chép những dữ liệu mới được thêm hoặc sửa đổi kể từ lần sao lưu gần nhất. Ưu điểm: diễn ra rất nhanh, tiết kiệm dung lượng lưu trữ; nhược điểm: khi khôi phục phải kết hợp bản Full cùng toàn bộ các bản gia tăng theo trình tự.\n\n"
                "b) Đề xuất lịch sao lưu:\n"
                "- 00:00 Chủ nhật hàng tuần: Thực hiện Full Backup.\n"
                "- 23:00 từ Thứ 2 đến Thứ 7: Thực hiện Incremental Backup.\n"
                "- Lưu trữ bản sao lưu: Tự động tải lên một dịch vụ đám mây riêng biệt và một ổ cứng ngoài đặt tại phòng văn thư.\n"
                "- Thử nghiệm phục hồi: Mỗi quý 1 lần, quản trị viên diễn tập nạp bản sao lưu lên máy chủ kiểm thử để đảm bảo tệp sao lưu không bị lỗi hỏng.",
            ),
            (
                4,
                "Tấn công chèn mã SQL (SQL Injection - SQLi) là gì?\n"
                "a) Cho đoạn mã đăng nhập ghép chuỗi trực tiếp:\n"
                "   query = \"SELECT * FROM NguoiDung WHERE TaiKhoan = '\" + user_input + \"' AND MatKhau = '\" + pass_input + \"'\"\n"
                "   Nếu kẻ tấn công nhập ô TaiKhoan là: admin' -- thì điều gì sẽ xảy ra? Vì sao?\n"
                "b) Nêu giải pháp chuẩn trong lập trình ứng dụng để phòng chống triệt để lỗ hổng SQL Injection.",
                [
                    ("Giải thích đúng khái niệm SQL Injection và phân tích cơ chế kẻ tấn công vượt qua đăng nhập bằng admin' --", 2.0),
                    ("Trình bày giải pháp chuẩn: sử dụng câu lệnh tham số hóa (Parameterized Query / Prepared Statements) hoặc ORM", 2.0),
                ],
                "a) Khái niệm và phân tích:\n"
                "- SQL Injection là kỹ thuật tấn công chèn các đoạn mã lệnh SQL độc hại vào các ô nhập liệu của người dùng nhằm thay đổi cấu trúc truy vấn ban đầu và truy cập trái phép dữ liệu.\n"
                "- Khi người dùng nhập: admin' --, câu truy vấn trở thành:\n"
                "   SELECT * FROM NguoiDung WHERE TaiKhoan = 'admin' --' AND MatKhau = '...'\n"
                "   Ký hiệu -- trong SQL đánh dấu chú thích (comment), bỏ qua toàn bộ phần kiểm tra mật khẩu phía sau. Hệ thống sẽ trả về bản ghi của tài khoản 'admin' và kẻ tấn công đăng nhập thành công quyền quản trị mà không cần mật khẩu.\n\n"
                "b) Biện pháp phòng chống triệt để:\n"
                "1. Sử dụng Parameterized Queries (Truy vấn tham số hóa) hoặc Prepared Statements: Hệ quản trị CSDL sẽ coi toàn bộ nội dung người dùng nhập vào là giá trị dữ liệu thuần túy (literal value), không bao giờ biên dịch thành lệnh SQL.\n"
                "2. Sử dụng thư viện ORM (như SQLAlchemy, Hibernate): Các thư viện này tự động tham số hóa mọi câu lệnh.\n"
                "3. Kiểm tra tính hợp lệ của đầu vào (Input Validation) và áp dụng nguyên tắc đặc quyền tối thiểu cho tài khoản kết nối CSDL.",
            ),
        ],
    ),
]

# (họ tên, năng lực gốc, ghi chú) – năng lực theo thang Elo; tên giả định
STUDENTS: list[tuple[str, float, str]] = [
    ("Nguyễn Minh Anh", 1.9, "Học sinh giỏi, tiếp thu nhanh, thích bài thử thách"),
    ("Trần Gia Bảo", 0.6, ""),
    ("Lê Hoàng Châu", 0.1, ""),
    ("Phạm Đức Duy", 1.1, ""),
    ("Võ Thanh Hà", 0.9, ""),
    ("Đặng Quốc Huy", -0.5, "Hay quên nộp bài"),
    ("Bùi Ngọc Khánh", 0.4, ""),
    ("Huỳnh Bảo Ngọc", 1.4, ""),
    ("Đỗ Thành Phát", -0.9, "Cần kèm thêm phần lập trình"),
    ("Ngô Thảo Vy", 0.7, ""),
]


def create_sample_subject(db: Session, teacher: Teacher, grade: int = 10) -> Subject:
    if grade == 11:
        name = "Tin học 11"
        desc = "Định hướng CSDL & SQL và Hệ thống máy tính (GDPT 2018). Dữ liệu mẫu."
        data = TIN_HOC_11
    else:
        name = "Tin học 10 (Khoa học máy tính)"
        desc = "Định hướng Khoa học máy tính (CS) – Lập trình Python và Thuật toán (GDPT 2018). Dữ liệu mẫu."
        data = TIN_HOC_10
    subject = Subject(
        teacher_id=teacher.id,
        name=name,
        description=desc,
    )
    db.add(subject)
    db.flush()
    for position, (topic_name, questions) in enumerate(data):
        topic = Topic(subject_id=subject.id, name=topic_name, position=position)
        db.add(topic)
        db.flush()
        for level, content, rubric, answer in questions:
            db.add(
                Question(
                    subject_id=subject.id,
                    topic_id=topic.id,
                    content=content,
                    level=level,
                    max_score=MAX_BY_LEVEL[level],
                    rubric=[{"criterion": c, "points": p} for c, p in rubric],
                    reference_answer=answer,
                    source="bank",
                    status="active",
                )
            )
    db.flush()
    db.refresh(subject)
    return subject


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def render_handwriting(lines: list[str]) -> bytes:
    """Ảnh mô phỏng trang giấy làm bài (dùng cho dữ liệu mẫu)."""
    width, height = 1240, 1600
    img = Image.new("RGB", (width, height), "#fdfdf8")
    draw = ImageDraw.Draw(img)
    for y in range(140, height, 52):
        draw.line([(60, y), (width - 60, y)], fill="#c5d5ea", width=2)
    draw.line([(130, 0), (130, height)], fill="#f2b8b8", width=2)
    font = ImageFont.load_default(size=34)
    rng = random.Random(len("".join(lines)))
    y = 102
    for line in lines:
        x = 150 + rng.randint(-4, 4)
        draw.text((x, y + rng.randint(-3, 3)), strip_accents(line), fill="#1f3a93", font=font)
        y += 52
        if y > height - 60:
            break
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def seed_sample_data(
    db: Session, teacher: Teacher, settings: Settings, ai: AIProvider | None = None, grade: int = 10
) -> Classroom:
    """Tạo môn Tin học (10 hoặc 11) + lớp mẫu có lịch sử 3 tuần + 1 đợt giao bài đang mở."""
    rng = random.Random(2026 + (111 if grade == 11 else 0))
    subject = create_sample_subject(db, teacher, grade=grade)
    classroom = Classroom(
        teacher_id=teacher.id, subject_id=subject.id, name=f"{grade}A1 (lớp mẫu)", school_year="2026-2027"
    )
    db.add(classroom)
    db.flush()

    abilities: dict[int, float] = {}
    offsets: dict[tuple[int, int], float] = {}
    for name, ability, note in STUDENTS:
        student = add_student(db, classroom, name, note=note)
        abilities[student.id] = ability
        for topic in subject.topics:
            offsets[(student.id, topic.id)] = rng.uniform(-0.9, 0.9)
    db.refresh(classroom)
    by_name = {s.full_name: s for s in classroom.students}
    duy = by_name["Phạm Đức Duy"]
    skip_last_week = {by_name["Đặng Quốc Huy"].id, by_name["Đỗ Thành Phát"].id}

    now = utcnow()
    # Bài khảo sát đầu năm chấm theo từng chủ đề (như khi giáo viên nhập bảng điểm có cột chủ đề)
    for student in classroom.students:
        for topic in subject.topics:
            frac = _sigmoid(abilities[student.id] + offsets[(student.id, topic.id)] + rng.gauss(0, 0.4))
            db.add(
                ScoreRecord(
                    student_id=student.id,
                    topic_id=topic.id,
                    label="Khảo sát đầu năm",
                    score=round(frac * 20) / 2,
                    max_score=10,
                    source="import",
                    recorded_at=now - timedelta(days=28),
                )
            )
    db.flush()

    for week, days_ago in enumerate((21, 14, 7), start=1):
        created = now - timedelta(days=days_ago)
        result = create_batch(
            db,
            classroom,
            title=f"Luyện tập tuần {week}",
            due_at=created + timedelta(days=3),
            num_questions=4,
            mode="auto",
            generate_missing=False,
        )
        batch = result.batch
        batch.created_at = created
        for assignment in batch.assignments:
            if not assignment.items:
                continue
            approve_assignment(db, assignment)
            assignment.created_at = assignment.assigned_at = assignment.sent_at = created
            if week == 3 and assignment.student_id in skip_last_week:
                continue  # không nộp -> cảnh báo quá hạn
            ability = abilities[assignment.student_id]
            if assignment.student_id == duy.id and week >= 2:
                ability -= 2.2  # mô phỏng học sinh tụt điểm
            submitted = created + timedelta(days=2, hours=rng.randint(1, 20))
            sub = Submission(
                student_id=assignment.student_id,
                assignment_id=assignment.id,
                status=SubmissionStatus.CONFIRMED,
                created_at=submitted,
                submitted_at=submitted,
                graded_at=submitted + timedelta(minutes=1),
                confirmed_at=submitted + timedelta(hours=10),
                result_sent_at=submitted + timedelta(hours=10),
            )
            total = max_total = 0.0
            for pos, item in enumerate(assignment.items, start=1):
                q = item.question
                theta = ability + offsets[(assignment.student_id, q.topic_id)]
                frac = _sigmoid(theta - difficulty_of(q.level) + rng.gauss(0, 0.6))
                criteria = [
                    {
                        "criterion": r["criterion"],
                        "max_points": r["points"],
                        "awarded": round_quarter(r["points"] * frac),
                        "comment": "",
                    }
                    for r in q.rubric
                ]
                score = sum(c["awarded"] for c in criteria)
                sub.grades.append(
                    ItemGrade(
                        assignment_item_id=item.id,
                        question_id=q.id,
                        position=pos,
                        max_score=q.max_score,
                        transcription="(dữ liệu mẫu)",
                        ai_score=score,
                        final_score=score,
                        ai_comment="Làm tốt!" if frac > 0.8 else "Cần xem lại các bước làm.",
                        criteria=criteria,
                        confidence=0.9,
                    )
                )
                total += score
                max_total += q.max_score
            sub.ai_total = sub.final_total = total
            sub.max_total = max_total
            db.add(sub)
            assignment.status = AssignmentStatus.GRADED
            db.flush()  # để tuần sau tính mức nắm vững từ kết quả tuần này

    # Đợt giao bài đang mở + một bài nộp mẫu có ảnh chờ AI chấm
    current = create_batch(
        db,
        classroom,
        title="Luyện tập tuần 4",
        due_at=now + timedelta(days=2),
        num_questions=4,
        mode="auto",
        generate_missing=False,
    ).batch
    for assignment in current.assignments:
        if assignment.items:
            approve_assignment(db, assignment)
    sample = next(a for a in current.assignments if a.student.full_name == "Nguyễn Minh Anh")
    lines: list[str] = []
    for pos, item in enumerate(sample.items, start=1):
        lines.append(f"Cau {pos}:")
        answer_lines = [ln for ln in item.question.reference_answer.split("\n") if ln.strip()]
        lines += answer_lines[: 6 if pos < len(sample.items) else 2]  # câu cuối làm dở
        lines.append("")
    sub = Submission(
        student_id=sample.student_id,
        assignment_id=sample.id,
        status=SubmissionStatus.SUBMITTED,
        submitted_at=now - timedelta(minutes=30),
        max_total=sample.max_total,
    )
    db.add(sub)
    db.flush()
    rel_path, mime = save_submission_file(settings, sub.id, 1, render_handwriting(lines), "image/jpeg")
    sub.images.append(SubmissionImage(file_path=rel_path, mime_type=mime, position=1))
    sample.status = AssignmentStatus.SUBMITTED
    db.flush()
    return classroom
