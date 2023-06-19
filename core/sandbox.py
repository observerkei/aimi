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
        max_return_len = 2048
        run = {
            "returncode": "-1",
            "stdout": "",
            "stderr": ""
        }

        result = ""
        try:
            result = subprocess.run(
                [sys.executable, Sandbox.sandbox_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if result.returncode != 0:
                return result.stderr.decode("utf-8")
            
            run_returncode = str(result.returncode)
            run_stdout = str(result.stdout.decode("utf-8"))
            run_stderr = str(result.stderr.decode("utf-8"))
            if len(run_stdout) > max_return_len:
                log_err(f"run stdout over limit: {str(len(run_stdout))}")
                run_stdout = run_stdout[max_return_len:]
            if len(run_stderr) > max_return_len:
                log_err(f"run stderr over limit: {str(len(run_stderr))}")
                run_stderr = run_stderr[max_return_len:]
            run = {
                "returncode": run_returncode,
                "stdout": run_stdout,
                "stderr": run_stderr
            }
            return run
        except Exception as e:
            log_err(f"fail to exec code: {str(e)}")
            run["stderr"] = str(e)
        return run
