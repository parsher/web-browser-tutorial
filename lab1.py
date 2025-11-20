import socket
import ssl
import gzip
import zlib
import brotli
import os
import base64
from urllib.parse import urlparse, unquote, unquote_to_bytes
from pathlib import Path


class URL:
    """URL을 파싱하고 관리하는 클래스"""
    
    def __init__(self, url):
        # 더 안정적인 파싱을 위해 urllib.parse 사용
        parsed = urlparse(url)
        self.scheme = parsed.scheme

        if self.scheme in ["http", "https"]:
            # host와 path 분리
            self.host = parsed.netloc
            self.path = parsed.path or "/"
            # 포트번호 설정 (http는 80, https는 443)
            if self.scheme == "http":
                self.port = 80
            elif self.scheme == "https":
                self.port = 443
        elif self.scheme == "file":
            # file URL: file:///C:/path or file:///home/user/file
            # parsed.netloc는 보통 빈 문자열 또는 'localhost'
            # unquote하지 않으면 os가 실제 경로를 찾지를 못함
            raw_path = unquote(parsed.path)
            # Windows 드라이브 표기 처리: '/C:/path' -> 'C:/path'
            if os.name == 'nt' and raw_path.startswith("/") and len(raw_path) > 2 and raw_path[2] == ':' :
                raw_path = raw_path.lstrip('/')
            # 로컬 파일 경로 저장
            self.filepath = raw_path
        elif self.scheme == "data":
            # data:[<mediatype>][;base64],<data>
            # parsed.path may contain the whole data part; use the original URL
            data_part = url.split(":", 1)[1]
            try:
                meta, data = data_part.split(",", 1)
            except ValueError:
                raise ValueError("Invalid data URI: missing comma separator")
            meta_parts = meta.split(";") if meta else []
            mediatype = meta_parts[0] if meta_parts and meta_parts[0] else "text/plain"
            is_base64 = "base64" in meta_parts
            # extract charset if present
            charset = None
            for part in meta_parts:
                if part.startswith("charset="):
                    charset = part.split("=", 1)[1]
                    break
            # decode data
            if is_base64:
                try:
                    data_bytes = base64.b64decode(data)
                except Exception as e:
                    raise ValueError(f"Invalid base64 data in data URI: {e}")
            else:
                # percent-decoded bytes
                data_bytes = unquote_to_bytes(data)
            # store for request()
            self.data_bytes = data_bytes
            self.data_mediatype = mediatype
            self.data_charset = charset
        elif self.scheme == "view-source":
            # view-source:<inner-uri> -> store inner URL object to fetch its source
            # extract the remainder after the first ':' (preserve // for http/https)
            inner_uri = url[len('view-source:'):]
            # allow whitespace tolerance
            inner_uri = inner_uri.strip()
            # create URL object for inner resource
            self.inner = URL(inner_uri)
        else:
            raise AssertionError(f"Unknown scheme {self.scheme}")
    
    def request(self):
        """서버에 HTTP 요청을 보내고 응답을 받는 함수"""
        # view-source인 경우 내부 URL의 본문을 가져와 그대로 반환
        if getattr(self, 'scheme', None) == 'view-source':
            # view-source:example.com의 inner는 example.com임 따라서 반드시 있어야함
            if not hasattr(self, 'inner'):
                raise ValueError('view-source missing inner URL')
            return self.inner.request()
        # data 스킴이면 URI에 포함된 데이터를 반환
        if getattr(self, 'scheme', None) == 'data':
            # Determine charset to decode bytes to text
            charset = self.data_charset or ("utf-8" if self.data_mediatype.startswith("text/") else "utf-8")
            try:
                return self.data_bytes.decode(charset, errors='replace')
            except Exception:
                return self.data_bytes.decode('utf-8', errors='replace')

        # file 스킴이면 로컬 파일을 읽어서 내용을 반환
        if getattr(self, 'scheme', None) == 'file':
            # 파일이 존재하는지 확인
            if not os.path.exists(self.filepath):
                raise FileNotFoundError(f"File not found: {self.filepath}")
            with open(self.filepath, 'rb') as f:
                data = f.read()
                # '�� invalid utf8 �' 이처럼 변환이 됨, U+FFFD
            return data.decode('utf8', errors='replace')
        
        # 1. 소켓 생성 - 서버와의 연결 통로
        s = socket.socket(
            family=socket.AF_INET,      # IPv4 사용
            type=socket.SOCK_STREAM,    # TCP 연결
            proto=socket.IPPROTO_TCP,   # TCP 프로토콜
        )
        
        # 2. 서버에 연결
        s.connect((self.host, self.port))
        
        # 3. HTTPS인 경우 TLS로 암호화
        if self.scheme == "https":
            ctx = ssl.create_default_context()
            s = ctx.wrap_socket(s, server_hostname=self.host)
        
        # 4. HTTP 요청 메시지 작성
        # GET 메서드로 특정 경로의 리소스를 요청
        request = "GET {} HTTP/1.0\r\n".format(self.path)
        request += "Host: {}\r\n".format(self.host)
        # 압축 지원을 서버에 알림
        request += "Accept-Encoding: gzip, deflate, br\r\n"
        request += "\r\n"  # 헤더의 끝을 표시
        
        # 5. 요청 전송 (문자열을 바이트로 변환)
        s.send(request.encode("utf8"))
        
        # 6. 응답 받기 (바이너리로 읽어야 압축 해제 가능)
        response = s.makefile("rb")
        
        # 7. 상태 라인 읽기 (예: "HTTP/1.0 200 OK")
        statusline = response.readline().decode("utf8")
        version, status, explanation = statusline.split(" ", 2)
        
        # 8. 응답 헤더 읽기 (빈 줄이 나올 때까지)
        response_headers = {}
        while True:
            line = response.readline().decode("utf8")
            if line == "\r\n": break  # 헤더의 끝
            header, value = line.split(":", 1)
            # casefold()는 lower()보다 더 공격적인 대소문자 정규화
            # 국제화된 문자도 올바르게 처리
            response_headers[header.casefold()] = value.strip()
        
        # 9. Transfer-Encoding 체크 (여전히 지원하지 않음)
        assert "transfer-encoding" not in response_headers, \
            "Transfer-Encoding not supported (chunked transfer)"
        
        # 10. HTTP 상태 확인
        assert status == "200", "{}: {}".format(status, explanation)
        
        # 11. 본문(body) 읽기 - 바이너리로 읽음
        body = response.read()
        s.close()
        
        # 12. Content-Encoding에 따라 압축 해제
        encoding = response_headers.get("content-encoding", "").lower()
        
        if encoding == "gzip":
            print("🗜️  gzip 압축 해제 중...")
            body = gzip.decompress(body)
        elif encoding == "deflate":
            print("🗜️  deflate 압축 해제 중...")
            try:
                # deflate는 두 가지 형식이 있음 (zlib 헤더 있음/없음)
                body = zlib.decompress(body)
            except zlib.error:
                # zlib 헤더가 없는 경우 raw deflate 시도
                body = zlib.decompress(body, -zlib.MAX_WBITS)
        elif encoding == "br":
                body = brotli.decompress(body)
        elif encoding:
            # 알 수 없는 인코딩
            raise Exception(f"Unsupported content-encoding: {encoding}")
        else:
            print("📄 압축 없음")
        
        # 13. 바이트를 문자열로 변환
        body = body.decode("utf8", errors="replace")
        
        return body


