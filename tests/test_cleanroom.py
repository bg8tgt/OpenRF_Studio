"""干净室守卫：源码/文档不得出现第三方程序名、逆向/反编译或授权文件痕迹。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TOKENS = ["Smith" + "Chart", "逆" + "向", "反" + "编译", "Dev" + "Components",
          "license" + "-KEY", "f15" + "bc", "orac" + "le", "sm" + "ith4.1"]
EXTS = {".py", ".md", ".txt", ".cmd"}
SKIP_DIRS = {"dist", "build", "__pycache__", ".git", "images"}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 审计报告本身需要描述"检查了什么"，允许它提及被禁止的类别名
ALLOW = {"docs/合规与来源审核.md", "NOTICE-合规说明.md", "交付说明.txt"}


def hits() -> list:
    out = []
    self_path = os.path.abspath(__file__)
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith("_")]
        for name in files:
            p = os.path.join(base, name)
            if os.path.abspath(p) == self_path:
                continue
            if os.path.relpath(p, ROOT).replace("\\", "/") in ALLOW:
                continue
            if os.path.splitext(name)[1].lower() not in EXTS:
                continue
            try:
                text = open(p, encoding="utf-8").read()
            except Exception:
                continue
            for tok in TOKENS:
                if tok in text:
                    out.append(f"{os.path.relpath(p, ROOT)}:{tok}")
    return out


def main() -> int:
    found = hits()
    print("== 干净室审计")
    if found:
        for h in found:
            print("  [FAIL]", h)
        print(f"失败 {len(found)} 处")
        return 1
    print("  [OK]   未发现第三方程序名 / 逆向痕迹 / 授权文件引用")
    print("干净室审计通过 ✔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())