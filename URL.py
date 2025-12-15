import socket
import ssl
import gzip
import zlib
import brotli
import os
import base64
import time
from urllib.parse import urlparse, unquote, unquote_to_bytes, urljoin
from pathlib import Path
import atexit


class URL:
    """URL을 파싱하고 관리하는 클래스"""
    
    # 클래스 변수: 소켓 캐시 (host:port를 키로 사용)
    _socket_cache = {}
    
    # 클래스 변수: 콘텐츠 캐시 {url: {body, headers, timestamp, max_age}}
    _content_cache = {}
    
    # 캐시 가능한 파일 확장자
    _CACHEABLE_EXTENSIONS = {
        '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico',  # 이미지
        '.css',  # 스타일
        '.js', '.mjs',  # 스크립트
        '.woff', '.woff2', '.ttf', '.eot',  # 폰트
    }
    
    @staticmethod
    def _is_cacheable(url_path):
        """캐시 가능한 리소스인지 확인"""
        ext = os.path.splitext(url_path.lower())[1]
        return ext in URL._CACHEABLE_EXTENSIONS
    
    @staticmethod
    def _parse_cache_control(cache_control_header):
        """
        Cache-Control 헤더 파싱
        리턴: (no_store: bool, max_age: int or None)
        """
        if not cache_control_header:
            return False, None
        
        directives = [d.strip().lower() for d in cache_control_header.split(',')]
        no_store = False
        max_age = None
        
        for directive in directives:
            if directive == 'no-store':
                no_store = True
            elif directive.startswith('max-age='):
                try:
                    max_age = int(directive.split('=')[1])
                except (ValueError, IndexError):
                    pass
        
        return no_store, max_age
    
    @staticmethod
    def _get_from_cache(full_url):
        """캐시에서 데이터 가져오기 (만료 확인)"""
        if full_url not in URL._content_cache:
            return None
        
        cache_entry = URL._content_cache[full_url]
        timestamp = cache_entry['timestamp']
        max_age = cache_entry['max_age']
        
        # max_age가 없으면 영구 캐시
        if max_age is None:
            return cache_entry
        
        # max_age 확인
        elapsed = time.time() - timestamp
        if elapsed < max_age:
            return cache_entry
        else:
            # 만료됨 - 캐시에서 제거
            print(f"⏰ 캐시 만료: {full_url}")
            del URL._content_cache[full_url]
            return None
    
    @staticmethod
    def _save_to_cache(full_url, body, headers, max_age):
        """캐시에 데이터 저장"""
        URL._content_cache[full_url] = {
            'body': body,
            'headers': headers,
            'timestamp': time.time(),
            'max_age': max_age
        }
        print(f"💾 캐시 저장: {full_url} (max-age: {max_age if max_age else 'unlimited'})")
    
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
    
    def request(self, redirects: int = 5, redirect_log=None):
        """서버에 HTTP 요청을 보내고 응답을 받는 함수"""
        # redirect_log 초기화 (최상위 호출자가 None을 주면 여기서 생성하고
        # 최종 결과 직전에 로그를 출력함)
        created_local_log = False
        if redirect_log is None:
            redirect_log = []
            created_local_log = True

        # view-source인 경우 내부 URL의 본문을 가져와 그대로 반환
        if getattr(self, 'scheme', None) == 'view-source':
            # view-source:example.com의 inner는 example.com임 따라서 반드시 있어야함
            if not hasattr(self, 'inner'):
                raise ValueError('view-source missing inner URL')
            body = self.inner.request(redirects=redirects, redirect_log=redirect_log)
            return body
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
        
        # HTTP/HTTPS 요청에 대한 캐시 처리
        full_url = f"{self.scheme}://{self.host}{self.path}"
        
        # 캐시 가능한 리소스인지 확인
        is_cacheable = URL._is_cacheable(self.path)
        
        # 캐시 확인
        if is_cacheable:
            cached = URL._get_from_cache(full_url)
            if cached:
                print(f"⚡ 캐시에서 반환: {full_url}")
                return cached['body']
        
        # 1. 소켓 캐시 확인 및 재사용
        cache_key = f"{self.scheme}://{self.host}:{self.port}"
        s = URL._socket_cache.get(cache_key)
        
        # 기존 소켓이 없거나 닫혀있으면 새로 생성
        if s is None:
            print(f"🔌 새 연결 생성: {cache_key}")
            s = socket.socket(
                family=socket.AF_INET,      # IPv4 사용
                type=socket.SOCK_STREAM,    # TCP 연결
                proto=socket.IPPROTO_TCP,   # TCP 프로토콜
            )
            
            # 2. 서버에 연결
            try:
                # set a sensible timeout for network operations
                s.settimeout(10.0)
                s.connect((self.host, self.port))
            except Exception as e:
                # Ensure socket not left in cache on failure
                try:
                    s.close()
                except Exception:
                    pass
                raise Exception(f"Network error connecting to {self.host}:{self.port} - {e}")
            
            # 3. HTTPS인 경우 TLS로 암호화
            if self.scheme == "https":
                ctx = ssl.create_default_context()
                s = ctx.wrap_socket(s, server_hostname=self.host)
            
            # 캐시에 저장
            URL._socket_cache[cache_key] = s
        else:
            print(f"♻️  기존 연결 재사용: {cache_key}")
        
        # 4. HTTP 요청 메시지 작성 (HTTP/1.1 지원, Keep-Alive)
        # GET 메서드로 특정 경로의 리소스를 요청
        request = "GET {} HTTP/1.1\r\n".format(self.path)
        request += "Host: {}\r\n".format(self.host)
        # Keep-Alive 사용 (연결 유지)
        request += "Connection: keep-alive\r\n"
        request += "User-Agent: Mozilla/5.0 (CustomBrowser)\r\n"
        # 압축 지원을 서버에 알림
        request += "Accept-Encoding: gzip, deflate, br\r\n"
        request += "\r\n"  # 헤더의 끝을 표시
        
        # 5. 요청 전송 (문자열을 바이트로 변환)
        s.send(request.encode("utf8"))
        
        # 6. 응답 받기 (바이너리로 읽어야 압축 해제 가능)
        try:
            response = s.makefile("rb")
        except Exception as e:
            if cache_key in URL._socket_cache:
                del URL._socket_cache[cache_key]
            s.close()
            raise Exception(f"Failed to read response from {self.host}:{self.port} - {e}")
        
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
        
        # 9. HTTP 상태 확인 및 리다이렉트 처리
        status_code = int(status)
        # 리다이렉트(3xx) 처리: Location 헤더가 있으면 따라간다
        if 300 <= status_code < 400:
            if redirects <= 0:
                raise Exception('Too many redirects')
            loc = response_headers.get('location')
            if loc:
                # 절대/상대 URL 모두 처리
                base = f"{self.scheme}://{self.host}{self.path}"
                new_uri = urljoin(base, loc)
                # 로그에 현재->새 URL 기록
                redirect_log.append((base, new_uri))
                # 리다이렉트 시 소켓 캐시에서 제거하고 닫기
                if cache_key in URL._socket_cache:
                    del URL._socket_cache[cache_key]
                s.close()
                # Don't return immediately — call inner request and then
                # let this frame finish so it can print the redirect trace
                body = URL(new_uri).request(redirects=redirects-1, redirect_log=redirect_log)
                if created_local_log and redirect_log:
                    print("Redirect trace:")
                    for i, (src, dst) in enumerate(redirect_log, 1):
                        print(f" {i}. {src} -> {dst}")
                return body
            # Location이 없으면 계속 진행하여 에러 처리
        assert status_code == 200, "{}: {}".format(status_code, explanation)

        # 10. 본문(body) 읽기 - Transfer-Encoding: chunked 지원
        transfer_encoding = response_headers.get("transfer-encoding", "").lower()

        def read_chunked(rfile):
            chunks = []
            trailers = {}
            while True:
                # 청크 크기 라인 읽기
                line = rfile.readline().decode("ascii")
                if not line:
                    raise Exception("Unexpected EOF while reading chunk size")
                line = line.strip()
                # 사이즈 파싱 (세미콜론 뒤의 익스텐션 무시)
                size_str = line.split(';', 1)[0]
                try:
                    size = int(size_str, 16)
                except ValueError:
                    raise Exception(f"Invalid chunk size: {size_str}")
                if size == 0:
                    # 트레일러 헤더(있다면) 읽기: 빈 줄 전까지 헤더 라인들
                    while True:
                        trailer_line = rfile.readline().decode("utf8")
                        if trailer_line in ("\r\n", "\n", ""):
                            break
                        if ":" in trailer_line:
                            h, v = trailer_line.split(":", 1)
                            trailers[h.casefold()] = v.strip()
                    break
                data = rfile.read(size)
                chunks.append(data)
                # 청크 끝의 CRLF 소비
                rfile.read(2)
            return b"".join(chunks), trailers

        if "chunked" in transfer_encoding:
            body, trailers = read_chunked(response)
            # 트레일러 헤더를 응답 헤더에 병합 (기존 헤더를 덮어쓸 수 있음)
            for k, v in trailers.items():
                response_headers[k] = v
        else:
            # Content-Length 헤더를 사용하여 정확한 바이트 수만 읽기
            if "content-length" in response_headers:
                length = int(response_headers["content-length"])
                body = response.read(length)
                print(f"📦 Content-Length: {length} 바이트 읽음")
            else:
                # Content-Length가 없으면 소켓이 닫힐 때까지 읽음
                body = response.read()
                print("⚠️  Content-Length 없음 - 소켓 닫힘")
                # 캐시에서 제거하고 소켓 닫기
                if cache_key in URL._socket_cache:
                    del URL._socket_cache[cache_key]
                s.close()
        
        # Connection 헤더 확인하여 소켓 유지 여부 결정
        connection_header = response_headers.get("connection", "").lower()
        if "close" in connection_header:
            print("🔌 서버가 연결 종료 요청 - 소켓 닫기")
            if cache_key in URL._socket_cache:
                del URL._socket_cache[cache_key]
            s.close()
        else:
            print("✅ 연결 유지 (Keep-Alive)")
        
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
        
        # 14. 캐시 저장 (200 OK 응답이고 캐시 가능한 리소스인 경우)
        if status_code == 200 and is_cacheable:
            cache_control = response_headers.get('cache-control', '')
            no_store, max_age = URL._parse_cache_control(cache_control)
            
            if not no_store:
                # no-store가 아니면 캐시에 저장
                URL._save_to_cache(full_url, body, response_headers, max_age)
            else:
                print(f"🚫 캐시 금지 (no-store): {full_url}")

        # If we created the redirect_log in this call and there are entries,
        # print the redirect trace for non-view-source requests as well.
        if created_local_log and redirect_log:
            print("Redirect trace:")
            for i, (src, dst) in enumerate(redirect_log, 1):
                print(f" {i}. {src} -> {dst}")

        return body


# Ensure sockets in the socket cache are closed on program exit
def _close_socket_cache():
    for key, s in list(URL._socket_cache.items()):
        try:
            s.close()
        except Exception:
            pass
    URL._socket_cache.clear()

atexit.register(_close_socket_cache)