def show(body):
    """HTML에서 텍스트만 추출하여 출력하는 함수"""
    
    in_tag = False  # 현재 태그 안에 있는지 추적
    entity = ""  # HTML 엔티티를 저장할 변수
    
    for c in body:
        if c == "<":
            in_tag = True  # 태그 시작
        elif c == ">":
            in_tag = False  # 태그 끝
        elif not in_tag:
            # HTML 엔티티 처리
            if c == "&":
                entity = "&"
            elif entity:
                entity += c
                if c == ";":
                    # 엔티티 치환
                    if entity == "&lt;":
                        print("<", end="")
                    elif entity == "&gt;":
                        print(">", end="")
                    elif entity == "&nbsp;":
                        print(" ", end="")
                    elif entity == "&amp;":
                        print("&", end="")
                    elif entity == "&quot;":
                        print('"', end="")
                    else:
                        # 알 수 없는 엔티티는 그대로 출력
                        print(entity, end="")
                    entity = ""
            else:
                print(c, end="")  # 태그 밖의 문자만 출력


def load(url):
    """URL을 받아서 웹 페이지를 다운로드하고 표시하는 메인 함수"""
    body = url.request()
    # If this is a view-source URL, print the raw source directly
    if getattr(url, 'scheme', None) == 'view-source':
        print(body)
    else:
        show(body)


if __name__ == "__main__":
    import sys
    
    # 명령줄 인자로 URL을 받음
    # 예: python lab1.py http://example.org/
    if len(sys.argv) > 1:
        # Reconstruct URI for cases where shells (PowerShell) split data: URIs
        # across multiple argv elements (commas, spaces). If any argument
        # starts with 'data:', join all argv[1:] with spaces to rebuild it.
        if any(arg.startswith('data:') for arg in sys.argv[1:]):
            uri = ' '.join(sys.argv[1:])
        else:
            raw = sys.argv[1]
            # If user passed a plain filesystem path (no scheme) and it exists,
            # convert it to a file:// URI so URL() can handle it.
            if "://" not in raw and os.path.exists(raw):
                uri = Path(raw).resolve().as_uri()
            else:
                uri = raw
        load(URL(uri))
    else:
        # 기본 테스트 URL
        load(URL("https://www.naver.com/"))
