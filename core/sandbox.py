import sys

from tool.util import log_err, log_dbg


class Sandbox:
    # 容器类型
    # system:       不安全用法
    # proot-distro  termux
    # docker
    model: str = "system"
    sandbox_file: str = "./run/sandbox.py"

    def __init__(self):
        pass

    def write_code(code: str):
        try:
            file = open(Sandbox.sandbox_file, "w", encoding="utf-8")
            file.write(str(code))
            file.close()
            log_dbg("write code done")
            return True
        except Exception as e:
            log_err(f"fail to write code: {str(e)}")
        return False

    def run_code():
        import subprocess

        result = ""
        try:
            result = subprocess.run(
                [sys.executable, Sandbox.sandbox_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if result.returncode != 0:
                return result.stderr.decode("utf-8")
            retval = result.stdout.decode("utf-8")
            if not len(retval):
                "python 执行完成, 但是没有打印任何输出值. 请把你想要的结果打印出来."
            return retval
        except Exception as e:
            log_err(f"fail to exec code: {str(e)}")
            result = str(e)
        return f"system error: exec code failed:\n{result}"
