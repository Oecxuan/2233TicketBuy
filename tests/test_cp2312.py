"""
cp2312 算法测试脚本
用于验证 cp2312 token 生成算法的正确性（对齐 BHYG v1.13.1 OSS）
"""

import sys
import base64
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.cp2312 import Cp2312Generator, create_generator, get_ctoken, get_token


def test_generate_ctoken_default():
    print("=" * 60)
    print("测试 generate_ctoken（默认参数）")
    print("=" * 60)
    g = Cp2312Generator()
    ctoken = g.generate_ctoken()
    print(f"ctoken: {ctoken[:40]}...")
    print(f"长度: {len(ctoken)}")
    try:
        decoded = base64.b64decode(ctoken)
        print(f"Base64 解码成功: {len(decoded)} 字节")
        assert len(decoded) == 32, f"期望 32 字节, 实际 {len(decoded)}"
        print("  结构验证: 32 字节 OK")
    except Exception as e:
        print(f"失败: {e}")
        return False
    return True


def test_generate_ctoken_deterministic():
    print()
    print("=" * 60)
    print("测试 generate_ctoken 确定性")
    print("=" * 60)
    g1 = Cp2312Generator()
    g2 = Cp2312Generator()
    args = dict(m1=100,m2=200,m3=50,m4=150,m5=75,m6=125,m7=25,m8=175,m9=225,
                touchend=40,visibilitychange=30,beforeunload=20,timer=5)
    c1 = g1.generate_ctoken(**args)
    c2 = g2.generate_ctoken(**args)
    print(f"ctoken1: {c1[:40]}...")
    print(f"ctoken2: {c2[:40]}...")
    assert c1 == c2, "确定性失败!"
    print("  确定性验证: 相同输入 -> 相同输出 OK")
    return True


def test_generate_ctoken_random():
    print()
    print("=" * 60)
    print("测试 generate_ctoken 随机性")
    print("=" * 60)
    c1 = Cp2312Generator().generate_ctoken()
    c2 = Cp2312Generator().generate_ctoken()
    print(f"ctoken1: {c1[:40]}...")
    print(f"ctoken2: {c2[:40]}...")
    if c1 != c2:
        print("  随机性验证: 默认参数产生不同值 OK")
        return True
    else:
        print("  (偶然相同，再试一次)")
        c3 = Cp2312Generator().generate_ctoken()
        return c1 != c3


def test_m_function():
    print()
    print("=" * 60)
    print("测试 _m 函数")
    print("=" * 60)
    g = Cp2312Generator()
    env = g._get_env_data()
    assert len(env) == 16
    print(f"env_data 长度: {len(env)} OK")
    for t in range(256):
        val = g._m(t, env)
        assert 0 <= val <= 255
    print("_m(t) in [0,255] for t=0..255 OK")
    return True


def test_get_ctoken():
    print()
    print("=" * 60)
    print("测试 get_ctoken")
    print("=" * 60)
    ctoken = get_ctoken(1001701, 1009287, 889997, 1)
    print(f"ctoken: {ctoken[:40]}... len={len(ctoken)}")
    decoded = base64.b64decode(ctoken)
    assert len(decoded) == 32
    print("get_ctoken OK")
    return True


def test_get_token():
    print()
    print("=" * 60)
    print("测试 get_token")
    print("=" * 60)
    token = get_token(1001701, 1009287, 889997, 1)
    print(f"token: {token[:40]}... len={len(token)}")
    decoded = base64.b64decode(token)
    assert len(decoded) == 32
    print("get_token OK")
    return True


def test_create_generator():
    print()
    print("=" * 60)
    print("测试 create_generator")
    print("=" * 60)
    g = create_generator()
    assert isinstance(g, Cp2312Generator)
    decoded = base64.b64decode(g.generate_ctoken())
    assert len(decoded) == 32
    print("create_generator OK")
    return True


def run_all_tests():
    tests = [
        ("generate_ctoken (默认)", test_generate_ctoken_default),
        ("generate_ctoken (确定性)", test_generate_ctoken_deterministic),
        ("generate_ctoken (随机性)", test_generate_ctoken_random),
        ("_m 函数", test_m_function),
        ("get_ctoken", test_get_ctoken),
        ("get_token", test_get_token),
        ("create_generator", test_create_generator),
    ]
    results = []
    for name, fn in tests:
        try:
            passed = fn()
            results.append((name, passed))
        except Exception as e:
            print(f"  测试 {name} 异常: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    print()
    print("=" * 60)
    print("结果汇总")
    print("=" * 60)
    all_ok = True
    for name, ok in results:
        print(f"  {name}: {'OK' if ok else 'FAIL'}")
        if not ok:
            all_ok = False
    print(f"\n总体: {'全部通过' if all_ok else '存在失败'}")
    return all_ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if run_all_tests() else 1)
