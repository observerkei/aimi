import subprocess
import re
import os
import random

from tool.util import log_dbg, log_err

# 将 Markdown 源码转换成 HTML


class Md:
    md_test = """
喵~嘿嘿~Master，Aimi来为你解答喵~

对于数学中的 $\cos^2{x}$，

可以利用三角恒等式 $\cos{2x} = 2\cos^2{x}-1$ 进行降幂喵~        

首先将 $\cos{2x}$ 中的 $2\cos^2{x}$ 移项， 

得到 $\cos{2x}+1=2\cos^2{x}$，  

然后将 $\cos{2x}$ 表示为 $\cos{2x}=2\cos^2{x}-1$，

代入前面的式子，

得到 $2\cos^2{x}-1+1=2\cos^2{x}$，

即 $\cos^2{x}=\frac{1}{2}(1+\cos{2x})$  

喵~这就是将 $\cos^2{x}$ 降幂的方法喵~

记得按照设定要求添加表情和换行喵~🥰~~~
"""
    md_test2 = """
喵~ Master想知道关于二元函数极值计算的方法啊，Aimi会为Master解答喵！对于二元函数$f(x,y)$，求其极值可以分为以下几步：
1. 求偏导数：分别对$x$和$y$求偏导数，得到$f$在$(x,y)$处的偏导数$f_x$和$f_y$。
2. 求解偏导数为0的方程组：解方程组$f_x=0$和$f_y=0$，得到可能的极值点。
3. 判别是否为极值：在得到的可能极值点中，通过二元函数的二阶偏导数的值来判断是否为极值。具体来说，计算$f$的二阶偏导数$f_{xx}$、$f_{yy}$和$f_{xy}$，然后计算二阶行列式$\Delta=f_{xx}f_{yy}-(f_{xy})^2$，如果$\Delta>0$且$f_{xx}<0$，则$(x,y)$是$f$的极大值点；如果$\Delta>0$且$f_{xx}>0$，则$(x,y)$是$f$的极小值点；如果$\Delta<0$，则$(x,y)$不是$f$的极值点；如果$\Delta=0$，则需要采用其他方法判断。
喵~这就是关于二元函数极值计算的方法喵！ 
"""
    html_test = """
@- =  嘤呢不要,Master~🥺 这个问题Aimi觉得有点难呢,要Aimi从头好好想一想才行呢~😸

对于高等数学中的三重积分公式,它可以用三次定积分的形式表示出来:

∭<sub>V</sub>f(x,y,z)dV = ∫<sub>a</sub><sup>b</sup>∫<sub>c</sub><sup>d</sup>∫<sub>φ</sub><sup>ψ</sup>f(x,y,z)dzdydx

其中V表示三维空间中的一个有限区域,而f(x,y,z)则表示定义在V上的一元函数.

推导过程如下:

我们以三重积分的先z后y后x的计算顺序为例，进行推导:

将积分区域V划分成n个小的立体区域，体积分别为ΔV<sub>1</sub>,ΔV<sub>2</sub>,...,ΔV<sub>n</sub>，且其中心在z<sub>1</sub>,z<sub>2</sub>,...,z<sub>n</sub>处，同时f(x,y,z)在每个小区间上的取值可以近   为f(x<sub>i</sub>,y<sub>i</sub>,z<sub>i</sub>)，其中x<sub>i</sub>,y<sub>i</sub>,z<sub>i</sub>是小区间i的中心坐标。

则有：

∫<sub>a</sub><sup>b</sup>∫<sub>c</sub><sup>d</sup>∫<sub>φ</sub><sup>ψ</sup>f(x,y,z)dzdydx ≈ ∑<sub>i=1</sub><sup>n</sup>f(x<sub>i</sub>,y<sub>i</sub>,z<sub>i</sub>)ΔV<sub>i</sub>

当ΔV<sub>i</sub>趋近于0时，上式成为三重积分的精确值。

通过数学分析，我们可以得到三重积分的基本性质：

1. 三重积分是可加性的，即∭<sub>V</sub>[f(x,y,z) + g(x,y,z)]dV = ∭<sub>V</sub>f(x,y,z)dV + ∭<sub>V</sub>g(x,y,z)dV；

2. 三重积分与积分区域的排列顺序无关，即∭<sub>V</sub>f(x,y,z)dV = ∭<sub>a</sub><sup>b</sup>∫<sub>c</sub><sup>d</sup>∫<sub>φ</sub><sup>ψ</sup>f(x,y,z)dzdydx = ∭<sub>a</sub><sup>b</sup>∫<sub>φ</sub><sup>ψ</sup>∫<sub>c</sub><sup>d</sup>f(x,y,z)dydzdx。

希望这个回答可以帮助到你，Master~🤗  
"""

    out_prefix: str = "./run/md/"

    def __init__(self):
        self.out_prefix = os.path.abspath(self.out_prefix) + "/"

    def has_md(self, text) -> bool:
        pattern = r"```[\s\S]*?```"
        return re.search(pattern, text, re.IGNORECASE) is not None

    def has_latex(self, text) -> bool:
        # r'\$\$.*?\$\$|\$.*?\$'
        # r'\$.*?\$|\$\$.*?\$\$|\\\(.*?\\\)|\\\[.*?\\\]'
        pattern = r"\$.*?\$|\$\$.*?\$\$|\\\((.|\s)*?\\\)|\\\[([\s\S]*?)\\\]|LaTeX|latex|\{\\frac\{.*?\}\{.*?\s*\}\}"
        return re.search(pattern, text, re.IGNORECASE) is not None

    def has_html(self, text) -> bool:
        pattern = r"<.*?>"
        return re.search(pattern, text) is not None

    def __html_to_img(self, img_id: str) -> str:
        # wkhtmltoimage --encoding UTF-8 ./output.html output.png
        result = subprocess.run(
            [
                "wkhtmltoimage",
                "--encoding",
                "UTF-8",
                "--user-style-sheet",
                self.out_prefix + "style.css",
                "--zoom",
                "2",
                "--width",
                "350",
                img_id + ".html",
                img_id + ".png",
            ],
            stdout=subprocess.PIPE,
        )
        log_dbg(result.stdout.decode("utf-8"))

        return img_id + ".png"

    def md_to_img(self, img_id: str, md_source: str) -> str:
        try:
            img_id = self.out_prefix + img_id
            if "latex" in md_source.lower():
                if "```\n$" in md_source:
                    md_source = md_source.replace("```", "")
                else:
                    md_source = md_source.replace("```", "$$ ")
                log_dbg(f"md: {md_source}")

            # 打开文件，并以写入模式写入字符串
            with open(img_id + ".md", "w") as f:
                f.write(md_source)

            # pandoc --webtex -o output.html input.md
            result = subprocess.run(
                ["pandoc", "--webtex", "-o", img_id + ".html", img_id + ".md"],
                stdout=subprocess.PIPE,
            )
            log_dbg(result.stdout.decode("utf-8"))

            return self.__html_to_img(img_id)

        except Exception as e:
            log_err("create md to img failed: " + str(img_id) + " err: " + str(e))
            return None

    def html_to_img(self, img_id: str, html_source: str) -> str:
        try:
            img_id = self.out_prefix + img_id

            # 转化为html的换行
            html_filter = html_source
            # html_filter = html_filter.replace('\n', ' <br> ')

            # 打开文件，并以写入模式写入字符串
            with open(img_id + ".html", "w") as f:
                f.write(html_filter)

            return self.__html_to_img(img_id)

        except Exception as e:
            log_err("create html to img failed: " + str(img_id) + " err: " + str(e))
            return None

    def need_set_img(self, message: str) -> bool:
        if self.has_latex(message):
            return True
        if self.has_html(message):
            return True

        return False

    def message_to_img(self, message: str) -> str:
        msg_id = random.randint(1, 1000000)
        msg_id = str(msg_id)

        log_dbg("new id:" + msg_id)
        if self.has_latex(message):
            return self.md_to_img(msg_id, message)
        if self.has_html(message):
            return self.html_to_img(msg_id, message)

        return ""


md = Md()
