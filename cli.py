#!/usr/bin/env python3

import sys
import os
from pathlib import Path
from URL import URL
from Browser import HTMLParser, Text

def render_text(body: str) -> str:
    """Convert an HTML/text body into a plain text representation.

    This reuses the module's `HTMLParser` and `Text`/`Element` structure to
    preserve basic semantics like paragraphs and line breaks without
    instantiating the GUI `Browser` class.
    """
    try:
        tree = HTMLParser(body).parse()
    except Exception:
        # fall back to raw body if parsing fails
        return body

    tokens = []

    def walk(node):
        # Text nodes: append their text
        if isinstance(node, Text):
            tokens.append(node.text)
            return
        # Element nodes: handle a few common tags
        tag = getattr(node, 'tag', '').lower()
        if tag == 'br':
            tokens.append('\n')
            return
        if tag == 'p':
            # collect paragraph children then add a paragraph break
            for child in node.children:
                walk(child)
            tokens.append('\n\n')
            return
        # default: recurse into children
        for child in node.children:
            walk(child)

    walk(tree)

    # Join tokens preserving explicit newlines, avoid duplicate spaces
    out = ''
    for tok in tokens:
        if tok == '\n' or tok == '\n\n':
            out += tok
        else:
            # normalize whitespace inside token
            piece = ' '.join(tok.split())
            if not out or out.endswith('\n'):
                out += piece
            else:
                out += ' ' + piece

    return out.strip()

def load(url):
    body = url.request()
    # If this is a view-source URL, print the raw source directly
    if getattr(url, 'scheme', None) == 'view-source':
        print(body)
    else:
        print(render_text(body))


def main():
    # 명령줄 인자로 URL을 받음
    # 예: python cli.py http://example.org/ http://example.com/
    if len(sys.argv) > 1:
        # data: URI 처리 (공백으로 분리된 경우)
        if any(arg.startswith('data:') for arg in sys.argv[1:]):
            uri = ' '.join(sys.argv[1:])
            load(URL(uri))
        else:
            # 여러 URL을 순차적으로 처리
            for i, raw in enumerate(sys.argv[1:], 1):
                print(f"\n{'='*60}")
                print(f"🌎 요청 #{i}: {raw}")
                print('='*60)
                
                # 파일 경로면 file:// URI로 변환
                if "://" not in raw and os.path.exists(raw):
                    uri = Path(raw).resolve().as_uri()
                else:
                    uri = raw
                
                try:
                    load(URL(uri))
                except Exception as e:
                    print(f"\n❌ 오류 발생: {e}")
                
                print("\n")  # 구분선
    else:
        # 대화형 모드: 계속 URL을 입력받음
        print("🌐 대화형 모드 - Keep-Alive 테스트")
        print("도움말: 동일 서버에 여러 요청을 보내면 소켓 재사용을 확인할 수 있습니다.")
        print("종료하려면 'quit' 또는 'exit'를 입력하거나 Ctrl+C를 누르세요.\n")
        
        request_count = 0
        while True:
            try:
                uri = input(f"URL [{request_count+1}]: ").strip()
                
                if not uri:
                    continue
                
                if uri.lower() in ['quit', 'exit', 'q']:
                    print("\n👋 종료합니다.")
                    break
                
                request_count += 1
                print(f"\n{'='*60}")
                print(f"🌎 요청 #{request_count}: {uri}")
                print('='*60)
                
                # 파일 경로면 file:// URI로 변환
                if "://" not in uri and os.path.exists(uri):
                    uri = Path(uri).resolve().as_uri()
                
                try:
                    load(URL(uri))
                except Exception as e:
                    print(f"\n❌ 오류 발생: {e}")
                
                print("\n")  # 구분선
                
            except KeyboardInterrupt:
                print("\n\n👋 종료합니다.")
                break
            except EOFError:
                print("\n\n👋 종료합니다.")
                break


if __name__ == "__main__":
    main()
