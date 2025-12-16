#!/usr/bin/env python3
"""
JavaScript 파싱 테스트 스크립트
Browser.py의 HTMLParser가 <script> 태그를 올바르게 처리하는지 확인
"""

from Browser import HTMLParser, Text, Element

def print_tree(node, indent=0):
    """트리 구조를 시각적으로 출력"""
    prefix = "  " * indent
    if isinstance(node, Text):
        # 텍스트 노드는 공백 제거 후 출력
        text = " ".join(node.text.split())
        if text:
            print(f"{prefix}[TEXT] {text[:50]}...")
    else:
        # 요소 노드
        print(f"{prefix}<{node.tag}>")
        for child in node.children:
            print_tree(child, indent + 1)

def test_script_parsing():
    """여러 케이스를 테스트"""
    
    print("=" * 60)
    print("Test 1: Simple script with < operator")
    print("=" * 60)
    html1 = """
    <html>
        <body>
            <p>Before</p>
            <script>
                if (x < 10) {
                    console.log("test");
                }
            </script>
            <p>After</p>
        </body>
    </html>
    """
    tree1 = HTMLParser(html1).parse()
    print_tree(tree1)
    print()
    
    print("=" * 60)
    print("Test 2: Script with HTML-like strings")
    print("=" * 60)
    html2 = """
    <html>
        <body>
            <p>Real paragraph</p>
            <script>
                var html = "<div>Fake div</div>";
                var tag = "<p>Fake paragraph</p>";
            </script>
            <div>Real div</div>
        </body>
    </html>
    """
    tree2 = HTMLParser(html2).parse()
    print_tree(tree2)
    print()
    
    print("=" * 60)
    print("Test 3: Multiple scripts")
    print("=" * 60)
    html3 = """
    <html>
        <body>
            <h1>Title</h1>
            <script>var a = 1 < 2;</script>
            <p>Middle</p>
            <script>var b = 3 > 2;</script>
            <p>End</p>
        </body>
    </html>
    """
    tree3 = HTMLParser(html3).parse()
    print_tree(tree3)
    print()
    
    print("=" * 60)
    print("Test 4: From test_script.html file")
    print("=" * 60)
    with open("test_script.html", "r", encoding="utf-8") as f:
        html4 = f.read()
    tree4 = HTMLParser(html4).parse()
    print_tree(tree4)
    print()
    
    print("=" * 60)
    print("✅ All tests completed!")
    print("=" * 60)
    print()
    print("💡 주요 확인 사항:")
    print("  1. <script> 태그 안의 < 와 > 가 HTML 태그로 인식되지 않았는가?")
    print("  2. <script> 안의 '<div>' 같은 문자열이 실제 태그로 파싱되지 않았는가?")
    print("  3. <script> 태그 이후의 실제 HTML이 정상적으로 파싱되었는가?")

if __name__ == "__main__":
    test_script_parsing()
