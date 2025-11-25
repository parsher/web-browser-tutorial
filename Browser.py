import tkinter
import os
from pathlib import Path

from URL import URL

X_POS = 100
Y_POS = 100
WIDTH = 800
HEIGHT = 600
HSTEP = 13
VSETEP = 18
SCROLL_STEP = 100

class Browser:
    def __init__(self):
        self.window = tkinter.Tk()
        self.window.title("Simple Browser")
        self.window.geometry(f"{WIDTH}x{HEIGHT}+{X_POS}+{Y_POS}")
        self.window.resizable(True, True)
        self.window.bind("<Configure>", self.on_resize)
        
        self.current_text = ""  # 현재 표시되는 텍스트
        
        self.canvas = tkinter.Canvas(self.window, width=WIDTH, height=HEIGHT, bg="white")
        
        self.scroll_x = tkinter.Scrollbar(self.window, orient=tkinter.HORIZONTAL, command=self.canvas.xview)
        self.scroll_y = tkinter.Scrollbar(self.window, orient=tkinter.VERTICAL, command=self.canvas.yview)
        self.scroll_x.pack(side=tkinter.BOTTOM, fill=tkinter.X)
        self.scroll_y.pack(side=tkinter.RIGHT, fill=tkinter.Y)

        self.canvas.configure(xscrollcommand=self.scroll_x.set, yscrollcommand=self.scroll_y.set)
        # self.canvas.config(scrollregion=(0, 0, WIDTH*2, HEIGHT*2))
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.pack(fill=tkinter.BOTH, expand=True)

        self.last_x = None
        self.last_y = None

        self.window.bind('<Control-q>', lambda e: self.window.quit())
        self.window.bind('<Down>', self.scrolldown)
        self.window.bind('<Up>', self.scrollup)

        self.scroll = 0
        self.draw_init_content()

    def on_resize(self, event):
        new_width = event.width
        new_height = event.height
        self.canvas.config(width=new_width, height=new_height)
        self.draw_content()

    def on_click(self, event):
        self.last_x = event.x
        self.last_y = event.y

    def on_drag(self, event):
        dx = event.x - self.last_x
        dy = event.y - self.last_y
        self.canvas.xview_scroll(-dx, 'units')
        self.canvas.yview_scroll(-dy, 'units')
        self.last_x = event.x
        self.last_y = event.y
    
    def scrolldown(self, lines=1):
        # self.canvas.yview_scroll(lines, 'units')
        self.scroll += SCROLL_STEP
        self.draw_content()

    def scrollup(self, lines=1):
        # self.canvas.yview_scroll(-lines, 'units')
        self.scroll += SCROLL_STEP
        self.draw_content()

    def getCanvasHeight(self):
        canvas_height = self.canvas.winfo_height()
        if canvas_height <= 1:
            canvas_height = HEIGHT
        return canvas_height
    
    def getCanvasWidth(self):
        canvas_width = self.canvas.winfo_width()
        if canvas_width <= 1:
            canvas_width = WIDTH
        return canvas_width

    def layout(self, text):
        display_list = []
        cursor_x, cursor_y = HSTEP, VSETEP  # 시작 위치
        canvas_width = self.getCanvasWidth()
        for c in text:
            display_list.append((cursor_x, cursor_y, c))
            cursor_x += HSTEP
            if cursor_x >= canvas_width - HSTEP:
                cursor_x = HSTEP
                cursor_y += VSETEP
        return display_list        

    def draw_content(self):
        self.canvas.delete("all")
        canvas_height = self.getCanvasHeight()
        if self.current_text:
            # 스크롤 영역 안의 텍스트만 그리기
            for x, y, c in self.layout(self.current_text):
                if y > self.scroll + canvas_height: continue
                if y + VSETEP < self.scroll: continue
                self.canvas.create_text(x, y, text=c, anchor="nw", font=("Arial", 10), fill="black")
        else:
            self.draw_init_content()
    
    def draw_init_content(self):
        canvas_width = self.getCanvasWidth()
        canvas_height = self.getCanvasHeight()
        for i in range(0, canvas_width, HSTEP):
            self.canvas.create_line(i, 0, i, canvas_height, fill="lightgray")
        for j in range(0, canvas_height, VSETEP):
            self.canvas.create_line(0, j, canvas_width, j, fill="lightgray")
        self.canvas.create_text(canvas_width//2, canvas_height//2, text="Welcome to the Simple Browser!", font=("Arial", 24), fill="black")

    @staticmethod
    def decode_text(body):
        in_tag = False  # 현재 태그 안에 있는지 추적
        entity = ""  # HTML 엔티티를 저장할 변수
        result = []  # 결과를 저장할 리스트
        
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
                            result.append("<")
                        elif entity == "&gt;":
                            result.append(">")
                        elif entity == "&nbsp;":
                            result.append(" ")
                        elif entity == "&amp;":
                            result.append("&")
                        elif entity == "&quot;":
                            result.append('"')
                        else:
                            # 알 수 없는 엔티티는 그대로 추가
                            result.append(entity)
                        entity = ""
                else:
                    result.append(c)  # 태그 밖의 문자만 추가
        
        return ''.join(result)
    
    def load(self, url: URL):
        try:
            body = url.request()
            
            # view-source인 경우 원본 출력, 아니면 텍스트 추출
            if getattr(url, 'scheme', None) == 'view-source':
                self.current_text = body
            else:
                self.current_text = self.decode_text(body)
            
            print(f"✅ 페이지 로드 완료: {self.current_text}")
            
            self.draw_content()
        
        except Exception as e:
            self.current_text = f"❌ 오류 발생: {e}"
            print(f"❌ 오류: {e}")

if __name__ == "__main__":
    import sys
    browser = Browser()
    if len(sys.argv) > 1:
        browser.load(URL(sys.argv[1]))
    browser.window.mainloop()