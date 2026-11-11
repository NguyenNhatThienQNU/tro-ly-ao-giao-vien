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


def create_sample_subject(db: Session, teacher: Teacher) -> Subject:
    subject = Subject(
        teacher_id=teacher.id,
        name="Tin học 10",
        description="Chủ đề F – Giải quyết vấn đề với sự trợ giúp của máy tính (lập trình Python). Dữ liệu mẫu.",
    )
    db.add(subject)
    db.flush()
    for position, (topic_name, questions) in enumerate(TIN_HOC_10):
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


def seed_sample_data(db: Session, teacher: Teacher, settings: Settings, ai: AIProvider | None = None) -> Classroom:
    """Tạo môn Tin học 10 + lớp mẫu có lịch sử 3 tuần + 1 đợt giao bài đang mở."""
    rng = random.Random(2026)
    subject = create_sample_subject(db, teacher)
    classroom = Classroom(teacher_id=teacher.id, subject_id=subject.id, name="10A1 (lớp mẫu)", school_year="2026-2027")
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
