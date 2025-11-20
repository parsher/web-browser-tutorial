import socket
import ssl
import gzip
import zlib
import brotli
import os
from urllib.parse import urlparse, unquote
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
        else:
            raise AssertionError(f"Unknown scheme {self.scheme}")
    
    def request(self):
        """서버에 HTTP 요청을 보내고 응답을 받는 함수"""
        # file 스킴이면 로컬 파일을 읽어서 내용을 반환
        if getattr(self, 'scheme', None) == 'file':
            # 파일이 존재하는지 확인
            if not os.path.exists(self.filepath):
                raise FileNotFoundError(f"File not found: {self.filepath}")
            with open(self.filepath, 'rb') as f:
                data = f.read()
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
    
    for c in body:
        if c == "<":
            in_tag = True  # 태그 시작
        elif c == ">":
            in_tag = False  # 태그 끝
        elif not in_tag:
            print(c, end="")  # 태그 밖의 문자만 출력


def load(url):
    """URL을 받아서 웹 페이지를 다운로드하고 표시하는 메인 함수"""
    body = url.request()
    show(body)


if __name__ == "__main__":
    import sys
    
    # 명령줄 인자로 URL을 받음
    # 예: python lab1.py http://example.org/
    if len(sys.argv) > 1:
        raw = sys.argv[1]
        # If user passed a plain filesystem path (no scheme) and it exists,
        # convert it to a file:// URI so URL() can handle it.
        if "://" not in raw:
            if not os.path.exists(raw):
                raise FileNotFoundError(f"File not found: {raw}")
            uri = Path(raw).resolve().as_uri()
        else:
            uri = raw
        load(URL(uri))
    else:
        # 기본 테스트 URL
        load(URL("https://www.naver.com/"))
