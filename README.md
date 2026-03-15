# finding-hidden-bugs

## Workflow luyện tập (judge scripts)

Cấu trúc chính:

- `problems/<id>/` chứa `buggy.cpp`, `sol.cpp`, `gentest.cpp`
- `problems/<id>/tests/` là nơi **generate test** (`*.in`) và **output chuẩn** (`*.out`)
- `workspace/<id>.cpp` là file bạn sửa (copy từ `buggy.cpp`)
- `state/round.json` lưu trạng thái round hiện tại
- `history/*.json` lưu lịch sử sau khi hoàn thành round

### 1) Start round

Chạy:

- `./judge/start.sh` (random 3–5 bài)
- hoặc `./judge/start.sh --count 3 --tests 20`

Dọn dẹp để làm round mới (nếu cần chạy tay):

- `./judge/clean.sh`

Script sẽ:

- random 3–5 problem
- gen tests + expected outputs trong `problems/<id>/tests/`
- copy `buggy.cpp` vào `workspace/<id>.cpp`
- tạo `state/round.json`

### 2) Mở bài hiện tại

- `./judge/open.sh`

Mở bài bất kỳ trong round (không cần theo thứ tự):

- `./judge/open.sh p01`

### 3) Nộp bài (chấm 10/0)

- `./judge/submit.sh`

Nộp bài bất kỳ trong round (không cần theo thứ tự):

- `./judge/submit.sh p01`

Logic: compile `workspace/<id>.cpp`, chạy tất cả `tests/*.in`, so output với `tests/*.out`.
Đúng tất cả test = +10, sai bất kỳ test nào = 0 và đánh dấu `failed`.

Note: output khi chạy test được lưu trong `state/run/<id>/` để workspace gọn.

### 4) Chuyển bài tiếp theo

- `./judge/next.sh`

## Cách thêm bài

Để thêm bài mới, tạo folder `problems/pXX/` với:

- `statement.txt`: file mô tả đề bài
- `buggy.cpp`: code có bug
- `sol.cpp`: code đúng
- `gentest.cpp`: code gen test (xuất input ra stdout)
  Sau đó chạy `./judge/gentest.sh pXX` để gen test và output chuẩn.

## Cách sửa file `gentest.cpp`

File `gentest.cpp` là code gen test, bạn có thể sửa để tạo ra các test case khác nhau. Lấy template ở `./template/gentest.cpp` và sửa phần nhập input ở đoạn sau:

```cpp
for (int t = 1; t <= numTests; ++t) {
    const string path = testsDir + "/" + two(t) + ".in";
    ofstream fout(path, ios::binary);
    if (!fout) {
        cerr << "Cannot write: " << path << "\n";
        return 3;
    }

    // Your code here
}
```

Ở code trên, input chỉ có 1 số n, bạn chỉ cần sửa phần nhập input cho phù hợp với đề bài.

Một số hàm cần dùng trong file `gentest.cpp`:

- `rd(l, r)`: sinh một số kiểu `int` ngẫu nhiên trong khoảng [l, r]
- `rdll(l, r)`: sinh một số kiểu `long long` ngẫu nhiên trong khoảng [l, r]

Xem mẫu ở `./problems/p01/` để hiểu rõ hơn.
