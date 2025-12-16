#!/usr/bin/env python3
"""
잘못 중첩된 서식 태그 처리 테스트
"""

from Browser import HTMLParser, Text, Element

def print_tree(node, indent=0):
    """트리 구조를 시각적으로 출력"""
    prefix = "  " * indent
    if isinstance(node, Text):
        text = node.text.strip()
        if text:
            print(f"{prefix}[TEXT] \"{text}\"")
    else:
        print(f"{prefix}<{node.tag}>")
        for child in node.children:
            print_tree(child, indent + 1)

def test_nested_formatting():
    print("=" * 70)
    print("잘못 중첩된 서식 태그 처리 테스트")
    print("=" * 70)
    
    test_cases = [
        {
            "name": "기본 중첩 오류",
            "html": "<b>bold <i>both</b> italic</i>",
            "expected": "<b>bold <i>both</i></b><i> italic</i>"
        },
        {
            "name": "여러 태그 중첩",
            "html": "<b>one <i>two <small>three</b> four</small> five</i>",
            "expected": "<b>one <i>two <small>three</small></i></b><i><small> four</small> five</i>"
        },
        {
            "name": "단순 케이스",
            "html": "<b><i>both</i></b>",
            "expected": "<b><i>both</i></b>"
        },
        {
            "name": "역순 닫기",
            "html": "<b><i>text</b></i>",
            "expected": "<b><i>text</i></b><i></i>"
        },
    ]
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n테스트 {i}: {test['name']}")
        print("-" * 70)
        print(f"입력:    {test['html']}")
        print(f"기대값:  {test['expected']}")
        print()
        
        try:
            tree = HTMLParser(test['html']).parse()
            print("파싱 결과 트리:")
            print_tree(tree)
            
            # 트리를 HTML로 다시 변환
            result_html = tree_to_html(tree)
            print(f"\n출력:    {result_html}")
            
        except Exception as e:
            print(f"❌ 오류: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 70)
    print("✅ 테스트 완료!")

def tree_to_html(node):
    """트리를 HTML 문자열로 변환 (디버깅용)"""
    if isinstance(node, Text):
        return node.text
    
    result = []
    # html, head, body 태그는 스킵
    if node.tag not in ['html', 'head', 'body']:
        result.append(f"<{node.tag}>")
    
    for child in node.children:
        result.append(tree_to_html(child))
    
    if node.tag not in ['html', 'head', 'body']:
        result.append(f"</{node.tag}>")
    
    return ''.join(result)

if __name__ == "__main__":
    test_nested_formatting()
